import pytest
from datetime import datetime
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.crypto.monitor import BlockchainMonitor
from aisbf.payments.crypto.pricing import CryptoPriceService


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
    return db


@pytest.mark.anyio
async def test_process_transaction(db_manager):
    """Test transaction processing"""
    config = {'currency_code': 'USD', 'btc_confirmations': 3}
    monitor = BlockchainMonitor(db_manager, config)
    
    # Create user and address
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_crypto_addresses 
            (user_id, crypto_type, address, derivation_path, derivation_index)
            VALUES (1, 'btc', 'bc1qtest', 'm/44/0/0/0/0', 0)
        """)
        cursor.execute("""
            INSERT INTO user_crypto_wallets
            (user_id, crypto_type, balance_crypto, balance_fiat)
            VALUES (1, 'btc', 0, 0)
        """)
        conn.commit()
    
    # Process transaction
    await monitor.process_transaction(
        user_id=1,
        crypto_type='btc',
        tx_hash='test_tx_hash',
        from_address='bc1qfrom',
        to_address='bc1qtest',
        amount=0.001,
        confirmations=3
    )
    
    # Check transaction was recorded
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM crypto_transactions WHERE tx_hash = ?",
            ('test_tx_hash',)
        )
        tx = cursor.fetchone()
    
    assert tx is not None
    assert tx[9] == 'confirmed'  # status column
    assert float(tx[5]) == 0.001  # amount_crypto column
