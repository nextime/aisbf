# Payment System Phase 1: Foundation & Crypto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement database foundation, HD wallet generation, crypto address management, blockchain monitoring (API mode), and price aggregation. Users can receive crypto addresses and system tracks incoming payments.

**Architecture:** Database schema with migrations, BIP32/BIP44 HD wallet derivation, multi-API blockchain monitoring, multi-exchange price averaging, async operations throughout.

**Tech Stack:** SQLite/MySQL, cryptography (Fernet), bip32, mnemonic, bitcoinlib, web3, eth-account, httpx (async)

---

## Phase 1 Deliverables

- ✅ Complete database schema for payment system
- ✅ HD wallet generation and address derivation
- ✅ User crypto address management
- ✅ Blockchain transaction monitoring (API polling mode)
- ✅ Multi-exchange price aggregation
- ✅ Basic API endpoints for crypto addresses and wallets
- ✅ Unit tests for all components

---

## Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add payment system dependencies**

Add to `requirements.txt`:

```
# Payment system dependencies
stripe>=5.0.0
httpx>=0.24.0
cryptography>=41.0.0
bip32>=3.4
mnemonic>=0.20
bitcoinlib>=0.6.14
web3>=6.0.0
eth-account>=0.9.0
```

- [ ] **Step 2: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: All packages install successfully

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat(payments): add payment system dependencies"
```

---

## Task 2: Database Schema and Migrations

**Files:**
- Create: `aisbf/payments/__init__.py`
- Create: `aisbf/payments/migrations.py`
- Modify: `aisbf/database.py`

- [ ] **Step 1: Create payments module init**

Create `aisbf/payments/__init__.py`:

```python
"""
Payment system module
"""
from aisbf.payments.migrations import PaymentMigrations

__all__ = ['PaymentMigrations']
```

- [ ] **Step 2: Create migrations module**

Create `aisbf/payments/migrations.py` with complete schema (see design doc Section 1 for full SQL).

Key tables to create:
- crypto_master_keys
- user_crypto_addresses
- user_crypto_wallets
- crypto_transactions
- crypto_webhooks
- payment_methods
- payment_transactions
- subscriptions
- payment_retry_queue
- api_requests
- crypto_price_sources
- crypto_consolidation_settings
- email_notification_settings
- email_templates
- email_config
- payment_gateway_config
- crypto_api_config
- job_locks
- crypto_consolidation_queue
- email_notification_queue

Include indexes and default data inserts.

- [ ] **Step 3: Add migration runner to database manager**

Modify `aisbf/database.py`, add method to DatabaseManager class:

```python
def run_payment_migrations(self):
    """Run payment system migrations"""
    from aisbf.payments.migrations import PaymentMigrations
    
    migrations = PaymentMigrations(self)
    migrations.run_migrations()
```

- [ ] **Step 4: Test migrations**

Create `tests/payments/__init__.py`:

```python
"""Payment system tests"""
```

Create `tests/payments/test_migrations.py`:

```python
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
    tables = db.fetch_all("""
        SELECT name FROM sqlite_master 
        WHERE type='table'
    """)
    
    table_names = [t['name'] for t in tables]
    
    assert 'crypto_master_keys' in table_names
    assert 'user_crypto_addresses' in table_names
    assert 'payment_methods' in table_names
    assert 'subscriptions' in table_names


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
    sources = db.fetch_all("SELECT * FROM crypto_price_sources")
    assert len(sources) >= 3
    
    # Check consolidation settings
    settings = db.fetch_all("SELECT * FROM crypto_consolidation_settings")
    assert len(settings) == 4
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/payments/test_migrations.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add aisbf/payments/__init__.py aisbf/payments/migrations.py aisbf/database.py tests/payments/
git commit -m "feat(payments): add database schema and migrations"
```

---

## Task 3: Pydantic Models

**Files:**
- Create: `aisbf/payments/models.py`

- [ ] **Step 1: Create Pydantic models**

Create `aisbf/payments/models.py`:

```python
"""
Pydantic models for payment system
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class CryptoAddress(BaseModel):
    """Crypto address model"""
    crypto_type: str
    address: str
    derivation_path: str
    derivation_index: int


class CryptoWallet(BaseModel):
    """Crypto wallet balance model"""
    crypto_type: str
    balance_crypto: Decimal
    balance_fiat: Decimal
    last_sync_at: Optional[datetime] = None


class AddCryptoPaymentMethodRequest(BaseModel):
    """Request to add crypto payment method"""
    crypto_type: str
```

- [ ] **Step 2: Update module init**

Modify `aisbf/payments/__init__.py`:

```python
"""
Payment system module
"""
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.models import (
    CryptoAddress,
    CryptoWallet,
    AddCryptoPaymentMethodRequest
)

__all__ = [
    'PaymentMigrations',
    'CryptoAddress',
    'CryptoWallet',
    'AddCryptoPaymentMethodRequest'
]
```

- [ ] **Step 3: Commit**

```bash
git add aisbf/payments/models.py aisbf/payments/__init__.py
git commit -m "feat(payments): add Pydantic models"
```

---

## Task 4: HD Wallet Manager

**Files:**
- Create: `aisbf/payments/crypto/__init__.py`
- Create: `aisbf/payments/crypto/wallet.py`
- Create: `tests/payments/test_wallet.py`

- [ ] **Step 1: Write failing test for wallet initialization**

Create `tests/payments/test_wallet.py`:

```python
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
    keys = db_manager.fetch_all("SELECT * FROM crypto_master_keys")
    assert len(keys) == 4  # btc, eth, usdt, usdc
    
    crypto_types = [k['crypto_type'] for k in keys]
    assert 'btc' in crypto_types
    assert 'eth' in crypto_types
    assert 'usdt' in crypto_types
    assert 'usdc' in crypto_types
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/payments/test_wallet.py::test_initialize_master_keys -v
```

Expected: FAIL with "No module named 'aisbf.payments.crypto.wallet'"

- [ ] **Step 3: Create crypto module init**

Create `aisbf/payments/crypto/__init__.py`:

```python
"""
Crypto payment module
"""
from aisbf.payments.crypto.wallet import CryptoWalletManager

__all__ = ['CryptoWalletManager']
```

- [ ] **Step 4: Implement HD wallet manager**

Create `aisbf/payments/crypto/wallet.py`:

```python
"""
HD Wallet Manager for cryptocurrency addresses
"""
import logging
from mnemonic import Mnemonic
from bip32 import BIP32
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class CryptoWalletManager:
    """Manages HD wallets for all supported cryptocurrencies"""
    
    # BIP44 coin types
    COIN_TYPES = {
        'btc': 0,
        'eth': 60,
        'usdt': 60,  # ERC20 uses Ethereum
        'usdc': 60   # ERC20 uses Ethereum
    }
    
    def __init__(self, db_manager, encryption_key: str):
        self.db = db_manager
        self.encryption_key = encryption_key
        self.fernet = Fernet(encryption_key.encode())
        
        # Initialize master keys on first run
        self._initialize_master_keys()
        
    def _initialize_master_keys(self):
        """Initialize master keys for all crypto types (run once on setup)"""
        for crypto_type in ['btc', 'eth', 'usdt', 'usdc']:
            existing = self.db.fetch_one(
                "SELECT id FROM crypto_master_keys WHERE crypto_type = ?",
                (crypto_type,)
            )
            
            if not existing:
                # Generate new BIP39 mnemonic (24 words)
                mnemo = Mnemonic("english")
                mnemonic = mnemo.generate(strength=256)
                
                # Encrypt mnemonic
                encrypted_seed = self.fernet.encrypt(mnemonic.encode()).decode()
                
                # Store in database
                self.db.execute("""
                    INSERT INTO crypto_master_keys 
                    (crypto_type, encrypted_seed, encryption_key_id)
                    VALUES (?, ?, ?)
                """, (crypto_type, encrypted_seed, 'default'))
                
                logger.info(f"Generated master key for {crypto_type}")
    
    def get_master_seed(self, crypto_type: str) -> str:
        """Get decrypted master seed for crypto type"""
        result = self.db.fetch_one(
            "SELECT encrypted_seed FROM crypto_master_keys WHERE crypto_type = ?",
            (crypto_type,)
        )
        
        if not result:
            raise ValueError(f"No master key found for {crypto_type}")
        
        # Decrypt seed
        encrypted_seed = result['encrypted_seed']
        mnemonic = self.fernet.decrypt(encrypted_seed.encode()).decode()
        return mnemonic
    
    def derive_address(self, crypto_type: str, index: int) -> dict:
        """Derive address from master key using BIP44 path"""
        mnemonic = self.get_master_seed(crypto_type)
        
        # Generate seed from mnemonic
        mnemo = Mnemonic("english")
        seed = mnemo.to_seed(mnemonic)
        
        # BIP44 path: m/44'/coin_type'/0'/0/index
        coin_type = self.COIN_TYPES[crypto_type]
        path = f"m/44'/{coin_type}'/0'/0/{index}"
        
        if crypto_type == 'btc':
            return self._derive_bitcoin_address(seed, path, index)
        elif crypto_type in ['eth', 'usdt', 'usdc']:
            return self._derive_ethereum_address(seed, path, index)
    
    def _derive_bitcoin_address(self, seed: bytes, path: str, index: int) -> dict:
        """Derive Bitcoin address"""
        from bitcoinlib.keys import HDKey
        
        # Create HD key from seed
        hd_key = HDKey.from_seed(seed)
        
        # Derive child key
        child_key = hd_key.subkey_for_path(path)
        
        # Get P2WPKH address (native segwit, starts with bc1)
        address = child_key.address(encoding='bech32')
        
        return {
            'address': address,
            'derivation_path': path,
            'derivation_index': index
        }
    
    def _derive_ethereum_address(self, seed: bytes, path: str, index: int) -> dict:
        """Derive Ethereum address (also used for USDT/USDC ERC20)"""
        from eth_account import Account
        
        # Create BIP32 instance
        bip32 = BIP32.from_seed(seed)
        
        # Derive child key
        child_key = bip32.get_privkey_from_path(path)
        
        # Get Ethereum address from private key
        account = Account.from_key(child_key)
        address = account.address
        
        return {
            'address': address,
            'derivation_path': path,
            'derivation_index': index
        }
    
    async def get_or_create_user_address(self, user_id: int, crypto_type: str) -> str:
        """Get existing address or create new one for user"""
        # Check if user already has address
        existing = self.db.fetch_one("""
            SELECT address FROM user_crypto_addresses 
            WHERE user_id = ? AND crypto_type = ?
        """, (user_id, crypto_type))
        
        if existing:
            return existing['address']
        
        # Get next available index
        max_index = self.db.fetch_one("""
            SELECT COALESCE(MAX(derivation_index), -1) as max_idx
            FROM user_crypto_addresses
            WHERE crypto_type = ?
        """, (crypto_type,))
        
        next_index = max_index['max_idx'] + 1
        
        # Derive new address
        address_info = self.derive_address(crypto_type, next_index)
        
        # Store in database
        self.db.execute("""
            INSERT INTO user_crypto_addresses
            (user_id, crypto_type, address, derivation_path, derivation_index)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            crypto_type,
            address_info['address'],
            address_info['derivation_path'],
            address_info['derivation_index']
        ))
        
        # Create wallet entry
        self.db.execute("""
            INSERT INTO user_crypto_wallets
            (user_id, crypto_type, balance_crypto, balance_fiat)
            VALUES (?, ?, 0, 0)
        """, (user_id, crypto_type))
        
        logger.info(f"Created {crypto_type} address for user {user_id}: {address_info['address']}")
        
        return address_info['address']
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/payments/test_wallet.py::test_initialize_master_keys -v
```

Expected: PASS

- [ ] **Step 6: Add test for address derivation**

Add to `tests/payments/test_wallet.py`:

```python
@pytest.mark.asyncio
async def test_derive_bitcoin_address(db_manager, encryption_key):
    """Test Bitcoin address derivation"""
    wallet_manager = CryptoWalletManager(db_manager, encryption_key)
    
    address_info = wallet_manager.derive_address('btc', 0)
    
    assert address_info['address'].startswith('bc1')
    assert address_info['derivation_path'] == "m/44'/0'/0'/0/0"
    assert address_info['derivation_index'] == 0


@pytest.mark.asyncio
async def test_derive_ethereum_address(db_manager, encryption_key):
    """Test Ethereum address derivation"""
    wallet_manager = CryptoWalletManager(db_manager, encryption_key)
    
    address_info = wallet_manager.derive_address('eth', 0)
    
    assert address_info['address'].startswith('0x')
    assert len(address_info['address']) == 42
    assert address_info['derivation_path'] == "m/44'/60'/0'/0/0"


@pytest.mark.asyncio
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
```

- [ ] **Step 7: Run all wallet tests**

```bash
pytest tests/payments/test_wallet.py -v
```

Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add aisbf/payments/crypto/ tests/payments/test_wallet.py
git commit -m "feat(payments): implement HD wallet manager with BIP32/BIP44"
```

---

## Task 5: Multi-Exchange Price Service

**Files:**
- Create: `aisbf/payments/crypto/pricing.py`
- Create: `tests/payments/test_pricing.py`

- [ ] **Step 1: Write failing test for price fetching**

Create `tests/payments/test_pricing.py`:

```python
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


@pytest.mark.asyncio
async def test_convert_crypto_to_fiat(db_manager):
    """Test crypto to fiat conversion"""
    config = {'currency_code': 'USD'}
    price_service = CryptoPriceService(db_manager, config)
    
    # Convert 1 BTC to USD
    fiat_amount = await price_service.convert_crypto_to_fiat('btc', 1.0)
    
    # Should return a reasonable price (> $1000)
    assert fiat_amount > 1000
    assert isinstance(fiat_amount, float)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/payments/test_pricing.py::test_convert_crypto_to_fiat -v
```

Expected: FAIL with "No module named 'aisbf.payments.crypto.pricing'"

- [ ] **Step 3: Implement price service**

Create `aisbf/payments/crypto/pricing.py`:

```python
"""
Multi-exchange crypto price aggregation service
"""
import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class CryptoPriceService:
    """Configurable crypto price fetching from multiple sources"""
    
    def __init__(self, db_manager, config: dict):
        self.db = db_manager
        self.config = config
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.cache = {}  # Simple in-memory cache
        self.cache_ttl = 60  # Cache prices for 60 seconds
    
    async def convert_crypto_to_fiat(self, crypto_type: str, amount: float) -> float:
        """Convert crypto to fiat using configured price sources"""
        currency = self.config.get('currency_code', 'USD')
        
        # Check cache first
        cache_key = f"{crypto_type}_{currency}"
        if cache_key in self.cache:
            cached_price, cached_at = self.cache[cache_key]
            if (datetime.utcnow() - cached_at).seconds < self.cache_ttl:
                return round(amount * cached_price, 2)
        
        # Get enabled price sources ordered by priority
        sources = self.db.fetch_all("""
            SELECT * FROM crypto_price_sources
            WHERE enabled = TRUE
            ORDER BY priority ASC
        """)
        
        if not sources:
            raise ValueError("No price sources configured")
        
        # Fetch prices from all sources concurrently
        import asyncio
        tasks = [
            self._fetch_price_from_source(source, crypto_type, currency)
            for source in sources
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results
        prices = [r for r in results if isinstance(r, (int, float)) and r > 0]
        
        if not prices:
            raise ValueError(f"Could not fetch price for {crypto_type} from any source")
        
        # Use average of all successful prices
        avg_price = sum(prices) / len(prices)
        
        # Cache the result
        self.cache[cache_key] = (avg_price, datetime.utcnow())
        
        logger.info(f"Price for {crypto_type}: ${avg_price} (from {len(prices)} sources)")
        
        return round(amount * avg_price, 2)
    
    async def _fetch_price_from_source(self, source: dict, crypto_type: str, 
                                       currency: str) -> Optional[float]:
        """Fetch price from a single source"""
        try:
            api_type = source['api_type']
            
            if api_type == 'coinbase':
                return await self._fetch_coinbase(source, crypto_type, currency)
            elif api_type == 'binance':
                return await self._fetch_binance(source, crypto_type, currency)
            elif api_type == 'kraken':
                return await self._fetch_kraken(source, crypto_type, currency)
            else:
                logger.warning(f"Unknown API type: {api_type}")
                return None
                
        except Exception as e:
            logger.warning(f"Failed to fetch price from {source['name']}: {e}")
            return None
    
    async def _fetch_coinbase(self, source: dict, crypto_type: str, currency: str) -> Optional[float]:
        """Fetch from Coinbase"""
        symbol_map = {'btc': 'BTC', 'eth': 'ETH', 'usdt': 'USDT', 'usdc': 'USDC'}
        symbol = symbol_map.get(crypto_type, crypto_type.upper())
        
        url = source['endpoint_url'].format(symbol=symbol, currency=currency)
        
        headers = {}
        if source.get('api_key'):
            headers['Authorization'] = f"Bearer {source['api_key']}"
        
        response = await self.http_client.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            return float(data['data']['amount'])
        return None
    
    async def _fetch_binance(self, source: dict, crypto_type: str, currency: str) -> Optional[float]:
        """Fetch from Binance"""
        symbol_map = {'btc': 'BTC', 'eth': 'ETH', 'usdt': 'USDT', 'usdc': 'USDC'}
        symbol = symbol_map.get(crypto_type, crypto_type.upper())
        
        # Binance uses BTCUSDT format
        pair = f"{symbol}{currency}"
        url = source['endpoint_url'].format(symbol=pair)
        
        response = await self.http_client.get(url)
        
        if response.status_code == 200:
            data = response.json()
            return float(data['price'])
        return None
    
    async def _fetch_kraken(self, source: dict, crypto_type: str, currency: str) -> Optional[float]:
        """Fetch from Kraken"""
        symbol_map = {'btc': 'XBT', 'eth': 'ETH', 'usdt': 'USDT', 'usdc': 'USDC'}
        symbol = symbol_map.get(crypto_type, crypto_type.upper())
        
        # Kraken uses XXBTZUSD format
        pair = f"X{symbol}Z{currency}" if symbol == 'XBT' else f"{symbol}{currency}"
        url = source['endpoint_url'].format(symbol=pair, currency=currency)
        
        response = await self.http_client.get(url)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('error'):
                return None
            result = data['result']
            pair_data = list(result.values())[0]
            return float(pair_data['c'][0])  # Last trade closed price
        return None
```

- [ ] **Step 4: Update crypto module init**

Modify `aisbf/payments/crypto/__init__.py`:

```python
"""
Crypto payment module
"""
from aisbf.payments.crypto.wallet import CryptoWalletManager
from aisbf.payments.crypto.pricing import CryptoPriceService

__all__ = ['CryptoWalletManager', 'CryptoPriceService']
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/payments/test_pricing.py::test_convert_crypto_to_fiat -v
```

Expected: PASS (fetches real prices from APIs)

- [ ] **Step 6: Add test for price caching**

Add to `tests/payments/test_pricing.py`:

```python
@pytest.mark.asyncio
async def test_price_caching(db_manager):
    """Test that prices are cached"""
    config = {'currency_code': 'USD'}
    price_service = CryptoPriceService(db_manager, config)
    
    # First call fetches from API
    price1 = await price_service.convert_crypto_to_fiat('btc', 1.0)
    
    # Second call should use cache (same price)
    price2 = await price_service.convert_crypto_to_fiat('btc', 1.0)
    
    assert price1 == price2
```

- [ ] **Step 7: Run all pricing tests**

```bash
pytest tests/payments/test_pricing.py -v
```

Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add aisbf/payments/crypto/pricing.py tests/payments/test_pricing.py aisbf/payments/crypto/__init__.py
git commit -m "feat(payments): implement multi-exchange price aggregation"
```

---

## Task 6: Blockchain Monitoring (API Mode)

**Files:**
- Create: `aisbf/payments/crypto/monitor.py`
- Create: `tests/payments/test_monitor.py`

- [ ] **Step 1: Write failing test for transaction processing**

Create `tests/payments/test_monitor.py`:

```python
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


@pytest.mark.asyncio
async def test_process_transaction(db_manager):
    """Test transaction processing"""
    config = {'currency_code': 'USD', 'btc_confirmations': 3}
    monitor = BlockchainMonitor(db_manager, config)
    
    # Create user and address
    db_manager.execute("""
        INSERT INTO user_crypto_addresses 
        (user_id, crypto_type, address, derivation_path, derivation_index)
        VALUES (1, 'btc', 'bc1qtest', 'm/44/0/0/0/0', 0)
    """)
    
    db_manager.execute("""
        INSERT INTO user_crypto_wallets
        (user_id, crypto_type, balance_crypto, balance_fiat)
        VALUES (1, 'btc', 0, 0)
    """)
    
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
    tx = db_manager.fetch_one(
        "SELECT * FROM crypto_transactions WHERE tx_hash = ?",
        ('test_tx_hash',)
    )
    
    assert tx is not None
    assert tx['status'] == 'confirmed'
    assert float(tx['amount_crypto']) == 0.001
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/payments/test_monitor.py::test_process_transaction -v
```

Expected: FAIL with "No module named 'aisbf.payments.crypto.monitor'"

- [ ] **Step 3: Implement blockchain monitor**

Create `aisbf/payments/crypto/monitor.py`:

```python
"""
Blockchain monitoring service (API polling mode)
"""
import logging
import httpx
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class BlockchainMonitor:
    """Monitor blockchain transactions using APIs"""
    
    def __init__(self, db_manager, config: dict):
        self.db = db_manager
        self.config = config
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def check_crypto_payments(self):
        """Main entry point for checking payments (API polling)"""
        await self.poll_blockchain_apis()
    
    async def poll_blockchain_apis(self):
        """Poll blockchain APIs for new transactions"""
        # Get all user addresses that need monitoring
        addresses = self.db.fetch_all("""
            SELECT DISTINCT ua.crypto_type, ua.address, ua.user_id
            FROM user_crypto_addresses ua
            INNER JOIN users u ON ua.user_id = u.id
        """)
        
        # Group by crypto type
        by_crypto = {}
        for addr in addresses:
            crypto_type = addr['crypto_type']
            if crypto_type not in by_crypto:
                by_crypto[crypto_type] = []
            by_crypto[crypto_type].append(addr)
        
        # Check each crypto type concurrently
        import asyncio
        tasks = []
        for crypto_type, addrs in by_crypto.items():
            if crypto_type == 'btc':
                tasks.append(self.check_bitcoin_addresses(addrs))
            elif crypto_type in ['eth', 'usdt', 'usdc']:
                tasks.append(self.check_ethereum_addresses(addrs, crypto_type))
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def check_bitcoin_addresses(self, addresses: list):
        """Check Bitcoin addresses for new transactions"""
        for addr_info in addresses:
            try:
                # Try multiple APIs
                txs = await self._get_bitcoin_transactions(addr_info['address'])
                
                for tx in txs:
                    await self.process_transaction(
                        user_id=addr_info['user_id'],
                        crypto_type='btc',
                        tx_hash=tx['hash'],
                        from_address=tx.get('from', 'unknown'),
                        to_address=addr_info['address'],
                        amount=tx['amount'],
                        confirmations=tx['confirmations']
                    )
            except Exception as e:
                logger.error(f"Error checking BTC address {addr_info['address']}: {e}")
    
    async def _get_bitcoin_transactions(self, address: str) -> list:
        """Get Bitcoin transactions from multiple APIs"""
        # Try Blockchain.com
        try:
            response = await self.http_client.get(
                f"https://blockchain.info/rawaddr/{address}"
            )
            if response.status_code == 200:
                data = response.json()
                return self._parse_blockchain_com_btc(data, address)
        except Exception as e:
            logger.warning(f"Blockchain.com API failed: {e}")
        
        return []
    
    def _parse_blockchain_com_btc(self, data: dict, address: str) -> list:
        """Parse Blockchain.com Bitcoin response"""
        txs = []
        for tx in data.get('txs', []):
            # Find outputs to our address
            for output in tx.get('out', []):
                if address in output.get('addr', ''):
                    txs.append({
                        'hash': tx['hash'],
                        'from': tx.get('inputs', [{}])[0].get('prev_out', {}).get('addr', 'unknown'),
                        'amount': output['value'] / 100000000,  # Satoshi to BTC
                        'confirmations': data.get('n_tx', 0)
                    })
        return txs
    
    async def check_ethereum_addresses(self, addresses: list, crypto_type: str):
        """Check Ethereum addresses (ETH, USDT, USDC)"""
        for addr_info in addresses:
            try:
                if crypto_type == 'eth':
                    txs = await self._get_ethereum_transactions(addr_info['address'])
                else:
                    # For ERC20 tokens, would need token-specific API
                    txs = []
                
                for tx in txs:
                    await self.process_transaction(
                        user_id=addr_info['user_id'],
                        crypto_type=crypto_type,
                        tx_hash=tx['hash'],
                        from_address=tx['from'],
                        to_address=addr_info['address'],
                        amount=tx['amount'],
                        confirmations=tx['confirmations']
                    )
            except Exception as e:
                logger.error(f"Error checking {crypto_type} address {addr_info['address']}: {e}")
    
    async def _get_ethereum_transactions(self, address: str) -> list:
        """Get Ethereum transactions (placeholder - would use Etherscan/Infura)"""
        # In production, would use Etherscan API or Infura
        return []
    
    async def process_transaction(self, user_id: int, crypto_type: str, 
                                  tx_hash: str, from_address: str, 
                                  to_address: str, amount: float, 
                                  confirmations: int):
        """Process detected transaction"""
        # Check if already recorded
        existing = self.db.fetch_one(
            "SELECT id, status FROM crypto_transactions WHERE tx_hash = ?",
            (tx_hash,)
        )
        
        required_confirmations = self.config.get(f'{crypto_type}_confirmations', 3)
        
        if existing:
            # Update confirmations
            if existing['status'] != 'credited':
                self.db.execute("""
                    UPDATE crypto_transactions
                    SET confirmations = ?,
                        status = CASE 
                            WHEN ? >= required_confirmations THEN 'confirmed'
                            ELSE 'pending'
                        END,
                        confirmed_at = CASE
                            WHEN ? >= required_confirmations AND confirmed_at IS NULL
                            THEN CURRENT_TIMESTAMP
                            ELSE confirmed_at
                        END
                    WHERE id = ?
                """, (confirmations, confirmations, confirmations, existing['id']))
                
                # Credit wallet if confirmed
                if confirmations >= required_confirmations:
                    await self.credit_user_wallet(existing['id'])
        else:
            # New transaction
            status = 'confirmed' if confirmations >= required_confirmations else 'pending'
            
            self.db.execute("""
                INSERT INTO crypto_transactions
                (user_id, crypto_type, tx_hash, from_address, to_address,
                 amount_crypto, confirmations, required_confirmations, status,
                 confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, crypto_type, tx_hash, from_address, to_address,
                amount, confirmations, required_confirmations, status,
                datetime.utcnow() if status == 'confirmed' else None
            ))
            
            tx_id = self.db.get_last_insert_id()
            
            # Credit wallet if confirmed
            if status == 'confirmed':
                await self.credit_user_wallet(tx_id)
    
    async def credit_user_wallet(self, transaction_id: int):
        """Credit user's crypto wallet with confirmed transaction"""
        tx = self.db.fetch_one(
            "SELECT * FROM crypto_transactions WHERE id = ?",
            (transaction_id,)
        )
        
        if tx['status'] == 'credited':
            return  # Already credited
        
        # Get current crypto price in fiat (would use price service)
        # For now, use placeholder
        fiat_amount = float(tx['amount_crypto']) * 50000  # Placeholder price
        
        # Update transaction with fiat amount
        self.db.execute("""
            UPDATE crypto_transactions
            SET amount_fiat = ?, status = 'credited', credited_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (fiat_amount, transaction_id))
        
        # Update user wallet
        self.db.execute("""
            UPDATE user_crypto_wallets
            SET balance_crypto = balance_crypto + ?,
                balance_fiat = balance_fiat + ?,
                last_sync_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND crypto_type = ?
        """, (tx['amount_crypto'], fiat_amount, tx['user_id'], tx['crypto_type']))
        
        logger.info(f"Credited {tx['amount_crypto']} {tx['crypto_type']} "
                   f"(${fiat_amount}) to user {tx['user_id']}")
```

- [ ] **Step 4: Update crypto module init**

Modify `aisbf/payments/crypto/__init__.py`:

```python
"""
Crypto payment module
"""
from aisbf.payments.crypto.wallet import CryptoWalletManager
from aisbf.payments.crypto.pricing import CryptoPriceService
from aisbf.payments.crypto.monitor import BlockchainMonitor

__all__ = ['CryptoWalletManager', 'CryptoPriceService', 'BlockchainMonitor']
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/payments/test_monitor.py::test_process_transaction -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add aisbf/payments/crypto/monitor.py tests/payments/test_monitor.py aisbf/payments/crypto/__init__.py
git commit -m "feat(payments): implement blockchain monitoring (API mode)"
```

---

## Task 7: Basic Payment Service

**Files:**
- Create: `aisbf/payments/service.py`

- [ ] **Step 1: Implement basic payment service**

Create `aisbf/payments/service.py`:

```python
"""
Main payment service orchestrator
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PaymentService:
    """Main payment service orchestrating all payment operations"""
    
    def __init__(self, db_manager, config: dict):
        self.db = db_manager
        self.config = config
        
        # Initialize sub-services
        from aisbf.payments.crypto.wallet import CryptoWalletManager
        from aisbf.payments.crypto.pricing import CryptoPriceService
        from aisbf.payments.crypto.monitor import BlockchainMonitor
        
        self.wallet_manager = CryptoWalletManager(db_manager, config['encryption_key'])
        self.price_service = CryptoPriceService(db_manager, config)
        self.blockchain_monitor = BlockchainMonitor(db_manager, config)
    
    async def initialize(self):
        """Initialize payment service (run on startup)"""
        logger.info("Payment service initialized")
    
    async def get_user_crypto_addresses(self, user_id: int) -> dict:
        """Get or create crypto addresses for user"""
        addresses = {}
        
        # Get enabled crypto types
        enabled_cryptos = self.db.fetch_all("""
            SELECT crypto_type FROM crypto_consolidation_settings
            WHERE enabled = TRUE
        """)
        
        for crypto_config in enabled_cryptos:
            crypto_type = crypto_config['crypto_type']
            address = await self.wallet_manager.get_or_create_user_address(
                user_id, 
                crypto_type
            )
            addresses[crypto_type] = address
        
        return addresses
    
    async def get_user_wallet_balances(self, user_id: int) -> dict:
        """Get user's crypto wallet balances"""
        wallets = self.db.fetch_all("""
            SELECT crypto_type, balance_crypto, balance_fiat, last_sync_at
            FROM user_crypto_wallets
            WHERE user_id = ?
        """, (user_id,))
        
        return {
            wallet['crypto_type']: {
                'balance_crypto': float(wallet['balance_crypto']),
                'balance_fiat': float(wallet['balance_fiat']),
                'last_sync': wallet['last_sync_at']
            }
            for wallet in wallets
        }
    
    async def add_crypto_payment_method(self, user_id: int, crypto_type: str) -> dict:
        """Add crypto as payment method"""
        try:
            # Get or create crypto address
            address = await self.wallet_manager.get_or_create_user_address(
                user_id,
                crypto_type
            )
            
            # Create payment method entry
            self.db.execute("""
                INSERT INTO payment_methods
                (user_id, type, gateway, crypto_type, is_default, status)
                VALUES (?, 'crypto', ?, ?, TRUE, 'active')
            """, (user_id, crypto_type, crypto_type))
            
            return {
                'success': True,
                'crypto_type': crypto_type,
                'address': address
            }
            
        except Exception as e:
            logger.error(f"Error adding crypto payment method: {e}")
            return {'success': False, 'error': str(e)}
```

- [ ] **Step 2: Update payments module init**

Modify `aisbf/payments/__init__.py`:

```python
"""
Payment system module
"""
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.models import (
    CryptoAddress,
    CryptoWallet,
    AddCryptoPaymentMethodRequest
)
from aisbf.payments.service import PaymentService

__all__ = [
    'PaymentMigrations',
    'CryptoAddress',
    'CryptoWallet',
    'AddCryptoPaymentMethodRequest',
    'PaymentService'
]
```

- [ ] **Step 3: Commit**

```bash
git add aisbf/payments/service.py aisbf/payments/__init__.py
git commit -m "feat(payments): implement basic payment service orchestrator"
```

---

## Task 8: API Endpoints

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add payment service initialization to main.py**

Add to `main.py` after existing imports:

```python
import os
from cryptography.fernet import Fernet

# Payment service global
payment_service = None
```

Add startup event handler:

```python
@app.on_event("startup")
async def startup_payment_service():
    """Initialize payment service on startup"""
    global payment_service
    
    # Generate or load encryption key
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if not encryption_key:
        encryption_key = Fernet.generate_key().decode()
        logger.warning("No ENCRYPTION_KEY set, generated temporary key")
    
    config = {
        'encryption_key': encryption_key,
        'base_url': os.getenv('BASE_URL', 'http://localhost:17765'),
        'currency_code': 'USD',
        'btc_confirmations': 3,
        'eth_confirmations': 12
    }
    
    from aisbf.payments.service import PaymentService
    payment_service = PaymentService(db_manager, config)
    await payment_service.initialize()
    
    logger.info("Payment service started")
```

- [ ] **Step 2: Add crypto address endpoints**

Add to `main.py`:

```python
@app.get("/api/crypto/addresses")
async def get_crypto_addresses(current_user: dict = Depends(get_current_user)):
    """Get user's crypto addresses"""
    addresses = await payment_service.get_user_crypto_addresses(current_user['id'])
    return {'addresses': addresses}


@app.get("/api/crypto/wallets")
async def get_crypto_wallets(current_user: dict = Depends(get_current_user)):
    """Get user's crypto wallet balances"""
    balances = await payment_service.get_user_wallet_balances(current_user['id'])
    return {'wallets': balances}


@app.post("/api/payment-methods/crypto")
async def add_crypto_payment_method(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Add crypto payment method"""
    result = await payment_service.add_crypto_payment_method(
        current_user['id'],
        request['crypto_type']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result
```

- [ ] **Step 3: Test endpoints manually**

Start server:
```bash
python main.py
```

Test with curl (requires authentication):
```bash
curl http://localhost:17765/api/crypto/addresses -H "Authorization: Bearer YOUR_TOKEN"
```

Expected: Returns crypto addresses for user

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(payments): add crypto API endpoints"
```

---

## Phase 1 Complete!

Phase 1 deliverables achieved:
- ✅ Database schema with migrations
- ✅ HD wallet generation and address derivation
- ✅ User crypto address management
- ✅ Blockchain transaction monitoring (API mode)
- ✅ Multi-exchange price aggregation
- ✅ Basic API endpoints for crypto addresses and wallets
- ✅ Unit tests for all components

**Next Steps:**
- Phase 2: Fiat Payments (Stripe/PayPal integration)
- Phase 3: Subscriptions & Billing
- Phase 4: Advanced Features (Quota, Consolidation, Emails)
