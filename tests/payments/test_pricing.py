import pytest
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
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
async def test_convert_crypto_to_fiat(db_manager):
    """Test crypto to fiat conversion"""
    config = {'currency_code': 'USD'}
    price_service = CryptoPriceService(db_manager, config)
    
    # Convert 1 BTC to USD
    fiat_amount = await price_service.convert_crypto_to_fiat('btc', 1.0)
    
    # Should return a reasonable price (> $1000)
    assert fiat_amount > 1000
    assert isinstance(fiat_amount, float)


@pytest.mark.anyio
async def test_price_caching(db_manager):
    """Test that prices are cached"""
    config = {'currency_code': 'USD'}
    price_service = CryptoPriceService(db_manager, config)
    
    # First call fetches from API
    price1 = await price_service.convert_crypto_to_fiat('btc', 1.0)
    
    # Second call should use cache (same price)
    price2 = await price_service.convert_crypto_to_fiat('btc', 1.0)
    
    assert price1 == price2
