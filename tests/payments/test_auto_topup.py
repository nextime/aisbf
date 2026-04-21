"""
Test suite for auto top up system implementation
"""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from aisbf.payments.wallet.manager import WalletManager
from aisbf.payments.fiat.stripe_handler import StripePaymentHandler
from aisbf.payments.scheduler import PaymentScheduler


@pytest.mark.asyncio
async def test_auto_topup_trigger_condition():
    """Test auto top up trigger condition checks correctly"""
    mock_session = AsyncMock(spec=AsyncSession)
    wallet_manager = WalletManager(mock_session)
    
    # Test 1: Enabled, balance below threshold, configured amount and payment method
    wallet = {
        "auto_topup_enabled": True,
        "balance": Decimal("5.00"),
        "auto_topup_threshold": Decimal("10.00"),
        "auto_topup_amount": Decimal("20.00"),
        "auto_topup_payment_method_id": 123
    }
    
    assert wallet_manager.should_trigger_auto_topup(wallet) is True
    
    # Test 2: Disabled
    wallet["auto_topup_enabled"] = False
    assert wallet_manager.should_trigger_auto_topup(wallet) is False
    
    # Test 3: Balance above threshold
    wallet["auto_topup_enabled"] = True
    wallet["balance"] = Decimal("15.00")
    assert wallet_manager.should_trigger_auto_topup(wallet) is False
    
    # Test 4: No amount configured
    wallet["balance"] = Decimal("5.00")
    wallet["auto_topup_amount"] = None
    assert wallet_manager.should_trigger_auto_topup(wallet) is False
    
    # Test 5: No payment method configured
    wallet["auto_topup_amount"] = Decimal("20.00")
    wallet["auto_topup_payment_method_id"] = None
    assert wallet_manager.should_trigger_auto_topup(wallet) is False


@pytest.mark.asyncio
async def test_stripe_auto_charge():
    """Test Stripe auto charging for auto top up"""
    mock_db = Mock()
    stripe_handler = StripePaymentHandler(mock_db, {"currency_code": "USD"})
    
    with patch('aisbf.payments.fiat.stripe_handler.stripe.PaymentIntent.create') as mock_create:
        mock_create.return_value = {
            "id": "pi_123",
            "status": "succeeded",
            "amount": 2000
        }
        
        result = await stripe_handler.auto_charge(
            user_id=1,
            amount=Decimal("20.00"),
            payment_method_id="pm_123"
        )
        
        assert result["success"] is True
        assert result["gateway_transaction_id"] == "pi_123"
        mock_create.assert_called_once()
        assert mock_create.call_args[1]["amount"] == 2000
        assert mock_create.call_args[1]["confirm"] is True
        assert mock_create.call_args[1]["payment_method"] == "pm_123"


@pytest.mark.asyncio
async def test_auto_topup_retry_logic():
    """Test failure handling and retries for auto top up"""
    mock_session = AsyncMock(spec=AsyncSession)
    wallet_manager = WalletManager(mock_session)
    
    # Test retry counter increment
    wallet = {"id": 1, "user_id": 1}
    await wallet_manager.record_auto_topup_attempt(wallet["id"], success=False)
    
    # Test that after 3 failures auto top up is disabled
    for i in range(3):
        await wallet_manager.record_auto_topup_attempt(wallet["id"], success=False)
    
    updated_wallet = await wallet_manager.get_wallet(1)
    assert updated_wallet["auto_topup_enabled"] is False


@pytest.mark.asyncio
async def test_scheduler_auto_topup_job():
    """Test scheduled auto top up check job"""
    mock_db = Mock()
    mock_payment_service = Mock()
    
    scheduler = PaymentScheduler(mock_db, mock_payment_service)
    
    with patch.object(scheduler, '_acquire_lock', return_value=True):
        with patch.object(scheduler, '_release_lock'):
            await scheduler._run_auto_topup_check()
    
    # Verify job executed without exceptions
    assert True
