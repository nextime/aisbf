"""
Wallet API endpoints
"""
import logging
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field

from aisbf.payments.wallet.manager import WalletManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wallet", tags=["wallet"])


class WalletBalanceResponse(BaseModel):
    balance: Decimal
    currency_code: str
    auto_topup_enabled: bool
    auto_topup_amount: Optional[Decimal]
    auto_topup_threshold: Optional[Decimal]


class TransactionResponse(BaseModel):
    id: int
    amount: Decimal
    type: str
    status: str
    description: Optional[str]
    created_at: str


class TopUpRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    payment_method: str


class AutoTopUpSettings(BaseModel):
    enabled: bool
    amount: Optional[Decimal] = Field(gt=0, decimal_places=2)
    threshold: Optional[Decimal] = Field(gt=0, decimal_places=2)
    payment_method_id: Optional[int]


async def get_wallet_manager(request: Request):
    return WalletManager(request.app.state.db)


@router.get("/balance", response_model=WalletBalanceResponse)
async def get_wallet_balance(
    request: Request,
    wallet_manager: WalletManager = Depends(get_wallet_manager)
):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    wallet = await wallet_manager.get_wallet(user_id)
    return WalletBalanceResponse(
        balance=wallet.balance,
        currency_code=wallet.currency_code,
        auto_topup_enabled=wallet.auto_topup_enabled,
        auto_topup_amount=wallet.auto_topup_amount,
        auto_topup_threshold=wallet.auto_topup_threshold
    )


@router.get("/transactions", response_model=List[TransactionResponse])
async def get_transaction_history(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    wallet_manager: WalletManager = Depends(get_wallet_manager)
):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    transactions = await wallet_manager.get_transactions(user_id, limit, offset)
    return [
        TransactionResponse(
            id=t.id,
            amount=t.amount,
            type=t.type,
            status=t.status,
            description=t.description,
            created_at=t.created_at.isoformat()
        ) for t in transactions
    ]


@router.post("/topup", status_code=status.HTTP_201_CREATED)
async def initiate_topup(
    request: Request,
    topup_data: TopUpRequest,
    wallet_manager: WalletManager = Depends(get_wallet_manager)
):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    # Validate supported amounts
    supported_amounts = [Decimal('10.00'), Decimal('15.00'), Decimal('20.00'), Decimal('50.00'), Decimal('100.00')]
    if topup_data.amount not in supported_amounts and (topup_data.amount < Decimal('5.00') or topup_data.amount > Decimal('500.00')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid top up amount. Supported: 10,15,20,50,100 or custom 5-500"
        )
    
    payment_service = request.app.state.payment_service
    
    if topup_data.payment_method == "stripe":
        intent = await payment_service.stripe_handler.create_payment_intent(
            user_id,
            topup_data.amount,
            metadata={"type": "wallet_topup"}
        )
        return {"client_secret": intent.client_secret, "payment_method": "stripe"}
    elif topup_data.payment_method == "paypal":
        order = await payment_service.paypal_handler.create_order(
            user_id,
            topup_data.amount,
            metadata={"type": "wallet_topup"}
        )
        return {"order_id": order.id, "payment_method": "paypal"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported payment method"
        )


@router.put("/auto-topup")
async def configure_auto_topup(
    request: Request,
    settings: AutoTopUpSettings,
    wallet_manager: WalletManager = Depends(get_wallet_manager)
):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if settings.enabled:
        if not settings.amount or not settings.threshold or not settings.payment_method_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount, threshold and payment method are required when enabling auto top up"
            )
    
    await wallet_manager.configure_auto_topup(
        user_id,
        enabled=settings.enabled,
        amount=settings.amount,
        threshold=settings.threshold,
        payment_method_id=settings.payment_method_id
    )
    
    return {"status": "ok"}
