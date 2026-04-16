import pytest
from cryptography.fernet import Fernet
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.crypto.wallet import CryptoWalletManager


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


@pytest.fixture
def encryption_key():
    """Generate test encryption key"""
    return Fernet.generate_key().decode()


def test_initialize_master_keys(db_manager, encryption_key):
    """Test master key initialization"""
    wallet_manager = CryptoWalletManager(db_manager, encryption_key)
    
    # Should create keys for all crypto types
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crypto_master_keys")
        keys = cursor.fetchall()
    
    assert len(keys) == 4  # btc, eth, usdt, usdc
    
    # Get crypto types
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT crypto_type FROM crypto_master_keys")
        crypto_types = [row[0] for row in cursor.fetchall()]
    
    assert 'btc' in crypto_types
    assert 'eth' in crypto_types
    assert 'usdt' in crypto_types
    assert 'usdc' in crypto_types


def test_derive_bitcoin_address(db_manager, encryption_key):
    """Test Bitcoin address derivation"""
    wallet_manager = CryptoWalletManager(db_manager, encryption_key)
    
    address_info = wallet_manager.derive_address('btc', 0)
    
    assert address_info['address'].startswith('bc1')
    assert address_info['derivation_path'] == "m/44'/0'/0'/0/0"
    assert address_info['derivation_index'] == 0


def test_derive_ethereum_address(db_manager, encryption_key):
    """Test Ethereum address derivation"""
    wallet_manager = CryptoWalletManager(db_manager, encryption_key)
    
    address_info = wallet_manager.derive_address('eth', 0)
    
    assert address_info['address'].startswith('0x')
    assert len(address_info['address']) == 42
    assert address_info['derivation_path'] == "m/44'/60'/0'/0/0"


@pytest.mark.anyio
async def test_get_or_create_user_address(db_manager, encryption_key):
    """Test user address creation"""
    wallet_manager = CryptoWalletManager(db_manager, encryption_key)
    
    # Create address for user 1
    address1 = await wallet_manager.get_or_create_user_address(1, 'btc')
    assert address1.startswith('bc1')
    
    # Getting again should return same address
    address2 = await wallet_manager.get_or_create_user_address(1, 'btc')
    assert address1 == address2
    
    # Different user should get different address
    address3 = await wallet_manager.get_or_create_user_address(2, 'btc')
    assert address3 != address1
