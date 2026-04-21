"""
Blockchain monitoring service for detecting incoming cryptocurrency transactions.

Uses API polling mode - periodically checks blockchain APIs for transactions
to user addresses. Tracks confirmations and credits user wallets when confirmed.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from decimal import Decimal

import httpx

from aisbf.payments.crypto.pricing import CryptoPriceService

logger = logging.getLogger(__name__)


class BlockchainMonitor:
    """
    Monitors blockchain for incoming transactions to user addresses.
    
    Uses API polling mode - checks blockchain APIs every 60 seconds.
    Tracks transaction confirmations and credits user wallets when confirmed.
    """
    
    def __init__(self, db_manager, config: Dict):
        """
        Initialize blockchain monitor.
        
        Args:
            db_manager: DatabaseManager instance
            config: Configuration dict with:
                - currency_code: Fiat currency (e.g., 'USD')
                - btc_confirmations: Required confirmations for BTC (default: 3)
                - eth_confirmations: Required confirmations for ETH (default: 12)
        """
        self.db = db_manager
        self.config = config
        self.price_service = CryptoPriceService(db_manager, config)
        
        # Required confirmations per crypto type
        self.required_confirmations = {
            'btc': config.get('btc_confirmations', 3),
            'eth': config.get('eth_confirmations', 12)
        }
    
    async def check_crypto_payments(self):
        """
        Main entry point for polling blockchain APIs.
        
        Called by background scheduler every 60 seconds.
        Checks all user addresses for new transactions.
        """
        logger.info("Starting blockchain payment check...")
        
        try:
            await self.poll_blockchain_apis()
            logger.info("Blockchain payment check completed")
        except Exception as e:
            logger.error(f"Error during blockchain payment check: {e}", exc_info=True)
    
    async def poll_blockchain_apis(self):
        """
        Poll blockchain APIs for all user addresses.
        
        Checks Bitcoin and Ethereum addresses concurrently.
        """
        # Run Bitcoin and Ethereum checks concurrently
        await asyncio.gather(
            self.check_bitcoin_addresses(),
            self.check_ethereum_addresses(),
            return_exceptions=True
        )
    
    async def check_bitcoin_addresses(self):
        """
        Check all Bitcoin addresses for transactions.
        
        Uses Blockchain.com API (free, no auth required).
        """
        # Get all Bitcoin addresses
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, address
                FROM user_crypto_addresses
                WHERE crypto_type = 'btc'
            """)
            addresses = cursor.fetchall()
        
        if not addresses:
            logger.debug("No Bitcoin addresses to check")
            return
        
        logger.info(f"Checking {len(addresses)} Bitcoin addresses...")
        
        # Check each address
        for address_id, user_id, address in addresses:
            try:
                transactions = await self._get_bitcoin_transactions(address)
                
                for tx in transactions:
                    await self.process_transaction(
                        user_id=user_id,
                        crypto_type='btc',
                        tx_hash=tx['hash'],
                        from_address=tx['from_address'],
                        to_address=address,
                        amount=tx['amount'],
                        confirmations=tx['confirmations']
                    )
            except Exception as e:
                logger.error(f"Error checking Bitcoin address {address}: {e}")
    
    async def _get_bitcoin_transactions(self, address: str) -> List[Dict]:
        """
        Fetch Bitcoin transactions from Blockchain.com API.
        
        Args:
            address: Bitcoin address to check
            
        Returns:
            List of transaction dicts with keys: hash, from_address, amount, confirmations
        """
        url = f"https://blockchain.info/rawaddr/{address}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        
        return self._parse_blockchain_com_btc(data, address)
    
    def _parse_blockchain_com_btc(self, data: Dict, target_address: str) -> List[Dict]:
        """
        Parse Blockchain.com API response for Bitcoin transactions.
        
        Args:
            data: API response data
            target_address: The address we're monitoring (to identify incoming txs)
            
        Returns:
            List of incoming transaction dicts
        """
        transactions = []
        
        for tx in data.get('txs', []):
            # Check if this transaction sends to our address
            for output in tx.get('out', []):
                if output.get('addr') == target_address:
                    # This is an incoming transaction
                    amount_satoshi = output.get('value', 0)
                    amount_btc = amount_satoshi / 100000000  # Convert satoshi to BTC
                    
                    # Get sender address (first input address)
                    from_address = None
                    if tx.get('inputs'):
                        prev_out = tx['inputs'][0].get('prev_out', {})
                        from_address = prev_out.get('addr', 'unknown')
                    
                    transactions.append({
                        'hash': tx['hash'],
                        'from_address': from_address or 'unknown',
                        'amount': amount_btc,
                        'confirmations': data.get('n_tx', 0)  # Use block height as proxy
                    })
        
        return transactions
    
    async def check_ethereum_addresses(self):
        """
        Check all Ethereum addresses for transactions.
        
        Placeholder - would use Etherscan/Infura API in production.
        """
        # Get all Ethereum addresses
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, address
                FROM user_crypto_addresses
                WHERE crypto_type = 'eth'
            """)
            addresses = cursor.fetchall()
        
        if not addresses:
            logger.debug("No Ethereum addresses to check")
            return
        
        logger.info(f"Checking {len(addresses)} Ethereum addresses (placeholder)...")
        # TODO: Implement Ethereum checking with Etherscan/Infura API
    
    async def process_transaction(
        self,
        user_id: int,
        crypto_type: str,
        tx_hash: str,
        from_address: str,
        to_address: str,
        amount: float,
        confirmations: int
    ):
        """
        Process a detected transaction.
        
        Creates new transaction record or updates existing one.
        Credits user wallet when transaction reaches required confirmations.
        
        Args:
            user_id: User ID
            crypto_type: Cryptocurrency type (e.g., 'btc', 'eth')
            tx_hash: Transaction hash
            from_address: Sender address
            to_address: Recipient address (user's address)
            amount: Amount in crypto
            confirmations: Current confirmation count
        """
        crypto_type = crypto_type.lower()
        required_confs = self.required_confirmations.get(crypto_type, 3)
        
        # Check if transaction already exists
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, status, confirmations FROM crypto_transactions WHERE tx_hash = ?",
                (tx_hash,)
            )
            existing = cursor.fetchone()
        
        if existing:
            # Update existing transaction
            tx_id, status, old_confirmations = existing
            
            # Only update if confirmations increased or status changed
            if confirmations > old_confirmations or status == 'pending':
                new_status = 'confirmed' if confirmations >= required_confs else 'pending'
                
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE crypto_transactions
                        SET confirmations = ?, status = ?, confirmed_at = ?
                        WHERE id = ?
                    """, (
                        confirmations,
                        new_status,
                        datetime.utcnow() if new_status == 'confirmed' else None,
                        tx_id
                    ))
                    conn.commit()
                
                logger.info(f"Updated transaction {tx_hash}: {confirmations} confirmations, status={new_status}")
                
                # Credit wallet if newly confirmed
                if new_status == 'confirmed' and status == 'pending':
                    await self.credit_user_wallet(user_id, crypto_type, amount, tx_id)
        else:
            # Create new transaction
            status = 'confirmed' if confirmations >= required_confs else 'pending'
            
            # Get address_id
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM user_crypto_addresses WHERE user_id = ? AND address = ?",
                    (user_id, to_address)
                )
                address_row = cursor.fetchone()
                address_id = address_row[0] if address_row else None
            
            if not address_id:
                logger.error(f"Address {to_address} not found for user {user_id}")
                return
            
            # Convert to fiat
            try:
                amount_fiat = await self.price_service.convert_crypto_to_fiat(crypto_type, amount)
            except Exception as e:
                logger.warning(f"Could not convert to fiat: {e}")
                amount_fiat = None
            
            # Insert transaction
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO crypto_transactions
                    (user_id, address_id, crypto_type, tx_hash, amount_crypto, amount_fiat,
                     confirmations, required_confirmations, status, detected_at, confirmed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    address_id,
                    crypto_type,
                    tx_hash,
                    amount,
                    amount_fiat,
                    confirmations,
                    required_confs,
                    status,
                    datetime.utcnow(),
                    datetime.utcnow() if status == 'confirmed' else None
                ))
                tx_id = cursor.lastrowid
                conn.commit()
            
            logger.info(f"Created transaction {tx_hash}: {amount} {crypto_type}, status={status}")
            
            # Credit wallet if confirmed
            if status == 'confirmed':
                await self.credit_user_wallet(user_id, crypto_type, amount, tx_id)
    
    async def credit_user_wallet(self, user_id: int, crypto_type: str, amount: float, tx_id: int):
        """
        Credit user's crypto wallet with confirmed transaction amount.

        Args:
            user_id: User ID
            crypto_type: Cryptocurrency type
            amount: Amount in crypto
            tx_id: Transaction ID
        """
        # Convert to fiat
        try:
            amount_fiat = await self.price_service.convert_crypto_to_fiat(crypto_type, amount)
        except Exception as e:
            logger.error(f"Could not convert to fiat for crediting: {e}")
            amount_fiat = 0

        # Update crypto wallet balance
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_crypto_wallets
                SET balance_crypto = balance_crypto + ?,
                    balance_fiat = balance_fiat + ?,
                    last_updated = ?
                WHERE user_id = ? AND crypto_type = ?
            """, (amount, amount_fiat, datetime.utcnow(), user_id, crypto_type))
            
            # Mark transaction as credited
            cursor.execute("""
                UPDATE crypto_transactions
                SET credited_at = ?
                WHERE id = ?
            """, (datetime.utcnow(), tx_id))
            
            conn.commit()

        # Also credit fiat wallet
        if amount_fiat > 0:
            from aisbf.payments.wallet.manager import WalletManager
            from sqlalchemy.ext.asyncio import AsyncSession
            
            try:
                async with AsyncSession(self.db.engine) as session:
                    wallet_manager = WalletManager(session)
                    await wallet_manager.credit_wallet(
                        user_id=user_id,
                        amount=Decimal(str(amount_fiat)),
                        transaction_details={
                            'payment_gateway': f'crypto_{crypto_type}',
                            'gateway_transaction_id': f'crypto_tx_{tx_id}',
                            'description': f'Wallet top up via {crypto_type.upper()} payment',
                            'metadata': {'crypto_amount': amount, 'crypto_type': crypto_type, 'tx_id': tx_id}
                        }
                    )
                    await session.commit()
                
                logger.info(f"Fiat wallet credited {amount_fiat:.2f} USD for user {user_id} from crypto payment")
            except Exception as e:
                logger.error(f"Error crediting fiat wallet from crypto payment: {e}")

        logger.info(f"Credited {amount} {crypto_type} (${amount_fiat:.2f}) to user {user_id}")
