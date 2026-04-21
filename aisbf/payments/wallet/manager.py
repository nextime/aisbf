"""
Wallet Manager service class with core wallet operations, atomic balance transactions, and transaction logging
"""
import logging
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select, update, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class WalletManager:
    """
    Manager class for user wallet operations with atomic transactions and full audit logging
    """

    def __init__(self, db_session: AsyncSession):
        """Initialize WalletManager with active database session"""
        self.db = db_session

    async def get_wallet(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user wallet, create if it doesn't exist"""
        result = await self.db.execute(
            """SELECT id, user_id, balance, currency_code,
                      auto_topup_enabled, auto_topup_amount,
                      auto_topup_threshold, auto_topup_payment_method_id,
                      created_at, updated_at
               FROM user_wallets
               WHERE user_id = :user_id""",
            {"user_id": user_id}
        )
        mappings = result.mappings()
        wallet = mappings.first() if hasattr(mappings, 'first') else (mappings[0] if mappings else None)

        if not wallet:
            # Create default wallet for user
            result = await self.db.execute(
                "INSERT INTO user_wallets (user_id, balance, currency_code) "
                "VALUES (:user_id, 0.00, 'USD') "
                "RETURNING id, user_id, balance, currency_code, auto_topup_enabled, "
                "auto_topup_amount, auto_topup_threshold, auto_topup_payment_method_id, "
                "created_at, updated_at",
                {"user_id": user_id}
            )
            mappings = result.mappings()
            wallet = mappings.first() if hasattr(mappings, 'first') else (mappings[0] if mappings else None)
            await self.db.commit()

        return dict(wallet)

    async def has_sufficient_balance(self, user_id: int, amount: Decimal) -> bool:
        """Check if user has sufficient balance for given amount"""
        if amount <= Decimal("0.00"):
            raise ValueError("Amount must be positive")

        wallet = await self.get_wallet(user_id)
        return Decimal(wallet["balance"]) >= amount

    async def credit_wallet(
        self,
        user_id: int,
        amount: Decimal,
        transaction_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Credit wallet with given amount atomically
        Returns: updated wallet balance and transaction record
        """
        if amount <= Decimal("0.00"):
            raise ValueError("Credit amount must be positive")

        try:
            async with self.db.begin():
                # Get and lock wallet row for atomic update
                wallet = await self.get_wallet(user_id)

                # Update balance
                new_balance = Decimal(wallet["balance"]) + amount
                await self.db.execute(
                    "UPDATE user_wallets SET balance = :balance, updated_at = CURRENT_TIMESTAMP WHERE id = :wallet_id",
                    {"balance": new_balance, "wallet_id": wallet["id"]}
                )

                # Log transaction
                tx_result = await self.db.execute(
                    """INSERT INTO wallet_transactions
                    (user_id, wallet_id, amount, type, status, payment_method_id,
                     payment_gateway, gateway_transaction_id, description, metadata)
                    VALUES
                    (:user_id, :wallet_id, :amount, 'credit', 'completed', :payment_method_id,
                     :payment_gateway, :gateway_transaction_id, :description, :metadata)
                    RETURNING id, created_at
                    """,
                    {
                        "user_id": user_id,
                        "wallet_id": wallet["id"],
                        "amount": amount,
                        "payment_method_id": transaction_details.get("payment_method_id"),
                        "payment_gateway": transaction_details.get("payment_gateway"),
                        "gateway_transaction_id": transaction_details.get("gateway_transaction_id"),
                        "description": transaction_details.get("description", ""),
                        "metadata": transaction_details.get("metadata", {})
                    }
                )
                mappings = tx_result.mappings()
                transaction = mappings.first() if hasattr(mappings, 'first') else (mappings[0] if mappings else None)

            logger.info(f"Wallet credit successful: user={user_id}, amount={amount}, tx_id={transaction['id']}")
            return {
                "wallet_id": wallet["id"],
                "new_balance": new_balance,
                "transaction_id": transaction["id"],
                "transaction_created_at": transaction["created_at"]
            }

        except SQLAlchemyError as e:
            logger.error(f"Wallet credit failed: user={user_id}, amount={amount}, error={str(e)}")
            raise

    async def debit_wallet(
        self,
        user_id: int,
        amount: Decimal,
        transaction_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Debit wallet with given amount atomically
        Returns: updated wallet balance and transaction record
        """
        if amount <= Decimal("0.00"):
            raise ValueError("Debit amount must be positive")

        try:
            async with self.db.begin():
                # Get and lock wallet row for atomic update
                wallet = await self.get_wallet(user_id)

                current_balance = Decimal(wallet["balance"])
                if current_balance < amount:
                    raise ValueError(f"Insufficient balance: available {current_balance}, required {amount}")

                # Update balance
                new_balance = current_balance - amount
                await self.db.execute(
                    "UPDATE user_wallets SET balance = :balance, updated_at = CURRENT_TIMESTAMP WHERE id = :wallet_id",
                    {"balance": new_balance, "wallet_id": wallet["id"]}
                )

                # Log transaction
                tx_result = await self.db.execute(
                    """INSERT INTO wallet_transactions
                    (user_id, wallet_id, amount, type, status, payment_method_id,
                     payment_gateway, gateway_transaction_id, description, metadata)
                    VALUES
                    (:user_id, :wallet_id, :amount, 'debit', 'completed', :payment_method_id,
                     :payment_gateway, :gateway_transaction_id, :description, :metadata)
                    RETURNING id, created_at
                    """,
                    {
                        "user_id": user_id,
                        "wallet_id": wallet["id"],
                        "amount": amount,
                        "payment_method_id": transaction_details.get("payment_method_id"),
                        "payment_gateway": transaction_details.get("payment_gateway"),
                        "gateway_transaction_id": transaction_details.get("gateway_transaction_id"),
                        "description": transaction_details.get("description", ""),
                        "metadata": transaction_details.get("metadata", {})
                    }
                )
                mappings = tx_result.mappings()
                transaction = mappings.first() if hasattr(mappings, 'first') else (mappings[0] if mappings else None)

            logger.info(f"Wallet debit successful: user={user_id}, amount={amount}, tx_id={transaction['id']}")
            return {
                "wallet_id": wallet["id"],
                "new_balance": new_balance,
                "transaction_id": transaction["id"],
                "transaction_created_at": transaction["created_at"]
            }

        except SQLAlchemyError as e:
            logger.error(f"Wallet debit failed: user={user_id}, amount={amount}, error={str(e)}")
            raise

    async def configure_auto_topup(self, user_id: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Configure auto top-up settings for user wallet
        """
        wallet = await self.get_wallet(user_id)

        update_fields = {}

        if "auto_topup_enabled" in settings:
            update_fields["auto_topup_enabled"] = settings["auto_topup_enabled"]
            if settings["auto_topup_enabled"]:
                # Reset failure counter when enabling
                update_fields["auto_topup_failures"] = 0

        if "auto_topup_amount" in settings:
            update_fields["auto_topup_amount"] = settings["auto_topup_amount"]

        if "auto_topup_threshold" in settings:
            update_fields["auto_topup_threshold"] = settings["auto_topup_threshold"]

        if "auto_topup_payment_method_id" in settings:
            update_fields["auto_topup_payment_method_id"] = settings["auto_topup_payment_method_id"]

        if not update_fields:
            return wallet

        update_fields["updated_at"] = datetime.utcnow()

        await self.db.execute(
            update("user_wallets")
            .where("user_wallets.id" == wallet["id"])
            .values(**update_fields)
        )
        await self.db.commit()

        return await self.get_wallet(user_id)

    def should_trigger_auto_topup(self, wallet: Dict[str, Any]) -> bool:
        """
        Check if auto top up should be triggered for this wallet
        """
        if not wallet.get("auto_topup_enabled", False):
            return False
        
        balance = Decimal(wallet["balance"])
        threshold = wallet.get("auto_topup_threshold")
        amount = wallet.get("auto_topup_amount")
        payment_method = wallet.get("auto_topup_payment_method_id")
        
        if threshold is None or amount is None or payment_method is None:
            return False
        
        return balance < Decimal(threshold)

    async def record_auto_topup_attempt(self, wallet_id: int, success: bool) -> None:
        """
        Record auto top up attempt result and handle failure retries
        """
        result = await self.db.execute(
            """SELECT auto_topup_failures, auto_topup_enabled
               FROM user_wallets WHERE id = :wallet_id""",
            {"wallet_id": wallet_id}
        )
        mappings = result.mappings()
        wallet = mappings.first() if hasattr(mappings, 'first') else (mappings[0] if mappings else None)
        
        if success:
            # Reset failure counter on success
            await self.db.execute(
                """UPDATE user_wallets 
                   SET auto_topup_failures = 0, updated_at = CURRENT_TIMESTAMP
                   WHERE id = :wallet_id""",
                {"wallet_id": wallet_id}
            )
        else:
            # Increment failure counter
            new_failures = wallet["auto_topup_failures"] + 1
            
            # Disable auto top up after 3 consecutive failures
            enabled = wallet["auto_topup_enabled"] if new_failures < 3 else False
            
            await self.db.execute(
                """UPDATE user_wallets 
                   SET auto_topup_failures = :failures, 
                       auto_topup_enabled = :enabled,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = :wallet_id""",
                {"wallet_id": wallet_id, "failures": new_failures, "enabled": enabled}
            )
        
        await self.db.commit()

    async def get_transactions(self, user_id: int, limit: int = 50, offset: int = 0) -> list[Dict[str, Any]]:
        """
        Get paginated transaction history for user
        """
        result = await self.db.execute("""
            SELECT id, amount, type, status, description, created_at
            FROM wallet_transactions
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """, {
            "user_id": user_id,
            "limit": limit,
            "offset": offset
        })
        
        return [dict(row) for row in result.mappings().all()]

    async def get_wallets_needing_auto_topup(self) -> list[Dict[str, Any]]:
        """
        Get all wallets that meet auto top up trigger conditions
        """
        result = await self.db.execute("""
            SELECT id, user_id, balance, auto_topup_amount, auto_topup_payment_method_id
            FROM user_wallets
            WHERE auto_topup_enabled = 1
              AND auto_topup_amount IS NOT NULL
              AND auto_topup_threshold IS NOT NULL
              AND auto_topup_payment_method_id IS NOT NULL
              AND balance < auto_topup_threshold
              AND auto_topup_failures < 3
        """)
        
        return [dict(row) for row in result.mappings().all()]
