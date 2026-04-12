#!/usr/bin/env python3
"""
Database diagnostic script for AISBF

This script checks which database contains which tables and helps identify
database separation issues.

Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
"""

import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple


def get_tables(db_path: Path) -> List[str]:
    """Get list of tables in a database"""
    if not db_path.exists():
        return []
    
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error reading {db_path}: {e}")
        return []


def get_table_count(db_path: Path, table_name: str) -> int:
    """Get row count for a table"""
    if not db_path.exists():
        return 0
    
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cursor.fetchone()[0]
    except Exception as e:
        return 0


def main():
    print("=" * 70)
    print("AISBF Database Diagnostic Tool")
    print("=" * 70)
    print()
    
    # Database paths
    aisbf_dir = Path.home() / '.aisbf'
    cache_db = aisbf_dir / 'cache.db'
    aisbf_db = aisbf_dir / 'aisbf.db'
    response_cache_db = aisbf_dir / 'response_cache.db'
    
    print(f"Checking databases in: {aisbf_dir}")
    print()
    
    # Configuration tables (should be in aisbf.db)
    config_tables = [
        'users', 'user_providers', 'user_rotations', 'user_autoselects',
        'user_prompts', 'user_api_tokens', 'user_token_usage',
        'user_auth_files', 'user_oauth2_credentials',
        'account_tiers', 'payment_methods', 'user_subscriptions',
        'payment_transactions', 'context_dimensions', 'token_usage',
        'model_embeddings'
    ]
    
    # Cache tables (should be in cache.db)
    cache_tables = ['cache', 'response_cache']
    
    # Check cache.db
    print("📁 cache.db")
    print("-" * 70)
    if cache_db.exists():
        cache_db_tables = get_tables(cache_db)
        print(f"   Tables found: {len(cache_db_tables)}")
        
        # Check for misplaced configuration tables
        misplaced = [t for t in cache_db_tables if t in config_tables]
        if misplaced:
            print(f"   ⚠️  WARNING: Configuration tables found in cache.db:")
            for table in misplaced:
                count = get_table_count(cache_db, table)
                print(f"      - {table} ({count} rows)")
        
        # Check for correct cache tables
        correct = [t for t in cache_db_tables if t in cache_tables]
        if correct:
            print(f"   ✅ Cache tables (correct):")
            for table in correct:
                count = get_table_count(cache_db, table)
                print(f"      - {table} ({count} rows)")
        
        # Unknown tables
        unknown = [t for t in cache_db_tables if t not in config_tables and t not in cache_tables]
        if unknown:
            print(f"   ❓ Unknown tables:")
            for table in unknown:
                count = get_table_count(cache_db, table)
                print(f"      - {table} ({count} rows)")
    else:
        print("   ❌ Database does not exist")
    print()
    
    # Check aisbf.db
    print("📁 aisbf.db")
    print("-" * 70)
    if aisbf_db.exists():
        aisbf_db_tables = get_tables(aisbf_db)
        print(f"   Tables found: {len(aisbf_db_tables)}")
        
        # Check for correct configuration tables
        correct = [t for t in aisbf_db_tables if t in config_tables]
        if correct:
            print(f"   ✅ Configuration tables (correct):")
            for table in correct:
                count = get_table_count(aisbf_db, table)
                print(f"      - {table} ({count} rows)")
        
        # Check for misplaced cache tables
        misplaced = [t for t in aisbf_db_tables if t in cache_tables]
        if misplaced:
            print(f"   ⚠️  WARNING: Cache tables found in aisbf.db:")
            for table in misplaced:
                count = get_table_count(aisbf_db, table)
                print(f"      - {table} ({count} rows)")
        
        # Unknown tables
        unknown = [t for t in aisbf_db_tables if t not in config_tables and t not in cache_tables]
        if unknown:
            print(f"   ❓ Unknown tables:")
            for table in unknown:
                count = get_table_count(aisbf_db, table)
                print(f"      - {table} ({count} rows)")
    else:
        print("   ❌ Database does not exist")
    print()
    
    # Check response_cache.db
    print("📁 response_cache.db")
    print("-" * 70)
    if response_cache_db.exists():
        response_cache_db_tables = get_tables(response_cache_db)
        print(f"   Tables found: {len(response_cache_db_tables)}")
        for table in response_cache_db_tables:
            count = get_table_count(response_cache_db, table)
            print(f"      - {table} ({count} rows)")
    else:
        print("   ❌ Database does not exist")
    print()
    
    # Summary and recommendations
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    
    issues_found = False
    
    # Check for configuration tables in cache.db
    if cache_db.exists():
        cache_db_tables = get_tables(cache_db)
        misplaced_in_cache = [t for t in cache_db_tables if t in config_tables]
        if misplaced_in_cache:
            issues_found = True
            print("❌ ISSUE: Configuration tables found in cache.db")
            print(f"   Tables: {', '.join(misplaced_in_cache)}")
            print()
            print("   SOLUTION: Run the migration script:")
            print("   python migrate_cache_to_aisbf.py")
            print()
    
    # Check for cache tables in aisbf.db
    if aisbf_db.exists():
        aisbf_db_tables = get_tables(aisbf_db)
        misplaced_in_aisbf = [t for t in aisbf_db_tables if t in cache_tables]
        if misplaced_in_aisbf:
            issues_found = True
            print("⚠️  WARNING: Cache tables found in aisbf.db")
            print(f"   Tables: {', '.join(misplaced_in_aisbf)}")
            print("   This is unusual but not critical.")
            print()
    
    if not issues_found:
        print("✅ All tables are in the correct databases!")
        print()
        print("Database separation is correct:")
        print("  - aisbf.db contains configuration tables")
        print("  - cache.db contains cache tables only")
    
    print()
    print("=" * 70)
    
    return 0 if not issues_found else 1


if __name__ == '__main__':
    sys.exit(main())
