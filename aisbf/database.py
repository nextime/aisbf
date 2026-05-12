
"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Why did the programmer quit his job? Because he didn't get arrays!

Database module for persistent tracking of context dimensions and rate limiting.
"""
import sqlite3
import json
import hashlib
import time
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP

try:
    import bcrypt as _bcrypt_lib
    _BCRYPT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _BCRYPT_AVAILABLE = False

def _hash_password(password: str) -> str:
    """Hash a password. Uses bcrypt when available, falls back to SHA-256."""
    if _BCRYPT_AVAILABLE:
        return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()
    return hashlib.sha256(password.encode()).hexdigest()

def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash (bcrypt or legacy SHA-256)."""
    if stored_hash.startswith("$2") and _BCRYPT_AVAILABLE:
        return _bcrypt_lib.checkpw(password.encode(), stored_hash.encode())
    # Legacy SHA-256 path
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

try:
    import mysql.connector as _mysql_connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    _mysql_connector = None

logger = logging.getLogger(__name__)

# Global thread pool executor for database operations
_db_executor = None

def get_db_executor():
    """Get or create the global database thread pool executor."""
    global _db_executor
    if _db_executor is None:
        _db_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="db_worker")
    return _db_executor


class _MySQLConnectionWrapper:
    """Wrapper that gives mysql.connector connections a reliable context manager protocol.

    mysql-connector-python's C extension (__enter__/__exit__) has version-dependent
    behaviour (some versions return a cursor from __enter__, others close the connection
    in __exit__ unexpectedly).  This wrapper always yields the raw connection and
    handles commit/rollback/close explicitly.
    """

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._conn.commit()
        else:
            try:
                self._conn.rollback()
            except Exception:
                pass
        # Connection is intentionally left open: cursor and conn variables in the
        # calling function remain valid after the with-block exits (matching SQLite's
        # context-manager behaviour).  The connection is closed by GC when the caller
        # function returns and conn goes out of scope.
        return False

    # Forward attribute access so the wrapper can be used directly as well
    def __getattr__(self, name):
        return getattr(self._conn, name)


class DatabaseManager:
    """
    Manages database for persistent tracking of context dimensions and rate limiting.

    Supports both SQLite and MySQL databases.
    All database operations are non-blocking using asyncio and thread pool executors.
    """

    def __init__(self, db_config: Optional[Dict[str, Any]] = None):
        """
        Initialize the database manager.

        Args:
            db_config: Database configuration dictionary. If None, uses default SQLite config.
        """
        if db_config is None:
            # Default SQLite configuration
            aisbf_dir = Path.home() / '.aisbf'
            aisbf_dir.mkdir(exist_ok=True)
            self.db_config = {
                'type': 'sqlite',
                'sqlite_path': str(aisbf_dir / 'aisbf.db'),
                'mysql_host': 'localhost',
                'mysql_port': 3306,
                'mysql_user': 'aisbf',
                'mysql_password': '',
                'mysql_database': 'aisbf'
            }
        else:
            self.db_config = db_config

        self.db_type = self.db_config.get('type', 'sqlite').lower()
        self.executor = get_db_executor()
        
        if self.db_type == 'mysql':
            if not MYSQL_AVAILABLE:
                raise ImportError("MySQL connector not available. Install mysql-connector-python.")

        self._initialize_database()
        logger.info(f"Database initialized: {self.db_type}")

    def _get_connection(self):
        """Get a database connection based on the configured type."""
        if self.db_type == 'sqlite':
            db_path = Path(self.db_config['sqlite_path']).expanduser()
            return sqlite3.connect(str(db_path))
        elif self.db_type == 'mysql':
            try:
                conn = _mysql_connector.connect(
                    host=self.db_config['mysql_host'],
                    port=self.db_config['mysql_port'],
                    user=self.db_config['mysql_user'],
                    password=self.db_config['mysql_password'],
                    database=self.db_config['mysql_database'],
                )
                return _MySQLConnectionWrapper(conn)
            except Exception as e:
                logger.error(f"MySQL connection failed: {e}")
                raise
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")
    
    @property
    def placeholder(self) -> str:
        return '?' if self.db_type == 'sqlite' else '%s'

    @staticmethod
    def _quantize_money(value: Any) -> Decimal:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def _market_cache_key(consumer_user_id: int, listing_id: int, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(metadata, dict):
            return None
        request_id = metadata.get('market_request_id') or metadata.get('request_id')
        if not request_id:
            return None
        return f"market:settlement:{consumer_user_id}:{listing_id}:{request_id}"

    @staticmethod
    def _extract_market_settlement_key(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(metadata, dict):
            return None
        key = metadata.get('market_settlement_key')
        return str(key).strip() if key not in (None, '') else None

    @staticmethod
    def _sanitize_market_config(config: Dict[str, Any]) -> Dict[str, Any]:
        secret_keys = {
            'api_key', 'password', 'secret', 'token', 'access_token', 'refresh_token',
            'client_secret', 'authorization', 'credentials', 'session_token'
        }

        def _sanitize(value):
            if isinstance(value, dict):
                sanitized = {}
                for key, item in value.items():
                    lowered = str(key).lower()
                    if lowered in secret_keys or lowered.endswith('_token') or lowered.endswith('_secret'):
                        continue
                    if lowered in {'auth_files', 'credentials_file', 'cookie_file', 'oauth_file'}:
                        continue
                    sanitized[key] = _sanitize(item)
                return sanitized
            if isinstance(value, list):
                return [_sanitize(item) for item in value]
            return value

        return _sanitize(copy.deepcopy(config or {}))

    def _load_market_listing_row(self, row) -> Dict[str, Any]:
        metadata = json.loads(row[14]) if row[14] else {}
        config_snapshot = json.loads(row[15]) if row[15] else {}
        return {
            'id': row[0],
            'owner_user_id': row[1],
            'owner_username': row[2],
            'source_scope': row[3],
            'source_type': row[4],
            'source_id': row[5],
            'listing_key': row[6],
            'title': row[7],
            'description': row[8],
            'provider_id': row[9],
            'model_id': row[10],
            'endpoint': row[11],
            'currency_code': row[12],
            'price_per_million_tokens': float(row[13] or 0),
            'price_per_1000_requests': float(row[16] or 0),
            'provider_price_per_million_tokens': float(row[17]) if row[17] is not None else None,
            'provider_price_per_1000_requests': float(row[18]) if row[18] is not None else None,
            'metadata': metadata,
            'config_snapshot': config_snapshot,
            'is_active': bool(row[19]),
            'created_at': row[20],
            'updated_at': row[21],
        }

    async def _run_in_executor(self, func, *args):
        """Run a blocking database operation in a thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, func, *args)

    async def execute(self, sql: str, params: dict = None):
        """Execute SQL query and return result with mappings (compatible with AsyncSession interface)"""
        _params = params or {}
        def _sync_execute():
            with self._get_connection() as conn:
                if self.db_type == 'sqlite':
                    cursor = conn.cursor()
                    cursor.row_factory = sqlite3.Row
                    cursor.execute(sql, _params)
                else:
                    cursor = conn.cursor(dictionary=True)
                    import re
                    param_names = []
                    processed_sql = re.sub(r':(\w+)', lambda m: (param_names.append(m.group(1)), '%s')[1], sql)
                    cursor.execute(processed_sql, [_params[n] for n in param_names])

                if cursor.description:
                    rows = [dict(row) for row in cursor.fetchall()]
                    # Simulate SQLAlchemy Result object with mappings() method
                    class ResultWrapper:
                        def mappings(self):
                            class MappingsWrapper:
                                def first(self):
                                    return rows[0] if rows else None
                                def all(self):
                                    return rows
                            return MappingsWrapper()
                    return ResultWrapper()
                else:
                    class EmptyResult:
                        def mappings(self):
                            return []
                    return EmptyResult()
        
        return await self._run_in_executor(_sync_execute)
    
    async def commit(self):
        """Commit transaction (compatibility method for WalletManager)"""
        # Transactions are auto-committed per operation in this implementation
        pass
    
    def begin(self):
        """Async context manager for transactions (compatibility)"""
        class TransactionContext:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False  # never suppress exceptions
        return TransactionContext()



    async def record_context_dimension_async(
        self,
        provider_id: str,
        model_name: str,
        context_size: Optional[int] = None,
        condense_context: Optional[int] = None,
        condense_method: Optional[str] = None
    ):
        """
        Record or update context dimension configuration for a model (async version).

        Args:
            provider_id: The provider identifier
            model_name: The model name
            context_size: Maximum context size in tokens
            condense_context: Percentage (0-100) at which to trigger condensation
            condense_method: Condensation method(s) as string or list
        """
        def _sync_operation():
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Convert condense_method to JSON string if it's a list
                condense_method_str = json.dumps(condense_method) if isinstance(condense_method, list) else condense_method

                if self.db_type == 'sqlite':
                    cursor.execute('''
                        INSERT OR REPLACE INTO context_dimensions
                        (provider_id, model_name, context_size, condense_context, condense_method, last_updated)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (provider_id, model_name, context_size, condense_context, condense_method_str))
                else:  # mysql
                    cursor.execute('''
                        INSERT INTO context_dimensions
                        (provider_id, model_name, context_size, condense_context, condense_method, last_updated)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE
                        context_size=VALUES(context_size), condense_context=VALUES(condense_context),
                        condense_method=VALUES(condense_method), last_updated=CURRENT_TIMESTAMP
                    ''', (provider_id, model_name, context_size, condense_context, condense_method_str))

                conn.commit()
                logger.debug(f"Recorded context dimension for {provider_id}/{model_name}")

        await self._run_in_executor(_sync_operation)

    def record_context_dimension(
        self,
        provider_id: str,
        model_name: str,
        context_size: Optional[int] = None,
        condense_context: Optional[int] = None,
        condense_method: Optional[str] = None
    ):
        """
        Record or update context dimension configuration for a model.

        Args:
            provider_id: The provider identifier
            model_name: The model name
            context_size: Maximum context size in tokens
            condense_context: Percentage (0-100) at which to trigger condensation
            condense_method: Condensation method(s) as string or list
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Convert condense_method to JSON string if it's a list
            condense_method_str = json.dumps(condense_method) if isinstance(condense_method, list) else condense_method

            if self.db_type == 'sqlite':
                cursor.execute('''
                    INSERT OR REPLACE INTO context_dimensions
                    (provider_id, model_name, context_size, condense_context, condense_method, last_updated)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (provider_id, model_name, context_size, condense_context, condense_method_str))
            else:  # mysql
                cursor.execute('''
                    INSERT INTO context_dimensions
                    (provider_id, model_name, context_size, condense_context, condense_method, last_updated)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                    context_size=VALUES(context_size), condense_context=VALUES(condense_context),
                    condense_method=VALUES(condense_method), last_updated=CURRENT_TIMESTAMP
                ''', (provider_id, model_name, context_size, condense_context, condense_method_str))

            conn.commit()
            logger.debug(f"Recorded context dimension for {provider_id}/{model_name}")
    
    def run_payment_migrations(self):
        """Run payment system migrations"""
        from aisbf.payments.migrations import PaymentMigrations
        
        migrations = PaymentMigrations(self)
        migrations.run_migrations()
    
    def get_context_dimension(
        self,
        provider_id: str,
        model_name: str
    ) -> Optional[Dict]:
        """
        Retrieve context dimension configuration for a model.

        Args:
            provider_id: The provider identifier
            model_name: The model name

        Returns:
            Dictionary with context configuration or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT context_size, condense_context, condense_method, effective_context
                FROM context_dimensions
                WHERE provider_id = {placeholder} AND model_name = {placeholder}
            ''', (provider_id, model_name))

            row = cursor.fetchone()
            if row:
                condense_method = json.loads(row[2]) if row[2] else None
                return {
                    'context_size': row[0],
                    'condense_context': row[1],
                    'condense_method': condense_method,
                    'effective_context': row[3]
                }
            return None
    
    def update_effective_context(
        self,
        provider_id: str,
        model_name: str,
        effective_context: int
    ):
        """
        Update the effective context value for a model.

        Args:
            provider_id: The provider identifier
            model_name: The model name
            effective_context: Total tokens used in the request
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE context_dimensions
                SET effective_context = {placeholder}, last_updated = CURRENT_TIMESTAMP
                WHERE provider_id = {placeholder} AND model_name = {placeholder}
            ''', (effective_context, provider_id, model_name))

            conn.commit()
            logger.debug(f"Updated effective_context for {provider_id}/{model_name}: {effective_context}")
    
    def record_token_usage(
        self,
        provider_id: str,
        model_name: str,
        tokens_used: int,
        user_id: Optional[int] = None,
        success: bool = True,
        latency_ms: float = 0,
        error_type: Optional[str] = None,
        token_id: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        actual_cost: Optional[float] = None,
        rotation_id: Optional[str] = None,
        autoselect_id: Optional[str] = None,
        analytics_kind: str = 'execution'
    ):
        """
        Record token usage for rate limiting and analytics.

        Args:
            provider_id: The provider identifier
            model_name: The model name
            tokens_used: Number of tokens used in the request (total)
            user_id: Optional user ID for user-specific tracking
            success: Whether the request was successful
            latency_ms: Request latency in milliseconds (float)
            error_type: Optional error type if request failed
            token_id: Optional API token ID used for the request
            prompt_tokens: Optional number of input/prompt tokens
            completion_tokens: Optional number of output/completion tokens
            actual_cost: Optional actual cost returned by provider (in USD)
        """
        logger.debug(f"DB.record_token_usage: provider={provider_id}, tokens={tokens_used}, user_id={user_id}")
        try:
            # Convert latency to int for storage
            latency_int = int(latency_ms) if latency_ms else 0
            logger.debug(f"DB.record_token_usage params: provider={provider_id}, model={model_name}, tokens={tokens_used}, user={user_id}, success={success}")

            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db_type == 'sqlite' else '%s'

                # Build dynamic INSERT based on available columns (for backward compatibility)
                base_columns = ['user_id', 'provider_id', 'model_name', 'tokens_used', 'timestamp']
                base_params = [user_id, provider_id, model_name, tokens_used]

                # Check for additional columns and add them if they exist
                try:
                    # Try to insert with all columns
                    sql = f'''
                        INSERT INTO token_usage (user_id, provider_id, model_name, tokens_used, prompt_tokens, completion_tokens, actual_cost, success, latency_ms, error_type, token_id, rotation_id, autoselect_id, analytics_kind, timestamp)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    '''
                    params = (user_id, provider_id, model_name, tokens_used, prompt_tokens, completion_tokens, actual_cost, success, latency_int, error_type, token_id, rotation_id, autoselect_id, analytics_kind)
                    logger.debug(f"Trying full INSERT with {len(params)} parameters")
                    cursor.execute(sql, params)
                    logger.debug(f"Inserted with full column set, rows affected: {cursor.rowcount}")
                except Exception as full_insert_error:
                    logger.warning(f"⚠️ Full column insert failed: {full_insert_error}")
                    logger.warning(f"⚠️ Full insert error type: {type(full_insert_error).__name__}")
                    import traceback
                    logger.warning(f"⚠️ Full insert traceback: {traceback.format_exc()}")
                    logger.debug("Falling back to basic insert")
                    # Fallback to basic columns only
                    sql = f'''
                        INSERT INTO token_usage (user_id, provider_id, model_name, tokens_used, timestamp)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    '''
                    params = (user_id, provider_id, model_name, tokens_used)
                    cursor.execute(sql, params)
                    logger.debug(f"Inserted with basic column set, rows affected: {cursor.rowcount}")

                conn.commit()
                logger.info(f"Recorded token usage: {provider_id}/{model_name} {tokens_used} tokens (user_id={user_id})")
        except Exception as e:
            logger.error(f"❌ Failed to record token usage for {provider_id}/{model_name}: {e}")
            logger.error(f"Error details - user_id={user_id}, tokens={tokens_used}, success={success}")
            # Try a simple test insert to see if database works
            try:
                with self._get_connection() as test_conn:
                    test_cursor = test_conn.cursor()
                    test_cursor.execute("INSERT INTO token_usage (provider_id, model_name, tokens_used, success) VALUES (?, 'test', 1, 1)" if self.db_type == 'sqlite' else "INSERT INTO token_usage (provider_id, model_name, tokens_used, success) VALUES (%s, 'test', 1, 1)", (f"test-{provider_id}",))
                    test_conn.commit()
                    logger.debug("Test database insert succeeded")
            except Exception as test_e:
                logger.error(f"❌ Even test database insert failed: {test_e}")
            raise
    
    def get_token_usage(
        self,
        provider_id: str,
        model_name: str,
        time_window: str = '1m',  # 1m, 1h, 1d
        user_id: Optional[int] = None
    ) -> int:
        """
        Get total token usage for a model within a time window.

        Args:
            provider_id: The provider identifier
            model_name: The model name
            time_window: Time window ('1m' for minute, '1h' for hour, '1d' for day)
            user_id: Optional user ID to filter by

        Returns:
            Total tokens used within the time window
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Calculate timestamp based on time window
            if time_window == '1m':
                cutoff = datetime.now() - timedelta(minutes=1)
            elif time_window == '1h':
                cutoff = datetime.now() - timedelta(hours=1)
            elif time_window == '1d':
                cutoff = datetime.now() - timedelta(days=1)
            else:
                cutoff = datetime.now() - timedelta(minutes=1)

            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if user_id is not None:
                if self.db_type == 'sqlite':
                    cursor.execute(f'''
                        SELECT COALESCE(SUM(tokens_used), 0)
                        FROM token_usage
                        WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name = {placeholder} AND timestamp >= {placeholder}
                    ''', (user_id, provider_id, model_name, cutoff.isoformat()))
                else:  # mysql
                    cursor.execute(f'''
                        SELECT COALESCE(SUM(tokens_used), 0)
                        FROM token_usage
                        WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name = {placeholder} AND timestamp >= {placeholder}
                    ''', (user_id, provider_id, model_name, cutoff.isoformat()))
            else:
                if self.db_type == 'sqlite':
                    cursor.execute(f'''
                        SELECT COALESCE(SUM(tokens_used), 0)
                        FROM token_usage
                        WHERE provider_id = {placeholder} AND model_name = {placeholder} AND timestamp >= {placeholder}
                    ''', (provider_id, model_name, cutoff.isoformat()))
                else:  # mysql
                    cursor.execute(f'''
                        SELECT COALESCE(SUM(tokens_used), 0)
                        FROM token_usage
                        WHERE provider_id = {placeholder} AND model_name = {placeholder} AND timestamp >= {placeholder}
                    ''', (provider_id, model_name, cutoff.isoformat()))

            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_user_token_usage_stats(self, user_id: int) -> Dict[str, int]:
        """
        Get aggregated token usage statistics for a user across all providers.
        
        Args:
            user_id: The user ID
            
        Returns:
            Dictionary with TPM, TPH, TPD statistics
        """
        return {
            'TPM': self.get_user_token_usage(user_id, '1m'),
            'TPH': self.get_user_token_usage(user_id, '1h'),
            'TPD': self.get_user_token_usage(user_id, '1d')
        }
    
    def get_user_token_usage(self, user_id: int, time_window: str = '1m') -> int:
        """
        Get total token usage for a user within a time window.
        
        Args:
            user_id: The user ID
            time_window: Time window ('1m', '1h', '1d')
            
        Returns:
            Total tokens used within the time window
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if time_window == '1m':
                cutoff = datetime.now() - timedelta(minutes=1)
            elif time_window == '1h':
                cutoff = datetime.now() - timedelta(hours=1)
            elif time_window == '1d':
                cutoff = datetime.now() - timedelta(days=1)
            else:
                cutoff = datetime.now() - timedelta(minutes=1)
            
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT COALESCE(SUM(tokens_used), 0)
                FROM token_usage
                WHERE user_id = {placeholder} AND timestamp >= {placeholder}
            ''', (user_id, cutoff.isoformat()))
            
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_all_users_token_usage(self) -> List[Dict]:
        """
        Get aggregated token usage for all users.
        
        Returns:
            List of user statistics with token usage
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Get all users
            cursor.execute(f'''
                SELECT u.id, u.username, u.role
                FROM users u
                WHERE u.is_active = 1
            ''')
            
            users = []
            for row in cursor.fetchall():
                user_id = row[0]
                # Get token usage for this user in last hour and day
                cursor.execute(f'''
                    SELECT COALESCE(SUM(tokens_used), 0)
                    FROM token_usage
                    WHERE user_id = {placeholder} AND timestamp >= {placeholder}
                ''', (user_id, (datetime.now() - timedelta(hours=1)).isoformat()))
                tokens_1h = cursor.fetchone()[0] or 0
                
                cursor.execute(f'''
                    SELECT COALESCE(SUM(tokens_used), 0)
                    FROM token_usage
                    WHERE user_id = {placeholder} AND timestamp >= {placeholder}
                ''', (user_id, (datetime.now() - timedelta(days=1)).isoformat()))
                tokens_1d = cursor.fetchone()[0] or 0
                
                users.append({
                    'user_id': user_id,
                    'username': row[1],
                    'role': row[2],
                    'tokens_1h': tokens_1h,
                    'tokens_1d': tokens_1d
                })
            
            return users
    
    def cleanup_old_token_usage(self, days_to_keep: int = 7):
        """
        Clean up old token usage records to prevent database bloat.

        Args:
            days_to_keep: Number of days of token usage to keep
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days_to_keep)

            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM token_usage
                WHERE timestamp < {placeholder}
            ''', (cutoff.isoformat(),))

            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old token usage records")

    def delete_analytics_global(self):
        """Delete token_usage rows that belong to global (non-user) requests only."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM token_usage WHERE user_id IS NULL')
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted} global analytics records")
            return deleted

    def delete_analytics_all(self):
        """Delete all token_usage rows (global + all users)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM token_usage')
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted} total analytics records")
            return deleted
    
    def get_all_context_dimensions(self, user_filter: Optional[int] = None) -> List[Dict]:
        """
        Get all context dimension configurations.

        Args:
            user_filter: Optional user ID to filter by

        Returns:
            List of dictionaries with context configurations
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Note: context_dimensions table doesn't have user_id, so we can't filter by user
            # This method returns all context dimensions regardless of user_filter
            # User-specific filtering happens at the token_usage level in other methods
            cursor.execute('''
                SELECT provider_id, model_name, context_size, condense_context, condense_method, effective_context, last_updated
                FROM context_dimensions
                ORDER BY provider_id, model_name
            ''')

            results = []
            for row in cursor.fetchall():
                condense_method = json.loads(row[4]) if row[4] else None
                results.append({
                    'provider_id': row[0],
                    'model_name': row[1],
                    'context_size': row[2],
                    'condense_context': row[3],
                    'condense_method': condense_method,
                    'effective_context': row[5],
                    'last_updated': row[6]
                })

            return results
    
    def get_token_usage_stats(
        self,
        provider_id: str,
        model_name: str
    ) -> Dict[str, int]:
        """
        Get token usage statistics for a model.
        
        Args:
            provider_id: The provider identifier
            model_name: The model name
        
        Returns:
            Dictionary with TPM, TPH, and TPD statistics
        """
        return {
            'TPM': self.get_token_usage(provider_id, model_name, '1m'),
            'TPH': self.get_token_usage(provider_id, model_name, '1h'),
            'TPD': self.get_token_usage(provider_id, model_name, '1d')
        }

    # User management methods
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """
        Authenticate a user by username and plain-text password.

        Supports bcrypt hashes and legacy SHA-256 hashes.  On a successful
        SHA-256 match the stored hash is transparently upgraded to bcrypt.

        Args:
            username: Username to authenticate
            password: Plain-text password

        Returns:
            User dict if authenticated, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'

            # First check what columns exist in users table
            if self.db_type == 'sqlite':
                cursor.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]
            else:  # mysql
                cursor.execute("""
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = 'users'
                    AND TABLE_SCHEMA = DATABASE()
                """)
                columns = [col[0] for col in cursor.fetchall()]

            select_fields = ['id', 'username', 'role', 'is_active', 'password_hash']
            if 'email' in columns:
                select_fields.append('email')
            if 'email_verified' in columns:
                select_fields.append('email_verified')
            if 'created_at' in columns:
                select_fields.append('created_at')
            if 'last_verification_email_sent' in columns:
                select_fields.append('last_verification_email_sent')

            cursor.execute(f'''
                SELECT {', '.join(select_fields)}
                FROM users
                WHERE username = {placeholder} AND is_active = 1
            ''', (username,))

            row = cursor.fetchone()
            if not row:
                return None

            stored_hash = row[4]
            if not _verify_password(password, stored_hash):
                return None

            # Auto-upgrade legacy SHA-256 hash to bcrypt on successful login
            if not stored_hash.startswith("$2") and _BCRYPT_AVAILABLE:
                new_hash = _hash_password(password)
                cursor.execute(
                    f'UPDATE users SET password_hash = {placeholder} WHERE id = {placeholder}',
                    (new_hash, row[0])
                )
                conn.commit()

            result = {
                'id': row[0],
                'username': row[1],
                'role': row[2],
                'is_active': row[3],
                'email': None,
                'email_verified': True,
                'created_at': None,
                'last_verification_email_sent': None
            }

            idx = 5
            if 'email' in columns:
                result['email'] = row[idx] or None
                idx += 1
            if 'email_verified' in columns:
                result['email_verified'] = bool(row[idx]) if row[idx] is not None else True
                idx += 1
            if 'created_at' in columns:
                result['created_at'] = row[idx] if row[idx] else None
                idx += 1
            if 'last_verification_email_sent' in columns:
                result['last_verification_email_sent'] = row[idx] if row[idx] else None

            return result

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """
        Get a user by username.

        Args:
            username: Username to look up

        Returns:
            User dict if found, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, username, display_name, role, is_active
                FROM users
                WHERE username = {placeholder} AND is_active = 1
            ''', (username,))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'username': row[1],
                    'display_name': row[2] or row[1],  # Default to username if display_name empty
                    'role': row[3],
                    'is_active': row[4]
                }
            return None

    def create_user(self, username: str, password_hash: str, role: str = 'user', created_by: str = None,
                email: str = None, email_verified: bool = False, display_name: str = None) -> int:
        """
        Create a new user.

        Args:
            username: Username for the new user
            password_hash: Password hash (bcrypt or SHA-256 legacy)
            role: User role ('admin' or 'user')
            created_by: Username of the creator
            email: Email address (optional)
            email_verified: Whether email is verified (default: False)
            display_name: Display name for the user (optional, defaults to username)

        Returns:
            User ID of the created user
        """
        # When user is created by an admin (created_by is set), automatically mark email as verified
        # regardless of whether email was provided - admins don't need verification
        if created_by is not None:
            email_verified = True
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO users (username, email, password_hash, role, created_by, email_verified, display_name)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (username, email, password_hash, role, created_by, 1 if email_verified else 0, display_name or username))
            conn.commit()
            return cursor.lastrowid

    def delete_stale_unverified_signup_users(self, inactivity_days: int = 14) -> int:
        """
        Delete self-registered users who never logged in within the grace period.

        Args:
            inactivity_days: Number of days after registration before deletion.

        Returns:
            Number of deleted users.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'

            if self.db_type == 'sqlite':
                cutoff_expr = f"datetime('now', '-' || {placeholder} || ' days')"
            else:
                cutoff_expr = f"DATE_SUB(NOW(), INTERVAL {placeholder} DAY)"

            cursor.execute(f'''
                SELECT id
                FROM users
                WHERE role = 'user'
                  AND created_by IS NULL
                  AND last_login IS NULL
                  AND email_verified = 0
                  AND created_at <= {cutoff_expr}
            ''', (inactivity_days,))
            user_ids = [row[0] for row in cursor.fetchall()]

            for user_id in user_ids:
                self.delete_user(user_id)

            return len(user_ids)
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """
        Get a user by email address.

        Args:
            email: Email address to look up

        Returns:
            User dict if found, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, username, email, display_name, role, is_active, email_verified, profile_pic
                FROM users
                WHERE email = {placeholder}
            ''', (email,))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'display_name': row[3] or row[1],  # Default to username if display_name empty
                    'role': row[4],
                    'is_active': row[5],
                    'email_verified': row[6],
                    'profile_pic': row[7] or None
                }
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """
        Get a user by ID.

        Args:
            user_id: User ID to look up

        Returns:
            User dict if found, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, username, email, display_name, role, is_active, email_verified, created_at, last_verification_email_sent, profile_pic
                FROM users
                WHERE id = {placeholder}
            ''', (user_id,))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'display_name': row[3] or row[1],  # Default to username if display_name empty
                    'role': row[4],
                    'is_active': row[5],
                    'email_verified': row[6],
                    'created_at': row[7],
                    'last_verification_email_sent': row[8],
                    'profile_pic': row[9] or None
                }
            return None

    def list_studio_assets(self, user_id: int, asset_type: str) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT name, description, metadata_json, files_json, quote_text, created_at, updated_at
                FROM studio_assets
                WHERE user_id = {placeholder} AND asset_type = {placeholder}
                ORDER BY updated_at DESC
            ''', (user_id, asset_type))
            rows = cursor.fetchall()
            items = []
            for row in rows:
                meta = _studio_json_loads(row[2], {})
                files = _studio_json_loads(row[3], [])
                item = {
                    'name': row[0],
                    'description': row[1] or '',
                    'kind': asset_type,
                    'created_at': self._normalize_db_timestamp(row[5]),
                    'updated_at': self._normalize_db_timestamp(row[6]),
                }
                item.update(meta)
                if asset_type in ('character', 'environment'):
                    item['ref_images'] = files
                    item['image_count'] = len(files)
                elif asset_type == 'voice':
                    item['sample_files'] = files
                    item['quote'] = row[4] or ''
                    item['transcript'] = row[4] or ''
                items.append(item)
            return items

    def get_studio_asset(self, user_id: int, asset_type: str, name: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT name, description, metadata_json, files_json, quote_text, created_at, updated_at
                FROM studio_assets
                WHERE user_id = {placeholder} AND asset_type = {placeholder} AND name = {placeholder}
            ''', (user_id, asset_type, name))
            row = cursor.fetchone()
            if not row:
                return None
            meta = _studio_json_loads(row[2], {})
            files = _studio_json_loads(row[3], [])
            item = {
                'name': row[0],
                'description': row[1] or '',
                'kind': asset_type,
                'created_at': self._normalize_db_timestamp(row[5]),
                'updated_at': self._normalize_db_timestamp(row[6]),
            }
            item.update(meta)
            if asset_type in ('character', 'environment'):
                item['ref_images'] = files
                item['image_count'] = len(files)
            elif asset_type == 'voice':
                item['sample_files'] = files
                item['quote'] = row[4] or ''
                item['transcript'] = row[4] or ''
            return item

    def upsert_studio_asset(self, user_id: int, asset_type: str, name: str, description: str, metadata: Dict, files: List[str], quote_text: str = '') -> Dict:
        existing = self.get_studio_asset(user_id, asset_type, name)
        created_at = existing.get('created_at') if existing else int(time.time())
        now = int(time.time())
        payload_meta = dict(metadata or {})
        payload_meta.setdefault('name', name)
        payload_meta.setdefault('kind', asset_type)
        payload_meta['created_at'] = created_at
        payload_meta['updated_at'] = now
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT INTO studio_assets (user_id, asset_type, name, description, metadata_json, files_json, quote_text, created_at, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, datetime({placeholder}, 'unixepoch'), datetime({placeholder}, 'unixepoch'))
                    ON CONFLICT(user_id, asset_type, name) DO UPDATE SET
                        description=excluded.description,
                        metadata_json=excluded.metadata_json,
                        files_json=excluded.files_json,
                        quote_text=excluded.quote_text,
                        updated_at=excluded.updated_at
                ''', (user_id, asset_type, name, description, _studio_json_dumps(payload_meta), _studio_json_dumps(files), quote_text, created_at, now))
            else:
                cursor.execute(f'''
                    INSERT INTO studio_assets (user_id, asset_type, name, description, metadata_json, files_json, quote_text, created_at, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, FROM_UNIXTIME({placeholder}), FROM_UNIXTIME({placeholder}))
                    ON DUPLICATE KEY UPDATE
                        description=VALUES(description),
                        metadata_json=VALUES(metadata_json),
                        files_json=VALUES(files_json),
                        quote_text=VALUES(quote_text),
                        updated_at=VALUES(updated_at)
                ''', (user_id, asset_type, name, description, _studio_json_dumps(payload_meta), _studio_json_dumps(files), quote_text, created_at, now))
            conn.commit()
        return self.get_studio_asset(user_id, asset_type, name)

    def delete_studio_asset(self, user_id: int, asset_type: str, name: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'DELETE FROM studio_assets WHERE user_id = {placeholder} AND asset_type = {placeholder} AND name = {placeholder}', (user_id, asset_type, name))
            conn.commit()
            return cursor.rowcount > 0

    def list_studio_pipelines(self, user_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT pipeline_id, name, description, steps_json, created_at, updated_at
                FROM studio_pipelines
                WHERE user_id = {placeholder}
                ORDER BY updated_at DESC
            ''', (user_id,))
            rows = cursor.fetchall()
            return [{
                'id': row[0],
                'name': row[1],
                'description': row[2] or '',
                'steps': _studio_json_loads(row[3], []),
                'created_at': self._normalize_db_timestamp(row[4]),
                'updated_at': self._normalize_db_timestamp(row[5]),
            } for row in rows]

    def get_studio_pipeline(self, user_id: int, pipeline_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT pipeline_id, name, description, steps_json, created_at, updated_at
                FROM studio_pipelines
                WHERE user_id = {placeholder} AND pipeline_id = {placeholder}
            ''', (user_id, pipeline_id))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                'id': row[0],
                'name': row[1],
                'description': row[2] or '',
                'steps': _studio_json_loads(row[3], []),
                'created_at': self._normalize_db_timestamp(row[4]),
                'updated_at': self._normalize_db_timestamp(row[5]),
            }

    def upsert_studio_pipeline(self, user_id: int, pipeline_id: str, name: str, description: str, steps: List[Dict]) -> Dict:
        existing = self.get_studio_pipeline(user_id, pipeline_id)
        created_at = existing.get('created_at') if existing else int(time.time())
        now = int(time.time())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT INTO studio_pipelines (user_id, pipeline_id, name, description, steps_json, created_at, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, datetime({placeholder}, 'unixepoch'), datetime({placeholder}, 'unixepoch'))
                    ON CONFLICT(user_id, pipeline_id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        steps_json=excluded.steps_json,
                        updated_at=excluded.updated_at
                ''', (user_id, pipeline_id, name, description, _studio_json_dumps(steps), created_at, now))
            else:
                cursor.execute(f'''
                    INSERT INTO studio_pipelines (user_id, pipeline_id, name, description, steps_json, created_at, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, FROM_UNIXTIME({placeholder}), FROM_UNIXTIME({placeholder}))
                    ON DUPLICATE KEY UPDATE
                        name=VALUES(name),
                        description=VALUES(description),
                        steps_json=VALUES(steps_json),
                        updated_at=VALUES(updated_at)
                ''', (user_id, pipeline_id, name, description, _studio_json_dumps(steps), created_at, now))
            conn.commit()
        return self.get_studio_pipeline(user_id, pipeline_id)

    def delete_studio_pipeline(self, user_id: int, pipeline_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'DELETE FROM studio_pipelines WHERE user_id = {placeholder} AND pipeline_id = {placeholder}', (user_id, pipeline_id))
            conn.commit()
            return cursor.rowcount > 0

    def _normalize_db_timestamp(self, value) -> int:
        if value is None:
            return int(time.time())
        if isinstance(value, datetime):
            return int(value.timestamp())
        if isinstance(value, str):
            try:
                return int(datetime.fromisoformat(value).timestamp())
            except Exception:
                try:
                    return int(datetime.strptime(value, '%Y-%m-%d %H:%M:%S').timestamp())
                except Exception:
                    return int(time.time())
        try:
            return int(value)
        except Exception:
            return int(time.time())

    def set_verification_token(self, user_id: int, token: str, expires_at: datetime):
        """
        Set email verification token for a user.

        Args:
            user_id: User ID
            token: Verification token
            expires_at: Token expiration datetime
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET verification_token = {placeholder}, verification_token_expires = {placeholder}
                WHERE id = {placeholder}
            ''', (token, expires_at.isoformat(), user_id))
            conn.commit()

    def update_last_verification_email_sent(self, user_id: int, sent_at: datetime):
        """
        Update the last verification email sent timestamp for a user.

        Args:
            user_id: User ID
            sent_at: Timestamp when email was sent
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET last_verification_email_sent = {placeholder}
                WHERE id = {placeholder}
            ''', (sent_at.isoformat(), user_id))
            conn.commit()

    def verify_email_token(self, email: str, token: str) -> bool:
        """
        Verify an email verification token for a specific email address.

        Args:
            email: User's email address
            token: Verification token

        Returns:
            True if token is valid and not expired, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Find user with this email and token that hasn't expired
            cursor.execute(f'''
                SELECT id, verification_token_expires
                FROM users
                WHERE email = {placeholder} AND verification_token = {placeholder} AND is_active = 1
            ''', (email, token))
            
            row = cursor.fetchone()
            if not row:
                return False
            
            user_id, expires_str = row
            
            # Check if token has expired
            if expires_str:
                # Handle both string and datetime objects
                if isinstance(expires_str, str):
                    expires_at = datetime.fromisoformat(expires_str)
                else:
                    expires_at = expires_str
                
                if datetime.now() > expires_at:
                    return False
            
            return True

    def verify_email(self, email: str) -> bool:
        """
        Mark a user's email as verified and clear the verification token.

        Args:
            email: User's email address

        Returns:
            True if email was verified successfully, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Mark email as verified and clear token
            cursor.execute(f'''
                UPDATE users
                SET email_verified = 1, verification_token = NULL, verification_token_expires = NULL
                WHERE email = {placeholder}
            ''', (email,))
            conn.commit()
            
            return cursor.rowcount > 0
    
    def set_password_reset_token(self, user_id: int, token: str, expires_at: datetime):
        """
        Set password reset token for a user.

        Args:
            user_id: User ID
            token: Password reset token
            expires_at: Token expiration datetime
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET reset_password_token = {placeholder}, reset_password_token_expires = {placeholder}
                WHERE id = {placeholder}
            ''', (token, expires_at.isoformat(), user_id))
            conn.commit()
    
    def get_user_by_reset_token(self, token: str) -> Optional[Dict]:
        """
        Get a user by password reset token, checking expiration.

        Args:
            token: Password reset token

        Returns:
            User dict if token is valid and not expired, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            cursor.execute(f'''
                SELECT id, username, email, reset_password_token_expires
                FROM users
                WHERE reset_password_token = {placeholder} AND is_active = 1
            ''', (token,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            user_id, username, email, expires_str = row
            
            # Check if token has expired
            if expires_str:
                expires_at = datetime.fromisoformat(expires_str)
                if datetime.now() > expires_at:
                    return None
            
            return {
                'id': user_id,
                'username': username,
                'email': email
            }
    
    def clear_password_reset_token(self, user_id: int):
        """
        Clear password reset token after successful password reset.

        Args:
            user_id: User ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET reset_password_token = NULL, reset_password_token_expires = NULL
                WHERE id = {placeholder}
            ''', (user_id,))
            conn.commit()
    
    def update_user_password(self, user_id: int, password_hash: str):
        """
        Update a user's password hash.

        Args:
            user_id: User ID
            password_hash: New password hash (bcrypt or SHA-256)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET password_hash = {placeholder}
                WHERE id = {placeholder}
            ''', (password_hash, user_id))
            conn.commit()

    def get_users(self) -> List[Dict]:
        """
        Get all users.

        Returns:
            List of user dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Always select columns explicitly in order - fixes broken column order after migrations
            cursor.execute('''
                SELECT
                    id,
                    username,
                    email,
                    role,
                    created_by,
                    created_at,
                    last_login,
                    is_active
                FROM users
                ORDER BY created_at DESC
            ''')

            # Use column names from cursor description instead of positions
            # This is 100% safe regardless of table column order
            columns = [col[0] for col in cursor.description]
            
            users = []
            for row in cursor.fetchall():
                user = dict(zip(columns, row))
                # Normalize boolean fields
                user['is_active'] = bool(user['is_active']) if user['is_active'] is not None else True
                users.append(user)
            return users

    def get_users_paginated(self, page: int = 1, limit: int = 25, search: str = None,
                           order_by: str = 'created_at', direction: str = 'desc',
                           status_filter: str = None, role_filter: str = None,
                           tier_filter: str = None, market_export_filter: str = None) -> Dict:
        """
        Get paginated users with search, sorting, and filtering support.

        Args:
            page: Page number (1-indexed)
            limit: Number of users per page
            search: Optional search term (searches username, email, display_name)
            order_by: Column to sort by (username, last_login, created_at, tier_name)
            direction: Sort direction (asc or desc)
            status_filter: Optional status filter ('active', 'inactive', or None)
            role_filter: Optional role filter ('admin', 'user', or None)
            tier_filter: Optional account tier id filter
            market_export_filter: Optional market export filter ('exporting', 'not_exporting', or None)

        Returns:
            Dictionary with 'users' list and 'total' count
        """
        # Validate and sanitize sorting parameters
        valid_columns = ['username', 'last_login', 'created_at', 'tier_name']
        valid_directions = ['asc', 'desc']

        if order_by not in valid_columns:
            order_by = 'created_at'
        if direction.lower() not in valid_directions:
            direction = 'desc'

        direction = direction.upper()

        # Validate filter parameters
        valid_status_filters = ['active', 'inactive', None]
        valid_role_filters = ['admin', 'user', None]

        if status_filter not in valid_status_filters:
            status_filter = None
        if role_filter not in valid_role_filters:
            role_filter = None
        
        # Calculate offset
        offset = (page - 1) * limit
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Build WHERE clause
            where_conditions = []
            params = []

            # Add search condition
            if search:
                search_term = f'%{search}%'
                where_conditions.append(f'''
                    (
                        u.username LIKE {placeholder}
                        OR u.email LIKE {placeholder}
                        OR u.display_name LIKE {placeholder}
                    )
                ''')
                params.extend([search_term, search_term, search_term])

            # Add status filter
            if status_filter == 'active':
                where_conditions.append(f'u.is_active = {placeholder}')
                params.append(1)
            elif status_filter == 'inactive':
                where_conditions.append(f'u.is_active = {placeholder}')
                params.append(0)

            # Add role filter
            if role_filter:
                where_conditions.append(f'u.role = {placeholder}')
                params.append(role_filter)

            if tier_filter:
                where_conditions.append(f'u.tier_id = {placeholder}')
                params.append(tier_filter)

            if market_export_filter == 'exporting':
                where_conditions.append(
                    f'EXISTS (SELECT 1 FROM market_listings ml WHERE ml.owner_user_id = u.id AND ml.is_active = 1)'
                )
            elif market_export_filter == 'not_exporting':
                where_conditions.append(
                    f'NOT EXISTS (SELECT 1 FROM market_listings ml WHERE ml.owner_user_id = u.id AND ml.is_active = 1)'
                )

            # Build final WHERE clause
            where_clause = 'WHERE ' + ' AND '.join(where_conditions) if where_conditions else ''
            
            # Build ORDER BY clause - map tier_name to the joined column
            if order_by == 'tier_name':
                order_clause = f't.name {direction}'
            else:
                order_clause = f'u.{order_by} {direction}'
            
            # Get total count
            count_query = f'''
                SELECT COUNT(*)
                FROM users u
                LEFT JOIN account_tiers t ON u.tier_id = t.id
                {where_clause}
            '''
            cursor.execute(count_query, params)
            total = cursor.fetchone()[0]
            
            # Get paginated users
            users_query = f'''
                SELECT
                    u.id,
                    u.username,
                    u.email,
                    u.role,
                    u.created_by,
                    u.created_at,
                    u.last_login,
                    u.is_active,
                    u.tier_id,
                    u.display_name,
                    t.name as tier_name
                FROM users u
                LEFT JOIN account_tiers t ON u.tier_id = t.id
                {where_clause}
                ORDER BY {order_clause}
                LIMIT {placeholder} OFFSET {placeholder}
            '''
            
            query_params = params + [limit, offset]
            cursor.execute(users_query, query_params)
            
            # Use column names from cursor description
            columns = [col[0] for col in cursor.description]
            
            users = []
            for row in cursor.fetchall():
                user = dict(zip(columns, row))
                # Normalize boolean fields
                user['is_active'] = bool(user['is_active']) if user['is_active'] is not None else True
                users.append(user)
            
            return {
                'users': users,
                'total': total
            }

    def delete_user(self, user_id: int):
        """
        Delete a user and all their configurations.

        Args:
            user_id: User ID to delete
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            # Delete user configurations first (due to foreign key constraints)
            cursor.execute(f'DELETE FROM user_providers WHERE user_id = {placeholder}', (user_id,))
            cursor.execute(f'DELETE FROM user_rotations WHERE user_id = {placeholder}', (user_id,))
            cursor.execute(f'DELETE FROM user_autoselects WHERE user_id = {placeholder}', (user_id,))
            cursor.execute(f'DELETE FROM user_api_tokens WHERE user_id = {placeholder}', (user_id,))
            cursor.execute(f'DELETE FROM user_token_usage WHERE user_id = {placeholder}', (user_id,))
            cursor.execute(f'DELETE FROM user_notifications WHERE user_id = {placeholder}', (user_id,))
            # Delete the user
            cursor.execute(f'DELETE FROM users WHERE id = {placeholder}', (user_id,))
            conn.commit()

    def update_user(self, user_id: int, username: str, password_hash: str = None, role: str = None, is_active: bool = None, display_name: str = None):
        """
        Update a user.

        Args:
            user_id: User ID to update
            username: New username
            password_hash: New password hash (optional)
            role: New role (optional)
            is_active: New active status (optional)
            display_name: New display name (optional)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Build update query dynamically
            updates = []
            params = []
            
            updates.append(f"username = {placeholder}")
            params.append(username)
            
            if password_hash:
                updates.append(f"password_hash = {placeholder}")
                params.append(password_hash)
            
            if role:
                updates.append(f"role = {placeholder}")
                params.append(role)
            
            if is_active is not None:
                updates.append(f"is_active = {placeholder}")
                params.append(1 if is_active else 0)

            if display_name is not None:
                updates.append(f"display_name = {placeholder}")
                params.append(display_name)

            params.append(user_id)
            
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = {placeholder}"
            cursor.execute(query, params)
            conn.commit()

    def create_notification(self, user_id: int, title: str, message: str, notification_type: str = 'message') -> int:
        """Create a notification for a user. Returns the new notification id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO user_notifications (user_id, title, message, notification_type)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (user_id, title, message, notification_type))
            conn.commit()
            return cursor.lastrowid

    def get_user_notifications(self, user_id: int, limit: int = 50, unread_only: bool = False) -> List[Dict]:
        """Return notifications for a user, newest first."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            where = f'user_id = {placeholder}'
            params: list = [user_id]
            if unread_only:
                where += f' AND is_read = 0'
            cursor.execute(f'''
                SELECT id, title, message, notification_type, is_read, created_at
                FROM user_notifications
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT {placeholder}
            ''', params + [limit])
            rows = cursor.fetchall()
            return [
                {
                    'id': r[0],
                    'title': r[1],
                    'message': r[2],
                    'notification_type': r[3],
                    'is_read': bool(r[4]),
                    'created_at': str(r[5]),
                }
                for r in rows
            ]

    def get_unread_notification_count(self, user_id: int) -> int:
        """Return count of unread notifications for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT COUNT(*) FROM user_notifications
                WHERE user_id = {placeholder} AND is_read = 0
            ''', (user_id,))
            row = cursor.fetchone()
            return row[0] if row else 0

    def mark_notification_read(self, notification_id: int, user_id: int) -> bool:
        """Mark a single notification as read. Returns True if updated."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE user_notifications SET is_read = 1
                WHERE id = {placeholder} AND user_id = {placeholder}
            ''', (notification_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def mark_all_notifications_read(self, user_id: int) -> int:
        """Mark all notifications as read for a user. Returns count updated."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE user_notifications SET is_read = 1
                WHERE user_id = {placeholder} AND is_read = 0
            ''', (user_id,))
            conn.commit()
            return cursor.rowcount

    def delete_notification(self, notification_id: int, user_id: int) -> bool:
        """Delete a notification. Returns True if deleted."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_notifications
                WHERE id = {placeholder} AND user_id = {placeholder}
            ''', (notification_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def verify_user_password(self, user_id: int, password: str) -> bool:
        """
        Verify a user's plain-text password against the stored hash.

        Supports bcrypt and legacy SHA-256 hashes.

        Args:
            user_id: User ID
            password: Plain text password to verify

        Returns:
            True if password matches, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT password_hash FROM users WHERE id = {placeholder}
            ''', (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            return _verify_password(password, row[0])

    def update_user_email(self, user_id: int, new_email: str):
        """
        Update a user's email address.

        Args:
            user_id: User ID
            new_email: New email address
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET email = {placeholder}, email_verified = 0
                WHERE id = {placeholder}
            ''', (new_email, user_id))
            conn.commit()

    def update_user_profile(self, user_id: int, username: str, email: str, display_name: str = None, profile_pic: str = None):
        """
        Update user profile (username and display_name, email is read-only).

        Args:
            user_id: User ID
            username: New username
            email: Email (ignored, kept for backward compatibility)
            display_name: New display name (optional)
            profile_pic: Base64-encoded profile picture data URL (optional)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'

            fields = ['username = ' + placeholder]
            params = [username]
            if display_name is not None:
                fields.append('display_name = ' + placeholder)
                params.append(display_name)
            if profile_pic is not None:
                fields.append('profile_pic = ' + placeholder)
                params.append(profile_pic)
            params.append(user_id)

            cursor.execute(f'''
                UPDATE users SET {', '.join(fields)} WHERE id = {placeholder}
            ''', tuple(params))
            conn.commit()

    def sanitize_username(self, input_str: str) -> str:
        """
        Sanitize string to valid username format.
        
        Args:
            input_str: Input string to sanitize
            
        Returns:
            Sanitized username string (empty if invalid)
        """
        if not input_str:
            return ""
        
        # Lowercase
        result = input_str.lower()
        
        # Replace spaces with underscores
        result = result.replace(" ", "_")
        
        # Remove invalid characters (keep a-z, 0-9, -, _, .)
        import re
        result = re.sub(r'[^a-z0-9\-_.]', '', result)
        
        # Trim and ensure length
        result = result.strip("._-")
        if len(result) < 3:
            return ""
        if len(result) > 50:
            result = result[:50].rstrip("._-")
        
        return result

    def generate_username_from_display_name(self, display_name: str, email: str) -> str:
        """
        Generate clean username from display_name, fallback to email.
        
        Args:
            display_name: Display name from OAuth provider
            email: Email address for fallback
            
        Returns:
            Generated username base (not guaranteed unique)
        """
        # Try display_name first
        if display_name and display_name.strip():
            username_base = self.sanitize_username(display_name)
            if username_base:
                return username_base
        
        # Fallback to email prefix
        if email and '@' in email:
            email_prefix = email.split('@')[0]
            username_base = self.sanitize_username(email_prefix)
            if username_base:
                return username_base
        
        # Final fallback
        return "user"

    def find_unique_username(self, base_username: str) -> str:
        """
        Find a unique username, appending counter if needed.
        
        Args:
            base_username: Base username to start with
            
        Returns:
            Unique username
            
        Raises:
            ValueError: If cannot generate unique username after 100 attempts
        """
        username = base_username
        counter = 1
        
        while self.get_user_by_username(username):
            username = f"{base_username}{counter}"
            counter += 1
            if counter > 100:  # Prevent infinite loop
                raise ValueError("Could not generate unique username")
        
        return username

    # User-specific provider methods
    def save_user_provider(self, user_id: int, provider_name: str, config: Dict):
        """
        Save user-specific provider configuration.

        Args:
            user_id: User ID
            provider_name: Provider name
            config: Provider configuration dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            config_json = json.dumps(config)
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_providers (user_id, provider_id, config, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', (user_id, provider_name, config_json))
            else:  # mysql
                cursor.execute(f'''
                    INSERT INTO user_providers (user_id, provider_id, config, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE config=VALUES(config), updated_at=CURRENT_TIMESTAMP
                ''', (user_id, provider_name, config_json))
            conn.commit()

    def get_user_providers(self, user_id: int) -> List[Dict]:
        """
        Get all user-specific providers for a user.

        Args:
            user_id: User ID

        Returns:
            List of provider configurations
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT provider_id, config, created_at, updated_at
                FROM user_providers
                WHERE user_id = {placeholder}
                ORDER BY provider_id
            ''', (user_id,))

            providers = []
            for row in cursor.fetchall():
                providers.append({
                    'provider_id': row[0],
                    'user_id': user_id,
                    'config': json.loads(row[1]),
                    'created_at': row[2],
                    'updated_at': row[3]
                })
            return providers

    def get_all_user_providers(self) -> List[Dict]:
        """Get all user-specific provider configurations across all users."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, provider_id, config, created_at, updated_at
                FROM user_providers
                ORDER BY user_id, provider_id
            ''')

            providers = []
            for row in cursor.fetchall():
                providers.append({
                    'user_id': row[0],
                    'provider_id': row[1],
                    'config': json.loads(row[2]),
                    'created_at': row[3],
                    'updated_at': row[4]
                })
            return providers

    def get_user_provider(self, user_id: int, provider_name: str) -> Optional[Dict]:
        """
        Get a specific user provider configuration.

        Args:
            user_id: User ID
            provider_name: Provider name

        Returns:
            Provider configuration dict or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT config, created_at, updated_at
                FROM user_providers
                WHERE user_id = {placeholder} AND provider_id = {placeholder}
            ''', (user_id, provider_name))

            row = cursor.fetchone()
            if row:
                return {
                    'config': json.loads(row[0]),
                    'created_at': row[1],
                    'updated_at': row[2]
                }
            return None

    def delete_user_provider(self, user_id: int, provider_name: str):
        """
        Delete a user-specific provider configuration.

        Args:
            user_id: User ID
            provider_name: Provider name
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_providers
                WHERE user_id = {placeholder} AND provider_id = {placeholder}
            ''', (user_id, provider_name))
            conn.commit()

    def get_runpod_provider_state(self, provider_scope: str, owner_user_id: Optional[int], provider_id: str) -> Optional[Dict[str, Any]]:
        """Get stored RunPod runtime state for a provider."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            owner_clause = 'owner_user_id IS NULL' if owner_user_id is None else f'owner_user_id = {placeholder}'
            params = [provider_scope]
            if owner_user_id is not None:
                params.append(owner_user_id)
            params.append(provider_id)
            cursor.execute(f'''
                SELECT provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id,
                       resource_kind, status, endpoint_url, public_catalog_json, metadata,
                       last_used_at, last_status_sync_at, updated_at
                FROM runpod_provider_state
                WHERE provider_scope = {placeholder} AND {owner_clause} AND provider_id = {placeholder}
                LIMIT 1
            ''', tuple(params))
            row = cursor.fetchone()
            return self._row_to_runpod_provider_state(row)

    def save_runpod_provider_state(self, provider_scope: str, owner_user_id: Optional[int], provider_id: str, mode: str,
                                   wrapper_mode: Optional[str], resource_id: Optional[str], resource_kind: str,
                                   status: str, endpoint_url: Optional[str] = None, public_catalog_json: Optional[Any] = None,
                                   metadata: Optional[Dict[str, Any]] = None, last_used_at: Optional[Any] = None,
                                   last_status_sync_at: Optional[Any] = None) -> Dict[str, Any]:
        """Persist RunPod runtime state for a provider."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            catalog_payload = json.dumps(public_catalog_json or [])
            metadata_payload = json.dumps(metadata or {})
            sync_value = last_status_sync_at if last_status_sync_at is not None else time.time()
            used_value = last_used_at

            if owner_user_id is None:
                cursor.execute(f'''
                    UPDATE runpod_provider_state
                    SET provider_scope = {placeholder},
                        mode = {placeholder},
                        wrapper_mode = {placeholder},
                        resource_id = {placeholder},
                        resource_kind = {placeholder},
                        status = {placeholder},
                        endpoint_url = {placeholder},
                        public_catalog_json = {placeholder},
                        metadata = {placeholder},
                        last_used_at = {placeholder},
                        last_status_sync_at = {placeholder},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE provider_scope = {placeholder} AND owner_user_id IS NULL AND provider_id = {placeholder}
                ''', (
                    provider_scope, mode, wrapper_mode, resource_id, resource_kind, status,
                    endpoint_url, catalog_payload, metadata_payload, used_value, sync_value,
                    provider_scope, provider_id,
                ))
                if cursor.rowcount:
                    conn.commit()
                    return self.get_runpod_provider_state(provider_scope, owner_user_id, provider_id)

            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT INTO runpod_provider_state (
                        provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id,
                        resource_kind, status, endpoint_url, public_catalog_json, metadata,
                        last_used_at, last_status_sync_at, updated_at
                    ) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                              {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                              {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON CONFLICT(owner_user_id, provider_id) DO UPDATE SET
                        provider_scope = excluded.provider_scope,
                        mode = excluded.mode,
                        wrapper_mode = excluded.wrapper_mode,
                        resource_id = excluded.resource_id,
                        resource_kind = excluded.resource_kind,
                        status = excluded.status,
                        endpoint_url = excluded.endpoint_url,
                        public_catalog_json = excluded.public_catalog_json,
                        metadata = excluded.metadata,
                        last_used_at = excluded.last_used_at,
                        last_status_sync_at = excluded.last_status_sync_at,
                        updated_at = CURRENT_TIMESTAMP
                ''', (provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id, resource_kind,
                      status, endpoint_url, catalog_payload, metadata_payload, used_value, sync_value))
            else:
                cursor.execute(f'''
                    INSERT INTO runpod_provider_state (
                        provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id,
                        resource_kind, status, endpoint_url, public_catalog_json, metadata,
                        last_used_at, last_status_sync_at, updated_at
                    ) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                              {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                              {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                        provider_scope = VALUES(provider_scope),
                        mode = VALUES(mode),
                        wrapper_mode = VALUES(wrapper_mode),
                        resource_id = VALUES(resource_id),
                        resource_kind = VALUES(resource_kind),
                        status = VALUES(status),
                        endpoint_url = VALUES(endpoint_url),
                        public_catalog_json = VALUES(public_catalog_json),
                        metadata = VALUES(metadata),
                        last_used_at = VALUES(last_used_at),
                        last_status_sync_at = VALUES(last_status_sync_at),
                        updated_at = CURRENT_TIMESTAMP
                ''', (provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id, resource_kind,
                      status, endpoint_url, catalog_payload, metadata_payload, used_value, sync_value))
            conn.commit()
        return self.get_runpod_provider_state(provider_scope, owner_user_id, provider_id)

    def touch_runpod_provider_state(self, provider_scope: str, owner_user_id: Optional[int], provider_id: str,
                                    last_used_at: Optional[Any] = None) -> None:
        """Update last-used timestamp for a RunPod state row."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            owner_clause = 'owner_user_id IS NULL' if owner_user_id is None else f'owner_user_id = {placeholder}'
            params = [last_used_at if last_used_at is not None else time.time(), provider_scope]
            if owner_user_id is not None:
                params.append(owner_user_id)
            params.append(provider_id)
            cursor.execute(f'''
                UPDATE runpod_provider_state
                SET last_used_at = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE provider_scope = {placeholder} AND {owner_clause} AND provider_id = {placeholder}
            ''', tuple(params))
            conn.commit()

    def list_runpod_provider_states(self, provider_scope: Optional[str] = None) -> List[Dict[str, Any]]:
        """List stored RunPod runtime state rows."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if provider_scope is None:
                cursor.execute('''
                    SELECT provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id,
                           resource_kind, status, endpoint_url, public_catalog_json, metadata,
                           last_used_at, last_status_sync_at, updated_at
                    FROM runpod_provider_state
                    ORDER BY updated_at DESC
                ''')
            else:
                cursor.execute(f'''
                    SELECT provider_scope, owner_user_id, provider_id, mode, wrapper_mode, resource_id,
                           resource_kind, status, endpoint_url, public_catalog_json, metadata,
                           last_used_at, last_status_sync_at, updated_at
                    FROM runpod_provider_state
                    WHERE provider_scope = {placeholder}
                    ORDER BY updated_at DESC
                ''', (provider_scope,))
            return [state for state in (self._row_to_runpod_provider_state(row) for row in cursor.fetchall()) if state]

    def _row_to_runpod_provider_state(self, row) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        public_catalog_payload = row[9]
        metadata_payload = row[10]
        try:
            public_catalog = json.loads(public_catalog_payload) if public_catalog_payload else []
        except Exception:
            public_catalog = []
        try:
            metadata = json.loads(metadata_payload) if metadata_payload else {}
        except Exception:
            metadata = {}
        return {
            'provider_scope': row[0],
            'owner_user_id': row[1],
            'provider_id': row[2],
            'mode': row[3],
            'wrapper_mode': row[4],
            'resource_id': row[5],
            'resource_kind': row[6],
            'status': row[7],
            'endpoint_url': row[8],
            'public_catalog_json': public_catalog,
            'metadata': metadata,
            'last_used_at': row[11],
            'last_status_sync_at': row[12],
            'updated_at': row[13],
        }

    # User-specific rotation methods
    def save_user_rotation(self, user_id: int, rotation_name: str, config: Dict):
        """
        Save user-specific rotation configuration.

        Args:
            user_id: User ID
            rotation_name: Rotation name
            config: Rotation configuration dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            config_json = json.dumps(config)
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_rotations (user_id, rotation_id, config, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', (user_id, rotation_name, config_json))
            else:  # mysql
                cursor.execute(f'''
                    INSERT INTO user_rotations (user_id, rotation_id, config, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE config=VALUES(config), updated_at=CURRENT_TIMESTAMP
                ''', (user_id, rotation_name, config_json))
            conn.commit()

    def get_user_rotations(self, user_id: int) -> List[Dict]:
        """
        Get all user-specific rotations for a user.

        Args:
            user_id: User ID

        Returns:
            List of rotation configurations
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT rotation_id, config, created_at, updated_at
                FROM user_rotations
                WHERE user_id = {placeholder}
                ORDER BY rotation_id
            ''', (user_id,))

            rotations = []
            for row in cursor.fetchall():
                rotations.append({
                    'rotation_id': row[0],
                    'config': json.loads(row[1]),
                    'created_at': row[2],
                    'updated_at': row[3]
                })
            return rotations

    def get_user_rotation(self, user_id: int, rotation_name: str) -> Optional[Dict]:
        """
        Get a specific user rotation configuration.

        Args:
            user_id: User ID
            rotation_name: Rotation name

        Returns:
            Rotation configuration dict or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT config, created_at, updated_at
                FROM user_rotations
                WHERE user_id = {placeholder} AND rotation_id = {placeholder}
            ''', (user_id, rotation_name))

            row = cursor.fetchone()
            if row:
                return {
                    'config': json.loads(row[0]),
                    'created_at': row[1],
                    'updated_at': row[2]
                }
            return None

    def delete_user_rotation(self, user_id: int, rotation_name: str):
        """
        Delete a user-specific rotation configuration.

        Args:
            user_id: User ID
            rotation_name: Rotation name
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_rotations
                WHERE user_id = {placeholder} AND rotation_id = {placeholder}
            ''', (user_id, rotation_name))
            conn.commit()

    # User-specific autoselect methods
    def save_user_autoselect(self, user_id: int, autoselect_name: str, config: Dict):
        """
        Save user-specific autoselect configuration.

        Args:
            user_id: User ID
            autoselect_name: Autoselect name
            config: Autoselect configuration dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            config_json = json.dumps(config)
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_autoselects (user_id, autoselect_id, config, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', (user_id, autoselect_name, config_json))
            else:  # mysql
                cursor.execute(f'''
                    INSERT INTO user_autoselects (user_id, autoselect_id, config, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE config=VALUES(config), updated_at=CURRENT_TIMESTAMP
                ''', (user_id, autoselect_name, config_json))
            conn.commit()

    def get_user_autoselects(self, user_id: int) -> List[Dict]:
        """
        Get all user-specific autoselects for a user.

        Args:
            user_id: User ID

        Returns:
            List of autoselect configurations
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT autoselect_id, config, created_at, updated_at
                FROM user_autoselects
                WHERE user_id = {placeholder}
                ORDER BY autoselect_id
            ''', (user_id,))

            autoselects = []
            for row in cursor.fetchall():
                autoselects.append({
                    'autoselect_id': row[0],
                    'config': json.loads(row[1]),
                    'created_at': row[2],
                    'updated_at': row[3]
                })
            return autoselects

    def get_user_autoselect(self, user_id: int, autoselect_name: str) -> Optional[Dict]:
        """
        Get a specific user autoselect configuration.

        Args:
            user_id: User ID
            autoselect_name: Autoselect name

        Returns:
            Autoselect configuration dict or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT config, created_at, updated_at
                FROM user_autoselects
                WHERE user_id = {placeholder} AND autoselect_id = {placeholder}
            ''', (user_id, autoselect_name))

            row = cursor.fetchone()
            if row:
                return {
                    'config': json.loads(row[0]),
                    'created_at': row[1],
                    'updated_at': row[2]
                }
            return None

    def delete_user_autoselect(self, user_id: int, autoselect_name: str):
        """
        Delete a user-specific autoselect configuration.

        Args:
            user_id: User ID
            autoselect_name: Autoselect name
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_autoselects
                WHERE user_id = {placeholder} AND autoselect_id = {placeholder}
            ''', (user_id, autoselect_name))
            conn.commit()

    # User-specific prompt methods
    def save_user_prompt(self, user_id: int, prompt_key: str, content: str):
        """
        Save user-specific prompt override.

        Args:
            user_id: User ID
            prompt_key: Prompt identifier
            content: Prompt content
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'

            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_prompts (user_id, prompt_key, content, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', (user_id, prompt_key, content))
            else:  # mysql
                cursor.execute(f'''
                    INSERT INTO user_prompts (user_id, prompt_key, content, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE content=VALUES(content), updated_at=CURRENT_TIMESTAMP
                ''', (user_id, prompt_key, content))
            conn.commit()

    def get_user_prompt(self, user_id: int, prompt_key: str) -> Optional[str]:
        """
        Get user-specific prompt override.

        Args:
            user_id: User ID
            prompt_key: Prompt identifier

        Returns:
            Prompt content if exists, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT content
                FROM user_prompts
                WHERE user_id = {placeholder} AND prompt_key = {placeholder}
            ''', (user_id, prompt_key))

            row = cursor.fetchone()
            return row[0] if row else None

    def get_user_prompts(self, user_id: int) -> List[Dict]:
        """
        Get all user-specific prompt overrides for a user.

        Args:
            user_id: User ID

        Returns:
            List of prompt dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT prompt_key, content, created_at, updated_at
                FROM user_prompts
                WHERE user_id = {placeholder}
                ORDER BY prompt_key
            ''', (user_id,))

            prompts = []
            for row in cursor.fetchall():
                prompts.append({
                    'prompt_key': row[0],
                    'content': row[1],
                    'created_at': row[2],
                    'updated_at': row[3]
                })
            return prompts

    def delete_user_prompt(self, user_id: int, prompt_key: str):
        """
        Delete user-specific prompt override.

        Args:
            user_id: User ID
            prompt_key: Prompt identifier
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_prompts
                WHERE user_id = {placeholder} AND prompt_key = {placeholder}
            ''', (user_id, prompt_key))
            conn.commit()

    # User API token methods
    def create_user_api_token(self, user_id: int, token: str, description: str = None, scope: str = 'api') -> int:
        """
        Create a new API token for a user.

        Args:
            user_id: User ID
            token: The token string
            description: Optional description
            scope: Token scope - 'api' (proxy only), 'mcp' (MCP only), or 'both'

        Returns:
            Token ID
        """
        if scope not in ('api', 'mcp', 'both'):
            scope = 'api'
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO user_api_tokens (user_id, token, description, scope)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (user_id, token, description, scope))
            conn.commit()
            return cursor.lastrowid

    def get_user_api_tokens(self, user_id: int) -> List[Dict]:
        """
        Get all API tokens for a user.

        Args:
            user_id: User ID

        Returns:
            List of token dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, token, description, created_at, last_used, is_active,
                       COALESCE(scope, 'api') as scope
                FROM user_api_tokens
                WHERE user_id = {placeholder}
                ORDER BY created_at DESC
            ''', (user_id,))

            tokens = []
            for row in cursor.fetchall():
                tokens.append({
                    'id': row[0],
                    'token': row[1],
                    'description': row[2],
                    'created_at': row[3],
                    'last_used': row[4],
                    'is_active': row[5],
                    'scope': row[6]
                })
            return tokens

    def authenticate_user_token(self, token: str) -> Optional[Dict]:
        """
        Authenticate a user by API token.

        Args:
            token: API token string

        Returns:
            User dict if authenticated, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT u.id, u.username, u.role, t.id as token_id,
                       COALESCE(t.scope, 'api') as scope
                FROM users u
                JOIN user_api_tokens t ON u.id = t.user_id
                WHERE t.token = {placeholder} AND t.is_active = 1 AND u.is_active = 1
            ''', (token,))

            row = cursor.fetchone()
            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'role': row[2],
                    'token_id': row[3],
                    'scope': row[4]
                }
            return None

    def delete_user_api_token(self, user_id: int, token_id: int):
        """
        Delete a user API token.

        Args:
            user_id: User ID
            token_id: Token ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_api_tokens
                WHERE id = {placeholder} AND user_id = {placeholder}
            ''', (token_id, user_id))
            conn.commit()

    # User token usage methods
    def record_user_token_usage(self, user_id: int, token_id: int, provider_id: str, model_name: str, tokens_used: int):
        """
        Record token usage for a user API request.

        Args:
            user_id: User ID
            token_id: API token ID
            provider_id: Provider identifier
            model_name: Model name
            tokens_used: Number of tokens used
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO user_token_usage (user_id, token_id, provider_id, model_name, tokens_used)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (user_id, token_id, provider_id, model_name, tokens_used))

            # Update last_used timestamp for the token
            cursor.execute(f'''
                UPDATE user_api_tokens
                SET last_used = CURRENT_TIMESTAMP
                WHERE id = {placeholder}
            ''', (token_id,))

            conn.commit()

    def get_user_token_usage(self, user_id: int) -> List[Dict]:
        """
        Get token usage for a user.

        Args:
            user_id: User ID

        Returns:
            List of token usage records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT provider_id, model_name, tokens_used, timestamp
                FROM user_token_usage
                WHERE user_id = {placeholder}
                ORDER BY timestamp DESC
                LIMIT 1000
            ''', (user_id,))

            usage = []
            for row in cursor.fetchall():
                usage.append({
                    'provider_id': row[0],
                    'model_name': row[1],
                    'token_count': row[2],
                    'timestamp': row[3]
                })
            return usage
    
    # User authentication file methods
    def save_user_auth_file(self, user_id: int, provider_id: str, file_type: str,
                           original_filename: str, stored_filename: str,
                           file_path: str, file_size: int, mime_type: str = None) -> int:
        """
        Save user authentication file metadata.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier
            file_type: Type of file (e.g., 'credentials', 'database', 'config')
            original_filename: Original uploaded filename
            stored_filename: Filename stored on disk
            file_path: Full path to stored file
            file_size: File size in bytes
            mime_type: MIME type of the file
            
        Returns:
            File record ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_auth_files
                    (user_id, provider_id, file_type, original_filename, stored_filename,
                     file_path, file_size, mime_type, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder},
                            {placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', (user_id, provider_id, file_type, original_filename, stored_filename,
                      file_path, file_size, mime_type))
            else:  # mysql
                cursor.execute(f'''
                    INSERT INTO user_auth_files
                    (user_id, provider_id, file_type, original_filename, stored_filename,
                     file_path, file_size, mime_type, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder},
                            {placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                    original_filename=VALUES(original_filename), stored_filename=VALUES(stored_filename),
                    file_path=VALUES(file_path), file_size=VALUES(file_size), mime_type=VALUES(mime_type),
                    updated_at=CURRENT_TIMESTAMP
                ''', (user_id, provider_id, file_type, original_filename, stored_filename,
                      file_path, file_size, mime_type))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_user_auth_files(self, user_id: int, provider_id: str = None) -> List[Dict]:
        """
        Get all authentication files for a user.
        
        Args:
            user_id: User ID
            provider_id: Optional provider ID to filter by
            
        Returns:
            List of file metadata dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if provider_id:
                cursor.execute(f'''
                    SELECT id, provider_id, file_type, original_filename, stored_filename,
                           file_path, file_size, mime_type, created_at, updated_at
                    FROM user_auth_files
                    WHERE user_id = {placeholder} AND provider_id = {placeholder}
                    ORDER BY provider_id, file_type
                ''', (user_id, provider_id))
            else:
                cursor.execute(f'''
                    SELECT id, provider_id, file_type, original_filename, stored_filename,
                           file_path, file_size, mime_type, created_at, updated_at
                    FROM user_auth_files
                    WHERE user_id = {placeholder}
                    ORDER BY provider_id, file_type
                ''', (user_id,))
            
            files = []
            for row in cursor.fetchall():
                files.append({
                    'id': row[0],
                    'provider_id': row[1],
                    'file_type': row[2],
                    'original_filename': row[3],
                    'stored_filename': row[4],
                    'file_path': row[5],
                    'file_size': row[6],
                    'mime_type': row[7],
                    'created_at': row[8],
                    'updated_at': row[9]
                })
            return files
    
    def get_user_auth_file(self, user_id: int, provider_id: str, file_type: str) -> Optional[Dict]:
        """
        Get a specific authentication file for a user.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier
            file_type: Type of file
            
        Returns:
            File metadata dictionary or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, provider_id, file_type, original_filename, stored_filename,
                       file_path, file_size, mime_type, created_at, updated_at
                FROM user_auth_files
                WHERE user_id = {placeholder} AND provider_id = {placeholder} AND file_type = {placeholder}
            ''', (user_id, provider_id, file_type))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'provider_id': row[1],
                    'file_type': row[2],
                    'original_filename': row[3],
                    'stored_filename': row[4],
                    'file_path': row[5],
                    'file_size': row[6],
                    'mime_type': row[7],
                    'created_at': row[8],
                    'updated_at': row[9]
                }
            return None
    
    def delete_user_auth_file(self, user_id: int, provider_id: str, file_type: str) -> bool:
        """
        Delete an authentication file record.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier
            file_type: Type of file
            
        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_auth_files
                WHERE user_id = {placeholder} AND provider_id = {placeholder} AND file_type = {placeholder}
            ''', (user_id, provider_id, file_type))
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_user_auth_files_by_provider(self, user_id: int, provider_id: str) -> int:
        """
        Delete all authentication files for a provider.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier
            
        Returns:
            Number of files deleted
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM user_auth_files
                WHERE user_id = {placeholder} AND provider_id = {placeholder}
            ''', (user_id, provider_id))
            conn.commit()
            return cursor.rowcount
    
    # User OAuth2 credential methods
    def save_user_oauth2_credentials(self, user_id: int, provider_id: str, auth_type: str, credentials: Dict) -> int:
        """
        Save OAuth2 credentials for a user/provider combination.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier (e.g., 'codex', 'kilo', 'claude')
            auth_type: Auth type (e.g., 'codex_oauth2', 'kilo_oauth2', 'claude_oauth2')
            credentials: Credentials dictionary
            
        Returns:
            Record ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            credentials_json = json.dumps(credentials)
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_oauth2_credentials
                    (user_id, provider_id, auth_type, credentials, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', (user_id, provider_id, auth_type, credentials_json))
            else:
                cursor.execute(f'''
                    INSERT INTO user_oauth2_credentials
                    (user_id, provider_id, auth_type, credentials, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                    credentials=VALUES(credentials), updated_at=CURRENT_TIMESTAMP
                ''', (user_id, provider_id, auth_type, credentials_json))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_user_oauth2_credentials(self, user_id: int, provider_id: str, auth_type: str = None) -> Optional[Dict]:
        """
        Get OAuth2 credentials for a user/provider combination.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier
            auth_type: Optional auth type filter
            
        Returns:
            Credentials dictionary or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if auth_type:
                cursor.execute(f'''
                    SELECT id, auth_type, credentials, created_at, updated_at
                    FROM user_oauth2_credentials
                    WHERE user_id = {placeholder} AND provider_id = {placeholder} AND auth_type = {placeholder}
                ''', (user_id, provider_id, auth_type))
            else:
                cursor.execute(f'''
                    SELECT id, auth_type, credentials, created_at, updated_at
                    FROM user_oauth2_credentials
                    WHERE user_id = {placeholder} AND provider_id = {placeholder}
                    ORDER BY updated_at DESC
                    LIMIT 1
                ''', (user_id, provider_id))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'auth_type': row[1],
                    'credentials': json.loads(row[2]),
                    'created_at': row[3],
                    'updated_at': row[4]
                }
            return None
    
    def get_all_user_oauth2_credentials(self, user_id: int) -> List[Dict]:
        """
        Get all OAuth2 credentials for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of credential dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            cursor.execute(f'''
                SELECT id, provider_id, auth_type, credentials, created_at, updated_at
                FROM user_oauth2_credentials
                WHERE user_id = {placeholder}
                ORDER BY provider_id, auth_type
            ''', (user_id,))
            
            credentials = []
            for row in cursor.fetchall():
                credentials.append({
                    'id': row[0],
                    'provider_id': row[1],
                    'auth_type': row[2],
                    'credentials': json.loads(row[3]),
                    'created_at': row[4],
                    'updated_at': row[5]
                })
            return credentials
    
    def delete_user_oauth2_credentials(self, user_id: int, provider_id: str, auth_type: str = None) -> int:
        """
        Delete OAuth2 credentials for a user/provider combination.
        
        Args:
            user_id: User ID
            provider_id: Provider identifier
            auth_type: Optional auth type filter (if None, deletes all for provider)
            
        Returns:
            Number of records deleted
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            if auth_type:
                cursor.execute(f'''
                    DELETE FROM user_oauth2_credentials
                    WHERE user_id = {placeholder} AND provider_id = {placeholder} AND auth_type = {placeholder}
                ''', (user_id, provider_id, auth_type))
            else:
                cursor.execute(f'''
                    DELETE FROM user_oauth2_credentials
                    WHERE user_id = {placeholder} AND provider_id = {placeholder}
                ''', (user_id, provider_id))
            
            conn.commit()
            return cursor.rowcount

    # Provider Usage methods
    def get_provider_usage(self, user_id, provider_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if user_id is None:
                cursor.execute(f'''
                    SELECT usage_data, last_updated FROM user_provider_usage
                    WHERE user_id IS NULL AND provider_id = {placeholder}
                ''', (provider_id,))
            else:
                cursor.execute(f'''
                    SELECT usage_data, last_updated FROM user_provider_usage
                    WHERE user_id = {placeholder} AND provider_id = {placeholder}
                ''', (user_id, provider_id))
            row = cursor.fetchone()
            if row:
                return {'usage_data': json.loads(row[0]), 'last_updated': row[1]}
            return None

    def save_provider_usage(self, user_id, provider_id: str, usage_data: Dict):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            timestamp_default = 'CURRENT_TIMESTAMP'
            data_json = json.dumps(usage_data)
            if user_id is None:
                # Admin: delete-then-insert to handle NULL in UNIQUE constraint
                cursor.execute(f'DELETE FROM user_provider_usage WHERE user_id IS NULL AND provider_id = {placeholder}', (provider_id,))
                cursor.execute(f'INSERT INTO user_provider_usage (user_id, provider_id, usage_data, last_updated) VALUES (NULL, {placeholder}, {placeholder}, {timestamp_default})', (provider_id, data_json))
            elif self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO user_provider_usage (user_id, provider_id, usage_data, last_updated)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {timestamp_default})
                ''', (user_id, provider_id, data_json))
            else:
                cursor.execute(f'''
                    INSERT INTO user_provider_usage (user_id, provider_id, usage_data, last_updated)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {timestamp_default})
                    ON DUPLICATE KEY UPDATE usage_data=VALUES(usage_data), last_updated=CURRENT_TIMESTAMP
                ''', (user_id, provider_id, data_json))
            conn.commit()

    # Provider Disabled State methods
    def get_provider_disabled_until(self, user_id, provider_id: str) -> Optional[float]:
        """Return the disabled_until Unix timestamp for a provider, or None if not disabled."""
        import time as _time
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if user_id is None:
                cursor.execute(f'''
                    SELECT disabled_until FROM provider_disabled_state
                    WHERE user_id IS NULL AND provider_id = {placeholder}
                ''', (provider_id,))
            else:
                cursor.execute(f'''
                    SELECT disabled_until FROM provider_disabled_state
                    WHERE user_id = {placeholder} AND provider_id = {placeholder}
                ''', (user_id, provider_id))
            row = cursor.fetchone()
            if row and row[0] is not None:
                ts = float(row[0])
                if ts > _time.time():
                    return ts
                # Expired — clean it up
                try:
                    self.clear_provider_disabled_until(user_id, provider_id)
                except Exception:
                    pass
        return None

    def set_provider_disabled_until(self, user_id, provider_id: str, disabled_until: float, reason: str = None):
        """Persist a usage-based disabled_until timestamp for a provider."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if user_id is None:
                cursor.execute(f'DELETE FROM provider_disabled_state WHERE user_id IS NULL AND provider_id = {placeholder}', (provider_id,))
                cursor.execute(f'''
                    INSERT INTO provider_disabled_state (user_id, provider_id, disabled_until, disable_reason)
                    VALUES (NULL, {placeholder}, {placeholder}, {placeholder})
                ''', (provider_id, disabled_until, reason))
            elif self.db_type == 'sqlite':
                cursor.execute(f'''
                    INSERT OR REPLACE INTO provider_disabled_state (user_id, provider_id, disabled_until, disable_reason)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
                ''', (user_id, provider_id, disabled_until, reason))
            else:
                cursor.execute(f'''
                    INSERT INTO provider_disabled_state (user_id, provider_id, disabled_until, disable_reason)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
                    ON DUPLICATE KEY UPDATE disabled_until=VALUES(disabled_until), disable_reason=VALUES(disable_reason), updated_at=CURRENT_TIMESTAMP
                ''', (user_id, provider_id, disabled_until, reason))
            conn.commit()

    def clear_provider_disabled_until(self, user_id, provider_id: str):
        """Clear a provider's usage-based disabled state."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if user_id is None:
                cursor.execute(f'DELETE FROM provider_disabled_state WHERE user_id IS NULL AND provider_id = {placeholder}', (provider_id,))
            else:
                cursor.execute(f'DELETE FROM provider_disabled_state WHERE user_id = {placeholder} AND provider_id = {placeholder}', (user_id, provider_id))
            conn.commit()

    # Sort order methods

    def get_sort_order(self, user_id, entity_type: str) -> Optional[List[str]]:
        """Return the saved sort order for provider/rotation/autoselect lists, or None."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if user_id is None:
                cursor.execute(
                    f'SELECT ordered_ids FROM user_sort_order WHERE user_id IS NULL AND entity_type = {placeholder}',
                    (entity_type,)
                )
            else:
                cursor.execute(
                    f'SELECT ordered_ids FROM user_sort_order WHERE user_id = {placeholder} AND entity_type = {placeholder}',
                    (user_id, entity_type)
                )
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except Exception:
                    return None
            return None

    def set_sort_order(self, user_id, entity_type: str, ordered_ids: List[str]):
        """Persist the sort order for provider/rotation/autoselect lists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            data_json = json.dumps(ordered_ids)
            if self.db_type == 'sqlite':
                # SQLite: use DELETE+INSERT (no UNIQUE constraint due to NULL handling)
                if user_id is None:
                    cursor.execute(
                        f'DELETE FROM user_sort_order WHERE user_id IS NULL AND entity_type = {placeholder}',
                        (entity_type,)
                    )
                    cursor.execute(
                        f'INSERT INTO user_sort_order (user_id, entity_type, ordered_ids) VALUES (NULL, {placeholder}, {placeholder})',
                        (entity_type, data_json)
                    )
                else:
                    cursor.execute(
                        f'DELETE FROM user_sort_order WHERE user_id = {placeholder} AND entity_type = {placeholder}',
                        (user_id, entity_type)
                    )
                    cursor.execute(
                        f'INSERT INTO user_sort_order (user_id, entity_type, ordered_ids) VALUES ({placeholder}, {placeholder}, {placeholder})',
                        (user_id, entity_type, data_json)
                    )
            else:
                # MySQL: UNIQUE(user_id, entity_type) + ON DUPLICATE KEY UPDATE
                cursor.execute(
                    f'INSERT INTO user_sort_order (user_id, entity_type, ordered_ids) VALUES ({placeholder}, {placeholder}, {placeholder}) '
                    f'ON DUPLICATE KEY UPDATE ordered_ids = {placeholder}',
                    (user_id, entity_type, data_json, data_json)
                )
            conn.commit()

    # Account Tier methods
    def get_all_tiers(self) -> List[Dict]:
        """
        Get all account tiers.
        
        Returns:
            List of tier dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, description, price_monthly, price_yearly, is_default, is_active,
                       max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                       max_autoselections, max_rotation_models, max_autoselection_models,
                       created_at, updated_at, is_visible, market_fee_percentage
                FROM account_tiers
                ORDER BY price_monthly ASC
            ''')
            
            tiers = []
            for row in cursor.fetchall():
                tiers.append({
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'price_monthly': float(row[3]),
                    'price_yearly': float(row[4]),
                    'is_default': bool(row[5]),
                    'is_active': bool(row[6]),
                    'max_requests_per_day': row[7],
                    'max_requests_per_month': row[8],
                    'max_providers': row[9],
                    'max_rotations': row[10],
                    'max_autoselections': row[11],
                    'max_rotation_models': row[12],
                    'max_autoselection_models': row[13],
                    'created_at': row[14],
                    'updated_at': row[15],
                    'is_visible': bool(row[16]) if len(row) > 16 else True,
                    'market_fee_percentage': float(row[17] or 10.0) if len(row) > 17 else 10.0,
                })
            return tiers
    
    def get_tier_by_id(self, tier_id: int) -> Optional[Dict]:
        """
        Get a specific tier by ID.
        
        Args:
            tier_id: Tier ID
            
        Returns:
            Tier dictionary or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, name, description, price_monthly, price_yearly, is_default, is_active,
                       max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                       max_autoselections, max_rotation_models, max_autoselection_models,
                       created_at, updated_at, is_visible, market_fee_percentage
                FROM account_tiers
                WHERE id = {placeholder}
            ''', (tier_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'price_monthly': float(row[3]),
                    'price_yearly': float(row[4]),
                    'is_default': bool(row[5]),
                    'is_active': bool(row[6]),
                    'max_requests_per_day': row[7],
                    'max_requests_per_month': row[8],
                    'max_providers': row[9],
                    'max_rotations': row[10],
                    'max_autoselections': row[11],
                    'max_rotation_models': row[12],
                    'max_autoselection_models': row[13],
                    'created_at': row[14],
                    'updated_at': row[15],
                    'is_visible': bool(row[16]) if len(row) > 16 else True,
                    'market_fee_percentage': float(row[17] or 10.0) if len(row) > 17 else 10.0,
                }
            return None
    
    def create_tier(self, name: str, description: str, price_monthly: float, price_yearly: float,
                    max_requests_per_day: int = -1, max_requests_per_month: int = -1,
                    max_providers: int = -1, max_rotations: int = -1,
                    max_autoselections: int = -1, max_rotation_models: int = -1,
                    max_autoselection_models: int = -1, market_fee_percentage: float = 10.0,
                    is_active: bool = True, is_visible: bool = True) -> int:
        """
        Create a new account tier.
        
        Args:
            name: Tier name
            description: Tier description
            price_monthly: Monthly price
            price_yearly: Yearly price
            max_requests_per_day: Max requests per day (-1 for unlimited)
            max_requests_per_month: Max requests per month (-1 for unlimited)
            max_providers: Max providers allowed (-1 for unlimited)
            max_rotations: Max rotations allowed (-1 for unlimited)
            max_autoselections: Max autoselections allowed (-1 for unlimited)
            max_rotation_models: Max models per rotation (-1 for unlimited)
            max_autoselection_models: Max models per autoselection (-1 for unlimited)
            is_active: Whether tier is active
            is_visible: Whether tier is visible to users (default True)
            
        Returns:
            Created tier ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO account_tiers
                (name, description, price_monthly, price_yearly, is_active, is_visible,
                  max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                  max_autoselections, max_rotation_models, max_autoselection_models, market_fee_percentage)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder},
                        {placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (name, description, price_monthly, price_yearly, 1 if is_active else 0, 1 if is_visible else 0,
                  max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                  max_autoselections, max_rotation_models, max_autoselection_models, market_fee_percentage))
            conn.commit()
            return cursor.lastrowid
    
    def update_tier(self, tier_id: int, **kwargs) -> bool:
        """
        Update an existing tier.
        
        Args:
            tier_id: Tier ID
            **kwargs: Fields to update
            
        Returns:
            True if updated, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            updates = []
            params = []
            
            allowed_fields = ['name', 'description', 'price_monthly', 'price_yearly', 'is_active', 'is_visible',
                              'max_requests_per_day', 'max_requests_per_month', 'max_providers',
                              'max_rotations', 'max_autoselections', 'max_rotation_models',
                              'max_autoselection_models', 'market_fee_percentage']
            
            for field in allowed_fields:
                if field in kwargs:
                    updates.append(f"{field} = {placeholder}")
                    params.append(kwargs[field])
            
            if not updates:
                return False
            
            params.append(tier_id)
            query = f"UPDATE account_tiers SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = {placeholder}"
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_tier(self, tier_id: int) -> bool:
        """
        Delete a tier (cannot delete default tier).
        
        Args:
            tier_id: Tier ID
            
        Returns:
            True if deleted, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Prevent deleting default tier
            cursor.execute(f'''
                DELETE FROM account_tiers
                WHERE id = {placeholder} AND is_default = 0
            ''', (tier_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_market_fee_percentage_for_user(self, user_id: int) -> float:
        tier = self.get_user_tier(user_id)
        if not tier:
            tiers = self.get_all_tiers()
            default_tier = next((t for t in tiers if t.get('is_default')), None)
            if default_tier:
                return float(default_tier.get('market_fee_percentage', 10.0) or 10.0)
            return 10.0
        return float(tier.get('market_fee_percentage', 10.0) or 10.0)

    def upsert_market_listing(self, owner_user_id: int, owner_username: str, payload: Dict[str, Any]) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            metadata_json = json.dumps(payload.get('metadata') or {})
            snapshot_json = json.dumps(self._sanitize_market_config(payload.get('config_snapshot') or {}))
            listing_key = payload['listing_key']
            existing = None
            cursor.execute(
                f'''SELECT id FROM market_listings WHERE owner_user_id = {placeholder} AND listing_key = {placeholder}''',
                (owner_user_id, listing_key)
            )
            existing = cursor.fetchone()

            values = (
                owner_user_id,
                owner_username,
                payload.get('source_scope', 'user'),
                payload['source_type'],
                payload['source_id'],
                listing_key,
                payload['title'],
                payload.get('description'),
                payload.get('provider_id'),
                payload.get('model_id'),
                payload.get('endpoint'),
                payload.get('currency_code', 'USD'),
                float(payload.get('price_per_million_tokens', 0) or 0),
                metadata_json,
                snapshot_json,
                float(payload.get('price_per_1000_requests', 0) or 0),
                payload.get('provider_price_per_million_tokens'),
                payload.get('provider_price_per_1000_requests'),
                1 if payload.get('is_active', True) else 0,
            )

            if existing:
                cursor.execute(
                    f'''
                    UPDATE market_listings
                    SET owner_username = {placeholder},
                        source_scope = {placeholder},
                        source_type = {placeholder},
                        source_id = {placeholder},
                        title = {placeholder},
                        description = {placeholder},
                        provider_id = {placeholder},
                        model_id = {placeholder},
                        endpoint = {placeholder},
                        currency_code = {placeholder},
                        price_per_million_tokens = {placeholder},
                        metadata = {placeholder},
                        config_snapshot = {placeholder},
                        price_per_1000_requests = {placeholder},
                        provider_price_per_million_tokens = {placeholder},
                        provider_price_per_1000_requests = {placeholder},
                        is_active = {placeholder},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = {placeholder}
                    ''',
                    values[1:] + (existing[0],)
                )
                conn.commit()
                return existing[0]

            cursor.execute(
                f'''
                INSERT INTO market_listings (
                    owner_user_id, owner_username, source_scope, source_type, source_id, listing_key,
                    title, description, provider_id, model_id, endpoint, currency_code,
                    price_per_million_tokens, metadata, config_snapshot, price_per_1000_requests,
                    provider_price_per_million_tokens, provider_price_per_1000_requests, is_active,
                    created_at, updated_at
                ) VALUES (
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ''',
                values
            )
            conn.commit()
            return cursor.lastrowid

    def list_market_listings(self, active_only: bool = True) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT id, owner_user_id, owner_username, source_scope, source_type, source_id, listing_key,
                       title, description, provider_id, model_id, endpoint, currency_code,
                       price_per_million_tokens, metadata, config_snapshot, price_per_1000_requests,
                       provider_price_per_million_tokens, provider_price_per_1000_requests, is_active,
                       created_at, updated_at
                FROM market_listings
            '''
            if active_only:
                query += ' WHERE is_active = 1'
            query += ' ORDER BY created_at DESC'
            cursor.execute(query)
            return [self._load_market_listing_row(row) for row in cursor.fetchall()]

    def list_market_listings_paginated(
        self,
        page: int = 1,
        limit: int = 25,
        search: Optional[str] = None,
        source_type: Optional[str] = None,
        active_filter: Optional[str] = None,
        online_filter: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> Dict[str, Any]:
        page = max(int(page or 1), 1)
        limit = max(1, min(int(limit or 25), 100))
        offset = (page - 1) * limit

        where_clauses = []
        params: List[Any] = []
        placeholder = self.placeholder

        if search:
            like = f"%{search.strip()}%"
            where_clauses.append(
                f"(title LIKE {placeholder} OR description LIKE {placeholder} OR source_id LIKE {placeholder} OR provider_id LIKE {placeholder} OR model_id LIKE {placeholder} OR owner_username LIKE {placeholder})"
            )
            params.extend([like, like, like, like, like, like])

        if source_type:
            where_clauses.append(f"source_type = {placeholder}")
            params.append(source_type)

        if owner_username:
            where_clauses.append(f"owner_username = {placeholder}")
            params.append(owner_username)

        if active_filter == 'active':
            where_clauses.append("is_active = 1")
        elif active_filter == 'inactive':
            where_clauses.append("is_active = 0")

        if online_filter == 'online':
            where_clauses.append("provider_id IS NOT NULL")
        elif online_filter == 'offline':
            where_clauses.append("provider_id IS NULL")

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM market_listings{where_sql}", tuple(params))
            total_row = cursor.fetchone()
            total = int(total_row[0] if total_row else 0)

            query = f'''
                SELECT id, owner_user_id, owner_username, source_scope, source_type, source_id, listing_key,
                       title, description, provider_id, model_id, endpoint, currency_code,
                       price_per_million_tokens, metadata, config_snapshot, price_per_1000_requests,
                       provider_price_per_million_tokens, provider_price_per_1000_requests, is_active,
                       created_at, updated_at
                FROM market_listings
                {where_sql}
                ORDER BY created_at DESC
                LIMIT {placeholder} OFFSET {placeholder}
            '''
            cursor.execute(query, tuple(params + [limit, offset]))
            items = [self._load_market_listing_row(row) for row in cursor.fetchall()]
            return {
                'items': items,
                'total': total,
                'page': page,
                'limit': limit,
            }

    def get_market_listing(self, listing_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                SELECT id, owner_user_id, owner_username, source_scope, source_type, source_id, listing_key,
                       title, description, provider_id, model_id, endpoint, currency_code,
                       price_per_million_tokens, metadata, config_snapshot, price_per_1000_requests,
                       provider_price_per_million_tokens, provider_price_per_1000_requests, is_active,
                       created_at, updated_at
                FROM market_listings
                WHERE id = {placeholder}
                ''',
                (listing_id,)
            )
            row = cursor.fetchone()
            return self._load_market_listing_row(row) if row else None

    def set_market_listing_active(self, listing_id: int, owner_user_id: int, is_active: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''UPDATE market_listings SET is_active = {placeholder}, updated_at = CURRENT_TIMESTAMP WHERE id = {placeholder} AND owner_user_id = {placeholder}''',
                (1 if is_active else 0, listing_id, owner_user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def admin_set_market_listing_active(self, listing_id: int, is_active: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''UPDATE market_listings SET is_active = {placeholder}, updated_at = CURRENT_TIMESTAMP WHERE id = {placeholder}''',
                (1 if is_active else 0, listing_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def upsert_market_vote(self, listing_id: int, voter_user_id: int, target_type: str, target_key: str, vote: int) -> bool:
        vote = 1 if int(vote) > 0 else -1
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''SELECT id FROM market_votes WHERE listing_id = {placeholder} AND voter_user_id = {placeholder} AND target_type = {placeholder} AND target_key = {placeholder}''',
                (listing_id, voter_user_id, target_type, target_key)
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    f'''UPDATE market_votes SET vote = {placeholder}, updated_at = CURRENT_TIMESTAMP WHERE id = {placeholder}''',
                    (vote, row[0])
                )
            else:
                cursor.execute(
                    f'''
                    INSERT INTO market_votes (listing_id, voter_user_id, target_type, target_key, vote, created_at, updated_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ''',
                    (listing_id, voter_user_id, target_type, target_key, vote)
                )
            conn.commit()
            return True

    def get_market_vote_summary(self, listing_id: int) -> Dict[str, Dict[str, int]]:
        summary = {
            'listing': {'upvotes': 0, 'downvotes': 0, 'score': 0},
            'provider': {'upvotes': 0, 'downvotes': 0, 'score': 0},
            'model': {'upvotes': 0, 'downvotes': 0, 'score': 0},
            'user': {'upvotes': 0, 'downvotes': 0, 'score': 0},
        }
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                SELECT target_type,
                       SUM(CASE WHEN vote > 0 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN vote < 0 THEN 1 ELSE 0 END),
                       COALESCE(SUM(vote), 0)
                FROM market_votes
                WHERE listing_id = {placeholder}
                GROUP BY target_type
                ''',
                (listing_id,)
            )
            for row in cursor.fetchall():
                target_type = row[0]
                if target_type in summary:
                    summary[target_type] = {
                        'upvotes': int(row[1] or 0),
                        'downvotes': int(row[2] or 0),
                        'score': int(row[3] or 0),
                    }
        return summary

    def list_market_imports(self, user_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                SELECT i.id, i.listing_id, i.imported_config_type, i.imported_config_id, i.created_at,
                       l.title, l.owner_username
                FROM market_imports i
                JOIN market_listings l ON l.id = i.listing_id
                WHERE i.user_id = {placeholder}
                ORDER BY i.created_at DESC
                ''',
                (user_id,)
            )
            return [
                {
                    'id': row[0],
                    'listing_id': row[1],
                    'imported_config_type': row[2],
                    'imported_config_id': row[3],
                    'created_at': row[4],
                    'title': row[5],
                    'owner_username': row[6],
                }
                for row in cursor.fetchall()
            ]

    def record_market_import(self, user_id: int, listing_id: int, imported_config_type: str, imported_config_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                INSERT INTO market_imports (user_id, listing_id, imported_config_type, imported_config_id, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''',
                (user_id, listing_id, imported_config_type, imported_config_id)
            )
            conn.commit()
            return cursor.lastrowid

    def get_market_listing_for_share(self, owner_username: str, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                SELECT id, owner_user_id, owner_username, source_scope, source_type, source_id, listing_key,
                       title, description, provider_id, model_id, endpoint, currency_code,
                       price_per_million_tokens, metadata, config_snapshot, price_per_1000_requests,
                       provider_price_per_million_tokens, provider_price_per_1000_requests, is_active,
                       created_at, updated_at
                FROM market_listings
                WHERE owner_username = {placeholder} AND source_type = {placeholder} AND source_id = {placeholder} AND is_active = 1
                ''',
                (owner_username, resource_type, resource_id)
            )
            row = cursor.fetchone()
            return self._load_market_listing_row(row) if row else None

    def get_market_listing_stats(self, listing_id: int) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                SELECT COUNT(*),
                       COALESCE(SUM(total_tokens), 0),
                       COALESCE(SUM(requests_count), 0),
                       COALESCE(SUM(gross_amount), 0),
                       COALESCE(SUM(platform_fee), 0),
                       COALESCE(SUM(provider_amount), 0),
                       COALESCE(AVG(total_tokens), 0),
                       COUNT(settlement_key)
                FROM market_usage_transactions
                WHERE listing_id = {placeholder}
                ''',
                (listing_id,)
            )
            row = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0)
            return {
                'usage_events': int(row[0] or 0),
                'total_tokens': int(row[1] or 0),
                'total_requests': int(row[2] or 0),
                'gross_revenue': float(row[3] or 0),
                'platform_fees': float(row[4] or 0),
                'provider_revenue': float(row[5] or 0),
                'avg_tokens_per_request': float(row[6] or 0),
                'settled_requests': int(row[7] or 0),
            }

    def _get_market_usage_transaction_by_settlement_key(self, settlement_key: Optional[str]) -> Optional[Dict[str, Any]]:
        if not settlement_key:
            return None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(
                f'''
                SELECT gross_amount, platform_fee, provider_amount, currency_code, metadata
                FROM market_usage_transactions
                WHERE settlement_key = {placeholder}
                ''',
                (settlement_key,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            metadata = {}
            try:
                metadata = json.loads(row[4]) if row[4] else {}
            except Exception:
                metadata = {}
            return {
                'gross_amount': Decimal(str(row[0] or 0)),
                'platform_fee': Decimal(str(row[1] or 0)),
                'provider_amount': Decimal(str(row[2] or 0)),
                'currency_code': row[3],
                'metadata': metadata,
            }

    def settle_market_usage(
        self,
        consumer_user_id: int,
        listing_id: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        requests_count: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        listing = self.get_market_listing(listing_id)
        if not listing or not listing.get('is_active'):
            raise ValueError('Market listing not available')
        settlement_cache_key = self._market_cache_key(consumer_user_id, listing_id, metadata)
        if settlement_cache_key:
            metadata = {**metadata, 'market_settlement_key': settlement_cache_key}
        if listing['owner_user_id'] == consumer_user_id:
            return {
                'charged_amount': Decimal('0.00'),
                'seller_amount': Decimal('0.00'),
                'platform_fee': Decimal('0.00'),
                'platform_revenue': Decimal('0.00'),
                'balance_after': None,
                'listing': listing,
                'self_use': True,
                'charged': False,
            }

        total_tokens = max(int(prompt_tokens or 0) + int(completion_tokens or 0), 0)
        request_units = Decimal(str(max(int(requests_count or 0), 0))) / Decimal('1000')
        token_units = Decimal(str(total_tokens)) / Decimal('1000000')
        token_price = Decimal(str(listing.get('price_per_million_tokens') or 0))
        request_price = Decimal(str(listing.get('price_per_1000_requests') or 0))
        gross_amount = self._quantize_money((token_units * token_price) + (request_units * request_price))
        if gross_amount <= Decimal('0.00'):
            return {
                'charged_amount': Decimal('0.00'),
                'seller_amount': Decimal('0.00'),
                'platform_fee': Decimal('0.00'),
                'platform_revenue': Decimal('0.00'),
                'balance_after': None,
                'listing': listing,
                'self_use': False,
                'charged': False,
            }

        owner_user_id = int(listing.get('owner_user_id') or 0)
        is_platform_owned_listing = owner_user_id <= 0
        fee_percentage = Decimal(str(self.get_market_fee_percentage_for_user(owner_user_id))) if owner_user_id > 0 else Decimal('0')
        platform_fee = self._quantize_money((gross_amount * fee_percentage) / Decimal('100')) if owner_user_id > 0 else Decimal('0.00')
        seller_amount = self._quantize_money(gross_amount - platform_fee) if owner_user_id > 0 else Decimal('0.00')
        platform_revenue = self._quantize_money(gross_amount if is_platform_owned_listing else platform_fee)

        def _build_deduplicated_result(existing_txn: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            balance_after = self.get_wallet_summary(consumer_user_id)
            gross = Decimal(str((existing_txn or {}).get('gross_amount', 0) or 0))
            fee = Decimal(str((existing_txn or {}).get('platform_fee', 0) or 0))
            seller = Decimal(str((existing_txn or {}).get('provider_amount', 0) or 0))
            return {
                'charged_amount': gross,
                'seller_amount': seller,
                'platform_fee': fee,
                'platform_revenue': gross if is_platform_owned_listing else fee,
                'balance_after': self._quantize_money((balance_after or {}).get('balance', 0)) if balance_after else None,
                'listing': listing,
                'self_use': False,
                'charged': False,
                'deduplicated': True,
            }

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder

            if settlement_cache_key:
                existing_txn = self._get_market_usage_transaction_by_settlement_key(settlement_cache_key)
                if existing_txn:
                    return _build_deduplicated_result(existing_txn)

            if self.db_type == 'mysql':
                cursor.execute(f'''SELECT id, balance FROM user_wallets WHERE user_id = {placeholder} FOR UPDATE''', (consumer_user_id,))
            else:
                cursor.execute(f'''SELECT id, balance FROM user_wallets WHERE user_id = {placeholder}''', (consumer_user_id,))
            consumer_wallet = cursor.fetchone()
            if not consumer_wallet:
                cursor.execute(
                    f'''INSERT INTO user_wallets (user_id, balance, currency_code, created_at, updated_at) VALUES ({placeholder}, 0.00, {placeholder}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                    (consumer_user_id, listing.get('currency_code', 'USD'))
                )
                consumer_wallet_id = cursor.lastrowid
                consumer_balance = Decimal('0.00')
            else:
                consumer_wallet_id = consumer_wallet[0]
                consumer_balance = Decimal(str(consumer_wallet[1] or 0))

            if consumer_balance < gross_amount:
                raise ValueError('Insufficient wallet balance')

            consumer_currency = None if not consumer_wallet else (self.get_wallet_summary(consumer_user_id) or {}).get('currency_code')
            if consumer_currency and consumer_currency != listing.get('currency_code', 'USD'):
                raise ValueError('Consumer wallet currency does not match listing currency')

            owner_wallet_id = None
            owner_balance = Decimal('0.00')
            if owner_user_id > 0:
                if self.db_type == 'mysql':
                    cursor.execute(f'''SELECT id, balance FROM user_wallets WHERE user_id = {placeholder} FOR UPDATE''', (owner_user_id,))
                else:
                    cursor.execute(f'''SELECT id, balance FROM user_wallets WHERE user_id = {placeholder}''', (owner_user_id,))
                owner_wallet = cursor.fetchone()
                if not owner_wallet:
                    cursor.execute(
                        f'''INSERT INTO user_wallets (user_id, balance, currency_code, created_at, updated_at) VALUES ({placeholder}, 0.00, {placeholder}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                        (owner_user_id, listing.get('currency_code', 'USD'))
                    )
                    owner_wallet_id = cursor.lastrowid
                else:
                    owner_wallet_id = owner_wallet[0]
                    owner_balance = Decimal(str(owner_wallet[1] or 0))

            new_consumer_balance = self._quantize_money(consumer_balance - gross_amount)
            new_owner_balance = self._quantize_money(owner_balance + seller_amount)

            cursor.execute(
                f'''UPDATE user_wallets SET balance = {placeholder}, updated_at = CURRENT_TIMESTAMP WHERE id = {placeholder}''',
                (float(new_consumer_balance), consumer_wallet_id)
            )
            if owner_wallet_id is not None:
                cursor.execute(
                    f'''UPDATE user_wallets SET balance = {placeholder}, updated_at = CURRENT_TIMESTAMP WHERE id = {placeholder}''',
                    (float(new_owner_balance), owner_wallet_id)
                )

            listing_meta = {
                'listing_id': listing_id,
                'provider_id': listing.get('provider_id'),
                'model_id': listing.get('model_id'),
                'market': True,
                **metadata,
            }

            cursor.execute(
                f'''
                INSERT INTO wallet_transactions
                (user_id, wallet_id, amount, type, status, description, metadata, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder}, 'debit', 'completed', {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''',
                (
                    consumer_user_id,
                    consumer_wallet_id,
                    float(gross_amount),
                    f"Market usage: {listing['title']}",
                    json.dumps(listing_meta),
                )
            )
            if owner_wallet_id is not None:
                cursor.execute(
                    f'''
                    INSERT INTO wallet_transactions
                    (user_id, wallet_id, amount, type, status, description, metadata, created_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, 'credit', 'completed', {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ''',
                    (
                        owner_user_id,
                        owner_wallet_id,
                        float(seller_amount),
                        f"Market sale: {listing['title']}",
                        json.dumps({**listing_meta, 'platform_fee': float(platform_fee), 'platform_revenue': float(platform_revenue)}),
                    )
                )
            try:
                cursor.execute(
                    f'''
                    INSERT INTO market_usage_transactions
                    (listing_id, consumer_user_id, provider_user_id, prompt_tokens, completion_tokens, total_tokens,
                     requests_count, gross_amount, platform_fee, provider_amount, currency_code, settlement_key, metadata, created_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                            {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ''',
                    (
                        listing_id,
                        consumer_user_id,
                        owner_user_id,
                        int(prompt_tokens or 0),
                        int(completion_tokens or 0),
                        total_tokens,
                        int(requests_count or 0),
                        float(gross_amount),
                        float(platform_fee),
                        float(seller_amount),
                        listing.get('currency_code', 'USD'),
                        settlement_cache_key,
                        json.dumps({**listing_meta, 'platform_fee': float(platform_fee), 'platform_revenue': float(platform_revenue), 'platform_owned_listing': is_platform_owned_listing}),
                    )
                )
            except Exception as exc:
                if settlement_cache_key:
                    duplicate_error = 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower() or 'constraint' in str(exc).lower()
                    if duplicate_error:
                        conn.rollback()
                        existing_txn = self._get_market_usage_transaction_by_settlement_key(settlement_cache_key)
                        if existing_txn:
                            return _build_deduplicated_result(existing_txn)
                raise
            conn.commit()

        return {
            'charged_amount': gross_amount,
            'seller_amount': seller_amount if owner_wallet_id is not None else Decimal('0.00'),
            'platform_fee': platform_fee,
            'platform_revenue': platform_revenue,
            'balance_after': new_consumer_balance,
            'listing': listing,
            'self_use': False,
            'charged': True,
        }

    def get_wallet_summary(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = self.placeholder
            cursor.execute(f'''SELECT id, balance, currency_code FROM user_wallets WHERE user_id = {placeholder}''', (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {'id': row[0], 'balance': float(row[1] or 0), 'currency_code': row[2]}
    
    def get_user_tier(self, user_id: int) -> Optional[Dict]:
        """
        Get the current tier for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Tier dictionary or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT t.id, t.name, t.description, t.price_monthly, t.price_yearly,
                       t.max_requests_per_day, t.max_requests_per_month, t.max_providers,
                       t.max_rotations, t.max_autoselections, t.max_rotation_models,
                       t.max_autoselection_models, t.market_fee_percentage, t.is_default, t.is_active
                FROM users u
                JOIN account_tiers t ON u.tier_id = t.id
                WHERE u.id = {placeholder}
            ''', (user_id,))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'price_monthly': float(row[3]),
                    'price_yearly': float(row[4]),
                    'max_requests_per_day': row[5],
                    'max_requests_per_month': row[6],
                    'max_providers': row[7],
                    'max_rotations': row[8],
                    'max_autoselections': row[9],
                    'max_rotation_models': row[10],
                    'max_autoselection_models': row[11],
                    'market_fee_percentage': float(row[12] or 10.0),
                    'is_default': bool(row[13]),
                    'is_active': bool(row[14]),
                }
            return None
    
    def set_user_tier(self, user_id: int, tier_id: int) -> bool:
        """
        Set the tier for a user.
        
        Args:
            user_id: User ID
            tier_id: Tier ID
            
        Returns:
            True if updated, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                UPDATE users
                SET tier_id = {placeholder}
                WHERE id = {placeholder}
            ''', (tier_id, user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_visible_tiers(self) -> List[Dict]:
        """
        Get only visible account tiers (for user selection).
        
        Returns:
            List of visible tier dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, description, price_monthly, price_yearly, is_default, is_active,
                       max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                       max_autoselections, max_rotation_models, max_autoselection_models,
                       created_at, updated_at, is_visible, market_fee_percentage
                FROM account_tiers
                WHERE is_visible = 1 AND is_active = 1
                ORDER BY price_monthly ASC
            ''')
            
            tiers = []
            for row in cursor.fetchall():
                tiers.append({
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'price_monthly': float(row[3]),
                    'price_yearly': float(row[4]),
                    'is_default': bool(row[5]),
                    'is_active': bool(row[6]),
                    'max_requests_per_day': row[7],
                    'max_requests_per_month': row[8],
                    'max_providers': row[9],
                    'max_rotations': row[10],
                    'max_autoselections': row[11],
                    'max_rotation_models': row[12],
                    'max_autoselection_models': row[13],
                    'created_at': row[14],
                    'updated_at': row[15],
                    'is_visible': bool(row[16]) if len(row) > 16 else True,
                    'market_fee_percentage': float(row[17] or 10.0) if len(row) > 17 else 10.0,
                })
            return tiers

    # Payment and Subscription methods
    def get_user_payment_methods(self, user_id: int) -> List[Dict]:
        """Get all payment methods for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, type, identifier, is_default, is_active, metadata, created_at
                FROM payment_methods
                WHERE user_id = {placeholder}
                ORDER BY is_default DESC, created_at DESC
            ''', (user_id,))
            methods = []
            for row in cursor.fetchall():
                method_data = {
                    'id': row[0], 
                    'type': row[1], 
                    'identifier': row[2],
                    'is_default': bool(row[3]), 
                    'is_active': bool(row[4]),
                    'metadata': json.loads(row[5]) if row[5] else {},
                    'created_at': row[6]
                }
                
                # Add display fields based on type
                if method_data['type'] == 'paypal':
                    metadata = method_data['metadata']
                    method_data['email'] = metadata.get('paypal_email', method_data['identifier'])
                    method_data['last4'] = None
                elif method_data['type'] == 'stripe':
                    # Extract last4 from identifier or metadata
                    method_data['last4'] = method_data['identifier'][-4:] if len(method_data['identifier']) >= 4 else None
                    method_data['email'] = None
                elif method_data['type'] in ['bitcoin', 'ethereum', 'eth', 'usdt', 'usdc']:
                    method_data['address'] = method_data['identifier']
                    method_data['email'] = None
                    method_data['last4'] = None
                else:
                    method_data['email'] = None
                    method_data['last4'] = None
                
                methods.append(method_data)
            return methods

    def add_payment_method(self, user_id: int, method_type: str, identifier: str,
                           is_default: bool = False, metadata: Dict = None) -> int:
        """Add a payment method for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            if is_default:
                cursor.execute(f'''
                    UPDATE payment_methods SET is_default = 0
                    WHERE user_id = {placeholder}
                ''', (user_id,))
            cursor.execute(f'''
                INSERT INTO payment_methods (user_id, type, identifier, is_default, metadata)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (user_id, method_type, identifier, 1 if is_default else 0,
                  json.dumps(metadata) if metadata else None))
            conn.commit()
            return cursor.lastrowid

    def delete_payment_method(self, user_id: int, method_id: int) -> bool:
        """Delete a payment method."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                DELETE FROM payment_methods
                WHERE id = {placeholder} AND user_id = {placeholder}
            ''', (method_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def set_user_default_payment_method(self, user_id: int, method_type: str) -> bool:
        """Set a payment method type as default for crypto payments."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            try:
                # First, unset any existing default
                cursor.execute(f'''
                    UPDATE payment_methods SET is_default = 0
                    WHERE user_id = {placeholder}
                ''', (user_id,))
                
                # Check if user already has this payment method type
                cursor.execute(f'''
                    SELECT id FROM payment_methods
                    WHERE user_id = {placeholder} AND type = {placeholder}
                ''', (user_id, method_type))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing to be default
                    cursor.execute(f'''
                        UPDATE payment_methods SET is_default = 1
                        WHERE id = {placeholder}
                    ''', (existing[0],))
                else:
                    # Create new payment method entry
                    cursor.execute(f'''
                        INSERT INTO payment_methods (user_id, type, identifier, is_default, metadata)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, 1, NULL)
                    ''', (user_id, method_type, 'default'))
                
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error setting default payment method: {e}")
                return False

    def get_user_subscription(self, user_id: int) -> Optional[Dict]:
        """Get current active subscription for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT s.id, s.tier_id, t.name, s.status, s.start_date, s.end_date,
                       s.next_billing_date, s.auto_renew, t.price_monthly, t.price_yearly
                FROM user_subscriptions s
                JOIN account_tiers t ON s.tier_id = t.id
                WHERE s.user_id = {placeholder} AND s.status = 'active'
                ORDER BY s.created_at DESC LIMIT 1
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0], 'tier_id': row[1], 'tier_name': row[2],
                    'status': row[3], 'start_date': row[4], 'end_date': row[5],
                    'next_billing_date': row[6], 'auto_renew': bool(row[7]),
                    'price_monthly': float(row[8]), 'price_yearly': float(row[9])
                }
            return None

    def get_user_payment_transactions(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Get payment transaction history for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, amount, currency, status, transaction_type,
                       external_transaction_id, created_at, completed_at
                FROM payment_transactions
                WHERE user_id = {placeholder}
                ORDER BY created_at DESC LIMIT {placeholder}
            ''', (user_id, limit))
            transactions = []
            for row in cursor.fetchall():
                transactions.append({
                    'id': row[0], 'amount': float(row[1]), 'currency': row[2],
                    'status': row[3], 'transaction_type': row[4],
                    'external_transaction_id': row[5],
                    'created_at': row[6], 'completed_at': row[7]
                })
            return transactions

    def get_payment_gateway_settings(self) -> Dict:
        """Get payment gateway settings from admin_settings table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            default_gateways = {
                "paypal": {"enabled": False, "client_id": "", "client_secret": "", "webhook_secret": "", "sandbox": True},
                "stripe": {"enabled": False, "publishable_key": "", "secret_key": "", "webhook_secret": "", "test_mode": True},
                "bitcoin": {"enabled": False, "address": "", "confirmations": 3, "expiration_minutes": 120},
                "ethereum": {"enabled": False, "address": "", "confirmations": 12, "chain_id": 1},
                "usdt": {"enabled": False, "address": "", "network": "erc20", "confirmations": 3},
                "usdc": {"enabled": False, "address": "", "network": "erc20", "confirmations": 3}
            }
            
            try:
                cursor.execute(f'''
                    SELECT setting_value
                    FROM admin_settings
                    WHERE setting_key = {placeholder}
                ''', ('payment_gateways',))
                row = cursor.fetchone()
                if row and row[0]:
                    import json
                    return json.loads(row[0])
            except Exception as e:
                logger.warning(f"Error loading payment gateway settings: {e}")
            
            return default_gateways

    def get_encryption_key(self) -> Optional[str]:
        """Get encryption key from admin_settings table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            try:
                cursor.execute(f'''
                    SELECT setting_value
                    FROM admin_settings
                    WHERE setting_key = {placeholder}
                ''', ('encryption_key',))
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]
            except Exception as e:
                logger.warning(f"Error loading encryption key: {e}")
            
            return None

    def save_encryption_key(self, encryption_key: str) -> bool:
        """Save encryption key to admin_settings table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            try:
                insert_syntax = 'INSERT OR REPLACE' if self.db_type == 'sqlite' else 'REPLACE'
                cursor.execute(f'''
                    {insert_syntax} INTO admin_settings (setting_key, setting_value, updated_at)
                    VALUES ({placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', ('encryption_key', encryption_key))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error saving encryption key: {e}")
                conn.rollback()
                return False

    def save_payment_gateway_settings(self, settings: Dict) -> bool:
        """Save payment gateway settings to admin_settings table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            import json
            settings_json = json.dumps(settings)
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            logger.info(f"Attempting to save payment gateway settings to database (db_type={self.db_type})")
            logger.info(f"Settings to save: {settings_json[:200]}...")  # Log first 200 chars
            
            try:
                insert_syntax = 'INSERT OR REPLACE' if self.db_type == 'sqlite' else 'REPLACE'
                query = f'''
                    {insert_syntax} INTO admin_settings (setting_key, setting_value, updated_at)
                    VALUES ({placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                '''
                logger.info(f"Executing query: {query}")
                cursor.execute(query, ('payment_gateways', settings_json))
                conn.commit()
                logger.info("Payment gateway settings saved to database successfully")
                
                # Verify the save
                cursor.execute(f'''
                    SELECT setting_value FROM admin_settings WHERE setting_key = {placeholder}
                ''', ('payment_gateways',))
                row = cursor.fetchone()
                if row:
                    logger.info(f"Verification: Settings in DB after save: {row[0][:200]}...")
                else:
                    logger.error("Verification failed: No payment_gateways record found after save!")
                
                return True
            except Exception as e:
                logger.error(f"Error saving payment gateway settings: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return False

    def get_user_cache_settings(self, user_id: int, provider_id: str = None, model_name: str = None) -> Dict:
        """
        Get user's prompt cache settings.
        
        Args:
            user_id: User ID
            provider_id: Optional provider ID to filter by
            model_name: Optional model name to filter by
            
        Returns:
            Dict with cache settings. If specific provider/model not found, returns default enabled.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            # Build query based on filters
            if provider_id and model_name:
                # Check for specific provider+model setting
                cursor.execute(f'''
                    SELECT cache_enabled FROM user_cache_settings
                    WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name = {placeholder}
                ''', (user_id, provider_id, model_name))
                row = cursor.fetchone()
                if row:
                    return {'cache_enabled': bool(row[0]), 'level': 'model'}
                
                # Fall back to provider-level setting
                cursor.execute(f'''
                    SELECT cache_enabled FROM user_cache_settings
                    WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name IS NULL
                ''', (user_id, provider_id))
                row = cursor.fetchone()
                if row:
                    return {'cache_enabled': bool(row[0]), 'level': 'provider'}
                    
            elif provider_id:
                # Check for provider-level setting
                cursor.execute(f'''
                    SELECT cache_enabled FROM user_cache_settings
                    WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name IS NULL
                ''', (user_id, provider_id))
                row = cursor.fetchone()
                if row:
                    return {'cache_enabled': bool(row[0]), 'level': 'provider'}
            
            # Check for global user setting (NULL provider and model)
            cursor.execute(f'''
                SELECT cache_enabled FROM user_cache_settings
                WHERE user_id = {placeholder} AND provider_id IS NULL AND model_name IS NULL
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                return {'cache_enabled': bool(row[0]), 'level': 'global'}
            
            # Default: cache enabled
            return {'cache_enabled': True, 'level': 'default'}
    
    def set_user_cache_setting(self, user_id: int, cache_enabled: bool, provider_id: str = None, model_name: str = None) -> bool:
        """
        Set user's prompt cache setting.
        
        Args:
            user_id: User ID
            cache_enabled: Whether to enable cache
            provider_id: Optional provider ID (None = global setting)
            model_name: Optional model name (requires provider_id)
            
        Returns:
            True if successful
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            try:
                # First, check if a record exists (handle NULL values explicitly)
                if provider_id is None and model_name is None:
                    cursor.execute(f'''
                        SELECT id FROM user_cache_settings 
                        WHERE user_id = {placeholder} AND provider_id IS NULL AND model_name IS NULL
                    ''', (user_id,))
                elif provider_id is not None and model_name is None:
                    cursor.execute(f'''
                        SELECT id FROM user_cache_settings 
                        WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name IS NULL
                    ''', (user_id, provider_id))
                else:
                    cursor.execute(f'''
                        SELECT id FROM user_cache_settings 
                        WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name = {placeholder}
                    ''', (user_id, provider_id, model_name))
                
                existing = cursor.fetchone()
                cursor.fetchall()  # Consume any remaining results to avoid "Unread result found" error
                
                if existing:
                    # Update existing record
                    cursor.execute(f'''
                        UPDATE user_cache_settings 
                        SET cache_enabled = {placeholder}, updated_at = CURRENT_TIMESTAMP
                        WHERE id = {placeholder}
                    ''', (cache_enabled, existing[0]))
                else:
                    # Insert new record
                    cursor.execute(f'''
                        INSERT INTO user_cache_settings 
                        (user_id, provider_id, model_name, cache_enabled, updated_at)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                    ''', (user_id, provider_id, model_name, cache_enabled))
                
                conn.commit()
                logger.info(f"Set cache setting for user {user_id}, provider={provider_id}, model={model_name}, enabled={cache_enabled}")
                return True
            except Exception as e:
                logger.error(f"Error setting cache setting: {e}")
                return False
    
    def get_all_user_cache_settings(self, user_id: int) -> list:
        """Get all cache settings for a user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            cursor.execute(f'''
                SELECT provider_id, model_name, cache_enabled, created_at, updated_at
                FROM user_cache_settings
                WHERE user_id = {placeholder}
                ORDER BY provider_id, model_name
            ''', (user_id,))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                cache_val = row[2]
                result = {
                    'provider_id': row[0],
                    'model_name': row[1],
                    'cache_enabled': bool(cache_val) if cache_val is not None else True,
                    'created_at': row[3],
                    'updated_at': row[4]
                }
                logger.info(f"Cache setting: provider={row[0]}, model={row[1]}, raw_val={cache_val}, bool={bool(cache_val)}")
                results.append(result)
            return results
    
    def delete_user_cache_setting(self, user_id: int, provider_id: str = None, model_name: str = None) -> bool:
        """Delete a user's cache setting."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            try:
                if provider_id and model_name:
                    cursor.execute(f'''
                        DELETE FROM user_cache_settings
                        WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name = {placeholder}
                    ''', (user_id, provider_id, model_name))
                elif provider_id:
                    cursor.execute(f'''
                        DELETE FROM user_cache_settings
                        WHERE user_id = {placeholder} AND provider_id = {placeholder} AND model_name IS NULL
                    ''', (user_id, provider_id))
                else:
                    cursor.execute(f'''
                        DELETE FROM user_cache_settings
                        WHERE user_id = {placeholder} AND provider_id IS NULL AND model_name IS NULL
                    ''', (user_id,))
                
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error deleting cache setting: {e}")
                return False

    def get_currency_settings(self) -> Dict:
        """Get currency settings from admin_settings table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            default_currency = {
                "currency_code": "USD",
                "currency_symbol": "$",
                "currency_decimals": 2
            }
            
            try:
                cursor.execute(f'''
                    SELECT setting_value
                    FROM admin_settings
                    WHERE setting_key = {placeholder}
                ''', ('currency',))
                row = cursor.fetchone()
                if row and row[0]:
                    import json
                    return json.loads(row[0])
            except Exception as e:
                logger.warning(f"Error loading currency settings: {e}")
            
            return default_currency

    def get_market_settings(self) -> Dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            default_settings = {
                'enabled': False,
                'allow_user_publish': True,
                'allow_admin_publish': True,
                'allow_import': True,
            }
            try:
                cursor.execute(f'''
                    SELECT setting_value
                    FROM admin_settings
                    WHERE setting_key = {placeholder}
                ''', ('market',))
                row = cursor.fetchone()
                if row and row[0]:
                    loaded = json.loads(row[0])
                    if isinstance(loaded, dict):
                        default_settings.update(loaded)
            except Exception as e:
                logger.warning(f"Error loading market settings: {e}")
            return default_settings

    def save_market_settings(self, settings: Dict) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            settings_json = json.dumps(settings or {})
            try:
                insert_syntax = 'INSERT OR REPLACE' if self.db_type == 'sqlite' else 'REPLACE'
                cursor.execute(f'''
                    {insert_syntax} INTO admin_settings (setting_key, setting_value, updated_at)
                    VALUES ({placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', ('market', settings_json))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error saving market settings: {e}")
                return False

    def save_currency_settings(self, settings: Dict) -> bool:
        """Save currency settings to admin_settings table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            import json
            settings_json = json.dumps(settings)
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
            try:
                insert_syntax = 'INSERT OR REPLACE' if self.db_type == 'sqlite' else 'REPLACE'
                cursor.execute(f'''
                    {insert_syntax} INTO admin_settings (setting_key, setting_value, updated_at)
                    VALUES ({placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ''', ('currency', settings_json))
                conn.commit()
                logger.info("Currency settings saved to database")
                return True
            except Exception as e:
                logger.error(f"Error saving currency settings: {e}")
                return False


# ============================================================
# DATABASE REGISTRY - EXPLICIT NAMED INSTANCES
# No more accidental wrong database connections!
# ============================================================

class DatabaseRegistry:
    """
    Explicit registry for database connections.
    
    This prevents accidental mixing of configuration and cache databases.
    Use the named getters instead of creating DatabaseManager directly:
    
        db = DatabaseRegistry.get_config_database()
        db = DatabaseRegistry.get_cache_database()
    
    This class guarantees you will always get the correct database instance.
    """
    
    # Explicit database types
    TYPE_CONFIG = 'config'
    TYPE_CACHE = 'cache'
    
    # Singleton instances
    _instances: Dict[str, DatabaseManager] = {}
    
    @classmethod
    def get_config_database(cls, db_config: Optional[Dict[str, Any]] = None) -> DatabaseManager:
        """Get the CONFIGURATION database (aisbf.db) - FOR PERMANENT USER DATA ONLY

        NOTE: Config database ALWAYS uses SQLite or MySQL.
        Redis is NEVER used for permanent configuration storage.
        """
        if cls.TYPE_CONFIG not in cls._instances:
            if db_config is not None:
                # CONFIG DATABASE NEVER USES REDIS - FORCE SQLITE OR MYSQL
                config_type = db_config.get('type', 'sqlite').lower()
                if config_type == 'redis':
                    logger.warning("⚠️ CONFIG DATABASE: Redis requested, falling back to SQLite (Redis is for cache only!)")
                    # Fallback to SQLite for config
                    aisbf_dir = Path.home() / '.aisbf'
                    aisbf_dir.mkdir(exist_ok=True)
                    db_config = {
                        'type': 'sqlite',
                        'sqlite_path': str(aisbf_dir / 'aisbf.db'),
                        'mysql_host': 'localhost',
                        'mysql_port': 3306,
                        'mysql_user': 'aisbf',
                        'mysql_password': '',
                        'mysql_database': 'aisbf'
                    }
                # ✅ FIX: Allow MySQL configuration for config database
                elif config_type == 'mysql':
                    # Validate MySQL configuration is present
                    required_mysql_fields = ['mysql_host', 'mysql_port', 'mysql_user', 'mysql_database']
                    missing_fields = [field for field in required_mysql_fields if field not in db_config]
                    if missing_fields:
                        logger.warning(f"⚠️ CONFIG DATABASE: MySQL configuration missing fields: {missing_fields}, falling back to SQLite")
                        aisbf_dir = Path.home() / '.aisbf'
                        aisbf_dir.mkdir(exist_ok=True)
                        db_config = {
                            'type': 'sqlite',
                            'sqlite_path': str(aisbf_dir / 'aisbf.db'),
                            'mysql_host': 'localhost',
                            'mysql_port': 3306,
                            'mysql_user': 'aisbf',
                            'mysql_password': '',
                            'mysql_database': 'aisbf'
                        }
                    else:
                        logger.info(f"✅ CONFIG DATABASE: Using MySQL configuration as specified - host: {db_config['mysql_host']}, database: {db_config['mysql_database']}")
            
            cls._instances[cls.TYPE_CONFIG] = DatabaseManager(db_config, database_type=cls.TYPE_CONFIG)
            logger.info(f"✅ CONFIG DATABASE INSTANCE REGISTERED [backend: {cls._instances[cls.TYPE_CONFIG].db_type}]")
        return cls._instances[cls.TYPE_CONFIG]
    
    @classmethod
    def get_cache_database(cls, db_config: Optional[Dict[str, Any]] = None) -> DatabaseManager:
        """Get the CACHE database (cache.db) - FOR TEMPORARY DATA ONLY"""
        if cls.TYPE_CACHE not in cls._instances:
            # For cache database, respect the configured backend type
            if db_config is None:
                aisbf_dir = Path.home() / '.aisbf'
                aisbf_dir.mkdir(exist_ok=True)
                # Use same backend type as config database by default
                db_config = {
                    'type': 'sqlite',
                    'sqlite_path': str(aisbf_dir / 'cache.db'),
                    'mysql_host': 'localhost',
                    'mysql_port': 3306,
                    'mysql_user': 'aisbf',
                    'mysql_password': '',
                    'mysql_database': 'aisbf_cache',
                    'redis_host': 'localhost',
                    'redis_port': 6379,
                    'redis_db': 1,
                    'redis_password': '',
                    'redis_key_prefix': 'aisbf:cache:'
                }
            else:
                # Ensure we always use the correct database name/suffix for cache
                if db_config.get('type') == 'mysql':
                    if 'mysql_database' in db_config:
                        # Never use main config database for cache
                        if db_config['mysql_database'] == 'aisbf':
                            db_config['mysql_database'] = 'aisbf_cache'
                if db_config.get('type') == 'redis':
                    # Use separate Redis DB number for cache
                    if db_config.get('redis_db', 0) == 0:
                        db_config['redis_db'] = 1
                    if 'redis_key_prefix' not in db_config:
                        db_config['redis_key_prefix'] = 'aisbf:cache:'
            
            cls._instances[cls.TYPE_CACHE] = DatabaseManager(db_config, database_type=cls.TYPE_CACHE)
            logger.info(f"✅ CACHE DATABASE INSTANCE REGISTERED [backend: {db_config.get('type', 'sqlite')}]")
        return cls._instances[cls.TYPE_CACHE]
    
    @classmethod
    def get_instance(cls, database_type: str, db_config: Optional[Dict[str, Any]] = None) -> DatabaseManager:
        """Get database instance by explicit type"""
        if database_type == cls.TYPE_CONFIG:
            return cls.get_config_database(db_config)
        elif database_type == cls.TYPE_CACHE:
            return cls.get_cache_database(db_config)
        else:
            raise ValueError(f"Unknown database type: {database_type}. Use TYPE_CONFIG or TYPE_CACHE")
    
    @classmethod
    def reset(cls):
        """Reset all instances (for testing only)"""
        cls._instances.clear()


# ============================================================
# LEGACY COMPATIBILITY LAYER
# ============================================================

def get_database(db_config: Optional[Dict[str, Any]] = None) -> DatabaseManager:
    """
    Legacy getter - DEPRECATED!
    
    Use DatabaseRegistry.get_config_database() instead for explicit type safety.
    This method now returns ONLY the CONFIG database to preserve existing behaviour.
    """
    logger.warning("⚠️ DEPRECATED: get_database() is deprecated. Use DatabaseRegistry.get_config_database() or DatabaseRegistry.get_cache_database() instead")
    return DatabaseRegistry.get_config_database(db_config)


def initialize_database(db_config: Optional[Dict[str, Any]] = None):
    """
    Initialize the database and clean up old records.
    This should be called at application startup.

    Args:
        db_config: Database configuration. If None, uses default.
    """
    db = DatabaseRegistry.get_config_database(db_config)
    db.cleanup_old_token_usage(days_to_keep=7)
    logger.info("Database initialized and old records cleaned up")


# Now modify DatabaseManager constructor to accept type parameter
def DatabaseManager__init__(self, db_config: Optional[Dict[str, Any]] = None, database_type: str = DatabaseRegistry.TYPE_CONFIG):
    """
    Initialize the database manager.

    Args:
        db_config: Database configuration dictionary. If None, uses default SQLite config.
        database_type: TYPE_CONFIG for permanent user data, TYPE_CACHE for temporary cache
    """
    self.database_type = database_type
    
    if db_config is None:
        # Default SQLite configuration
        aisbf_dir = Path.home() / '.aisbf'
        aisbf_dir.mkdir(exist_ok=True)
        if database_type == DatabaseRegistry.TYPE_CONFIG:
            db_path = str(aisbf_dir / 'aisbf.db')
        else:
            db_path = str(aisbf_dir / 'cache.db')
            
        self.db_config = {
            'type': 'sqlite',
            'sqlite_path': db_path,
            'mysql_host': 'localhost',
            'mysql_port': 3306,
            'mysql_user': 'aisbf',
            'mysql_password': '',
            'mysql_database': 'aisbf' if database_type == DatabaseRegistry.TYPE_CONFIG else 'aisbf_cache'
        }
    else:
        self.db_config = db_config

    self.db_type = self.db_config.get('type', 'sqlite').lower()
    self.executor = get_db_executor()

    if self.db_type == 'mysql':
        # Import the module-level MYSQL_AVAILABLE flag
        import aisbf.database as db_module
        if not db_module.MYSQL_AVAILABLE:
            logger.error(f"❌ DEBUG: MySQL connector not available!")
            raise ImportError("MySQL connector not available. Install mysql-connector-python.")
        logger.info(f"✅ DEBUG: MySQL connector available, proceeding...")

    self._initialize_database()
    logger.info(f"Database initialized: {self.db_type} [TYPE: {self.database_type}]")
DatabaseManager.__init__ = DatabaseManager__init__


# ============================================================
# SAFETY MECHANISM: Prevent config tables in cache database
# ============================================================

def DatabaseManager__initialize_database(self):
    """Create database tables if they don't exist."""
    with self._get_connection() as conn:
        cursor = conn.cursor()

        if self.db_type == 'sqlite':
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA busy_timeout=5000')
            auto_increment = 'AUTOINCREMENT'
            timestamp_default = 'CURRENT_TIMESTAMP'
            boolean_type = 'BOOLEAN'
        else:  # mysql
            auto_increment = 'AUTO_INCREMENT'
            timestamp_default = 'CURRENT_TIMESTAMP'
            boolean_type = 'TINYINT(1)'

        if self.database_type == DatabaseRegistry.TYPE_CONFIG:
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY {auto_increment},
                    user_id INTEGER,
                    provider_id VARCHAR(255) NOT NULL,
                    model_name VARCHAR(255) NOT NULL,
                    tokens_used INTEGER NOT NULL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    actual_cost DECIMAL(10,6),
                    success BOOLEAN DEFAULT 1,
                    latency_ms INTEGER,
                    error_type VARCHAR(255),
                    token_id INTEGER,
                    rotation_id VARCHAR(255),
                    autoselect_id VARCHAR(255),
                    analytics_kind VARCHAR(32) DEFAULT 'execution',
                    timestamp TIMESTAMP DEFAULT {timestamp_default}
                )
            ''')

            # Migration: add columns to token_usage for older databases
            try:
                if self.db_type == 'sqlite':
                    cursor.execute("PRAGMA table_info(token_usage)")
                    columns = [row[1] for row in cursor.fetchall()]
                    for col, defn in [
                        ('prompt_tokens', 'INTEGER'),
                        ('completion_tokens', 'INTEGER'),
                        ('actual_cost', 'DECIMAL(10,6)'),
                        ('success', 'BOOLEAN DEFAULT 1'),
                        ('latency_ms', 'INTEGER'),
                        ('error_type', 'VARCHAR(255)'),
                        ('token_id', 'INTEGER'),
                        ('rotation_id', 'VARCHAR(255)'),
                        ('autoselect_id', 'VARCHAR(255)'),
                        ('analytics_kind', "VARCHAR(32) DEFAULT 'execution'"),
                    ]:
                        if col not in columns:
                            cursor.execute(f'ALTER TABLE token_usage ADD COLUMN {col} {defn}')
                            logger.info(f"✅ Migration: Added {col} column to token_usage")
                else:
                    cursor.execute("""
                        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'token_usage'
                    """)
                    existing = {row[0] for row in cursor.fetchall()}
                    for col, defn in [
                        ('prompt_tokens', 'INTEGER'),
                        ('completion_tokens', 'INTEGER'),
                        ('actual_cost', 'DECIMAL(10,6)'),
                        ('success', 'BOOLEAN DEFAULT 1'),
                        ('latency_ms', 'INTEGER'),
                        ('error_type', 'VARCHAR(255)'),
                        ('token_id', 'INTEGER'),
                        ('rotation_id', 'VARCHAR(255)'),
                        ('autoselect_id', 'VARCHAR(255)'),
                        ('analytics_kind', "VARCHAR(32) DEFAULT 'execution'"),
                    ]:
                        if col not in existing:
                            cursor.execute(f'ALTER TABLE token_usage ADD COLUMN {col} {defn}')
                            logger.info(f"✅ Migration: Added {col} column to token_usage")
            except Exception as e:
                logger.warning(f"Migration check for token_usage columns: {e}")

            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS admin_settings (
                    id INTEGER PRIMARY KEY {auto_increment},
                    setting_key VARCHAR(255) UNIQUE NOT NULL,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT {timestamp_default}
                )
            ''')

            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY {auto_increment},
                    username VARCHAR(255) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE,
                    display_name VARCHAR(255),
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) DEFAULT 'user',
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    last_login TIMESTAMP NULL,
                    is_active {boolean_type} DEFAULT 1,
                    email_verified {boolean_type} DEFAULT 0,
                    verification_token VARCHAR(255),
                    verification_token_expires TIMESTAMP NULL,
                    last_verification_email_sent TIMESTAMP NULL
                )
            ''')

            self._run_config_migrations(cursor, auto_increment, timestamp_default, boolean_type)

        else:
            self._create_cache_tables(cursor, auto_increment, timestamp_default, boolean_type)

        conn.commit()
        logger.info(f"Database tables initialized successfully for {self.database_type} database")


def _studio_json_dumps(value: Any) -> str:
    return json.dumps(value)


def _studio_json_loads(value: Any, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def DatabaseManager__create_cache_tables(self, cursor, auto_increment, timestamp_default, boolean_type):
    """Create only temporary cache tables (CACHE DB ONLY)"""
    
    # Only minimal tracking tables for cache database
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY {auto_increment},
            user_id INTEGER,
            provider_id VARCHAR(255) NOT NULL,
            model_name VARCHAR(255) NOT NULL,
            tokens_used INTEGER NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            actual_cost DECIMAL(10,6),
            success BOOLEAN DEFAULT 1,
            latency_ms INTEGER,
            error_type VARCHAR(255),
            token_id INTEGER,
            analytics_kind VARCHAR(32) DEFAULT 'execution',
            timestamp TIMESTAMP DEFAULT {timestamp_default}
        )
    ''')
    
    logger.info("⚠️ CACHE DATABASE: Only minimal cache tables created - NO USER TABLES")


def DatabaseManager__run_config_migrations(self, cursor, auto_increment, timestamp_default, boolean_type):
    """Run all configuration database migrations"""
    # ==============================================
    # UNIVERSAL MIGRATIONS - RUN ON EVERY STARTUP
    # These run for ALL databases, new and existing
    # ==============================================
    logger.info("Running database migrations...")
    
    # Migration: Create user_cache_settings table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(user_cache_settings)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE user_cache_settings (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER NOT NULL,
                        provider_id VARCHAR(255),
                        model_name VARCHAR(255),
                        cache_enabled {boolean_type} DEFAULT 1,
                        created_at TIMESTAMP DEFAULT {timestamp_default},
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE(user_id, provider_id, model_name)
                    )
                ''')
                logger.info("✅ Migration: Created user_cache_settings table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = 'user_cache_settings'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE user_cache_settings (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER NOT NULL,
                        provider_id VARCHAR(255),
                        model_name VARCHAR(255),
                        cache_enabled {boolean_type} DEFAULT 1,
                        created_at TIMESTAMP DEFAULT {timestamp_default},
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE(user_id, provider_id, model_name)
                    )
                ''')
                logger.info("✅ Migration: Created user_cache_settings table")
    except Exception as e:
        logger.warning(f"Migration check for user_cache_settings table: {e}")
    
    # Migration: Clean up duplicate cache settings (NULL values bypass UNIQUE constraint in MySQL)
    try:
        logger.info("Checking for duplicate cache settings...")
        
        # Get all users with duplicate global settings
        if self.db_type == 'sqlite':
            cursor.execute('''
                SELECT user_id, COUNT(*) as cnt
                FROM user_cache_settings
                WHERE provider_id IS NULL AND model_name IS NULL
                GROUP BY user_id
                HAVING cnt > 1
            ''')
        else:
            cursor.execute('''
                SELECT user_id, COUNT(*) as cnt
                FROM user_cache_settings
                WHERE provider_id IS NULL AND model_name IS NULL
                GROUP BY user_id
                HAVING cnt > 1
            ''')
        
        duplicate_users = cursor.fetchall()
        
        if duplicate_users:
            logger.info(f"Found {len(duplicate_users)} users with duplicate global cache settings")
            
            for user_row in duplicate_users:
                user_id = user_row[0]
                
                # Get all global settings for this user, ordered by updated_at DESC
                placeholder = '?' if self.db_type == 'sqlite' else '%s'
                cursor.execute(f'''
                    SELECT id FROM user_cache_settings
                    WHERE user_id = {placeholder} AND provider_id IS NULL AND model_name IS NULL
                    ORDER BY updated_at DESC
                ''', (user_id,))

                all_ids = [row[0] for row in cursor.fetchall()]

                if len(all_ids) > 1:
                    # Keep the first (most recent), delete the rest
                    keep_id = all_ids[0]
                    delete_ids = all_ids[1:]

                    placeholders = ','.join([placeholder] * len(delete_ids))
                    cursor.execute(f'''
                        DELETE FROM user_cache_settings
                        WHERE id IN ({placeholders})
                    ''', tuple(delete_ids))
                    
                    logger.info(f"✅ Cleaned up {len(delete_ids)} duplicate cache settings for user {user_id}, kept id={keep_id}")
            
            # Note: conn.commit() will be called by the caller after all migrations
        else:
            logger.info("No duplicate cache settings found")
    except Exception as e:
        logger.warning(f"Migration check for duplicate cache settings: {e}")
    
    # Migration: Create account_tiers table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(account_tiers)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE account_tiers (
                        id INTEGER PRIMARY KEY {auto_increment},
                        name VARCHAR(255) UNIQUE NOT NULL,
                        description TEXT,
                        price_monthly DECIMAL(10,2) DEFAULT 0.00,
                        price_yearly DECIMAL(10,2) DEFAULT 0.00,
                        is_default {boolean_type} DEFAULT 0,
                        is_active {boolean_type} DEFAULT 1,
                        max_requests_per_day INTEGER DEFAULT -1,
                        max_requests_per_month INTEGER DEFAULT -1,
                        max_providers INTEGER DEFAULT -1,
                        max_rotations INTEGER DEFAULT -1,
                        max_autoselections INTEGER DEFAULT -1,
                        max_rotation_models INTEGER DEFAULT -1,
                        max_autoselection_models INTEGER DEFAULT -1,
                        is_visible {boolean_type} DEFAULT 1,
                        created_at TIMESTAMP DEFAULT {timestamp_default},
                        updated_at TIMESTAMP DEFAULT {timestamp_default}
                    )
                ''')
                logger.info("✅ Migration: Created missing account_tiers table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = 'account_tiers'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE account_tiers (
                        id INTEGER PRIMARY KEY {auto_increment},
                        name VARCHAR(255) UNIQUE NOT NULL,
                        description TEXT,
                        price_monthly DECIMAL(10,2) DEFAULT 0.00,
                        price_yearly DECIMAL(10,2) DEFAULT 0.00,
                        is_default {boolean_type} DEFAULT 0,
                        is_active {boolean_type} DEFAULT 1,
                        max_requests_per_day INTEGER DEFAULT -1,
                        max_requests_per_month INTEGER DEFAULT -1,
                        max_providers INTEGER DEFAULT -1,
                        max_rotations INTEGER DEFAULT -1,
                        max_autoselections INTEGER DEFAULT -1,
                        max_rotation_models INTEGER DEFAULT -1,
                        max_autoselection_models INTEGER DEFAULT -1,
                        is_visible {boolean_type} DEFAULT 1,
                        created_at TIMESTAMP DEFAULT {timestamp_default},
                        updated_at TIMESTAMP DEFAULT {timestamp_default}
                    )
                ''')
                logger.info("✅ Migration: Created missing account_tiers table")
    except Exception as e:
        logger.warning(f"Migration check for account_tiers table: {e}")

    try:
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS studio_assets (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                asset_type VARCHAR(32) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                metadata_json TEXT,
                files_json TEXT,
                quote_text TEXT,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, asset_type, name)
            )
        ''')
    except Exception as e:
        logger.warning(f"Migration check for studio_assets table: {e}")

    try:
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS studio_pipelines (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                pipeline_id VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                steps_json TEXT,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, pipeline_id)
            )
        ''')
    except Exception as e:
        logger.warning(f"Migration check for studio_pipelines table: {e}")

    # Migration: Add missing columns to account_tiers
    try:
        tier_columns = [
            ('max_requests_per_day', 'INTEGER DEFAULT -1'),
            ('max_requests_per_month', 'INTEGER DEFAULT -1'),
            ('max_providers', 'INTEGER DEFAULT -1'),
            ('max_rotations', 'INTEGER DEFAULT -1'),
            ('max_autoselections', 'INTEGER DEFAULT -1'),
            ('max_rotation_models', 'INTEGER DEFAULT -1'),
            ('max_autoselection_models', 'INTEGER DEFAULT -1'),
            ('market_fee_percentage', 'DECIMAL(5,2) DEFAULT 10.0'),
            ('is_default', f'{boolean_type} DEFAULT 0'),
            ('is_active', f'{boolean_type} DEFAULT 1'),
            ('is_visible', f'{boolean_type} DEFAULT 1')
        ]
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(account_tiers)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            col_count = 0
            for col_name, col_def in tier_columns:
                if col_name not in existing_columns:
                    cursor.execute(f'ALTER TABLE account_tiers ADD COLUMN {col_name} {col_def}')
                    col_count += 1
            if col_count > 0:
                logger.info(f"✅ Migration: Added {col_count} missing columns to account_tiers")
        else:
            cursor.execute("""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'account_tiers'
            """)
            existing_columns = {row[0] for row in cursor.fetchall()}
            col_count = 0
            for col_name, col_def in tier_columns:
                if col_name not in existing_columns:
                    cursor.execute(f'ALTER TABLE account_tiers ADD COLUMN {col_name} {col_def}')
                    col_count += 1
            if col_count > 0:
                logger.info(f"✅ Migration: Added {col_count} missing columns to account_tiers")
    except Exception as e:
        logger.warning(f"Migration check for account_tiers columns: {e}")

    # Migration: Ensure default free tier exists
    try:
        cursor.execute(f'SELECT COUNT(*) FROM account_tiers WHERE is_default = 1')
        free_tier_count = cursor.fetchone()[0]
        if free_tier_count == 0:
            cursor.execute(f'''
                INSERT INTO account_tiers
                (name, description, price_monthly, price_yearly, is_default, is_active,
                 max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                 max_autoselections, max_rotation_models, max_autoselection_models, market_fee_percentage)
                VALUES
                ('Free Tier', 'Default free account tier with unlimited access', 0.00, 0.00, 1, 1,
                 -1, -1, -1, -1, -1, -1, -1, 10.0)
            ''')
            logger.info("✅ Migration: Inserted default free tier")
    except Exception as e:
        logger.warning(f"Migration check for default free tier: {e}")

    # Users table is created with full schema earlier in migrations

    # Migration: Add all missing columns to users table
    try:
        required_columns = [
            ('display_name', 'VARCHAR(255)'),
            ('role', "VARCHAR(50) DEFAULT 'user'"),
            ('created_by', 'VARCHAR(255)'),
            ('last_login', 'TIMESTAMP NULL'),
            ('is_active', f'{boolean_type} DEFAULT 1'),
            ('email_verified', f'{boolean_type} DEFAULT 0'),
            ('verification_token', 'VARCHAR(255)'),
            ('verification_token_expires', 'TIMESTAMP NULL'),
            ('last_verification_email_sent', 'TIMESTAMP NULL'),
            ('tier_id', 'INTEGER DEFAULT 1'),
            ('subscription_expires', 'TIMESTAMP NULL'),
            ('stripe_customer_id', 'VARCHAR(100)'),
            ('reset_password_token', 'VARCHAR(255)'),
            ('reset_password_token_expires', 'TIMESTAMP NULL'),
            ('profile_pic', 'MEDIUMTEXT'),
        ]
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in cursor.fetchall()]
            for col_name, col_def in required_columns:
                if col_name not in columns:
                    cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}')
                    logger.info(f"✅ Migration: Added {col_name} column to users")
        else:
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'
            """)
            existing = {row[0]: row[1] for row in cursor.fetchall()}
            for col_name, col_def in required_columns:
                if col_name not in existing:
                    try:
                        cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}')
                        logger.info(f"✅ Migration: Added {col_name} column to users")
                    except Exception as col_e:
                        logger.warning(f"Migration check for users.{col_name}: {col_e}")
            # Widen profile_pic from TEXT to MEDIUMTEXT if needed
            if existing.get('profile_pic', '').lower() == 'text':
                try:
                    cursor.execute('ALTER TABLE users MODIFY COLUMN profile_pic MEDIUMTEXT')
                    logger.info("✅ Migration: Widened users.profile_pic to MEDIUMTEXT")
                except Exception as col_e:
                    logger.warning(f"Migration: could not widen profile_pic: {col_e}")
    except Exception as e:
        logger.warning(f"Migration check for users table columns: {e}")

    # Migration: Create payment_methods, user_subscriptions, payment_transactions tables
    for table_name, create_sql in [
        ('payment_methods', f'''
            CREATE TABLE payment_methods (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                type VARCHAR(50) NOT NULL,
                identifier VARCHAR(255) NOT NULL,
                is_default {boolean_type} DEFAULT 0,
                is_active {boolean_type} DEFAULT 1,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''),
        ('user_subscriptions', f'''
            CREATE TABLE user_subscriptions (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                tier_id INTEGER NOT NULL,
                status VARCHAR(50) DEFAULT 'active',
                start_date TIMESTAMP DEFAULT {timestamp_default},
                end_date TIMESTAMP NULL,
                next_billing_date TIMESTAMP NULL,
                trial_end_date TIMESTAMP NULL,
                payment_method_id INTEGER,
                auto_renew {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (tier_id) REFERENCES account_tiers(id),
                FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id),
                UNIQUE(user_id, tier_id)
            )
        '''),
        ('payment_transactions', f'''
            CREATE TABLE payment_transactions (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                tier_id INTEGER,
                subscription_id INTEGER,
                payment_method_id INTEGER,
                amount DECIMAL(10,2) NOT NULL,
                currency VARCHAR(10) DEFAULT 'USD',
                status VARCHAR(50) NOT NULL,
                transaction_type VARCHAR(50) NOT NULL,
                external_transaction_id VARCHAR(255),
                metadata TEXT,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                completed_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (tier_id) REFERENCES account_tiers(id),
                FOREIGN KEY (subscription_id) REFERENCES user_subscriptions(id),
                FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id)
            )
        '''),
        ('user_cache_settings', f'''
            CREATE TABLE user_cache_settings (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                provider_id VARCHAR(255),
                model_name VARCHAR(255),
                cache_enabled {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, provider_id, model_name)
            )
        '''),
        ('market_listings', f'''
            CREATE TABLE market_listings (
                id INTEGER PRIMARY KEY {auto_increment},
                owner_user_id INTEGER NOT NULL,
                owner_username VARCHAR(255) NOT NULL,
                source_scope VARCHAR(32) NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                source_id VARCHAR(255) NOT NULL,
                listing_key VARCHAR(255) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                provider_id VARCHAR(255),
                model_id VARCHAR(255),
                endpoint TEXT,
                currency_code VARCHAR(10) NOT NULL DEFAULT 'USD',
                price_per_million_tokens DECIMAL(10,4) NOT NULL DEFAULT 0.0,
                metadata TEXT,
                config_snapshot TEXT,
                price_per_1000_requests DECIMAL(10,4) NOT NULL DEFAULT 0.0,
                provider_price_per_million_tokens DECIMAL(10,4),
                provider_price_per_1000_requests DECIMAL(10,4),
                is_active {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (owner_user_id) REFERENCES users(id),
                UNIQUE(owner_user_id, listing_key)
            )
        '''),
        ('market_votes', f'''
            CREATE TABLE market_votes (
                id INTEGER PRIMARY KEY {auto_increment},
                listing_id INTEGER NOT NULL,
                voter_user_id INTEGER NOT NULL,
                target_type VARCHAR(32) NOT NULL,
                target_key VARCHAR(255) NOT NULL,
                vote INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (listing_id) REFERENCES market_listings(id),
                FOREIGN KEY (voter_user_id) REFERENCES users(id),
                UNIQUE(listing_id, voter_user_id, target_type, target_key)
            )
        '''),
        ('market_imports', f'''
            CREATE TABLE market_imports (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                listing_id INTEGER NOT NULL,
                imported_config_type VARCHAR(32) NOT NULL,
                imported_config_id VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (listing_id) REFERENCES market_listings(id)
            )
        '''),
        ('market_import_references', f'''
            CREATE TABLE market_import_references (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                listing_id INTEGER NOT NULL,
                reference_type VARCHAR(32) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                owner_username VARCHAR(255) NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                source_id VARCHAR(255) NOT NULL,
                is_active {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (listing_id) REFERENCES market_listings(id)
            )
        '''),
        ('market_usage_transactions', f'''
            CREATE TABLE market_usage_transactions (
                id INTEGER PRIMARY KEY {auto_increment},
                listing_id INTEGER NOT NULL,
                consumer_user_id INTEGER NOT NULL,
                provider_user_id INTEGER NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                requests_count INTEGER DEFAULT 0,
                gross_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                platform_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                provider_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                currency_code VARCHAR(10) NOT NULL DEFAULT 'USD',
                settlement_key VARCHAR(255),
                metadata TEXT,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (listing_id) REFERENCES market_listings(id),
                FOREIGN KEY (consumer_user_id) REFERENCES users(id),
                FOREIGN KEY (provider_user_id) REFERENCES users(id),
                UNIQUE(settlement_key)
            )
        ''')
    ]:
        try:
            if self.db_type == 'sqlite':
                cursor.execute(f"PRAGMA table_info({table_name})")
                if not cursor.fetchall():
                    cursor.execute(create_sql)
                    logger.info(f"✅ Migration: Created missing {table_name} table")
            else:
                cursor.execute(f"""
                    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_NAME = '{table_name}'
                """)
                if not cursor.fetchone():
                    cursor.execute(create_sql)
                    logger.info(f"✅ Migration: Created missing {table_name} table")
        except Exception as e:
            logger.warning(f"Migration check for {table_name} table: {e}")


    # Migration: Create user config tables (providers, rotations, autoselects, prompts, tokens, etc.)
    for table_name, create_sql in [
        ('user_providers', f'''
            CREATE TABLE user_providers (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                provider_id VARCHAR(255) NOT NULL,
                config TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, provider_id)
            )
        '''),
        ('user_rotations', f'''
            CREATE TABLE user_rotations (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                rotation_id VARCHAR(255) NOT NULL,
                config TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, rotation_id)
            )
        '''),
        ('user_autoselects', f'''
            CREATE TABLE user_autoselects (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                autoselect_id VARCHAR(255) NOT NULL,
                config TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, autoselect_id)
            )
        '''),
        ('user_prompts', f'''
            CREATE TABLE user_prompts (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                prompt_key VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, prompt_key)
            )
        '''),
        ('user_api_tokens', f'''
            CREATE TABLE user_api_tokens (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                token VARCHAR(255) UNIQUE NOT NULL,
                description TEXT,
                scope VARCHAR(10) DEFAULT 'api',
                created_at TIMESTAMP DEFAULT {timestamp_default},
                last_used TIMESTAMP NULL,
                is_active {boolean_type} DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''),
        ('user_token_usage', f'''
            CREATE TABLE user_token_usage (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                token_id INTEGER,
                provider_id VARCHAR(255) NOT NULL,
                model_name VARCHAR(255) NOT NULL,
                tokens_used INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (token_id) REFERENCES user_api_tokens(id)
            )
        '''),
        ('user_auth_files', f'''
            CREATE TABLE user_auth_files (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                provider_id VARCHAR(255) NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                stored_filename VARCHAR(255) NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                mime_type VARCHAR(100),
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, provider_id, file_type)
            )
        '''),
        ('user_oauth2_credentials', f'''
            CREATE TABLE user_oauth2_credentials (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                provider_id VARCHAR(255) NOT NULL,
                auth_type VARCHAR(50) NOT NULL,
                credentials TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, provider_id, auth_type)
            )
        '''),
    ]:
        try:
            if self.db_type == 'sqlite':
                cursor.execute(f"PRAGMA table_info({table_name})")
                if not cursor.fetchall():
                    cursor.execute(create_sql)
                    logger.info(f"✅ Migration: Created {table_name} table")
            else:
                cursor.execute("""
                    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                """, (table_name,))
                if not cursor.fetchone():
                    cursor.execute(create_sql)
                    logger.info(f"✅ Migration: Created {table_name} table")
        except Exception as e:
            logger.warning(f"Migration check for {table_name} table: {e}")

    # Migration: Add scope column to user_api_tokens if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(user_api_tokens)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'scope' not in columns and columns:
                cursor.execute("ALTER TABLE user_api_tokens ADD COLUMN scope VARCHAR(10) DEFAULT 'api'")
                logger.info("✅ Migration: Added scope column to user_api_tokens")
        else:
            cursor.execute("""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = 'user_api_tokens' AND COLUMN_NAME = 'scope'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE user_api_tokens ADD COLUMN scope VARCHAR(10) DEFAULT 'api'")
                logger.info("✅ Migration: Added scope column to user_api_tokens")
    except Exception as e:
        logger.warning(f"Migration check for user_api_tokens.scope: {e}")

    # Migration: Create user_notifications table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(user_notifications)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE user_notifications (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        message TEXT NOT NULL,
                        notification_type VARCHAR(50) DEFAULT 'message',
                        is_read {boolean_type} DEFAULT 0,
                        created_at TIMESTAMP DEFAULT {timestamp_default},
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                ''')
                logger.info("✅ Migration: Created user_notifications table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_notifications'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE user_notifications (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        message TEXT NOT NULL,
                        notification_type VARCHAR(50) DEFAULT 'message',
                        is_read {boolean_type} DEFAULT 0,
                        created_at TIMESTAMP DEFAULT {timestamp_default},
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                ''')
                logger.info("✅ Migration: Created user_notifications table")
    except Exception as e:
        logger.warning(f"Migration check for user_notifications table: {e}")

    # Migration: add settlement_key to market_usage_transactions and index it for deduplication
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(market_usage_transactions)")
            columns = [row[1] for row in cursor.fetchall()]
            if columns and 'settlement_key' not in columns:
                cursor.execute("ALTER TABLE market_usage_transactions ADD COLUMN settlement_key VARCHAR(255)")
                logger.info("✅ Migration: Added settlement_key column to market_usage_transactions")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_usage_transactions_settlement_key ON market_usage_transactions(settlement_key)")
        else:
            cursor.execute("""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'market_usage_transactions' AND COLUMN_NAME = 'settlement_key'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE market_usage_transactions ADD COLUMN settlement_key VARCHAR(255) NULL")
                logger.info("✅ Migration: Added settlement_key column to market_usage_transactions")
            cursor.execute("""
                SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'market_usage_transactions' AND INDEX_NAME = 'idx_market_usage_transactions_settlement_key'
            """)
            if not cursor.fetchone():
                cursor.execute("CREATE UNIQUE INDEX idx_market_usage_transactions_settlement_key ON market_usage_transactions(settlement_key)")
                logger.info("✅ Migration: Added settlement_key unique index to market_usage_transactions")
    except Exception as e:
        logger.warning(f"Migration check for market_usage_transactions.settlement_key: {e}")

    # Migration: Create context_dimensions table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(context_dimensions)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE context_dimensions (
                        id INTEGER PRIMARY KEY {auto_increment},
                        provider_id VARCHAR(255) NOT NULL,
                        model_name VARCHAR(255) NOT NULL,
                        context_size INTEGER,
                        condense_context INTEGER,
                        condense_method TEXT,
                        effective_context INTEGER DEFAULT 0,
                        last_updated TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(provider_id, model_name)
                    )
                ''')
                logger.info("✅ Migration: Created context_dimensions table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'context_dimensions'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE context_dimensions (
                        id INTEGER PRIMARY KEY {auto_increment},
                        provider_id VARCHAR(255) NOT NULL,
                        model_name VARCHAR(255) NOT NULL,
                        context_size INTEGER,
                        condense_context INTEGER,
                        condense_method TEXT,
                        effective_context INTEGER DEFAULT 0,
                        last_updated TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(provider_id, model_name)
                    )
                ''')
                logger.info("✅ Migration: Created context_dimensions table")
    except Exception as e:
        logger.warning(f"Migration check for context_dimensions table: {e}")

    # Migration: Create user_provider_usage table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(user_provider_usage)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE user_provider_usage (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER,
                        provider_id VARCHAR(255) NOT NULL,
                        usage_data TEXT NOT NULL,
                        last_updated TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(user_id, provider_id)
                    )
                ''')
                logger.info("✅ Migration: Created user_provider_usage table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_provider_usage'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE user_provider_usage (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER,
                        provider_id VARCHAR(255) NOT NULL,
                        usage_data TEXT NOT NULL,
                        last_updated TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(user_id, provider_id)
                    )
                ''')
                logger.info("✅ Migration: Created user_provider_usage table")
    except Exception as e:
        logger.warning(f"Migration check for user_provider_usage table: {e}")

    # Migration: Create provider_disabled_state table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(provider_disabled_state)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE provider_disabled_state (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER,
                        provider_id VARCHAR(255) NOT NULL,
                        disabled_until REAL,
                        disable_reason VARCHAR(255),
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(user_id, provider_id)
                    )
                ''')
                logger.info("✅ Migration: Created provider_disabled_state table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'provider_disabled_state'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE provider_disabled_state (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER,
                        provider_id VARCHAR(255) NOT NULL,
                        disabled_until DOUBLE,
                        disable_reason VARCHAR(255),
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(user_id, provider_id)
                    )
                ''')
                logger.info("✅ Migration: Created provider_disabled_state table")
    except Exception as e:
        logger.warning(f"Migration check for provider_disabled_state table: {e}")

    # Migration: Create runpod_provider_state table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(runpod_provider_state)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE runpod_provider_state (
                        id INTEGER PRIMARY KEY {auto_increment},
                        provider_scope VARCHAR(16) NOT NULL,
                        owner_user_id INTEGER,
                        provider_id VARCHAR(255) NOT NULL,
                        mode VARCHAR(64) NOT NULL,
                        wrapper_mode VARCHAR(64),
                        resource_id VARCHAR(255),
                        resource_kind VARCHAR(64) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        endpoint_url TEXT,
                        public_catalog_json TEXT,
                        metadata TEXT,
                        last_used_at REAL,
                        last_status_sync_at REAL,
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(owner_user_id, provider_id)
                    )
                ''')
                logger.info("✅ Migration: Created runpod_provider_state table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'runpod_provider_state'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE runpod_provider_state (
                        id INTEGER PRIMARY KEY {auto_increment},
                        provider_scope VARCHAR(16) NOT NULL,
                        owner_user_id INTEGER NULL,
                        provider_id VARCHAR(255) NOT NULL,
                        mode VARCHAR(64) NOT NULL,
                        wrapper_mode VARCHAR(64) NULL,
                        resource_id VARCHAR(255) NULL,
                        resource_kind VARCHAR(64) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        endpoint_url TEXT NULL,
                        public_catalog_json LONGTEXT NULL,
                        metadata LONGTEXT NULL,
                        last_used_at DOUBLE NULL,
                        last_status_sync_at DOUBLE NULL,
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE KEY uniq_runpod_provider_state (owner_user_id, provider_id)
                    )
                ''')
                logger.info("✅ Migration: Created runpod_provider_state table")
    except Exception as e:
        logger.warning(f"Migration check for runpod_provider_state table: {e}")

    # Migration: Create user_sort_order table if missing
    try:
        if self.db_type == 'sqlite':
            cursor.execute("PRAGMA table_info(user_sort_order)")
            if not cursor.fetchall():
                cursor.execute(f'''
                    CREATE TABLE user_sort_order (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER,
                        entity_type VARCHAR(50) NOT NULL,
                        ordered_ids TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT {timestamp_default}
                    )
                ''')
                logger.info("✅ Migration: Created user_sort_order table")
        else:
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sort_order'
            """)
            if not cursor.fetchone():
                cursor.execute(f'''
                    CREATE TABLE user_sort_order (
                        id INTEGER PRIMARY KEY {auto_increment},
                        user_id INTEGER,
                        entity_type VARCHAR(50) NOT NULL,
                        ordered_ids TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT {timestamp_default},
                        UNIQUE(user_id, entity_type)
                    )
                ''')
                logger.info("✅ Migration: Created user_sort_order table")
    except Exception as e:
        logger.warning(f"Migration check for user_sort_order table: {e}")

    logger.info("✅ All database migrations completed")

# Patch the methods
DatabaseManager._initialize_database = DatabaseManager__initialize_database
DatabaseManager._create_cache_tables = DatabaseManager__create_cache_tables
DatabaseManager._run_config_migrations = DatabaseManager__run_config_migrations
