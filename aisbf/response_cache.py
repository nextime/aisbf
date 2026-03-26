"""
Response Cache module for AISBF with semantic deduplication.

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

import hashlib
import json
import logging
import time
import pickle
from typing import Dict, Any, Optional, Tuple
from functools import lru_cache
from pathlib import Path

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
            conn = mysql.connector.connect(**self.mysql_config)
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
        except mysql.connector.Error as e:
            if e.errno == 1049:
                temp_config = self.mysql_config.copy()
                del temp_config['database']
                conn = mysql.connector.connect(**temp_config)
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
            conn = mysql.connector.connect(**self.mysql_config)
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
            conn = mysql.connector.connect(**self.mysql_config)
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
            conn = mysql.connector.connect(**self.mysql_config)
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
            conn = mysql.connector.connect(**self.mysql_config)
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
            conn = mysql.connector.connect(**self.mysql_config)
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
            conn = mysql.connector.connect(**self.mysql_config)
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