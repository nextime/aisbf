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
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages SQLite database for persistent tracking of context dimensions and rate limiting.
    
    Database is stored in ~/.aisbf/aisbf.db and is automatically
    created if it doesn't exist.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the database manager.
        
        Args:
            db_path: Optional path to database file. If None, uses ~/.aisbf/aisbf.db
        """
        if db_path is None:
            # Default to ~/.aisbf/aisbf.db
            aisbf_dir = Path.home() / '.aisbf'
            aisbf_dir.mkdir(exist_ok=True)
            self.db_path = aisbf_dir / 'aisbf.db'
        else:
            self.db_path = Path(db_path)
        
        self._initialize_database()
        logger.info(f"Database initialized at: {self.db_path}")
    
    def _initialize_database(self):
        """Create database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create context_dimensions table for tracking context usage
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS context_dimensions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    context_size INTEGER,
                    condense_context INTEGER,
                    condense_method TEXT,
                    effective_context INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider_id, model_name)
                )
            ''')
            
            # Create token_usage table for tracking rate limiting
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    tokens_used INTEGER NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider_id, model_name, timestamp)
                )
            ''')
            
            # Create indexes for better query performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_context_provider_model 
                ON context_dimensions(provider_id, model_name)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_token_provider_model 
                ON token_usage(provider_id, model_name)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_token_timestamp 
                ON token_usage(timestamp)
            ''')
            
            conn.commit()
            logger.info("Database tables initialized successfully")
    
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Convert condense_method to JSON string if it's a list
            condense_method_str = json.dumps(condense_method) if isinstance(condense_method, list) else condense_method
            
            cursor.execute('''
                INSERT OR REPLACE INTO context_dimensions 
                (provider_id, model_name, context_size, condense_context, condense_method, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT context_size, condense_context, condense_method, effective_context
                FROM context_dimensions
                WHERE provider_id = ? AND model_name = ?
            ''', (provider_id, model_name))
            
            row = cursor.fetchone()
            if row:
                condense_method = json.loads(row[3]) if row[3] else None
                return {
                    'context_size': row[0],
                    'condense_context': row[1],
                    'condense_method': condense_method,
                    'effective_context': row[2]
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE context_dimensions
                SET effective_context = ?, last_updated = CURRENT_TIMESTAMP
                WHERE provider_id = ? AND model_name = ?
            ''', (effective_context, provider_id, model_name))
            
            conn.commit()
            logger.debug(f"Updated effective_context for {provider_id}/{model_name}: {effective_context}")
    
    def record_token_usage(
        self,
        provider_id: str,
        model_name: str,
        tokens_used: int
    ):
        """
        Record token usage for rate limiting.
        
        Args:
            provider_id: The provider identifier
            model_name: The model name
            tokens_used: Number of tokens used in the request
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO token_usage (provider_id, model_name, tokens_used, timestamp)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (provider_id, model_name, tokens_used))
            
            conn.commit()
            logger.debug(f"Recorded token usage for {provider_id}/{model_name}: {tokens_used}")
    
    def get_token_usage(
        self,
        provider_id: str,
        model_name: str,
        time_window: str = '1m'  # 1m, 1h, 1d
    ) -> int:
        """
        Get total token usage for a model within a time window.
        
        Args:
            provider_id: The provider identifier
            model_name: The model name
            time_window: Time window ('1m' for minute, '1h' for hour, '1d' for day)
        
        Returns:
            Total tokens used within the time window
        """
        with sqlite3.connect(self.db_path) as conn:
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
            
            cursor.execute('''
                SELECT COALESCE(SUM(tokens_used), 0)
                FROM token_usage
                WHERE provider_id = ? AND model_name = ? AND timestamp >= ?
            ''', (provider_id, model_name, cutoff.isoformat()))
            
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def cleanup_old_token_usage(self, days_to_keep: int = 7):
        """
        Clean up old token usage records to prevent database bloat.
        
        Args:
            days_to_keep: Number of days of token usage to keep
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days_to_keep)
            
            cursor.execute('''
                DELETE FROM token_usage
                WHERE timestamp < ?
            ''', (cutoff.isoformat(),))
            
            deleted = cursor.rowcount
            conn.commit()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old token usage records")
    
    def get_all_context_dimensions(self) -> List[Dict]:
        """
        Get all context dimension configurations.
        
        Returns:
            List of dictionaries with context configurations
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
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


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_database() -> DatabaseManager:
    """
    Get the global database manager instance.
    
    Returns:
        The DatabaseManager instance
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def initialize_database():
    """
    Initialize the database and clean up old records.
    This should be called at application startup.
    """
    db = get_database()
    db.cleanup_old_token_usage(days_to_keep=7)
    logger.info("Database initialized and old records cleaned up")