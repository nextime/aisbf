"""
Integration tests for payment system

Tests complete payment flows including:
- Crypto payment flow
- Subscription creation and management
- Payment retries
- Wallet consolidation
- Email notifications
"""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock


@pytest.fixture
def db_manager():
    """Create test database manager"""
    from aisbf.database import DatabaseManager
    
    # Use in-memory SQLite for tests
    db = DatabaseManager(db_type='sqlite', db_path=':memory:')
    
    # Run migrations
    from aisbf.payments.migrations import PaymentMigrations
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Create test user
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, role, email_verified)
            VALUES ('testuser', 'test@example.com', 'hash', 'user', 1)
        """)
        conn.commit()
    
    return db


@pytest.fixture
def payment_config():
    """Payment service configuration"""
    return {
        'encryption_key': 'test_key_32_bytes_long_exactly!!',
        'currency_code': 'USD',
        'btc_confirmations': 3,
        'eth_confirmations': 12,
        'stripe_api_key': 'test_stripe_key',
        'paypal_client_id': 'test_paypal_id',
        'paypal_client_secret': 'test_paypal_secret'
    }


@pytest.fixture
async def payment_service(db_manager, payment_config):
    """Create payment service instance"""
    from aisbf.payments.service import PaymentService
    
    service = PaymentService(db_manager, payment_config)
    await service.initialize()
    
    return service


class TestCryptoPaymentFlow:
    """Test complete crypto payment flow"""
    
    @pytest.mark.asyncio
    async def test_create_crypto_address(self, payment_service, db_manager):
        """Test creating crypto address for user"""
        # Get or create address
        address = await payment_service.wallet_manager.get_or_create_user_address(1, 'btc')
        
        assert address is not None
        assert len(address) > 0
        
        # Verify address stored in database
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT address FROM user_crypto_addresses
                WHERE user_id = 1 AND crypto_type = 'btc'
            """)
            row = cursor.fetchone()
        
        assert row is not None
        assert row[0] == address
    
    @pytest.mark.asyncio
    async def test_detect_incoming_payment(self, payment_service, db_manager):
        """Test detecting incoming crypto payment"""
        # Create address
        address = await payment_service.wallet_manager.get_or_create_user_address(1, 'btc')
        
        # Simulate incoming transaction
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO crypto_transactions
                (user_id, crypto_type, tx_hash, from_address, to_address, amount_crypto, confirmations, status)
                VALUES (1, 'btc', 'test_tx_hash', 'sender_addr', ?, 0.001, 3, 'pending')
            """, (address,))
            conn.commit()
        
        # Process transaction (simulate blockchain monitor)
        await payment_service.blockchain_monitor.process_transaction(
            user_id=1,
            crypto_type='btc',
            tx_hash='test_tx_hash',
            from_address='sender_addr',
            to_address=address,
            amount=Decimal('0.001'),
            confirmations=3
        )
        
        # Verify wallet balance updated
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT balance_crypto FROM user_crypto_wallets
                WHERE user_id = 1 AND crypto_type = 'btc'
            """)
            row = cursor.fetchone()
        
        assert row is not None
        assert Decimal(str(row[0])) > 0


class TestSubscriptionFlow:
    """Test subscription creation and management"""
    
    @pytest.mark.asyncio
    async def test_create_subscription(self, payment_service, db_manager):
        """Test creating a subscription"""
        # Create tier
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO subscription_tiers
                (name, price_monthly, price_yearly, features_json, is_active)
                VALUES ('Pro', 10.00, 100.00, '{}', 1)
            """)
            conn.commit()
            tier_id = cursor.lastrowid
        
        # Create subscription
        result = await payment_service.subscription_manager.create_subscription(
            user_id=1,
            tier_id=tier_id,
            billing_cycle='monthly',
            payment_method_id=1
        )
        
        assert result['success'] is True
        assert 'subscription_id' in result
        
        # Verify subscription in database
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status FROM user_subscriptions
                WHERE user_id = 1
            """)
            row = cursor.fetchone()
        
        assert row is not None
        assert row[0] == 'active'
    
    @pytest.mark.asyncio
    async def test_subscription_renewal(self, payment_service, db_manager):
        """Test subscription renewal process"""
        # Create tier and subscription
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO subscription_tiers
                (name, price_monthly, price_yearly, features_json, is_active)
                VALUES ('Pro', 10.00, 100.00, '{}', 1)
            """)
            tier_id = cursor.lastrowid
            
            # Create subscription expiring soon
            cursor.execute("""
                INSERT INTO user_subscriptions
                (user_id, tier_id, status, billing_cycle, next_billing_date, payment_method_id)
                VALUES (1, ?, 'active', 'monthly', date('now', '+1 day'), 1)
            """, (tier_id,))
            conn.commit()
        
        # Process renewals
        await payment_service.renewal_processor.process_renewals()
        
        # Verify renewal was attempted
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM subscription_billing_history
                WHERE user_id = 1
            """)
            count = cursor.fetchone()[0]
        
        assert count > 0


class TestWalletConsolidation:
    """Test wallet consolidation"""
    
    @pytest.mark.asyncio
    async def test_consolidate_above_threshold(self, payment_service, db_manager):
        """Test consolidating wallet above threshold"""
        from aisbf.payments.crypto.consolidation import WalletConsolidator
        
        consolidator = WalletConsolidator(
            db_manager,
            payment_service.wallet_manager
        )
        
        # Create user wallet with balance above threshold
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            
            # Create address
            cursor.execute("""
                INSERT INTO user_crypto_addresses
                (user_id, crypto_type, address, derivation_path, derivation_index)
                VALUES (1, 'btc', 'user_btc_address', 'm/44/0/0/0/0', 0)
            """)
            
            # Create wallet with high balance
            cursor.execute("""
                INSERT INTO user_crypto_wallets
                (user_id, crypto_type, balance_crypto, balance_fiat)
                VALUES (1, 'btc', 1.5, 50000.00)
            """)
            
            conn.commit()
        
        # Run consolidation
        await consolidator.consolidate_wallets()
        
        # Verify consolidation was queued
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM crypto_consolidation_queue
                WHERE user_id = 1 AND status = 'pending'
            """)
            count = cursor.fetchone()[0]
        
        assert count > 0


class TestEmailNotifications:
    """Test email notification system"""
    
    @pytest.mark.asyncio
    async def test_send_payment_success_notification(self, db_manager):
        """Test sending payment success notification"""
        from aisbf.payments.notifications.email import EmailNotificationService
        
        email_service = EmailNotificationService(db_manager)
        
        # Configure SMTP (mock)
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_config
                (smtp_host, smtp_port, smtp_username, smtp_password, from_email, from_name, use_tls)
                VALUES ('smtp.test.com', 587, 'test', 'pass', 'noreply@test.com', 'Test', 1)
            """)
            conn.commit()
        
        # Mock SMTP
        with patch('smtplib.SMTP') as mock_smtp:
            mock_server = Mock()
            mock_smtp.return_value = mock_server
            
            # Send notification
            await email_service.notify_payment_success(
                user_id=1,
                amount=10.00,
                currency='USD'
            )
            
            # Verify SMTP was called
            assert mock_smtp.called
    
    @pytest.mark.asyncio
    async def test_notification_queue_retry(self, db_manager):
        """Test notification retry on failure"""
        from aisbf.payments.notifications.email import EmailNotificationService
        
        email_service = EmailNotificationService(db_manager)
        
        # Queue a notification
        email_service._queue_notification(
            user_id=1,
            notification_type='payment_success',
            context={'amount': 10.00, 'currency': 'USD'},
            error='SMTP connection failed'
        )
        
        # Verify queued
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM email_notification_queue
                WHERE user_id = 1 AND status = 'pending'
            """)
            count = cursor.fetchone()[0]
        
        assert count == 1


class TestPaymentScheduler:
    """Test payment scheduler"""
    
    @pytest.mark.asyncio
    async def test_scheduler_distributed_lock(self, payment_service, db_manager):
        """Test scheduler distributed locking"""
        from aisbf.payments.scheduler import PaymentScheduler
        
        scheduler = PaymentScheduler(db_manager, payment_service)
        
        # Acquire lock
        acquired = await scheduler._acquire_lock('test_job')
        assert acquired is True
        
        # Try to acquire again (should fail)
        acquired2 = await scheduler._acquire_lock('test_job')
        assert acquired2 is False
        
        # Release lock
        await scheduler._release_lock('test_job')
        
        # Should be able to acquire again
        acquired3 = await scheduler._acquire_lock('test_job')
        assert acquired3 is True
    
    @pytest.mark.asyncio
    async def test_run_job_manually(self, payment_service, db_manager):
        """Test manually triggering a job"""
        from aisbf.payments.scheduler import PaymentScheduler
        
        scheduler = PaymentScheduler(db_manager, payment_service)
        
        # Mock job handler
        job_executed = False
        
        async def mock_handler():
            nonlocal job_executed
            job_executed = True
        
        # Replace handler
        scheduler.jobs[0] = ('test_job', 60, mock_handler)
        
        # Run job
        await scheduler.run_job_now('test_job')
        
        assert job_executed is True


class TestEndToEndFlow:
    """Test complete end-to-end payment flow"""
    
    @pytest.mark.asyncio
    async def test_complete_crypto_subscription_flow(self, payment_service, db_manager):
        """Test complete flow: crypto payment -> subscription creation -> renewal"""
        # 1. Create crypto address
        address = await payment_service.wallet_manager.get_or_create_user_address(1, 'btc')
        assert address is not None
        
        # 2. Simulate incoming payment
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO crypto_transactions
                (user_id, crypto_type, tx_hash, from_address, to_address, amount_crypto, confirmations, status)
                VALUES (1, 'btc', 'tx_001', 'sender', ?, 0.01, 3, 'confirmed')
            """, (address,))
            
            # Credit wallet
            cursor.execute("""
                INSERT INTO user_crypto_wallets
                (user_id, crypto_type, balance_crypto, balance_fiat)
                VALUES (1, 'btc', 0.01, 500.00)
            """)
            
            conn.commit()
        
        # 3. Create subscription tier
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO subscription_tiers
                (name, price_monthly, price_yearly, features_json, is_active)
                VALUES ('Pro', 10.00, 100.00, '{}', 1)
            """)
            tier_id = cursor.lastrowid
            conn.commit()
        
        # 4. Create subscription
        result = await payment_service.subscription_manager.create_subscription(
            user_id=1,
            tier_id=tier_id,
            billing_cycle='monthly',
            payment_method_id=1
        )
        
        assert result['success'] is True
        
        # 5. Verify subscription active
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status FROM user_subscriptions WHERE user_id = 1
            """)
            status = cursor.fetchone()[0]
        
        assert status == 'active'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
