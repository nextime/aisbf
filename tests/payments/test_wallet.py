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


@pytest.mark.anyio
async def test_wallet_manager_get_wallet_creates_new_wallet():
    """Test that WalletManager get_wallet creates a new wallet when none exists"""
    from unittest.mock import AsyncMock, MagicMock
    from decimal import Decimal
    from aisbf.payments.wallet.manager import WalletManager

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    # First call returns no wallet
    mock_session.execute.side_effect = [
        MagicMock(mappings=lambda: [None]),  # first select
        MagicMock(mappings=lambda: [{
            "id": 1,
            "user_id": 123,
            "balance": Decimal("0.00"),
            "currency_code": "USD",
            "auto_topup_enabled": False,
            "auto_topup_amount": None,
            "auto_topup_threshold": None,
            "auto_topup_payment_method_id": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00"
        }])
    ]

    manager = WalletManager(mock_session)
    wallet = await manager.get_wallet(123)

    assert wallet is not None
    assert wallet["user_id"] == 123
    assert wallet["balance"] == Decimal("0.00")
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_wallet_manager_has_sufficient_balance():
    """Test WalletManager sufficient balance check"""
    from unittest.mock import AsyncMock
    from decimal import Decimal
    from aisbf.payments.wallet.manager import WalletManager

    mock_session = AsyncMock()
    manager = WalletManager(mock_session)

    manager.get_wallet = AsyncMock(return_value={
        "balance": Decimal("50.00")
    })

    assert await manager.has_sufficient_balance(123, Decimal("25.00")) is True
    assert await manager.has_sufficient_balance(123, Decimal("50.00")) is True
    assert await manager.has_sufficient_balance(123, Decimal("75.00")) is False


@pytest.mark.asyncio
async def test_wallet_manager_credit_wallet():
    """Test WalletManager credit operation"""
    from unittest.mock import AsyncMock, MagicMock
    from decimal import Decimal
    from aisbf.payments.wallet.manager import WalletManager

    mock_session = AsyncMock()
    manager = WalletManager(mock_session)

    manager.get_wallet = AsyncMock(return_value={
        "id": 1,
        "user_id": 123,
        "balance": Decimal("10.00")
    })

    mock_transaction = {"id": 1001, "created_at": "2026-04-21T22:00:00"}
    mock_session.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: [mock_transaction]
    ))

    result = await manager.credit_wallet(123, Decimal("25.00"), {
        "description": "Test credit",
        "payment_gateway": "stripe",
        "gateway_transaction_id": "tx_123"
    })

    assert result["new_balance"] == Decimal("35.00")
    assert result["transaction_id"] == 1001


@pytest.mark.asyncio
async def test_wallet_manager_debit_wallet_sufficient_funds():
    """Test WalletManager debit with sufficient balance"""
    from unittest.mock import AsyncMock, MagicMock
    from decimal import Decimal
    from aisbf.payments.wallet.manager import WalletManager

    mock_session = AsyncMock()
    manager = WalletManager(mock_session)

    manager.get_wallet = AsyncMock(return_value={
        "id": 1,
        "user_id": 123,
        "balance": Decimal("50.00")
    })

    mock_transaction = {"id": 1002, "created_at": "2026-04-21T22:00:00"}
    mock_session.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: [mock_transaction]
    ))

    result = await manager.debit_wallet(123, Decimal("20.00"), {
        "description": "Test debit",
        "payment_method_id": 5
    })

    assert result["new_balance"] == Decimal("30.00")


@pytest.mark.asyncio
async def test_wallet_manager_debit_wallet_insufficient_funds():
    """Test WalletManager debit fails when balance is insufficient"""
    from unittest.mock import AsyncMock
    from decimal import Decimal
    from aisbf.payments.wallet.manager import WalletManager
    import pytest

    mock_session = AsyncMock()
    manager = WalletManager(mock_session)

    manager.get_wallet = AsyncMock(return_value={
        "id": 1,
        "user_id": 123,
        "balance": Decimal("10.00")
    })

    with pytest.raises(ValueError, match="Insufficient balance"):
        await manager.debit_wallet(123, Decimal("20.00"), {})
