"""
Smart payment retry logic for failed subscription payments

Implements different retry strategies:
- Crypto: Retry immediately when wallet balance is sufficient
- Fiat: Retry daily (fixed schedule)
- Max 3 attempts, then downgrade to free tier
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


class PaymentRetryProcessor:
    """Process payment retries with smart retry logic"""
    
    def __init__(self, db_manager, subscription_manager):
        self.db = db_manager
        self.subscription_manager = subscription_manager
    
    async def process_retries(self) -> Dict:
        """Process all pending payment retries"""
        # Get pending retries that are due
        now = datetime.utcnow().isoformat()
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT * FROM payment_retry_queue
                WHERE status = 'pending'
                AND next_retry_at <= {placeholder}
            """, (now,))
            retries = cursor.fetchall()
        
        processed = 0
        successful = 0
        failed = 0
        
        for retry_row in retries:
            retry = dict(zip([col[0] for col in cursor.description], retry_row))
            result = await self._process_single_retry(retry)
            
            processed += 1
            if result['success']:
                successful += 1
            else:
                failed += 1
        
        logger.info(f"Processed {processed} retries: {successful} successful, {failed} failed")
        
        return {
            'processed': processed,
            'successful': successful,
            'failed': failed
        }
    
    async def _process_single_retry(self, retry: dict) -> Dict:
        """Process a single retry attempt"""
        try:
            retry_id = retry['id']
            subscription_id = retry['subscription_id']
            user_id = retry['user_id']
            payment_method_type = retry['payment_method_type']
            amount = float(retry['amount'])
            attempt_count = retry['attempt_count']
            max_attempts = retry['max_attempts']
            
            # Check if this is a crypto payment and wallet has sufficient balance
            if payment_method_type == 'crypto':
                can_retry = await self._check_crypto_balance(user_id, amount)
                if not can_retry:
                    # Wallet still insufficient, skip this retry
                    logger.info(f"Crypto wallet still insufficient for retry {retry_id}, skipping")
                    return {'success': False, 'reason': 'insufficient_balance'}
            
            # Attempt payment
            payment_result = await self._attempt_payment(subscription_id, amount)
            
            if payment_result['success']:
                # Payment succeeded, mark retry as completed
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                    cursor.execute(f"""
                        UPDATE payment_retry_queue
                        SET status = 'completed',
                            completed_at = datetime('now')
                        WHERE id = {placeholder}
                    """, (retry_id,))
                    conn.commit()
                
                logger.info(f"Retry {retry_id} succeeded for subscription {subscription_id}")
                return {'success': True}
            
            else:
                # Payment failed, increment attempt count
                new_attempt_count = attempt_count + 1
                
                if new_attempt_count >= max_attempts:
                    # Max attempts reached, downgrade to free tier
                    await self._handle_max_retries_exceeded(subscription_id, user_id, retry_id)
                    return {'success': False, 'reason': 'max_attempts_exceeded'}
                
                else:
                    # Schedule next retry
                    if payment_method_type == 'crypto':
                        # Crypto: Check again on next process_retries() call
                        next_retry_at = datetime.utcnow()
                    else:
                        # Fiat: Retry daily
                        next_retry_at = datetime.utcnow() + timedelta(days=1)
                    
                    with self.db._get_connection() as conn:
                        cursor = conn.cursor()
                        placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                        cursor.execute(f"""
                            UPDATE payment_retry_queue
                            SET attempt_count = {placeholder},
                                next_retry_at = {placeholder},
                                last_attempt_at = datetime('now')
                            WHERE id = {placeholder}
                        """, (new_attempt_count, next_retry_at.isoformat(), retry_id))
                        conn.commit()
                    
                    logger.info(f"Retry {retry_id} failed, attempt {new_attempt_count}/{max_attempts}")
                    return {'success': False, 'reason': 'payment_failed'}
        
        except Exception as e:
            logger.error(f"Error processing retry {retry.get('id')}: {e}")
            return {'success': False, 'reason': str(e)}
    
    async def _check_crypto_balance(self, user_id: int, required_amount: float) -> bool:
        """Check if user's crypto wallet has sufficient balance"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT SUM(balance_fiat) as total_balance
                FROM user_crypto_wallets
                WHERE user_id = {placeholder}
            """, (user_id,))
            result = cursor.fetchone()
        
        if result and result[0]:
            total_balance = float(result[0])
            return total_balance >= required_amount
        
        return False
    
    async def _attempt_payment(self, subscription_id: int, amount: float) -> Dict:
        """Attempt to charge payment for subscription"""
        # Get subscription details
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                SELECT s.*, pm.type as payment_type
                FROM subscriptions s
                JOIN payment_methods pm ON s.payment_method_id = pm.id
                WHERE s.id = {placeholder}
            """, (subscription_id,))
            result = cursor.fetchone()
        
        if not result:
            return {'success': False, 'error': 'Subscription not found'}
        
        subscription = dict(zip([col[0] for col in cursor.description], result))
        payment_type = subscription['payment_type']
        
        # Attempt payment based on type
        if payment_type == 'crypto':
            return await self._charge_crypto_wallet(subscription['user_id'], amount)
        elif payment_type == 'stripe' or payment_type == 'card':
            return await self._charge_stripe(subscription, amount)
        elif payment_type == 'paypal':
            return await self._charge_paypal(subscription, amount)
        else:
            return {'success': False, 'error': f'Unknown payment type: {payment_type}'}
    
    async def _charge_crypto_wallet(self, user_id: int, amount: float) -> Dict:
        """Charge crypto wallet"""
        try:
            # Check total balance across all crypto wallets
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    SELECT id, crypto_type, balance_fiat
                    FROM user_crypto_wallets
                    WHERE user_id = {placeholder}
                    AND balance_fiat > 0
                    ORDER BY balance_fiat DESC
                """, (user_id,))
                wallets = cursor.fetchall()
            
            if not wallets:
                return {'success': False, 'error': 'No crypto wallets found'}
            
            # Calculate total balance
            total_balance = sum(float(w[2]) for w in wallets)
            
            if total_balance < amount:
                return {'success': False, 'error': 'Insufficient balance'}
            
            # Deduct from wallets (largest first)
            remaining = amount
            for wallet in wallets:
                if remaining <= 0:
                    break
                
                wallet_id = wallet[0]
                wallet_balance = float(wallet[2])
                
                deduct = min(wallet_balance, remaining)
                
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                    cursor.execute(f"""
                        UPDATE user_crypto_wallets
                        SET balance_fiat = balance_fiat - {placeholder}
                        WHERE id = {placeholder}
                    """, (deduct, wallet_id))
                    conn.commit()
                
                remaining -= deduct
            
            logger.info(f"Charged ${amount} from crypto wallet for user {user_id}")
            return {'success': True, 'transaction_id': f'crypto_{user_id}_{datetime.utcnow().timestamp()}'}
        
        except Exception as e:
            logger.error(f"Error charging crypto wallet: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _charge_stripe(self, subscription: dict, amount: float) -> Dict:
        """Charge via Stripe (placeholder)"""
        # In production, would call Stripe API
        logger.info(f"Would charge ${amount} via Stripe for subscription {subscription['id']}")
        return {'success': True, 'transaction_id': f"stripe_{subscription['id']}"}
    
    async def _charge_paypal(self, subscription: dict, amount: float) -> Dict:
        """Charge via PayPal (placeholder)"""
        # In production, would call PayPal API
        logger.info(f"Would charge ${amount} via PayPal for subscription {subscription['id']}")
        return {'success': True, 'transaction_id': f"paypal_{subscription['id']}"}
    
    async def _handle_max_retries_exceeded(self, subscription_id: int, user_id: int, retry_id: int):
        """Handle case where max retry attempts exceeded"""
        try:
            # Mark retry as failed
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    UPDATE payment_retry_queue
                    SET status = 'failed',
                        completed_at = datetime('now')
                    WHERE id = {placeholder}
                """, (retry_id,))
                conn.commit()
            
            # Cancel subscription and downgrade to free tier
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    UPDATE subscriptions
                    SET status = 'cancelled',
                        cancelled_at = datetime('now')
                    WHERE id = {placeholder}
                """, (subscription_id,))
                conn.commit()
            
            # Get free tier ID
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM tiers WHERE is_default = TRUE OR name = 'Free' LIMIT 1")
                free_tier = cursor.fetchone()
            
            if free_tier:
                free_tier_id = free_tier[0]
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                    cursor.execute(f"""
                        UPDATE users
                        SET tier_id = {placeholder}
                        WHERE id = {placeholder}
                    """, (free_tier_id, user_id))
                    conn.commit()
            
            logger.warning(f"Max retries exceeded for subscription {subscription_id}, downgraded user {user_id} to free tier")
        
        except Exception as e:
            logger.error(f"Error handling max retries exceeded: {e}")
    
    async def add_to_retry_queue(self, subscription_id: int, user_id: int, 
                                 payment_method_type: str, amount: float) -> Dict:
        """Add failed payment to retry queue"""
        try:
            # Determine next retry time based on payment type
            if payment_method_type == 'crypto':
                # Crypto: Check immediately on next process
                next_retry_at = datetime.utcnow()
            else:
                # Fiat: Retry in 24 hours
                next_retry_at = datetime.utcnow() + timedelta(days=1)
            
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    INSERT INTO payment_retry_queue
                    (subscription_id, user_id, payment_method_type, amount, 
                     attempt_count, max_attempts, next_retry_at, status)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                            0, 3, {placeholder}, 'pending')
                """, (subscription_id, user_id, payment_method_type, amount, 
                      next_retry_at.isoformat()))
                conn.commit()
            
            logger.info(f"Added subscription {subscription_id} to retry queue")
            return {'success': True}
        
        except Exception as e:
            logger.error(f"Error adding to retry queue: {e}")
            return {'success': False, 'error': str(e)}
