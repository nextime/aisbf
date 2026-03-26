"""
Cache module for AISBF with support for multiple backends (Redis, file-based, memory).

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
"""

import json
import pickle
import logging
from typing import Any, Optional, Dict, List
from pathlib import Path
import time

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    mysql = None

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


class CacheBackend:
    """Abstract base class for cache backends"""

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with optional TTL"""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Delete value from cache"""
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        raise NotImplementedError

    def clear(self) -> None:
        """Clear all cache entries"""
        raise NotImplementedError


class MemoryCache(CacheBackend):
    """In-memory cache backend"""

    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            return self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._cache[key] = value
        if ttl:
            self._timestamps[key] = time.time() + ttl

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

    def exists(self, key: str) -> bool:
        if key in self._timestamps:
            if time.time() > self._timestamps[key]:
                self.delete(key)
                return False
        return key in self._cache

    def clear(self) -> None:
        self._cache.clear()
        self._timestamps.clear()


class RedisCache(CacheBackend):
    """Redis cache backend"""

    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0,
                 password: str = '', key_prefix: str = ''):
        if not REDIS_AVAILABLE:
            raise ImportError("Redis is not available. Install redis package.")

        self.key_prefix = key_prefix
        self.redis = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password if password else None,
            decode_responses=False  # We'll handle serialization ourselves
        )

        # Test connection
        try:
            self.redis.ping()
            logger.info(f"Connected to Redis at {host}:{port}")
        except redis.ConnectionError as e:
            logger.warning(f"Redis connection failed: {e}")
            raise

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        try:
            data = self.redis.get(self._make_key(key))
            if data:
                return pickle.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        try:
            data = pickle.dumps(value)
            if ttl:
                self.redis.setex(self._make_key(key), ttl, data)
            else:
                self.redis.set(self._make_key(key), data)
        except Exception as e:
            logger.warning(f"Redis set error: {e}")

    def delete(self, key: str) -> None:
        try:
            self.redis.delete(self._make_key(key))
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")

    def exists(self, key: str) -> bool:
        try:
            return bool(self.redis.exists(self._make_key(key)))
        except Exception as e:
            logger.warning(f"Redis exists error: {e}")
            return False

    def clear(self) -> None:
        try:
            keys = self.redis.keys(f"{self.key_prefix}*")
            if keys:
                self.redis.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")


class SQLiteCache(CacheBackend):
    """SQLite cache backend"""

    def __init__(self, db_path: str = '~/.aisbf/cache.db'):
        import sqlite3
        from pathlib import Path

        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()
        logger.info(f"Connected to SQLite cache at {self.db_path}")

    def _init_db(self):
        """Initialize the SQLite database and create tables"""
        import sqlite3

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()

            # Enable WAL mode for better concurrent access
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA busy_timeout=5000')

            # Create cache table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ttl REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')

            # Create index for TTL cleanup
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_cache_ttl
                ON cache(ttl)
            ''')

            conn.commit()

    def _cleanup_expired(self):
        """Clean up expired cache entries"""
        import sqlite3
        import time

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cache WHERE ttl IS NOT NULL AND ttl < ?', (time.time(),))
            conn.commit()

    def get(self, key: str) -> Optional[Any]:
        import sqlite3
        import time

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()

                # Clean up expired entries first
                self._cleanup_expired()

                cursor.execute('SELECT value, ttl FROM cache WHERE key = ?', (key,))
                row = cursor.fetchone()

                if row:
                    value_str, ttl = row
                    # Check if entry has expired
                    if ttl and time.time() > ttl:
                        cursor.execute('DELETE FROM cache WHERE key = ?', (key,))
                        conn.commit()
                        return None

                    # Deserialize the value
                    return pickle.loads(value_str.encode('latin1'))

                return None
        except Exception as e:
            logger.warning(f"SQLite cache get error for {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        import sqlite3
        import time

        try:
            # Serialize the value
            value_bytes = pickle.dumps(value)
            value_str = value_bytes.decode('latin1')

            # Calculate TTL timestamp if provided
            ttl_timestamp = time.time() + ttl if ttl else None

            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO cache (key, value, ttl, created_at)
                    VALUES (?, ?, ?, strftime('%s', 'now'))
                ''', (key, value_str, ttl_timestamp))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite cache set error for {key}: {e}")

    def delete(self, key: str) -> None:
        import sqlite3

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cache WHERE key = ?', (key,))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite cache delete error for {key}: {e}")

    def exists(self, key: str) -> bool:
        import sqlite3
        import time

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()

                # Clean up expired entries first
                self._cleanup_expired()

                cursor.execute('SELECT ttl FROM cache WHERE key = ?', (key,))
                row = cursor.fetchone()

                if row:
                    ttl = row[0]
                    # Check if entry has expired
                    if ttl and time.time() > ttl:
                        cursor.execute('DELETE FROM cache WHERE key = ?', (key,))
                        conn.commit()
                        return False
                    return True

                return False
        except Exception as e:
            logger.warning(f"SQLite cache exists error for {key}: {e}")
            return False

    def clear(self) -> None:
        import sqlite3

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cache')
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite cache clear error: {e}")


class MySQLCache(CacheBackend):
    """MySQL cache backend"""

    def __init__(self, host: str = 'localhost', port: int = 3306, user: str = 'aisbf',
                 password: str = '', database: str = 'aisbf_cache'):
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL connector not available. Install mysql-connector-python.")

        self.mysql_config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database
        }

        # Initialize database
        self._init_db()
        logger.info(f"Connected to MySQL cache at {host}:{port}")

    def _init_db(self):
        """Initialize the MySQL database and create tables"""
        try:
            # Try to connect to the database
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()

            # Create cache table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cache (
                    `key` VARCHAR(255) PRIMARY KEY,
                    `value` LONGTEXT NOT NULL,
                    ttl DOUBLE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create index for TTL cleanup
            cursor.execute('''
                CREATE INDEX idx_cache_ttl_mysql
                ON cache(ttl)
            ''')

            conn.commit()
            cursor.close()
            conn.close()
        except mysql.connector.Error as e:
            if e.errno == 1049:  # Unknown database
                # Try to create the database
                temp_config = self.mysql_config.copy()
                del temp_config['database']
                conn = mysql.connector.connect(**temp_config)
                cursor = conn.cursor()
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.mysql_config['database']}`")
                conn.commit()
                cursor.close()
                conn.close()

                # Now try again with the database
                self._init_db()
            else:
                raise

    def _cleanup_expired(self):
        """Clean up expired cache entries"""
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cache WHERE ttl IS NOT NULL AND ttl < UNIX_TIMESTAMP()')
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL cleanup error: {e}")

    def get(self, key: str) -> Optional[Any]:
        import time

        try:
            self._cleanup_expired()

            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('SELECT `value`, ttl FROM cache WHERE `key` = %s', (key,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if row:
                value_str, ttl = row
                # Check if entry has expired
                if ttl and time.time() > ttl:
                    self.delete(key)
                    return None

                # Deserialize the value
                return pickle.loads(value_str.encode('latin1'))

            return None
        except Exception as e:
            logger.warning(f"MySQL cache get error for {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        import time

        try:
            # Serialize the value
            value_bytes = pickle.dumps(value)
            value_str = value_bytes.decode('latin1')

            # Calculate TTL timestamp if provided
            ttl_timestamp = time.time() + ttl if ttl else None

            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO cache (`key`, `value`, ttl)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE `value`=VALUES(`value`), ttl=VALUES(ttl)
            ''', (key, value_str, ttl_timestamp))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL cache set error for {key}: {e}")

    def delete(self, key: str) -> None:
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cache WHERE `key` = %s', (key,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL cache delete error for {key}: {e}")

    def exists(self, key: str) -> bool:
        import time

        try:
            self._cleanup_expired()

            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('SELECT ttl FROM cache WHERE `key` = %s', (key,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if row:
                ttl = row[0]
                # Check if entry has expired
                if ttl and time.time() > ttl:
                    self.delete(key)
                    return False
                return True

            return False
        except Exception as e:
            logger.warning(f"MySQL cache exists error for {key}: {e}")
            return False

    def clear(self) -> None:
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cache')
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL cache clear error: {e}")


class FileCache(CacheBackend):
    """File-based cache backend using JSON/pickle"""

    def __init__(self, cache_dir: str = '~/.aisbf/cache'):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, key: str) -> Path:
        # Sanitize key for filename
        safe_key = key.replace('/', '_').replace('\\', '_').replace(':', '_')
        return self.cache_dir / f"{safe_key}.cache"

    def get(self, key: str) -> Optional[Any]:
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"File cache get error for {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(value, f)
        except Exception as e:
            logger.warning(f"File cache set error for {key}: {e}")

    def delete(self, key: str) -> None:
        cache_path = self._get_cache_path(key)
        try:
            cache_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"File cache delete error for {key}: {e}")

    def exists(self, key: str) -> bool:
        cache_path = self._get_cache_path(key)
        return cache_path.exists()

    def clear(self) -> None:
        try:
            for cache_file in self.cache_dir.glob('*.cache'):
                cache_file.unlink()
        except Exception as e:
            logger.warning(f"File cache clear error: {e}")


class NumpyFileCache:
    """Specialized cache for numpy arrays (for model embeddings)"""

    def __init__(self, cache_dir: str = '~/.aisbf/cache'):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def save_array(self, key: str, array: Any, metadata: Optional[Dict] = None) -> None:
        """Save numpy array with optional metadata"""
        if not NUMPY_AVAILABLE:
            raise ImportError("NumPy is not available")

        base_path = self.cache_dir / key
        array_path = base_path.with_suffix('.npy')
        meta_path = base_path.with_suffix('.meta')

        try:
            np.save(array_path, array)
            if metadata:
                with open(meta_path, 'w') as f:
                    json.dump(metadata, f)
        except Exception as e:
            logger.warning(f"Numpy cache save error for {key}: {e}")

    def load_array(self, key: str) -> tuple[Optional[Any], Optional[Dict]]:
        """Load numpy array and metadata"""
        if not NUMPY_AVAILABLE:
            return None, None

        base_path = self.cache_dir / key
        array_path = base_path.with_suffix('.npy')
        meta_path = base_path.with_suffix('.meta')

        if not array_path.exists():
            return None, None

        try:
            array = np.load(array_path)

            metadata = None
            if meta_path.exists():
                with open(meta_path, 'r') as f:
                    metadata = json.load(f)

            return array, metadata
        except Exception as e:
            logger.warning(f"Numpy cache load error for {key}: {e}")
            return None, None

    def exists(self, key: str) -> bool:
        base_path = self.cache_dir / key
        return base_path.with_suffix('.npy').exists()

    def delete(self, key: str) -> None:
        base_path = self.cache_dir / key
        try:
            base_path.with_suffix('.npy').unlink(missing_ok=True)
            base_path.with_suffix('.meta').unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Numpy cache delete error for {key}: {e}")


class CacheManager:
    """Unified cache manager with support for multiple backends"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {
            'type': 'sqlite',
            'sqlite_path': '~/.aisbf/cache.db',
            'redis_host': 'localhost',
            'redis_port': 6379,
            'redis_db': 0,
            'redis_password': '',
            'redis_key_prefix': 'aisbf:',
            'mysql_host': 'localhost',
            'mysql_port': 3306,
            'mysql_user': 'aisbf',
            'mysql_password': '',
            'mysql_database': 'aisbf_cache'
        }

        self.cache_type = self.config.get('type', 'sqlite')
        self._backend = None
        self._numpy_cache = None

    @property
    def backend(self) -> CacheBackend:
        if self._backend is None:
            self._backend = self._create_backend()
        return self._backend

    @property
    def numpy_cache(self) -> NumpyFileCache:
        if self._numpy_cache is None:
            self._numpy_cache = NumpyFileCache()
        return self._numpy_cache

    def _create_backend(self) -> CacheBackend:
        """Create appropriate cache backend based on configuration"""
        cache_type = self.cache_type.lower()

        if cache_type == 'redis':
            try:
                return RedisCache(
                    host=self.config.get('redis_host', 'localhost'),
                    port=self.config.get('redis_port', 6379),
                    db=self.config.get('redis_db', 0),
                    password=self.config.get('redis_password', ''),
                    key_prefix=self.config.get('redis_key_prefix', 'aisbf:')
                )
            except Exception as e:
                logger.warning(f"Failed to create Redis cache, falling back to SQLite: {e}")
                return SQLiteCache()

        elif cache_type == 'mysql':
            try:
                return MySQLCache(
                    host=self.config.get('mysql_host', 'localhost'),
                    port=self.config.get('mysql_port', 3306),
                    user=self.config.get('mysql_user', 'aisbf'),
                    password=self.config.get('mysql_password', ''),
                    database=self.config.get('mysql_database', 'aisbf_cache')
                )
            except Exception as e:
                logger.warning(f"Failed to create MySQL cache, falling back to SQLite: {e}")
                return SQLiteCache()

        elif cache_type == 'file':
            return FileCache()

        elif cache_type == 'sqlite':
            return SQLiteCache(self.config.get('sqlite_path', '~/.aisbf/cache.db'))

        else:  # memory or unknown
            return MemoryCache()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        return self.backend.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with optional TTL"""
        self.backend.set(key, value, ttl)

    def delete(self, key: str) -> None:
        """Delete value from cache"""
        self.backend.delete(key)

    def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        return self.backend.exists(key)

    def clear(self) -> None:
        """Clear all cache entries"""
        self.backend.clear()

    # Numpy-specific methods
    def save_numpy_array(self, key: str, array: Any, metadata: Optional[Dict] = None) -> None:
        """Save numpy array (fallback to file-based even with Redis)"""
        self.numpy_cache.save_array(key, array, metadata)

    def load_numpy_array(self, key: str) -> tuple[Optional[Any], Optional[Dict]]:
        """Load numpy array"""
        return self.numpy_cache.load_array(key)

    def numpy_array_exists(self, key: str) -> bool:
        """Check if numpy array exists"""
        return self.numpy_cache.exists(key)


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager(config: Optional[Dict] = None) -> CacheManager:
    """Get the global cache manager instance"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(config)
    return _cache_manager


def initialize_cache(config: Optional[Dict] = None):
    """Initialize the cache system"""
    global _cache_manager
    _cache_manager = CacheManager(config)
    logger.info(f"Cache initialized: {config.get('type', 'memory') if config else 'memory'}")