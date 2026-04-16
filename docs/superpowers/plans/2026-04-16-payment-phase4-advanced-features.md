# Phase 4: Advanced Features - Implementation Plan

**Branch:** `feature/subscription-payment-system`  
**Phase:** 4 of 4  
**Focus:** Quota enforcement, wallet consolidation, email notifications, background scheduler

## Overview

This phase implements the advanced features that complete the subscription payment system:
- Quota enforcement based on tier limits (creation order, never delete configs)
- Crypto wallet consolidation to admin addresses
- Email notifications for payment events (admin configurable)
- Background scheduler for monitoring and processing tasks

## Prerequisites

- Phase 1 completed (foundation, crypto payments)
- Phase 2 completed (fiat payments)
- Phase 3 completed (subscriptions, billing, renewals)

## Tasks

### Task 1: Quota Enforcement Service

**Goal:** Implement quota enforcement that respects tier limits using creation order

**Test File:** `tests/payments/subscription/test_quota.py`

**Failing Tests:**
```python
async def test_quota_enforcement_creation_order():
    """Test that oldest configs are used when quota exceeded"""
    # User has tier with max_configs=2
    # Create 3 configs
    # Verify oldest 2 are active, newest is inactive
    
async def test_quota_enforcement_never_deletes():
    """Test that configs are never deleted, only marked inactive"""
    # Create configs exceeding quota
    # Verify all configs exist in database
    # Verify only quota-allowed configs are active
    
async def test_quota_enforcement_on_downgrade():
    """Test quota enforcement when downgrading tiers"""
    # User has 5 configs on premium tier (max 10)
    # Downgrade to basic tier (max 2)
    # Verify oldest 2 remain active, others inactive
    
async def test_quota_enforcement_on_upgrade():
    """Test quota expansion when upgrading tiers"""
    # User has 5 configs (3 active, 2 inactive) on basic tier
    # Upgrade to premium tier (max 10)
    # Verify all 5 configs become active (by creation order)
```

**Implementation:**
- Create `aisbf/payments/subscription/quota.py`
- Implement `QuotaEnforcer` class:
  - `enforce_quota(user_id: str, tier: SubscriptionTier)` - Apply quota limits
  - `get_active_configs(user_id: str)` - Get configs within quota
  - `reactivate_configs(user_id: str, new_limit: int)` - Reactivate on upgrade
- Never delete configs, only mark `is_active=False`
- Use creation timestamp for ordering
- Update subscription manager to call quota enforcer on tier changes

**Verification:**
```bash
pytest tests/payments/subscription/test_quota.py -v
```

**Commit:** `feat(payments): implement quota enforcement with creation order`

---

### Task 2: Wallet Consolidation Service

**Goal:** Implement automatic consolidation of crypto payments to admin addresses

**Test File:** `tests/payments/crypto/test_consolidation.py`

**Failing Tests:**
```python
async def test_consolidation_threshold_check():
    """Test that consolidation only happens above threshold"""
    # Wallet has balance below threshold
    # Verify no consolidation triggered
    # Add balance above threshold
    # Verify consolidation triggered
    
async def test_consolidation_transaction_creation():
    """Test consolidation transaction is created correctly"""
    # Wallet has balance above threshold
    # Trigger consolidation
    # Verify transaction sends to admin address
    # Verify transaction includes proper fee calculation
    
async def test_consolidation_multiple_wallets():
    """Test consolidation processes multiple wallets"""
    # Multiple user wallets with balances above threshold
    # Run consolidation job
    # Verify all eligible wallets consolidated
    
async def test_consolidation_respects_pending_payments():
    """Test consolidation doesn't interfere with pending payments"""
    # Wallet has pending payment + extra balance
    # Verify consolidation only moves extra balance
```

**Implementation:**
- Create `aisbf/payments/crypto/consolidation.py`
- Implement `WalletConsolidator` class:
  - `check_consolidation_needed(wallet_address: str, crypto_type: str)` - Check threshold
  - `consolidate_wallet(wallet_address: str, crypto_type: str)` - Execute consolidation
  - `consolidate_all_wallets()` - Batch consolidation job
- Admin configurable thresholds per crypto type
- Respect pending payments (don't consolidate reserved amounts)
- Record consolidation transactions in database
- Add admin addresses to settings

**Verification:**
```bash
pytest tests/payments/crypto/test_consolidation.py -v
```

**Commit:** `feat(payments): implement crypto wallet consolidation`

---

### Task 3: Email Notification Service

**Goal:** Implement email notifications for payment events with admin configuration

**Test File:** `tests/payments/notifications/test_email.py`

**Failing Tests:**
```python
async def test_payment_success_email():
    """Test email sent on successful payment"""
    # Mock email service
    # Process successful payment
    # Verify email sent with correct template and data
    
async def test_payment_failed_email():
    """Test email sent on payment failure"""
    # Mock email service
    # Process failed payment
    # Verify email sent with failure details
    
async def test_subscription_upgraded_email():
    """Test email sent on tier upgrade"""
    # Mock email service
    # Upgrade subscription
    # Verify email sent with new tier details
    
async def test_subscription_downgraded_email():
    """Test email sent on tier downgrade"""
    # Mock email service
    # Downgrade subscription
    # Verify email sent with downgrade details
    
async def test_email_admin_configuration():
    """Test admin can enable/disable notification types"""
    # Disable payment success emails
    # Process successful payment
    # Verify no email sent
    # Enable payment success emails
    # Process successful payment
    # Verify email sent
```

**Implementation:**
- Create `aisbf/payments/notifications/email.py`
- Implement `EmailNotificationService` class:
  - `send_payment_success(user_email: str, payment: Payment)` - Success notification
  - `send_payment_failed(user_email: str, payment: Payment)` - Failure notification
  - `send_subscription_upgraded(user_email: str, subscription: Subscription)` - Upgrade notification
  - `send_subscription_downgraded(user_email: str, subscription: Subscription)` - Downgrade notification
  - `send_subscription_cancelled(user_email: str, subscription: Subscription)` - Cancellation notification
  - `send_payment_retry(user_email: str, payment: Payment, attempt: int)` - Retry notification
- Admin configurable per notification type (stored in database)
- Email templates with proper formatting
- Integration with existing email service (if any) or use SMTP
- Add email settings to admin configuration

**Verification:**
```bash
pytest tests/payments/notifications/test_email.py -v
```

**Commit:** `feat(payments): implement email notification service`

---

### Task 4: Background Scheduler

**Goal:** Implement background scheduler for monitoring and processing tasks

**Test File:** `tests/payments/test_scheduler.py`

**Failing Tests:**
```python
async def test_scheduler_blockchain_monitoring():
    """Test scheduler runs blockchain monitoring job"""
    # Mock blockchain monitor
    # Run scheduler cycle
    # Verify blockchain monitor called
    
async def test_scheduler_renewal_processing():
    """Test scheduler processes subscription renewals"""
    # Create subscription due for renewal
    # Run scheduler cycle
    # Verify renewal processed
    
async def test_scheduler_payment_retry():
    """Test scheduler retries failed payments"""
    # Create failed payment eligible for retry
    # Run scheduler cycle
    # Verify retry attempted
    
async def test_scheduler_wallet_consolidation():
    """Test scheduler runs wallet consolidation"""
    # Create wallets above consolidation threshold
    # Run scheduler cycle
    # Verify consolidation executed
    
async def test_scheduler_distributed_locking():
    """Test scheduler uses distributed locks for horizontal scaling"""
    # Start two scheduler instances
    # Verify only one processes each job
    # Verify no duplicate processing
```

**Implementation:**
- Create `aisbf/payments/scheduler.py`
- Implement `PaymentScheduler` class:
  - `run_blockchain_monitoring()` - Monitor blockchain for payments (every 1 min)
  - `run_renewal_processing()` - Process subscription renewals (every 1 hour)
  - `run_payment_retry()` - Retry failed payments (daily)
  - `run_wallet_consolidation()` - Consolidate crypto wallets (daily)
  - `run_price_update()` - Update crypto prices (every 5 min)
- Use distributed locking (Redis or database) for horizontal scaling
- Configurable job intervals
- Error handling and logging
- Health check endpoint for monitoring
- Add startup hook in `main.py` to start scheduler

**Verification:**
```bash
pytest tests/payments/test_scheduler.py -v
```

**Commit:** `feat(payments): implement background scheduler with distributed locking`

---

### Task 5: Admin Configuration API

**Goal:** Implement API endpoints for admin configuration of payment system

**Test File:** `tests/payments/test_admin_api.py`

**Failing Tests:**
```python
async def test_update_price_sources():
    """Test admin can configure price sources"""
    # Update price sources configuration
    # Verify configuration saved
    # Verify price service uses new sources
    
async def test_update_blockchain_monitoring():
    """Test admin can configure blockchain monitoring"""
    # Switch between API polling and webhook modes
    # Verify configuration saved
    # Verify monitor uses new mode
    
async def test_update_consolidation_thresholds():
    """Test admin can configure consolidation thresholds"""
    # Update thresholds per crypto type
    # Verify configuration saved
    # Verify consolidator uses new thresholds
    
async def test_update_email_notifications():
    """Test admin can enable/disable email notifications"""
    # Toggle notification types
    # Verify configuration saved
    # Verify email service respects settings
    
async def test_update_scheduler_intervals():
    """Test admin can configure scheduler job intervals"""
    # Update job intervals
    # Verify configuration saved
    # Verify scheduler uses new intervals
```

**Implementation:**
- Add admin API endpoints to `main.py`:
  - `PUT /api/admin/payments/config/price-sources` - Configure price sources
  - `PUT /api/admin/payments/config/blockchain-monitoring` - Configure monitoring mode
  - `PUT /api/admin/payments/config/consolidation` - Configure consolidation thresholds
  - `PUT /api/admin/payments/config/email-notifications` - Configure email settings
  - `PUT /api/admin/payments/config/scheduler` - Configure scheduler intervals
  - `GET /api/admin/payments/config` - Get all payment configuration
- Store configuration in database (new `payment_config` table)
- Require admin authentication
- Validate configuration values
- Apply configuration changes without restart (hot reload)

**Verification:**
```bash
pytest tests/payments/test_admin_api.py -v
curl -X GET http://localhost:8000/api/admin/payments/config
```

**Commit:** `feat(payments): implement admin configuration API`

---

### Task 6: Integration Testing

**Goal:** End-to-end integration tests for complete payment flow

**Test File:** `tests/payments/test_integration.py`

**Failing Tests:**
```python
async def test_complete_crypto_payment_flow():
    """Test complete flow: subscribe -> pay with crypto -> quota enforced"""
    # Create subscription
    # Generate crypto payment address
    # Simulate blockchain payment
    # Verify payment processed
    # Verify subscription activated
    # Verify quota enforced
    # Verify email sent
    
async def test_complete_fiat_payment_flow():
    """Test complete flow: subscribe -> pay with Stripe -> quota enforced"""
    # Create subscription
    # Process Stripe payment
    # Verify payment processed
    # Verify subscription activated
    # Verify quota enforced
    # Verify email sent
    
async def test_upgrade_downgrade_flow():
    """Test complete upgrade/downgrade flow with prorated charges"""
    # Create basic subscription
    # Upgrade to premium (verify prorated charge)
    # Downgrade to basic (verify no refund)
    # Verify quota adjusted
    # Verify emails sent
    
async def test_payment_retry_flow():
    """Test complete payment retry flow"""
    # Create subscription with failed payment
    # Verify retry scheduled
    # Simulate retry attempts
    # Verify downgrade after max retries
    # Verify emails sent
    
async def test_wallet_consolidation_flow():
    """Test complete wallet consolidation flow"""
    # Multiple users pay with crypto
    # Wallets accumulate balance
    # Run consolidation job
    # Verify funds moved to admin addresses
```

**Implementation:**
- Create comprehensive integration tests
- Use test database and mock external services
- Test all major user flows end-to-end
- Verify database state at each step
- Verify email notifications sent
- Verify quota enforcement applied

**Verification:**
```bash
pytest tests/payments/test_integration.py -v
```

**Commit:** `test(payments): add comprehensive integration tests`

---

## Phase 4 Completion Checklist

- [ ] Task 1: Quota enforcement service implemented and tested
- [ ] Task 2: Wallet consolidation service implemented and tested
- [ ] Task 3: Email notification service implemented and tested
- [ ] Task 4: Background scheduler implemented and tested
- [ ] Task 5: Admin configuration API implemented and tested
- [ ] Task 6: Integration tests passing
- [ ] All Phase 4 tests passing
- [ ] Code reviewed and refactored
- [ ] Documentation updated
- [ ] Phase 4 committed to git

## Next Steps

After Phase 4 completion:
1. Run full test suite across all phases
2. Manual testing of complete system
3. Update main documentation
4. Create pull request for review
5. Deploy to staging environment
6. Production deployment planning

## Notes

- Phase 4 completes the subscription payment system
- All features are now production-ready
- System supports horizontal scaling with distributed locking
- Admin has full control over payment configuration
- Users receive email notifications for all payment events
- Quota enforcement ensures fair usage across tiers
