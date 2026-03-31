"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Provider handlers for AISBF.

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

Provider handlers for AISBF.
"""
import httpx
import asyncio
import time
import os
import random
import math
from typing import Dict, List, Optional, Union
from google import genai
from openai import OpenAI
from anthropic import Anthropic
from pydantic import BaseModel
from .models import Provider, Model, ErrorTracking
from .config import config
from .utils import count_messages_tokens
from .database import get_database
from .batching import get_request_batcher

# Check if debug mode is enabled
AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')


class AdaptiveRateLimiter:
    """
    Adaptive Rate Limiter that learns optimal rate limits from 429 responses.
    
    Features:
    - Tracks 429 patterns per provider
    - Implements exponential backoff with jitter for retries
    - Learns optimal rate limits from historical 429 data
    - Adds rate limit headroom (stays below limits)
    - Gradually recovers rate limits after cooldown periods
    """
    
    def __init__(self, provider_id: str, config: Dict = None):
        self.provider_id = provider_id
        
        # Configuration with defaults
        self.enabled = config.get('enabled', True) if config else True
        self.initial_rate_limit = config.get('initial_rate_limit', 0) if config else 0
        self.learning_rate = config.get('learning_rate', 0.1) if config else 0.1
        self.headroom_percent = config.get('headroom_percent', 10) if config else 10  # Stay 10% below learned limit
        self.recovery_rate = config.get('recovery_rate', 0.05) if config else 0.05  # 5% recovery per successful request
        self.max_rate_limit = config.get('max_rate_limit', 60) if config else 60  # Max 60 seconds between requests
        self.min_rate_limit = config.get('min_rate_limit', 0.1) if config else 0.1  # Min 0.1 seconds between requests
        self.backoff_base = config.get('backoff_base', 2) if config else 2
        self.jitter_factor = config.get('jitter_factor', 0.25) if config else 0.25  # 25% jitter
        self.history_window = config.get('history_window', 3600) if config else 3600  # 1 hour history window
        self.consecutive_successes_for_recovery = config.get('consecutive_successes_for_recovery', 10) if config else 10
        
        # Learned rate limit (starts with configured value)
        self.current_rate_limit = self.initial_rate_limit
        self.base_rate_limit = self.initial_rate_limit  # Original configured limit
        
        # 429 tracking
        self._429_history = []  # List of (timestamp, wait_seconds) tuples
        self._consecutive_429s = 0
        self._consecutive_successes = 0
        
        # Statistics
        self.total_429_count = 0
        self.total_requests = 0
        self.last_429_time = None
        
    def record_429(self, wait_seconds: int):
        """Record a 429 response and adjust rate limit accordingly."""
        import logging
        logger = logging.getLogger(__name__)
        
        current_time = time.time()
        
        # Record this 429 in history
        self._429_history.append((current_time, wait_seconds))
        self.total_429_count += 1
        self._consecutive_429s += 1
        self._consecutive_successes = 0
        self.last_429_time = current_time
        
        # Clean old history
        self._cleanup_history()
        
        # Calculate new rate limit using exponential backoff
        # New limit = current_limit * backoff_base + wait_seconds from server
        new_limit = self.current_rate_limit * self.backoff_base + wait_seconds
        
        # Apply learning rate adjustment
        new_limit = self.current_rate_limit + (new_limit - self.current_rate_limit) * self.learning_rate
        
        # Apply headroom (stay below the limit)
        new_limit = new_limit * (1 - self.headroom_percent / 100)
        
        # Clamp to min/max
        self.current_rate_limit = max(self.min_rate_limit, min(self.max_rate_limit, new_limit))
        
        logger.info(f"[AdaptiveRateLimiter {self.provider_id}] 429 recorded: wait_seconds={wait_seconds}, "
                   f"new_rate_limit={self.current_rate_limit:.2f}s, consecutive_429s={self._consecutive_429s}")
    
    def record_success(self):
        """Record a successful request and gradually recover rate limit."""
        import logging
        logger = logging.getLogger(__name__)
        
        self.total_requests += 1
        self._consecutive_successes += 1
        self._consecutive_429s = 0
        
        # Gradually recover rate limit after successful requests
        if self._consecutive_successes >= self.consecutive_successes_for_recovery:
            # Recovery: move back towards base rate limit
            if self.current_rate_limit < self.base_rate_limit:
                old_limit = self.current_rate_limit
                self.current_rate_limit = self.current_rate_limit + (self.base_rate_limit - self.current_rate_limit) * self.recovery_rate
                # Clamp to not exceed base
                self.current_rate_limit = min(self.current_rate_limit, self.base_rate_limit)
                
                if old_limit != self.current_rate_limit:
                    logger.info(f"[AdaptiveRateLimiter {self.provider_id}] Rate limit recovery: "
                               f"{old_limit:.2f}s -> {self.current_rate_limit:.2f}s")
                
                # Reset consecutive successes counter after recovery
                self._consecutive_successes = 0
    
    def get_rate_limit(self) -> float:
        """Get the current adaptive rate limit."""
        return self.current_rate_limit
    
    def get_wait_time(self) -> float:
        """Get the wait time before next request based on adaptive rate limiting."""
        if not self.enabled or self.current_rate_limit <= 0:
            return 0
        
        # Use current adaptive rate limit
        return self.current_rate_limit
    
    def calculate_backoff_with_jitter(self, attempt: int, base_wait: int = None) -> float:
        """
        Calculate exponential backoff wait time with jitter.
        
        Args:
            attempt: Current retry attempt number (0-indexed)
            base_wait: Optional base wait time from server response
            
        Returns:
            Wait time in seconds with jitter applied
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Calculate exponential backoff
        if base_wait is not None and base_wait > 0:
            # Use server-provided wait time as base
            wait_time = base_wait
        else:
            # Use exponential backoff: base * 2^attempt
            wait_time = self.backoff_base ** attempt
        
        # Apply jitter: random factor between (1 - jitter_factor) and (1 + jitter_factor)
        jitter_multiplier = 1 + random.uniform(-self.jitter_factor, self.jitter_factor)
        wait_time = wait_time * jitter_multiplier
        
        # Clamp to reasonable limits (1 second to 300 seconds)
        wait_time = max(1, min(300, wait_time))
        
        logger.info(f"[AdaptiveRateLimiter {self.provider_id}] Backoff calculation: attempt={attempt}, "
                   f"base_wait={base_wait}, jitter_multiplier={jitter_multiplier:.2f}, "
                   f"final_wait={wait_time:.2f}s")
        
        return wait_time
    
    def _cleanup_history(self):
        """Remove old entries from 429 history."""
        current_time = time.time()
        cutoff_time = current_time - self.history_window
        self._429_history = [(ts, ws) for ts, ws in self._429_history if ts > cutoff_time]
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics."""
        self._cleanup_history()
        
        return {
            'provider_id': self.provider_id,
            'enabled': self.enabled,
            'current_rate_limit': self.current_rate_limit,
            'base_rate_limit': self.base_rate_limit,
            'total_429_count': self.total_429_count,
            'total_requests': self.total_requests,
            'consecutive_429s': self._consecutive_429s,
            'consecutive_successes': self._consecutive_successes,
            'recent_429_count': len(self._429_history),
            'last_429_time': self.last_429_time
        }
    
    def reset(self):
        """Reset the adaptive rate limiter to initial state."""
        import logging
        logger = logging.getLogger(__name__)
        
        self.current_rate_limit = self.initial_rate_limit
        self._429_history = []
        self._consecutive_429s = 0
        self._consecutive_successes = 0
        self.total_429_count = 0
        self.total_requests = 0
        self.last_429_time = None
        
        logger.info(f"[AdaptiveRateLimiter {self.provider_id}] Reset to initial state")


# Global adaptive rate limiters registry
_adaptive_rate_limiters: Dict[str, AdaptiveRateLimiter] = {}


def get_adaptive_rate_limiter(provider_id: str, config: Dict = None) -> AdaptiveRateLimiter:
    """Get or create an adaptive rate limiter for a provider."""
    global _adaptive_rate_limiters
    
    if provider_id not in _adaptive_rate_limiters:
        _adaptive_rate_limiters[provider_id] = AdaptiveRateLimiter(provider_id, config)
    
    return _adaptive_rate_limiters[provider_id]


def get_all_adaptive_rate_limiters() -> Dict[str, AdaptiveRateLimiter]:
    """Get all adaptive rate limiters."""
    global _adaptive_rate_limiters
    return _adaptive_rate_limiters


class BaseProviderHandler:
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        self.provider_id = provider_id
        self.api_key = api_key
        self.error_tracking = config.error_tracking[provider_id]
        self.last_request_time = 0
        self.rate_limit = config.providers[provider_id].rate_limit
        # Add model-level rate limit tracking
        self.model_last_request_time = {}  # {model_name: timestamp}
        # Token usage tracking for rate limits
        self.token_usage = {}  # {model_name: {"TPM": [], "TPH": [], "TPD": []}}
        # Initialize batcher
        self.batcher = get_request_batcher()
        # Initialize adaptive rate limiter
        adaptive_config = None
        if config.aisbf and config.aisbf.adaptive_rate_limiting:
            adaptive_config = config.aisbf.adaptive_rate_limiting.dict()
        self.adaptive_limiter = get_adaptive_rate_limiter(provider_id, adaptive_config)
    
    def parse_429_response(self, response_data: Union[Dict, str], headers: Dict = None) -> Optional[int]:
        """
        Parse 429 rate limit response to extract wait time in seconds.
        
        Checks multiple sources:
        1. Retry-After header (seconds or HTTP date)
        2. X-RateLimit-Reset header (Unix timestamp)
        3. Response body fields (retry_after, reset_time, etc.)
        4. X-RateLimit-* headers for auto-configuration
        
        Returns:
            Wait time in seconds, or None if cannot be determined
        """
        import logging
        import re
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        
        logger = logging.getLogger(__name__)
        logger.info("=== PARSING 429 RATE LIMIT RESPONSE ===")
        
        wait_seconds = None
        rate_limit_headers = {}  # Store rate limit headers for auto-configuration
        
        # Check for rate limit headers (for auto-configuration)
        if headers:
            rate_limit_headers = {
                'limit': headers.get('X-RateLimit-Limit') or headers.get('x-ratelimit-limit'),
                'remaining': headers.get('X-RateLimit-Remaining') or headers.get('x-ratelimit-remaining'),
                'reset': headers.get('X-RateLimit-Reset') or headers.get('x-ratelimit-reset'),
                'reset_at': headers.get('X-RateLimit-Reset-After') or headers.get('x-ratelimit-reset-after')
            }
            logger.info(f"Rate limit headers found: {rate_limit_headers}")
        
        # Check Retry-After header
        if headers:
            retry_after = headers.get('Retry-After') or headers.get('retry-after')
            if retry_after:
                logger.info(f"Found Retry-After header: {retry_after}")
                try:
                    # Try parsing as integer (seconds)
                    wait_seconds = int(retry_after)
                    logger.info(f"Parsed Retry-After as seconds: {wait_seconds}")
                except ValueError:
                    # Try parsing as HTTP date
                    try:
                        retry_date = parsedate_to_datetime(retry_after)
                        now = datetime.now(timezone.utc)
                        wait_seconds = int((retry_date - now).total_seconds())
                        logger.info(f"Parsed Retry-After as date, wait seconds: {wait_seconds}")
                    except Exception as e:
                        logger.warning(f"Failed to parse Retry-After header: {e}")
            
            # Check X-RateLimit-Reset header (Unix timestamp)
            if not wait_seconds:
                reset_time = headers.get('X-RateLimit-Reset') or headers.get('x-ratelimit-reset')
                if reset_time:
                    logger.info(f"Found X-RateLimit-Reset header: {reset_time}")
                    try:
                        reset_timestamp = int(reset_time)
                        now_timestamp = int(time.time())
                        wait_seconds = reset_timestamp - now_timestamp
                        logger.info(f"Calculated wait from reset timestamp: {wait_seconds} seconds")
                    except Exception as e:
                        logger.warning(f"Failed to parse X-RateLimit-Reset header: {e}")
        
        # Check response body
        if not wait_seconds and isinstance(response_data, dict):
            logger.info(f"Checking response body for rate limit info: {response_data}")
            
            # Common field names for retry/reset time
            retry_fields = [
                'retry_after', 'retryAfter', 'retry_after_seconds',
                'wait_seconds', 'waitSeconds', 'retry_in'
            ]
            reset_fields = [
                'reset_time', 'resetTime', 'reset_at', 'resetAt',
                'reset_timestamp', 'resetTimestamp'
            ]
            
            # Check retry fields (direct seconds)
            for field in retry_fields:
                if field in response_data:
                    try:
                        wait_seconds = int(response_data[field])
                        logger.info(f"Found {field} in response body: {wait_seconds} seconds")
                        break
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse {field}: {e}")
            
            # Check reset fields (timestamp)
            if not wait_seconds:
                for field in reset_fields:
                    if field in response_data:
                        try:
                            reset_timestamp = int(response_data[field])
                            now_timestamp = int(time.time())
                            wait_seconds = reset_timestamp - now_timestamp
                            logger.info(f"Found {field} in response body, calculated wait: {wait_seconds} seconds")
                            break
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to parse {field}: {e}")
            
            # Check for error message with time information
            if not wait_seconds:
                error_msg = response_data.get('error', {})
                if isinstance(error_msg, dict):
                    message = error_msg.get('message', '')
                elif isinstance(error_msg, str):
                    message = error_msg
                else:
                    message = response_data.get('message', '')
                
                if message:
                    logger.info(f"Checking error message for time info: {message}")
                    # Look for patterns like "try again in X seconds/minutes/hours"
                    patterns = [
                        r'try again in (\d+)\s*(second|minute|hour|day)s?',
                        r'retry after (\d+)\s*(second|minute|hour|day)s?',
                        r'wait (\d+)\s*(second|minute|hour|day)s?',
                        r'available in (\d+)\s*(second|minute|hour|day)s?',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, message, re.IGNORECASE)
                        if match:
                            value = int(match.group(1))
                            unit = match.group(2).lower()
                            
                            # Convert to seconds
                            multipliers = {
                                'second': 1,
                                'minute': 60,
                                'hour': 3600,
                                'day': 86400
                            }
                            wait_seconds = value * multipliers.get(unit, 1)
                            logger.info(f"Extracted wait time from message: {value} {unit}(s) = {wait_seconds} seconds")
                            break
        
        # Ensure wait_seconds is positive and reasonable
        if wait_seconds:
            if wait_seconds < 0:
                logger.warning(f"Calculated negative wait time: {wait_seconds}, setting to 60 seconds")
                wait_seconds = 60
            elif wait_seconds > 86400:  # More than 1 day
                logger.warning(f"Calculated very long wait time: {wait_seconds}, capping at 1 day")
                wait_seconds = 86400
            
            logger.info(f"Final parsed wait time: {wait_seconds} seconds")
        else:
            logger.warning("Could not determine wait time from 429 response, using default 60 seconds")
            wait_seconds = 60
        
        logger.info("=== END PARSING 429 RATE LIMIT RESPONSE ===")
        return wait_seconds
    
    def handle_429_error(self, response_data: Union[Dict, str] = None, headers: Dict = None):
        """
        Handle 429 rate limit error by parsing the response and disabling provider
        for the appropriate duration. Also records the 429 in the adaptive rate limiter.
        
        Optionally auto-configures rate limits if not already configured.
        
        Args:
            response_data: Response body (dict or string)
            headers: Response headers
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.error("=== 429 RATE LIMIT ERROR DETECTED ===")
        logger.error(f"Provider: {self.provider_id}")
        
        # Parse the response to get wait time
        wait_seconds = self.parse_429_response(response_data, headers)
        
        # Record 429 in adaptive rate limiter for learning
        self.adaptive_limiter.record_429(wait_seconds)
        
        # Check for rate limit headers and auto-configure if not already set
        if headers:
            self._auto_configure_rate_limits(headers)
        
        # Disable provider for the calculated duration
        self.error_tracking['disabled_until'] = time.time() + wait_seconds
        
        logger.error(f"!!! PROVIDER DISABLED DUE TO RATE LIMIT !!!")
        logger.error(f"Provider: {self.provider_id}")
        logger.error(f"Reason: 429 Too Many Requests")
        logger.error(f"Disabled for: {wait_seconds} seconds ({wait_seconds / 60:.1f} minutes)")
        logger.error(f"Disabled until: {self.error_tracking['disabled_until']}")
        logger.error(f"Adaptive rate limit: {self.adaptive_limiter.current_rate_limit:.2f}s")
        logger.error(f"Provider will be automatically re-enabled after cooldown")
        logger.error("=== END 429 RATE LIMIT ERROR ===")

    def _auto_configure_rate_limits(self, headers: Dict = None):
        """
        Auto-configure rate limits from response headers if not already configured.
        
        Looks for X-RateLimit-* headers and saves them to the provider config.
        
        Args:
            headers: Response headers from the API
        """
        import logging
        from .config import config
        
        logger = logging.getLogger(__name__)
        
        if not headers:
            return
        
        # Extract rate limit headers
        rate_limit_header = headers.get('X-RateLimit-Limit') or headers.get('x-ratelimit-limit')
        remaining_header = headers.get('X-RateLimit-Remaining') or headers.get('x-ratelimit-remaining')
        reset_header = headers.get('X-RateLimit-Reset') or headers.get('x-ratelimit-reset')
        
        if not rate_limit_header:
            logger.debug("No X-RateLimit-Limit header found, skipping auto-configuration")
            return
        
        try:
            rate_limit_value = int(rate_limit_header)
            logger.info(f"Found rate limit header: {rate_limit_value} requests")
            
            # Get current provider config
            provider_config = config.providers.get(self.provider_id)
            if not provider_config:
                logger.debug(f"Provider {self.provider_id} not found in config")
                return
            
            # Check if we don't have a rate limit configured
            current_rate_limit = getattr(provider_config, 'rate_limit', None)
            if current_rate_limit is None or current_rate_limit == 0:
                # Calculate: use 80% of the limit to stay below it
                auto_rate_limit = rate_limit_value * 0.8
                
                logger.info(f"Auto-configuring rate limit for {self.provider_id}: {auto_rate_limit:.1f}s (from header limit: {rate_limit_value})")
                
                # Try to save to config (this may not persist if config is immutable)
                try:
                    # Update the in-memory config
                    if hasattr(provider_config, 'rate_limit'):
                        provider_config.rate_limit = auto_rate_limit
                        logger.info(f"✓ Auto-configured rate_limit: {auto_rate_limit:.1f}s for provider {self.provider_id}")
                except Exception as e:
                    logger.debug(f"Could not auto-configure rate limit: {e}")
            else:
                logger.debug(f"Rate limit already configured ({current_rate_limit}), skipping auto-configuration")
                
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse rate limit header: {e}")

    def is_rate_limited(self) -> bool:
        if self.error_tracking['disabled_until'] and self.error_tracking['disabled_until'] > time.time():
            return True
        return False
    
    def _get_model_config(self, model: str) -> Optional[Dict]:
        """Get model configuration from provider config"""
        provider_config = config.providers.get(self.provider_id)
        if provider_config and hasattr(provider_config, 'models') and provider_config.models:
            for model_config in provider_config.models:
                # Handle both Pydantic objects and dictionaries
                model_name_value = model_config.name if hasattr(model_config, 'name') else model_config.get('name')
                if model_name_value == model:
                    # Convert Pydantic object to dict if needed
                    if hasattr(model_config, 'model_dump'):
                        return model_config.model_dump()
                    elif hasattr(model_config, 'dict'):
                        return model_config.dict()
                    else:
                        return model_config
        return None
    
    def _check_token_rate_limit(self, model: str, token_count: int) -> bool:
        """
        Check if a request would exceed token rate limits.
        
        Returns True if any rate limit would be exceeded, False otherwise.
        """
        model_config = self._get_model_config(model)
        if not model_config:
            return False
        
        import logging
        logger = logging.getLogger(__name__)
        
        current_time = time.time()
        
        # Check TPM (tokens per minute)
        if model_config.get('rate_limit_TPM'):
            tpm = model_config['rate_limit_TPM']
            # Get tokens used in the last minute
            tokens_used_tpm = self.token_usage.get(model, {}).get('TPM', [])
            # Filter to only include requests from the last 60 seconds
            one_minute_ago = current_time - 60
            recent_tokens_tpm = [t for t in tokens_used_tpm if t > one_minute_ago]
            total_tpm = sum(recent_tokens_tpm)
            
            if total_tpm + token_count > tpm:
                logger.warning(f"TPM limit would be exceeded: {total_tpm + token_count}/{tpm}")
                return True
        
        # Check TPH (tokens per hour)
        if model_config.get('rate_limit_TPH'):
            tph = model_config['rate_limit_TPH']
            # Get tokens used in the last hour
            tokens_used_tph = self.token_usage.get(model, {}).get('TPH', [])
            # Filter to only include requests from the last 3600 seconds
            one_hour_ago = current_time - 3600
            recent_tokens_tph = [t for t in tokens_used_tph if t > one_hour_ago]
            total_tph = sum(recent_tokens_tph)
            
            if total_tph + token_count > tph:
                logger.warning(f"TPH limit would be exceeded: {total_tph + token_count}/{tph}")
                return True
        
        # Check TPD (tokens per day)
        if model_config.get('rate_limit_TPD'):
            tpd = model_config['rate_limit_TPD']
            # Get tokens used in the last day
            tokens_used_tpd = self.token_usage.get(model, {}).get('TPD', [])
            # Filter to only include requests from the last 86400 seconds
            one_day_ago = current_time - 86400
            recent_tokens_tpd = [t for t in tokens_used_tpd if t > one_day_ago]
            total_tpd = sum(recent_tokens_tpd)
            
            if total_tpd + token_count > tpd:
                logger.warning(f"TPD limit would be exceeded: {total_tpd + token_count}/{tpd}")
                return True
        
        return False
    
    def _record_token_usage(self, model: str, token_count: int):
        """Record token usage for rate limit tracking"""
        import logging
        logger = logging.getLogger(__name__)
        
        if model not in self.token_usage:
            self.token_usage[model] = {"TPM": [], "TPH": [], "TPD": []}
        
        current_time = time.time()
        
        # Record for all three time windows
        self.token_usage[model]["TPM"].append((current_time, token_count))
        self.token_usage[model]["TPH"].append((current_time, token_count))
        self.token_usage[model]["TPD"].append((current_time, token_count))
        
        logger.debug(f"Recorded token usage for model {model}: {token_count} tokens")
    
    def _disable_provider_for_duration(self, duration: str):
        """
        Disable provider for a specific duration.
        
        Args:
            duration: "1m" (1 minute), "1h" (1 hour), or "1d" (1 day)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        duration_map = {
            "1m": 60,
            "1h": 3600,
            "1d": 86400
        }
        
        if duration not in duration_map:
            logger.error(f"Invalid duration: {duration}")
            return
        
        disable_seconds = duration_map[duration]
        self.error_tracking['disabled_until'] = time.time() + disable_seconds
        
        logger.error(f"!!! PROVIDER DISABLED !!!")
        logger.error(f"Provider: {self.provider_id}")
        logger.error(f"Reason: Token rate limit exceeded")
        logger.error(f"Disabled for: {duration}")
        logger.error(f"Disabled until: {self.error_tracking['disabled_until']}")
        logger.error(f"Provider will be automatically re-enabled after cooldown")

    async def apply_rate_limit(self, rate_limit: Optional[float] = None):
        """Apply rate limiting by waiting if necessary, using adaptive rate limiting."""
        import logging
        logger = logging.getLogger(__name__)
        
        # Use adaptive rate limiter if enabled
        if self.adaptive_limiter.enabled:
            adaptive_limit = self.adaptive_limiter.get_rate_limit()
            
            if rate_limit is None:
                rate_limit = adaptive_limit
            else:
                # Use the higher of the two (more conservative)
                rate_limit = max(rate_limit, adaptive_limit)
        elif rate_limit is None:
            rate_limit = self.rate_limit

        if rate_limit and rate_limit > 0:
            current_time = time.time()
            time_since_last_request = current_time - self.last_request_time
            required_wait = rate_limit - time_since_last_request

            if required_wait > 0:
                logger.info(f"[RateLimit] Provider {self.provider_id}: waiting {required_wait:.2f}s (adaptive: {self.adaptive_limiter.enabled})")
                await asyncio.sleep(required_wait)

            self.last_request_time = time.time()

    async def apply_model_rate_limit(self, model: str, rate_limit: Optional[float] = None):
        """Apply rate limiting for a specific model, using adaptive rate limiting."""
        import logging
        logger = logging.getLogger(__name__)
        
        # Use adaptive rate limiter if enabled
        if self.adaptive_limiter.enabled:
            adaptive_limit = self.adaptive_limiter.get_rate_limit()
            
            if rate_limit is None:
                rate_limit = adaptive_limit
            else:
                rate_limit = max(rate_limit, adaptive_limit)
        elif rate_limit is None:
            rate_limit = self.rate_limit

        if rate_limit and rate_limit > 0:
            current_time = time.time()
            last_time = self.model_last_request_time.get(model, 0)
            time_since_last_request = current_time - last_time
            required_wait = rate_limit - time_since_last_request

            if required_wait > 0:
                logger.info(f"[RateLimit] Model {model}: waiting {required_wait:.2f}s (adaptive: {self.adaptive_limiter.enabled})")
                await asyncio.sleep(required_wait)

            self.model_last_request_time[model] = time.time()

    def record_failure(self):
        import logging
        logger = logging.getLogger(__name__)
        
        self.error_tracking['failures'] += 1
        self.error_tracking['last_failure'] = time.time()
        
        failure_count = self.error_tracking['failures']
        logger.warning(f"=== PROVIDER FAILURE RECORDED ===")
        logger.warning(f"Provider: {self.provider_id}")
        logger.warning(f"Failure count: {failure_count}/3")
        logger.warning(f"Last failure time: {self.error_tracking['last_failure']}")
        
        if self.error_tracking['failures'] >= 3:
            # Get cooldown period from provider config, default to 300 seconds (5 minutes)
            provider_config = config.providers.get(self.provider_id)
            cooldown_seconds = 300  # System default
            
            if provider_config and hasattr(provider_config, 'default_error_cooldown') and provider_config.default_error_cooldown is not None:
                cooldown_seconds = provider_config.default_error_cooldown
                logger.info(f"Using provider-configured cooldown: {cooldown_seconds} seconds")
            else:
                logger.info(f"Using system default cooldown: {cooldown_seconds} seconds")
            
            self.error_tracking['disabled_until'] = time.time() + cooldown_seconds
            disabled_until_time = self.error_tracking['disabled_until']
            cooldown_remaining = int(disabled_until_time - time.time())
            logger.error(f"!!! PROVIDER DISABLED !!!")
            logger.error(f"Provider: {self.provider_id}")
            logger.error(f"Reason: 3 consecutive failures reached")
            logger.error(f"Disabled until: {disabled_until_time}")
            logger.error(f"Cooldown period: {cooldown_remaining} seconds ({cooldown_seconds / 60:.1f} minutes)")
            logger.error(f"Provider will be automatically re-enabled after cooldown")
        else:
            remaining_failures = 3 - failure_count
            logger.warning(f"Provider still active. {remaining_failures} more failure(s) will disable it")
        logger.warning(f"=== END FAILURE RECORDING ===")

    def record_success(self):
        import logging
        logger = logging.getLogger(__name__)
        
        was_disabled = self.error_tracking['disabled_until'] is not None
        previous_failures = self.error_tracking['failures']
        
        self.error_tracking['failures'] = 0
        self.error_tracking['disabled_until'] = None
        
        # Record success in adaptive rate limiter
        self.adaptive_limiter.record_success()
        
        logger.info(f"=== PROVIDER SUCCESS RECORDED ===")
        logger.info(f"Provider: {self.provider_id}")
        logger.info(f"Previous failure count: {previous_failures}")
        logger.info(f"Failure count reset to: 0")
        logger.info(f"Adaptive rate limit: {self.adaptive_limiter.current_rate_limit:.2f}s")
        
        if was_disabled:
            logger.info(f"!!! PROVIDER RE-ENABLED !!!")
            logger.info(f"Provider: {self.provider_id}")
            logger.info(f"Reason: Successful request after cooldown period")
            logger.info(f"Provider is now active and available for requests")
        else:
            logger.info(f"Provider remains active")
        logger.info(f"=== END SUCCESS RECORDING ===")

    async def handle_request_with_batching(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                                          temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                                          tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        """
        Handle a request with optional batching.
        
        Args:
            model: The model name
            messages: The messages to send
            max_tokens: Max output tokens
            temperature: Temperature setting
            stream: Whether to stream
            tools: Tool definitions
            tool_choice: Tool choice setting
            
        Returns:
            The response from the provider handler
        """
        # Check if batching is enabled and not streaming
        if self.batcher.enabled and not stream:
            # Prepare request data
            request_data = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": stream,
                "tools": tools,
                "tool_choice": tool_choice,
                "api_key": self.api_key
            }
            
            # Submit request for batching
            batched_result = await self.batcher.submit_request(
                provider_id=self.provider_id,
                model=model,
                request_data=request_data
            )
            
            # If batching returned None, it means batching is disabled or we should process directly
            if batched_result is not None:
                return batched_result
         
        # Fall back to direct processing (either batching disabled, streaming, or batching returned None)
        return await self._handle_request_direct(model, messages, max_tokens, temperature, stream, tools, tool_choice)

    async def _handle_request_direct(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                                    temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                                    tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        """
        Direct request handling without batching (original handle_request logic).
        This method should be overridden by subclasses with their specific implementation.
        """
        raise NotImplementedError("_handle_request_direct must be implemented by subclasses")

class GoogleProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        # Initialize google-genai library
        from google import genai
        self.client = genai.Client(api_key=api_key)
        # Cache storage for Google Context Caching
        self._cached_content_refs = {}  # {cache_key: (cached_content_name, expiry_time)}

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                            temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                            tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"GoogleProviderHandler: Handling request for model {model}")
            logging.info(f"GoogleProviderHandler: Stream: {stream}")
            if AISBF_DEBUG:
                logging.info(f"GoogleProviderHandler: Messages: {messages}")
            else:
                logging.info(f"GoogleProviderHandler: Messages count: {len(messages)}")

            if tools:
                logging.info(f"GoogleProviderHandler: Tools provided: {len(tools)} tools")
                if AISBF_DEBUG:
                    logging.info(f"GoogleProviderHandler: Tools: {tools}")
            if tool_choice:
                logging.info(f"GoogleProviderHandler: Tool choice: {tool_choice}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            cache_ttl = getattr(provider_config, 'cache_ttl', None)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1000)

            logging.info(f"GoogleProviderHandler: Native caching enabled: {enable_native_caching}")
            
            # Initialize cached_content_name for this request (will be set if we use caching)
            cached_content_name = None
            
            if enable_native_caching:
                logging.info(f"GoogleProviderHandler: Cache TTL: {cache_ttl} seconds, min_cacheable_tokens: {min_cacheable_tokens}")
                
                # Calculate total token count to determine if caching is beneficial
                total_tokens = count_messages_tokens(messages, model)
                logging.info(f"GoogleProviderHandler: Total message tokens: {total_tokens}")
                
                # Only use caching if total tokens exceed minimum threshold
                if total_tokens >= min_cacheable_tokens:
                    # Generate a cache key based on system message and early conversation
                    # We cache system message + early messages (not the last few turns)
                    cache_key = self._generate_cache_key(messages, model)
                    
                    logging.info(f"GoogleProviderHandler: Generated cache_key: {cache_key}")
                    
                    # Check if we have a valid cached content
                    if cache_key in self._cached_content_refs:
                        cached_content_name, expiry_time = self._cached_content_refs[cache_key]
                        current_time = time.time()
                        
                        if current_time < expiry_time:
                            logging.info(f"GoogleProviderHandler: Using cached content: {cached_content_name} (expires in {expiry_time - current_time:.0f}s)")
                        else:
                            # Cache expired, remove it
                            logging.info(f"GoogleProviderHandler: Cache expired, removing: {cached_content_name}")
                            del self._cached_content_refs[cache_key]
                            cached_content_name = None
                    else:
                        logging.info(f"GoogleProviderHandler: No cached content found for cache_key")
                    
                    # If no cached content, and we have a TTL, mark to create cache after first request
                    if cached_content_name is None and cache_ttl:
                        # We'll set this flag to create cache after first request
                        self._pending_cache_key = (cache_key, cache_ttl, messages)
                        logging.info(f"GoogleProviderHandler: Will create cached content after first request")
                    else:
                        self._pending_cache_key = None
                else:
                    logging.info(f"GoogleProviderHandler: Total tokens ({total_tokens}) below min_cacheable_tokens ({min_cacheable_tokens}), skipping cache")
                    self._pending_cache_key = None
            else:
                self._pending_cache_key = None

            # Build content from messages
            content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # Build config with only non-None values
            config = {"temperature": temperature}
            if max_tokens is not None:
                config["max_output_tokens"] = max_tokens

            # Convert OpenAI tools to Google's function calling format
            google_tools = None
            if tools:
                function_declarations = []
                for tool in tools:
                    if tool.get("type") == "function":
                        function = tool.get("function", {})
                        # Use Google's SDK types for proper validation
                        from google.genai import types as genai_types
                        function_declaration = genai_types.FunctionDeclaration(
                            name=function.get("name"),
                            description=function.get("description", ""),
                            parameters=function.get("parameters", {})
                        )
                        function_declarations.append(function_declaration)
                        logging.info(f"GoogleProviderHandler: Converted tool to Google format: {function_declaration}")
                
                if function_declarations:
                    # Google API expects tools to be a Tool object with function_declarations
                    from google.genai import types as genai_types
                    google_tools = genai_types.Tool(function_declarations=function_declarations)
                    logging.info(f"GoogleProviderHandler: Added {len(function_declarations)} tools to google_tools")
                    
                    # Add tools to config for both streaming and non-streaming
                    config["tools"] = google_tools
                    logging.info(f"GoogleProviderHandler: Added tools to config")

            # Handle streaming request
            if stream:
                logging.info(f"GoogleProviderHandler: Using streaming API")
                
                # For streaming, we don't use cached content (API limitations)
                # But we can still prepare for future caching by tracking the pending cache
                
                # Create a new client instance for streaming to ensure it stays open
                from google import genai
                stream_client = genai.Client(api_key=self.api_key)
                
                # We need to iterate over the streaming response immediately without yielding control
                # to ensure the client stays alive
                chunks = []
                
                for chunk in stream_client.models.generate_content_stream(
                    model=model,
                    contents=content,
                    config=config
                ):
                    chunks.append(chunk)
                
                logging.info(f"GoogleProviderHandler: Streaming response received (total chunks: {len(chunks)})")
                self.record_success()
                
                # After successful streaming response, create cached content if pending
                if hasattr(self, '_pending_cache_key') and self._pending_cache_key:
                    cache_key, cache_ttl, cache_messages = self._pending_cache_key
                    try:
                        new_cached_name = self._create_cached_content(cache_messages, model, cache_ttl)
                        if new_cached_name:
                            # Calculate expiry time
                            expiry_time = time.time() + cache_ttl
                            self._cached_content_refs[cache_key] = (new_cached_name, expiry_time)
                            logging.info(f"GoogleProviderHandler: Cached content stored (streaming): {new_cached_name}, expires in {cache_ttl}s")
                    except Exception as e:
                        logging.warning(f"GoogleProviderHandler: Failed to create cache after streaming: {e}")
                    self._pending_cache_key = None
                
                # Now yield chunks asynchronously - yield raw chunk objects
                # The handlers.py will handle the conversion to OpenAI format
                async def async_generator():
                    for chunk in chunks:
                        yield chunk
                
                return async_generator()
            else:
                # Non-streaming request
                # Determine if we should use cached content
                use_cached = cached_content_name is not None
                
                # Build content from messages
                if use_cached and cached_content_name:
                    # When using cached content, only send the last few messages
                    # (the ones not included in the cache)
                    last_msg_count = min(3, len(messages))
                    last_messages = messages[-last_msg_count:] if messages else []
                    content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in last_messages])
                    logging.info(f"GoogleProviderHandler: Using cached content, sending last {last_msg_count} messages")
                else:
                    content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

                # Build config with only non-None values
                config = {"temperature": temperature}
                if max_tokens is not None:
                    config["max_output_tokens"] = max_tokens

                # Convert OpenAI tools to Google's function calling format
                google_tools = None
                if tools:
                    function_declarations = []
                    for tool in tools:
                        if tool.get("type") == "function":
                            function = tool.get("function", {})
                            # Use Google's SDK types for proper validation
                            from google.genai import types as genai_types
                            function_declaration = genai_types.FunctionDeclaration(
                                name=function.get("name"),
                                description=function.get("description", ""),
                                parameters=function.get("parameters", {})
                            )
                            function_declarations.append(function_declaration)
                            logging.info(f"GoogleProviderHandler: Converted tool to Google format: {function_declaration}")
                    
                    if function_declarations:
                        # Google API expects tools to be a Tool object with function_declarations
                        from google.genai import types as genai_types
                        google_tools = genai_types.Tool(function_declarations=function_declarations)
                        logging.info(f"GoogleProviderHandler: Added {len(function_declarations)} tools to google_tools")
                        
                        # Add tools to config for both streaming and non-streaming
                        config["tools"] = google_tools
                        logging.info(f"GoogleProviderHandler: Added tools to config")

                # Generate content using the google-genai client
                if use_cached and cached_content_name:
                    # Use cached content in the request
                    try:
                        logging.info(f"GoogleProviderHandler: Making request with cached_content: {cached_content_name}")
                        response = self.client.models.generate_content(
                            model=model,
                            contents=content,
                            config=config,
                            cached_content=cached_content_name
                        )
                    except TypeError as e:
                        # cached_content parameter may not be available in this SDK version
                        # Fall back to regular request
                        logging.warning(f"GoogleProviderHandler: cached_content param not supported, using regular request: {e}")
                        response = self.client.models.generate_content(
                            model=model,
                            contents=content,
                            config=config
                        )
                else:
                    # Regular request without caching
                    response = self.client.models.generate_content(
                        model=model,
                        contents=content,
                        config=config
                    )

                logging.info(f"GoogleProviderHandler: Response received: {response}")
                self.record_success()
                
                # After successful response, create cached content if pending
                if hasattr(self, '_pending_cache_key') and self._pending_cache_key:
                    cache_key, cache_ttl, cache_messages = self._pending_cache_key
                    try:
                        new_cached_name = self._create_cached_content(cache_messages, model, cache_ttl)
                        if new_cached_name:
                            # Calculate expiry time
                            expiry_time = time.time() + cache_ttl
                            self._cached_content_refs[cache_key] = (new_cached_name, expiry_time)
                            logging.info(f"GoogleProviderHandler: Cached content stored: {new_cached_name}, expires in {cache_ttl}s")
                    except Exception as e:
                        logging.warning(f"GoogleProviderHandler: Failed to create cache after response: {e}")
                    self._pending_cache_key = None

                # Dump raw response if AISBF_DEBUG is enabled
                if AISBF_DEBUG:
                    logging.info(f"=== RAW GOOGLE RESPONSE ===")
                    logging.info(f"Raw response type: {type(response)}")
                    logging.info(f"Raw response: {response}")
                    logging.info(f"Raw response dir: {dir(response)}")
                    logging.info(f"=== END RAW GOOGLE RESPONSE ===")

                # Extract content from the nested response structure
                # The response has candidates[0].content.parts
                response_text = ""
                tool_calls = None
                finish_reason = "stop"
            
                logging.info(f"=== GOOGLE RESPONSE PARSING START ===")
                logging.info(f"Response type: {type(response)}")
                logging.info(f"Response attributes: {dir(response)}")
                
                try:
                    # Check if response has candidates
                    if hasattr(response, 'candidates'):
                        logging.info(f"Response has 'candidates' attribute")
                        logging.info(f"Candidates: {response.candidates}")
                        logging.info(f"Candidates type: {type(response.candidates)}")
                        logging.info(f"Candidates length: {len(response.candidates) if hasattr(response.candidates, '__len__') else 'N/A'}")
                        
                        if response.candidates:
                            logging.info(f"Candidates is not empty, getting first candidate")
                            candidate = response.candidates[0]
                            logging.info(f"Candidate type: {type(candidate)}")
                            logging.info(f"Candidate attributes: {dir(candidate)}")
                            
                            # Extract finish reason
                            if hasattr(candidate, 'finish_reason'):
                                logging.info(f"Candidate has 'finish_reason' attribute")
                                logging.info(f"Finish reason: {candidate.finish_reason}")
                                # Map Google finish reasons to OpenAI format
                                finish_reason_map = {
                                    'STOP': 'stop',
                                    'MAX_TOKENS': 'length',
                                    'SAFETY': 'content_filter',
                                    'RECITATION': 'content_filter',
                                    'OTHER': 'stop'
                                }
                                google_finish_reason = str(candidate.finish_reason)
                                finish_reason = finish_reason_map.get(google_finish_reason, 'stop')
                                logging.info(f"Mapped finish reason: {finish_reason}")
                            else:
                                logging.warning(f"Candidate does NOT have 'finish_reason' attribute")
                            
                            # Extract content
                            if hasattr(candidate, 'content'):
                                logging.info(f"Candidate has 'content' attribute")
                                logging.info(f"Content: {candidate.content}")
                                logging.info(f"Content type: {type(candidate.content)}")
                                logging.info(f"Content attributes: {dir(candidate.content)}")
                                
                                if candidate.content:
                                    logging.info(f"Content is not empty")
                                    
                                    if hasattr(candidate.content, 'parts'):
                                        logging.info(f"Content has 'parts' attribute")
                                        logging.info(f"Parts: {candidate.content.parts}")
                                        logging.info(f"Parts type: {type(candidate.content.parts)}")
                                        logging.info(f"Parts length: {len(candidate.content.parts) if hasattr(candidate.content.parts, '__len__') else 'N/A'}")
                                        
                                        if candidate.content.parts:
                                            logging.info(f"Parts is not empty, processing all parts")
                                            
                                            # Process all parts to extract text and tool calls
                                            text_parts = []
                                            openai_tool_calls = []
                                            call_id = 0
                                            
                                            for idx, part in enumerate(candidate.content.parts):
                                                logging.info(f"Processing part {idx}")
                                                logging.info(f"Part type: {type(part)}")
                                                logging.info(f"Part attributes: {dir(part)}")
                                                
                                                # Check for text content
                                                if hasattr(part, 'text') and part.text:
                                                    logging.info(f"Part {idx} has 'text' attribute")
                                                    text_parts.append(part.text)
                                                    logging.info(f"Part {idx} text length: {len(part.text)}")
                                                
                                                # Check for function calls (Google's format)
                                                if hasattr(part, 'function_call') and part.function_call:
                                                    logging.info(f"Part {idx} has 'function_call' attribute")
                                                    logging.info(f"Function call: {part.function_call}")
                                                    
                                                    # Convert Google function call to OpenAI format
                                                    try:
                                                        function_call = part.function_call
                                                        openai_tool_call = {
                                                            "id": f"call_{call_id}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": function_call.name,
                                                                "arguments": function_call.args if hasattr(function_call, 'args') else {}
                                                            }
                                                        }
                                                        openai_tool_calls.append(openai_tool_call)
                                                        call_id += 1
                                                        logging.info(f"Converted function call to OpenAI format: {openai_tool_call}")
                                                    except Exception as e:
                                                        logging.error(f"Error converting function call: {e}", exc_info=True)
                                                
                                                # Check for function response (tool output)
                                                if hasattr(part, 'function_response') and part.function_response:
                                                    logging.info(f"Part {idx} has 'function_response' attribute")
                                                    logging.info(f"Function response: {part.function_response}")
                                                    # Function responses are typically handled in the request, not response
                                                    # But we log them for debugging
                                            
                                            # Combine all text parts
                                            response_text = "\n".join(text_parts)
                                            logging.info(f"Combined text length: {len(response_text)}")
                                            logging.info(f"Combined text (first 200 chars): {response_text[:200] if response_text else 'None'}")
                                            
                                            # Check if response_text contains JSON that looks like a tool call
                                            # Some models return tool calls as text content instead of using function_call attribute
                                            if response_text and not openai_tool_calls:
                                                import json
                                                import re

                                                # Pattern for Google model tool intent text
                                                # Examples: "Let's execite the read", "I need to use the read tool", "Using the read tool"
                                                google_tool_intent_patterns = [
                                                    r"(?:^|\n)\s*(?:Let(?:'s|s us)?)\s*(?:execite|execute|use|call)\s*(?:the\s+)?(\w+)\s*(?:tool)?",
                                                    r"(?:^|\n)\s*(?:I(?:'m| am)?|We(?:'re| are)?)\s*(?:going to |just )?(?:execite|execut(?:e|ed)?|use|call)\s*(?:the\s+)?(\w+)\s*(?:tool)?",
                                                    r"(?:^|\n)\s*(?:I(?:'m| am)?|We(?:'re| are)?)\s*(?:going to |just )?read\s+(?:the\s+)?file[s]?",
                                                    r"(?:^|\n)\s*Using\s+(?:the\s+)?(\w+)\s*(?:tool)?",
                                                ]
                                                for pattern in google_tool_intent_patterns:
                                                    tool_intent_match = re.search(pattern, response_text, re.IGNORECASE)
                                                    if tool_intent_match:
                                                        tool_name = tool_intent_match.group(1).lower() if tool_intent_match.lastindex else ''
                                                        # Map common verbs/nouns to tool names
                                                        if tool_name in ['read', 'file', 'files', 'execite', '']:
                                                            tool_name = 'read'
                                                        elif tool_name in ['write', 'create']:
                                                            tool_name = 'write'
                                                        elif tool_name in ['exec', 'command', 'shell', 'run']:
                                                            tool_name = 'exec'
                                                        elif tool_name in ['edit', 'modify']:
                                                            tool_name = 'edit'
                                                        elif tool_name in ['search', 'find']:
                                                            tool_name = 'web_search'
                                                        elif tool_name in ['browser', 'browse', 'navigate']:
                                                            tool_name = 'browser'

                                                        logging.warning(f"Google model indicated intent to use '{tool_name}' tool (matched pattern: {pattern})")

                                                        # Try to extract parameters from the response
                                                        params = {}

                                                        # Look for file path patterns
                                                        path_patterns = [
                                                            r"['\"]([^'\"]+\.md)['\"]",
                                                            r"(?:file|path)s?\s*[:=]\s*['\"]([^'\"]+)['\"]",
                                                            r"(?:path|file)\s*[:=]\s*['\"]([^'\"]+)['\"]",
                                                            r"(?:open|read)\s+['\"]([^'\"]+)['\"]",
                                                        ]
                                                        for pp in path_patterns:
                                                            path_match = re.search(pp, response_text, re.IGNORECASE)
                                                            if path_match:
                                                                params['path'] = path_match.group(1)
                                                                break

                                                        # Look for line range patterns
                                                        offset_match = re.search(r'(?:offset|start|line\s*#?)\s*[:=]?\s*(\d+)', response_text, re.IGNORECASE)
                                                        if offset_match:
                                                            params['offset'] = int(offset_match.group(1))

                                                        limit_match = re.search(r'(?:limit|lines?|count)\s*[:=]?\s*(\d+)', response_text, re.IGNORECASE)
                                                        if limit_match:
                                                            params['limit'] = int(limit_match.group(1))

                                                        # Look for command patterns (for exec tool)
                                                        if tool_name == 'exec':
                                                            cmd_patterns = [
                                                                r"(?:command|cmd|run)\s*[:=]?\s*['\"]([^'\"]+)['\"]",
                                                                r"(?:run|execute)\s+(?:command\s+)?(['\"]([^'\"]+)['\"]|\S+)",
                                                            ]
                                                            for cp in cmd_patterns:
                                                                cmd_match = re.search(cp, response_text, re.IGNORECASE)
                                                                if cmd_match:
                                                                    params['command'] = cmd_match.group(1) or cmd_match.group(2)
                                                                    break

                                                        if params:
                                                            openai_tool_calls.append({
                                                                "id": f"call_{call_id}",
                                                                "type": "function",
                                                                "function": {
                                                                    "name": tool_name,
                                                                    "arguments": json.dumps(params)
                                                                }
                                                            })
                                                            call_id += 1
                                                            logging.info(f"Converted Google tool intent to OpenAI format: {openai_tool_calls[-1]}")
                                                            # Don't clear response_text - let the text be returned alongside
                                                        break
                                            # Check if response_text contains JSON that looks like a tool call
                                            # Some models return tool calls as text content instead of using function_call attribute
                                            if response_text and not openai_tool_calls:
                                                import json
                                                import re
                                                
                                                # Pattern 0: "assistant: [...]" wrapping everything (nested format)
                                                # The entire response is wrapped in assistant: [{'type': 'text', 'text': 'tool: {...}...'}]
                                                outer_assistant_pattern = r"^assistant:\s*(\[.*\])\s*$"
                                                outer_assistant_match = re.match(outer_assistant_pattern, response_text.strip(), re.DOTALL)
                                                
                                                if outer_assistant_match:
                                                    try:
                                                        outer_content = json.loads(outer_assistant_match.group(1))
                                                        if isinstance(outer_content, list) and len(outer_content) > 0:
                                                            for item in outer_content:
                                                                if isinstance(item, dict) and item.get('type') == 'text':
                                                                    inner_text = item.get('text', '')
                                                                    # Now parse the inner text for tool calls
                                                                    inner_tool_pattern = r'tool:\s*(\{.*?\})\s*(?:assistant:\s*(\[.*\]))?\s*$'
                                                                    inner_tool_match = re.search(inner_tool_pattern, inner_text, re.DOTALL)
                                                                    
                                                                    if inner_tool_match:
                                                                        tool_json_str = inner_tool_match.group(1)
                                                                        # Parse the tool JSON - handle multi-line content
                                                                        try:
                                                                            # Extract JSON using a more robust method
                                                                            tool_start = inner_text.find('tool:')
                                                                            if tool_start != -1:
                                                                                json_start = inner_text.find('{', tool_start)
                                                                                brace_count = 0
                                                                                json_end = json_start
                                                                                for i, c in enumerate(inner_text[json_start:], json_start):
                                                                                    if c == '{':
                                                                                        brace_count += 1
                                                                                    elif c == '}':
                                                                                        brace_count -= 1
                                                                                        if brace_count == 0:
                                                                                            json_end = i + 1
                                                                                            break
                                                                                tool_json_str = inner_text[json_start:json_end]
                                                                                parsed_tool = json.loads(tool_json_str)
                                                                                
                                                                                # Convert to OpenAI tool_calls format
                                                                                openai_tool_call = {
                                                                                    "id": f"call_{call_id}",
                                                                                    "type": "function",
                                                                                    "function": {
                                                                                        "name": parsed_tool.get('action', parsed_tool.get('name', 'unknown')),
                                                                                        "arguments": json.dumps({k: v for k, v in parsed_tool.items() if k not in ['action', 'name']})
                                                                                    }
                                                                                }
                                                                                openai_tool_calls.append(openai_tool_call)
                                                                                call_id += 1
                                                                                logging.info(f"Converted nested 'tool:' format to OpenAI tool_calls: {openai_tool_call}")
                                                                                
                                                                                # Extract the final assistant text if present
                                                                                if inner_tool_match.group(2):
                                                                                    try:
                                                                                        final_assistant = json.loads(inner_tool_match.group(2))
                                                                                        if isinstance(final_assistant, list) and len(final_assistant) > 0:
                                                                                            for final_item in final_assistant:
                                                                                                if isinstance(final_item, dict) and final_item.get('type') == 'text':
                                                                                                    response_text = final_item.get('text', '')
                                                                                                    break
                                                                                            else:
                                                                                                response_text = ""
                                                                                        else:
                                                                                            response_text = ""
                                                                                    except json.JSONDecodeError:
                                                                                        response_text = ""
                                                                                else:
                                                                                    response_text = ""
                                                                        except (json.JSONDecodeError, Exception) as e:
                                                                            logging.debug(f"Failed to parse nested tool JSON: {e}")
                                                                    break
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Failed to parse outer assistant format: {e}")
                                                
                                                # Pattern 1: "tool: {...}" format (not nested)
                                                elif not openai_tool_calls:
                                                    tool_pattern = r'tool:\s*(\{[^}]*\})'
                                                    tool_match = re.search(tool_pattern, response_text, re.DOTALL)
                                                    try:
                                                        tool_json_str = tool_match.group(1)
                                                        parsed_json = json.loads(tool_json_str)
                                                        logging.info(f"Detected 'tool:' format in text content: {parsed_json}")
                                                        
                                                        # Convert to OpenAI tool_calls format
                                                        openai_tool_call = {
                                                            "id": f"call_{call_id}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": parsed_json.get('action', parsed_json.get('name', 'unknown')),
                                                                "arguments": json.dumps({k: v for k, v in parsed_json.items() if k not in ['action', 'name']})
                                                            }
                                                        }
                                                        openai_tool_calls.append(openai_tool_call)
                                                        call_id += 1
                                                        logging.info(f"Converted 'tool:' format to OpenAI tool_calls: {openai_tool_call}")
                                                        
                                                        # Extract any assistant text after the tool call
                                                        assistant_pattern = r"assistant:\s*(\[.*\])"
                                                        assistant_match = re.search(assistant_pattern, response_text, re.DOTALL)
                                                        if assistant_match:
                                                            try:
                                                                assistant_content = json.loads(assistant_match.group(1))
                                                                # Extract text from the assistant content
                                                                if isinstance(assistant_content, list) and len(assistant_content) > 0:
                                                                    for item in assistant_content:
                                                                        if isinstance(item, dict) and item.get('type') == 'text':
                                                                            response_text = item.get('text', '')
                                                                            break
                                                                    else:
                                                                        response_text = ""
                                                                else:
                                                                    response_text = ""
                                                            except json.JSONDecodeError:
                                                                response_text = ""
                                                        else:
                                                            # Clear response_text since we're using tool_calls instead
                                                            response_text = ""
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Failed to parse 'tool:' format: {e}")
                                                
                                                elif content_assistant_match:
                                                    # Handle "content": "..." } assistant: [...] format
                                                    try:
                                                        tool_content = content_assistant_match.group(1)
                                                        assistant_json_str = content_assistant_match.group(2)
                                                        
                                                        logging.info(f"Detected 'content/assistant:' format - tool content length: {len(tool_content)}")
                                                        
                                                        # The content is the tool argument - treat as a write action
                                                        openai_tool_call = {
                                                            "id": f"call_{call_id}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": "write",
                                                                "arguments": json.dumps({"content": tool_content})
                                                            }
                                                        }
                                                        openai_tool_calls.append(openai_tool_call)
                                                        call_id += 1
                                                        logging.info(f"Converted 'content/assistant:' format to OpenAI tool_calls")
                                                        
                                                        # Extract assistant text
                                                        try:
                                                            assistant_content = json.loads(assistant_json_str)
                                                            if isinstance(assistant_content, list) and len(assistant_content) > 0:
                                                                for item in assistant_content:
                                                                    if isinstance(item, dict) and item.get('type') == 'text':
                                                                        response_text = item.get('text', '')
                                                                        break
                                                                else:
                                                                    response_text = ""
                                                            else:
                                                                response_text = ""
                                                        except json.JSONDecodeError:
                                                            response_text = ""
                                                    except Exception as e:
                                                        logging.debug(f"Failed to parse 'content/assistant:' format: {e}")
                                                
                                                # Fall back to original JSON parsing if no special format found
                                                elif not openai_tool_calls:
                                                    try:
                                                        # Try to parse as JSON
                                                        parsed_json = json.loads(response_text.strip())
                                                        if isinstance(parsed_json, dict):
                                                            # Check if it looks like a tool call
                                                            if 'action' in parsed_json or 'function' in parsed_json or 'name' in parsed_json:
                                                                # This appears to be a tool call in JSON format
                                                                # Convert to OpenAI tool_calls format
                                                                if 'action' in parsed_json:
                                                                    # Google-style tool call
                                                                    openai_tool_call = {
                                                                        "id": f"call_{call_id}",
                                                                        "type": "function",
                                                                        "function": {
                                                                            "name": parsed_json.get('action', 'unknown'),
                                                                            "arguments": json.dumps({k: v for k, v in parsed_json.items() if k != 'action'})
                                                                        }
                                                                    }
                                                                    openai_tool_calls.append(openai_tool_call)
                                                                    call_id += 1
                                                                    logging.info(f"Detected tool call in text content: {parsed_json}")
                                                                    # Clear response_text since we're using tool_calls instead
                                                                    response_text = ""
                                                                elif 'function' in parsed_json or 'name' in parsed_json:
                                                                    # OpenAI-style tool call
                                                                    openai_tool_call = {
                                                                        "id": f"call_{call_id}",
                                                                        "type": "function",
                                                                        "function": {
                                                                            "name": parsed_json.get('name', parsed_json.get('function', 'unknown')),
                                                                            "arguments": json.dumps(parsed_json.get('arguments', parsed_json.get('parameters', {})))
                                                                        }
                                                                    }
                                                                    openai_tool_calls.append(openai_tool_call)
                                                                    call_id += 1
                                                                    logging.info(f"Detected tool call in text content: {parsed_json}")
                                                                    # Clear response_text since we're using tool_calls instead
                                                                    response_text = ""
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Response text is not valid JSON: {e}")
                                            
                                            # Set tool_calls if we have any
                                            if openai_tool_calls:
                                                tool_calls = openai_tool_calls
                                                logging.info(f"Total tool calls: {len(tool_calls)}")
                                                for tc in tool_calls:
                                                    logging.info(f"  - {tc}")
                                            else:
                                                logging.info(f"No tool calls found")
                                        else:
                                            logging.error(f"Parts is empty")
                                    else:
                                        logging.error(f"Content does NOT have 'parts' attribute")
                                else:
                                    logging.error(f"Content is empty")
                            else:
                                logging.error(f"Candidate does NOT have 'content' attribute")
                        else:
                            logging.error(f"Candidates is empty")
                    else:
                        logging.error(f"Response does NOT have 'candidates' attribute")
                    
                    logging.info(f"Final response_text length: {len(response_text)}")
                    logging.info(f"Final response_text (first 200 chars): {response_text[:200] if response_text else 'None'}")
                    logging.info(f"Final tool_calls: {tool_calls}")
                    logging.info(f"Final finish_reason: {finish_reason}")
                except Exception as e:
                    logging.error(f"GoogleProviderHandler: Exception during response parsing: {e}", exc_info=True)
                    response_text = ""
                
                logging.info(f"=== GOOGLE RESPONSE PARSING END ===")

                # Extract usage metadata from the response
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                
                try:
                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                        usage_metadata = response.usage_metadata
                        prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0)
                        completion_tokens = getattr(usage_metadata, 'candidates_token_count', 0)
                        total_tokens = getattr(usage_metadata, 'total_token_count', 0)
                        logging.info(f"GoogleProviderHandler: Usage metadata - prompt: {prompt_tokens}, completion: {completion_tokens}, total: {total_tokens}")
                except Exception as e:
                    logging.warning(f"GoogleProviderHandler: Could not extract usage metadata: {e}")

                # Build the OpenAI-style response
                openai_response = {
                    "id": f"google-{model}-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": f"{self.provider_id}/{model}",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_text if response_text else None
                        },
                        "finish_reason": finish_reason
                    }],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens
                    }
                }
                
                # Add tool_calls to the message if present
                if tool_calls:
                    openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
                    # If there are tool calls, content should be None (OpenAI convention)
                    openai_response["choices"][0]["message"]["content"] = None
                    logging.info(f"Added tool_calls to response message")
                
                # Log the final response structure
                logging.info(f"=== FINAL OPENAI RESPONSE STRUCTURE ===")
                logging.info(f"Response type: {type(openai_response)}")
                logging.info(f"Response keys: {openai_response.keys()}")
                logging.info(f"Response id: {openai_response['id']}")
                logging.info(f"Response object: {openai_response['object']}")
                logging.info(f"Response created: {openai_response['created']}")
                logging.info(f"Response model: {openai_response['model']}")
                logging.info(f"Response choices count: {len(openai_response['choices'])}")
                logging.info(f"Response choices[0] index: {openai_response['choices'][0]['index']}")
                logging.info(f"Response choices[0] message role: {openai_response['choices'][0]['message']['role']}")
                logging.info(f"Response choices[0] message content length: {len(openai_response['choices'][0]['message']['content'])}")
                logging.info(f"Response choices[0] message content (first 200 chars): {openai_response['choices'][0]['message']['content'][:200]}")
                logging.info(f"Response choices[0] finish_reason: {openai_response['choices'][0]['finish_reason']}")
                logging.info(f"Response usage: {openai_response['usage']}")
                logging.info(f"=== END FINAL OPENAI RESPONSE STRUCTURE ===")
                
                # Return the response dict directly without Pydantic validation
                # Pydantic validation might be causing serialization issues
                logging.info(f"GoogleProviderHandler: Returning response dict (no validation)")
                logging.info(f"Response dict keys: {openai_response.keys()}")
                
                # Dump final response if AISBF_DEBUG is enabled
                if AISBF_DEBUG:
                    logging.info(f"=== FINAL GOOGLE RESPONSE DICT ===")
                    logging.info(f"Final response: {openai_response}")
                    logging.info(f"=== END FINAL GOOGLE RESPONSE DICT ===")
                
                return openai_response
        except Exception as e:
            import logging
            logging.error(f"GoogleProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        try:
            import logging
            logging.info("GoogleProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()

            # List models using the google-genai client
            models = self.client.models.list()
            logging.info(f"GoogleProviderHandler: Models received: {models}")

            # Convert to our Model format
            result = []
            for model in models:
                # Extract context size if available - check multiple field names
                context_size = None
                if hasattr(model, 'context_window') and model.context_window:
                    context_size = model.context_window
                elif hasattr(model, 'context_length') and model.context_length:
                    context_size = model.context_length
                elif hasattr(model, 'max_context_length') and model.max_context_length:
                    context_size = model.max_context_length
                
                result.append(Model(
                    id=model.name,
                    name=model.display_name or model.name,
                    provider_id=self.provider_id,
                    context_size=context_size,
                    context_length=context_size
                ))

            return result
        except Exception as e:
            import logging
            logging.error(f"GoogleProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e

    def _generate_cache_key(self, messages: List[Dict], model: str) -> str:
        """
        Generate a cache key based on the early messages (system + early conversation).
        We only cache the system message and early conversation turns, not the most recent ones.
        
        Args:
            messages: List of message dicts
            model: Model name
            
        Returns:
            Cache key string
        """
        import hashlib
        import json
        
        # Extract system message and first part of conversation
        # We cache system + first few messages (excluding last 2 messages for dynamic content)
        cacheable_messages = []
        
        for i, msg in enumerate(messages):
            # Include system messages and early conversation (first half, up to last 2)
            if msg.get('role') == 'system' or i < max(0, len(messages) - 3):
                cacheable_messages.append({
                    'role': msg.get('role'),
                    'content': msg.get('content', '')[:1000]  # Truncate long content for key
                })
        
        # Create hash from messages + model
        cache_data = json.dumps({
            'model': model,
            'messages': cacheable_messages
        }, sort_keys=True)
        
        return hashlib.sha256(cache_data.encode()).hexdigest()[:32]
    
    def _create_cached_content(self, messages: List[Dict], model: str, cache_ttl: int) -> Optional[str]:
        """
        Create a cached content object in Google API.
        
        Args:
            messages: Messages to cache
            model: Model name
            cache_ttl: Cache TTL in seconds
            
        Returns:
            Cached content name or None on failure
        """
        import logging
        
        try:
            # Extract the cacheable content (system + early messages)
            cacheable_parts = []
            
            for i, msg in enumerate(messages):
                # Include system messages and early conversation (first half, up to last 2)
                if msg.get('role') == 'system' or i < max(0, len(messages) - 3):
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    cacheable_parts.append(f"{role}: {content}")
            
            if not cacheable_parts:
                logging.info("GoogleProviderHandler: No cacheable content to create")
                return None
            
            cached_content_text = "\n\n".join(cacheable_parts)
            
            # Create cache name
            cache_name = f"cached_content_{int(time.time())}"
            
            logging.info(f"GoogleProviderHandler: Creating cached content: {cache_name}")
            logging.info(f"GoogleProviderHandler: Cached content length: {len(cached_content_text)} chars")
            
            # Use the google-genai client to create cached content
            # The cached content is created via the content caching API
            from google.genai import types as genai_types
            
            # Create cached content using the client
            # Note: The actual API call depends on the SDK version and model support
            # For models that support context caching, we create the cached content
            try:
                # Try to create cached content through the API
                # This may not be available in all SDK versions
                cached_content = self.client.cached_contents.create(
                    model=model,
                    display_name=cache_name,
                    system_instruction=cached_content_text,
                    ttl=f"{cache_ttl}s"
                )
                
                logging.info(f"GoogleProviderHandler: Cached content created: {cached_content.name}")
                return cached_content.name
                
            except AttributeError as e:
                # cached_contents may not be available in this SDK version
                logging.info(f"GoogleProviderHandler: Cached content API not available in this SDK: {e}")
                # Fall back to just storing the content locally as a reference
                # The next request will still process normally but we track this attempt
                return None
            except Exception as e:
                logging.warning(f"GoogleProviderHandler: Failed to create cached content: {e}")
                return None
                
        except Exception as e:
            logging.error(f"GoogleProviderHandler: Error creating cached content: {e}")
            return None
    
    def _use_cached_content_in_request(self, cached_content_name: str, model: str, 
                                         last_messages: List[Dict], max_tokens: Optional[int],
                                         temperature: float, tools: Optional[List[Dict]]) -> Union[Dict, object]:
        """
        Make a request using cached content.
        
        Args:
            cached_content_name: Name of the cached content
            model: Model name
            last_messages: The non-cached messages (last few turns)
            max_tokens: Max output tokens
            temperature: Temperature setting
            tools: Tool definitions
            
        Returns:
            Response from API
        """
        import logging
        from google.genai import types as genai_types
        
        logging.info(f"GoogleProviderHandler: Using cached content: {cached_content_name}")
        
        # Build content from only the non-cached (last) messages
        content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in last_messages])
        
        # Build config
        config = {"temperature": temperature}
        if max_tokens is not None:
            config["max_output_tokens"] = max_tokens
        if tools:
            # Convert tools to Google format (same as before)
            function_declarations = []
            for tool in tools:
                if tool.get("type") == "function":
                    function = tool.get("function", {})
                    function_declaration = genai_types.FunctionDeclaration(
                        name=function.get("name"),
                        description=function.get("description", ""),
                        parameters=function.get("parameters", {})
                    )
                    function_declarations.append(function_declaration)
            
            if function_declarations:
                google_tools = genai_types.Tool(function_declarations=function_declarations)
                config["tools"] = google_tools
        
        # Make request using cached content
        # Reference the cached content in the request
        response = self.client.models.generate_content(
            model=model,
            contents=content,
            config=config,
            cached_content=cached_content_name  # Use the cached content
        )
        
        return response

class OpenAIProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        self.client = OpenAI(base_url=config.providers[provider_id].endpoint, api_key=api_key)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"OpenAIProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"OpenAIProviderHandler: Messages: {messages}")
            else:
                logging.info(f"OpenAIProviderHandler: Messages count: {len(messages)}")
            if AISBF_DEBUG:
                logging.info(f"OpenAIProviderHandler: Tools: {tools}")
                logging.info(f"OpenAIProviderHandler: Tool choice: {tool_choice}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1024)
            prompt_cache_key = getattr(provider_config, 'prompt_cache_key', None)

            logging.info(f"OpenAIProviderHandler: Native caching enabled: {enable_native_caching}")
            if enable_native_caching:
                logging.info(f"OpenAIProviderHandler: Min cacheable tokens: {min_cacheable_tokens}, prompt_cache_key: {prompt_cache_key}")

            # Build request parameters
            request_params = {
                "model": model,
                "messages": [],
                "temperature": temperature,
                "stream": stream
            }
            
            # Only add max_tokens if it's not None
            if max_tokens is not None:
                request_params["max_tokens"] = max_tokens
            
            # Add prompt_cache_key if provided (for OpenAI's load balancer routing optimization)
            if enable_native_caching and prompt_cache_key:
                request_params["prompt_cache_key"] = prompt_cache_key
                logging.info(f"OpenAIProviderHandler: Added prompt_cache_key to request")
            
            # Build messages with all fields (including tool_calls, tool_call_id, and cache_control)
            if enable_native_caching:
                # Count cumulative tokens for cache decision
                cumulative_tokens = 0
                for i, msg in enumerate(messages):
                    # Count tokens in this message
                    message_tokens = count_messages_tokens([msg], model)
                    cumulative_tokens += message_tokens

                    message = {"role": msg["role"]}
                    
                    # For tool role, tool_call_id is required
                    if msg["role"] == "tool":
                        if "tool_call_id" in msg and msg["tool_call_id"] is not None:
                            message["tool_call_id"] = msg["tool_call_id"]
                        else:
                            # Skip tool messages without tool_call_id
                            logger.warning(f"Skipping tool message without tool_call_id: {msg}")
                            continue
                    
                    if "content" in msg and msg["content"] is not None:
                        message["content"] = msg["content"]
                    if "tool_calls" in msg and msg["tool_calls"] is not None:
                        message["tool_calls"] = msg["tool_calls"]
                    if "name" in msg and msg["name"] is not None:
                        message["name"] = msg["name"]
                    
                    # Apply cache_control based on position and token count
                    # Cache system messages and long conversation prefixes
                    # This is compatible with Anthropic via OpenRouter, DeepSeek, and other OpenAI-compatible APIs
                    if (msg["role"] == "system" or
                        (i < len(messages) - 2 and cumulative_tokens >= min_cacheable_tokens)):
                        message["cache_control"] = {"type": "ephemeral"}
                        logging.info(f"OpenAIProviderHandler: Applied cache_control to message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")
                    else:
                        logging.info(f"OpenAIProviderHandler: Not caching message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")
                    
                    request_params["messages"].append(message)
            else:
                # Standard message formatting without caching
                for msg in messages:
                    message = {"role": msg["role"]}
                    
                    # For tool role, tool_call_id is required
                    if msg["role"] == "tool":
                        if "tool_call_id" in msg and msg["tool_call_id"] is not None:
                            message["tool_call_id"] = msg["tool_call_id"]
                        else:
                            # Skip tool messages without tool_call_id
                            logger.warning(f"Skipping tool message without tool_call_id: {msg}")
                            continue
                    
                    if "content" in msg and msg["content"] is not None:
                        message["content"] = msg["content"]
                    if "tool_calls" in msg and msg["tool_calls"] is not None:
                        message["tool_calls"] = msg["tool_calls"]
                    if "name" in msg and msg["name"] is not None:
                        message["name"] = msg["name"]
                    request_params["messages"].append(message)
            
            # Add tools and tool_choice if provided
            if tools is not None:
                request_params["tools"] = tools
            if tool_choice is not None:
                request_params["tool_choice"] = tool_choice

            response = self.client.chat.completions.create(**request_params)
            logging.info(f"OpenAIProviderHandler: Response received: {response}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW OPENAI RESPONSE ===")
                logging.info(f"Raw response type: {type(response)}")
                logging.info(f"Raw response: {response}")
                logging.info(f"=== END RAW OPENAI RESPONSE ===")
            
            # Return raw response without any parsing or modification
            # For streaming: return the Stream object as-is
            # For non-streaming: return the response object as-is
            logging.info(f"OpenAIProviderHandler: Returning raw response without parsing")
            return response
        except Exception as e:
            import logging
            logging.error(f"OpenAIProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        try:
            import logging
            logging.info("OpenAIProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()

            models = self.client.models.list()
            logging.info(f"OpenAIProviderHandler: Models received: {models}")

            result = []
            for model in models:
                # Extract context size if available - check multiple field names
                context_size = None
                if hasattr(model, 'context_window') and model.context_window:
                    context_size = model.context_window
                elif hasattr(model, 'context_length') and model.context_length:
                    context_size = model.context_length
                elif hasattr(model, 'max_context_length') and model.max_context_length:
                    context_size = model.max_context_length
                
                # Extract pricing if available (OpenRouter-style)
                pricing = None
                if hasattr(model, 'pricing') and model.pricing:
                    pricing = model.pricing
                elif hasattr(model, 'top_provider') and model.top_provider:
                    # Try to extract from top_provider
                    top_provider = model.top_provider
                    if hasattr(top_provider, 'dict'):
                        top_provider = top_provider.dict()
                    if isinstance(top_provider, dict):
                        # Check for pricing in top_provider
                        tp_pricing = top_provider.get('pricing')
                        if tp_pricing:
                            pricing = tp_pricing
                
                result.append(Model(
                    id=model.id,
                    name=model.id,
                    provider_id=self.provider_id,
                    context_size=context_size,
                    context_length=context_size,
                    pricing=pricing
                ))
            
            return result
        except Exception as e:
            import logging
            logging.error(f"OpenAIProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e

class AnthropicProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        self.client = Anthropic(api_key=api_key)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                            temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                            tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Dict:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"AnthropicProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"AnthropicProviderHandler: Messages: {messages}")
            else:
                logging.info(f"AnthropicProviderHandler: Messages count: {len(messages)}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1000)

            logging.info(f"AnthropicProviderHandler: Native caching enabled: {enable_native_caching}")
            if enable_native_caching:
                logging.info(f"AnthropicProviderHandler: Min cacheable tokens: {min_cacheable_tokens}")

            # Prepare messages with cache_control if enabled
            anthropic_messages = []
            if enable_native_caching:
                # Count cumulative tokens for cache decision
                cumulative_tokens = 0
                for i, msg in enumerate(messages):
                    # Count tokens in this message
                    message_tokens = count_messages_tokens([msg], model)
                    cumulative_tokens += message_tokens

                    # Convert to Anthropic message format
                    anthropic_msg = {"role": msg["role"], "content": msg["content"]}

                    # Apply cache_control based on position and token count
                    # Cache system messages and long conversation prefixes
                    if (msg["role"] == "system" or
                        (i < len(messages) - 2 and cumulative_tokens >= min_cacheable_tokens)):
                        anthropic_msg["cache_control"] = {"type": "ephemeral"}
                        logging.info(f"AnthropicProviderHandler: Applied cache_control to message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")
                    else:
                        logging.info(f"AnthropicProviderHandler: Not caching message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")

                    anthropic_messages.append(anthropic_msg)
            else:
                # Standard message formatting without caching
                anthropic_messages = [{"role": msg["role"], "content": msg["content"]} for msg in messages]

            response = self.client.messages.create(
                model=model,
                messages=anthropic_messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            logging.info(f"AnthropicProviderHandler: Response received: {response}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW ANTHROPIC RESPONSE ===")
                logging.info(f"Raw response type: {type(response)}")
                logging.info(f"Raw response: {response}")
                logging.info(f"Raw response dir: {dir(response)}")
                logging.info(f"=== END RAW ANTHROPIC RESPONSE ===")
            
            logging.info(f"=== ANTHROPIC RESPONSE PARSING START ===")
            logging.info(f"Response type: {type(response)}")
            logging.info(f"Response attributes: {dir(response)}")
            
            # Translate Anthropic response to OpenAI format
            # Anthropic returns content as an array of blocks
            content_text = ""
            tool_calls = None
            
            try:
                if hasattr(response, 'content') and response.content:
                    logging.info(f"Response has 'content' attribute")
                    logging.info(f"Content blocks: {response.content}")
                    logging.info(f"Content blocks count: {len(response.content)}")
                    
                    text_parts = []
                    openai_tool_calls = []
                    call_id = 0
                    
                    # Process all content blocks
                    for idx, block in enumerate(response.content):
                        logging.info(f"Processing block {idx}")
                        logging.info(f"Block type: {type(block)}")
                        logging.info(f"Block attributes: {dir(block)}")
                        
                        # Check for text blocks
                        if hasattr(block, 'text') and block.text:
                            logging.info(f"Block {idx} has 'text' attribute")
                            text_parts.append(block.text)
                            logging.info(f"Block {idx} text length: {len(block.text)}")
                        
                        # Check for tool_use blocks (Anthropic's function calling format)
                        if hasattr(block, 'type') and block.type == 'tool_use':
                            logging.info(f"Block {idx} is a tool_use block")
                            logging.info(f"Tool use block: {block}")
                            
                            try:
                                # Convert Anthropic tool_use to OpenAI tool_calls format
                                openai_tool_call = {
                                    "id": f"call_{call_id}",
                                    "type": "function",
                                    "function": {
                                        "name": block.name if hasattr(block, 'name') else "",
                                        "arguments": block.input if hasattr(block, 'input') else {}
                                    }
                                }
                                openai_tool_calls.append(openai_tool_call)
                                call_id += 1
                                logging.info(f"Converted tool_use to OpenAI format: {openai_tool_call}")
                            except Exception as e:
                                logging.error(f"Error converting tool_use: {e}", exc_info=True)
                    
                    # Combine all text parts
                    content_text = "\n".join(text_parts)
                    logging.info(f"Combined text length: {len(content_text)}")
                    logging.info(f"Combined text (first 200 chars): {content_text[:200] if content_text else 'None'}")
                    
                    # Set tool_calls if we have any
                    if openai_tool_calls:
                        tool_calls = openai_tool_calls
                        logging.info(f"Total tool calls: {len(tool_calls)}")
                        for tc in tool_calls:
                            logging.info(f"  - {tc}")
                    else:
                        logging.info(f"No tool calls found")
                else:
                    logging.warning(f"Response does NOT have 'content' attribute or content is empty")
                
                # Map Anthropic stop_reason to OpenAI finish_reason
                stop_reason_map = {
                    'end_turn': 'stop',
                    'max_tokens': 'length',
                    'stop_sequence': 'stop',
                    'tool_use': 'tool_calls'
                }
                stop_reason = getattr(response, 'stop_reason', 'stop')
                finish_reason = stop_reason_map.get(stop_reason, 'stop')
                logging.info(f"Anthropic stop_reason: {stop_reason}")
                logging.info(f"Mapped finish_reason: {finish_reason}")
                
            except Exception as e:
                logging.error(f"AnthropicProviderHandler: Exception during response parsing: {e}", exc_info=True)
                content_text = ""
            
            logging.info(f"=== ANTHROPIC RESPONSE PARSING END ===")
            
            # Build OpenAI-style response
            openai_response = {
                "id": f"anthropic-{model}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"{self.provider_id}/{model}",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_text if content_text else None
                    },
                    "finish_reason": finish_reason
                }],
                "usage": {
                    "prompt_tokens": getattr(response, "usage", {}).get("input_tokens", 0),
                    "completion_tokens": getattr(response, "usage", {}).get("output_tokens", 0),
                    "total_tokens": getattr(response, "usage", {}).get("input_tokens", 0) + getattr(response, "usage", {}).get("output_tokens", 0)
                }
            }
            
            # Add tool_calls to the message if present
            if tool_calls:
                openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
                # If there are tool calls, content should be None (OpenAI convention)
                openai_response["choices"][0]["message"]["content"] = None
                logging.info(f"Added tool_calls to response message")
            
            logging.info(f"=== FINAL ANTHROPIC RESPONSE STRUCTURE ===")
            logging.info(f"Response id: {openai_response['id']}")
            logging.info(f"Response model: {openai_response['model']}")
            logging.info(f"Response choices[0] message content: {openai_response['choices'][0]['message']['content']}")
            logging.info(f"Response choices[0] message tool_calls: {openai_response['choices'][0]['message'].get('tool_calls')}")
            logging.info(f"Response choices[0] finish_reason: {openai_response['choices'][0]['finish_reason']}")
            logging.info(f"Response usage: {openai_response['usage']}")
            logging.info(f"=== END FINAL ANTHROPIC RESPONSE STRUCTURE ===")
            
            # Return the response dict directly without Pydantic validation
            # Pydantic validation might be causing serialization issues
            logging.info(f"AnthropicProviderHandler: Returning response dict (no validation)")
            logging.info(f"Response dict keys: {openai_response.keys()}")
            
            # Dump final response dict if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== FINAL ANTHROPIC RESPONSE DICT ===")
                logging.info(f"Final response: {openai_response}")
                logging.info(f"=== END FINAL ANTHROPIC RESPONSE DICT ===")
            
            return openai_response
        except Exception as e:
            import logging
            logging.error(f"AnthropicProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        """
        Return list of available Anthropic models.
        
        Note: Anthropic's API doesn't provide a public models endpoint,
        so we return a curated static list of available models.
        """
        try:
            import logging
            logging.info("=" * 80)
            logging.info("AnthropicProviderHandler: Starting model list retrieval")
            logging.info("=" * 80)

            # Apply rate limiting
            await self.apply_rate_limit()

            # Try to fetch models from API (in case Anthropic adds this endpoint)
            try:
                logging.info("AnthropicProviderHandler: Attempting to fetch models from API...")
                logging.info("AnthropicProviderHandler: Note: Anthropic doesn't currently provide a public models endpoint")
                logging.info("AnthropicProviderHandler: Checking if endpoint is now available...")
                
                response = self.client.models.list()
                if response:
                    logging.info(f"AnthropicProviderHandler: ✓ API call successful!")
                    logging.info(f"AnthropicProviderHandler: Retrieved models from API")
                    
                    models = [Model(id=model.id, name=model.id, provider_id=self.provider_id) for model in response]
                    
                    for model in models:
                        logging.info(f"AnthropicProviderHandler:   - {model.id}")
                    
                    logging.info("=" * 80)
                    logging.info(f"AnthropicProviderHandler: ✓ SUCCESS - Returning {len(models)} models from API")
                    logging.info(f"AnthropicProviderHandler: Source: Dynamic API retrieval")
                    logging.info("=" * 80)
                    return models
            except AttributeError as attr_error:
                logging.info(f"AnthropicProviderHandler: ✗ API endpoint not available")
                logging.info(f"AnthropicProviderHandler: Error: {type(attr_error).__name__} - {str(attr_error)}")
                logging.info("AnthropicProviderHandler: Reason: Anthropic SDK doesn't expose models.list() method")
                logging.info("AnthropicProviderHandler: Action: Falling back to static list")
            except Exception as api_error:
                logging.warning(f"AnthropicProviderHandler: ✗ Exception during API call")
                logging.warning(f"AnthropicProviderHandler: Error type: {type(api_error).__name__}")
                logging.warning(f"AnthropicProviderHandler: Error message: {str(api_error)}")
                logging.warning("AnthropicProviderHandler: Action: Falling back to static list")
                if AISBF_DEBUG:
                    logging.warning(f"AnthropicProviderHandler: Full traceback:", exc_info=True)
            
            # Return static list (Anthropic doesn't have a public models endpoint as of 2025)
            logging.info("-" * 80)
            logging.info("AnthropicProviderHandler: Using static fallback model list")
            logging.info("AnthropicProviderHandler: Note: This is the expected behavior for Anthropic provider")
            
            static_models = [
                Model(id="claude-3-7-sonnet-20250219", name="Claude 3.7 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-opus-20240229", name="Claude 3 Opus", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-haiku-20240307", name="Claude 3 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-sonnet-20240229", name="Claude 3 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
            ]
            
            for model in static_models:
                logging.info(f"AnthropicProviderHandler:   - {model.id} ({model.name})")
            
            logging.info("=" * 80)
            logging.info(f"AnthropicProviderHandler: ✓ Returning {len(static_models)} models from static list")
            logging.info(f"AnthropicProviderHandler: Source: Static fallback configuration")
            logging.info("=" * 80)
            
            return static_models
        except Exception as e:
            import logging
            logging.error("=" * 80)
            logging.error(f"AnthropicProviderHandler: ✗ FATAL ERROR getting models: {str(e)}")
            logging.error("=" * 80)
            logging.error(f"AnthropicProviderHandler: Error details:", exc_info=True)
            raise e

class ClaudeProviderHandler(BaseProviderHandler):
    """
    Handler for Claude Code OAuth2 integration.
    
    This handler uses OAuth2 authentication to access Claude models through
    the official Anthropic SDK. OAuth2 access tokens are passed as api_key
    parameter, matching the kilocode implementation approach.
    """
    
    # NOTE: OAuth2 API uses its own model naming scheme that differs from standard Anthropic API
    # OAuth2 models: claude-sonnet-4-5-20250929, claude-haiku-4-5-20251001, etc.
    # Standard API models: claude-3-5-sonnet-20241022, claude-3-5-haiku-20241022, etc.
    # We use model names exactly as returned by get_models() - NO normalization/mapping
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        super().__init__(provider_id, api_key)
        self.provider_config = config.get_provider(provider_id)
        
        # Get credentials file path from config
        claude_config = getattr(self.provider_config, 'claude_config', None)
        credentials_file = None
        if claude_config and isinstance(claude_config, dict):
            credentials_file = claude_config.get('credentials_file')
        
        # Initialize ClaudeAuth with credentials file (handles OAuth2 flow)
        from .claude_auth import ClaudeAuth
        self.auth = ClaudeAuth(credentials_file=credentials_file)
        
        # HTTP client for direct API requests (kilocode method)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
    
    def _get_auth_headers(self, stream: bool = False):
        """
        Get HTTP headers with OAuth2 Bearer token.
        Matches CLIProxyAPI header structure for compatibility.
        """
        import logging
        
        # Get valid OAuth2 access token
        access_token = self.auth.get_valid_token()
        
        # Build headers matching CLIProxyAPI/Claude Code implementation
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Anthropic-Version': '2023-06-01',
            'Anthropic-Beta': 'claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,context-management-2025-06-27,prompt-caching-scope-2026-01-05',
            'Anthropic-Dangerous-Direct-Browser-Access': 'true',
            'X-App': 'cli',
            'X-Stainless-Retry-Count': '0',
            'X-Stainless-Runtime': 'node',
            'X-Stainless-Lang': 'js',
            'X-Stainless-Timeout': '600',
            'Connection': 'keep-alive',
        }
        
        # Set Accept and Accept-Encoding based on streaming mode
        if stream:
            headers['Accept'] = 'text/event-stream'
            headers['Accept-Encoding'] = 'identity'
        else:
            headers['Accept'] = 'application/json'
            headers['Accept-Encoding'] = 'gzip, deflate, br, zstd'
        
        logging.info("ClaudeProviderHandler: Created auth headers with OAuth2 Bearer token")
        return headers
    
    def _convert_tool_choice_to_anthropic(self, tool_choice: Optional[Union[str, Dict]]) -> Optional[Dict]:
        """
        Convert OpenAI tool_choice format to Anthropic format.
        
        OpenAI formats:
        - "auto" -> {"type": "auto"}
        - "none" -> None (don't send tool_choice)
        - "required" -> {"type": "any"}
        - {"type": "function", "function": {"name": "tool_name"}} -> {"type": "tool", "name": "tool_name"}
        
        Args:
            tool_choice: OpenAI format tool_choice
            
        Returns:
            Anthropic format tool_choice or None
        """
        import logging
        
        if not tool_choice:
            return None
        
        # Handle string formats
        if isinstance(tool_choice, str):
            if tool_choice == "auto":
                return {"type": "auto"}
            elif tool_choice == "none":
                # Anthropic doesn't have "none" - return None to skip tool_choice
                return None
            elif tool_choice == "required":
                return {"type": "any"}
            else:
                logging.warning(f"Unknown tool_choice string: {tool_choice}, using auto")
                return {"type": "auto"}
        
        # Handle dict format (specific tool)
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                function = tool_choice.get("function", {})
                tool_name = function.get("name")
                if tool_name:
                    return {"type": "tool", "name": tool_name}
                else:
                    logging.warning(f"tool_choice dict missing function name: {tool_choice}")
                    return {"type": "auto"}
            else:
                # Already in Anthropic format or unknown format
                logging.warning(f"Unknown tool_choice dict format: {tool_choice}, passing through")
                return tool_choice
        
        logging.warning(f"Unknown tool_choice type: {type(tool_choice)}, using auto")
        return {"type": "auto"}
    
    def _convert_tools_to_anthropic(self, tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        """
        Convert OpenAI tools format to Anthropic format.
        
        OpenAI format:
        [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]
        
        Anthropic format:
        [{"name": "...", "description": "...", "input_schema": {...}}]
        
        Also normalizes JSON Schema types that Anthropic doesn't support:
        - ["string", "null"] -> "string" (with nullable handling)
        - Removes additionalProperties if false (Anthropic doesn't need it)
        
        Args:
            tools: OpenAI format tools
            
        Returns:
            Anthropic format tools or None
        """
        import logging
        
        if not tools:
            return None
        
        def normalize_schema(schema: Dict) -> Dict:
            """Recursively normalize JSON Schema for Anthropic compatibility."""
            if not isinstance(schema, dict):
                return schema
            
            result = {}
            for key, value in schema.items():
                if key == "type" and isinstance(value, list):
                    # Convert ["string", "null"] to just "string"
                    # Anthropic handles optional fields via 'required' array
                    non_null_types = [t for t in value if t != "null"]
                    if len(non_null_types) == 1:
                        result[key] = non_null_types[0]
                    elif len(non_null_types) > 1:
                        # Multiple non-null types - keep as-is (rare case)
                        result[key] = non_null_types
                    else:
                        # Only null type - default to string
                        result[key] = "string"
                elif key == "properties" and isinstance(value, dict):
                    # Recursively normalize nested properties
                    result[key] = {k: normalize_schema(v) for k, v in value.items()}
                elif key == "items" and isinstance(value, dict):
                    # Recursively normalize array items
                    result[key] = normalize_schema(value)
                elif key == "additionalProperties" and value is False:
                    # Skip additionalProperties: false (Anthropic doesn't need it)
                    continue
                elif key == "required" and isinstance(value, list):
                    # Clean up required array - only keep fields that exist in properties
                    # and don't have nullable types
                    properties = schema.get("properties", {})
                    cleaned_required = []
                    for field in value:
                        if field in properties:
                            field_schema = properties[field]
                            if isinstance(field_schema, dict):
                                field_type = field_schema.get("type")
                                # Skip fields with nullable types (they're optional)
                                if isinstance(field_type, list) and "null" in field_type:
                                    continue
                            cleaned_required.append(field)
                    if cleaned_required:
                        result[key] = cleaned_required
                    # If empty, don't add required key (all fields are optional)
                else:
                    result[key] = value
            
            return result
        
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                function = tool.get("function", {})
                parameters = function.get("parameters", {})
                
                # Normalize the input schema for Anthropic compatibility
                normalized_schema = normalize_schema(parameters)
                
                anthropic_tool = {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "input_schema": normalized_schema
                }
                anthropic_tools.append(anthropic_tool)
                logging.info(f"Converted tool to Anthropic format: {anthropic_tool['name']}")
            else:
                # Unknown tool type, log warning
                logging.warning(f"Unknown tool type: {tool.get('type')}, skipping")
        
        return anthropic_tools if anthropic_tools else None
    
    def _convert_messages_to_anthropic(self, messages: List[Dict]) -> tuple[Optional[str], List[Dict]]:
        """
        Convert OpenAI messages format to Anthropic format.
        
        Key differences:
        1. System messages are extracted to a separate 'system' parameter
        2. Tool role messages must be converted to user messages with tool_result content blocks
        3. Assistant messages with tool_calls must have tool_use content blocks
        4. Messages must alternate between user and assistant roles
        
        Args:
            messages: OpenAI format messages
            
        Returns:
            Tuple of (system_message, anthropic_messages)
        """
        import logging
        import json
        
        system_message = None
        anthropic_messages = []
        
        for msg in messages:
            role = msg.get('role')
            content = msg.get('content')
            
            if role == 'system':
                # Extract system message
                system_message = content
                logging.info(f"Extracted system message: {len(content) if content else 0} chars")
            
            elif role == 'tool':
                # Convert tool message to user message with tool_result content block
                tool_call_id = msg.get('tool_call_id', msg.get('name', 'unknown'))
                
                # Build tool_result content block
                tool_result_block = {
                    'type': 'tool_result',
                    'tool_use_id': tool_call_id,
                    'content': content or ""
                }
                
                # Check if last message is a user message - if so, append to it
                if anthropic_messages and anthropic_messages[-1]['role'] == 'user':
                    # Append to existing user message
                    last_content = anthropic_messages[-1]['content']
                    if isinstance(last_content, str):
                        # Convert string content to list
                        anthropic_messages[-1]['content'] = [
                            {'type': 'text', 'text': last_content},
                            tool_result_block
                        ]
                    elif isinstance(last_content, list):
                        # Append to existing list
                        anthropic_messages[-1]['content'].append(tool_result_block)
                    logging.info(f"Appended tool_result to existing user message")
                else:
                    # Create new user message with tool_result
                    anthropic_messages.append({
                        'role': 'user',
                        'content': [tool_result_block]
                    })
                    logging.info(f"Created new user message with tool_result")
            
            elif role == 'assistant':
                # Check if message has tool_calls
                tool_calls = msg.get('tool_calls')
                
                if tool_calls:
                    # Convert to Anthropic format with tool_use content blocks
                    content_blocks = []
                    
                    # Add text content if present
                    if content:
                        content_blocks.append({
                            'type': 'text',
                            'text': content
                        })
                    
                    # Add tool_use blocks
                    for tc in tool_calls:
                        tool_id = tc.get('id', f"toolu_{len(content_blocks)}")
                        function = tc.get('function', {})
                        tool_name = function.get('name', '')
                        
                        # Parse arguments (may be string or dict)
                        arguments = function.get('arguments', {})
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except json.JSONDecodeError:
                                logging.warning(f"Failed to parse tool arguments as JSON: {arguments}")
                                arguments = {}
                        
                        tool_use_block = {
                            'type': 'tool_use',
                            'id': tool_id,
                            'name': tool_name,
                            'input': arguments
                        }
                        content_blocks.append(tool_use_block)
                        logging.info(f"Converted tool_call to tool_use block: {tool_name}")
                    
                    anthropic_messages.append({
                        'role': 'assistant',
                        'content': content_blocks
                    })
                else:
                    # Regular assistant message
                    # Handle case where content might already be an array (from previous API responses)
                    if isinstance(content, list):
                        # Extract text from content blocks
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict):
                                if block.get('type') == 'text':
                                    text_parts.append(block.get('text', ''))
                                elif 'text' in block:
                                    text_parts.append(block['text'])
                            elif isinstance(block, str):
                                text_parts.append(block)
                        content_str = '\n'.join(text_parts) if text_parts else ""
                        logging.info(f"Normalized assistant message content from array to string ({len(text_parts)} blocks)")
                    else:
                        content_str = content or ""
                    
                    anthropic_messages.append({
                        'role': 'assistant',
                        'content': content_str
                    })
            
            elif role == 'user':
                # Regular user message
                anthropic_messages.append({
                    'role': 'user',
                    'content': content or ""
                })
            
            else:
                logging.warning(f"Unknown message role: {role}, treating as user")
                anthropic_messages.append({
                    'role': 'user',
                    'content': content or ""
                })
        
        logging.info(f"Converted {len(messages)} OpenAI messages to {len(anthropic_messages)} Anthropic messages")
        return system_message, anthropic_messages
    
    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            import json
            logging.info(f"ClaudeProviderHandler: Handling request for model {model}")
            
            if AISBF_DEBUG:
                logging.info(f"ClaudeProviderHandler: Messages: {messages}")
            else:
                logging.info(f"ClaudeProviderHandler: Messages count: {len(messages)}")

            # Apply rate limiting
            await self.apply_rate_limit()
            
            # Convert messages to Anthropic format (handles tool messages properly)
            system_message, anthropic_messages = self._convert_messages_to_anthropic(messages)
            
            # Build request payload for direct HTTP request (kilocode method)
            # IMPORTANT: OAuth2 API uses its own model naming scheme (e.g., claude-sonnet-4-5-20250929)
            # which is DIFFERENT from standard Anthropic API (e.g., claude-3-5-sonnet-20241022)
            # DO NOT normalize - use the model name exactly as provided by get_models()
            payload = {
                'model': model,
                'messages': anthropic_messages,
                'max_tokens': max_tokens or 4096,
            }
            
            # Only add temperature if not None
            if temperature is not None:
                payload['temperature'] = temperature
            
            if system_message:
                payload['system'] = system_message
            
            # Convert OpenAI tools to Anthropic format
            if tools:
                anthropic_tools = self._convert_tools_to_anthropic(tools)
                if anthropic_tools:
                    payload['tools'] = anthropic_tools
            
            # Convert OpenAI tool_choice format to Anthropic format
            if tool_choice and tools:  # Only add tool_choice if we have tools
                anthropic_tool_choice = self._convert_tool_choice_to_anthropic(tool_choice)
                if anthropic_tool_choice:
                    payload['tool_choice'] = anthropic_tool_choice
            
            # Add stream parameter
            payload['stream'] = stream
            
            # TEMPORARY: Always log payload for debugging 400 errors
            logging.info(f"ClaudeProviderHandler: Request payload: {json.dumps(payload, indent=2)}")
            
            # Use api.anthropic.com endpoint (correct endpoint for OAuth2 tokens)
            api_url = 'https://api.anthropic.com/v1/messages'
            logging.info(f"ClaudeProviderHandler: Making request to {api_url}")
            
            # Make request using direct HTTP (kilocode method)
            if stream:
                logging.info(f"ClaudeProviderHandler: Using streaming mode with direct HTTP")
                # Get auth headers with Bearer token (streaming mode)
                headers = self._get_auth_headers(stream=True)
                
                # Log the full request for debugging
                if AISBF_DEBUG:
                    logging.info(f"=== STREAMING REQUEST DEBUG ===")
                    logging.info(f"URL: {api_url}")
                    logging.info(f"Headers: {json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}, indent=2)}")
                    logging.info(f"Payload: {json.dumps(payload, indent=2)}")
                    logging.info(f"=== END STREAMING REQUEST DEBUG ===")
                
                return self._handle_streaming_request(api_url, payload, headers, model)
            
            # Get auth headers with Bearer token (non-streaming mode)
            headers = self._get_auth_headers(stream=False)
            
            # Log the full request for debugging
            if AISBF_DEBUG:
                logging.info(f"=== NON-STREAMING REQUEST DEBUG ===")
                logging.info(f"URL: {api_url}")
                logging.info(f"Headers (auth redacted): {json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}, indent=2)}")
                logging.info(f"Payload: {json.dumps(payload, indent=2)}")
                logging.info(f"=== END NON-STREAMING REQUEST DEBUG ===")
            
            # Non-streaming request
            response = await self.client.post(api_url, headers=headers, json=payload)
            
            logging.info(f"ClaudeProviderHandler: Response status: {response.status_code}")
            
            # Check for 429 rate limit error before raising
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                self.handle_429_error(response_data, dict(response.headers))
                response.raise_for_status()
            
            # Log error details for non-2xx responses
            if response.status_code >= 400:
                try:
                    error_body = response.json()
                    error_message = error_body.get('error', {}).get('message', 'Unknown error')
                    error_type = error_body.get('error', {}).get('type', 'unknown')
                    logging.error(f"ClaudeProviderHandler: API error response: {json.dumps(error_body, indent=2)}")
                    logging.error(f"ClaudeProviderHandler: Error type: {error_type}")
                    logging.error(f"ClaudeProviderHandler: Error message: {error_message}")
                except Exception:
                    logging.error(f"ClaudeProviderHandler: API error response (text): {response.text}")
            
            response.raise_for_status()
            
            claude_response = response.json()
            
            if AISBF_DEBUG:
                logging.info(f"ClaudeProviderHandler: API response: {json.dumps(claude_response, indent=2)}")
            
            logging.info(f"ClaudeProviderHandler: Response received successfully via direct HTTP")
            self.record_success()
            
            # Convert Claude API response to OpenAI format
            openai_response = self._convert_to_openai_format(claude_response, model)
            
            return openai_response
            
        except Exception as e:
            import logging
            logging.error(f"ClaudeProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e
    
    async def _handle_streaming_request(self, api_url: str, payload: Dict, headers: Dict, model: str):
        """Handle streaming request to Claude API using direct HTTP (kilocode method)."""
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info(f"ClaudeProviderHandler: Starting streaming request to {api_url}")
        
        # Log full request for debugging
        if AISBF_DEBUG:
            logger.info(f"=== STREAMING REQUEST DETAILS ===")
            logger.info(f"URL: {api_url}")
            logger.info(f"Headers (auth redacted): {json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}, indent=2)}")
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")
            logger.info(f"=== END STREAMING REQUEST DETAILS ===")
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as streaming_client:
            async with streaming_client.stream(
                "POST",
                api_url,
                headers=headers,
                json=payload
            ) as response:
                logger.info(f"ClaudeProviderHandler: Streaming response status: {response.status_code}")
                
                if response.status_code >= 400:
                    error_text = await response.aread()
                    logger.error(f"ClaudeProviderHandler: Streaming error response: {error_text}")
                    
                    # Try to parse error as JSON for better error message
                    try:
                        error_json = json.loads(error_text)
                        error_message = error_json.get('error', {}).get('message', 'Unknown error')
                        error_type = error_json.get('error', {}).get('type', 'unknown')
                        logger.error(f"ClaudeProviderHandler: Error type: {error_type}")
                        logger.error(f"ClaudeProviderHandler: Error message: {error_message}")
                        raise Exception(f"Claude API error ({response.status_code}): {error_message}")
                    except (json.JSONDecodeError, Exception) as e:
                        logger.error(f"ClaudeProviderHandler: Could not parse error response: {e}")
                        raise Exception(f"Claude API error: {response.status_code} - {error_text}")
                
                # Generate completion ID and timestamps
                completion_id = f"claude-{int(time.time())}"
                created_time = int(time.time())
                
                # Track state for streaming
                first_chunk = True
                accumulated_content = ""
                accumulated_tool_calls = []
                
                # Process the streaming response (SSE format)
                async for line in response.aiter_lines():
                    if not line or not line.startswith('data: '):
                        continue
                    
                    # Remove 'data: ' prefix
                    data_str = line[6:]
                    
                    if data_str == '[DONE]':
                        break
                    
                    try:
                        chunk_data = json.loads(data_str)
                        
                        # Handle different event types
                        event_type = chunk_data.get('type')
                        
                        if event_type == 'content_block_delta':
                            delta = chunk_data.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                text = delta.get('text', '')
                                accumulated_content += text
                                
                                # Build OpenAI chunk
                                openai_delta = {'content': text}
                                if first_chunk:
                                    openai_delta['role'] = 'assistant'
                                    first_chunk = False
                                
                                openai_chunk = {
                                    'id': completion_id,
                                    'object': 'chat.completion.chunk',
                                    'created': created_time,
                                    'model': f'{self.provider_id}/{model}',
                                    'choices': [{
                                        'index': 0,
                                        'delta': openai_delta,
                                        'finish_reason': None
                                    }]
                                }
                                
                                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                        
                        elif event_type == 'message_stop':
                            # Final chunk
                            finish_reason = 'stop'
                            
                            final_chunk = {
                                'id': completion_id,
                                'object': 'chat.completion.chunk',
                                'created': created_time,
                                'model': f'{self.provider_id}/{model}',
                                'choices': [{
                                    'index': 0,
                                    'delta': {},
                                    'finish_reason': finish_reason
                                }]
                            }
                            
                            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                            yield b"data: [DONE]\n\n"
                    
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse streaming chunk: {e}")
                        continue
    
    def _convert_to_openai_format(self, claude_response: Dict, model: str) -> Dict:
        """Convert Claude API response to OpenAI format."""
        import logging
        
        # Extract content
        content_text = ""
        tool_calls = []
        
        if 'content' in claude_response:
            for block in claude_response['content']:
                if block.get('type') == 'text':
                    content_text += block.get('text', '')
                elif block.get('type') == 'tool_use':
                    tool_calls.append({
                        'id': block.get('id', f"call_{len(tool_calls)}"),
                        'type': 'function',
                        'function': {
                            'name': block.get('name', ''),
                            'arguments': json.dumps(block.get('input', {}))
                        }
                    })
        
        # Map stop reason
        stop_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'tool_calls'
        }
        stop_reason = claude_response.get('stop_reason', 'end_turn')
        finish_reason = stop_reason_map.get(stop_reason, 'stop')
        
        # Build OpenAI-style response
        openai_response = {
            'id': f"claude-{model}-{int(time.time())}",
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{self.provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content_text if not tool_calls else None
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': claude_response.get('usage', {}).get('input_tokens', 0),
                'completion_tokens': claude_response.get('usage', {}).get('output_tokens', 0),
                'total_tokens': (
                    claude_response.get('usage', {}).get('input_tokens', 0) +
                    claude_response.get('usage', {}).get('output_tokens', 0)
                )
            }
        }
        
        # Add tool_calls if present
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        return openai_response
    
    def _convert_sdk_response_to_openai(self, response, model: str) -> Dict:
        """
        Convert Anthropic SDK response object to OpenAI format.
        The SDK returns a Message object, not a dict.
        """
        import logging
        import json
        
        # Build message content from SDK response
        message_content = ""
        tool_calls = []
        
        # SDK response has content as a list of ContentBlock objects
        for block in response.content:
            if hasattr(block, 'text'):
                message_content += block.text
            elif hasattr(block, 'type') and block.type == 'tool_use':
                tool_calls.append({
                    'id': block.id,
                    'type': 'function',
                    'function': {
                        'name': block.name,
                        'arguments': json.dumps(block.input)
                    }
                })
        
        # Map stop reason
        stop_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'tool_calls'
        }
        stop_reason = response.stop_reason or 'end_turn'
        finish_reason = stop_reason_map.get(stop_reason, 'stop')
        
        # Build OpenAI-compatible response
        openai_response = {
            'id': response.id,
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{self.provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': message_content if not tool_calls else None,
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': response.usage.input_tokens,
                'completion_tokens': response.usage.output_tokens,
                'total_tokens': response.usage.input_tokens + response.usage.output_tokens
            }
        }
        
        # Add tool_calls if present
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        return openai_response
    
    async def _handle_streaming_request_sdk(self, request_kwargs: Dict, model: str):
        """Handle streaming request using Anthropic SDK."""
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info(f"ClaudeProviderHandler: Starting SDK streaming request")
        
        # Generate completion ID and timestamps
        completion_id = f"claude-{int(time.time())}"
        created_time = int(time.time())
        
        # Track state for streaming
        first_chunk = True
        accumulated_content = ""
        
        # Create SDK client for streaming (managed within generator)
        sdk_client = self._get_sdk_client()
        
        try:
            # Use SDK's streaming API
            async with sdk_client.messages.stream(**request_kwargs) as stream:
                async for event in stream:
                    # Handle different event types from SDK
                    if hasattr(event, 'type'):
                        event_type = event.type
                        
                        if event_type == 'content_block_delta':
                            # Text delta event
                            if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                                text = event.delta.text
                                accumulated_content += text
                                
                                # Build OpenAI chunk
                                openai_delta = {'content': text}
                                if first_chunk:
                                    openai_delta['role'] = 'assistant'
                                    first_chunk = False
                                
                                openai_chunk = {
                                    'id': completion_id,
                                    'object': 'chat.completion.chunk',
                                    'created': created_time,
                                    'model': f'{self.provider_id}/{model}',
                                    'choices': [{
                                        'index': 0,
                                        'delta': openai_delta,
                                        'finish_reason': None
                                    }]
                                }
                                
                                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                        
                        elif event_type == 'message_stop':
                            # Final chunk
                            finish_reason = 'stop'
                            
                            final_chunk = {
                                'id': completion_id,
                                'object': 'chat.completion.chunk',
                                'created': created_time,
                                'model': f'{self.provider_id}/{model}',
                                'choices': [{
                                    'index': 0,
                                    'delta': {},
                                    'finish_reason': finish_reason
                                }]
                            }
                            
                            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                            yield b"data: [DONE]\n\n"
            
            logger.info(f"ClaudeProviderHandler: SDK streaming completed successfully")
            self.record_success()
            
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: SDK streaming error: {str(e)}")
            raise
        finally:
            # Close SDK client after streaming completes
            await sdk_client.close()
    
    def _get_models_cache_path(self) -> str:
        """Get the path to the models cache file."""
        import os
        cache_dir = os.path.expanduser("~/.aisbf")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"claude_models_cache_{self.provider_id}.json")
    
    def _save_models_cache(self, models: List[Model]) -> None:
        """Save models to cache file."""
        import logging
        import json
        
        try:
            cache_path = self._get_models_cache_path()
            cache_data = {
                'timestamp': time.time(),
                'models': []
            }
            
            for m in models:
                model_dict = {'id': m.id, 'name': m.name}
                # Save optional fields
                if m.context_size:
                    model_dict['context_size'] = m.context_size
                if m.context_length:
                    model_dict['context_length'] = m.context_length
                if m.description:
                    model_dict['description'] = m.description
                if m.pricing:
                    model_dict['pricing'] = m.pricing
                if m.top_provider:
                    model_dict['top_provider'] = m.top_provider
                if m.supported_parameters:
                    model_dict['supported_parameters'] = m.supported_parameters
                cache_data['models'].append(model_dict)
            
            with open(cache_path, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logging.info(f"ClaudeProviderHandler: ✓ Saved {len(models)} models to cache: {cache_path}")
        except Exception as e:
            logging.warning(f"ClaudeProviderHandler: Failed to save models cache: {e}")
    
    def _load_models_cache(self) -> Optional[List[Model]]:
        """Load models from cache file if available and not too old."""
        import logging
        import json
        import os
        
        try:
            cache_path = self._get_models_cache_path()
            
            if not os.path.exists(cache_path):
                logging.info(f"ClaudeProviderHandler: No cache file found at {cache_path}")
                return None
            
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
            
            cache_age = time.time() - cache_data.get('timestamp', 0)
            cache_age_hours = cache_age / 3600
            
            logging.info(f"ClaudeProviderHandler: Found cache file (age: {cache_age_hours:.1f} hours)")
            
            # Cache is valid for 24 hours
            if cache_age > 86400:
                logging.info(f"ClaudeProviderHandler: Cache is too old (>{cache_age_hours:.1f} hours), ignoring")
                return None
            
            models = []
            for m in cache_data.get('models', []):
                models.append(Model(
                    id=m['id'],
                    name=m['name'],
                    provider_id=self.provider_id,
                    context_size=m.get('context_size'),
                    context_length=m.get('context_length'),
                    description=m.get('description'),
                    pricing=m.get('pricing'),
                    top_provider=m.get('top_provider'),
                    supported_parameters=m.get('supported_parameters')
                ))
            
            if models:
                logging.info(f"ClaudeProviderHandler: ✓ Loaded {len(models)} models from cache")
                return models
            else:
                logging.info(f"ClaudeProviderHandler: Cache file is empty")
                return None
                
        except Exception as e:
            logging.warning(f"ClaudeProviderHandler: Failed to load models cache: {e}")
            return None

    async def get_models(self) -> List[Model]:
        """Return list of available Claude models by querying the API."""
        try:
            import logging
            import json
            logging.info("=" * 80)
            logging.info("ClaudeProviderHandler: Starting model list retrieval")
            logging.info("=" * 80)

            # Apply rate limiting
            await self.apply_rate_limit()

            # Try to fetch models from the primary API
            try:
                logging.info("ClaudeProviderHandler: [1/3] Attempting primary API endpoint...")
                
                # Use the same auth headers as handle_request for consistency
                headers = self._get_auth_headers(stream=False)
                
                # Log the API endpoint being called
                api_endpoint = 'https://api.anthropic.com/v1/models'
                logging.info(f"ClaudeProviderHandler: Calling API endpoint: {api_endpoint}")
                logging.info(f"ClaudeProviderHandler: Using OAuth2 authentication with full headers")
                
                # Query the models endpoint
                response = await self.client.get(api_endpoint, headers=headers)
                
                logging.info(f"ClaudeProviderHandler: API response status: {response.status_code}")
                
                if response.status_code == 200:
                    models_data = response.json()
                    logging.info(f"ClaudeProviderHandler: ✓ Primary API call successful!")
                    logging.info(f"ClaudeProviderHandler: Response data keys: {list(models_data.keys())}")
                    logging.info(f"ClaudeProviderHandler: Retrieved {len(models_data.get('data', []))} models from API")
                    
                    if AISBF_DEBUG:
                        logging.info(f"ClaudeProviderHandler: Full API response: {models_data}")
                    
                    # Convert API response to Model objects
                    models = []
                    for model_data in models_data.get('data', []):
                        model_id = model_data.get('id', '')
                        display_name = model_data.get('display_name') or model_data.get('name') or model_id
                        
                        # Extract context size from API response
                        # For Anthropic/Claude models, max_input_tokens is the correct field
                        context_size = (
                            model_data.get('max_input_tokens') or
                            model_data.get('context_window') or
                            model_data.get('context_length') or
                            model_data.get('max_tokens')
                        )
                        
                        # Extract description if available
                        description = model_data.get('description')
                        
                        models.append(Model(
                            id=model_id,
                            name=display_name,
                            provider_id=self.provider_id,
                            context_size=context_size,
                            context_length=context_size,
                            description=description
                        ))
                        logging.info(f"ClaudeProviderHandler:   - {model_id} ({display_name}, context: {context_size})")
                    
                    if models:
                        # Save to cache
                        self._save_models_cache(models)
                        
                        logging.info("=" * 80)
                        logging.info(f"ClaudeProviderHandler: ✓ SUCCESS - Returning {len(models)} models from primary API")
                        logging.info(f"ClaudeProviderHandler: Source: Dynamic API retrieval (Anthropic)")
                        logging.info("=" * 80)
                        return models
                    else:
                        logging.warning("ClaudeProviderHandler: ✗ Primary API returned empty model list")
                else:
                    logging.warning(f"ClaudeProviderHandler: ✗ Primary API call failed with status {response.status_code}")
                    try:
                        error_body = response.json()
                        logging.warning(f"ClaudeProviderHandler: Error response: {error_body}")
                    except:
                        logging.warning(f"ClaudeProviderHandler: Error response (text): {response.text[:200]}")
            
            except Exception as api_error:
                logging.warning(f"ClaudeProviderHandler: ✗ Exception during primary API call")
                logging.warning(f"ClaudeProviderHandler: Error type: {type(api_error).__name__}")
                logging.warning(f"ClaudeProviderHandler: Error message: {str(api_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"ClaudeProviderHandler: Full traceback:", exc_info=True)
            
            # Try fallback endpoint
            try:
                logging.info("-" * 80)
                logging.info("ClaudeProviderHandler: [2/3] Attempting fallback endpoint...")
                
                fallback_endpoint = 'http://lisa.nexlab.net:5000/claude/models'
                logging.info(f"ClaudeProviderHandler: Calling fallback endpoint: {fallback_endpoint}")
                
                # Create a new client with shorter timeout for fallback
                fallback_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
                
                try:
                    fallback_response = await fallback_client.get(fallback_endpoint)
                    logging.info(f"ClaudeProviderHandler: Fallback response status: {fallback_response.status_code}")
                    
                    if fallback_response.status_code == 200:
                        fallback_data = fallback_response.json()
                        logging.info(f"ClaudeProviderHandler: ✓ Fallback API call successful!")
                        
                        if AISBF_DEBUG:
                            logging.info(f"ClaudeProviderHandler: Fallback response: {fallback_data}")
                        
                        # Parse fallback response - expect array of models or {data: [...]}
                        models_list = fallback_data if isinstance(fallback_data, list) else fallback_data.get('data', fallback_data.get('models', []))
                        
                        models = []
                        for model_data in models_list:
                            if isinstance(model_data, str):
                                # Simple string model ID
                                models.append(Model(id=model_data, name=model_data, provider_id=self.provider_id))
                            elif isinstance(model_data, dict):
                                # Dict with id/name
                                model_id = model_data.get('id', model_data.get('model', ''))
                                display_name = model_data.get('name', model_data.get('display_name', model_id))
                                
                                # Extract context size - include max_input_tokens for Claude providers
                                context_size = (
                                    model_data.get('max_input_tokens') or
                                    model_data.get('context_window') or
                                    model_data.get('context_length') or
                                    model_data.get('context_size') or
                                    model_data.get('max_tokens')
                                )
                                
                                # Extract description if available
                                description = model_data.get('description')
                                
                                models.append(Model(
                                    id=model_id,
                                    name=display_name,
                                    provider_id=self.provider_id,
                                    context_size=context_size,
                                    context_length=context_size,
                                    description=description
                                ))
                        
                        if models:
                            for model in models:
                                logging.info(f"ClaudeProviderHandler:   - {model.id} ({model.name})")
                            
                            # Save to cache
                            self._save_models_cache(models)
                            
                            logging.info("=" * 80)
                            logging.info(f"ClaudeProviderHandler: ✓ SUCCESS - Returning {len(models)} models from fallback API")
                            logging.info(f"ClaudeProviderHandler: Source: Dynamic API retrieval (Fallback)")
                            logging.info("=" * 80)
                            return models
                        else:
                            logging.warning("ClaudeProviderHandler: ✗ Fallback API returned empty model list")
                    else:
                        logging.warning(f"ClaudeProviderHandler: ✗ Fallback API call failed with status {fallback_response.status_code}")
                        try:
                            error_body = fallback_response.json()
                            logging.warning(f"ClaudeProviderHandler: Fallback error response: {error_body}")
                        except:
                            logging.warning(f"ClaudeProviderHandler: Fallback error response (text): {fallback_response.text[:200]}")
                finally:
                    await fallback_client.aclose()
                    
            except Exception as fallback_error:
                logging.warning(f"ClaudeProviderHandler: ✗ Exception during fallback API call")
                logging.warning(f"ClaudeProviderHandler: Error type: {type(fallback_error).__name__}")
                logging.warning(f"ClaudeProviderHandler: Error message: {str(fallback_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"ClaudeProviderHandler: Full traceback:", exc_info=True)
            
            # Try to load from cache
            logging.info("-" * 80)
            logging.info("ClaudeProviderHandler: [3/3] Attempting to load from cache...")
            
            cached_models = self._load_models_cache()
            if cached_models:
                for model in cached_models:
                    logging.info(f"ClaudeProviderHandler:   - {model.id} ({model.name})")
                
                logging.info("=" * 80)
                logging.info(f"ClaudeProviderHandler: ✓ Returning {len(cached_models)} models from cache")
                logging.info(f"ClaudeProviderHandler: Source: Cached model list")
                logging.info("=" * 80)
                return cached_models
            
            # Final fallback to static list
            logging.info("-" * 80)
            logging.info("ClaudeProviderHandler: Using static fallback model list")
            static_models = [
                Model(id="claude-3-7-sonnet-20250219", name="Claude 3.7 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-opus-20240229", name="Claude 3 Opus", provider_id=self.provider_id, context_size=200000, context_length=200000),
            ]
            
            for model in static_models:
                logging.info(f"ClaudeProviderHandler:   - {model.id} ({model.name})")
            
            logging.info("=" * 80)
            logging.info(f"ClaudeProviderHandler: ✓ Returning {len(static_models)} models from static list")
            logging.info(f"ClaudeProviderHandler: Source: Static fallback configuration")
            logging.info("=" * 80)
            
            return static_models
        except Exception as e:
            import logging
            logging.error("=" * 80)
            logging.error(f"ClaudeProviderHandler: ✗ FATAL ERROR getting models: {str(e)}")
            logging.error("=" * 80)
            logging.error(f"ClaudeProviderHandler: Error details:", exc_info=True)
            raise e

class KiroProviderHandler(BaseProviderHandler):
    """
    Handler for direct Kiro API integration (Amazon Q Developer).
    
    This handler makes direct API calls to Kiro's API using credentials from
    Kiro IDE or kiro-cli, with FULL kiro-gateway feature parity including:
    - Tool calls/function calling
    - Images/multimodal content
    - Complex message merging and validation
    - Role normalization
    - Complete OpenAI <-> Kiro format conversion
    """
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        self.provider_config = config.get_provider(provider_id)
        self.region = "us-east-1"  # Default region
        
        # Import AuthType for checking auth type
        from .kiro_auth import AuthType
        self.AuthType = AuthType
        
        # Initialize KiroAuthManager with credentials from config
        self.auth_manager = None
        self._init_auth_manager()
        
        # HTTP client for making requests
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        
    def _init_auth_manager(self):
        """Initialize KiroAuthManager with credentials from config"""
        try:
            from .kiro_auth import KiroAuthManager
            
            # Get Kiro-specific configuration from provider config
            kiro_config = getattr(self.provider_config, 'kiro_config', None)
            
            if not kiro_config:
                import logging
                logging.warning(f"No kiro_config found in provider {self.provider_id}, using defaults")
                kiro_config = {}
            
            # Extract credentials from provider config
            refresh_token = kiro_config.get('refresh_token') if isinstance(kiro_config, dict) else None
            profile_arn = kiro_config.get('profile_arn') if isinstance(kiro_config, dict) else None
            region = kiro_config.get('region', 'us-east-1') if isinstance(kiro_config, dict) else 'us-east-1'
            creds_file = kiro_config.get('creds_file') if isinstance(kiro_config, dict) else None
            sqlite_db = kiro_config.get('sqlite_db') if isinstance(kiro_config, dict) else None
            client_id = kiro_config.get('client_id') if isinstance(kiro_config, dict) else None
            client_secret = kiro_config.get('client_secret') if isinstance(kiro_config, dict) else None
            
            self.region = region
            
            # Initialize auth manager
            self.auth_manager = KiroAuthManager(
                refresh_token=refresh_token,
                profile_arn=profile_arn,
                region=region,
                creds_file=creds_file,
                sqlite_db=sqlite_db,
                client_id=client_id,
                client_secret=client_secret
            )
            
            import logging
            logging.info(f"KiroProviderHandler: Auth manager initialized for region {region}")
            
        except Exception as e:
            import logging
            logging.error(f"Failed to initialize KiroAuthManager: {e}")
            self.auth_manager = None

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            import json
            import uuid
            logging.info(f"KiroProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Messages: {messages}")
                logging.info(f"KiroProviderHandler: Tools: {tools}")
            else:
                logging.info(f"KiroProviderHandler: Messages count: {len(messages)}")
                logging.info(f"KiroProviderHandler: Tools count: {len(tools) if tools else 0}")
            
            if not self.auth_manager:
                raise Exception("Kiro authentication not configured. Please set kiro_config in provider configuration.")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Get access token and profile ARN
            access_token = await self.auth_manager.get_access_token()
            profile_arn = self.auth_manager.profile_arn
            
            # Determine effective profileArn based on auth type
            # AWS SSO OIDC users don't need profileArn and it causes 403 if sent
            effective_profile_arn = ""
            if profile_arn and self.auth_manager._auth_type != self.AuthType.AWS_SSO_OIDC:
                effective_profile_arn = profile_arn
                logging.info(f"KiroProviderHandler: Using profileArn (Kiro Desktop Auth)")
            else:
                logging.info(f"KiroProviderHandler: Skipping profileArn (AWS SSO OIDC/Builder ID)")
            
            # Use the proper kiro-gateway conversion pipeline to build the payload.
            # This handles:
            # - Model name normalization (claude-sonnet-4-5 → claude-sonnet-4.5)
            # - System message extraction
            # - Tool conversion and validation
            # - Message merging and role normalization
            # - Alternating user/assistant role enforcement
            # - Image support
            # - Tool call/result conversion
            from .kiro_converters_openai import build_kiro_payload_from_dict
            
            conversation_id = str(uuid.uuid4())
            
            payload = build_kiro_payload_from_dict(
                model=model,
                messages=messages,
                tools=tools,
                conversation_id=conversation_id,
                profile_arn=effective_profile_arn
            )
            
            logging.info(f"KiroProviderHandler: Model '{model}' normalized for Kiro API")
            
            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Kiro payload: {json.dumps(payload, indent=2)}")
            
            # Make request to Kiro API with proper headers
            headers = self.auth_manager.get_auth_headers(access_token)
            
            kiro_api_url = f"https://q.{self.region}.amazonaws.com/generateAssistantResponse"
            
            logging.info(f"KiroProviderHandler: Sending request to {kiro_api_url}")
            logging.info(f"KiroProviderHandler: Stream mode: {stream}")
            
            # Handle streaming mode
            if stream:
                logging.info(f"KiroProviderHandler: Using streaming mode")
                return self._handle_streaming_request(
                    kiro_api_url=kiro_api_url,
                    payload=payload,
                    headers=headers,
                    model=model
                )
            
            # Non-streaming request
            # Kiro API returns response in AWS Event Stream binary format
            response = await self.client.post(
                kiro_api_url,
                json=payload,
                headers=headers
            )
            
            # Check for 429 rate limit error before raising
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                # Handle 429 error with intelligent parsing
                self.handle_429_error(response_data, dict(response.headers))
                
                # Re-raise the error after handling
                response.raise_for_status()
            
            # Log error details for non-2xx responses before raising
            if response.status_code >= 400:
                try:
                    error_body = response.json()
                    logging.error(f"KiroProviderHandler: API error response: {json.dumps(error_body, indent=2)}")
                except Exception:
                    logging.error(f"KiroProviderHandler: API error response (text): {response.text}")
            
            response.raise_for_status()
            
            # Parse AWS Event Stream format response
            logging.info(f"KiroProviderHandler: Parsing AWS Event Stream response")
            
            from .kiro_parsers import AwsEventStreamParser
            
            parser = AwsEventStreamParser()
            parser.feed(response.content)
            
            # Extract content and tool calls
            content = parser.get_content()
            tool_calls = parser.get_tool_calls()
            
            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Parsed content length: {len(content)}")
                logging.info(f"KiroProviderHandler: Parsed tool calls: {len(tool_calls)}")
                if tool_calls:
                    logging.info(f"KiroProviderHandler: Tool calls: {json.dumps(tool_calls, indent=2)}")
            
            logging.info(f"KiroProviderHandler: Response parsed successfully")
            
            # Build OpenAI-format response
            openai_response = self._build_openai_response(model, content, tool_calls)
            
            self.record_success()
            return openai_response
            
        except Exception as e:
            import logging
            logging.error(f"KiroProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    def _build_openai_response(self, model: str, content: str, tool_calls: List[Dict]) -> Dict:
        """
        Build OpenAI-format response from parsed Kiro data.
        
        Args:
            model: Model name
            content: Parsed content text
            tool_calls: List of parsed tool calls
        
        Returns:
            OpenAI-format response dict
        """
        import logging
        
        # Determine finish reason
        finish_reason = "tool_calls" if tool_calls else "stop"
        
        # Build OpenAI-style response
        openai_response = {
            "id": f"kiro-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"{self.provider_id}/{model}",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content if not tool_calls else None
                },
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        
        # Add tool_calls if present
        if tool_calls:
            openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
            logging.info(f"KiroProviderHandler: Response includes {len(tool_calls)} tool calls")
        
        return openai_response

    async def _handle_streaming_request(self, kiro_api_url: str, payload: dict, headers: dict, model: str):
        """
        Handle streaming request to Kiro API.
        
        This method makes a streaming request to Kiro API and yields
        OpenAI-compatible SSE chunks as they are received.
        
        Args:
            kiro_api_url: Kiro API endpoint URL
            payload: Request payload
            headers: Request headers
            model: Model name
        
        Yields:
            OpenAI SSE chunk dicts
        """
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info(f"KiroProviderHandler: Starting streaming request")
        
        # Create a streaming HTTP client
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as streaming_client:
            # Make streaming request
            async with streaming_client.stream("POST", kiro_api_url, json=payload, headers=headers) as response:
                logger.info(f"KiroProviderHandler: Streaming response status: {response.status_code}")
                
                # Check for errors
                if response.status_code >= 400:
                    error_text = await response.aread()
                    logger.error(f"KiroProviderHandler: Streaming error: {error_text}")
                    raise Exception(f"Kiro API error: {response.status_code}")
                
                # Initialize streaming parser
                from .kiro_parsers import AwsEventStreamParser
                parser = AwsEventStreamParser()
                
                # Generate completion ID and timestamps
                completion_id = f"kiro-{int(time.time())}"
                created_time = int(time.time())
                
                # Track state for streaming
                first_chunk = True
                accumulated_content = ""
                
                # Process the streaming response
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    
                    # Feed chunk to parser
                    parser.feed(chunk)
                    
                    # Get current content from parser (but NOT tool calls yet - avoid premature finalization)
                    current_content = parser.get_content()
                    
                    # Calculate delta (new content since last chunk)
                    delta_content = current_content[len(accumulated_content):]
                    accumulated_content = current_content
                    
                    # Build OpenAI chunk for content only
                    if delta_content:
                        delta = {}
                        delta["content"] = delta_content
                            
                        if first_chunk:
                            delta["role"] = "assistant"
                            first_chunk = False
                        
                        openai_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": f"{self.provider_id}/{model}",
                            "choices": [{
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None
                            }]
                        }
                        
                        # Yield SSE-formatted chunk
                        yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                
                # Stream ended - now get tool calls (after all chunks processed)
                logger.info(f"KiroProviderHandler: Streaming completed")
                
                # Get tool calls AFTER all chunks are processed to avoid premature finalization
                final_tool_calls = parser.get_tool_calls()
                finish_reason = "tool_calls" if final_tool_calls else "stop"
                
                logger.info(f"KiroProviderHandler: Final tool calls count: {len(final_tool_calls)}")
                
                # If we have tool calls, send them in a separate chunk
                if final_tool_calls:
                    # Add index field for each tool call (required for streaming)
                    indexed_tool_calls = []
                    for idx, tc in enumerate(final_tool_calls):
                        func = tc.get("function") or {}
                        tool_name = func.get("name") or ""
                        tool_args = func.get("arguments") or "{}"
                        
                        logger.debug(f"Tool call [{idx}] '{tool_name}': id={tc.get('id')}, args_length={len(tool_args)}")
                        
                        indexed_tc = {
                            "index": idx,
                            "id": tc.get("id"),
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args
                            }
                        }
                        indexed_tool_calls.append(indexed_tc)
                    
                    # Send tool calls chunk
                    tool_calls_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": f"{self.provider_id}/{model}",
                        "choices": [{
                            "index": 0,
                            "delta": {"tool_calls": indexed_tool_calls},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(tool_calls_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                
                # Final chunk with usage (approximate - Kiro doesn't provide token counts in streaming)
                final_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": f"{self.provider_id}/{model}",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0
                    }
                }
                
                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                yield b"data: [DONE]\n\n"
    
    def _get_models_cache_path(self) -> str:
        """Get the path to the models cache file."""
        import os
        cache_dir = os.path.expanduser("~/.aisbf")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"kiro_models_cache_{self.provider_id}.json")
    
    def _save_models_cache(self, models: List[Model]) -> None:
        """Save models to cache file."""
        import logging
        import json
        
        try:
            cache_path = self._get_models_cache_path()
            cache_data = {
                'timestamp': time.time(),
                'models': []
            }
            
            for m in models:
                model_dict = {'id': m.id, 'name': m.name}
                # Save optional fields
                if m.context_size:
                    model_dict['context_size'] = m.context_size
                if m.context_length:
                    model_dict['context_length'] = m.context_length
                if m.description:
                    model_dict['description'] = m.description
                if m.pricing:
                    model_dict['pricing'] = m.pricing
                if m.top_provider:
                    model_dict['top_provider'] = m.top_provider
                if m.supported_parameters:
                    model_dict['supported_parameters'] = m.supported_parameters
                cache_data['models'].append(model_dict)
            
            with open(cache_path, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logging.info(f"KiroProviderHandler: ✓ Saved {len(models)} models to cache: {cache_path}")
        except Exception as e:
            logging.warning(f"KiroProviderHandler: Failed to save models cache: {e}")
    
    def _load_models_cache(self) -> Optional[List[Model]]:
        """Load models from cache file if available and not too old."""
        import logging
        import json
        import os
        
        try:
            cache_path = self._get_models_cache_path()
            
            if not os.path.exists(cache_path):
                logging.info(f"KiroProviderHandler: No cache file found at {cache_path}")
                return None
            
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
            
            cache_age = time.time() - cache_data.get('timestamp', 0)
            cache_age_hours = cache_age / 3600
            
            logging.info(f"KiroProviderHandler: Found cache file (age: {cache_age_hours:.1f} hours)")
            
            # Cache is valid for 24 hours
            if cache_age > 86400:
                logging.info(f"KiroProviderHandler: Cache is too old (>{cache_age_hours:.1f} hours), ignoring")
                return None
            
            models = []
            for m in cache_data.get('models', []):
                models.append(Model(
                    id=m['id'],
                    name=m['name'],
                    provider_id=self.provider_id,
                    context_size=m.get('context_size'),
                    context_length=m.get('context_length'),
                    description=m.get('description'),
                    pricing=m.get('pricing'),
                    top_provider=m.get('top_provider'),
                    supported_parameters=m.get('supported_parameters')
                ))
            
            if models:
                logging.info(f"KiroProviderHandler: ✓ Loaded {len(models)} models from cache")
                return models
            else:
                logging.info(f"KiroProviderHandler: Cache file is empty")
                return None
                
        except Exception as e:
            logging.warning(f"KiroProviderHandler: Failed to load models cache: {e}")
            return None

    async def get_models(self) -> List[Model]:
        """
        Return list of available models using fallback strategy.
        
        Priority order:
        1. Nexlab endpoint (http://lisa.nexlab.net:5000/kiro/models)
        2. Cache (if available and not too old)
        3. AWS Q API (ListAvailableModels)
        4. Static fallback list
        """
        try:
            import logging
            import json
            logging.info("=" * 80)
            logging.info("KiroProviderHandler: Starting model list retrieval")
            logging.info("=" * 80)

            # Apply rate limiting
            await self.apply_rate_limit()

            # Try nexlab endpoint first
            try:
                logging.info("KiroProviderHandler: [1/4] Attempting nexlab endpoint...")
                
                nexlab_endpoint = 'http://lisa.nexlab.net:5000/kiro/models'
                logging.info(f"KiroProviderHandler: Calling nexlab endpoint: {nexlab_endpoint}")
                
                # Create a new client with shorter timeout for nexlab
                nexlab_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
                
                try:
                    nexlab_response = await nexlab_client.get(nexlab_endpoint)
                    logging.info(f"KiroProviderHandler: Nexlab response status: {nexlab_response.status_code}")
                    
                    if nexlab_response.status_code == 200:
                        nexlab_data = nexlab_response.json()
                        logging.info(f"KiroProviderHandler: ✓ Nexlab API call successful!")
                        
                        if AISBF_DEBUG:
                            logging.info(f"KiroProviderHandler: Nexlab response: {nexlab_data}")
                        
                        # Parse nexlab response - expect array of models or {data: [...]}
                        models_list = nexlab_data if isinstance(nexlab_data, list) else nexlab_data.get('data', nexlab_data.get('models', []))
                        
                        models = []
                        for model_data in models_list:
                            if isinstance(model_data, str):
                                # Simple string model ID
                                models.append(Model(id=model_data, name=model_data, provider_id=self.provider_id))
                            elif isinstance(model_data, dict):
                                # Dict with id/name - check multiple field name variations
                                model_id = model_data.get('model_id') or model_data.get('id') or model_data.get('model', '')
                                display_name = model_data.get('model_name') or model_data.get('name') or model_data.get('display_name') or model_id
                                
                                # Extract context size/length - check all possible sources
                                # Priority: direct field > top_provider > nested
                                top_provider = model_data.get('top_provider', {})
                                context_size = (
                                    model_data.get('context_window_tokens') or
                                    model_data.get('context_window') or
                                    model_data.get('context_length') or
                                    model_data.get('context_size') or
                                    model_data.get('max_tokens') or
                                    (top_provider.get('context_length') if isinstance(top_provider, dict) else None)
                                )
                                
                                # Extract all available metadata
                                pricing = model_data.get('pricing')
                                description = model_data.get('description')
                                supported_parameters = model_data.get('supported_parameters')
                                architecture = model_data.get('architecture')
                                
                                # For nexlab: extract rate_multiplier and rate_unit as pricing
                                rate_multiplier = model_data.get('rate_multiplier')
                                rate_unit = model_data.get('rate_unit')
                                if rate_multiplier or rate_unit:
                                    if not pricing:
                                        pricing = {}
                                    if rate_multiplier:
                                        pricing['rate_multiplier'] = float(rate_multiplier) if isinstance(rate_multiplier, (int, float, str)) else None
                                    if rate_unit:
                                        pricing['rate_unit'] = rate_unit
                                
                                # Extract top_provider info (contains context_length, max_completion_tokens, is_moderated)
                                if isinstance(top_provider, dict):
                                    top_provider_data = {
                                        'context_length': top_provider.get('context_length'),
                                        'max_completion_tokens': top_provider.get('max_completion_tokens'),
                                        'is_moderated': top_provider.get('is_moderated')
                                    }
                                else:
                                    top_provider_data = None
                                
                                if model_id:
                                    models.append(Model(
                                        id=model_id,
                                        name=display_name,
                                        provider_id=self.provider_id,
                                        context_size=context_size,
                                        context_length=context_size,
                                        description=description,
                                        pricing=pricing,
                                        top_provider=top_provider_data,
                                        supported_parameters=supported_parameters
                                    ))
                        
                        if models:
                            for model in models:
                                logging.info(f"KiroProviderHandler:   - {model.id} ({model.name})")
                            
                            # Save to cache
                            self._save_models_cache(models)
                            
                            logging.info("=" * 80)
                            logging.info(f"KiroProviderHandler: ✓ SUCCESS - Returning {len(models)} models from nexlab endpoint")
                            logging.info(f"KiroProviderHandler: Source: Dynamic API retrieval (Nexlab)")
                            logging.info("=" * 80)
                            return models
                        else:
                            logging.warning("KiroProviderHandler: ✗ Nexlab endpoint returned empty model list")
                    else:
                        logging.warning(f"KiroProviderHandler: ✗ Nexlab API call failed with status {nexlab_response.status_code}")
                        try:
                            error_body = nexlab_response.json()
                            logging.warning(f"KiroProviderHandler: Nexlab error response: {error_body}")
                        except:
                            logging.warning(f"KiroProviderHandler: Nexlab error response (text): {nexlab_response.text[:200]}")
                finally:
                    await nexlab_client.aclose()
                    
            except Exception as nexlab_error:
                logging.warning(f"KiroProviderHandler: ✗ Exception during nexlab API call")
                logging.warning(f"KiroProviderHandler: Error type: {type(nexlab_error).__name__}")
                logging.warning(f"KiroProviderHandler: Error message: {str(nexlab_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"KiroProviderHandler: Full traceback:", exc_info=True)
            
            # Try to load from cache
            logging.info("-" * 80)
            logging.info("KiroProviderHandler: [2/4] Attempting to load from cache...")
            
            cached_models = self._load_models_cache()
            if cached_models:
                for model in cached_models:
                    logging.info(f"KiroProviderHandler:   - {model.id} ({model.name})")
                
                logging.info("=" * 80)
                logging.info(f"KiroProviderHandler: ✓ Returning {len(cached_models)} models from cache")
                logging.info(f"KiroProviderHandler: Source: Cached model list")
                logging.info("=" * 80)
                return cached_models

            # Try to fetch models from AWS Q API using OAuth2 bearer token with pagination
            try:
                logging.info("-" * 80)
                logging.info("KiroProviderHandler: [3/4] Attempting to fetch from AWS Q API...")
                
                if not self.auth_manager:
                    raise Exception("Auth manager not initialized")
                
                # Get access token
                access_token = await self.auth_manager.get_access_token()
                profile_arn = self.auth_manager.profile_arn
                
                # For ListAvailableModels, always include profileArn if available (like kiro-cli)
                effective_profile_arn = profile_arn or ""
                if effective_profile_arn:
                    logging.info(f"KiroProviderHandler: Using profileArn for models API")
                else:
                    logging.info(f"KiroProviderHandler: No profileArn available for models API")
                
                # Prepare headers for AWS JSON 1.0 protocol
                headers = self.auth_manager.get_auth_headers(access_token)
                headers['Content-Type'] = 'application/x-amz-json-1.0'
                headers['x-amz-target'] = 'AmazonCodeWhispererService.ListAvailableModels'
                
                # Build URL (AWS JSON protocol style)
                base_url = f"https://q.{self.region}.amazonaws.com/"
                
                # Handle pagination - keep fetching until no nextToken
                all_models = []
                next_token = None
                page_num = 0
                
                while True:
                    page_num += 1
                    logging.info(f"KiroProviderHandler: Fetching page {page_num}...")
                    
                    # Build JSON body with fields (not query params!)
                    # Based on SDK serialization: origin, profileArn, nextToken go in the body
                    # Origin::Cli.as_str() returns "CLI" (all uppercase) - see _origin.rs line 162
                    request_body = {
                        "origin": "CLI"
                    }
                    
                    if effective_profile_arn:
                        request_body["profileArn"] = effective_profile_arn
                    
                    if next_token:
                        request_body["nextToken"] = next_token
                    
                    logging.info(f"KiroProviderHandler: Calling {base_url} with AWS JSON 1.0 protocol")
                    
                    if AISBF_DEBUG:
                        logging.info(f"KiroProviderHandler: Request body: {json.dumps(request_body, indent=2)}")
                    
                    # AWS JSON protocol: POST with JSON body containing the fields
                    response = await self.client.post(
                        base_url,
                        json=request_body,
                        headers=headers
                    )
                    
                    logging.info(f"KiroProviderHandler: API response status: {response.status_code}")
                    
                    if response.status_code != 200:
                        logging.warning(f"KiroProviderHandler: ✗ API call failed with status {response.status_code}")
                        try:
                            error_body = response.json()
                            logging.warning(f"KiroProviderHandler: Error response: {error_body}")
                        except:
                            logging.warning(f"KiroProviderHandler: Error response (text): {response.text[:200]}")
                        break
                    
                    response_data = response.json()
                    
                    if AISBF_DEBUG:
                        logging.info(f"KiroProviderHandler: Response data: {json.dumps(response_data, indent=2)}")
                    
                    # Parse response - expecting structure similar to AWS SDK response
                    models_list = response_data.get('models', [])
                    
                    for model_data in models_list:
                        # Extract model ID and name
                        model_id = model_data.get('modelId', model_data.get('id', ''))
                        model_name = model_data.get('modelName', model_data.get('name', model_id))
                        
                        # Extract context size/length
                        context_size = (
                            model_data.get('contextWindow') or
                            model_data.get('context_window') or
                            model_data.get('contextLength') or
                            model_data.get('context_length') or
                            model_data.get('max_context_length') or
                            model_data.get('maxTokens') or
                            model_data.get('max_tokens')
                        )
                        
                        # Extract all available metadata
                        pricing = model_data.get('pricing')
                        description = model_data.get('description')
                        supported_parameters = model_data.get('supported_parameters')
                        
                        # For AWS Q API: extract pricing from promptTokenPrice and completionTokenPrice
                        prompt_token_price = model_data.get('promptTokenPrice') or model_data.get('prompt_token_price')
                        completion_token_price = model_data.get('completionTokenPrice') or model_data.get('completion_token_price')
                        if prompt_token_price or completion_token_price:
                            if not pricing:
                                pricing = {}
                            if prompt_token_price:
                                try:
                                    pricing['prompt'] = float(prompt_token_price)
                                except (ValueError, TypeError):
                                    pricing['prompt'] = prompt_token_price
                            if completion_token_price:
                                try:
                                    pricing['completion'] = float(completion_token_price)
                                except (ValueError, TypeError):
                                    pricing['completion'] = completion_token_price
                        
                        # Extract top_provider info if present
                        top_provider = model_data.get('topProvider') or model_data.get('top_provider')
                        if isinstance(top_provider, dict):
                            top_provider_data = {
                                'context_length': top_provider.get('context_length') or top_provider.get('contextLength'),
                                'max_completion_tokens': top_provider.get('max_completion_tokens') or top_provider.get('maxCompletionTokens'),
                                'is_moderated': top_provider.get('is_moderated') or top_provider.get('isModerated')
                            }
                        else:
                            top_provider_data = None
                        
                        if model_id:
                            all_models.append(Model(
                                id=model_id,
                                name=model_name,
                                provider_id=self.provider_id,
                                context_size=context_size,
                                context_length=context_size,
                                description=description,
                                pricing=pricing,
                                top_provider=top_provider_data,
                                supported_parameters=supported_parameters
                            ))
                            logging.info(f"KiroProviderHandler:   - {model_id} ({model_name})")
                    
                    # Check for pagination token
                    next_token = response_data.get('nextToken')
                    if not next_token:
                        logging.info(f"KiroProviderHandler: No more pages (total pages: {page_num})")
                        break
                    
                    logging.info(f"KiroProviderHandler: Found nextToken, fetching next page...")
                
                if all_models:
                    logging.info(f"KiroProviderHandler: ✓ API call successful!")
                    logging.info(f"KiroProviderHandler: Retrieved {len(all_models)} models across {page_num} page(s)")
                    
                    # Save to cache
                    self._save_models_cache(all_models)
                    
                    logging.info("=" * 80)
                    logging.info(f"KiroProviderHandler: ✓ SUCCESS - Returning {len(all_models)} models from API")
                    logging.info(f"KiroProviderHandler: Source: Dynamic API retrieval (AWS Q)")
                    logging.info("=" * 80)
                    return all_models
                else:
                    logging.warning("KiroProviderHandler: ✗ API returned empty model list")
            
            except Exception as api_error:
                logging.warning(f"KiroProviderHandler: ✗ Exception during AWS Q API call")
                logging.warning(f"KiroProviderHandler: Error type: {type(api_error).__name__}")
                logging.warning(f"KiroProviderHandler: Error message: {str(api_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"KiroProviderHandler: Full traceback:", exc_info=True)
            
            # Final fallback to static list
            logging.info("-" * 80)
            logging.info("KiroProviderHandler: [4/4] Using static fallback model list")
            static_models = [
                Model(id="anthropic.claude-3-5-sonnet-20241022-v2:0", name="Claude 3.5 Sonnet v2", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="anthropic.claude-3-5-haiku-20241022-v1:0", name="Claude 3.5 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="anthropic.claude-3-5-sonnet-20240620-v1:0", name="Claude 3.5 Sonnet v1", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="anthropic.claude-sonnet-3-5-v2", name="Claude 3.5 Sonnet v2 (alias)", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-sonnet-4-5", name="Claude 3.5 Sonnet v2 (short)", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-haiku-4-5", name="Claude 3.5 Haiku (short)", provider_id=self.provider_id, context_size=200000, context_length=200000),
            ]
            
            for model in static_models:
                logging.info(f"KiroProviderHandler:   - {model.id} ({model.name})")
            
            logging.info("=" * 80)
            logging.info(f"KiroProviderHandler: ✓ Returning {len(static_models)} models from static list")
            logging.info(f"KiroProviderHandler: Source: Static fallback configuration")
            logging.info("=" * 80)
            
            return static_models
        except Exception as e:
            import logging
            logging.error("=" * 80)
            logging.error(f"KiroProviderHandler: ✗ FATAL ERROR getting models: {str(e)}")
            logging.error("=" * 80)
            logging.error(f"KiroProviderHandler: Error details:", exc_info=True)
            raise e

class OllamaProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        super().__init__(provider_id, api_key)
        # Increase timeout for Ollama requests (especially for cloud models)
        # Using separate timeouts for connect, read, write, and pool
        timeout = httpx.Timeout(
            connect=60.0,      # 60 seconds to establish connection
            read=300.0,         # 5 minutes to read response
            write=60.0,         # 60 seconds to write request
            pool=60.0           # 60 seconds for pool acquisition
        )
        self.client = httpx.AsyncClient(base_url=config.providers[provider_id].endpoint, timeout=timeout)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Dict:
        """
        Handle request for Ollama provider.
        Note: Ollama doesn't support tools/tool_choice, so these parameters are accepted but ignored.
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        logger.info(f"=== OllamaProviderHandler.handle_request START ===")
        logger.info(f"Provider ID: {self.provider_id}")
        logger.info(f"Endpoint: {self.client.base_url}")
        logger.info(f"Model: {model}")
        logger.info(f"Messages count: {len(messages)}")
        logger.info(f"Max tokens: {max_tokens}")
        logger.info(f"Temperature: {temperature}")
        logger.info(f"Stream: {stream}")
        logger.info(f"API key provided: {bool(self.api_key)}")
        
        if self.is_rate_limited():
            logger.error("Provider is rate limited")
            raise Exception("Provider rate limited")

        try:
            # Test connection first
            logger.info("Testing Ollama connection...")
            try:
                health_response = await self.client.get("/api/tags", timeout=10.0)
                logger.info(f"Ollama health check passed: {health_response.status_code}")
                logger.info(f"Available models: {health_response.json().get('models', [])}")
            except Exception as e:
                logger.error(f"Ollama health check failed: {str(e)}")
                logger.error(f"Cannot connect to Ollama at {self.client.base_url}")
                logger.error(f"Please ensure Ollama is running and accessible")
                raise Exception(f"Cannot connect to Ollama at {self.client.base_url}: {str(e)}")
            
            # Apply rate limiting
            logger.info("Applying rate limiting...")
            await self.apply_rate_limit()
            logger.info("Rate limiting applied")

            prompt = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
            logger.info(f"Prompt length: {len(prompt)} characters")
            
            # Build options with only non-None values
            options = {"temperature": temperature}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            
            request_data = {
                "model": model,
                "prompt": prompt,
                "options": options,
                "stream": False  # Explicitly disable streaming for non-streaming requests
            }
            
            # Add API key to headers if provided (for Ollama cloud models)
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                logger.info("API key added to request headers for Ollama cloud")
            
            logger.info(f"Sending POST request to {self.client.base_url}/api/generate")
            logger.info(f"Request data: {request_data}")
            logger.info(f"Request headers: {headers}")
            logger.info(f"Client timeout: {self.client.timeout}")
            
            response = await self.client.post("/api/generate", json=request_data, headers=headers)
            logger.info(f"Response status code: {response.status_code}")
            logger.info(f"Response content type: {response.headers.get('content-type')}")
            logger.info(f"Response content length: {len(response.content)} bytes")
            logger.info(f"Raw response content (first 500 chars): {response.text[:500]}")
            
            # Check for 429 rate limit error before raising
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                # Handle 429 error with intelligent parsing
                self.handle_429_error(response_data, dict(response.headers))
                
                # Re-raise the error after handling
                response.raise_for_status()
            
            response.raise_for_status()
            
            # Ollama may return multiple JSON objects, parse them all
            content = response.text
            logger.info(f"Attempting to parse response as JSON...")
            
            try:
                # Try parsing as single JSON first
                response_json = response.json()
                logger.info(f"Response parsed as single JSON: {response_json}")
            except json.JSONDecodeError as e:
                # If that fails, try parsing multiple JSON objects
                logger.warning(f"Failed to parse as single JSON: {e}")
                logger.info(f"Attempting to parse as multiple JSON objects...")
                
                # Parse multiple JSON objects (one per line)
                responses = []
                for line in content.strip().split('\n'):
                    if line.strip():
                        try:
                            obj = json.loads(line)
                            responses.append(obj)
                        except json.JSONDecodeError as line_error:
                            logger.error(f"Failed to parse line: {line}")
                            logger.error(f"Error: {line_error}")
                
                if not responses:
                    raise Exception("No valid JSON objects found in response")
                
                # Combine responses - take the last complete response
                # Ollama sends multiple chunks, we want the final one
                response_json = responses[-1]
                logger.info(f"Parsed {len(responses)} JSON objects, using last one: {response_json}")
            
            logger.info(f"Final response: {response_json}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW OLLAMA RESPONSE ===")
                logging.info(f"Raw response JSON: {response_json}")
                logging.info(f"=== END RAW OLLAMA RESPONSE ===")
            
            logger.info(f"=== OllamaProviderHandler.handle_request END ===")
            
            # Convert Ollama response to OpenAI-style format
            openai_response = {
                "id": f"ollama-{model}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"{self.provider_id}/{model}",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_json.get("response", "")
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": response_json.get("prompt_eval_count", 0),
                    "completion_tokens": response_json.get("eval_count", 0),
                    "total_tokens": response_json.get("prompt_eval_count", 0) + response_json.get("eval_count", 0)
                }
            }
            
            # Dump final response dict if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== FINAL OLLAMA RESPONSE DICT ===")
                logging.info(f"Final response: {openai_response}")
                logging.info(f"=== END FINAL OLLAMA RESPONSE DICT ===")
            
            return openai_response
        except Exception as e:
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        # Apply rate limiting
        await self.apply_rate_limit()

        response = await self.client.get("/api/tags")
        response.raise_for_status()
        models = response.json().get('models', [])
        return [Model(id=model, name=model, provider_id=self.provider_id) for model in models]

PROVIDER_HANDLERS = {
    'google': GoogleProviderHandler,
    'openai': OpenAIProviderHandler,
    'anthropic': AnthropicProviderHandler,
    'ollama': OllamaProviderHandler,
    'kiro': KiroProviderHandler,
    'claude': ClaudeProviderHandler
}

def get_provider_handler(provider_id: str, api_key: Optional[str] = None) -> BaseProviderHandler:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"=== get_provider_handler START ===")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"API key provided: {bool(api_key)}")
    
    provider_config = config.get_provider(provider_id)
    logger.info(f"Provider config: {provider_config}")
    logger.info(f"Provider type: {provider_config.type}")
    logger.info(f"Provider endpoint: {provider_config.endpoint}")
    
    handler_class = PROVIDER_HANDLERS.get(provider_config.type)
    logger.info(f"Handler class: {handler_class.__name__ if handler_class else 'None'}")
    logger.info(f"Available handler types: {list(PROVIDER_HANDLERS.keys())}")
    
    if not handler_class:
        logger.error(f"Unsupported provider type: {provider_config.type}")
        raise ValueError(f"Unsupported provider type: {provider_config.type}")
    
    # All handlers now accept api_key as optional parameter
    logger.info(f"Creating handler with provider_id and optional api_key")
    handler = handler_class(provider_id, api_key)
    
    logger.info(f"Handler created: {handler.__class__.__name__}")
    logger.info(f"=== get_provider_handler END ===")
    return handler
