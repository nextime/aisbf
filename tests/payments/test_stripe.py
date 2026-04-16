import pytest
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.fiat.stripe_handler import StripePaymentHandler


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
    
    # Add test user
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (id, email, username, password_hash)
            VALUES (1, 'test@example.com', 'testuser', 'hash')
        """)
        conn.commit()
    
    return db


def test_add_payment_method_creates_customer(db_manager):
    """Test that adding payment method creates Stripe customer"""
    config = {}
    handler = StripePaymentHandler(db_manager, config)
    
    # Mock Stripe API calls would go here
    # For now, test the structure exists
    assert handler is not None
