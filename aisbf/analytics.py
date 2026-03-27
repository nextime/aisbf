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
    
    def record_request(
        self,
        provider_id: str,
        model_name: str,
        tokens_used: int,
        latency_ms: float,
        success: bool = True,
        error_type: Optional[str] = None,
        rotation_id: Optional[str] = None,
        autoselect_id: Optional[str] = None
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
            self.db.record_token_usage(provider_id, model_name, tokens_used)
    
    def get_provider_stats(self, provider_id: str) -> Dict[str, Any]:
        """
        Get statistics for a specific provider.
        
        Args:
            provider_id: Provider identifier
            
        Returns:
            Dictionary with provider statistics
        """
        stats = {
            'provider_id': provider_id,
            'requests': self._request_counts.get(provider_id, {'total': 0, 'success': 0, 'error': 0}),
            'latency': self._latencies.get(provider_id, {'count': 0, 'total_ms': 0.0, 'min_ms': 0, 'max_ms': 0}),
            'errors': self._error_types.get(provider_id, {}),
            'tokens': self._get_token_usage_by_provider(provider_id)
        }
        
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
    
    def get_all_providers_stats(self) -> List[Dict[str, Any]]:
        """
        Get statistics for all providers.
        
        Returns:
            List of provider statistics
        """
        all_providers = set(self._request_counts.keys())
        all_providers.update(self.db.get_all_context_dimensions())
        
        return [self.get_provider_stats(pid) for pid in sorted(all_providers)]
    
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
        time_range: str = '24h'
    ) -> List[Dict[str, Any]]:
        """
        Get token usage over time for charts.
        
        Args:
            provider_id: Optional provider filter
            time_range: Time range ('1h', '6h', '24h', '7d')
            
        Returns:
            List of time-series data points
        """
        if time_range == '1h':
            cutoff = datetime.now() - timedelta(hours=1)
            bucket_minutes = 5
        elif time_range == '6h':
            cutoff = datetime.now() - timedelta(hours=6)
            bucket_minutes = 15
        elif time_range == '7d':
            cutoff = datetime.now() - timedelta(days=7)
            bucket_minutes = 60 * 24  # Daily
        else:  # 24h default
            cutoff = datetime.now() - timedelta(hours=24)
            bucket_minutes = 30
        
        # Query database for token usage in time range
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            if provider_id:
                cursor.execute(f'''
                    SELECT 
                        strftime('%Y-%m-%d %H:%M', timestamp) as time_bucket,
                        SUM(tokens_used) as tokens
                    FROM token_usage
                    WHERE provider_id = {placeholder} AND timestamp >= {placeholder}
                    GROUP BY time_bucket
                    ORDER BY time_bucket
                ''', (provider_id, cutoff.isoformat()))
            else:
                cursor.execute(f'''
                    SELECT 
                        strftime('%Y-%m-%d %H:%M', timestamp) as time_bucket,
                        SUM(tokens_used) as tokens,
                        provider_id
                    FROM token_usage
                    WHERE timestamp >= {placeholder}
                    GROUP BY time_bucket, provider_id
                    ORDER BY time_bucket
                ''', (cutoff.isoformat(),))
            
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
    
    def get_model_performance(self) -> List[Dict[str, Any]]:
        """
        Get model performance comparison.
        
        Returns:
            List of model performance data
        """
        context_dims = self.db.get_all_context_dimensions()
        
        results = []
        for dim in context_dims:
            provider_id = dim['provider_id']
            model_name = dim['model_name']
            
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
                'avg_latency_ms': provider_stats.get('avg_latency_ms', 0)
            })
        
        return results
    
    def estimate_cost(
        self,
        provider_id: str,
        tokens_used: int,
        prompt_tokens: Optional[int] = None
    ) -> float:
        """
        Estimate cost for token usage.
        
        Args:
            provider_id: Provider identifier
            tokens_used: Total tokens used
            prompt_tokens: Optional breakdown of prompt tokens
            
        Returns:
            Estimated cost in USD
        """
        # Determine provider pricing
        provider_pricing = None
        for key, pricing in self.pricing.items():
            if key.lower() in provider_id.lower():
                provider_pricing = pricing
                break
        
        if not provider_pricing:
            provider_pricing = self.pricing.get('openrouter', {'prompt': 5.0, 'completion': 15.0})
        
        # Calculate cost
        if prompt_tokens is not None:
            completion_tokens = tokens_used - prompt_tokens
            prompt_cost = (prompt_tokens / 1_000_000) * provider_pricing.get('prompt', 0)
            completion_cost = (completion_tokens / 1_000_000) * provider_pricing.get('completion', 0)
            return prompt_cost + completion_cost
        else:
            # Assume 25% prompt, 75% completion (common for chat)
            prompt_tokens_est = tokens_used * 0.25
            completion_tokens_est = tokens_used * 0.75
            prompt_cost = (prompt_tokens_est / 1_000_000) * provider_pricing.get('prompt', 0)
            completion_cost = (completion_tokens_est / 1_000_000) * provider_pricing.get('completion', 0)
            return prompt_cost + completion_cost
    
    def get_cost_overview(self) -> Dict[str, Any]:
        """
        Get cost overview for all providers.
        
        Returns:
            Dictionary with cost estimates
        """
        providers = self.get_all_providers_stats()
        
        total_cost = 0.0
        provider_costs = []
        
        for provider in providers:
            provider_id = provider['provider_id']
            tokens = provider['tokens']
            total_tokens = tokens['TPD']  # Use daily tokens for cost estimation
            
            cost = self.estimate_cost(provider_id, total_tokens)
            total_cost += cost
            
            provider_costs.append({
                'provider_id': provider_id,
                'tokens_today': total_tokens,
                'estimated_cost': cost
            })
        
        return {
            'total_estimated_cost_today': total_cost,
            'providers': provider_costs,
            'currency': 'USD'
        }
    
    def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
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
    
    def export_to_json(self, time_range: str = '24h') -> str:
        """
        Export analytics data to JSON.
        
        Args:
            time_range: Time range for export
            
        Returns:
            JSON string with analytics data
        """
        data = {
            'export_time': datetime.now().isoformat(),
            'time_range': time_range,
            'providers': self.get_all_providers_stats(),
            'models': self.get_model_performance(),
            'cost_overview': self.get_cost_overview(),
            'recommendations': self.get_optimization_recommendations()
        }
        
        return json.dumps(data, indent=2)
    
    def export_to_csv(self, time_range: str = '24h') -> str:
        """
        Export analytics data to CSV.
        
        Args:
            time_range: Time range for export
            
        Returns:
            CSV string with analytics data
        """
        output = io.StringIO()
        
        # Provider stats CSV
        writer = csv.writer(output)
        writer.writerow(['Provider ID', 'Total Requests', 'Successful', 'Errors', 'Error Rate', 'Avg Latency (ms)', 'Tokens/Min', 'Tokens/Hour', 'Tokens/Day'])
        
        for provider in self.get_all_providers_stats():
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