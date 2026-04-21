"""
Tests for wallet top up system with Stripe, PayPal and crypto payments
"""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock

from aisbf.payments.service import PaymentService
from aisbf.payments.wallet.manager import WalletManager


@pytest.mark.asyncio
async def test_topup_amount_configuration():
    """Test that supported top up amounts are properly configured"""
    db = Mock()
    config = {'encryption_key': 'test_key', 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    
    amounts = service.get_supported_topup_amounts()
    
    assert Decimal('10.00') in amounts
    assert Decimal('15.00') in amounts
    assert Decimal('20.00') in amounts
    assert Decimal('50.00') in amounts
    assert Decimal('100.00') in amounts
    assert service.allow_custom_topup_amount is True
    assert service.minimum_topup_amount == Decimal('5.00')
    assert service.maximum_topup_amount == Decimal('500.00')


@pytest.mark.asyncio
async def test_initiate_stripe_topup():
    """Test initiating a Stripe top up payment"""
    db = Mock()
    config = {'encryption_key': 'test_key', 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    service.stripe_handler.create_payment_intent = AsyncMock(return_value={
        'success': True,
        'client_secret': 'test_secret_123',
        'payment_intent_id': 'pi_123'
    })
    
    result = await service.initiate_topup(
        user_id=123,
        amount=Decimal('20.00'),
        payment_method='stripe',
        payment_method_id='pm_123'
    )
    
    assert result['success'] is True
    assert 'client_secret' in result
    assert result['amount'] == Decimal('20.00')
    assert result['payment_method'] == 'stripe'
    service.stripe_handler.create_payment_intent.assert_called_once()


@pytest.mark.asyncio
async def test_initiate_paypal_topup():
    """Test initiating a PayPal top up payment"""
    db = Mock()
    config = {'encryption_key': 'test_key', 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    service.paypal_handler.create_order = AsyncMock(return_value={
        'success': True,
        'order_id': 'test_order_123',
        'approval_url': 'https://paypal.com/approve'
    })
    
    result = await service.initiate_topup(
        user_id=123,
        amount=Decimal('50.00'),
        payment_method='paypal'
    )
    
    assert result['success'] is True
    assert 'order_id' in result
    assert 'approval_url' in result
    service.paypal_handler.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_stripe_webhook_credits_wallet():
    """Test that successful Stripe payment webhook credits user wallet"""
    db = Mock()
    config = {'encryption_key': 'test_key', 'base_url': 'http://localhost'}
    
    with patch('aisbf.payments.wallet.manager.WalletManager.credit_wallet', new_callable=AsyncMock) as mock_credit:
        service = PaymentService(db, config)
        
        mock_credit.return_value = {'success': True, 'new_balance': Decimal('20.00')}
        
        event = {
            'type': 'payment_intent.succeeded',
            'data': {
                'object': {
                    'id': 'pi_12345',
                    'metadata': {'user_id': '123', 'topup': 'true'},
                    'amount': 2000,
                    'currency': 'usd'
                }
            }
        }
        
        result = await service.stripe_handler.handle_webhook(b'', 'test_sig')
        
        assert result['status'] == 'success'
        mock_credit.assert_called_once_with(
            user_id=123,
            amount=Decimal('20.00'),
            transaction_details={
                'payment_gateway': 'stripe',
                'gateway_transaction_id': 'pi_12345',
                'description': 'Wallet top up via Stripe'
            }
        )


@pytest.mark.asyncio
async def test_crypto_payment_credits_wallet():
    """Test that confirmed crypto payment credits user wallet"""
    db = Mock()
    config = {'encryption_key': 'test_key', 'base_url': 'http://localhost'}
    
    with patch('aisbf.payments.wallet.manager.WalletManager.credit_wallet', new_callable=AsyncMock) as mock_credit:
        service = PaymentService(db, config)
        service.price_service.convert_crypto_to_fiat = AsyncMock(return_value=Decimal('25.00'))
        
        await service.blockchain_monitor.credit_user_wallet(
            user_id=123,
            crypto_type='btc',
            amount=0.0005,
            tx_id=456
        )
        
        mock_credit.assert_called_once()
        args = mock_credit.call_args
        assert args[1]['user_id'] == 123
        assert args[1]['amount'] == Decimal('25.00')
        assert args[1]['transaction_details']['payment_gateway'] == 'crypto_btc'


@pytest.mark.asyncio
async def test_invalid_topup_amount():
    """Test that invalid top up amounts are rejected"""
    db = Mock()
    config = {'encryption_key': 'test_key', 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    
    with pytest.raises(ValueError, match="Amount below minimum"):
        await service.initiate_topup(user_id=123, amount=Decimal('3.00'), payment_method='stripe')
    
    with pytest.raises(ValueError, match="Amount above maximum"):
        await service.initiate_topup(user_id=123, amount=Decimal('1000.00'), payment_method='stripe')
