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
        """Fetch Bitcoin transactions from Blockchain.com API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            addr_resp = await client.get(f"https://blockchain.info/rawaddr/{address}?limit=25")
            addr_resp.raise_for_status()
            data = addr_resp.json()

            # Fetch latest block height for confirmation calculation
            try:
                block_resp = await client.get("https://blockchain.info/latestblock")
                block_resp.raise_for_status()
                data['latest_block'] = block_resp.json()
            except Exception:
                pass  # confirmations will be 0 if unavailable

        return self._parse_blockchain_com_btc(data, address)
    
    def _parse_blockchain_com_btc(self, data: Dict, target_address: str) -> List[Dict]:
        """Parse Blockchain.com API response for Bitcoin transactions."""
        transactions = []
        latest_block = data.get('latest_block', {}).get('height', 0)

        for tx in data.get('txs', []):
            for output in tx.get('out', []):
                if output.get('addr') == target_address:
                    amount_satoshi = output.get('value', 0)
                    amount_btc = amount_satoshi / 100_000_000

                    from_address = None
                    if tx.get('inputs'):
                        prev_out = tx['inputs'][0].get('prev_out', {})
                        from_address = prev_out.get('addr', 'unknown')

                    tx_block = tx.get('block_height')
                    confirmations = (latest_block - tx_block + 1) if tx_block else 0

                    transactions.append({
                        'hash': tx['hash'],
                        'from_address': from_address or 'unknown',
                        'amount': amount_btc,
                        'confirmations': confirmations,
                    })

        return transactions
    
    async def check_ethereum_addresses(self):
        """
        Check all Ethereum addresses (and ERC-20 tokens) for transactions.
        Uses Etherscan public API (no key required for basic polling).
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, address, crypto_type
                FROM user_crypto_addresses
                WHERE crypto_type IN ('eth', 'usdt', 'usdc')
            """)
            addresses = cursor.fetchall()

        if not addresses:
            logger.debug("No Ethereum addresses to check")
            return

        logger.info(f"Checking {len(addresses)} Ethereum addresses...")

        # ERC-20 contract addresses (mainnet)
        ERC20_CONTRACTS = {
            'usdt': '0xdac17f958d2ee523a2206206994597c13d831ec7',
            'usdc': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
        }

        for address_id, user_id, address, crypto_type in addresses:
            try:
                if crypto_type == 'eth':
                    transactions = await self._get_ethereum_transactions(address)
                else:
                    contract = ERC20_CONTRACTS.get(crypto_type)
                    if not contract:
                        continue
                    transactions = await self._get_erc20_transactions(address, contract, crypto_type)

                for tx in transactions:
                    await self.process_transaction(
                        user_id=user_id,
                        crypto_type=crypto_type,
                        tx_hash=tx['hash'],
                        from_address=tx['from_address'],
                        to_address=address,
                        amount=tx['amount'],
                        confirmations=tx['confirmations']
                    )
            except Exception as e:
                logger.error(f"Error checking Ethereum address {address}: {e}")

    async def _get_ethereum_transactions(self, address: str) -> List[Dict]:
        """Fetch ETH transactions from Etherscan public API."""
        url = (
            f"https://api.etherscan.io/api"
            f"?module=account&action=txlist&address={address}"
            f"&startblock=0&endblock=99999999&sort=desc&offset=25&page=1"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if data.get('status') != '1':
            return []

        results = []
        for tx in data.get('result', []):
            # Only incoming transactions
            if tx.get('to', '').lower() != address.lower():
                continue
            amount_wei = int(tx.get('value', 0))
            amount_eth = amount_wei / 1e18
            if amount_eth <= 0:
                continue
            confirmations = int(tx.get('confirmations', 0))
            results.append({
                'hash': tx['hash'],
                'from_address': tx.get('from', 'unknown'),
                'amount': amount_eth,
                'confirmations': confirmations,
            })
        return results

    async def _get_erc20_transactions(self, address: str, contract: str, crypto_type: str) -> List[Dict]:
        """Fetch ERC-20 token transfers from Etherscan public API."""
        url = (
            f"https://api.etherscan.io/api"
            f"?module=account&action=tokentx&contractaddress={contract}"
            f"&address={address}&startblock=0&endblock=99999999&sort=desc&offset=25&page=1"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if data.get('status') != '1':
            return []

        decimals_map = {'usdt': 6, 'usdc': 6}
        decimals = decimals_map.get(crypto_type, 18)

        results = []
        for tx in data.get('result', []):
            if tx.get('to', '').lower() != address.lower():
                continue
            amount_raw = int(tx.get('value', 0))
            amount = amount_raw / (10 ** decimals)
            if amount <= 0:
                continue
            confirmations = int(tx.get('confirmations', 0))
            results.append({
                'hash': tx['hash'],
                'from_address': tx.get('from', 'unknown'),
                'amount': amount,
                'confirmations': confirmations,
            })
        return results
    
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
        placeholder = '?' if self.db.db_type == 'sqlite' else '%s'

        # Check if transaction already exists
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT id, status, confirmations FROM crypto_transactions WHERE tx_hash = {placeholder}",
                (tx_hash,)
            )
            existing = cursor.fetchone()

        if existing:
            tx_id, status, old_confirmations = existing

            if confirmations > old_confirmations or status == 'pending':
                new_status = 'confirmed' if confirmations >= required_confs else 'pending'

                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        UPDATE crypto_transactions
                        SET confirmations = {placeholder}, status = {placeholder}, confirmed_at = {placeholder}
                        WHERE id = {placeholder}
                    """, (
                        confirmations,
                        new_status,
                        datetime.utcnow() if new_status == 'confirmed' else None,
                        tx_id
                    ))
                    conn.commit()

                logger.info(f"Updated transaction {tx_hash}: {confirmations} confirmations, status={new_status}")

                if new_status == 'confirmed' and status == 'pending':
                    await self.credit_user_wallet(user_id, crypto_type, amount, tx_id)
        else:
            status = 'confirmed' if confirmations >= required_confs else 'pending'

            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT id FROM user_crypto_addresses WHERE user_id = {placeholder} AND address = {placeholder}",
                    (user_id, to_address)
                )
                address_row = cursor.fetchone()
                address_id = address_row[0] if address_row else None

            if not address_id:
                logger.error(f"Address {to_address} not found for user {user_id}")
                return

            try:
                amount_fiat = await self.price_service.convert_crypto_to_fiat(crypto_type, amount)
            except Exception as e:
                logger.warning(f"Could not convert to fiat: {e}")
                amount_fiat = None

            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    INSERT INTO crypto_transactions
                    (user_id, address_id, crypto_type, tx_hash, amount_crypto, amount_fiat,
                     confirmations, required_confirmations, status, detected_at, confirmed_at)
                    VALUES ({placeholder},{placeholder},{placeholder},{placeholder},{placeholder},
                            {placeholder},{placeholder},{placeholder},{placeholder},{placeholder},{placeholder})
                """, (
                    user_id, address_id, crypto_type, tx_hash, amount, amount_fiat,
                    confirmations, required_confs, status,
                    datetime.utcnow(),
                    datetime.utcnow() if status == 'confirmed' else None
                ))
                tx_id = cursor.lastrowid
                conn.commit()

            logger.info(f"Created transaction {tx_hash}: {amount} {crypto_type}, status={status}")

            if status == 'confirmed':
                await self.credit_user_wallet(user_id, crypto_type, amount, tx_id)
    
    async def credit_user_wallet(self, user_id: int, crypto_type: str, amount: float, tx_id: int):
        """
        Credit user's fiat wallet with the confirmed transaction amount.
        """
        try:
            amount_fiat = await self.price_service.convert_crypto_to_fiat(crypto_type, amount)
        except Exception as e:
            logger.error(f"Could not convert to fiat for crediting: {e}")
            amount_fiat = 0

        now = datetime.utcnow()

        # Update crypto wallet balance
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            cursor.execute(f"""
                UPDATE user_crypto_wallets
                SET balance_crypto = balance_crypto + {placeholder},
                    balance_fiat = balance_fiat + {placeholder},
                    last_updated = {placeholder}
                WHERE user_id = {placeholder} AND crypto_type = {placeholder}
            """, (amount, amount_fiat, now, user_id, crypto_type))

            cursor.execute(f"""
                UPDATE crypto_transactions SET credited_at = {placeholder} WHERE id = {placeholder}
            """, (now, tx_id))
            conn.commit()

        # Credit fiat wallet directly via DB
        if amount_fiat > 0:
            try:
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    placeholder = '?' if self.db.db_type == 'sqlite' else '%s'

                    # Ensure wallet row exists
                    if self.db.db_type == 'sqlite':
                        cursor.execute(f"""
                            INSERT OR IGNORE INTO user_wallets (user_id, balance, currency_code)
                            VALUES ({placeholder}, 0.00, 'USD')
                        """, (user_id,))
                    else:
                        cursor.execute(f"""
                            INSERT IGNORE INTO user_wallets (user_id, balance, currency_code)
                            VALUES ({placeholder}, 0.00, 'USD')
                        """, (user_id,))

                    cursor.execute(f"""
                        UPDATE user_wallets
                        SET balance = balance + {placeholder}, updated_at = {placeholder}
                        WHERE user_id = {placeholder}
                    """, (amount_fiat, now, user_id))

                    # Get wallet id
                    cursor.execute(f"SELECT id FROM user_wallets WHERE user_id = {placeholder}", (user_id,))
                    wallet_row = cursor.fetchone()
                    wallet_id = wallet_row[0] if wallet_row else None

                    if wallet_id:
                        import json
                        cursor.execute(f"""
                            INSERT INTO wallet_transactions
                            (user_id, wallet_id, amount, type, status,
                             payment_gateway, gateway_transaction_id, description, metadata)
                            VALUES ({placeholder},{placeholder},{placeholder},'credit','completed',
                                    {placeholder},{placeholder},{placeholder},{placeholder})
                        """, (
                            user_id, wallet_id, amount_fiat,
                            f'crypto_{crypto_type}',
                            f'crypto_tx_{tx_id}',
                            f'Wallet top-up via {crypto_type.upper()} payment',
                            json.dumps({'crypto_amount': amount, 'crypto_type': crypto_type, 'tx_id': tx_id})
                        ))

                    conn.commit()

                logger.info(f"Fiat wallet credited {amount_fiat:.2f} for user {user_id} from {crypto_type} payment")
            except Exception as e:
                logger.error(f"Error crediting fiat wallet from crypto payment: {e}")

        logger.info(f"Credited {amount} {crypto_type} (${amount_fiat:.2f}) to user {user_id}")
