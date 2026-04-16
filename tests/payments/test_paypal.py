import pytest
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.fiat.paypal_handler import PayPalPaymentHandler


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


def test_paypal_handler_initialization(db_manager):
    """Test PayPal handler initialization"""
    config = {'base_url': 'http://localhost:17765'}
    handler = PayPalPaymentHandler(db_manager, config)
    
    assert handler is not None
