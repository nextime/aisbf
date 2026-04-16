import pytest
from datetime import datetime, timedelta
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.subscription.retry import PaymentRetryProcessor
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
    
    # Create tiers using database manager
    free_tier_id = db.create_tier(
        name='Free',
        description='Free tier',
        price_monthly=0,
        price_yearly=0
    )
    pro_tier_id = db.create_tier(
        name='Pro',
        description='Pro tier',
        price_monthly=10.00,
        price_yearly=100.00
    )
    
    # Create test user
    user_id = db.create_user(email='test@example.com', username='testuser', password_hash='hash')
    
    # Update user tier to Pro and add test data
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE users SET tier_id = {pro_tier_id} WHERE id = {user_id}")
        cursor.execute(f"""
            INSERT INTO payment_methods (id, user_id, type, identifier, is_default, is_active)
            VALUES (1, {user_id}, 'crypto', 'btc_wallet', 1, 1)
        """)
        cursor.execute(f"""
            INSERT INTO subscriptions (id, user_id, tier_id, payment_method_id, 
                                      billing_cycle, status, current_period_start, current_period_end)
            VALUES (1, {user_id}, {pro_tier_id}, 1, 'monthly', 'active', 
                    datetime('now', '-30 days'), datetime('now', '-1 day'))
        """)
        cursor.execute(f"""
            INSERT INTO user_crypto_wallets (user_id, crypto_type, balance_crypto, balance_fiat)
            VALUES ({user_id}, 'btc', 0.001, 50.00)
        """)
        conn.commit()
    
    return db


@pytest.mark.anyio
async def test_crypto_retry_with_sufficient_balance(db_manager):
    """Test crypto payment retry when wallet has sufficient balance"""
    # Mock subscription manager
    class MockSubscriptionManager:
        pass
    
    processor = PaymentRetryProcessor(db_manager, MockSubscriptionManager())
    
    # Add retry to queue
    await processor.add_to_retry_queue(
        subscription_id=1,
        user_id=1,
        payment_method_type='crypto',
        amount=10.00
    )
    
    # Process retries
    result = await processor.process_retries()
    
    assert result['processed'] == 1
    assert result['successful'] == 1
    
    # Check wallet balance was deducted
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance_fiat FROM user_crypto_wallets WHERE user_id = 1")
        balance = cursor.fetchone()[0]
    
    assert float(balance) == 40.00  # 50 - 10


@pytest.mark.anyio
async def test_crypto_retry_insufficient_balance(db_manager):
    """Test crypto payment retry when wallet has insufficient balance"""
    class MockSubscriptionManager:
        pass
    
    processor = PaymentRetryProcessor(db_manager, MockSubscriptionManager())
    
    # Add retry to queue with amount > balance
    await processor.add_to_retry_queue(
        subscription_id=1,
        user_id=1,
        payment_method_type='crypto',
        amount=100.00  # More than wallet balance
    )
    
    # Process retries
    result = await processor.process_retries()
    
    assert result['processed'] == 1
    assert result['successful'] == 0  # Should skip due to insufficient balance


@pytest.mark.anyio
async def test_fiat_retry_daily_schedule(db_manager):
    """Test fiat payment retry uses daily schedule"""
    class MockSubscriptionManager:
        pass
    
    processor = PaymentRetryProcessor(db_manager, MockSubscriptionManager())
    
    # Add fiat retry to queue
    await processor.add_to_retry_queue(
        subscription_id=1,
        user_id=1,
        payment_method_type='stripe',
        amount=10.00
    )
    
    # Check next_retry_at is ~24 hours from now
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT next_retry_at FROM payment_retry_queue WHERE subscription_id = 1")
        next_retry = cursor.fetchone()[0]
    
    next_retry_dt = datetime.fromisoformat(next_retry)
    expected = datetime.utcnow() + timedelta(days=1)
    
    # Allow 5 second tolerance
    assert abs((next_retry_dt - expected).total_seconds()) < 5


@pytest.mark.anyio
async def test_max_retries_downgrades_to_free(db_manager):
    """Test that max retry attempts downgrades user to free tier"""
    class MockSubscriptionManager:
        pass
    
    processor = PaymentRetryProcessor(db_manager, MockSubscriptionManager())
    
    # Get free tier ID
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM account_tiers WHERE name = 'Free' LIMIT 1")
        free_tier_id = cursor.fetchone()[0]
    
    # Add retry with max attempts already reached
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payment_retry_queue
            (subscription_id, user_id, payment_method_type, amount, 
             attempt_count, max_attempts, next_retry_at, status)
            VALUES (1, 1, 'crypto', 100.00, 2, 3, datetime('now'), 'pending')
        """)
        conn.commit()
    
    # Process retries (will fail due to insufficient balance, hitting max attempts)
    result = await processor.process_retries()
    
    # Check user was downgraded to free tier
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier_id FROM users WHERE id = 1")
        tier_id = cursor.fetchone()[0]
    
    assert tier_id == free_tier_id  # Free tier
    
    # Check subscription was cancelled
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM subscriptions WHERE id = 1")
        status = cursor.fetchone()[0]
    
    assert status == 'cancelled'


@pytest.mark.anyio
async def test_retry_increments_attempt_count(db_manager):
    """Test that failed retry increments attempt count"""
    class MockSubscriptionManager:
        pass
    
    processor = PaymentRetryProcessor(db_manager, MockSubscriptionManager())
    
    # Add retry to queue with future next_retry_at so it gets processed
    now = datetime.utcnow().isoformat()
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            INSERT INTO payment_retry_queue
            (subscription_id, user_id, payment_method_type, amount, 
             attempt_count, max_attempts, next_retry_at, status)
            VALUES (1, 1, 'crypto', 100.00, 0, 3, '{now}', 'pending')
        """)
        conn.commit()
    
    # Process retries (will fail due to insufficient balance)
    await processor.process_retries()
    
    # Check attempt count was incremented
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT attempt_count FROM payment_retry_queue WHERE subscription_id = 1")
        attempt_count = cursor.fetchone()[0]
    
    assert attempt_count == 1


@pytest.mark.anyio
async def test_successful_retry_marks_completed(db_manager):
    """Test that successful retry marks entry as completed"""
    class MockSubscriptionManager:
        pass
    
    processor = PaymentRetryProcessor(db_manager, MockSubscriptionManager())
    
    # Add retry to queue with sufficient balance
    await processor.add_to_retry_queue(
        subscription_id=1,
        user_id=1,
        payment_method_type='crypto',
        amount=10.00
    )
    
    # Process retries
    await processor.process_retries()
    
    # Check retry was marked as completed
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM payment_retry_queue WHERE subscription_id = 1")
        status = cursor.fetchone()[0]
    
    assert status == 'completed'
