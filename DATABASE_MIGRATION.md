# AISBF Database Migration Guide

## Overview

AISBF uses two separate SQLite databases with distinct purposes:

1. **`aisbf.db`** - Configuration and persistent data
2. **`cache.db`** - Temporary caching only

## Database Separation

### aisbf.db (Configuration Database)

This database contains all configuration and persistent data:

**User Management:**
- `users` - User accounts and authentication
- `user_api_tokens` - API tokens for users
- `user_providers` - User-specific provider configurations
- `user_rotations` - User-specific rotation configurations
- `user_autoselects` - User-specific autoselect configurations
- `user_prompts` - User-specific prompt overrides
- `user_auth_files` - User authentication file metadata
- `user_oauth2_credentials` - OAuth2 credentials per user/provider

**Billing & Subscriptions:**
- `account_tiers` - Subscription tier definitions
- `payment_methods` - User payment methods
- `user_subscriptions` - Active subscriptions
- `payment_transactions` - Payment history

**Analytics & Tracking:**
- `context_dimensions` - Context usage tracking
- `token_usage` - Token usage for rate limiting
- `user_token_usage` - User-specific token usage
- `model_embeddings` - Cached model embeddings

### cache.db (Cache Database)

This database contains ONLY temporary caching data:

- `cache` - General purpose cache
- `response_cache` - AI response caching

## Migration Issue

In some installations, configuration tables (especially `users`) were incorrectly created in `cache.db` instead of `aisbf.db`. This causes issues because:

1. Configuration data should persist across cache clears
2. The application expects configuration in `aisbf.db`
3. Cache database should be safe to delete without losing data

## Migration Process

### Step 1: Check Current State

First, verify which database contains your data:

```bash
# Check tables in cache.db
sqlite3 ~/.aisbf/cache.db ".tables"

# Check tables in aisbf.db
sqlite3 ~/.aisbf/aisbf.db ".tables"
```

If you see configuration tables (like `users`, `user_providers`, etc.) in `cache.db`, you need to migrate.

### Step 2: Dry Run

Test the migration without making changes:

```bash
python migrate_cache_to_aisbf.py --dry-run
```

This will show you:
- Which tables will be migrated
- How many rows will be copied
- Any potential issues

### Step 3: Perform Migration

Run the actual migration:

```bash
python migrate_cache_to_aisbf.py
```

The script will:
1. Create backups of both databases
2. Copy configuration tables from `cache.db` to `aisbf.db`
3. Preserve all existing data
4. Show a summary of migrated data

**Backup files are created automatically:**
- `~/.aisbf/cache_backup_YYYYMMDD_HHMMSS.db`
- `~/.aisbf/aisbf_backup_YYYYMMDD_HHMMSS.db`

### Step 4: Verify Migration

After migration, verify the data:

```bash
# Check users table in aisbf.db
sqlite3 ~/.aisbf/aisbf.db "SELECT COUNT(*) FROM users;"

# Check your user exists
sqlite3 ~/.aisbf/aisbf.db "SELECT username, role FROM users;"
```

### Step 5: Test Application

Start AISBF and verify:
1. You can log in with your existing credentials
2. All providers and rotations are available
3. User-specific configurations are preserved

```bash
# Start AISBF
aisbf

# Or if running from source
python main.py
```

### Step 6: Cleanup (Optional)

After confirming everything works, clean up `cache.db`:

```bash
python migrate_cache_to_aisbf.py --cleanup
```

This removes configuration tables from `cache.db`, leaving only cache tables.

## Advanced Options

### Force Overwrite

If destination tables already have data and you want to overwrite:

```bash
python migrate_cache_to_aisbf.py --force
```

### Custom Database Paths

If your databases are in non-standard locations:

```bash
python migrate_cache_to_aisbf.py \
  --cache-db /path/to/cache.db \
  --aisbf-db /path/to/aisbf.db
```

## Troubleshooting

### Issue: "Table already has rows in destination"

**Solution:** Use `--force` to overwrite, or manually inspect both databases to determine which has the correct data.

### Issue: Migration fails with "database is locked"

**Solution:** Stop AISBF before running migration:

```bash
# Stop AISBF
aisbf stop

# Run migration
python migrate_cache_to_aisbf.py

# Start AISBF
aisbf
```

### Issue: Lost data after migration

**Solution:** Restore from backup:

```bash
# Find your backup
ls -lt ~/.aisbf/*_backup_*.db

# Restore cache.db
cp ~/.aisbf/cache_backup_YYYYMMDD_HHMMSS.db ~/.aisbf/cache.db

# Restore aisbf.db
cp ~/.aisbf/aisbf_backup_YYYYMMDD_HHMMSS.db ~/.aisbf/aisbf.db
```

## Prevention

The code has been updated to ensure proper database separation:

1. **`database.py`** - All methods use `aisbf.db` for configuration
2. **`cache.py`** - All methods use `cache.db` for caching only
3. **Initialization** - Databases are created with correct table separation

After upgrading to the fixed version, new installations will automatically use the correct database structure.

## For Developers

### Database Initialization

```python
from aisbf.database import initialize_database, get_database

# Initialize configuration database (aisbf.db)
initialize_database()

# Get database manager
db = get_database()

# All operations use aisbf.db
user = db.authenticate_user(username, password_hash)
```

### Cache Operations

```python
from aisbf.cache import get_cache_manager

# Initialize cache (cache.db)
cache = get_cache_manager()

# All operations use cache.db
cache.set('key', 'value', ttl=600)
value = cache.get('key')
```

### Adding New Tables

**Configuration tables** (add to `database.py`):
```python
cursor.execute('''
    CREATE TABLE IF NOT EXISTS my_config_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ...
    )
''')
```

**Cache tables** (add to `cache.py`):
```python
cursor.execute('''
    CREATE TABLE IF NOT EXISTS my_cache_table (
        key TEXT PRIMARY KEY,
        value TEXT,
        ttl REAL
    )
''')
```

## Summary

- **aisbf.db** = Configuration & persistent data (users, providers, etc.)
- **cache.db** = Temporary caching only (cache, response_cache)
- **Migration script** = Moves misplaced tables from cache.db to aisbf.db
- **Backups** = Created automatically before any changes
- **Safe** = Can be run multiple times, dry-run available

For questions or issues, refer to the main DOCUMENTATION.md or open an issue on GitHub.
