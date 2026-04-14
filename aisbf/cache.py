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
    import mysql.connector as _mysql_connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    _mysql_connector = None

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
            conn = _mysql_connector.connect(**self.mysql_config)
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
        except _mysql_connector.Error as e:
            if e.errno == 1049:  # Unknown database
                # Try to create the database
                temp_config = self.mysql_config.copy()
                del temp_config['database']
                conn = _mysql_connector.connect(**temp_config)
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
            conn = _mysql_connector.connect(**self.mysql_config)
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

            conn = _mysql_connector.connect(**self.mysql_config)
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

            conn = _mysql_connector.connect(**self.mysql_config)
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
            conn = _mysql_connector.connect(**self.mysql_config)
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

            conn = _mysql_connector.connect(**self.mysql_config)
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
            conn = _mysql_connector.connect(**self.mysql_config)
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


class NumpyCacheBackend:
    """Abstract base class for numpy array cache backends"""
    def save_array(self, key: str, array: Any, metadata: Optional[Dict] = None) -> None:
        raise NotImplementedError

    def load_array(self, key: str) -> tuple[Optional[Any], Optional[Dict]]:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class NumpyFileCache(NumpyCacheBackend):
    """File-based cache for numpy arrays (for model embeddings)"""

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


class NumpyRedisCache(NumpyCacheBackend):
    """Redis-based cache for numpy arrays"""

    def __init__(self, redis_client, key_prefix: str = 'aisbf:numpy:'):
        self.redis = redis_client
        self.key_prefix = key_prefix

    def _make_key(self, key: str, suffix: str = '') -> str:
        return f"{self.key_prefix}{key}{suffix}"

    def save_array(self, key: str, array: Any, metadata: Optional[Dict] = None) -> None:
        """Save numpy array with optional metadata to Redis"""
        if not NUMPY_AVAILABLE:
            raise ImportError("NumPy is not available")

        try:
            # Serialize numpy array to bytes
            import io
            buf = io.BytesIO()
            np.save(buf, array)
            buf.seek(0)
            array_bytes = buf.read()

            # Store array
            self.redis.set(self._make_key(key), array_bytes)

            # Store metadata if present
            if metadata:
                self.redis.set(self._make_key(key, ':meta'), json.dumps(metadata))

        except Exception as e:
            logger.warning(f"Numpy Redis cache save error for {key}: {e}")

    def load_array(self, key: str) -> tuple[Optional[Any], Optional[Dict]]:
        """Load numpy array and metadata from Redis"""
        if not NUMPY_AVAILABLE:
            return None, None

        try:
            array_bytes = self.redis.get(self._make_key(key))
            if not array_bytes:
                return None, None

            import io
            buf = io.BytesIO(array_bytes)
            array = np.load(buf)

            metadata = None
            meta_bytes = self.redis.get(self._make_key(key, ':meta'))
            if meta_bytes:
                metadata = json.loads(meta_bytes)

            return array, metadata
        except Exception as e:
            logger.warning(f"Numpy Redis cache load error for {key}: {e}")
            return None, None

    def exists(self, key: str) -> bool:
        return bool(self.redis.exists(self._make_key(key)))

    def delete(self, key: str) -> None:
        try:
            self.redis.delete(self._make_key(key))
            self.redis.delete(self._make_key(key, ':meta'))
        except Exception as e:
            logger.warning(f"Numpy Redis cache delete error for {key}: {e}")


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
    def numpy_cache(self) -> NumpyCacheBackend:
        if self._numpy_cache is None:
            self._numpy_cache = self._create_numpy_backend()
        return self._numpy_cache

    def _create_numpy_backend(self) -> NumpyCacheBackend:
        """Create appropriate numpy cache backend based on configuration"""
        cache_type = self.cache_type.lower()

        if cache_type == 'redis' and REDIS_AVAILABLE:
            try:
                redis_client = redis.Redis(
                    host=self.config.get('redis_host', 'localhost'),
                    port=self.config.get('redis_port', 6379),
                    db=self.config.get('redis_db', 0),
                    password=self.config.get('redis_password', ''),
                    decode_responses=False
                )
                # Test connection
                redis_client.ping()
                return NumpyRedisCache(
                    redis_client,
                    key_prefix=self.config.get('redis_key_prefix', 'aisbf:') + 'numpy:'
                )
            except Exception as e:
                logger.warning(f"Failed to create Redis numpy cache, falling back to file: {e}")

        # Default to file cache for all other backends
        return NumpyFileCache()

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


# =============================================================================
# Response Cache - Semantic deduplication for AI responses
# (merged from response_cache.py)
# =============================================================================

import hashlib
from typing import Tuple
from functools import lru_cache


class SQLiteResponseCache:
    """SQLite backend for response cache"""
    
    def __init__(self, db_path: str = '~/.aisbf/response_cache.db'):
        import sqlite3
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"Response cache initialized with SQLite backend at {self.db_path}")
    
    def _init_db(self):
        """Initialize SQLite database"""
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA busy_timeout=5000')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS response_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ttl REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_response_cache_ttl
                ON response_cache(ttl)
            ''')
            conn.commit()
    
    def _cleanup_expired(self):
        """Clean up expired entries"""
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM response_cache WHERE ttl IS NOT NULL AND ttl < ?', (time.time(),))
            conn.commit()
    
    def get(self, key: str) -> Optional[Dict]:
        """Get cached response"""
        import sqlite3
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                self._cleanup_expired()
                cursor.execute('SELECT value, ttl FROM response_cache WHERE key = ?', (key,))
                row = cursor.fetchone()
                if row:
                    value_str, ttl = row
                    if ttl and time.time() > ttl:
                        cursor.execute('DELETE FROM response_cache WHERE key = ?', (key,))
                        conn.commit()
                        return None
                    return json.loads(value_str)
                return None
        except Exception as e:
            logger.warning(f"SQLite response cache get error: {e}")
            return None
    
    def set(self, key: str, value: Dict, ttl: int = 600) -> None:
        """Set cached response"""
        import sqlite3
        try:
            value_str = json.dumps(value, ensure_ascii=False)
            ttl_timestamp = time.time() + ttl
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO response_cache (key, value, ttl, created_at)
                    VALUES (?, ?, ?, strftime('%s', 'now'))
                ''', (key, value_str, ttl_timestamp))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite response cache set error: {e}")
    
    def delete(self, key: str) -> None:
        """Delete cached response"""
        import sqlite3
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM response_cache WHERE key = ?', (key,))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite response cache delete error: {e}")
    
    def clear(self) -> None:
        """Clear all cached responses"""
        import sqlite3
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM response_cache')
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite response cache clear error: {e}")
    
    def get_size(self) -> int:
        """Get number of cached items"""
        import sqlite3
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM response_cache')
                return cursor.fetchone()[0]
        except Exception as e:
            logger.warning(f"SQLite response cache size error: {e}")
            return 0


class MySQLResponseCache:
    """MySQL backend for response cache"""
    
    def __init__(self, host: str = 'localhost', port: int = 3306, user: str = 'aisbf',
                 password: str = '', database: str = 'aisbf_response_cache'):
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL connector not available. Install mysql-connector-python.")
        
        self.mysql_config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database
        }
        self._init_db()
        logger.info(f"Response cache initialized with MySQL backend at {host}:{port}")
    
    def _init_db(self):
        """Initialize MySQL database"""
        try:
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS response_cache (
                    `key` VARCHAR(255) PRIMARY KEY,
                    `value` LONGTEXT NOT NULL,
                    ttl DOUBLE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX idx_response_cache_ttl_mysql
                ON response_cache(ttl)
            ''')
            conn.commit()
            cursor.close()
            conn.close()
        except _mysql_connector.Error as e:
            if e.errno == 1049:
                temp_config = self.mysql_config.copy()
                del temp_config['database']
                conn = _mysql_connector.connect(**temp_config)
                cursor = conn.cursor()
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.mysql_config['database']}`")
                conn.commit()
                cursor.close()
                conn.close()
                self._init_db()
            else:
                raise
    
    def _cleanup_expired(self):
        """Clean up expired entries"""
        try:
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM response_cache WHERE ttl IS NOT NULL AND ttl < UNIX_TIMESTAMP()')
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL response cache cleanup error: {e}")
    
    def get(self, key: str) -> Optional[Dict]:
        """Get cached response"""
        try:
            self._cleanup_expired()
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('SELECT `value`, ttl FROM response_cache WHERE `key` = %s', (key,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            if row:
                value_str, ttl = row
                if ttl and time.time() > ttl:
                    self.delete(key)
                    return None
                return json.loads(value_str)
            return None
        except Exception as e:
            logger.warning(f"MySQL response cache get error: {e}")
            return None
    
    def set(self, key: str, value: Dict, ttl: int = 600) -> None:
        """Set cached response"""
        try:
            value_str = json.dumps(value, ensure_ascii=False)
            ttl_timestamp = time.time() + ttl
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO response_cache (`key`, `value`, ttl)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE `value`=VALUES(`value`), ttl=VALUES(ttl)
            ''', (key, value_str, ttl_timestamp))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL response cache set error: {e}")
    
    def delete(self, key: str) -> None:
        """Delete cached response"""
        try:
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM response_cache WHERE `key` = %s', (key,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL response cache delete error: {e}")
    
    def clear(self) -> None:
        """Clear all cached responses"""
        try:
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM response_cache')
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"MySQL response cache clear error: {e}")
    
    def get_size(self) -> int:
        """Get number of cached items"""
        try:
            conn = _mysql_connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM response_cache')
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            return count
        except Exception as e:
            logger.warning(f"MySQL response cache size error: {e}")
            return 0


class ResponseCache:
    """
    Response cache for AISBF with semantic deduplication support.

    Features:
    - Redis backend with in-memory LRU fallback
    - Semantic deduplication using message content hashing
    - TTL support (default: 5-10 minutes)
    - Cache statistics tracking
    - Thread-safe operations
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the response cache.

        Args:
            config: Cache configuration with keys:
                - enabled: Whether caching is enabled (default: True)
                - backend: 'redis', 'memory', 'sqlite', or 'mysql' (default: 'redis')
                - redis_host: Redis host (default: 'localhost')
                - redis_port: Redis port (default: 6379)
                - redis_db: Redis database (default: 0)
                - redis_password: Redis password (default: None)
                - redis_key_prefix: Key prefix (default: 'aisbf:response:')
                - sqlite_path: SQLite database path (default: '~/.aisbf/response_cache.db')
                - mysql_host: MySQL host (default: 'localhost')
                - mysql_port: MySQL port (default: 3306)
                - mysql_user: MySQL user (default: 'aisbf')
                - mysql_password: MySQL password (default: '')
                - mysql_database: MySQL database (default: 'aisbf_response_cache')
                - ttl: Default TTL in seconds (default: 600)
                - max_memory_cache: Max items for memory cache (default: 1000)
        """
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        self.backend = self.config.get('backend', 'redis')
        self.default_ttl = self.config.get('ttl', 600)  # 10 minutes default
        self.max_memory_cache = self.config.get('max_memory_cache', self.config.get('max_size', 1000))

        # Cache statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0,
            'errors': 0
        }

        # Initialize backends
        self.redis_client = None
        self.sqlite_backend = None
        self.mysql_backend = None
        self.memory_cache = {}

        if not self.enabled:
            logger.info("Response caching is disabled")
            return

        if self.backend == 'redis' and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.Redis(
                    host=self.config.get('redis_host', 'localhost'),
                    port=self.config.get('redis_port', 6379),
                    db=self.config.get('redis_db', 0),
                    password=self.config.get('redis_password'),
                    decode_responses=False  # We'll handle serialization
                )
                # Test connection
                self.redis_client.ping()
                self.key_prefix = self.config.get('redis_key_prefix', 'aisbf:response:')
                logger.info(f"Response cache initialized with Redis backend (prefix: {self.key_prefix})")
            except Exception as e:
                logger.warning(f"Redis connection failed, falling back to memory cache: {e}")
                self.backend = 'memory'
        elif self.backend == 'sqlite':
            try:
                self.sqlite_backend = SQLiteResponseCache(
                    db_path=self.config.get('sqlite_path', '~/.aisbf/response_cache.db')
                )
                logger.info("Response cache initialized with SQLite backend")
            except Exception as e:
                logger.warning(f"SQLite initialization failed, falling back to memory cache: {e}")
                self.backend = 'memory'
        elif self.backend == 'mysql' and MYSQL_AVAILABLE:
            try:
                self.mysql_backend = MySQLResponseCache(
                    host=self.config.get('mysql_host', 'localhost'),
                    port=self.config.get('mysql_port', 3306),
                    user=self.config.get('mysql_user', 'aisbf'),
                    password=self.config.get('mysql_password', ''),
                    database=self.config.get('mysql_database', 'aisbf_response_cache')
                )
                logger.info("Response cache initialized with MySQL backend")
            except Exception as e:
                logger.warning(f"MySQL initialization failed, falling back to memory cache: {e}")
                self.backend = 'memory'
        elif self.backend not in ['redis', 'sqlite', 'mysql']:
            self.backend = 'memory'

        if self.backend == 'memory':
            # Initialize LRU cache
            self._memory_cache = {}
            self._memory_timestamps = {}
            self._memory_access_order = []
            logger.info(f"Response cache initialized with memory backend (max: {self.max_memory_cache} items)")

    def _generate_cache_key(self, request_data: Dict) -> str:
        """
        Generate a cache key from request data using semantic deduplication.

        The key is based on:
        - model
        - messages content (hashed for semantic deduplication)
        - temperature (normalized)
        - max_tokens
        - tools (if present)
        - tool_choice (if present)

        Args:
            request_data: The request data dict

        Returns:
            Cache key string
        """
        # Extract key components
        model = request_data.get('model', '')
        messages = request_data.get('messages', [])
        temperature = request_data.get('temperature', 1.0)
        max_tokens = request_data.get('max_tokens')
        tools = request_data.get('tools')
        tool_choice = request_data.get('tool_choice')

        # Normalize temperature to reduce cache fragmentation
        # Group similar temperatures together (e.g., 0.7-0.8 -> 0.75)
        if isinstance(temperature, (int, float)):
            temperature = round(temperature * 4) / 4  # Round to nearest 0.25

        # Create message content hash for semantic deduplication
        # Include only the text content of messages, ignore metadata
        message_texts = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get('role', '')
                content = msg.get('content', '')
                # Handle both string and list content (for multimodal)
                if isinstance(content, list):
                    # For multimodal content, extract text parts
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get('type') == 'text':
                            text_parts.append(part.get('text', ''))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = ' '.join(text_parts)
                message_texts.append(f"{role}:{content}")

        messages_content = '\n'.join(message_texts)
        messages_hash = hashlib.md5(messages_content.encode('utf-8')).hexdigest()[:16]

        # Build key components
        key_parts = [
            f"model:{model}",
            f"msgs:{messages_hash}",
            f"temp:{temperature}"
        ]

        if max_tokens is not None:
            key_parts.append(f"max_tokens:{max_tokens}")

        if tools:
            # Hash the tools structure for consistency
            tools_str = json.dumps(tools, sort_keys=True)
            tools_hash = hashlib.md5(tools_str.encode('utf-8')).hexdigest()[:8]
            key_parts.append(f"tools:{tools_hash}")

        if tool_choice:
            if isinstance(tool_choice, dict):
                tool_choice_str = json.dumps(tool_choice, sort_keys=True)
                tool_choice_hash = hashlib.md5(tool_choice_str.encode('utf-8')).hexdigest()[:8]
                key_parts.append(f"tool_choice:{tool_choice_hash}")
            else:
                key_parts.append(f"tool_choice:{tool_choice}")

        # Combine into final key
        cache_key = '|'.join(key_parts)

        # Add backend prefix
        if self.backend == 'redis':
            cache_key = f"{self.key_prefix}{cache_key}"

        return cache_key

    def _serialize_response(self, response: Dict) -> bytes:
        """Serialize response for storage"""
        return json.dumps(response, ensure_ascii=False).encode('utf-8')

    def _deserialize_response(self, data: bytes) -> Dict:
        """Deserialize response from storage"""
        return json.loads(data.decode('utf-8'))

    def _memory_cache_cleanup(self):
        """Clean up expired entries from memory cache"""
        current_time = time.time()
        expired_keys = []

        for key, timestamp in self._memory_timestamps.items():
            if current_time > timestamp:
                expired_keys.append(key)

        for key in expired_keys:
            self._memory_cache.pop(key, None)
            self._memory_timestamps.pop(key, None)
            if key in self._memory_access_order:
                self._memory_access_order.remove(key)

        # Also enforce max size (LRU eviction)
        while len(self._memory_cache) > self.max_memory_cache and self._memory_access_order:
            # Remove least recently used
            lru_key = self._memory_access_order.pop(0)
            self._memory_cache.pop(lru_key, None)
            self._memory_timestamps.pop(lru_key, None)

    def get(self, request_data: Dict) -> Optional[Dict]:
        """
        Get cached response for a request.

        Args:
            request_data: The request data dict

        Returns:
            Cached response dict or None if not found
        """
        if not self.enabled:
            return None

        try:
            cache_key = self._generate_cache_key(request_data)

            if self.backend == 'redis' and self.redis_client:
                # Try Redis first
                data = self.redis_client.get(cache_key)
                if data:
                    self.stats['hits'] += 1
                    logger.debug(f"Cache hit (Redis): {cache_key}")
                    return self._deserialize_response(data)
            elif self.backend == 'sqlite' and self.sqlite_backend:
                # Try SQLite backend
                data = self.sqlite_backend.get(cache_key)
                if data:
                    self.stats['hits'] += 1
                    logger.debug(f"Cache hit (SQLite): {cache_key}")
                    return data
            elif self.backend == 'mysql' and self.mysql_backend:
                # Try MySQL backend
                data = self.mysql_backend.get(cache_key)
                if data:
                    self.stats['hits'] += 1
                    logger.debug(f"Cache hit (MySQL): {cache_key}")
                    return data
            elif self.backend == 'memory':
                # Check memory cache
                self._memory_cache_cleanup()
                if cache_key in self._memory_cache:
                    # Check TTL
                    if cache_key in self._memory_timestamps:
                        if time.time() > self._memory_timestamps[cache_key]:
                            # Expired, remove it
                            self._memory_cache.pop(cache_key, None)
                            self._memory_timestamps.pop(cache_key, None)
                            if cache_key in self._memory_access_order:
                                self._memory_access_order.remove(cache_key)
                        else:
                            # Valid, update access order
                            if cache_key in self._memory_access_order:
                                self._memory_access_order.remove(cache_key)
                            self._memory_access_order.append(cache_key)

                            self.stats['hits'] += 1
                            logger.debug(f"Cache hit (Memory): {cache_key}")
                            return self._memory_cache[cache_key]

            self.stats['misses'] += 1
            logger.debug(f"Cache miss: {cache_key}")
            return None

        except Exception as e:
            self.stats['errors'] += 1
            logger.warning(f"Cache get error: {e}")
            return None

    def set(self, request_data: Dict, response: Dict, ttl: Optional[int] = None) -> None:
        """
        Cache a response.

        Args:
            request_data: The request data dict
            response: The response dict to cache
            ttl: TTL in seconds (uses default if None)
        """
        if not self.enabled:
            return

        # Don't cache streaming responses
        if request_data.get('stream', False):
            return

        # Don't cache error responses
        if isinstance(response, dict) and 'error' in response:
            return

        try:
            cache_key = self._generate_cache_key(request_data)
            ttl_value = ttl or self.default_ttl

            if self.backend == 'redis' and self.redis_client:
                data = self._serialize_response(response)
                self.redis_client.setex(cache_key, ttl_value, data)
                logger.debug(f"Cached response (Redis): {cache_key} (TTL: {ttl_value}s)")
            elif self.backend == 'sqlite' and self.sqlite_backend:
                self.sqlite_backend.set(cache_key, response, ttl_value)
                logger.debug(f"Cached response (SQLite): {cache_key} (TTL: {ttl_value}s)")
            elif self.backend == 'mysql' and self.mysql_backend:
                self.mysql_backend.set(cache_key, response, ttl_value)
                logger.debug(f"Cached response (MySQL): {cache_key} (TTL: {ttl_value}s)")
            elif self.backend == 'memory':
                self._memory_cache[cache_key] = response
                self._memory_timestamps[cache_key] = time.time() + ttl_value
                self._memory_access_order.append(cache_key)
                self._memory_cache_cleanup()
                logger.debug(f"Cached response (Memory): {cache_key} (TTL: {ttl_value}s)")

            self.stats['sets'] += 1

        except Exception as e:
            self.stats['errors'] += 1
            logger.warning(f"Cache set error: {e}")

    def delete(self, request_data: Dict) -> None:
        """
        Delete a cached response.

        Args:
            request_data: The request data dict
        """
        if not self.enabled:
            return

        try:
            cache_key = self._generate_cache_key(request_data)

            if self.backend == 'redis' and self.redis_client:
                self.redis_client.delete(cache_key)
            elif self.backend == 'sqlite' and self.sqlite_backend:
                self.sqlite_backend.delete(cache_key)
            elif self.backend == 'mysql' and self.mysql_backend:
                self.mysql_backend.delete(cache_key)
            elif self.backend == 'memory':
                self._memory_cache.pop(cache_key, None)
                self._memory_timestamps.pop(cache_key, None)
                if cache_key in self._memory_access_order:
                    self._memory_access_order.remove(cache_key)

            self.stats['deletes'] += 1
            logger.debug(f"Deleted from cache: {cache_key}")

        except Exception as e:
            self.stats['errors'] += 1
            logger.warning(f"Cache delete error: {e}")

    def clear(self) -> None:
        """Clear all cached responses"""
        if not self.enabled:
            return

        try:
            if self.backend == 'redis' and self.redis_client:
                # Delete all keys with our prefix
                keys = self.redis_client.keys(f"{self.key_prefix}*")
                if keys:
                    self.redis_client.delete(*keys)
            elif self.backend == 'sqlite' and self.sqlite_backend:
                self.sqlite_backend.clear()
            elif self.backend == 'mysql' and self.mysql_backend:
                self.mysql_backend.clear()
            elif self.backend == 'memory':
                self._memory_cache.clear()
                self._memory_timestamps.clear()
                self._memory_access_order.clear()

            # Reset statistics
            self.stats = {k: 0 for k in self.stats}

            logger.info("Response cache cleared")

        except Exception as e:
            self.stats['errors'] += 1
            logger.warning(f"Cache clear error: {e}")

    def get_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        stats = self.stats.copy()

        # Add current cache size
        if self.backend == 'redis' and self.redis_client:
            try:
                pattern = f"{self.key_prefix}*"
                stats['current_size'] = len(self.redis_client.keys(pattern))
            except:
                stats['current_size'] = 0
        elif self.backend == 'sqlite' and self.sqlite_backend:
            stats['current_size'] = self.sqlite_backend.get_size()
        elif self.backend == 'mysql' and self.mysql_backend:
            stats['current_size'] = self.mysql_backend.get_size()
        elif self.backend == 'memory':
            stats['current_size'] = len(self._memory_cache)

        # Calculate hit rate
        total_requests = stats['hits'] + stats['misses']
        stats['hit_rate'] = (stats['hits'] / total_requests) if total_requests > 0 else 0.0

        return stats


# Global response cache instance
_response_cache: Optional[ResponseCache] = None


def get_response_cache(config: Optional[Dict] = None) -> ResponseCache:
    """Get the global response cache instance"""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache(config)
    return _response_cache


def initialize_response_cache(config: Optional[Dict] = None):
    """Initialize the response cache system"""
    global _response_cache
    _response_cache = ResponseCache(config)
    logger.info("Response cache initialized")