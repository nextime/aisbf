"""
Pydantic models for payment system
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class CryptoAddress(BaseModel):
    """Crypto address model"""
    crypto_type: str
    address: str
    derivation_path: str
    derivation_index: int


class CryptoWallet(BaseModel):
    """Crypto wallet balance model"""
    crypto_type: str
    balance_crypto: Decimal
    balance_fiat: Decimal
    last_sync_at: Optional[datetime] = None


class AddCryptoPaymentMethodRequest(BaseModel):
    """Request to add crypto payment method"""
    crypto_type: str
