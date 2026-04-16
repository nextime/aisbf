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
