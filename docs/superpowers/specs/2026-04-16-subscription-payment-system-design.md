# Subscription Payment System Design

**Date:** 2026-04-16  
**Author:** AI Assistant  
**Status:** Draft for Review

## Overview

Complete subscription payment system for AISBF with support for fiat (Stripe, PayPal) and cryptocurrency (BTC, ETH, USDT, USDC) payments. The system handles monthly/yearly subscriptions, tier upgrades/downgrades, payment retries, crypto wallet management, and quota enforcement.

## Requirements Summary

### Payment Types

**Fiat Payments (Stripe, PayPal):**
- User authenticates with payment gateway when adding payment method
- Authorization hold (not charge) for card verification, immediately released
- Automatic charging on subscription creation and renewals
- Managed by external gateway (Stripe/PayPal handles subscription logic)

**Crypto Payments (BTC, ETH, USDT, USDC):**
- HD wallet derivation (BIP32/BIP44) - one master seed per crypto type
- Unique address generated for each user per crypto type
- User manually sends crypto to their address
- System monitors blockchain for incoming transactions
- Converts crypto to fiat equivalent using multi-exchange pricing
- Credits user's wallet balance in fiat
- Subscription charges deduct from wallet balance
- Automatic consolidation to admin address when threshold exceeded

### Subscription Lifecycle

**Tier Changes:**
- **Upgrade:** Prorated charge (new tier price - unused portion of old tier)
- **Downgrade:** No refund, takes effect at period end
- **Cancellation:** No refund, access until period end

**Billing Cycle:**
- Immediate start (Option A) - billing cycle starts on upgrade date
- Monthly: 30 days, Yearly: 365 days

**Payment Failures:**
- **Retry Logic (Smart Retry - Option C):**
  - Crypto: Retry immediately when wallet topped up
  - Fiat: Retry daily (fixed schedule)
- **Max 3 attempts** over 3 days
- After 3 failures: Downgrade to free tier
- Email notifications at each stage

### Quota Enforcement

**Tier Limits:**
- Max providers, rotations, autoselections
- Max models per rotation/autoselection
- Max requests per day/month

**Enforcement Strategy (Creation Order - Option A):**
- Use oldest N configs when quota exceeded
- Never delete user configs
- Filter at runtime based on current tier
- Configs beyond quota are ignored but preserved

### Technical Requirements

**Architecture:**
- Fully async/non-blocking operations
- All external API calls use `asyncio` and `httpx`
- Background tasks with distributed locking
- Database-backed state for horizontal scaling
- Multiple instances can run concurrently

**Crypto Monitoring:**
- **API Polling (Option B):** Query blockchain APIs every 60 seconds
- **Webhooks (Option C):** Real-time notifications from BlockCypher/Alchemy
- **Admin Configurable:** Choose between API or webhook mode

**Price Sources:**
- **Multi-Exchange Averaging (Option B):** Query 2-3 exchanges, use average
- **Admin Configurable:** Add/remove/prioritize price sources
- Default sources: Coinbase, Binance, Kraken

**Email Notifications:**
- **Admin Configurable (Option D):** Enable/disable each notification type
- Types: payment_failed, subscription_renewed, subscription_upgraded, etc.
- Queue-based with retry logic

## Architecture

### System Components

```
aisbf/payments/
├── service.py              # Main PaymentService orchestrator
├── crypto/
│   ├── wallet.py           # HD wallet (BIP32/BIP44)
│   ├── monitor.py          # Blockchain monitoring
│   ├── consolidation.py    # Wallet consolidation
│   └── pricing.py          # Multi-exchange pricing
├── fiat/
│   ├── stripe_handler.py   # Stripe integration
│   └── paypal_handler.py   # PayPal integration
├── subscription/
│   ├── manager.py          # Subscription lifecycle
│   ├── renewal.py          # Renewal processing
│   └── quota.py            # Quota enforcement
├── notifications/
│   └── email.py            # Email notifications
├── scheduler.py            # Background tasks
└── models.py               # Pydantic models
```

### Database Schema

**Core Tables:**
- `crypto_master_keys` - Encrypted BIP39 seeds (one per crypto type)
- `user_crypto_addresses` - Derived addresses (BIP44 paths)
- `user_crypto_wallets` - Balance tracking (crypto + fiat equivalent)
- `crypto_transactions` - Incoming payments with confirmations
- `payment_methods` - User payment methods (stripe/paypal/crypto)
- `subscriptions` - Active subscriptions with billing cycles
- `payment_transactions` - All payment attempts and results
- `payment_retry_queue` - Failed payment retry management

**Configuration Tables:**
- `crypto_price_sources` - Configurable price APIs
- `crypto_consolidation_settings` - Per-crypto thresholds
- `email_notification_settings` - Admin-configurable notifications
- `payment_gateway_config` - Stripe/PayPal credentials

**Background Job Tables:**
- `job_locks` - Distributed locking for multi-instance
- `crypto_consolidation_queue` - Pending consolidations
- `email_notification_queue` - Pending emails

**Tracking Tables:**
- `api_requests` - Request counting for quotas
- `crypto_webhooks` - Registered webhook IDs

### Async Architecture

**Non-Blocking Principles:**
1. All external API calls use `asyncio.to_thread()` or `httpx.AsyncClient`
2. Database operations use connection pooling
3. Background tasks run in separate async loops
4. API endpoints return immediately, processing continues in background
5. Distributed locks prevent duplicate processing across instances

**Background Task Scheduler:**
- Crypto monitoring: Every 60 seconds
- Renewal processing: Every 5 minutes
- Retry processing: Every 10 minutes
- Consolidation check: Every 1 hour
- Email sending: Every 30 seconds
- Database cleanup: Every 24 hours

**Distributed Locking:**
- Uses database `job_locks` table
- Each task acquires lock before running
- Lock expires after TTL (prevents deadlocks)
- Only one instance processes each task at a time

## Detailed Design

### 1. Crypto Wallet Management

**HD Wallet Implementation:**
- Generate BIP39 mnemonic (24 words) for each crypto type
- Encrypt with Fernet (symmetric encryption)
- Store encrypted seed in `crypto_master_keys` table
- Derive addresses using BIP44 paths: `m/44'/coin_type'/0'/0/index`
- Each user gets unique index, deterministic address generation

**Coin Types (BIP44):**
- Bitcoin: 0
- Ethereum: 60
- USDT/USDC: 60 (ERC20 uses Ethereum)

**Address Generation:**
```python
# Bitcoin: P2WPKH (native segwit, bc1...)
# Ethereum: Standard 0x... address
# USDT/USDC: Same as Ethereum (ERC20 tokens)
```

**Security:**
- Master seeds never leave server
- Encrypted at rest with rotation-capable key ID
- Private keys derived on-demand, never stored
- Consolidation uses derived keys to sign transactions

### 2. Blockchain Monitoring

**API Polling Mode:**
- Query multiple APIs concurrently (Blockchair, Blockchain.com, BlockCypher for BTC)
- Query multiple APIs concurrently (Etherscan, Infura, Alchemy for ETH)
- Use first successful response
- Check all user addresses every 60 seconds
- Detect new transactions and track confirmations

**Webhook Mode:**
- Register webhooks with BlockCypher (Bitcoin)
- Register webhooks with Alchemy (Ethereum)
- Receive real-time notifications on new transactions
- Verify webhook signatures for security
- Process immediately without polling delay

**Transaction Processing:**
1. Detect incoming transaction to user address
2. Record in `crypto_transactions` with status='pending'
3. Track confirmations (3 for BTC, 12 for ETH, configurable)
4. When confirmed, convert to fiat using multi-exchange pricing
5. Credit user's `user_crypto_wallets` balance
6. Check if pending subscription renewal can now proceed

### 3. Multi-Exchange Pricing

**Configurable Price Sources:**
- Admin adds/removes exchanges via `crypto_price_sources` table
- Each source has: name, API type, endpoint URL, API key, priority
- Default sources: Coinbase, Binance, Kraken

**Price Fetching:**
- Query all enabled sources concurrently
- Use average of successful responses
- Cache prices for 60 seconds
- Fallback if some APIs fail

**Supported APIs:**
- Coinbase: Public API, no auth
- Binance: Public API, no auth
- Kraken: Public API, no auth
- CoinGecko: Free tier, 10-50 calls/min
- CoinMarketCap: Free tier, 333 calls/day (requires API key)

### 4. Fiat Payment Handlers

**Stripe Integration:**
- Create/retrieve Stripe customer for user
- Attach payment method using token from Stripe.js
- Authorization hold for $1.00 verification (capture_method='manual')
- Immediately cancel authorization (releases hold)
- Store payment method ID in database
- Charge using PaymentIntent with off_session=True for renewals

**PayPal Integration:**
- Create billing agreement token
- Redirect user to PayPal for approval
- Execute billing agreement after approval
- Verification: Create $1.00 authorization, then void it
- Store billing agreement ID in database
- Charge using Orders API with billing_agreement_id for renewals

**Webhook Handling:**
- Verify signatures (Stripe: HMAC, PayPal: API verification)
- Update transaction status on success/failure
- Trigger retry logic on failure

### 5. Subscription Management

**Creation:**
1. Validate tier and payment method
2. Calculate amount (monthly or yearly)
3. Charge initial payment
4. Create subscription record with period dates
5. Update user tier
6. Send welcome email

**Upgrade (Prorated):**
1. Calculate unused portion of current period
2. New charge = new_price - (old_price × unused_fraction)
3. Charge prorated amount
4. Update subscription tier immediately
5. Keep same period end date
6. Send upgrade email

**Downgrade (No Refund):**
1. Schedule downgrade for period end
2. Set `pending_tier_id` in subscription
3. No immediate charge or refund
4. Applied automatically at renewal
5. Send notification email

**Cancellation (No Refund):**
1. Set `cancel_at_period_end = TRUE`
2. User retains access until period end
3. No refund issued
4. Send cancellation email

### 6. Renewal Processing

**Renewal Flow:**
1. Check subscriptions where `current_period_end <= NOW`
2. Calculate renewal amount
3. Attempt payment:
   - Fiat: Charge via Stripe/PayPal
   - Crypto: Check wallet balance, deduct if sufficient
4. On success: Extend period by 30/365 days
5. On failure: Add to retry queue

**Smart Retry Logic (Option C):**
- **Crypto payments:** Check wallet balance before each retry
  - If topped up: Retry immediately (no wait)
  - If still insufficient: Skip retry, wait for next scheduled check
- **Fiat payments:** Retry daily (fixed schedule)
- Max 3 attempts over 3 days
- After 3 failures: Downgrade to free tier

**Retry Queue Processing:**
1. Get pending retries where `next_retry_at <= NOW`
2. For crypto: Check if wallet balance now sufficient
3. Attempt payment
4. On success: Mark complete, extend subscription
5. On failure: Increment attempt, schedule next retry
6. After max attempts: Downgrade to free tier

### 7. Quota Enforcement

**Runtime Filtering (Creation Order - Option A):**
- Never delete user configurations
- Query configs ordered by `created_at ASC`
- Apply `LIMIT` based on tier quota
- Filter models within rotations/autoselections
- Configs beyond quota are preserved but ignored

**Request Quota Checking:**
- Count requests in last 24 hours (daily quota)
- Count requests in last 30 days (monthly quota)
- Return 429 error if quota exceeded
- Record each API request in `api_requests` table

**Quota Status API:**
- Show used vs. limit for each quota type
- Indicate which configs are active vs. ignored
- Display in user dashboard

### 8. Crypto Consolidation

**Threshold Monitoring:**
- Admin configures threshold per crypto type (e.g., 0.1 BTC)
- Every hour, sum all user wallet balances
- If total >= threshold: Add to consolidation queue

**Consolidation Process:**
1. Get all user addresses with balance > 0
2. For Bitcoin:
   - Collect UTXOs from all addresses
   - Create transaction with inputs from all addresses
   - Single output to admin address (minus fees)
   - Sign with derived private keys
   - Broadcast transaction
3. For Ethereum/ERC20:
   - For each address with balance:
     - Create transfer transaction to admin address
     - Sign with derived private key
     - Broadcast transaction
   - Note: Requires ETH for gas (may need gas wallet)
4. Record transaction hash
5. Reset user wallet balances to 0

**Security:**
- Private keys derived on-demand, never stored
- Consolidation runs in locked background task
- Transaction broadcast uses multiple APIs for reliability

### 9. Email Notifications

**Admin-Configurable Types (Option D):**
- payment_failed
- payment_retry_success
- subscription_created
- subscription_renewed
- subscription_upgraded
- subscription_downgrade_scheduled
- subscription_canceled
- subscription_downgraded
- crypto_wallet_credited

**Queue Processing:**
1. Check if notification type is enabled
2. Create email from template
3. Send via SMTP
4. On failure: Retry with exponential backoff (5min, 15min, 30min)
5. Max 3 attempts

**Email Templates:**
- Default HTML template with AISBF branding
- Admin can customize per notification type
- Variables: {{username}}, {{body}}, etc.

## API Endpoints

### Payment Methods
- `GET /api/payment-methods` - List user's payment methods
- `POST /api/payment-methods/stripe` - Add Stripe payment method
- `POST /api/payment-methods/paypal/initiate` - Start PayPal flow
- `POST /api/payment-methods/paypal/complete` - Complete PayPal flow
- `POST /api/payment-methods/crypto` - Add crypto payment method
- `DELETE /api/payment-methods/{id}` - Delete payment method

### Crypto Wallets
- `GET /api/crypto/addresses` - Get user's crypto addresses
- `GET /api/crypto/wallets` - Get wallet balances

### Subscriptions
- `POST /api/subscriptions` - Create subscription
- `POST /api/subscriptions/upgrade` - Upgrade tier
- `POST /api/subscriptions/downgrade` - Downgrade tier
- `POST /api/subscriptions/cancel` - Cancel subscription
- `GET /api/subscriptions/status` - Get subscription status
- `GET /api/subscriptions/history` - Get payment history

### Quotas
- `GET /api/quota/status` - Get quota usage status

### Webhooks
- `POST /api/webhooks/stripe` - Stripe webhook handler
- `POST /api/webhooks/paypal` - PayPal webhook handler
- `POST /api/webhooks/crypto/blockcypher` - BlockCypher webhook
- `POST /api/webhooks/crypto/alchemy` - Alchemy webhook

## Security Considerations

**Encryption:**
- Master seeds encrypted with Fernet (AES-128)
- Encryption key stored in environment variable
- Support for key rotation via `encryption_key_id`

**Payment Data:**
- No credit card data stored locally
- Stripe/PayPal handle PCI compliance
- Only store payment method IDs/tokens

**API Keys:**
- All gateway credentials stored in database
- Encrypted at rest
- Admin-only access

**Webhooks:**
- Signature verification for all webhooks
- Reject unsigned/invalid webhooks
- Rate limiting on webhook endpoints

**Private Keys:**
- Never stored in database
- Derived on-demand from encrypted seed
- Used only for signing, then discarded

## Scalability

**Horizontal Scaling:**
- Multiple instances can run concurrently
- Distributed locking prevents duplicate processing
- Database-backed state (no in-memory state)
- Each instance has unique ID (hostname-pid)

**Database:**
- Connection pooling for concurrent access
- Indexes on frequently queried columns
- Automatic cleanup of old records

**Background Tasks:**
- Each task acquires lock before running
- Lock expires after TTL (prevents deadlocks)
- Failed locks are automatically released

**Performance:**
- Async operations prevent blocking
- Concurrent API calls (gather multiple exchanges)
- Caching (price data, 60s TTL)
- Batch processing (email queue, consolidation)

## Error Handling

**Payment Failures:**
- Record failure reason in database
- Add to retry queue
- Send notification email
- After max retries: Downgrade to free tier

**API Failures:**
- Try multiple APIs concurrently
- Use first successful response
- Log failures for monitoring
- Fallback to cached data when available

**Blockchain Issues:**
- Retry transaction broadcast
- Monitor confirmation status
- Handle reorgs (check confirmations)

**Email Failures:**
- Exponential backoff retry
- Max 3 attempts
- Mark as failed after max attempts
- Admin can view failed emails

## Monitoring & Logging

**Metrics to Track:**
- Payment success/failure rates
- Retry queue length
- Consolidation frequency
- Email delivery rates
- API response times
- Quota usage per user

**Logging:**
- All payment attempts
- All API calls (with timing)
- Background task execution
- Lock acquisition/release
- Error details with stack traces

**Alerts:**
- Payment gateway downtime
- High failure rates
- Consolidation failures
- Email delivery issues
- Lock contention

## Testing Strategy

**Unit Tests:**
- Crypto wallet derivation
- Price averaging logic
- Proration calculations
- Quota filtering
- Email template rendering

**Integration Tests:**
- Stripe/PayPal sandbox testing
- Blockchain testnet transactions
- Webhook signature verification
- Database operations
- Background task execution

**End-to-End Tests:**
- Complete subscription flow
- Upgrade/downgrade scenarios
- Payment failure and retry
- Crypto payment flow
- Consolidation process

## Migration Plan

**Phase 1: Database Setup**
1. Create all new tables
2. Add encryption key to environment
3. Initialize crypto master keys
4. Configure payment gateways

**Phase 2: Payment Methods**
1. Deploy payment method endpoints
2. Test Stripe integration
3. Test PayPal integration
4. Test crypto address generation

**Phase 3: Subscriptions**
1. Deploy subscription endpoints
2. Test subscription creation
3. Test upgrades/downgrades
4. Test cancellation

**Phase 4: Background Tasks**
1. Deploy background scheduler
2. Test crypto monitoring
3. Test renewal processing
4. Test email notifications

**Phase 5: Production**
1. Enable for beta users
2. Monitor metrics
3. Gradual rollout
4. Full production launch

## Dependencies

**Python Packages:**
```
stripe>=5.0.0
httpx>=0.24.0
cryptography>=41.0.0
bip32>=3.4
mnemonic>=0.20
bitcoinlib>=0.6.14
web3>=6.0.0
eth-account>=0.9.0
```

**External Services:**
- Stripe account (production + test mode)
- PayPal business account (production + sandbox)
- Blockchain API keys (optional, free tiers available)
- SMTP server for email

**Infrastructure:**
- PostgreSQL or MySQL (recommended for production)
- Redis (optional, for caching)
- TOR (optional, for hidden service)

## Future Enhancements

**Phase 2 Features:**
- Additional crypto support (SOL, MATIC, etc.)
- Lightning Network for Bitcoin
- Subscription pausing
- Gift subscriptions
- Referral program
- Usage-based billing
- Invoice generation
- Tax reporting

**Admin Features:**
- Payment analytics dashboard
- Fraud detection
- Refund management
- Subscription management tools
- Bulk operations

## Conclusion

This design provides a complete, production-ready subscription payment system with:
- Full async/non-blocking architecture
- Horizontal scalability with distributed locking
- Support for fiat and crypto payments
- Intelligent retry logic
- Quota enforcement
- Admin configurability
- Comprehensive error handling
- Security best practices

The system is designed to handle high volume while maintaining data consistency across multiple instances.
