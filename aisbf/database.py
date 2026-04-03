"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Database module for persistent tracking of context dimensions and rate limiting.

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
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import logging

try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    mysql = None

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database for persistent tracking of context dimensions and rate limiting.

    Supports both SQLite and MySQL databases.
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
        self.connection = None

        if self.db_type == 'mysql' and not MYSQL_AVAILABLE:
            raise ImportError("MySQL connector not available. Install mysql-connector-python.")

        self._initialize_database()
        logger.info(f"Database initialized: {self.db_type}")

    def _get_connection(self):
        """Get a database connection based on the configured type."""
        if self.db_type == 'sqlite':
            db_path = Path(self.db_config['sqlite_path']).expanduser()
            return sqlite3.connect(str(db_path))
        elif self.db_type == 'mysql':
            return mysql.connector.connect(
                host=self.db_config['mysql_host'],
                port=self.db_config['mysql_port'],
                user=self.db_config['mysql_user'],
                password=self.db_config['mysql_password'],
                database=self.db_config['mysql_database']
            )
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

    def _initialize_database(self):
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if self.db_type == 'sqlite':
                # Enable WAL mode for better concurrent access
                # WAL allows multiple readers and one writer simultaneously
                cursor.execute('PRAGMA journal_mode=WAL')

                # Set busy timeout to 5 seconds for concurrent access
                cursor.execute('PRAGMA busy_timeout=5000')
                auto_increment = 'AUTOINCREMENT'
                timestamp_default = 'CURRENT_TIMESTAMP'
                boolean_type = 'BOOLEAN'
            else:  # mysql
                auto_increment = 'AUTO_INCREMENT'
                timestamp_default = 'CURRENT_TIMESTAMP'
                boolean_type = 'TINYINT(1)'

            # Create context_dimensions table for tracking context usage
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS context_dimensions (
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

            # Create token_usage table for tracking rate limiting
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY {auto_increment},
                    user_id INTEGER,
                    provider_id VARCHAR(255) NOT NULL,
                    model_name VARCHAR(255) NOT NULL,
                    tokens_used INTEGER NOT NULL,
                    timestamp TIMESTAMP DEFAULT {timestamp_default}
                )
            ''')

            # Migration: Add user_id column to token_usage if it doesn't exist
            # This handles databases created before the user_id column was added
            try:
                if self.db_type == 'sqlite':
                    cursor.execute("PRAGMA table_info(token_usage)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'user_id' not in columns:
                        cursor.execute('ALTER TABLE token_usage ADD COLUMN user_id INTEGER')
                        logger.info("Migration: Added user_id column to token_usage table")
                else:  # mysql
                    cursor.execute("""
                        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'token_usage' AND COLUMN_NAME = 'user_id'
                    """)
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE token_usage ADD COLUMN user_id INTEGER')
                        logger.info("Migration: Added user_id column to token_usage table")
            except Exception as e:
                logger.warning(f"Migration check for token_usage.user_id: {e}")

            # Create indexes for token_usage
            try:
                cursor.execute('''
                    CREATE INDEX idx_token_user
                    ON token_usage(user_id)
                ''')
            except:
                pass

            # Create indexes for better query performance
            try:
                cursor.execute('''
                    CREATE INDEX idx_context_provider_model
                    ON context_dimensions(provider_id, model_name)
                ''')
            except:
                pass  # Index might already exist

            try:
                cursor.execute('''
                    CREATE INDEX idx_token_provider_model
                    ON token_usage(provider_id, model_name)
                ''')
            except:
                pass

            try:
                cursor.execute('''
                    CREATE INDEX idx_token_timestamp
                    ON token_usage(timestamp)
                ''')
            except:
                pass

            # Create model_embeddings table for caching vectorized model descriptions
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS model_embeddings (
                    id INTEGER PRIMARY KEY {auto_increment},
                    provider_id VARCHAR(255) NOT NULL,
                    model_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    embedding TEXT,
                    last_updated TIMESTAMP DEFAULT {timestamp_default},
                    UNIQUE(provider_id, model_name)
                )
            ''')

            try:
                cursor.execute('''
                    CREATE INDEX idx_model_embeddings_provider_model
                    ON model_embeddings(provider_id, model_name)
                ''')
            except:
                pass

            # Create users table for multi-user management
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY {auto_increment},
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) DEFAULT 'user',
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    last_login TIMESTAMP NULL,
                    is_active {boolean_type} DEFAULT 1
                )
            ''')

            # User-specific configuration tables for multi-user isolation
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS user_providers (
                    id INTEGER PRIMARY KEY {auto_increment},
                    user_id INTEGER NOT NULL,
                    provider_id VARCHAR(255) NOT NULL,
                    config TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    updated_at TIMESTAMP DEFAULT {timestamp_default},
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, provider_id)
                )
            ''')

            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS user_rotations (
                    id INTEGER PRIMARY KEY {auto_increment},
                    user_id INTEGER NOT NULL,
                    rotation_id VARCHAR(255) NOT NULL,
                    config TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    updated_at TIMESTAMP DEFAULT {timestamp_default},
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, rotation_id)
                )
            ''')

            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS user_autoselects (
                    id INTEGER PRIMARY KEY {auto_increment},
                    user_id INTEGER NOT NULL,
                    autoselect_id VARCHAR(255) NOT NULL,
                    config TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    updated_at TIMESTAMP DEFAULT {timestamp_default},
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, autoselect_id)
                )
            ''')

            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS user_api_tokens (
                    id INTEGER PRIMARY KEY {auto_increment},
                    user_id INTEGER NOT NULL,
                    token VARCHAR(255) UNIQUE NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    last_used TIMESTAMP NULL,
                    is_active {boolean_type} DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')

            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS user_token_usage (
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
            ''')

            conn.commit()
            logger.info("Database tables initialized successfully")
            
            # Create user_auth_files table for storing authentication file metadata
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS user_auth_files (
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
            ''')
            
            try:
                cursor.execute('''
                    CREATE INDEX idx_user_auth_files_user_provider
                    ON user_auth_files(user_id, provider_id)
                ''')
            except:
                pass  # Index might already exist
            
            conn.commit()
            logger.info("User auth files table initialized")
    
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
        user_id: Optional[int] = None
    ):
        """
        Record token usage for rate limiting.

        Args:
            provider_id: The provider identifier
            model_name: The model name
            tokens_used: Number of tokens used in the request
            user_id: Optional user ID for user-specific tracking
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO token_usage (user_id, provider_id, model_name, tokens_used, timestamp)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
            ''', (user_id, provider_id, model_name, tokens_used))

            conn.commit()
            logger.debug(f"Recorded token usage for {provider_id}/{model_name}: {tokens_used} (user_id={user_id})")
    
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
    def authenticate_user(self, username: str, password_hash: str) -> Optional[Dict]:
        """
        Authenticate a user by username and password hash.

        Args:
            username: Username to authenticate
            password_hash: SHA256 hash of the password

        Returns:
            User dict if authenticated, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                SELECT id, username, role, is_active
                FROM users
                WHERE username = {placeholder} AND password_hash = {placeholder} AND is_active = 1
            ''', (username, password_hash))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'username': row[1],
                    'role': row[2],
                    'is_active': row[3]
                }
            return None

    def create_user(self, username: str, password_hash: str, role: str = 'user', created_by: str = None) -> int:
        """
        Create a new user.

        Args:
            username: Username for the new user
            password_hash: SHA256 hash of the password
            role: User role ('admin' or 'user')
            created_by: Username of the creator

        Returns:
            User ID of the created user
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO users (username, password_hash, role, created_by)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
            ''', (username, password_hash, role, created_by))
            conn.commit()
            return cursor.lastrowid

    def get_users(self) -> List[Dict]:
        """
        Get all users.

        Returns:
            List of user dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, username, role, created_by, created_at, last_login, is_active
                FROM users
                ORDER BY created_at DESC
            ''')

            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'role': row[2],
                    'created_by': row[3],
                    'created_at': row[4],
                    'last_login': row[5],
                    'is_active': row[6]
                })
            return users

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
            # Delete the user
            cursor.execute(f'DELETE FROM users WHERE id = {placeholder}', (user_id,))
            conn.commit()

    def update_user(self, user_id: int, username: str, password_hash: str = None, role: str = None, is_active: bool = None):
        """
        Update a user.

        Args:
            user_id: User ID to update
            username: New username
            password_hash: New password hash (optional)
            role: New role (optional)
            is_active: New active status (optional)
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
            
            params.append(user_id)
            
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = {placeholder}"
            cursor.execute(query, params)
            conn.commit()

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
                    'config': json.loads(row[1]),
                    'created_at': row[2],
                    'updated_at': row[3]
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

    # User API token methods
    def create_user_api_token(self, user_id: int, token: str, description: str = None) -> int:
        """
        Create a new API token for a user.

        Args:
            user_id: User ID
            token: The token string
            description: Optional description

        Returns:
            Token ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db_type == 'sqlite' else '%s'
            cursor.execute(f'''
                INSERT INTO user_api_tokens (user_id, token, description)
                VALUES ({placeholder}, {placeholder}, {placeholder})
            ''', (user_id, token, description))
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
                SELECT id, token, description, created_at, last_used, is_active
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
                    'is_active': row[5]
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
                SELECT u.id, u.username, u.role, t.id as token_id
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
                    'token_id': row[3]
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


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_database(db_config: Optional[Dict[str, Any]] = None) -> DatabaseManager:
    """
    Get the global database manager instance.

    Args:
        db_config: Database configuration. If None, uses default.

    Returns:
        The DatabaseManager instance
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(db_config)
    return _db_manager


def initialize_database(db_config: Optional[Dict[str, Any]] = None):
    """
    Initialize the database and clean up old records.
    This should be called at application startup.

    Args:
        db_config: Database configuration. If None, uses default.
    """
    db = get_database(db_config)
    db.cleanup_old_token_usage(days_to_keep=7)
    logger.info("Database initialized and old records cleaned up")