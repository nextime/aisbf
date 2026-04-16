import pytest
from datetime import datetime, timedelta
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.subscription.renewal import RenewalProcessor


@pytest.fixture
def db_manager(tmp_path):
    """Create test database"""
    db_path = tmp_path / "test.db"
    db_config = {
        'type': 'sqlite',
        'sqlite_path': str(db_path)
    }
    db = DatabaseManager(db_config)
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Setup test data
    with db._get_connection() as conn:
        cursor = conn.cursor()
        
        # Get tier IDs
        cursor.execute("SELECT id FROM account_tiers WHERE name = 'Free'")
        free_tier = cursor.fetchone()
        free_tier_id = free_tier[0] if free_tier else 1
        
        cursor.execute("SELECT id FROM account_tiers WHERE name = 'Pro'")
        pro_tier = cursor.fetchone()
        
        # Add Pro tier if it doesn't exist
        if not pro_tier:
            cursor.execute("""
                INSERT INTO account_tiers (name, price_monthly, price_yearly, is_default)
                VALUES ('Pro', 10.00, 100.00, 0)
            """)
            conn.commit()
            pro_tier_id = cursor.lastrowid
        else:
            pro_tier_id = pro_tier[0]
        
        # Add Premium tier
        cursor.execute("""
            INSERT INTO account_tiers (name, price_monthly, price_yearly, is_default)
            VALUES ('Premium', 20.00, 200.00, 0)
        """)
        conn.commit()
        premium_tier_id = cursor.lastrowid
        
        # Add test users
        cursor.execute("""
            INSERT INTO users (id, email, username, password_hash, tier_id)
            VALUES (1, 'user1@example.com', 'user1', 'hash', ?)
        """, (pro_tier_id,))
        
        cursor.execute("""
            INSERT INTO users (id, email, username, password_hash, tier_id)
            VALUES (2, 'user2@example.com', 'user2', 'hash', ?)
        """, (pro_tier_id,))
        
        cursor.execute("""
            INSERT INTO users (id, email, username, password_hash, tier_id)
            VALUES (3, 'user3@example.com', 'user3', 'hash', ?)
        """, (premium_tier_id,))
        
        conn.commit()
        
        # Store tier IDs for test access
        db._test_free_tier_id = free_tier_id
        db._test_pro_tier_id = pro_tier_id
        db._test_premium_tier_id = premium_tier_id
    
    return db


@pytest.fixture
def renewal_processor(db_manager):
    """Create renewal processor with mock handlers"""
    class MockStripeHandler:
        def __init__(self):
            self.should_fail = False
        
        async def charge_subscription(self, subscription_id, amount):
            if self.should_fail:
                return {'success': False, 'error': 'Payment failed'}
            return {'success': True, 'transaction_id': 'test_tx'}
    
    stripe_handler = MockStripeHandler()
    processor = RenewalProcessor(
        db_manager,
        stripe_handler,
        None,  # PayPal handler
        None,  # Crypto wallet manager
        None   # Price service
    )
    processor._stripe_handler = stripe_handler  # Store for test access
    return processor


@pytest.mark.anyio
async def test_process_renewals_extends_period_for_due_subscription(db_manager, renewal_processor):
    """Test that renewal extends the billing period for subscriptions that are due"""
    # Create subscription with period ending now
    now = datetime.now()
    period_start = now - timedelta(days=30)
    period_end = now  # Due for renewal
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        # Add payment method
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (1, 1, 'card', 'pm_test', 1, 1)
        """)
        
        # Add subscription
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end)
            VALUES (1, ?, 1, 'active', 'monthly', ?, ?)
        """, (db_manager._test_pro_tier_id, period_start, period_end))
        conn.commit()
    
    # Process renewals
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    assert result['successful'] == 1
    assert result['failed'] == 0
    
    # Verify period was extended
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT current_period_start, current_period_end, status
            FROM subscriptions WHERE user_id = 1
        """)
        row = cursor.fetchone()
        
        new_start = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
        new_end = datetime.fromisoformat(row[1]) if isinstance(row[1], str) else row[1]
        status = row[2]
        
        # Period should be extended by 30 days
        assert status == 'active'
        assert new_start == period_end  # New start = old end
        assert (new_end - new_start).days == 30


@pytest.mark.anyio
async def test_process_renewals_yearly_subscription(db_manager, renewal_processor):
    """Test renewal extends yearly subscription by 365 days"""
    now = datetime.now()
    period_start = now - timedelta(days=365)
    period_end = now
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (2, 2, 'card', 'pm_test2', 1, 1)
        """)
        
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end)
            VALUES (2, ?, 2, 'active', 'yearly', ?, ?)
        """, (db_manager._test_pro_tier_id, period_start, period_end))
        conn.commit()
    
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    
    # Verify period extended by 365 days
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT current_period_start, current_period_end
            FROM subscriptions WHERE user_id = 2
        """)
        row = cursor.fetchone()
        
        new_start = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
        new_end = datetime.fromisoformat(row[1]) if isinstance(row[1], str) else row[1]
        
        assert (new_end - new_start).days == 365


@pytest.mark.anyio
async def test_process_renewals_applies_pending_downgrade(db_manager, renewal_processor):
    """Test that renewal applies pending tier changes (downgrades)"""
    now = datetime.now()
    period_start = now - timedelta(days=30)
    period_end = now
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (3, 3, 'card', 'pm_test3', 1, 1)
        """)
        
        # Create subscription with pending downgrade
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end, pending_tier_id)
            VALUES (3, ?, 3, 'active', 'monthly', ?, ?, ?)
        """, (db_manager._test_premium_tier_id, period_start, period_end, 
              db_manager._test_pro_tier_id))
        conn.commit()
    
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    
    # Verify tier was downgraded and pending_tier_id cleared
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tier_id, pending_tier_id FROM subscriptions WHERE user_id = 3
        """)
        row = cursor.fetchone()
        
        assert row[0] == db_manager._test_pro_tier_id  # Downgraded
        assert row[1] is None  # pending_tier_id cleared
    
    # Verify user tier was updated
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier_id FROM users WHERE id = 3")
        user_tier = cursor.fetchone()[0]
        assert user_tier == db_manager._test_pro_tier_id


@pytest.mark.anyio
async def test_process_renewals_handles_payment_failure(db_manager, renewal_processor):
    """Test that failed payments are handled gracefully"""
    now = datetime.now()
    period_end = now
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (4, 1, 'card', 'pm_fail', 1, 1)
        """)
        
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end)
            VALUES (1, ?, 4, 'active', 'monthly', ?, ?)
        """, (db_manager._test_pro_tier_id, now - timedelta(days=30), period_end))
        conn.commit()
    
    # Make payment fail
    renewal_processor._stripe_handler.should_fail = True
    
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    assert result['successful'] == 0
    assert result['failed'] == 1
    
    # Subscription should still be active (not cancelled immediately)
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM subscriptions WHERE user_id = 1")
        status = cursor.fetchone()[0]
        assert status == 'active'


@pytest.mark.anyio
async def test_process_renewals_cancels_subscription_with_cancel_flag(db_manager, renewal_processor):
    """Test that subscriptions with cancel_at_period_end are cancelled"""
    now = datetime.now()
    period_end = now
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (5, 2, 'card', 'pm_test5', 1, 1)
        """)
        
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end, cancel_at_period_end)
            VALUES (2, ?, 5, 'active', 'monthly', ?, ?, 1)
        """, (db_manager._test_pro_tier_id, now - timedelta(days=30), period_end))
        conn.commit()
    
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    
    # Subscription should be cancelled
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM subscriptions WHERE user_id = 2")
        status = cursor.fetchone()[0]
        assert status == 'cancelled'
    
    # User should be downgraded to free tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier_id FROM users WHERE id = 2")
        tier_id = cursor.fetchone()[0]
        assert tier_id == db_manager._test_free_tier_id


@pytest.mark.anyio
async def test_process_renewals_skips_future_subscriptions(db_manager, renewal_processor):
    """Test that subscriptions not yet due are skipped"""
    now = datetime.now()
    future_end = now + timedelta(days=10)  # Not due yet
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (6, 1, 'card', 'pm_test6', 1, 1)
        """)
        
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end)
            VALUES (1, ?, 6, 'active', 'monthly', ?, ?)
        """, (db_manager._test_pro_tier_id, now, future_end))
        conn.commit()
    
    result = await renewal_processor.process_renewals()
    
    # Should process 0 subscriptions
    assert result['success'] == True
    assert result['processed'] == 0


@pytest.mark.anyio
async def test_process_renewals_crypto_payment(db_manager, renewal_processor):
    """Test renewal with crypto wallet payment"""
    now = datetime.now()
    period_end = now
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        # Add crypto wallet with sufficient balance
        cursor.execute("""
            INSERT INTO user_crypto_wallets (user_id, crypto_type, balance_crypto, balance_fiat)
            VALUES (1, 'BTC', 0.001, 50.00)
        """)
        
        # Add crypto payment method (no crypto_type column in payment_methods)
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (7, 1, 'crypto', 'btc_wallet', 1, 1)
        """)
        
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end)
            VALUES (1, ?, 7, 'active', 'monthly', ?, ?)
        """, (db_manager._test_pro_tier_id, now - timedelta(days=30), period_end))
        conn.commit()
    
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    assert result['successful'] == 1
    
    # Verify wallet balance was deducted
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT balance_fiat FROM user_crypto_wallets 
            WHERE user_id = 1 AND crypto_type = 'BTC'
        """)
        balance = cursor.fetchone()[0]
        assert balance == 40.00  # 50 - 10 (Pro monthly price)


@pytest.mark.anyio
async def test_process_renewals_crypto_insufficient_balance(db_manager, renewal_processor):
    """Test renewal fails when crypto wallet has insufficient balance"""
    now = datetime.now()
    period_end = now
    
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        
        # Add crypto wallet with insufficient balance
        cursor.execute("""
            INSERT INTO user_crypto_wallets (user_id, crypto_type, balance_crypto, balance_fiat)
            VALUES (2, 'ETH', 0.001, 5.00)
        """)
        
        # Add crypto payment method (no crypto_type column in payment_methods)
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (8, 2, 'crypto', 'eth_wallet', 1, 1)
        """)
        
        cursor.execute("""
            INSERT INTO subscriptions 
            (user_id, tier_id, payment_method_id, status, billing_cycle,
             current_period_start, current_period_end)
            VALUES (2, ?, 8, 'active', 'monthly', ?, ?)
        """, (db_manager._test_pro_tier_id, now - timedelta(days=30), period_end))
        conn.commit()
    
    result = await renewal_processor.process_renewals()
    
    assert result['success'] == True
    assert result['processed'] == 1
    assert result['failed'] == 1
    
    # Wallet balance should be unchanged
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT balance_fiat FROM user_crypto_wallets 
            WHERE user_id = 2 AND crypto_type = 'ETH'
        """)
        balance = cursor.fetchone()[0]
        assert balance == 5.00  # Unchanged
