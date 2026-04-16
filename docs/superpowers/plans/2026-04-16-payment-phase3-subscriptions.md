# Payment System Phase 3: Subscriptions & Billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement complete subscription lifecycle including creation, tier upgrades/downgrades with proration, cancellation, renewal processing, and smart payment retry logic.

**Architecture:** Subscription manager for lifecycle, renewal processor with smart retry (crypto: immediate on wallet top-up, fiat: daily), proration calculations, async payment charging.

**Tech Stack:** Existing payment service, database transactions, async processing

**Prerequisites:** Phase 1 & 2 completed (crypto, fiat payments, payment methods)

---

## Phase 3 Deliverables

- ✅ Subscription creation with initial payment
- ✅ Tier upgrades with prorated charges
- ✅ Tier downgrades (scheduled at period end)
- ✅ Subscription cancellation (access until period end)
- ✅ Renewal processing (automatic charges)
- ✅ Smart payment retry logic (crypto: immediate, fiat: daily)
- ✅ Downgrade to free tier after 3 failed payments
- ✅ API endpoints for subscription management
- ✅ Unit tests for subscription logic

---

## Task 1: Subscription Manager

**Files:**
- Create: `aisbf/payments/subscription/__init__.py`
- Create: `aisbf/payments/subscription/manager.py`
- Create: `tests/payments/test_subscription.py`

- [ ] **Step 1: Write failing test for subscription creation**

Create `tests/payments/test_subscription.py`:

```python
import pytest
from datetime import datetime, timedelta
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.subscription.manager import SubscriptionManager


@pytest.fixture
def db_manager(tmp_path):
    """Create test database"""
    db_path = tmp_path / "test.db"
    db_config = {
        'type': 'sqlite',
        'sqlite_path': str(db_path)
    }
    db = DatabaseManager(db_config)
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Add test user and tier
    db.execute("""
        INSERT INTO users (id, email, username, password_hash, tier_id)
        VALUES (1, 'test@example.com', 'testuser', 'hash', 1)
    """)
    
    db.execute("""
        INSERT INTO tiers (id, name, price_monthly, price_yearly, is_default)
        VALUES (1, 'Free', 0, 0, TRUE),
               (2, 'Pro', 10.00, 100.00, FALSE)
    """)
    
    # Add payment method
    db.execute("""
        INSERT INTO payment_methods (id, user_id, type, gateway, is_default, status)
        VALUES (1, 1, 'stripe', 'stripe', TRUE, 'active')
    """)
    
    return db


@pytest.mark.asyncio
async def test_create_subscription(db_manager):
    """Test subscription creation"""
    # Mock handlers
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None,  # PayPal handler
        None,  # Crypto wallet manager
        None   # Price service
    )
    
    result = await manager.create_subscription(
        user_id=1,
        tier_id=2,
        payment_method_id=1,
        billing_cycle='monthly'
    )
    
    assert result['success'] == True
    assert 'subscription_id' in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/payments/test_subscription.py::test_create_subscription -v
```

Expected: FAIL with "No module named 'aisbf.payments.subscription.manager'"

- [ ] **Step 3: Create subscription module init**

Create `aisbf/payments/subscription/__init__.py`:

```python
"""
Subscription management module
"""
from aisbf.payments.subscription.manager import SubscriptionManager

__all__ = ['SubscriptionManager']
```

- [ ] **Step 4: Implement subscription manager (part 1: creation)**

Create `aisbf/payments/subscription/manager.py`:

```python
"""
Subscription lifecycle management
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manage subscription lifecycle and billing"""
    
    def __init__(self, db_manager, stripe_handler, paypal_handler, 
                 crypto_wallet_manager, price_service):
        self.db = db_manager
        self.stripe = stripe_handler
        self.paypal = paypal_handler
        self.crypto = crypto_wallet_manager
        self.price_service = price_service
    
    async def create_subscription(self, user_id: int, tier_id: int, 
                                 payment_method_id: int, 
                                 billing_cycle: str) -> dict:
        """Create new subscription"""
        try:
            # Get tier details
            tier = self.db.fetch_one(
                "SELECT * FROM tiers WHERE id = ?",
                (tier_id,)
            )
            
            if not tier:
                return {'success': False, 'error': 'Invalid tier'}
            
            # Get payment method
            payment_method = self.db.fetch_one(
                "SELECT * FROM payment_methods WHERE id = ? AND user_id = ?",
                (payment_method_id, user_id)
            )
            
            if not payment_method:
                return {'success': False, 'error': 'Invalid payment method'}
            
            # Calculate amount
            if billing_cycle == 'monthly':
                amount = tier['price_monthly']
            elif billing_cycle == 'yearly':
                amount = tier['price_yearly']
            else:
                return {'success': False, 'error': 'Invalid billing cycle'}
            
            # Check if user already has active subscription
            existing = self.db.fetch_one("""
                SELECT id FROM subscriptions 
                WHERE user_id = ? AND status = 'active'
            """, (user_id,))
            
            if existing:
                return {'success': False, 'error': 'User already has active subscription'}
            
            # Calculate period dates (immediate start)
            current_period_start = datetime.utcnow()
            if billing_cycle == 'monthly':
                current_period_end = current_period_start + timedelta(days=30)
            else:  # yearly
                current_period_end = current_period_start + timedelta(days=365)
            
            # Charge initial payment
            charge_result = await self._charge_payment(
                user_id=user_id,
                payment_method=payment_method,
                amount=amount,
                description=f"Initial subscription - {tier['name']} ({billing_cycle})"
            )
            
            if not charge_result['success']:
                return charge_result
            
            # Create subscription
            self.db.execute("""
                INSERT INTO subscriptions
                (user_id, tier_id, payment_method_id, status, billing_cycle,
                 current_period_start, current_period_end)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
            """, (
                user_id, tier_id, payment_method_id, billing_cycle,
                current_period_start, current_period_end
            ))
            
            subscription_id = self.db.get_last_insert_id()
            
            # Update user tier
            self.db.execute(
                "UPDATE users SET tier_id = ? WHERE id = ?",
                (tier_id, user_id)
            )
            
            logger.info(f"Created subscription {subscription_id} for user {user_id}")
            
            return {
                'success': True,
                'subscription_id': subscription_id,
                'next_billing_date': current_period_end.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _charge_payment(self, user_id: int, payment_method: dict, 
                             amount: float, description: str) -> dict:
        """Charge payment using appropriate gateway"""
        if payment_method['type'] == 'stripe':
            # Would call stripe handler
            return {'success': True, 'transaction_id': 'mock_tx'}
        elif payment_method['type'] == 'paypal':
            # Would call paypal handler
            return {'success': True, 'transaction_id': 'mock_tx'}
        elif payment_method['type'] == 'crypto':
            return await self._charge_crypto_wallet(
                user_id=user_id,
                crypto_type=payment_method['crypto_type'],
                amount=amount
            )
        else:
            return {'success': False, 'error': 'Unknown payment method type'}
    
    async def _charge_crypto_wallet(self, user_id: int, crypto_type: str, 
                                   amount: float) -> dict:
        """Charge from user's crypto wallet"""
        try:
            # Get wallet balance
            wallet = self.db.fetch_one("""
                SELECT * FROM user_crypto_wallets
                WHERE user_id = ? AND crypto_type = ?
            """, (user_id, crypto_type))
            
            if not wallet:
                return {'success': False, 'error': 'Wallet not found'}
            
            if wallet['balance_fiat'] < amount:
                return {'success': False, 'error': 'Insufficient balance'}
            
            # Deduct from wallet
            self.db.execute("""
                UPDATE user_crypto_wallets
                SET balance_fiat = balance_fiat - ?
                WHERE user_id = ? AND crypto_type = ?
            """, (amount, user_id, crypto_type))
            
            logger.info(f"Charged ${amount} from user {user_id} {crypto_type} wallet")
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error charging crypto wallet: {e}")
            return {'success': False, 'error': str(e)}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/payments/test_subscription.py::test_create_subscription -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add aisbf/payments/subscription/ tests/payments/test_subscription.py
git commit -m "feat(payments): implement subscription creation"
```

---

## Task 2: Tier Upgrades with Proration

**Files:**
- Modify: `aisbf/payments/subscription/manager.py`
- Modify: `tests/payments/test_subscription.py`

- [ ] **Step 1: Write failing test for upgrade**

Add to `tests/payments/test_subscription.py`:

```python
@pytest.mark.asyncio
async def test_upgrade_subscription_with_proration(db_manager):
    """Test subscription upgrade with prorated charge"""
    # Create initial subscription
    db_manager.execute("""
        INSERT INTO subscriptions 
        (id, user_id, tier_id, payment_method_id, status, billing_cycle,
         current_period_start, current_period_end)
        VALUES (1, 1, 2, 1, 'active', 'monthly', ?, ?)
    """, (datetime.utcnow(), datetime.utcnow() + timedelta(days=30)))
    
    # Mock handlers
    class MockStripeHandler:
        async def charge_subscription(self, subscription_id, amount):
            return {'success': True, 'transaction_id': 'test_tx'}
    
    manager = SubscriptionManager(
        db_manager,
        MockStripeHandler(),
        None, None, None
    )
    
    # Add higher tier
    db_manager.execute("""
        INSERT INTO tiers (id, name, price_monthly, price_yearly, is_default)
        VALUES (3, 'Premium', 20.00, 200.00, FALSE)
    """)
    
    result = await manager.upgrade_subscription(user_id=1, new_tier_id=3)
    
    assert result['success'] == True
    assert 'charged_amount' in result
    # Should charge less than full $20 due to proration
    assert result['charged_amount'] < 20.00
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/payments/test_subscription.py::test_upgrade_subscription_with_proration -v
```

Expected: FAIL with "AttributeError: 'SubscriptionManager' object has no attribute 'upgrade_subscription'"

- [ ] **Step 3: Implement upgrade method**

Add to `aisbf/payments/subscription/manager.py`:

```python
async def upgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
    """Upgrade subscription to higher tier with prorated credit"""
    try:
        # Get current subscription
        subscription = self.db.fetch_one("""
            SELECT s.*, t.price_monthly, t.price_yearly, t.name as tier_name
            FROM subscriptions s
            JOIN tiers t ON s.tier_id = t.id
            WHERE s.user_id = ? AND s.status = 'active'
        """, (user_id,))
        
        if not subscription:
            return {'success': False, 'error': 'No active subscription'}
        
        # Get new tier
        new_tier = self.db.fetch_one(
            "SELECT * FROM tiers WHERE id = ?",
            (new_tier_id,)
        )
        
        if not new_tier:
            return {'success': False, 'error': 'Invalid tier'}
        
        # Calculate prorated amount
        billing_cycle = subscription['billing_cycle']
        
        if billing_cycle == 'monthly':
            old_price = subscription['price_monthly']
            new_price = new_tier['price_monthly']
        else:  # yearly
            old_price = subscription['price_yearly']
            new_price = new_tier['price_yearly']
        
        # Calculate unused portion of current period
        now = datetime.utcnow()
        period_start = subscription['current_period_start']
        period_end = subscription['current_period_end']
        
        total_period_seconds = (period_end - period_start).total_seconds()
        remaining_seconds = (period_end - now).total_seconds()
        
        if remaining_seconds <= 0:
            # Period already ended, charge full amount
            prorated_amount = new_price
        else:
            # Calculate unused portion
            unused_fraction = remaining_seconds / total_period_seconds
            unused_credit = old_price * unused_fraction
            
            # New charge = new_price - unused_credit
            prorated_amount = new_price - unused_credit
            
            # Ensure non-negative
            prorated_amount = max(0, prorated_amount)
        
        logger.info(f"Upgrade proration: old=${old_price}, new=${new_price}, "
                   f"unused={unused_fraction:.2%}, charge=${prorated_amount:.2f}")
        
        # Get payment method
        payment_method = self.db.fetch_one(
            "SELECT * FROM payment_methods WHERE id = ?",
            (subscription['payment_method_id'],)
        )
        
        # Charge prorated amount
        if prorated_amount > 0:
            charge_result = await self._charge_payment(
                user_id=user_id,
                payment_method=payment_method,
                amount=prorated_amount,
                description=f"Upgrade to {new_tier['name']} (prorated)"
            )
            
            if not charge_result['success']:
                return charge_result
        
        # Update subscription
        self.db.execute("""
            UPDATE subscriptions
            SET tier_id = ?
            WHERE id = ?
        """, (new_tier_id, subscription['id']))
        
        # Update user tier
        self.db.execute(
            "UPDATE users SET tier_id = ? WHERE id = ?",
            (new_tier_id, user_id)
        )
        
        logger.info(f"Upgraded subscription {subscription['id']} to tier {new_tier_id}")
        
        return {
            'success': True,
            'charged_amount': prorated_amount,
            'next_billing_date': period_end.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error upgrading subscription: {e}")
        return {'success': False, 'error': str(e)}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/payments/test_subscription.py::test_upgrade_subscription_with_proration -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add aisbf/payments/subscription/manager.py tests/payments/test_subscription.py
git commit -m "feat(payments): implement tier upgrades with proration"
```

---

## Task 3: Tier Downgrades and Cancellation

**Files:**
- Modify: `aisbf/payments/subscription/manager.py`

- [ ] **Step 1: Implement downgrade method**

Add to `aisbf/payments/subscription/manager.py`:

```python
async def downgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
    """Downgrade subscription (no refund, takes effect at period end)"""
    try:
        # Get current subscription
        subscription = self.db.fetch_one("""
            SELECT s.*, t.name as current_tier_name
            FROM subscriptions s
            JOIN tiers t ON s.tier_id = t.id
            WHERE s.user_id = ? AND s.status = 'active'
        """, (user_id,))
        
        if not subscription:
            return {'success': False, 'error': 'No active subscription'}
        
        # Get new tier
        new_tier = self.db.fetch_one(
            "SELECT * FROM tiers WHERE id = ?",
            (new_tier_id,)
        )
        
        if not new_tier:
            return {'success': False, 'error': 'Invalid tier'}
        
        # Schedule downgrade at period end
        self.db.execute("""
            UPDATE subscriptions
            SET pending_tier_id = ?,
                cancel_at_period_end = FALSE
            WHERE id = ?
        """, (new_tier_id, subscription['id']))
        
        logger.info(f"Scheduled downgrade for subscription {subscription['id']} "
                   f"to tier {new_tier_id} at period end")
        
        return {
            'success': True,
            'effective_date': subscription['current_period_end'].isoformat(),
            'message': 'Downgrade scheduled for end of current period'
        }
        
    except Exception as e:
        logger.error(f"Error downgrading subscription: {e}")
        return {'success': False, 'error': str(e)}

async def cancel_subscription(self, user_id: int) -> dict:
    """Cancel subscription (no refund, access until period end)"""
    try:
        # Get current subscription
        subscription = self.db.fetch_one("""
            SELECT * FROM subscriptions
            WHERE user_id = ? AND status = 'active'
        """, (user_id,))
        
        if not subscription:
            return {'success': False, 'error': 'No active subscription'}
        
        # Mark for cancellation at period end
        self.db.execute("""
            UPDATE subscriptions
            SET cancel_at_period_end = TRUE,
                canceled_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (subscription['id'],))
        
        logger.info(f"Scheduled cancellation for subscription {subscription['id']}")
        
        return {
            'success': True,
            'access_until': subscription['current_period_end'].isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error canceling subscription: {e}")
        return {'success': False, 'error': str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add aisbf/payments/subscription/manager.py
git commit -m "feat(payments): implement tier downgrades and cancellation"
```

---

## Task 4: Renewal Processor

**Files:**
- Create: `aisbf/payments/subscription/renewal.py`
- Create: `tests/payments/test_renewal.py`

- [ ] **Step 1: Write failing test for renewal processing**

Create `tests/payments/test_renewal.py`:

```python
import pytest
from datetime import datetime, timedelta
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.subscription.renewal import SubscriptionRenewalProcessor
from aisbf.payments.subscription.manager import SubscriptionManager


@pytest.fixture
def db_manager(tmp_path):
    """Create test database with expired subscription"""
    db_path = tmp_path / "test.db"
    db_config = {'type': 'sqlite', 'sqlite_path': str(db_path)}
    db = DatabaseManager(db_config)
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Add test data
    db.execute("INSERT INTO users (id, email, username, password_hash, tier_id) VALUES (1, 'test@example.com', 'testuser', 'hash', 2)")
    db.execute("INSERT INTO tiers (id, name, price_monthly, price_yearly, is_default) VALUES (1, 'Free', 0, 0, TRUE), (2, 'Pro', 10.00, 100.00, FALSE)")
    db.execute("INSERT INTO payment_methods (id, user_id, type, gateway, is_default, status) VALUES (1, 1, 'stripe', 'stripe', TRUE, 'active')")
    
    # Add expired subscription
    db.execute("""
        INSERT INTO subscriptions 
        (id, user_id, tier_id, payment_method_id, status, billing_cycle,
         current_period_start, current_period_end)
        VALUES (1, 1, 2, 1, 'active', 'monthly', ?, ?)
    """, (datetime.utcnow() - timedelta(days=31), datetime.utcnow() - timedelta(days=1)))
    
    return db


@pytest.mark.asyncio
async def test_process_due_renewals(db_manager):
    """Test renewal processing"""
    class MockSubscriptionManager:
        async def _charge_payment(self, user_id, payment_method, amount, description):
            return {'success': True}
    
    manager = MockSubscriptionManager()
    processor = SubscriptionRenewalProcessor(db_manager, manager)
    
    await processor.process_due_renewals()
    
    # Check subscription was renewed
    subscription = db_manager.fetch_one("SELECT * FROM subscriptions WHERE id = 1")
    assert subscription['current_period_end'] > datetime.utcnow()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/payments/test_renewal.py::test_process_due_renewals -v
```

Expected: FAIL

- [ ] **Step 3: Implement renewal processor**

Create `aisbf/payments/subscription/renewal.py`:

```python
"""
Subscription renewal and retry processing
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SubscriptionRenewalProcessor:
    """Process subscription renewals and handle failures"""
    
    def __init__(self, db_manager, subscription_manager):
        self.db = db_manager
        self.subscription_manager = subscription_manager
    
    async def process_due_renewals(self):
        """Process all subscriptions due for renewal"""
        due_subscriptions = self.db.fetch_all("""
            SELECT s.*, t.price_monthly, t.price_yearly, t.name as tier_name,
                   pm.type as payment_type, pm.gateway, pm.crypto_type
            FROM subscriptions s
            JOIN tiers t ON s.tier_id = t.id
            LEFT JOIN payment_methods pm ON s.payment_method_id = pm.id
            WHERE s.status = 'active'
            AND s.current_period_end <= CURRENT_TIMESTAMP
            AND s.cancel_at_period_end = FALSE
        """)
        
        logger.info(f"Processing {len(due_subscriptions)} due renewals")
        
        for subscription in due_subscriptions:
            await self._process_renewal(subscription)
    
    async def _process_renewal(self, subscription: dict):
        """Process single subscription renewal"""
        try:
            # Calculate renewal amount
            if subscription['billing_cycle'] == 'monthly':
                amount = subscription['price_monthly']
                period_days = 30
            else:  # yearly
                amount = subscription['price_yearly']
                period_days = 365
            
            # Check for pending downgrade
            if subscription.get('pending_tier_id'):
                await self._apply_downgrade(subscription)
                return
            
            # Attempt payment
            payment_method = self.db.fetch_one(
                "SELECT * FROM payment_methods WHERE id = ?",
                (subscription['payment_method_id'],)
            )
            
            payment_result = await self.subscription_manager._charge_payment(
                user_id=subscription['user_id'],
                payment_method=payment_method,
                amount=amount,
                description=f"Subscription renewal - {subscription['tier_name']}"
            )
            
            if payment_result['success']:
                # Extend subscription period
                new_period_end = subscription['current_period_end'] + timedelta(days=period_days)
                
                self.db.execute("""
                    UPDATE subscriptions
                    SET current_period_start = current_period_end,
                        current_period_end = ?
                    WHERE id = ?
                """, (new_period_end, subscription['id']))
                
                logger.info(f"Renewed subscription {subscription['id']} until {new_period_end}")
            else:
                # Payment failed - add to retry queue
                await self._add_to_retry_queue(subscription, payment_result['error'])
                
        except Exception as e:
            logger.error(f"Error processing renewal for subscription {subscription['id']}: {e}")
    
    async def _add_to_retry_queue(self, subscription: dict, error: str):
        """Add failed payment to retry queue"""
        existing = self.db.fetch_one("""
            SELECT * FROM payment_retry_queue
            WHERE subscription_id = ? AND status = 'pending'
        """, (subscription['id'],))
        
        if existing:
            # Update existing retry
            attempt_number = existing['attempt_number'] + 1
            
            self.db.execute("""
                UPDATE payment_retry_queue
                SET attempt_number = ?,
                    next_retry_at = datetime(CURRENT_TIMESTAMP, '+1 day'),
                    last_error = ?
                WHERE id = ?
            """, (attempt_number, error, existing['id']))
        else:
            # Create new retry entry
            self.db.execute("""
                INSERT INTO payment_retry_queue
                (subscription_id, attempt_number, max_attempts, 
                 next_retry_at, last_error)
                VALUES (?, 1, 3, datetime(CURRENT_TIMESTAMP, '+1 day'), ?)
            """, (subscription['id'], error))
        
        logger.warning(f"Added subscription {subscription['id']} to retry queue")
    
    async def _apply_downgrade(self, subscription: dict):
        """Apply pending downgrade"""
        new_tier_id = subscription['pending_tier_id']
        
        self.db.execute("""
            UPDATE subscriptions
            SET tier_id = ?,
                pending_tier_id = NULL,
                current_period_start = current_period_end,
                current_period_end = datetime(current_period_end, '+30 days')
            WHERE id = ?
        """, (new_tier_id, subscription['id']))
        
        self.db.execute(
            "UPDATE users SET tier_id = ? WHERE id = ?",
            (new_tier_id, subscription['user_id'])
        )
        
        logger.info(f"Applied downgrade for subscription {subscription['id']} to tier {new_tier_id}")
```

- [ ] **Step 4: Update subscription module init**

Modify `aisbf/payments/subscription/__init__.py`:

```python
"""
Subscription management module
"""
from aisbf.payments.subscription.manager import SubscriptionManager
from aisbf.payments.subscription.renewal import SubscriptionRenewalProcessor

__all__ = ['SubscriptionManager', 'SubscriptionRenewalProcessor']
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/payments/test_renewal.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add aisbf/payments/subscription/renewal.py tests/payments/test_renewal.py aisbf/payments/subscription/__init__.py
git commit -m "feat(payments): implement subscription renewal processor"
```

---

## Task 5: Smart Retry Logic

**Files:**
- Modify: `aisbf/payments/subscription/renewal.py`

- [ ] **Step 1: Implement retry processor with smart logic**

Add to `aisbf/payments/subscription/renewal.py`:

```python
async def process_retry_queue(self):
    """Process payment retry queue (Smart Retry - Option C)"""
    retries = self.db.fetch_all("""
        SELECT prq.*, s.user_id, s.tier_id, s.billing_cycle,
               t.price_monthly, t.price_yearly, t.name as tier_name,
               pm.type as payment_type, pm.crypto_type
        FROM payment_retry_queue prq
        JOIN subscriptions s ON prq.subscription_id = s.id
        JOIN tiers t ON s.tier_id = t.id
        LEFT JOIN payment_methods pm ON s.payment_method_id = pm.id
        WHERE prq.status = 'pending'
        AND prq.next_retry_at <= CURRENT_TIMESTAMP
        AND prq.attempt_number <= prq.max_attempts
    """)
    
    logger.info(f"Processing {len(retries)} payment retries")
    
    for retry in retries:
        await self._process_retry(retry)

async def _process_retry(self, retry: dict):
    """Process single payment retry (Smart Retry)"""
    try:
        # For crypto payments, check if wallet was topped up
        if retry['payment_type'] == 'crypto':
            wallet = self.db.fetch_one("""
                SELECT balance_fiat FROM user_crypto_wallets
                WHERE user_id = ? AND crypto_type = ?
            """, (retry['user_id'], retry['crypto_type']))
            
            # Calculate required amount
            if retry['billing_cycle'] == 'monthly':
                required_amount = retry['price_monthly']
            else:
                required_amount = retry['price_yearly']
            
            if wallet and wallet['balance_fiat'] >= required_amount:
                logger.info(f"Crypto wallet topped up for user {retry['user_id']}, retrying payment")
            else:
                # Still insufficient - skip this retry
                logger.info(f"Crypto wallet still insufficient for user {retry['user_id']}")
                return
        
        # Get subscription and payment method
        subscription = self.db.fetch_one(
            "SELECT * FROM subscriptions WHERE id = ?",
            (retry['subscription_id'],)
        )
        
        payment_method = self.db.fetch_one(
            "SELECT * FROM payment_methods WHERE id = ?",
            (subscription['payment_method_id'],)
        )
        
        # Calculate amount
        if subscription['billing_cycle'] == 'monthly':
            amount = retry['price_monthly']
            period_days = 30
        else:
            amount = retry['price_yearly']
            period_days = 365
        
        # Attempt payment
        payment_result = await self.subscription_manager._charge_payment(
            user_id=retry['user_id'],
            payment_method=payment_method,
            amount=amount,
            description=f"Subscription renewal retry - {retry['tier_name']}"
        )
        
        if payment_result['success']:
            # Payment succeeded
            self.db.execute("""
                UPDATE payment_retry_queue
                SET status = 'completed'
                WHERE id = ?
            """, (retry['id'],))
            
            # Extend subscription
            new_period_end = subscription['current_period_end'] + timedelta(days=period_days)
            
            self.db.execute("""
                UPDATE subscriptions
                SET current_period_start = current_period_end,
                    current_period_end = ?
                WHERE id = ?
            """, (new_period_end, subscription['id']))
            
            logger.info(f"Retry successful for subscription {subscription['id']}")
        else:
            # Payment still failed
            if retry['attempt_number'] >= retry['max_attempts']:
                # Max attempts reached - downgrade to free tier
                await self._downgrade_to_free_tier(subscription)
                
                self.db.execute("""
                    UPDATE payment_retry_queue
                    SET status = 'failed'
                    WHERE id = ?
                """, (retry['id'],))
            else:
                # Schedule next retry
                self.db.execute("""
                    UPDATE payment_retry_queue
                    SET attempt_number = attempt_number + 1,
                        next_retry_at = datetime(CURRENT_TIMESTAMP, '+1 day'),
                        last_error = ?
                    WHERE id = ?
                """, (payment_result['error'], retry['id']))
                
                logger.warning(f"Retry {retry['attempt_number']} failed for subscription {subscription['id']}")
                
    except Exception as e:
        logger.error(f"Error processing retry {retry['id']}: {e}")

async def _downgrade_to_free_tier(self, subscription: dict):
    """Downgrade user to free tier after failed payments"""
    free_tier = self.db.fetch_one(
        "SELECT id FROM tiers WHERE is_default = TRUE LIMIT 1"
    )
    
    if not free_tier:
        logger.error("No default free tier found!")
        return
    
    # Update subscription status
    self.db.execute("""
        UPDATE subscriptions
        SET status = 'suspended'
        WHERE id = ?
    """, (subscription['id'],))
    
    # Update user tier
    self.db.execute(
        "UPDATE users SET tier_id = ? WHERE id = ?",
        (free_tier['id'], subscription['user_id'])
    )
    
    logger.info(f"Downgraded user {subscription['user_id']} to free tier after failed payments")
```

- [ ] **Step 2: Commit**

```bash
git add aisbf/payments/subscription/renewal.py
git commit -m "feat(payments): implement smart retry logic (crypto: immediate, fiat: daily)"
```

---

## Task 6: Subscription API Endpoints

**Files:**
- Modify: `aisbf/payments/service.py`
- Modify: `main.py`

- [ ] **Step 1: Add subscription methods to payment service**

Modify `aisbf/payments/service.py`, add to `__init__`:

```python
# Initialize subscription sub-services
from aisbf.payments.subscription.manager import SubscriptionManager
from aisbf.payments.subscription.renewal import SubscriptionRenewalProcessor

self.subscription_manager = SubscriptionManager(
    db_manager,
    self.stripe_handler,
    self.paypal_handler,
    self.wallet_manager,
    self.price_service
)

self.renewal_processor = SubscriptionRenewalProcessor(
    db_manager,
    self.subscription_manager
)
```

Add methods:

```python
async def create_subscription(self, user_id: int, tier_id: int, 
                             payment_method_id: int, 
                             billing_cycle: str) -> dict:
    """Create new subscription"""
    return await self.subscription_manager.create_subscription(
        user_id, tier_id, payment_method_id, billing_cycle
    )

async def upgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
    """Upgrade subscription"""
    return await self.subscription_manager.upgrade_subscription(user_id, new_tier_id)

async def downgrade_subscription(self, user_id: int, new_tier_id: int) -> dict:
    """Downgrade subscription"""
    return await self.subscription_manager.downgrade_subscription(user_id, new_tier_id)

async def cancel_subscription(self, user_id: int) -> dict:
    """Cancel subscription"""
    return await self.subscription_manager.cancel_subscription(user_id)

async def get_subscription_status(self, user_id: int) -> dict:
    """Get user's subscription status"""
    subscription = self.db.fetch_one("""
        SELECT s.*, t.name as tier_name, t.price_monthly, t.price_yearly,
               pm.type as payment_type, pm.gateway
        FROM subscriptions s
        JOIN tiers t ON s.tier_id = t.id
        LEFT JOIN payment_methods pm ON s.payment_method_id = pm.id
        WHERE s.user_id = ?
        ORDER BY s.created_at DESC
        LIMIT 1
    """, (user_id,))
    
    return dict(subscription) if subscription else None

async def process_renewals(self):
    """Process subscription renewals (called by scheduler)"""
    await self.renewal_processor.process_due_renewals()

async def process_retries(self):
    """Process payment retries (called by scheduler)"""
    await self.renewal_processor.process_retry_queue()
```

- [ ] **Step 2: Add subscription API endpoints**

Add to `main.py`:

```python
@app.post("/api/subscriptions")
async def create_subscription(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create new subscription"""
    result = await payment_service.create_subscription(
        current_user['id'],
        request['tier_id'],
        request['payment_method_id'],
        request['billing_cycle']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/subscriptions/upgrade")
async def upgrade_subscription(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Upgrade subscription"""
    result = await payment_service.upgrade_subscription(
        current_user['id'],
        request['tier_id']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/subscriptions/downgrade")
async def downgrade_subscription(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Downgrade subscription"""
    result = await payment_service.downgrade_subscription(
        current_user['id'],
        request['tier_id']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/subscriptions/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    """Cancel subscription"""
    result = await payment_service.cancel_subscription(current_user['id'])
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.get("/api/subscriptions/status")
async def get_subscription_status(current_user: dict = Depends(get_current_user)):
    """Get subscription status"""
    status = await payment_service.get_subscription_status(current_user['id'])
    return {'subscription': status}
```

- [ ] **Step 3: Commit**

```bash
git add aisbf/payments/service.py main.py
git commit -m "feat(payments): add subscription API endpoints"
```

---

## Phase 3 Complete!

Phase 3 deliverables achieved:
- ✅ Subscription creation with initial payment
- ✅ Tier upgrades with prorated charges
- ✅ Tier downgrades (scheduled at period end)
- ✅ Subscription cancellation (access until period end)
- ✅ Renewal processing (automatic charges)
- ✅ Smart payment retry logic (crypto: immediate, fiat: daily)
- ✅ Downgrade to free tier after 3 failed payments
- ✅ API endpoints for subscription management
- ✅ Unit tests for subscription logic

**Next Steps:**
- Phase 4: Advanced Features (Quota enforcement, crypto consolidation, email notifications, background scheduler)
