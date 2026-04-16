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
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT crypto_type FROM crypto_consolidation_settings
                WHERE enabled = {placeholder}
            """, (True,))
            enabled_cryptos = cursor.fetchall()
        
        for crypto_config in enabled_cryptos:
            crypto_type = crypto_config[0]
            address = await self.wallet_manager.get_or_create_user_address(
                user_id, 
                crypto_type
            )
            addresses[crypto_type] = address
        
        return addresses
    
    async def get_user_wallet_balances(self, user_id: int) -> dict:
        """Get user's crypto wallet balances"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT crypto_type, balance_crypto, balance_fiat, last_updated
                FROM user_crypto_wallets
                WHERE user_id = {placeholder}
            """, (user_id,))
            wallets = cursor.fetchall()
        
        return {
            wallet[0]: {
                'balance_crypto': float(wallet[1]),
                'balance_fiat': float(wallet[2]),
                'last_sync': wallet[3]
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
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    INSERT INTO payment_methods
                    (user_id, type, gateway, crypto_type, is_default, status)
                    VALUES ({placeholder}, 'crypto', {placeholder}, {placeholder}, {placeholder}, 'active')
                """, (user_id, crypto_type, crypto_type, True))
                conn.commit()
            
            return {
                'success': True,
                'crypto_type': crypto_type,
                'address': address
            }
            
        except Exception as e:
            logger.error(f"Error adding crypto payment method: {e}")
            return {'success': False, 'error': str(e)}
