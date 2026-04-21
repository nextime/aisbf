"""
Unit and integration tests for subscription renewal wallet integration
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from aisbf.payments.subscription.renewal import SubscriptionRenewalProcessor
from aisbf.payments.wallet.manager import WalletManager


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.session = AsyncMock()
    return db


@pytest.fixture
def renewal_processor(mock_db):
    return SubscriptionRenewalProcessor(mock_db)


@pytest.fixture
def sample_subscription():
    return {
        'id': 123,
        'user_id': 456,
        'tier_id': 2,
        'tier_name': 'Pro',
        'billing_cycle': 'monthly',
        'price_monthly': '19.99',
        'price_yearly': '199.99',
        'payment_method_id': 789,
        'current_period_end': datetime.utcnow(),
        'pending_tier_id': None,
        'status': 'active'
    }


class TestSubscriptionRenewalWalletIntegration:
    """Test subscription renewal with wallet integration"""

    @pytest.mark.asyncio
    async def test_renew_uses_wallet_when_sufficient_balance(self, renewal_processor, sample_subscription):
        """Test that renewal first uses wallet when sufficient balance exists"""
        
        with patch.object(WalletManager, 'get_wallet') as mock_get_wallet, \
             patch.object(WalletManager, 'has_sufficient_balance') as mock_has_balance, \
             patch.object(WalletManager, 'debit_wallet') as mock_debit_wallet, \
             patch.object(renewal_processor, '_charge_payment') as mock_charge_payment:
            
            mock_get_wallet.return_value = {
                'id': 1,
                'user_id': 456,
                'balance': Decimal('50.00'),
                'auto_topup_enabled': False
            }
            
            mock_has_balance.return_value = True
            mock_debit_wallet.return_value = {'success': True}
            
            result = await renewal_processor._renew_subscription(sample_subscription)
            
            assert result['success'] is True
            mock_debit_wallet.assert_called_once()
            mock_charge_payment.assert_not_called()
            
            # Verify debit amount is correct
            call_args = mock_debit_wallet.call_args
            assert call_args[1]['user_id'] == 456
            assert call_args[1]['amount'] == Decimal('19.99')

    @pytest.mark.asyncio
    async def test_renew_triggers_auto_topup_when_insufficient_balance(self, renewal_processor, sample_subscription):
        """Test that auto top up is triggered when wallet balance is insufficient"""
        
        with patch.object(WalletManager, 'get_wallet') as mock_get_wallet, \
             patch.object(WalletManager, 'has_sufficient_balance') as mock_has_balance, \
             patch.object(WalletManager, 'should_trigger_auto_topup') as mock_should_trigger, \
             patch('aisbf.payments.subscription.renewal.trigger_auto_topup') as mock_trigger_topup, \
             patch.object(WalletManager, 'debit_wallet') as mock_debit_wallet, \
             patch.object(renewal_processor, '_charge_payment') as mock_charge_payment:
            
            mock_get_wallet.return_value = {
                'id': 1,
                'user_id': 456,
                'balance': Decimal('5.00'),
                'auto_topup_enabled': True,
                'auto_topup_threshold': Decimal('20.00'),
                'auto_topup_amount': Decimal('30.00'),
                'auto_topup_payment_method_id': 789
            }
            
            mock_has_balance.return_value = False
            mock_should_trigger.return_value = True
            mock_trigger_topup.return_value = True
            mock_debit_wallet.return_value = {'success': True}
            
            result = await renewal_processor._renew_subscription(sample_subscription)
            
            assert result['success'] is True
            mock_trigger_topup.assert_called_once()
            mock_debit_wallet.assert_called_once()
            mock_charge_payment.assert_not_called()

    @pytest.mark.asyncio
    async def test_renew_falls_back_to_payment_method_when_auto_topup_fails(self, renewal_processor, sample_subscription):
        """Test that renewal falls back to direct payment when auto top up fails"""
        
        with patch.object(WalletManager, 'get_wallet') as mock_get_wallet, \
             patch.object(WalletManager, 'has_sufficient_balance') as mock_has_balance, \
             patch.object(WalletManager, 'should_trigger_auto_topup') as mock_should_trigger, \
             patch('aisbf.payments.subscription.renewal.trigger_auto_topup') as mock_trigger_topup, \
             patch.object(renewal_processor, '_charge_payment') as mock_charge_payment:
            
            mock_get_wallet.return_value = {
                'id': 1,
                'user_id': 456,
                'balance': Decimal('5.00'),
                'auto_topup_enabled': True,
                'auto_topup_threshold': Decimal('20.00'),
                'auto_topup_amount': Decimal('30.00'),
                'auto_topup_payment_method_id': 789
            }
            
            mock_has_balance.return_value = False
            mock_should_trigger.return_value = True
            mock_trigger_topup.return_value = False
            mock_charge_payment.return_value = {'success': True}
            
            # Mock payment method lookup
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = (789, 456, 'card', 'stripe', 'pm_123', '{}')
            
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            
            with patch.object(renewal_processor.db, '_get_connection') as mock_get_conn:
                mock_get_conn.return_value.__enter__.return_value = mock_conn
                result = await renewal_processor._renew_subscription(sample_subscription)
            
            assert result['success'] is True
            mock_charge_payment.assert_called_once()

    @pytest.mark.asyncio
    async def test_renew_uses_pending_tier_price(self, renewal_processor, sample_subscription):
        """Test renewal uses pending tier price when available"""
        
        sample_subscription['pending_tier_id'] = 3
        
        with patch.object(WalletManager, 'get_wallet') as mock_get_wallet, \
             patch.object(WalletManager, 'has_sufficient_balance') as mock_has_balance, \
             patch.object(WalletManager, 'debit_wallet') as mock_debit_wallet:
            
            mock_get_wallet.return_value = {
                'id': 1,
                'user_id': 456,
                'balance': Decimal('100.00'),
                'auto_topup_enabled': False
            }
            
            mock_has_balance.return_value = True
            mock_debit_wallet.return_value = {'success': True}
            
            # Mock tier lookup
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = (Decimal('29.99'), Decimal('299.99'), 'Business')
            
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            
            with patch.object(renewal_processor.db, '_get_connection') as mock_get_conn:
                mock_get_conn.return_value.__enter__.return_value = mock_conn
                result = await renewal_processor._renew_subscription(sample_subscription)
            
            assert result['success'] is True
            call_args = mock_debit_wallet.call_args
            assert call_args[1]['amount'] == Decimal('29.99')
