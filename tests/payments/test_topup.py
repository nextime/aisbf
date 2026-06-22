"""
Tests for wallet top up system with Stripe, PayPal and crypto payments
"""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock

import tempfile

from cryptography.fernet import Fernet

from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.service import PaymentService
from aisbf.payments.wallet.manager import WalletManager

# PaymentService validates the encryption key as a real Fernet key.
_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


def _make_payment_db():
    """A real migrated SQLite DB. PaymentService construction now initializes
    crypto master keys, so a plain Mock can't stand in for the database."""
    path = tempfile.mktemp(suffix=".db")
    db = DatabaseManager({'type': 'sqlite', 'sqlite_path': path})
    PaymentMigrations(db).run_migrations()
    return db


@pytest.mark.asyncio
async def test_topup_amount_configuration():
    """Test that supported top up amounts are properly configured"""
    db = _make_payment_db()
    config = {'encryption_key': _TEST_ENCRYPTION_KEY, 'base_url': 'http://localhost'}
    
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
    db = _make_payment_db()
    config = {'encryption_key': _TEST_ENCRYPTION_KEY, 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    # initiate_topup delegates to stripe_handler.create_topup_intent and returns
    # its result verbatim.
    service.stripe_handler.create_topup_intent = AsyncMock(return_value={
        'success': True,
        'client_secret': 'test_secret_123',
        'payment_intent_id': 'pi_123',
        'amount': Decimal('20.00'),
        'payment_method': 'stripe'
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
    service.stripe_handler.create_topup_intent.assert_called_once()


@pytest.mark.asyncio
async def test_initiate_paypal_topup():
    """Test initiating a PayPal top up payment"""
    db = _make_payment_db()
    config = {'encryption_key': _TEST_ENCRYPTION_KEY, 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    # initiate_topup delegates to paypal_handler.create_topup_order.
    service.paypal_handler.create_topup_order = AsyncMock(return_value={
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
    service.paypal_handler.create_topup_order.assert_called_once()


@pytest.mark.asyncio
async def test_stripe_webhook_credits_wallet():
    """Test that successful Stripe payment webhook credits user wallet"""
    db = _make_payment_db()
    config = {'encryption_key': _TEST_ENCRYPTION_KEY, 'base_url': 'http://localhost'}
    
    event = {
        'type': 'payment_intent.succeeded',
        'data': {
            'object': {
                'id': 'pi_12345',
                # amount lives in metadata for top-up intents
                'metadata': {'user_id': '123', 'topup': 'true', 'amount': '20.00'},
                'amount': 2000,
                'currency': 'usd'
            }
        }
    }

    with patch('aisbf.payments.wallet.manager.WalletManager.credit_wallet', new_callable=AsyncMock) as mock_credit, \
         patch('stripe.Webhook.construct_event', return_value=event):
        service = PaymentService(db, config)

        mock_credit.return_value = {'success': True, 'new_balance': Decimal('20.00')}

        result = await service.stripe_handler.handle_webhook(b'{}', 'test_sig')

        assert result['status'] == 'success'
        mock_credit.assert_called_once_with(
            user_id=123,
            amount=Decimal('20.00'),
            transaction_details={
                'payment_gateway': 'stripe',
                'gateway_transaction_id': 'pi_12345',
                'description': 'Wallet top up via Stripe',
                'metadata': {'payment_intent': 'pi_12345'}
            }
        )


@pytest.mark.asyncio
async def test_crypto_payment_credits_wallet():
    """Test that confirmed crypto payment credits user wallet"""
    db = _make_payment_db()
    config = {'encryption_key': _TEST_ENCRYPTION_KEY, 'base_url': 'http://localhost'}
    
    # Create the user so the fiat wallet row can be created/credited.
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (id, username, email, password_hash, role, email_verified)
            VALUES (123, 'crypto-user', 'crypto@example.com', 'hash', 'user', 1)
        """)
        conn.commit()

    service = PaymentService(db, config)
    # credit_user_wallet uses the monitor's own price service.
    service.blockchain_monitor.price_service.convert_crypto_to_fiat = AsyncMock(return_value=25.00)

    # credit_user_wallet credits the fiat wallet directly via SQL (no
    # WalletManager.credit_wallet call), so verify the resulting balance.
    await service.blockchain_monitor.credit_user_wallet(
        user_id=123,
        crypto_type='btc',
        amount=0.0005,
        tx_id=456
    )

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM user_wallets WHERE user_id = 123")
        row = cursor.fetchone()

    assert row is not None
    assert Decimal(str(row[0])) == Decimal('25.00')


@pytest.mark.asyncio
async def test_invalid_topup_amount():
    """Test that invalid top up amounts are rejected"""
    db = _make_payment_db()
    config = {'encryption_key': _TEST_ENCRYPTION_KEY, 'base_url': 'http://localhost'}
    
    service = PaymentService(db, config)
    
    with pytest.raises(ValueError, match="Amount below minimum"):
        await service.initiate_topup(user_id=123, amount=Decimal('3.00'), payment_method='stripe')
    
    with pytest.raises(ValueError, match="Amount above maximum"):
        await service.initiate_topup(user_id=123, amount=Decimal('1000.00'), payment_method='stripe')
