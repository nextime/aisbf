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
        from aisbf.payments.fiat.stripe_handler import StripePaymentHandler
        from aisbf.payments.fiat.paypal_handler import PayPalPaymentHandler
        
        self.wallet_manager = CryptoWalletManager(db_manager, config['encryption_key'])
        self.price_service = CryptoPriceService(db_manager, config)
        self.blockchain_monitor = BlockchainMonitor(db_manager, config)
        self.stripe_handler = StripePaymentHandler(db_manager, config)
        self.paypal_handler = PayPalPaymentHandler(db_manager, config)
        
        # Initialize subscription sub-services
        from aisbf.payments.subscription.manager import SubscriptionManager
        from aisbf.payments.subscription.renewal import SubscriptionRenewalProcessor
        
        self.subscription_manager = SubscriptionManager(
            db_manager,
            self.stripe_handler,
            self.paypal_handler,
            self.wallet_manager,
            self.price_service
        )
        
        self.renewal_processor = SubscriptionRenewalProcessor(
            db_manager,
            self.stripe_handler,
            self.paypal_handler,
            self.wallet_manager,
            self.price_service
        )
    
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
    
    async def add_stripe_payment_method(self, user_id: int, payment_method_id: str) -> dict:
        """Add Stripe payment method for user"""
        try:
            result = await self.stripe_handler.add_payment_method(user_id, payment_method_id)
            return result
        except Exception as e:
            logger.error(f"Error adding Stripe payment method: {e}")
            return {'success': False, 'error': str(e)}
    
    async def initiate_paypal_billing_agreement(self, user_id: int, return_url: str, cancel_url: str) -> dict:
        """Initiate PayPal billing agreement setup"""
        try:
            result = await self.paypal_handler.create_billing_agreement(
                user_id, 
                return_url, 
                cancel_url
            )
            return result
        except Exception as e:
            logger.error(f"Error initiating PayPal billing agreement: {e}")
            return {'success': False, 'error': str(e)}
    
    async def complete_paypal_billing_agreement(self, user_id: int, token: str) -> dict:
        """Complete PayPal billing agreement after user approval"""
        try:
            result = await self.paypal_handler.execute_billing_agreement(user_id, token)
            return result
        except Exception as e:
            logger.error(f"Error completing PayPal billing agreement: {e}")
            return {'success': False, 'error': str(e)}
    
    async def get_payment_methods(self, user_id: int) -> list:
        """Get all payment methods for user"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    SELECT id, type, gateway, crypto_type, last4, brand, 
                           paypal_email, is_default, status, created_at
                    FROM payment_methods
                    WHERE user_id = {placeholder}
                    ORDER BY is_default DESC, created_at DESC
                """, (user_id,))
                methods = cursor.fetchall()
            
            return [
                {
                    'id': method[0],
                    'type': method[1],
                    'gateway': method[2],
                    'crypto_type': method[3],
                    'last4': method[4],
                    'brand': method[5],
                    'paypal_email': method[6],
                    'is_default': bool(method[7]),
                    'status': method[8],
                    'created_at': method[9]
                }
                for method in methods
            ]
        except Exception as e:
            logger.error(f"Error getting payment methods: {e}")
            return []
    
    async def delete_payment_method(self, user_id: int, payment_method_id: int) -> dict:
        """Delete payment method with validation"""
        try:
            # Check if payment method is used by active subscription
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                
                # Verify ownership
                cursor.execute(f"""
                    SELECT id, type, gateway FROM payment_methods
                    WHERE id = {placeholder} AND user_id = {placeholder}
                """, (payment_method_id, user_id))
                method = cursor.fetchone()
                
                if not method:
                    return {'success': False, 'error': 'Payment method not found'}
                
                # Check for active subscriptions using this method
                cursor.execute(f"""
                    SELECT COUNT(*) FROM subscriptions
                    WHERE user_id = {placeholder} 
                    AND payment_method_id = {placeholder}
                    AND status IN ('active', 'trialing')
                """, (user_id, payment_method_id))
                active_count = cursor.fetchone()[0]
                
                if active_count > 0:
                    return {
                        'success': False, 
                        'error': 'Cannot delete payment method used by active subscription'
                    }
                
                # Delete from gateway if needed
                method_type = method[1]
                gateway = method[2]
                
                if method_type == 'card' and gateway == 'stripe':
                    await self.stripe_handler.delete_payment_method(user_id, payment_method_id)
                elif method_type == 'paypal':
                    await self.paypal_handler.cancel_billing_agreement(user_id, payment_method_id)
                
                # Delete from database
                cursor.execute(f"""
                    DELETE FROM payment_methods
                    WHERE id = {placeholder} AND user_id = {placeholder}
                """, (payment_method_id, user_id))
                conn.commit()
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error deleting payment method: {e}")
            return {'success': False, 'error': str(e)}
    
    async def create_subscription(self, user_id: int, tier_id: int, 
                                 payment_method_id: int, 
                                 billing_cycle: str) -> dict:
        """Create new subscription"""
        return await self.subscription_manager.create_subscription(
            user_id, tier_id, payment_method_id, billing_cycle
        )
    
    async def upgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
        """Upgrade subscription"""
        return await self.subscription_manager.upgrade_subscription(user_id, new_tier_id)
    
    async def downgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
        """Downgrade subscription"""
        return await self.subscription_manager.downgrade_subscription(user_id, new_tier_id)
    
    async def cancel_subscription(self, user_id: int) -> dict:
        """Cancel subscription"""
        return await self.subscription_manager.cancel_subscription(user_id)
    
    async def get_subscription_status(self, user_id: int) -> dict:
        """Get user's subscription status"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT s.*, t.name as tier_name, t.price_monthly, t.price_yearly,
                       pm.type as payment_type, pm.gateway
                FROM subscriptions s
                JOIN tiers t ON s.tier_id = t.id
                LEFT JOIN payment_methods pm ON s.payment_method_id = pm.id
                WHERE s.user_id = {placeholder}
                ORDER BY s.created_at DESC
                LIMIT 1
            """, (user_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Get column names
            columns = [desc[0] for desc in cursor.description]
            subscription = dict(zip(columns, row))
            
            return subscription
    
    async def process_renewals(self):
        """Process subscription renewals (called by scheduler)"""
        await self.renewal_processor.process_due_renewals()
    
    async def process_retries(self):
        """Process payment retries (called by scheduler)"""
        await self.renewal_processor.process_retry_queue()
