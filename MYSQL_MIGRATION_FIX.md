# MySQL Migration Issue - Payment Tables Not Created

## Issue

**Error**: `Table 'aisbf.crypto_master_keys' doesn't exist`

**Environment**: MySQL database (remote server)

**Root Cause**: Payment system migrations are NOT being run automatically on startup.

## Problem Analysis

### Current Code Flow

```python
# main.py lines 1160-1184
try:
    from aisbf.payments.service import PaymentService
    db_manager = DatabaseRegistry.get_config_database()
    payment_service = PaymentService(db_manager, payment_config)
    await payment_service.initialize()
except Exception as e:
    logger.error(f"Failed to initialize payment service: {e}")
```

**Issue**: The migrations are NEVER called!

The `PaymentService.__init__()` tries to initialize wallet managers and other services that require the tables to exist, but the tables haven't been created yet.

### Expected Flow

```python
1. Run migrations (create tables)
2. Initialize PaymentService (use tables)
```

### Actual Flow

```python
1. Initialize PaymentService (tries to use tables)
2. Tables don't exist → ERROR
3. Migrations never run
```

## Solution

Add migration execution BEFORE initializing PaymentService.

### Fix for main.py

**Location**: Line 1177 (before PaymentService initialization)

**Add**:
```python
# Run payment system migrations
from aisbf.payments.migrations import PaymentMigrations
migrations = PaymentMigrations(db_manager)
migrations.run_migrations()
logger.info("Payment system migrations completed")
```

**Complete Fixed Code**:
```python
# Initialize payment service
global payment_service
try:
    # Generate or load encryption key
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if not encryption_key:
        encryption_key = Fernet.generate_key().decode()
        logger.warning("No ENCRYPTION_KEY set, generated temporary key")
    
    payment_config = {
        'encryption_key': encryption_key,
        'base_url': os.getenv('BASE_URL', 'http://localhost:17765'),
        'currency_code': 'USD',
        'btc_confirmations': 3,
        'eth_confirmations': 12
    }
    
    from aisbf.payments.service import PaymentService
    from aisbf.payments.migrations import PaymentMigrations  # ADD THIS
    
    db_manager = DatabaseRegistry.get_config_database()
    
    # Run migrations BEFORE initializing service  # ADD THIS
    migrations = PaymentMigrations(db_manager)     # ADD THIS
    migrations.run_migrations()                     # ADD THIS
    logger.info("Payment system migrations completed")  # ADD THIS
    
    payment_service = PaymentService(db_manager, payment_config)
    await payment_service.initialize()
    
    logger.info("Payment service started")
except Exception as e:
    logger.error(f"Failed to initialize payment service: {e}")
    # Continue startup even if payment service fails
```

## Why This Happened

The payment system was developed with the assumption that migrations would be run manually or automatically, but the automatic migration call was never added to the startup sequence.

In development with SQLite, the tables might have been created manually or through testing, so the issue wasn't caught.

## MySQL-Specific Considerations

### AUTO_INCREMENT vs AUTOINCREMENT

The migrations code correctly handles this:

```python
if self.db_type == 'sqlite':
    auto_increment = 'AUTOINCREMENT'
else:  # mysql
    auto_increment = 'AUTO_INCREMENT'
```

### INTEGER vs INT

MySQL uses `INT` not `INTEGER` for primary keys, but MySQL accepts `INTEGER` as an alias, so this should work.

However, for better MySQL compatibility, consider:

```python
if self.db_type == 'sqlite':
    int_type = 'INTEGER'
else:  # mysql
    int_type = 'INT'
```

## Verification Steps

After applying the fix:

1. **Check migrations run**:
   ```bash
   # Look for this in logs:
   # "Starting payment system migrations..."
   # "✅ Payment system migrations completed successfully"
   ```

2. **Verify tables exist**:
   ```sql
   USE aisbf;
   SHOW TABLES LIKE 'crypto_%';
   SHOW TABLES LIKE 'payment_%';
   SHOW TABLES LIKE 'subscription_%';
   ```

3. **Check table structure**:
   ```sql
   DESCRIBE crypto_master_keys;
   DESCRIBE user_crypto_addresses;
   DESCRIBE payments;
   DESCRIBE subscriptions;
   ```

4. **Test payment service**:
   ```bash
   # Service should start without errors
   # Check logs for "Payment service started"
   ```

## Tables That Should Be Created

The migrations create these tables:

**Crypto Tables**:
- `crypto_master_keys`
- `user_crypto_addresses`
- `user_crypto_wallets`
- `crypto_transactions`
- `crypto_prices`
- `crypto_price_sources`
- `crypto_consolidation_settings`
- `blockchain_monitoring_config`

**Payment Tables**:
- `payments`
- `payment_methods`

**Subscription Tables**:
- `subscriptions`
- `subscription_usage_tracking`

**Job Tables**:
- `job_locks`
- `job_queue`

**Config Tables**:
- `email_config`
- `email_notification_settings`

**Total**: 16 new tables

## Prevention

To prevent this in the future:

1. **Add migration check to startup**:
   ```python
   # Always run migrations on startup
   # They use CREATE TABLE IF NOT EXISTS, so safe to run multiple times
   ```

2. **Add migration status endpoint**:
   ```python
   @app.get("/api/admin/migrations/status")
   async def migration_status():
       # Check which tables exist
       # Return migration status
   ```

3. **Add to deployment checklist**:
   - Verify migrations run on first startup
   - Check all tables exist
   - Verify payment service initializes

## Deployment Steps

1. **Pull latest code** (with fix):
   ```bash
   git pull origin feature/subscription-payment-system
   ```

2. **Rebuild package**:
   ```bash
   ./build.sh
   ```

3. **Reinstall**:
   ```bash
   pip install dist/aisbf-0.99.27-*.whl --force-reinstall
   ```

4. **Restart service**:
   ```bash
   systemctl restart aisbf
   ```

5. **Check logs**:
   ```bash
   tail -f /var/log/aisbf/aisbf.log | grep -i migration
   tail -f /var/log/aisbf/aisbf.log | grep -i payment
   ```

6. **Verify tables**:
   ```bash
   mysql -u aisbf -p aisbf -e "SHOW TABLES LIKE 'crypto_%';"
   ```

## Status

- ❌ **Current**: Migrations not called, tables don't exist
- ⏳ **Fix**: Add migration call to main.py
- ✅ **After Fix**: Migrations run automatically, tables created

## Related Files

- `main.py` line 1177 - Where fix needs to be applied
- `aisbf/payments/migrations.py` - Migration code (already correct)
- `aisbf/payments/service.py` - Payment service (requires tables)

## Commit

This fix will be committed as:
```
fix: run payment system migrations on startup

- Migrations were never called automatically
- PaymentService tried to use tables that didn't exist
- Added migration execution before PaymentService initialization
- Fixes MySQL "Table doesn't exist" error
```
