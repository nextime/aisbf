"""
Wallet Consolidation Service

Consolidates cryptocurrency payments from user addresses to admin addresses
when balances exceed configured thresholds. Respects pending payments to
avoid consolidating reserved amounts.
"""
import logging
from typing import Dict, Optional
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class WalletConsolidator:
    """
    Consolidates crypto payments to admin addresses.
    
    Monitors user wallet balances and transfers funds to admin addresses
    when they exceed configured thresholds, while respecting pending payments.
    """
    
    def __init__(self, db_manager, wallet_manager):
        """
        Initialize wallet consolidator.
        
        Args:
            db_manager: DatabaseManager instance
            wallet_manager: CryptoWalletManager instance
        """
        self.db = db_manager
        self.wallet_manager = wallet_manager
    
    async def consolidate_wallets(self):
        """
        Main entry point for wallet consolidation.
        
        Called by background scheduler periodically.
        Checks all user wallets and consolidates when above threshold.
        """
        logger.info("Starting wallet consolidation...")
        
        try:
            # Get enabled consolidation settings
            settings = self._get_consolidation_settings()
            
            for crypto_type, config in settings.items():
                if config['enabled']:
                    await self._consolidate_crypto_type(
                        crypto_type,
                        config['threshold'],
                        config['admin_address']
                    )
            
            logger.info("Wallet consolidation completed")
        except Exception as e:
            logger.error(f"Error during wallet consolidation: {e}", exc_info=True)
    
    def _get_consolidation_settings(self) -> Dict:
        """
        Get consolidation settings for all crypto types.
        
        Returns:
            Dict mapping crypto_type to config dict with keys:
                - threshold: Decimal amount threshold
                - admin_address: Admin address to consolidate to
                - enabled: Boolean
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT crypto_type, threshold_amount, admin_address, is_enabled
                FROM crypto_consolidation_settings
            """)
            rows = cursor.fetchall()
        
        return {
            row[0]: {
                'threshold': Decimal(str(row[1])),
                'admin_address': row[2],
                'enabled': bool(row[3])
            }
            for row in rows
        }
    
    async def _consolidate_crypto_type(
        self,
        crypto_type: str,
        threshold: Decimal,
        admin_address: str
    ):
        """
        Consolidate wallets for a specific crypto type.
        
        Args:
            crypto_type: Crypto type (btc, eth, usdt, usdc)
            threshold: Minimum balance to trigger consolidation
            admin_address: Admin address to send funds to
        """
        logger.info(f"Checking {crypto_type} wallets for consolidation (threshold: {threshold})")
        
        # Get all user wallets above threshold
        wallets = self._get_wallets_above_threshold(crypto_type, threshold)
        
        if not wallets:
            logger.debug(f"No {crypto_type} wallets above threshold")
            return
        
        logger.info(f"Found {len(wallets)} {crypto_type} wallets to consolidate")
        
        # Process each wallet
        for user_id, balance, address in wallets:
            try:
                # Calculate available balance (excluding pending payments)
                available = await self._get_available_balance(user_id, crypto_type, balance)
                
                if available >= threshold:
                    await self._queue_consolidation(
                        user_id,
                        crypto_type,
                        address,
                        admin_address,
                        available
                    )
            except Exception as e:
                logger.error(f"Error consolidating wallet for user {user_id}: {e}")
    
    def _get_wallets_above_threshold(
        self,
        crypto_type: str,
        threshold: Decimal
    ) -> list:
        """
        Get user wallets with balance above threshold.
        
        Args:
            crypto_type: Crypto type to check
            threshold: Minimum balance threshold
            
        Returns:
            List of tuples: (user_id, balance_crypto, address)
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                SELECT w.user_id, w.balance_crypto, a.address
                FROM user_crypto_wallets w
                JOIN user_crypto_addresses a ON w.user_id = a.user_id AND w.crypto_type = a.crypto_type
                WHERE w.crypto_type = {placeholder}
                AND w.balance_crypto >= {placeholder}
            """, (crypto_type, str(threshold)))
            
            return cursor.fetchall()
    
    async def _get_available_balance(
        self,
        user_id: int,
        crypto_type: str,
        total_balance: Decimal
    ) -> Decimal:
        """
        Calculate available balance excluding pending payments.
        
        Args:
            user_id: User ID
            crypto_type: Crypto type
            total_balance: Total wallet balance
            
        Returns:
            Available balance (total - pending)
        """
        # Get pending payment amounts
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                SELECT COALESCE(SUM(amount_crypto), 0)
                FROM crypto_transactions
                WHERE user_id = {placeholder}
                AND crypto_type = {placeholder}
                AND status IN ('pending', 'confirming')
            """, (user_id, crypto_type))
            
            pending = cursor.fetchone()[0]
        
        available = Decimal(str(total_balance)) - Decimal(str(pending))
        return max(available, Decimal('0'))
    
    async def _queue_consolidation(
        self,
        user_id: int,
        crypto_type: str,
        from_address: str,
        to_address: str,
        amount: Decimal
    ):
        """
        Queue a consolidation transaction.
        
        Args:
            user_id: User ID
            crypto_type: Crypto type
            from_address: User's address
            to_address: Admin address
            amount: Amount to consolidate
        """
        logger.info(f"Queueing consolidation: {amount} {crypto_type} from user {user_id}")
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Check if already queued
            cursor.execute(f"""
                SELECT id FROM crypto_consolidation_queue
                WHERE user_id = {placeholder}
                AND crypto_type = {placeholder}
                AND status = 'pending'
            """, (user_id, crypto_type))
            
            if cursor.fetchone():
                logger.debug(f"Consolidation already queued for user {user_id}")
                return
            
            # Queue consolidation
            cursor.execute(f"""
                INSERT INTO crypto_consolidation_queue
                (user_id, crypto_type, from_address, to_address, amount, status)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 'pending')
            """, (user_id, crypto_type, from_address, to_address, str(amount)))
            
            conn.commit()
        
        logger.info(f"Consolidation queued for user {user_id}")
    
    async def process_consolidation_queue(self):
        """
        Process pending consolidation transactions.
        
        Called by background scheduler to execute queued consolidations.
        """
        logger.info("Processing consolidation queue...")
        
        try:
            # Get pending consolidations
            pending = self._get_pending_consolidations()
            
            if not pending:
                logger.debug("No pending consolidations")
                return
            
            logger.info(f"Processing {len(pending)} pending consolidations")
            
            for consolidation in pending:
                try:
                    await self._execute_consolidation(consolidation)
                except Exception as e:
                    logger.error(f"Error executing consolidation {consolidation['id']}: {e}")
                    self._mark_consolidation_failed(consolidation['id'], str(e))
            
            logger.info("Consolidation queue processing completed")
        except Exception as e:
            logger.error(f"Error processing consolidation queue: {e}", exc_info=True)
    
    def _get_pending_consolidations(self) -> list:
        """
        Get pending consolidation transactions.
        
        Returns:
            List of consolidation dicts
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, crypto_type, from_address, to_address, amount
                FROM crypto_consolidation_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 10
            """)
            
            rows = cursor.fetchall()
        
        return [
            {
                'id': row[0],
                'user_id': row[1],
                'crypto_type': row[2],
                'from_address': row[3],
                'to_address': row[4],
                'amount': Decimal(str(row[5]))
            }
            for row in rows
        ]
    
    async def _execute_consolidation(self, consolidation: dict):
        """
        Execute a consolidation transaction.
        
        Args:
            consolidation: Consolidation dict with keys:
                - id: Queue entry ID
                - user_id: User ID
                - crypto_type: Crypto type
                - from_address: Source address
                - to_address: Destination address
                - amount: Amount to transfer
        """
        logger.info(f"Executing consolidation {consolidation['id']}")
        
        # Mark as processing
        self._update_consolidation_status(consolidation['id'], 'processing')
        
        # In a real implementation, this would:
        # 1. Get private key for from_address from wallet manager
        # 2. Create and sign transaction
        # 3. Broadcast to blockchain
        # 4. Wait for confirmation
        
        # For now, simulate successful consolidation
        tx_hash = f"consolidation_{consolidation['id']}_simulated"
        
        # Update user wallet balance
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                UPDATE user_crypto_wallets
                SET balance_crypto = balance_crypto - {placeholder}
                WHERE user_id = {placeholder}
                AND crypto_type = {placeholder}
            """, (str(consolidation['amount']), consolidation['user_id'], consolidation['crypto_type']))
            
            conn.commit()
        
        # Mark as completed
        self._mark_consolidation_completed(consolidation['id'], tx_hash)
        
        logger.info(f"Consolidation {consolidation['id']} completed: {tx_hash}")
    
    def _update_consolidation_status(self, consolidation_id: int, status: str):
        """Update consolidation status"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                UPDATE crypto_consolidation_queue
                SET status = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE id = {placeholder}
            """, (status, consolidation_id))
            
            conn.commit()
    
    def _mark_consolidation_completed(self, consolidation_id: int, tx_hash: str):
        """Mark consolidation as completed"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                UPDATE crypto_consolidation_queue
                SET status = 'completed',
                    tx_hash = {placeholder},
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = {placeholder}
            """, (tx_hash, consolidation_id))
            
            conn.commit()
    
    def _mark_consolidation_failed(self, consolidation_id: int, error: str):
        """Mark consolidation as failed"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                UPDATE crypto_consolidation_queue
                SET status = 'failed',
                    error_message = {placeholder},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = {placeholder}
            """, (error, consolidation_id))
            
            conn.commit()
