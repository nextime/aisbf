"""
Subscription lifecycle management
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manage subscription lifecycle and billing"""
    
    def __init__(self, db_manager, stripe_handler, paypal_handler, 
                 crypto_wallet_manager, price_service):
        self.db = db_manager
        self.stripe = stripe_handler
        self.paypal = paypal_handler
        self.crypto = crypto_wallet_manager
        self.price_service = price_service
    
    async def create_subscription(self, user_id: int, tier_id: int, 
                                 payment_method_id: int, 
                                 billing_cycle: str) -> dict:
        """Create new subscription"""
        try:
            # Get tier details
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM account_tiers WHERE id = ?",
                    (tier_id,)
                )
                tier_row = cursor.fetchone()
            
            if not tier_row:
                return {'success': False, 'error': 'Invalid tier'}
            
            # Convert row to dict
            tier = {
                'id': tier_row[0],
                'name': tier_row[1],
                'price_monthly': tier_row[2],
                'price_yearly': tier_row[3]
            }
            
            # Get payment method
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM payment_methods WHERE id = ? AND user_id = ?",
                    (payment_method_id, user_id)
                )
                pm_row = cursor.fetchone()
            
            if not pm_row:
                return {'success': False, 'error': 'Invalid payment method'}
            
            # Convert row to dict
            payment_method = {
                'id': pm_row[0],
                'user_id': pm_row[1],
                'type': pm_row[2],
                'gateway': pm_row[3],
                'crypto_type': pm_row[4] if len(pm_row) > 4 else None
            }
            
            # Calculate amount
            if billing_cycle == 'monthly':
                amount = tier['price_monthly']
            elif billing_cycle == 'yearly':
                amount = tier['price_yearly']
            else:
                return {'success': False, 'error': 'Invalid billing cycle'}
            
            # Check if user already has active subscription
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM subscriptions 
                    WHERE user_id = ? AND status = 'active'
                """, (user_id,))
                existing = cursor.fetchone()
            
            if existing:
                return {'success': False, 'error': 'User already has active subscription'}
            
            # Calculate period dates (immediate start)
            current_period_start = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).replace(tzinfo=None)
            if billing_cycle == 'monthly':
                current_period_end = current_period_start + timedelta(days=30)
            else:  # yearly
                current_period_end = current_period_start + timedelta(days=365)
            
            # Charge initial payment
            charge_result = await self._charge_payment(
                user_id=user_id,
                payment_method=payment_method,
                amount=amount,
                description=f"Initial subscription - {tier['name']} ({billing_cycle})"
            )
            
            if not charge_result['success']:
                return charge_result
            
            # Create subscription
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO subscriptions
                    (user_id, tier_id, payment_method_id, status, billing_cycle,
                     current_period_start, current_period_end)
                    VALUES (?, ?, ?, 'active', ?, ?, ?)
                """, (
                    user_id, tier_id, payment_method_id, billing_cycle,
                    current_period_start, current_period_end
                ))
                conn.commit()
                subscription_id = cursor.lastrowid
            
            # Update user tier
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET tier_id = ? WHERE id = ?",
                    (tier_id, user_id)
                )
                conn.commit()
            
            logger.info(f"Created subscription {subscription_id} for user {user_id}")
            
            return {
                'success': True,
                'subscription_id': subscription_id,
                'next_billing_date': current_period_end.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _charge_payment(self, user_id: int, payment_method: dict, 
                             amount: float, description: str) -> dict:
        """Charge payment using appropriate gateway"""
        payment_type = payment_method['type']
        
        if payment_type == 'card':
            # Stripe card payment
            if self.stripe:
                # Would call stripe handler
                return {'success': True, 'transaction_id': 'mock_tx'}
            return {'success': True, 'transaction_id': 'mock_tx'}
        elif payment_type == 'paypal':
            # PayPal payment
            if self.paypal:
                # Would call paypal handler
                return {'success': True, 'transaction_id': 'mock_tx'}
            return {'success': True, 'transaction_id': 'mock_tx'}
        elif payment_type == 'crypto':
            return await self._charge_crypto_wallet(
                user_id=user_id,
                crypto_type=payment_method['crypto_type'],
                amount=amount
            )
        else:
            return {'success': False, 'error': f'Unknown payment method type: {payment_type}'}
    
    async def _charge_crypto_wallet(self, user_id: int, crypto_type: str, 
                                   amount: float) -> dict:
        """Charge from user's crypto wallet"""
        try:
            # Get wallet balance
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM user_crypto_wallets
                    WHERE user_id = ? AND crypto_type = ?
                """, (user_id, crypto_type))
                wallet_row = cursor.fetchone()
            
            if not wallet_row:
                return {'success': False, 'error': 'Wallet not found'}
            
            wallet = {
                'balance_fiat': wallet_row[3]  # balance_fiat column
            }
            
            if wallet['balance_fiat'] < amount:
                return {'success': False, 'error': 'Insufficient balance'}
            
            # Deduct from wallet
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_crypto_wallets
                    SET balance_fiat = balance_fiat - ?
                    WHERE user_id = ? AND crypto_type = ?
                """, (amount, user_id, crypto_type))
                conn.commit()
            
            logger.info(f"Charged ${amount} from user {user_id} {crypto_type} wallet")
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error charging crypto wallet: {e}")
            return {'success': False, 'error': str(e)}
    
    async def upgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
        """Upgrade subscription to higher tier with prorated credit"""
        try:
            # Get current subscription
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT s.id, s.user_id, s.tier_id, s.payment_method_id, s.status, 
                           s.billing_cycle, s.current_period_start, s.current_period_end,
                           t.price_monthly, t.price_yearly, t.name as tier_name
                    FROM subscriptions s
                    JOIN account_tiers t ON s.tier_id = t.id
                    WHERE s.user_id = ? AND s.status = 'active'
                """, (user_id,))
                sub_row = cursor.fetchone()
            
            if not sub_row:
                return {'success': False, 'error': 'No active subscription'}
            
            # Convert row to dict
            subscription = {
                'id': sub_row[0],
                'user_id': sub_row[1],
                'tier_id': sub_row[2],
                'payment_method_id': sub_row[3],
                'status': sub_row[4],
                'billing_cycle': sub_row[5],
                'current_period_start': sub_row[6],
                'current_period_end': sub_row[7],
                'price_monthly': sub_row[8],
                'price_yearly': sub_row[9],
                'tier_name': sub_row[10]
            }
            
            # Get new tier
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, name, price_monthly, price_yearly FROM account_tiers WHERE id = ?",
                    (new_tier_id,)
                )
                tier_row = cursor.fetchone()
            
            if not tier_row:
                return {'success': False, 'error': 'Invalid tier'}
            
            new_tier = {
                'id': tier_row[0],
                'name': tier_row[1],
                'price_monthly': tier_row[2],
                'price_yearly': tier_row[3]
            }
            
            # Calculate prorated amount
            billing_cycle = subscription['billing_cycle']
            
            if billing_cycle == 'monthly':
                old_price = subscription['price_monthly']
                new_price = new_tier['price_monthly']
            else:  # yearly
                old_price = subscription['price_yearly']
                new_price = new_tier['price_yearly']
            
            if old_price is None or new_price is None:
                return {'success': False, 'error': f'Invalid prices: old={old_price}, new={new_price}'}
            
            # Calculate unused portion of current period
            now = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).replace(tzinfo=None)
            
            # Parse datetime strings if needed
            period_start = subscription['current_period_start']
            period_end = subscription['current_period_end']
            
            if isinstance(period_start, str):
                period_start = datetime.fromisoformat(period_start)
            if isinstance(period_end, str):
                period_end = datetime.fromisoformat(period_end)
            
            total_period_seconds = (period_end - period_start).total_seconds()
            remaining_seconds = (period_end - now).total_seconds()
            
            if remaining_seconds <= 0:
                # Period already ended, charge full amount
                prorated_amount = new_price
                unused_fraction = 0
            else:
                # Calculate unused portion
                unused_fraction = remaining_seconds / total_period_seconds
                unused_credit = old_price * unused_fraction
                
                # New charge = new_price - unused_credit
                prorated_amount = new_price - unused_credit
                
                # Ensure non-negative
                prorated_amount = max(0, prorated_amount)
            
            logger.info(f"Upgrade proration: old=${old_price}, new=${new_price}, "
                       f"unused={unused_fraction:.2%}, charge=${prorated_amount:.2f}")
            
            # Get payment method
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM payment_methods WHERE id = ?",
                    (subscription['payment_method_id'],)
                )
                pm_row = cursor.fetchone()
            
            if not pm_row:
                return {'success': False, 'error': 'Payment method not found'}
            
            payment_method = {
                'id': pm_row[0],
                'user_id': pm_row[1],
                'type': pm_row[2],
                'gateway': pm_row[3],
                'crypto_type': pm_row[4] if len(pm_row) > 4 else None
            }
            
            # Charge prorated amount
            if prorated_amount > 0:
                charge_result = await self._charge_payment(
                    user_id=user_id,
                    payment_method=payment_method,
                    amount=prorated_amount,
                    description=f"Upgrade to {new_tier['name']} (prorated)"
                )
                
                if not charge_result['success']:
                    return charge_result
            
            # Update subscription
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE subscriptions
                    SET tier_id = ?
                    WHERE id = ?
                """, (new_tier_id, subscription['id']))
                conn.commit()
            
            # Update user tier
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET tier_id = ? WHERE id = ?",
                    (new_tier_id, user_id)
                )
                conn.commit()
            
            logger.info(f"Upgraded subscription {subscription['id']} to tier {new_tier_id}")
            
            return {
                'success': True,
                'charged_amount': prorated_amount,
                'next_billing_date': period_end.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error upgrading subscription: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}
