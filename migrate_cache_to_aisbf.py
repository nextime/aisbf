#!/usr/bin/env python3
"""
Migration script to move configuration data from cache.db to aisbf.db

This script handles the case where configuration tables (users, providers, etc.)
were incorrectly created in cache.db instead of aisbf.db.

Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import sqlite3
import sys
from pathlib import Path
import shutil
from datetime import datetime

# Configuration tables that should be in aisbf.db
CONFIG_TABLES = [
    'users',
    'user_providers',
    'user_rotations',
    'user_autoselects',
    'user_prompts',
    'user_api_tokens',
    'user_token_usage',
    'user_auth_files',
    'user_oauth2_credentials',
    'account_tiers',
    'payment_methods',
    'user_subscriptions',
    'payment_transactions',
    'context_dimensions',
    'token_usage',
    'model_embeddings'
]

# Cache tables that should stay in cache.db
CACHE_TABLES = [
    'cache',
    'response_cache'
]


def backup_database(db_path: Path) -> Path:
    """Create a backup of the database"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = db_path.parent / f"{db_path.stem}_backup_{timestamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ Created backup: {backup_path}")
    return backup_path


def get_table_list(conn: sqlite3.Connection) -> list:
    """Get list of tables in database"""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [row[0] for row in cursor.fetchall()]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if table exists in database"""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def get_table_schema(conn: sqlite3.Connection, table_name: str) -> str:
    """Get CREATE TABLE statement for a table"""
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    result = cursor.fetchone()
    return result[0] if result else None


def copy_table_data(source_conn: sqlite3.Connection, dest_conn: sqlite3.Connection, 
                    table_name: str, force: bool = False) -> tuple:
    """
    Copy table data from source to destination database
    
    Returns:
        (success: bool, rows_copied: int, message: str)
    """
    try:
        # Check if table exists in source
        if not table_exists(source_conn, table_name):
            return (True, 0, f"Table '{table_name}' not found in source database (skipping)")
        
        # Get row count from source
        source_cursor = source_conn.cursor()
        source_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        source_count = source_cursor.fetchone()[0]
        
        if source_count == 0:
            return (True, 0, f"Table '{table_name}' is empty in source database (skipping)")
        
        # Check if table exists in destination
        dest_exists = table_exists(dest_conn, table_name)
        
        if dest_exists:
            # Get row count from destination
            dest_cursor = dest_conn.cursor()
            dest_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            dest_count = dest_cursor.fetchone()[0]
            
            if dest_count > 0 and not force:
                return (False, 0, f"Table '{table_name}' already has {dest_count} rows in destination. Use --force to overwrite.")
        
        # Get table schema from source
        schema = get_table_schema(source_conn, table_name)
        if not schema:
            return (False, 0, f"Could not get schema for table '{table_name}'")
        
        # Create table in destination if it doesn't exist
        if not dest_exists:
            dest_cursor = dest_conn.cursor()
            dest_cursor.execute(schema)
            dest_conn.commit()
            print(f"  Created table '{table_name}' in destination")
        
        # Get all data from source
        source_cursor.execute(f"SELECT * FROM {table_name}")
        rows = source_cursor.fetchall()
        
        # Get column names
        column_names = [description[0] for description in source_cursor.description]
        placeholders = ','.join(['?' for _ in column_names])
        columns_str = ','.join(column_names)
        
        # Insert data into destination
        dest_cursor = dest_conn.cursor()
        
        if force and dest_exists:
            # Clear existing data if force mode
            dest_cursor.execute(f"DELETE FROM {table_name}")
            print(f"  Cleared existing data from '{table_name}'")
        
        dest_cursor.executemany(
            f"INSERT OR REPLACE INTO {table_name} ({columns_str}) VALUES ({placeholders})",
            rows
        )
        dest_conn.commit()
        
        return (True, len(rows), f"Copied {len(rows)} rows")
        
    except Exception as e:
        return (False, 0, f"Error: {str(e)}")


def migrate_databases(cache_db_path: Path, aisbf_db_path: Path, force: bool = False, dry_run: bool = False):
    """
    Migrate configuration tables from cache.db to aisbf.db
    
    Args:
        cache_db_path: Path to cache.db
        aisbf_db_path: Path to aisbf.db
        force: Overwrite existing data in destination
        dry_run: Don't actually perform migration, just show what would be done
    """
    print("=" * 70)
    print("AISBF Database Migration Tool")
    print("=" * 70)
    print()
    
    # Check if databases exist
    if not cache_db_path.exists():
        print(f"❌ Error: cache.db not found at {cache_db_path}")
        return False
    
    if not aisbf_db_path.exists():
        print(f"⚠️  Warning: aisbf.db not found at {aisbf_db_path}")
        print("   It will be created during migration.")
    
    print(f"Source (cache.db): {cache_db_path}")
    print(f"Destination (aisbf.db): {aisbf_db_path}")
    print()
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print()
    
    # Create backups
    if not dry_run:
        print("Creating backups...")
        backup_cache = backup_database(cache_db_path)
        if aisbf_db_path.exists():
            backup_aisbf = backup_database(aisbf_db_path)
        print()
    
    # Connect to databases
    cache_conn = sqlite3.connect(str(cache_db_path))
    aisbf_conn = sqlite3.connect(str(aisbf_db_path))
    
    try:
        # Get list of tables in cache.db
        cache_tables = get_table_list(cache_conn)
        print(f"Tables found in cache.db: {', '.join(cache_tables)}")
        print()
        
        # Find configuration tables that need to be migrated
        tables_to_migrate = [t for t in cache_tables if t in CONFIG_TABLES]
        
        if not tables_to_migrate:
            print("✅ No configuration tables found in cache.db that need migration.")
            print("   All tables are correctly separated.")
            return True
        
        print(f"Configuration tables to migrate: {', '.join(tables_to_migrate)}")
        print()
        
        # Migrate each table
        total_rows = 0
        success_count = 0
        
        for table_name in tables_to_migrate:
            print(f"Migrating table: {table_name}")
            
            if dry_run:
                # Just check what would be done
                source_cursor = cache_conn.cursor()
                source_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = source_cursor.fetchone()[0]
                print(f"  Would copy {count} rows")
                success_count += 1
                total_rows += count
            else:
                # Actually perform migration
                success, rows, message = copy_table_data(cache_conn, aisbf_conn, table_name, force)
                print(f"  {message}")
                
                if success:
                    success_count += 1
                    total_rows += rows
                else:
                    print(f"  ❌ Failed to migrate {table_name}")
            
            print()
        
        # Summary
        print("=" * 70)
        print("Migration Summary")
        print("=" * 70)
        print(f"Tables processed: {len(tables_to_migrate)}")
        print(f"Successfully migrated: {success_count}")
        print(f"Total rows migrated: {total_rows}")
        
        if dry_run:
            print()
            print("This was a dry run. No changes were made.")
            print("Run without --dry-run to perform the actual migration.")
        else:
            print()
            print("✅ Migration completed successfully!")
            print()
            print("Next steps:")
            print("1. Verify the migrated data in aisbf.db")
            print("2. Test the application to ensure everything works")
            print("3. If everything is OK, you can optionally clean up cache.db:")
            print(f"   python {sys.argv[0]} --cleanup")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        cache_conn.close()
        aisbf_conn.close()


def cleanup_cache_db(cache_db_path: Path):
    """Remove configuration tables from cache.db after successful migration"""
    print("=" * 70)
    print("Cleanup cache.db")
    print("=" * 70)
    print()
    
    if not cache_db_path.exists():
        print(f"❌ Error: cache.db not found at {cache_db_path}")
        return False
    
    # Create backup first
    print("Creating backup...")
    backup_cache = backup_database(cache_db_path)
    print()
    
    conn = sqlite3.connect(str(cache_db_path))
    cursor = conn.cursor()
    
    try:
        # Get list of tables
        tables = get_table_list(conn)
        
        # Find configuration tables to remove
        tables_to_remove = [t for t in tables if t in CONFIG_TABLES]
        
        if not tables_to_remove:
            print("✅ No configuration tables found in cache.db")
            return True
        
        print(f"Configuration tables to remove: {', '.join(tables_to_remove)}")
        print()
        
        # Remove each table
        for table_name in tables_to_remove:
            print(f"Dropping table: {table_name}")
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        
        conn.commit()
        
        # Vacuum to reclaim space
        print()
        print("Vacuuming database to reclaim space...")
        cursor.execute("VACUUM")
        
        print()
        print("✅ Cleanup completed successfully!")
        print(f"   Backup saved at: {backup_cache}")
        
        return True
        
    except Exception as e:
        print(f"❌ Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        conn.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Migrate configuration data from cache.db to aisbf.db',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be migrated
  python migrate_cache_to_aisbf.py --dry-run
  
  # Perform the migration
  python migrate_cache_to_aisbf.py
  
  # Force overwrite existing data
  python migrate_cache_to_aisbf.py --force
  
  # Clean up cache.db after successful migration
  python migrate_cache_to_aisbf.py --cleanup
  
  # Use custom database paths
  python migrate_cache_to_aisbf.py --cache-db /path/to/cache.db --aisbf-db /path/to/aisbf.db
        """
    )
    
    parser.add_argument('--cache-db', type=str, default='~/.aisbf/cache.db',
                        help='Path to cache.db (default: ~/.aisbf/cache.db)')
    parser.add_argument('--aisbf-db', type=str, default='~/.aisbf/aisbf.db',
                        help='Path to aisbf.db (default: ~/.aisbf/aisbf.db)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing data in destination database')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('--cleanup', action='store_true',
                        help='Remove configuration tables from cache.db after migration')
    
    args = parser.parse_args()
    
    # Expand paths
    cache_db_path = Path(args.cache_db).expanduser()
    aisbf_db_path = Path(args.aisbf_db).expanduser()
    
    if args.cleanup:
        success = cleanup_cache_db(cache_db_path)
    else:
        success = migrate_databases(cache_db_path, aisbf_db_path, args.force, args.dry_run)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
