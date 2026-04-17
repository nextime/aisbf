"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Token Usage Analytics module for AISBF.

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

Token Usage Analytics module for AISBF.
"""
import json
import csv
import io
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class Analytics:
    """
    Token Usage Analytics for AISBF.
    
    Provides:
    - Token usage tracking and historical queries
    - Request counts and latency tracking
    - Error rates and types tracking
    - Cost estimation per provider
    - Model performance comparison
    - Export functionality (CSV, JSON)
    """
    
    # Default pricing (can be overridden by config)
    DEFAULT_PRICING = {
        'anthropic': {'prompt': 15.0, 'completion': 75.0},  # $15/M prompt, $75/M completion
        'openai': {'prompt': 10.0, 'completion': 30.0},  # $10/M prompt, $30/M completion
        'google': {'prompt': 1.25, 'completion': 5.0},  # $1.25/M prompt, $5/M completion
        'kiro': {'prompt': 0.5, 'completion': 1.5},  # $0.5/M prompt, $1.5/M completion
        'openrouter': {'prompt': 5.0, 'completion': 15.0},  # Average pricing
    }
    
    def __init__(self, db_manager, pricing: Optional[Dict] = None):
        """
        Initialize the Analytics module.
        
        Args:
            db_manager: Database manager instance
            pricing: Optional custom pricing (provider -> {prompt, completion} per million tokens)
        """
        self.db = db_manager
        self.pricing = pricing or self.DEFAULT_PRICING
        
        # In-memory tracking for real-time analytics
        self._request_counts = {}  # {provider_id: {total: int, success: int, error: int}}
        self._latencies = {}  # {provider_id: {count: int, total_ms: float, min_ms: float, max_ms: float}}
        self._error_types = {}  # {provider_id: {error_type: count}}
    
    def _get_provider_pricing(self, provider_id: str) -> Dict[str, float]:
        """
        Get pricing for a provider, checking config first, then defaults.
        
        Args:
            provider_id: Provider identifier
            
        Returns:
            Dictionary with 'prompt' and 'completion' pricing per million tokens
        """
        from .config import config
        
        # Try to get provider config
        try:
            provider_config = config.get_provider(provider_id)
            if provider_config:
                # Check if it's a subscription provider (free)
                is_subscription = getattr(provider_config, 'is_subscription', False)
                if is_subscription:
                    return {'prompt': 0.0, 'completion': 0.0}
                
                # Check for custom pricing
                price_prompt = getattr(provider_config, 'price_per_million_prompt', None)
                price_completion = getattr(provider_config, 'price_per_million_completion', None)
                
                if price_prompt is not None and price_completion is not None:
                    return {'prompt': price_prompt, 'completion': price_completion}
        except Exception:
            pass
        
        # Fall back to default pricing
        for key, pricing in self.pricing.items():
            if key in provider_id.lower():
                return pricing
        
        # Ultimate fallback
        return self.pricing.get('openrouter', {'prompt': 5.0, 'completion': 15.0})
    
    
    def record_request(
        self,
        provider_id: str,
        model_name: str,
        tokens_used: int,
        latency_ms: float,
        success: bool = True,
        error_type: Optional[str] = None,
        rotation_id: Optional[str] = None,
        autoselect_id: Optional[str] = None,
        user_id: Optional[int] = None,
        token_id: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        actual_cost: Optional[float] = None
    ):
        """
        Record a request for analytics.

        Args:
            provider_id: Provider identifier
            model_name: Model name
            tokens_used: Total tokens used (prompt + completion)
            latency_ms: Request latency in milliseconds
            success: Whether the request was successful
            error_type: Optional error type if failed
            rotation_id: Optional rotation identifier if request went through rotation
            autoselect_id: Optional autoselect identifier if request went through autoselect
            user_id: Optional user ID if request was made with API token
            token_id: Optional API token ID if request was made with API token
            prompt_tokens: Optional number of input/prompt tokens
            completion_tokens: Optional number of output/completion tokens
            actual_cost: Optional actual cost returned by provider (in USD)
        """
        # Initialize provider tracking if needed
        if provider_id not in self._request_counts:
            self._request_counts[provider_id] = {'total': 0, 'success': 0, 'error': 0}
            self._latencies[provider_id] = {'count': 0, 'total_ms': 0.0, 'min_ms': float('inf'), 'max_ms': 0.0}
            self._error_types[provider_id] = {}
        
        # Update request counts
        self._request_counts[provider_id]['total'] += 1
        if success:
            self._request_counts[provider_id]['success'] += 1
        else:
            self._request_counts[provider_id]['error'] += 1
            if error_type:
                self._error_types[provider_id][error_type] = self._error_types[provider_id].get(error_type, 0) + 1
        
        # Update latencies
        self._latencies[provider_id]['count'] += 1
        self._latencies[provider_id]['total_ms'] += latency_ms
        self._latencies[provider_id]['min_ms'] = min(self._latencies[provider_id]['min_ms'], latency_ms)
        self._latencies[provider_id]['max_ms'] = max(self._latencies[provider_id]['max_ms'], latency_ms)
        
        # Persist to database
        if tokens_used > 0:
            logger.info(f"Analytics.record_request: Recording to DB - provider={provider_id}, latency_ms={latency_ms}, success={success}, prompt={prompt_tokens}, completion={completion_tokens}, cost={actual_cost}")
            self.db.record_token_usage(provider_id, model_name, tokens_used, user_id, success, latency_ms, error_type, token_id, prompt_tokens, completion_tokens, actual_cost)

            # Also record user token usage if this was an API token request
            if user_id is not None and token_id is not None:
                self.db.record_user_token_usage(user_id, token_id, provider_id, model_name, tokens_used)
    
    def get_provider_stats(
        self,
        provider_id: str,
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None,
        user_filter: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get statistics for a specific provider.
        
        Args:
            provider_id: Provider identifier
            from_datetime: Optional start datetime for filtering
            to_datetime: Optional end datetime for filtering
            
        Returns:
            Dictionary with provider statistics
        """
        # Use in-memory stats if no date range specified, otherwise query DB
        if from_datetime is None and to_datetime is None:
            # Default to last 24 hours from database instead of in-memory
            from_datetime = datetime.now() - timedelta(days=1)
            to_datetime = datetime.now()
            stats = self._get_provider_stats_from_db(provider_id, from_datetime, to_datetime, user_filter)
        else:
            # Query database for date range stats
            start = from_datetime or (datetime.now() - timedelta(days=1))
            end = to_datetime or datetime.now()
            
            stats = self._get_provider_stats_from_db(provider_id, start, end, user_filter)
        
        # Calculate error rate
        total = stats['requests']['total']
        if total > 0:
            stats['error_rate'] = stats['requests']['error'] / total
        else:
            stats['error_rate'] = 0.0
        
        # Calculate average latency
        latency = stats['latency']
        if latency['count'] > 0:
            stats['avg_latency_ms'] = latency['total_ms'] / latency['count']
            stats['min_latency_ms'] = latency['min_ms'] if latency['min_ms'] != float('inf') else 0
            stats['max_latency_ms'] = latency['max_ms']
        else:
            stats['avg_latency_ms'] = 0
            stats['min_latency_ms'] = 0
            stats['max_latency_ms'] = 0
        
        return stats
    
    def _get_provider_stats_from_db(
        self,
        provider_id: str,
        from_datetime: datetime,
        to_datetime: datetime,
        user_filter: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get provider stats from database for a specific date range."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Build query with optional user filter
            # user_filter = -1 means "only global requests" (user_id IS NULL)
            # user_filter = None means "all requests"
            # user_filter = <id> means "only requests from that user"
            if user_filter == -1:
                user_condition = " AND user_id IS NULL"
                params = [provider_id, from_datetime.isoformat(), to_datetime.isoformat()]
            elif user_filter is not None:
                user_condition = f" AND user_id = {placeholder}"
                params = [provider_id, from_datetime.isoformat(), to_datetime.isoformat(), user_filter]
            else:
                user_condition = ""
                params = [provider_id, from_datetime.isoformat(), to_datetime.isoformat()]
            
            # Get token usage and actual time range of requests
            cursor.execute(f'''
                SELECT
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count,
                    AVG(COALESCE(latency_ms, 0)) as avg_latency,
                    MIN(COALESCE(latency_ms, 0)) as min_latency,
                    MAX(COALESCE(latency_ms, 0)) as max_latency,
                    SUM(tokens_used) as total_tokens,
                    SUM(COALESCE(prompt_tokens, 0)) as total_prompt_tokens,
                    SUM(COALESCE(completion_tokens, 0)) as total_completion_tokens,
                    SUM(COALESCE(actual_cost, 0)) as total_actual_cost,
                    MIN(timestamp) as first_request,
                    MAX(timestamp) as last_request
                FROM token_usage
                WHERE provider_id = {placeholder}
                  AND timestamp >= {placeholder}
                  AND timestamp <= {placeholder}
                  {user_condition}
            ''', params)
            
            result = cursor.fetchone()
            total_requests = result[0] if result else 0
            success_count = result[1] if result else 0
            error_count = result[2] if result else 0
            avg_latency = result[3] if result and result[3] else 0
            min_latency = result[4] if result and result[4] else 0
            max_latency = result[5] if result and result[5] else 0
            total_tokens = result[6] if result else 0
            total_prompt_tokens = result[7] if result else 0
            total_completion_tokens = result[8] if result else 0
            total_actual_cost = result[9] if result else 0
            first_request = result[10] if result and result[10] else None
            last_request = result[11] if result and result[11] else None
            
            # Calculate time-based rates using ACTUAL usage window, not query window
            # This gives more accurate rate limiting metrics
            if first_request and last_request and total_tokens > 0:
                try:
                    first_dt = datetime.fromisoformat(first_request)
                    last_dt = datetime.fromisoformat(last_request)
                    
                    # Use actual duration between first and last request
                    # Add a minimum of 1 minute to avoid division by very small numbers
                    actual_duration_seconds = max((last_dt - first_dt).total_seconds(), 60)
                    duration_minutes = actual_duration_seconds / 60
                    duration_hours = actual_duration_seconds / 3600
                    duration_days = actual_duration_seconds / 86400
                    
                    # Calculate rates based on actual usage period
                    tpm = int(total_tokens / duration_minutes) if duration_minutes > 0 else 0
                    tph = int(total_tokens / duration_hours) if duration_hours > 0 else 0
                    tpd = int(total_tokens / duration_days) if duration_days > 0 else 0
                except Exception as e:
                    # Fallback to query window if parsing fails
                    duration_seconds = (to_datetime - from_datetime).total_seconds()
                    duration_minutes = duration_seconds / 60
                    duration_hours = duration_seconds / 3600
                    duration_days = duration_seconds / 86400
                    
                    tpm = int(total_tokens / duration_minutes) if duration_minutes > 0 else 0
                    tph = int(total_tokens / duration_hours) if duration_hours > 0 else 0
                    tpd = int(total_tokens / duration_days) if duration_days > 0 else 0
            else:
                tpm = tph = tpd = 0
            
            return {
                'provider_id': provider_id,
                'requests': {'total': total_requests, 'success': success_count, 'error': error_count},
                'latency': {'count': total_requests, 'total_ms': avg_latency * total_requests if total_requests > 0 else 0, 'min_ms': min_latency, 'max_ms': max_latency},
                'errors': {},  # Could be populated from error_type column if needed
                'tokens': {
                    'total': total_tokens,
                    'prompt': total_prompt_tokens,
                    'completion': total_completion_tokens,
                    'TPM': tpm,
                    'TPH': tph,
                    'TPD': tpd
                },
                'actual_cost': total_actual_cost  # Actual cost from provider responses
            }
    
    def get_token_usage_by_date_range(
        self,
        provider_id: Optional[str] = None,
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None,
        user_filter: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get token usage for a specific date range.
        
        Args:
            provider_id: Optional provider filter
            from_datetime: Start datetime
            to_datetime: End datetime
            
        Returns:
            Dictionary with token counts and cost estimates
        """
        start = from_datetime or (datetime.now() - timedelta(days=1))
        end = to_datetime or datetime.now()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            if provider_id:
                cursor.execute(f'''
                    SELECT SUM(tokens_used) as total_tokens
                    FROM token_usage
                    WHERE provider_id = {placeholder} AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                ''', (provider_id, start.isoformat(), end.isoformat()))
                row = cursor.fetchone()
                total_tokens = row[0] if row and row[0] else 0
            else:
                cursor.execute(f'''
                    SELECT provider_id, SUM(tokens_used) as total_tokens
                    FROM token_usage
                    WHERE timestamp >= {placeholder} AND timestamp <= {placeholder}
                    GROUP BY provider_id
                ''', (start.isoformat(), end.isoformat()))
                
                provider_tokens = {}
                total_tokens = 0
                for row in cursor.fetchall():
                    provider_tokens[row[0]] = row[1]
                    total_tokens += row[1]
            
            # Calculate cost
            cost = self.estimate_cost(provider_id or 'all', total_tokens)
            
            # Calculate duration in days for display
            duration_days = (end - start).total_seconds() / 86400
            
            return {
                'total_tokens': total_tokens,
                'estimated_cost': cost,
                'start': start.isoformat(),
                'end': end.isoformat(),
                'duration_days': duration_days,
                'provider_tokens': provider_tokens if not provider_id else None
            }
    
    def get_all_providers_stats(
        self,
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None,
        user_filter: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get statistics for all providers.
        
        Args:
            from_datetime: Optional start datetime for filtering
            to_datetime: Optional end datetime for filtering
            user_filter: Optional user ID filter (-1 for global only, None for all, or user ID)
            
        Returns:
            List of provider statistics dictionaries
        """
        # Get all unique providers from database
        start = from_datetime or (datetime.now() - timedelta(days=1))
        end = to_datetime or datetime.now()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Build query with optional user filter
            if user_filter == -1:
                user_condition = " AND user_id IS NULL"
                params = [start.isoformat(), end.isoformat()]
            elif user_filter is not None:
                user_condition = f" AND user_id = {placeholder}"
                params = [start.isoformat(), end.isoformat(), user_filter]
            else:
                user_condition = ""
                params = [start.isoformat(), end.isoformat()]
            
            cursor.execute(f'''
                SELECT DISTINCT provider_id
                FROM token_usage
                WHERE timestamp >= {placeholder}
                  AND timestamp <= {placeholder}
                  {user_condition}
            ''', params)
            
            all_providers = [row[0] for row in cursor.fetchall()]
        
        return [self.get_provider_stats(pid, from_datetime, to_datetime, user_filter) for pid in sorted(all_providers)]
    
    def _get_token_usage_by_provider(self, provider_id: str) -> Dict[str, int]:
        """
        Get token usage for a provider.
        
        Args:
            provider_id: Provider identifier
            
        Returns:
            Dictionary with TPM, TPH, TPD
        """
        return {
            'TPM': self.db.get_token_usage(provider_id, '', '1m'),
            'TPH': self.db.get_token_usage(provider_id, '', '1h'),
            'TPD': self.db.get_token_usage(provider_id, '', '1d')
        }
    
    def get_token_usage_over_time(
        self,
        provider_id: Optional[str] = None,
        time_range: str = '24h',
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None,
        user_filter: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get token usage over time for charts.
        
        Args:
            provider_id: Optional provider filter
            time_range: Time range ('1h', '6h', '24h', '7d', '30d', '90d', 'custom')
            from_datetime: Optional custom start datetime (used when time_range='custom')
            to_datetime: Optional custom end datetime (used when time_range='custom')
            user_filter: Optional user ID to filter by
            
        Returns:
            List of time-series data points
        """
        # Determine time range
        if time_range == 'custom' and from_datetime and to_datetime:
            cutoff = from_datetime
            end_time = to_datetime
            # Calculate bucket size based on range
            total_minutes = (end_time - cutoff).total_seconds() / 60
            if total_minutes <= 60:
                bucket_minutes = 5
            elif total_minutes <= 3600:
                bucket_minutes = 15
            elif total_minutes <= 86400:
                bucket_minutes = 30
            elif total_minutes <= 604800:  # 7 days
                bucket_minutes = 60  # hourly
            elif total_minutes <= 2592000:  # 30 days
                bucket_minutes = 60 * 24  # daily
            else:  # > 30 days
                bucket_minutes = 60 * 24 * 7  # weekly
        elif time_range == '1h':
            cutoff = datetime.now() - timedelta(hours=1)
            end_time = datetime.now()
            bucket_minutes = 5
        elif time_range == '6h':
            cutoff = datetime.now() - timedelta(hours=6)
            end_time = datetime.now()
            bucket_minutes = 15
        elif time_range == '24h':
            cutoff = datetime.now() - timedelta(hours=24)
            end_time = datetime.now()
            bucket_minutes = 30
        elif time_range == '7d':
            cutoff = datetime.now() - timedelta(days=7)
            end_time = datetime.now()
            bucket_minutes = 60 * 24  # Daily
        elif time_range == '30d':
            cutoff = datetime.now() - timedelta(days=30)
            end_time = datetime.now()
            bucket_minutes = 60 * 24  # Daily
        elif time_range == '90d':
            cutoff = datetime.now() - timedelta(days=90)
            end_time = datetime.now()
            bucket_minutes = 60 * 24  # Daily
        else:  # Default 24h
            cutoff = datetime.now() - timedelta(hours=24)
            end_time = datetime.now()
            bucket_minutes = 30
        
        # Query database for token usage in time range
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Determine date format and time bucket expression based on database type
            if self.db.db_type == 'sqlite':
                date_format = "%Y-%m-%d %H:%M"
                time_bucket_expr = f"strftime('{date_format}', timestamp)"
            else:
                date_format = "%Y-%m-%d %H:%i"
                time_bucket_expr = f"DATE_FORMAT(timestamp, '{date_format}')"
            
            if provider_id:
                if user_filter == -1:
                    # Global requests only
                    cursor.execute(f'''
                        SELECT 
                            {time_bucket_expr} as time_bucket,
                            SUM(tokens_used) as tokens
                        FROM token_usage
                        WHERE provider_id = {placeholder} AND user_id IS NULL AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                        GROUP BY time_bucket
                        ORDER BY time_bucket
                    ''', (provider_id, cutoff.isoformat(), end_time.isoformat()))
                elif user_filter:
                    cursor.execute(f'''
                        SELECT 
                            {time_bucket_expr} as time_bucket,
                            SUM(tokens_used) as tokens
                        FROM token_usage
                        WHERE provider_id = {placeholder} AND user_id = {placeholder} AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                        GROUP BY time_bucket
                        ORDER BY time_bucket
                    ''', (provider_id, user_filter, cutoff.isoformat(), end_time.isoformat()))
                else:
                    cursor.execute(f'''
                        SELECT 
                            {time_bucket_expr} as time_bucket,
                            SUM(tokens_used) as tokens
                        FROM token_usage
                        WHERE provider_id = {placeholder} AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                        GROUP BY time_bucket
                        ORDER BY time_bucket
                    ''', (provider_id, cutoff.isoformat(), end_time.isoformat()))
            else:
                if user_filter == -1:
                    # Global requests only
                    cursor.execute(f'''
                        SELECT 
                            {time_bucket_expr} as time_bucket,
                            SUM(tokens_used) as tokens,
                            provider_id
                        FROM token_usage
                        WHERE user_id IS NULL AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                        GROUP BY time_bucket, provider_id
                        ORDER BY time_bucket
                    ''', (cutoff.isoformat(), end_time.isoformat()))
                elif user_filter:
                    cursor.execute(f'''
                        SELECT 
                            {time_bucket_expr} as time_bucket,
                            SUM(tokens_used) as tokens,
                            provider_id
                        FROM token_usage
                        WHERE user_id = {placeholder} AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                        GROUP BY time_bucket, provider_id
                        ORDER BY time_bucket
                    ''', (user_filter, cutoff.isoformat(), end_time.isoformat()))
                else:
                    cursor.execute(f'''
                        SELECT 
                            {time_bucket_expr} as time_bucket,
                            SUM(tokens_used) as tokens,
                            provider_id
                        FROM token_usage
                        WHERE timestamp >= {placeholder} AND timestamp <= {placeholder}
                        GROUP BY time_bucket, provider_id
                        ORDER BY time_bucket
                    ''', (cutoff.isoformat(), end_time.isoformat()))
            
            results = []
            for row in cursor.fetchall():
                if provider_id:
                    results.append({
                        'timestamp': row[0],
                        'tokens': row[1]
                    })
                else:
                    results.append({
                        'timestamp': row[0],
                        'tokens': row[1],
                        'provider_id': row[2]
                    })
            
            return results
    
    def get_model_performance(
        self,
        provider_filter: Optional[str] = None,
        model_filter: Optional[str] = None,
        rotation_filter: Optional[str] = None,
        autoselect_filter: Optional[str] = None,
        user_filter: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get model performance comparison with optional filters.
        
        Args:
            provider_filter: Optional provider ID to filter by
            model_filter: Optional model name to filter by
            rotation_filter: Optional rotation ID to filter by
            autoselect_filter: Optional autoselect ID to filter by
            user_filter: Optional user ID to filter by
            
        Returns:
            List of model performance data
        """
        context_dims = self.db.get_all_context_dimensions(user_filter=user_filter)
        
        results = []
        for dim in context_dims:
            provider_id = dim['provider_id']
            model_name = dim['model_name']
            
            # Apply filters
            if provider_filter and provider_id != provider_filter:
                continue
            if model_filter and model_name != model_filter:
                continue
            
            # Check if this is a rotation or autoselect by checking the model name
            # Rotations and autoselects have special prefixes in the context dimensions
            is_rotation = dim.get('is_rotation', False)
            is_autoselect = dim.get('is_autoselect', False)
            
            # Get rotation/autoselect ID from context dimensions if available
            rotation_id = dim.get('rotation_id')
            autoselect_id = dim.get('autoselect_id')
            
            # Apply rotation filter
            if rotation_filter:
                # Skip if not a rotation or different rotation
                if not is_rotation or (rotation_id and rotation_id != rotation_filter):
                    continue
            
            # Apply autoselect filter
            if autoselect_filter:
                # Skip if not an autoselect or different autoselect
                if not is_autoselect or (autoselect_id and autoselect_id != autoselect_filter):
                    continue
            
            # Get token usage for this model
            stats = self.db.get_token_usage_stats(provider_id, model_name)
            
            # Get provider request stats
            provider_stats = self.get_provider_stats(provider_id)
            
            results.append({
                'provider_id': provider_id,
                'model_name': model_name,
                'context_size': dim.get('context_size'),
                'effective_context': dim.get('effective_context'),
                'condense_context': dim.get('condense_context'),
                'condense_method': dim.get('condense_method'),
                'tokens_per_minute': stats['TPM'],
                'tokens_per_hour': stats['TPH'],
                'tokens_per_day': stats['TPD'],
                'error_rate': provider_stats.get('error_rate', 0),
                'avg_latency_ms': provider_stats.get('avg_latency_ms', 0),
                'is_rotation': is_rotation,
                'is_autoselect': is_autoselect,
                'rotation_id': rotation_id,
                'autoselect_id': autoselect_id
            })
        
        return results
    
    def get_rotations_stats(self) -> List[Dict[str, Any]]:
        """
        Get statistics for all configured rotations.
        
        Returns:
            List of rotation statistics
        """
        from aisbf.config import config as cfg
        
        results = []
        for rotation_id, rotation_config in cfg.rotations.items():
            # Get token usage for providers in this rotation
            rotation_providers = []
            for provider in rotation_config.providers:
                provider_id = provider.get('provider_id')
                if provider_id:
                    stats = self.get_provider_stats(provider_id)
                    rotation_providers.append(stats)
            
            results.append({
                'rotation_id': rotation_id,
                'model_name': rotation_config.model_name,
                'providers': rotation_providers,
                'provider_count': len(rotation_providers)
            })
        
        return results
    
    def get_autoselects_stats(self) -> List[Dict[str, Any]]:
        """
        Get statistics for all configured autoselects.
        
        Returns:
            List of autoselect statistics
        """
        from aisbf.config import config as cfg
        
        results = []
        for autoselect_id, autoselect_config in cfg.autoselect.items():
            # Get the fallback provider info
            fallback = autoselect_config.fallback
            fallback_provider = None
            fallback_model = None
            
            if '/' in fallback:
                fallback_provider, fallback_model = fallback.split('/', 1)
            
            results.append({
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.model_name,
                'description': autoselect_config.description,
                'fallback_provider': fallback_provider,
                'fallback_model': fallback_model,
                'available_models_count': len(autoselect_config.available_models)
            })
        
        return results
    
    def estimate_cost(
        self,
        provider_id: str,
        tokens_used: int,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None
    ) -> float:
        """
        Estimate cost for token usage.
        
        Args:
            provider_id: Provider identifier
            tokens_used: Total tokens used
            prompt_tokens: Optional breakdown of prompt tokens
            completion_tokens: Optional breakdown of completion tokens
            
        Returns:
            Estimated cost in USD
        """
        # Get provider-specific pricing (checks subscription status and custom pricing)
        provider_pricing = self._get_provider_pricing(provider_id)
        
        # Calculate cost with actual token breakdown if available
        if prompt_tokens is not None and completion_tokens is not None:
            prompt_cost = (prompt_tokens / 1_000_000) * provider_pricing.get('prompt', 0)
            completion_cost = (completion_tokens / 1_000_000) * provider_pricing.get('completion', 0)
            return prompt_cost + completion_cost
        elif prompt_tokens is not None:
            # Only prompt tokens provided, calculate completion from total
            completion_tokens_calc = tokens_used - prompt_tokens
            prompt_cost = (prompt_tokens / 1_000_000) * provider_pricing.get('prompt', 0)
            completion_cost = (completion_tokens_calc / 1_000_000) * provider_pricing.get('completion', 0)
            return prompt_cost + completion_cost
        else:
            # No breakdown available - use estimation (25% prompt, 75% completion is common for chat)
            prompt_tokens_est = tokens_used * 0.25
            completion_tokens_est = tokens_used * 0.75
            prompt_cost = (prompt_tokens_est / 1_000_000) * provider_pricing.get('prompt', 0)
            completion_cost = (completion_tokens_est / 1_000_000) * provider_pricing.get('completion', 0)
            return prompt_cost + completion_cost
    
    def get_cost_overview(
        self,
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None,
        user_filter: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get cost overview for all providers.
        
        Args:
            from_datetime: Optional start datetime for filtering
            to_datetime: Optional end datetime for filtering
            
        Returns:
            Dictionary with cost estimates
        """
        # Use date range for token usage if specified
        start = from_datetime or (datetime.now() - timedelta(days=1))
        end = to_datetime or datetime.now()
        
        # Get token usage by date range
        range_usage = self.get_token_usage_by_date_range(None, start, end)
        
        # Get providers that have data
        providers = self.get_all_providers_stats(from_datetime, to_datetime)
        
        total_cost = 0.0
        provider_costs = []
        
        for provider in providers:
            provider_id = provider['provider_id']
            
            # Get token usage for this provider in the date range
            if from_datetime or to_datetime:
                provider_usage = self.get_token_usage_by_date_range(provider_id, start, end)
                total_tokens = provider_usage['total_tokens']
            else:
                tokens = provider['tokens']
                total_tokens = tokens['TPD']  # Use daily tokens for cost estimation
            
            # Get actual prompt/completion tokens from provider stats
            prompt_tokens = tokens.get('prompt', 0) if not (from_datetime or to_datetime) else None
            completion_tokens = tokens.get('completion', 0) if not (from_datetime or to_datetime) else None
            
            # Use actual cost if available, otherwise estimate
            actual_cost = provider.get('actual_cost', 0)
            if actual_cost > 0:
                cost = actual_cost
            else:
                cost = self.estimate_cost(provider_id, total_tokens, prompt_tokens, completion_tokens)
            
            total_cost += cost
            
            provider_costs.append({
                'provider_id': provider_id,
                'tokens_today': total_tokens,
                'estimated_cost': cost,
                'is_actual': actual_cost > 0
            })
        
        return {
            'total_estimated_cost_today': total_cost,
            'providers': provider_costs,
            'currency': 'USD',
            'date_range': {
                'start': start.isoformat(),
                'end': end.isoformat()
            }
        }
    
    def get_optimization_recommendations(self, user_filter: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Generate optimization recommendations based on analytics.
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        # Analyze provider stats
        providers = self.get_all_providers_stats()
        
        for provider in providers:
            provider_id = provider['provider_id']
            
            # High error rate recommendation
            if provider.get('error_rate', 0) > 0.1:
                recommendations.append({
                    'type': 'high_error_rate',
                    'severity': 'high',
                    'provider': provider_id,
                    'message': f"Provider {provider_id} has {provider.get('error_rate', 0)*100:.1f}% error rate. Consider reviewing provider configuration.",
                    'action': 'Review provider configuration in providers.json'
                })
            
            # High latency recommendation
            if provider.get('avg_latency_ms', 0) > 5000:
                recommendations.append({
                    'type': 'high_latency',
                    'severity': 'medium',
                    'provider': provider_id,
                    'message': f"Provider {provider_id} has high average latency: {provider.get('avg_latency_ms', 0)/1000:.1f}s",
                    'action': 'Consider adjusting rotation weights or adding faster providers'
                })
        
        # Analyze token usage for potential cost savings
        context_dims = self.db.get_all_context_dimensions()
        for dim in context_dims:
            if dim.get('condense_context') and dim['condense_context'] > 80:
                recommendations.append({
                    'type': 'high_condense_threshold',
                    'severity': 'low',
                    'provider': dim['provider_id'],
                    'model': dim['model_name'],
                    'message': f"High condensation threshold ({dim['condense_context']}%) may cause excessive context reduction",
                    'action': f"Consider lowering condense_context to 70-80% for better balance"
                })
        
        return recommendations
    
    def export_to_json(
        self,
        time_range: str = '24h',
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None
    ) -> str:
        """
        Export analytics data to JSON.
        
        Args:
            time_range: Time range for export
            from_datetime: Optional custom start datetime
            to_datetime: Optional custom end datetime
            
        Returns:
            JSON string with analytics data
        """
        data = {
            'export_time': datetime.now().isoformat(),
            'time_range': time_range,
            'date_range': {
                'from': from_datetime.isoformat() if from_datetime else None,
                'to': to_datetime.isoformat() if to_datetime else None
            },
            'providers': self.get_all_providers_stats(from_datetime, to_datetime),
            'models': self.get_model_performance(),
            'cost_overview': self.get_cost_overview(from_datetime, to_datetime),
            'recommendations': self.get_optimization_recommendations()
        }
        
        return json.dumps(data, indent=2)
    
    def export_to_csv(
        self,
        time_range: str = '24h',
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None
    ) -> str:
        """
        Export analytics data to CSV.
        
        Args:
            time_range: Time range for export
            from_datetime: Optional custom start datetime
            to_datetime: Optional custom end datetime
            
        Returns:
            CSV string with analytics data
        """
        output = io.StringIO()
        
        # Provider stats CSV
        writer = csv.writer(output)
        writer.writerow(['Provider ID', 'Total Requests', 'Successful', 'Errors', 'Error Rate', 'Avg Latency (ms)', 'Tokens/Min', 'Tokens/Hour', 'Tokens/Day'])
        
        for provider in self.get_all_providers_stats(from_datetime, to_datetime):
            writer.writerow([
                provider['provider_id'],
                provider['requests']['total'],
                provider['requests']['success'],
                provider['requests']['error'],
                f"{provider.get('error_rate', 0)*100:.2f}%",
                f"{provider.get('avg_latency_ms', 0):.2f}",
                provider['tokens']['TPM'],
                provider['tokens']['TPH'],
                provider['tokens']['TPD']
            ])
        
        return output.getvalue()
    
    def reset_stats(self):
        """Reset in-memory statistics (does not affect database)."""
        self._request_counts = {}
        self._latencies = {}
        self._error_types = {}
        logger.info("Analytics stats reset")
    
    # User-specific analytics methods
    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Get token usage statistics for a specific user.
        
        Args:
            user_id: The user ID
            
        Returns:
            Dictionary with user token statistics
        """
        return self.db.get_user_token_usage_stats(user_id)
    
    def get_all_users_stats(self) -> List[Dict[str, Any]]:
        """
        Get token usage statistics for all users (admin only).
        
        Returns:
            List of user statistics
        """
        return self.db.get_all_users_token_usage()
    
    def get_global_stats(self) -> Dict[str, Any]:
        """
        Get global token usage statistics (across all users and non-user requests).
        
        Returns:
            Dictionary with global token statistics
        """
        # Get total tokens in last hour and day from the token_usage table
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Last hour
            cursor.execute(f'''
                SELECT COALESCE(SUM(tokens_used), 0)
                FROM token_usage
                WHERE timestamp >= {placeholder}
            ''', ((datetime.now() - timedelta(hours=1)).isoformat(),))
            tokens_1h = cursor.fetchone()[0] or 0
            
            # Last day
            cursor.execute(f'''
                SELECT COALESCE(SUM(tokens_used), 0)
                FROM token_usage
                WHERE timestamp >= {placeholder}
            ''', ((datetime.now() - timedelta(days=1)).isoformat(),))
            tokens_1d = cursor.fetchone()[0] or 0
            
            # Last week
            cursor.execute(f'''
                SELECT COALESCE(SUM(tokens_used), 0)
                FROM token_usage
                WHERE timestamp >= {placeholder}
            ''', ((datetime.now() - timedelta(days=7)).isoformat(),))
            tokens_7d = cursor.fetchone()[0] or 0
            
            # Total by provider
            cursor.execute(f'''
                SELECT provider_id, COALESCE(SUM(tokens_used), 0) as total
                FROM token_usage
                GROUP BY provider_id
            ''')
            provider_totals = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                'tokens_1h': tokens_1h,
                'tokens_1d': tokens_1d,
                'tokens_7d': tokens_7d,
                'provider_totals': provider_totals,
                'estimated_cost_1h': self.estimate_cost('global', tokens_1h),
                'estimated_cost_1d': self.estimate_cost('global', tokens_1d),
                'estimated_cost_7d': self.estimate_cost('global', tokens_7d)
            }
    
    def get_user_token_usage_over_time(
        self,
        user_id: int,
        time_range: str = '24h',
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get token usage over time for a specific user.
        
        Args:
            user_id: The user ID
            time_range: Time range ('1h', '6h', '24h', '7d', '30d', '90d', 'custom')
            from_datetime: Optional custom start datetime
            to_datetime: Optional custom end datetime
            
        Returns:
            List of time-series data points
        """
        # Determine time range
        if time_range == 'custom' and from_datetime and to_datetime:
            cutoff = from_datetime
            end_time = to_datetime
        elif time_range == '1h':
            cutoff = datetime.now() - timedelta(hours=1)
            end_time = datetime.now()
        elif time_range == '6h':
            cutoff = datetime.now() - timedelta(hours=6)
            end_time = datetime.now()
        elif time_range == '24h':
            cutoff = datetime.now() - timedelta(hours=24)
            end_time = datetime.now()
        elif time_range == '7d':
            cutoff = datetime.now() - timedelta(days=7)
            end_time = datetime.now()
        elif time_range == '30d':
            cutoff = datetime.now() - timedelta(days=30)
            end_time = datetime.now()
        elif time_range == '90d':
            cutoff = datetime.now() - timedelta(days=90)
            end_time = datetime.now()
        else:  # Default 24h
            cutoff = datetime.now() - timedelta(hours=24)
            end_time = datetime.now()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            if self.db.db_type == 'sqlite':
                date_format = "%Y-%m-%d %H:%M"
                time_bucket_expr = f"strftime('{date_format}', timestamp)"
            else:
                date_format = "%Y-%m-%d %H:%i"
                time_bucket_expr = f"DATE_FORMAT(timestamp, '{date_format}')"
            
            cursor.execute(f'''
                SELECT 
                    {time_bucket_expr} as time_bucket,
                    SUM(tokens_used) as tokens,
                    provider_id
                FROM token_usage
                WHERE user_id = {placeholder} AND timestamp >= {placeholder} AND timestamp <= {placeholder}
                GROUP BY time_bucket, provider_id
                ORDER BY time_bucket
            ''', (user_id, cutoff.isoformat(), end_time.isoformat()))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'timestamp': row[0],
                    'tokens': row[1],
                    'provider_id': row[2]
                })
            
            return results


# Global analytics instance
_analytics: Optional[Analytics] = None


def get_analytics(db_manager=None) -> Analytics:
    """
    Get the global analytics instance.
    
    Args:
        db_manager: Optional database manager. If None, uses global db manager.
        
    Returns:
        Analytics instance
    """
    global _analytics
    
    if _analytics is None:
        if db_manager is None:
            from .database import get_database
            db_manager = get_database()
        
        _analytics = Analytics(db_manager)
    
    return _analytics


def initialize_analytics(db_manager):
    """
    Initialize the analytics module with a database manager.
    
    Args:
        db_manager: Database manager instance
    """
    global _analytics
    _analytics = Analytics(db_manager)
    logger.info("Analytics module initialized")