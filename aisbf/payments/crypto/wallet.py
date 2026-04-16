"""
HD Wallet Manager for cryptocurrency addresses

Implements BIP32/BIP44 hierarchical deterministic wallet generation.
Each crypto type has its own encrypted master seed, from which user addresses
are deterministically derived.
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
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(
                    f"SELECT id FROM crypto_master_keys WHERE crypto_type = {placeholder}",
                    (crypto_type,)
                )
                existing = cursor.fetchone()
            
            if not existing:
                # Generate new BIP39 mnemonic (24 words)
                mnemo = Mnemonic("english")
                mnemonic = mnemo.generate(strength=256)
                
                # Encrypt mnemonic
                encrypted_seed = self.fernet.encrypt(mnemonic.encode()).decode()
                
                # BIP44 derivation path
                coin_type = self.COIN_TYPES[crypto_type]
                derivation_path = f"m/44'/{coin_type}'/0'/0"
                
                # Store in database
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                    cursor.execute(f"""
                        INSERT INTO crypto_master_keys 
                        (crypto_type, encrypted_seed, encryption_key_id, derivation_path)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
                    """, (crypto_type, encrypted_seed, 'default', derivation_path))
                    conn.commit()
                
                logger.info(f"Generated master key for {crypto_type}")
    
    def get_master_seed(self, crypto_type: str) -> str:
        """Get decrypted master seed for crypto type"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(
                f"SELECT encrypted_seed FROM crypto_master_keys WHERE crypto_type = {placeholder}",
                (crypto_type,)
            )
            result = cursor.fetchone()
        
        if not result:
            raise ValueError(f"No master key found for {crypto_type}")
        
        # Decrypt seed
        encrypted_seed = result[0]
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
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT address FROM user_crypto_addresses 
                WHERE user_id = {placeholder} AND crypto_type = {placeholder}
            """, (user_id, crypto_type))
            existing = cursor.fetchone()
        
        if existing:
            return existing[0]
        
        # Get next available index
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT COALESCE(MAX(derivation_index), -1) as max_idx
                FROM user_crypto_addresses
                WHERE crypto_type = {placeholder}
            """, (crypto_type,))
            max_index = cursor.fetchone()
        
        next_index = max_index[0] + 1
        
        # Derive new address
        address_info = self.derive_address(crypto_type, next_index)
        
        # Store in database
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                INSERT INTO user_crypto_addresses
                (user_id, crypto_type, address, derivation_path, derivation_index)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (
                user_id,
                crypto_type,
                address_info['address'],
                address_info['derivation_path'],
                address_info['derivation_index']
            ))
            conn.commit()
        
        # Create wallet entry
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                INSERT INTO user_crypto_wallets
                (user_id, crypto_type, balance_crypto, balance_fiat)
                VALUES ({placeholder}, {placeholder}, 0, 0)
            """, (user_id, crypto_type))
            conn.commit()
        
        logger.info(f"Created {crypto_type} address for user {user_id}: {address_info['address']}")
        
        return address_info['address']
