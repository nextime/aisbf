# Database Migration Fixes for v0.99.29

## Issues Fixed

### Issue 1: Lost Account Tiers After Server Restart

**Problem**: Custom account tiers disappeared after restarting the server, leaving only the default "Free Tier".

**Root Cause**: 
- On April 14 (commit `f997a0f`), the `account_tiers` table creation was removed from `database.py` migrations
- On April 16 (commit `0052431`), payment migrations were added but didn't include `account_tiers` table creation
- The payment migrations referenced `account_tiers` (via foreign keys) but never created it
- Result: When migrations ran, the table structure existed but custom tiers were lost

**Fix Applied**:
- Added `_create_account_tiers_table()` method to `aisbf/payments/migrations.py`
- Creates the table with all necessary columns including `is_visible`
- Ensures default "Free Tier" is inserted if no default tier exists
- Uses `CREATE TABLE IF NOT EXISTS` to preserve existing data

### Issue 2: Lost Payment Gateway Configurations (MySQL)

**Problem**: After upgrading to v0.99.29 on MySQL, payment gateway configurations (Stripe, PayPal, crypto) were lost.

**Root Cause**:
- Payment gateway settings are stored in the `admin_settings` table
- The `admin_settings` table was only created in `database.py` migrations (line 3335-3342)
- It was NOT included in `aisbf/payments/migrations.py`
- On MySQL installations using payment migrations, the `admin_settings` table was never created
- Result: Payment gateway settings had nowhere to be stored and were lost

**Fix Applied**:
- Added `admin_settings` table creation to `_create_config_tables()` in `aisbf/payments/migrations.py`
- Table stores payment gateway configs, encryption keys, and other admin settings
- Uses `CREATE TABLE IF NOT EXISTS` to preserve existing data

## Changes Made

### File: `aisbf/payments/migrations.py`

1. **Added `_create_account_tiers_table()` method** (lines 68-92):
   - Creates `account_tiers` table with all columns
   - Includes `is_visible` column for tier visibility control
   - Called first in migration sequence to ensure it exists before other tables

2. **Added `admin_settings` table creation** (lines 318-325):
   - Added to `_create_config_tables()` method
   - Stores payment gateway configurations as JSON
   - Stores encryption keys and other admin settings

3. **Added default tier insertion** (lines 527-557):
   - Ensures "Free Tier" exists if no default tier is present
   - Prevents empty tier list after fresh installation

## Migration Safety

Both fixes use `CREATE TABLE IF NOT EXISTS`, which means:
- ✅ Existing tables are preserved
- ✅ Existing data is NOT deleted
- ✅ Safe to run on existing installations
- ✅ Safe to run multiple times

## What Users Need to Do

### For Lost Tiers (SQLite and MySQL):
1. Restart your server - the migrations will run automatically
2. The table structure will be verified/created
3. **You will need to recreate your custom tiers** through the admin dashboard
4. Future restarts will preserve your tiers

### For Lost Payment Gateway Configs (MySQL only):
1. Restart your server - the migrations will run automatically
2. The `admin_settings` table will be created
3. **You will need to reconfigure your payment gateways** through the admin dashboard:
   - Go to Admin → Payment Settings
   - Configure Stripe, PayPal, and crypto gateways
   - Save the configuration
4. Future restarts will preserve your settings

## Prevention

These fixes ensure that:
- All required tables are created by payment migrations
- Data is preserved across server restarts
- Both SQLite and MySQL installations work correctly
- Payment system tables are self-contained in payment migrations

## Testing

To verify the fix works:

```bash
# Test migrations
cd /working/aisbf
python3 -c "
from aisbf.database import DatabaseRegistry
from aisbf.payments.migrations import PaymentMigrations

db = DatabaseRegistry.get_config_database()
migrations = PaymentMigrations(db)
migrations.run_migrations()
print('✅ Migrations completed successfully')
"
```

## Version

These fixes are included in v0.99.29 and will be part of the next release.

## Related Commits

- `ceafa18` - Initial tier system implementation (April 12)
- `f997a0f` - Removed tier migrations from database.py (April 14)
- `0052431` - Added payment migrations without tiers (April 16)
- `7ea471c` - Moved payment gateway settings to payment settings page (April 16)
- Current - Fixed both issues in payment migrations
