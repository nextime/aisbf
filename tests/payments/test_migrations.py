import pytest
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations


def test_migrations_create_all_tables(tmp_path):
    """Test that migrations create all required tables"""
    db_path = tmp_path / "test.db"
    db_config = {
        'type': 'sqlite',
        'sqlite_path': str(db_path)
    }
    
    db = DatabaseManager(db_config)
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Check that key tables exist
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table'
        """)
        tables = cursor.fetchall()
    
    table_names = [t[0] for t in tables]
    
    assert 'crypto_master_keys' in table_names
    assert 'user_crypto_addresses' in table_names
    assert 'user_crypto_wallets' in table_names
    assert 'crypto_transactions' in table_names
    assert 'payment_retry_queue' in table_names
    assert 'subscriptions' in table_names
    assert 'job_locks' in table_names
    assert 'crypto_price_sources' in table_names
    assert 'email_notification_settings' in table_names


def test_migrations_insert_default_data(tmp_path):
    """Test that default data is inserted"""
    db_path = tmp_path / "test.db"
    db_config = {
        'type': 'sqlite',
        'sqlite_path': str(db_path)
    }
    
    db = DatabaseManager(db_config)
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Check price sources
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crypto_price_sources")
        sources = cursor.fetchall()
        assert len(sources) >= 3
        
        # Check consolidation settings
        cursor.execute("SELECT * FROM crypto_consolidation_settings")
        settings = cursor.fetchall()
        assert len(settings) == 4
        
        # Check email notification settings
        cursor.execute("SELECT * FROM email_notification_settings")
        notifications = cursor.fetchall()
        assert len(notifications) >= 9
