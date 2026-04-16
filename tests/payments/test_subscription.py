import pytest
from datetime import datetime, timedelta
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.subscription.manager import SubscriptionManager


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
    
    # Check existing tiers and add test user
    with db._get_connection() as conn:
        cursor = conn.cursor()
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
        
        # Add test user
        cursor.execute("""
            INSERT INTO users (id, email, username, password_hash, tier_id)
            VALUES (1, 'test@example.com', 'testuser', 'hash', ?)
        """, (free_tier_id,))
        conn.commit()
    
    # Add payment method
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (1, 1, 'card', 'pm_test_stripe', 1, 1)
        """)
        conn.commit()
    
    # Store pro_tier_id for test access
    db._test_pro_tier_id = pro_tier_id
    
    return db


@pytest.mark.anyio
async def test_create_subscription(db_manager):
    """Test subscription creation"""
    # Mock handlers
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None,  # PayPal handler
        None,  # Crypto wallet manager
        None   # Price service
    )
    
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    
    print(f"Result: {result}")
    assert result['success'] == True, f"Expected success but got: {result}"
    assert 'subscription_id' in result


@pytest.mark.anyio
async def test_upgrade_subscription_with_proration(db_manager):
    """Test subscription upgrade with prorated charges"""
    # Mock handlers
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None,  # PayPal handler
        None,  # Crypto wallet manager
        None   # Price service
    )
    
    # Create initial subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Add Premium tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO account_tiers (name, price_monthly, price_yearly, is_default)
            VALUES ('Premium', 20.00, 200.00, 0)
        """)
        conn.commit()
        premium_tier_id = cursor.lastrowid
    
    # Upgrade to Premium
    result = await manager.upgrade_subscription(user_id=1, new_tier_id=premium_tier_id)
    
    assert result['success'] == True
    assert 'charged_amount' in result
    # Should charge less than full $20 due to proration
    assert result['charged_amount'] < 20.00
    assert result['charged_amount'] > 0
    
    # Verify subscription was updated
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tier_id FROM subscriptions WHERE user_id = 1 AND status = 'active'
        """)
        row = cursor.fetchone()
        assert row[0] == premium_tier_id
    
    # Verify user tier was updated
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier_id FROM users WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == premium_tier_id


@pytest.mark.anyio
async def test_upgrade_subscription_proration_calculation(db_manager):
    """Test that proration calculation is accurate"""
    from datetime import datetime, timedelta
    
    # Mock handlers
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create initial subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Manually set subscription to be halfway through billing period
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).replace(tzinfo=None)
        period_start = now - timedelta(days=15)
        period_end = now + timedelta(days=15)
        
        cursor.execute("""
            UPDATE subscriptions 
            SET current_period_start = ?, current_period_end = ?
            WHERE user_id = 1
        """, (period_start, period_end))
        conn.commit()
    
    # Add Premium tier ($20/month)
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO account_tiers (name, price_monthly, price_yearly, is_default)
            VALUES ('Premium', 20.00, 200.00, 0)
        """)
        conn.commit()
        premium_tier_id = cursor.lastrowid
    
    # Upgrade to Premium
    result = await manager.upgrade_subscription(user_id=1, new_tier_id=premium_tier_id)
    
    assert result['success'] == True
    # At halfway point: new_price - (old_price * 0.5) = 20 - (10 * 0.5) = 15
    # Allow small floating point variance
    assert 14.9 < result['charged_amount'] < 15.1


@pytest.mark.anyio
async def test_upgrade_subscription_no_active_subscription(db_manager):
    """Test upgrade fails when no active subscription exists"""
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Try to upgrade without creating subscription first
    result = await manager.upgrade_subscription(user_id=1, new_tier_id=2)
    
    assert result['success'] == False
    assert 'No active subscription' in result['error']


@pytest.mark.anyio
async def test_upgrade_subscription_invalid_tier(db_manager):
    """Test upgrade fails with invalid tier ID"""
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create initial subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Try to upgrade to non-existent tier
    result = await manager.upgrade_subscription(user_id=1, new_tier_id=99999)
    
    assert result['success'] == False
    assert 'Invalid tier' in result['error']


@pytest.mark.anyio
async def test_downgrade_subscription(db_manager):
    """Test subscription downgrade scheduled at period end"""
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create Premium tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO account_tiers (name, price_monthly, price_yearly, is_default)
            VALUES ('Premium', 20.00, 200.00, 0)
        """)
        conn.commit()
        premium_tier_id = cursor.lastrowid
    
    # Create subscription at Premium tier
    result = await manager.create_subscription(
        user_id=1,
        tier_id=premium_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Downgrade to Pro tier (scheduled at period end)
    result = await manager.downgrade_subscription(user_id=1, new_tier_id=db_manager._test_pro_tier_id)
    
    assert result['success'] == True
    assert 'downgrade_date' in result
    
    # Verify pending_tier_id is set
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tier_id, pending_tier_id FROM subscriptions 
            WHERE user_id = 1 AND status = 'active'
        """)
        row = cursor.fetchone()
        assert row[0] == premium_tier_id  # Still on Premium
        assert row[1] == db_manager._test_pro_tier_id  # Downgrade scheduled
    
    # Verify user still has Premium tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier_id FROM users WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == premium_tier_id


@pytest.mark.anyio
async def test_downgrade_subscription_no_charge(db_manager):
    """Test downgrade does not charge immediately"""
    charge_called = False
    
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            nonlocal charge_called
            charge_called = True
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create Premium tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO account_tiers (name, price_monthly, price_yearly, is_default)
            VALUES ('Premium', 20.00, 200.00, 0)
        """)
        conn.commit()
        premium_tier_id = cursor.lastrowid
    
    # Create subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=premium_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Reset charge flag
    charge_called = False
    
    # Downgrade
    result = await manager.downgrade_subscription(user_id=1, new_tier_id=db_manager._test_pro_tier_id)
    
    assert result['success'] == True
    assert charge_called == False  # No charge should occur


@pytest.mark.anyio
async def test_downgrade_subscription_no_active_subscription(db_manager):
    """Test downgrade fails when no active subscription exists"""
    manager = SubscriptionManager(db_manager, None, None, None, None)
    
    result = await manager.downgrade_subscription(user_id=1, new_tier_id=db_manager._test_pro_tier_id)
    
    assert result['success'] == False
    assert 'No active subscription' in result['error']


@pytest.mark.anyio
async def test_downgrade_subscription_invalid_tier(db_manager):
    """Test downgrade fails with invalid tier ID"""
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Try to downgrade to non-existent tier
    result = await manager.downgrade_subscription(user_id=1, new_tier_id=99999)
    
    assert result['success'] == False
    assert 'Invalid tier' in result['error']


@pytest.mark.anyio
async def test_cancel_subscription(db_manager):
    """Test subscription cancellation at period end"""
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Cancel subscription
    result = await manager.cancel_subscription(user_id=1)
    
    assert result['success'] == True
    assert 'cancellation_date' in result
    
    # Verify cancel_at_period_end is set
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, cancel_at_period_end FROM subscriptions 
            WHERE user_id = 1
        """)
        row = cursor.fetchone()
        assert row[0] == 'active'  # Still active
        assert row[1] == 1  # Cancel scheduled
    
    # Verify user still has Pro tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier_id FROM users WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == db_manager._test_pro_tier_id


@pytest.mark.anyio
async def test_cancel_subscription_no_refund(db_manager):
    """Test cancellation does not issue refund"""
    refund_called = False
    
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
        
        async def refund_payment(self, transaction_id, amount):
            nonlocal refund_called
            refund_called = True
            return {'success': True}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Create subscription
    result = await manager.create_subscription(
        user_id=1,
        tier_id=db_manager._test_pro_tier_id,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    assert result['success'] == True
    
    # Cancel subscription
    result = await manager.cancel_subscription(user_id=1)
    
    assert result['success'] == True
    assert refund_called == False  # No refund should occur


@pytest.mark.anyio
async def test_cancel_subscription_no_active_subscription(db_manager):
    """Test cancellation fails when no active subscription exists"""
    manager = SubscriptionManager(db_manager, None, None, None, None)
    
    result = await manager.cancel_subscription(user_id=1)
    
    assert result['success'] == False
    assert 'No active subscription' in result['error']
