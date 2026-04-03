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


class AnthropicFormatConverter:
    """
    Shared utility class for converting between OpenAI and Anthropic message formats.
    Used by both AnthropicProviderHandler and ClaudeProviderHandler.
    
    All methods are static to allow usage without instantiation.
    """
    
    # Anthropic stop_reason → OpenAI finish_reason mapping
    STOP_REASON_MAP = {
        'end_turn': 'stop',
        'max_tokens': 'length',
        'stop_sequence': 'stop',
        'tool_use': 'tool_calls'
    }
    
    @staticmethod
    def sanitize_tool_call_id(tool_call_id: str) -> str:
        """Sanitize tool call ID for Anthropic API (alphanumeric, underscore, hyphen only)."""
        import re
        return re.sub(r'[^a-zA-Z0-9_-]', '_', tool_call_id)
    
    @staticmethod
    def filter_empty_content(content) -> Union[str, list, None]:
        """Filter empty content from messages for Anthropic API compatibility."""
        if content is None:
            return None
        if isinstance(content, str):
            return None if content.strip() == "" else content
        if isinstance(content, list):
            filtered = []
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        text = block.get('text', '')
                        if text and text.strip():
                            filtered.append(block)
                    else:
                        filtered.append(block)
                else:
                    filtered.append(block)
            return filtered if filtered else None
        return content
    
    @staticmethod
    def extract_images_from_content(content) -> list:
        """
        Convert OpenAI image_url content blocks to Anthropic image source format.
        
        Handles:
        - data:image/jpeg;base64,... → {"type": "image", "source": {"type": "base64", ...}}
        - https://... → {"type": "image", "source": {"type": "url", ...}}
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not isinstance(content, list):
            return []
        
        images = []
        max_image_size = 5 * 1024 * 1024  # 5MB
        
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get('type') != 'image_url':
                continue
            
            image_url_obj = block.get('image_url', {})
            url = image_url_obj.get('url', '') if isinstance(image_url_obj, dict) else ''
            if not url:
                continue
            
            if url.startswith('data:'):
                try:
                    header, data = url.split(',', 1)
                    media_type = header.split(';')[0].replace('data:', '')
                    if len(data) > max_image_size:
                        logger.warning(f"Image too large ({len(data)} bytes), skipping")
                        continue
                    images.append({
                        'type': 'image',
                        'source': {'type': 'base64', 'media_type': media_type, 'data': data}
                    })
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse data URL: {e}")
            elif url.startswith(('http://', 'https://')):
                images.append({
                    'type': 'image',
                    'source': {'type': 'url', 'url': url}
                })
            elif block.get('type') == 'image' and 'source' in block:
                images.append(block)
        
        return images
    
    @staticmethod
    def convert_messages_to_anthropic(messages: list, sanitize_ids: bool = True) -> tuple:
        """
        Convert OpenAI messages to Anthropic format.
        
        Handles:
        - System message extraction (separate 'system' parameter)
        - Tool role → user message with tool_result content blocks
        - Assistant tool_calls → tool_use content blocks
        - Multimodal content (images)
        - Empty content filtering
        
        Args:
            messages: OpenAI format messages
            sanitize_ids: Whether to sanitize tool call IDs
            
        Returns:
            Tuple of (system_message: str|None, anthropic_messages: list)
        """
        import logging
        import json
        
        system_message = None
        anthropic_messages = []
        
        for msg in messages:
            role = msg.get('role')
            content = msg.get('content')
            
            if role == 'system':
                system_message = content
                logging.info(f"AnthropicFormatConverter: Extracted system message ({len(content) if content else 0} chars)")
            
            elif role == 'tool':
                tool_call_id = msg.get('tool_call_id', msg.get('name', 'unknown'))
                tool_result_block = {
                    'type': 'tool_result',
                    'tool_use_id': tool_call_id,
                    'content': content or ""
                }
                
                if anthropic_messages and anthropic_messages[-1]['role'] == 'user':
                    last_content = anthropic_messages[-1]['content']
                    if isinstance(last_content, str):
                        anthropic_messages[-1]['content'] = [
                            {'type': 'text', 'text': last_content},
                            tool_result_block
                        ]
                    elif isinstance(last_content, list):
                        anthropic_messages[-1]['content'].append(tool_result_block)
                else:
                    anthropic_messages.append({
                        'role': 'user',
                        'content': [tool_result_block]
                    })
            
            elif role == 'assistant':
                tool_calls = msg.get('tool_calls')
                
                if tool_calls:
                    content_blocks = []
                    filtered = AnthropicFormatConverter.filter_empty_content(content)
                    if filtered:
                        if isinstance(filtered, str):
                            content_blocks.append({'type': 'text', 'text': filtered})
                        elif isinstance(filtered, list):
                            content_blocks.extend(filtered)
                    
                    for tc in tool_calls:
                        raw_id = tc.get('id', f"toolu_{len(content_blocks)}")
                        tool_id = AnthropicFormatConverter.sanitize_tool_call_id(raw_id) if sanitize_ids else raw_id
                        function = tc.get('function', {})
                        arguments = function.get('arguments', {})
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except json.JSONDecodeError:
                                arguments = {}
                        
                        content_blocks.append({
                            'type': 'tool_use',
                            'id': tool_id,
                            'name': function.get('name', ''),
                            'input': arguments
                        })
                    
                    if content_blocks:
                        anthropic_messages.append({
                            'role': 'assistant',
                            'content': content_blocks
                        })
                else:
                    filtered = AnthropicFormatConverter.filter_empty_content(content)
                    if filtered is None:
                        continue
                    
                    if isinstance(filtered, list):
                        text_parts = []
                        for block in filtered:
                            if isinstance(block, dict):
                                text_parts.append(block.get('text', ''))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        content_str = '\n'.join(text_parts)
                    else:
                        content_str = filtered or ""
                    
                    if content_str:
                        anthropic_messages.append({
                            'role': 'assistant',
                            'content': content_str
                        })
            
            elif role == 'user':
                if isinstance(content, list):
                    content_blocks = []
                    images = AnthropicFormatConverter.extract_images_from_content(content)
                    
                    for block in content:
                        if isinstance(block, dict):
                            btype = block.get('type', '')
                            if btype == 'text':
                                content_blocks.append(block)
                            elif btype not in ('image_url', 'image'):
                                content_blocks.append(block)
                        elif isinstance(block, str):
                            content_blocks.append({'type': 'text', 'text': block})
                    
                    content_blocks.extend(images)
                    anthropic_messages.append({
                        'role': 'user',
                        'content': content_blocks if content_blocks else content or ""
                    })
                else:
                    anthropic_messages.append({
                        'role': 'user',
                        'content': content or ""
                    })
            
            else:
                logging.warning(f"AnthropicFormatConverter: Unknown role '{role}', treating as user")
                anthropic_messages.append({
                    'role': 'user',
                    'content': content or ""
                })
        
        logging.info(f"AnthropicFormatConverter: Converted {len(messages)} OpenAI → {len(anthropic_messages)} Anthropic messages")
        return system_message, anthropic_messages
    
    @staticmethod
    def convert_tools_to_anthropic(tools: list) -> Optional[list]:
        """
        Convert OpenAI tools to Anthropic format with schema normalization.
        
        Normalizes:
        - ["string", "null"] → "string"
        - Removes additionalProperties: false
        - Cleans up required array for nullable fields
        """
        import logging
        
        if not tools:
            return None
        
        def normalize_schema(schema):
            if not isinstance(schema, dict):
                return schema
            result = {}
            for key, value in schema.items():
                if key == "type" and isinstance(value, list):
                    non_null = [t for t in value if t != "null"]
                    result[key] = non_null[0] if len(non_null) == 1 else (non_null if non_null else "string")
                elif key == "properties" and isinstance(value, dict):
                    result[key] = {k: normalize_schema(v) for k, v in value.items()}
                elif key == "items" and isinstance(value, dict):
                    result[key] = normalize_schema(value)
                elif key == "additionalProperties" and value is False:
                    continue
                elif key == "required" and isinstance(value, list):
                    props = schema.get("properties", {})
                    cleaned = [f for f in value if f in props and not (isinstance(props.get(f, {}), dict) and isinstance(props[f].get("type"), list) and "null" in props[f]["type"])]
                    if cleaned:
                        result[key] = cleaned
                else:
                    result[key] = value
            return result
        
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                function = tool.get("function", {})
                anthropic_tools.append({
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "input_schema": normalize_schema(function.get("parameters", {}))
                })
                logging.info(f"AnthropicFormatConverter: Converted tool: {function.get('name')}")
        
        return anthropic_tools if anthropic_tools else None
    
    @staticmethod
    def convert_tool_choice_to_anthropic(tool_choice) -> Optional[dict]:
        """
        Convert OpenAI tool_choice to Anthropic format.
        
        "auto" → {"type": "auto"}
        "none" → None
        "required" → {"type": "any"}
        {"type": "function", "function": {"name": "X"}} → {"type": "tool", "name": "X"}
        """
        import logging
        
        if not tool_choice:
            return None
        
        if isinstance(tool_choice, str):
            if tool_choice == "auto":
                return {"type": "auto"}
            elif tool_choice == "none":
                return None
            elif tool_choice == "required":
                return {"type": "any"}
            else:
                logging.warning(f"Unknown tool_choice: {tool_choice}")
                return {"type": "auto"}
        
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                name = tool_choice.get("function", {}).get("name")
                return {"type": "tool", "name": name} if name else {"type": "auto"}
            return tool_choice
        
        return {"type": "auto"}
    
    @staticmethod
    def convert_anthropic_response_to_openai(response_data: dict, provider_id: str, model: str) -> dict:
        """
        Convert Anthropic API response (dict) to OpenAI chat completion format.
        
        Handles text blocks, tool_use blocks, thinking blocks, usage metadata, stop reasons.
        """
        import json
        import logging
        logger = logging.getLogger(__name__)
        
        content_text = ""
        tool_calls = []
        thinking_text = ""
        
        for block in response_data.get('content', []):
            btype = block.get('type', '')
            if btype == 'text':
                content_text += block.get('text', '')
            elif btype == 'tool_use':
                tool_calls.append({
                    'id': block.get('id', f"call_{len(tool_calls)}"),
                    'type': 'function',
                    'function': {
                        'name': block.get('name', ''),
                        'arguments': json.dumps(block.get('input', {}))
                    }
                })
            elif btype == 'thinking':
                thinking_text = block.get('thinking', '')
            elif btype == 'redacted_thinking':
                logger.debug("Found redacted_thinking block")
        
        stop_reason = response_data.get('stop_reason', 'end_turn')
        finish_reason = AnthropicFormatConverter.STOP_REASON_MAP.get(stop_reason, 'stop')
        
        usage = response_data.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cache_read = usage.get('cache_read_input_tokens', 0)
        cache_creation = usage.get('cache_creation_input_tokens', 0)
        
        openai_response = {
            'id': f"{provider_id}-{model}-{int(time.time())}",
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content_text if content_text else None
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'prompt_tokens_details': {'cached_tokens': cache_read, 'audio_tokens': 0},
                'completion_tokens_details': {'reasoning_tokens': 0, 'audio_tokens': 0}
            }
        }
        
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        if thinking_text:
            openai_response['choices'][0]['message']['provider_options'] = {
                'anthropic': {'thinking': thinking_text}
            }
        
        return openai_response
    
    @staticmethod
    def convert_anthropic_sdk_response_to_openai(response, provider_id: str, model: str) -> dict:
        """
        Convert Anthropic SDK response object (with attributes) to OpenAI format.
        """
        import json
        import logging
        logger = logging.getLogger(__name__)
        
        content_text = ""
        tool_calls = []
        thinking_text = ""
        
        for block in getattr(response, 'content', []):
            btype = getattr(block, 'type', '')
            if btype == 'text' or hasattr(block, 'text'):
                content_text += getattr(block, 'text', '')
            elif btype == 'tool_use':
                raw_input = getattr(block, 'input', {})
                tool_calls.append({
                    'id': getattr(block, 'id', f"call_{len(tool_calls)}"),
                    'type': 'function',
                    'function': {
                        'name': getattr(block, 'name', ''),
                        'arguments': json.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
                    }
                })
            elif btype == 'thinking':
                thinking_text = getattr(block, 'thinking', '')
        
        stop_reason = getattr(response, 'stop_reason', 'end_turn') or 'end_turn'
        finish_reason = AnthropicFormatConverter.STOP_REASON_MAP.get(stop_reason, 'stop')
        
        usage_obj = getattr(response, 'usage', None)
        input_tokens = getattr(usage_obj, 'input_tokens', 0) or 0 if usage_obj else 0
        output_tokens = getattr(usage_obj, 'output_tokens', 0) or 0 if usage_obj else 0
        cache_read = getattr(usage_obj, 'cache_read_input_tokens', 0) or 0 if usage_obj else 0
        cache_creation = getattr(usage_obj, 'cache_creation_input_tokens', 0) or 0 if usage_obj else 0
        
        openai_response = {
            'id': getattr(response, 'id', f"{provider_id}-{model}-{int(time.time())}"),
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content_text if content_text else None
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'prompt_tokens_details': {'cached_tokens': cache_read, 'audio_tokens': 0},
                'completion_tokens_details': {'reasoning_tokens': 0, 'audio_tokens': 0}
            }
        }
        
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        if thinking_text:
            openai_response['choices'][0]['message']['provider_options'] = {
                'anthropic': {'thinking': thinking_text}
            }
        
        return openai_response


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

            # Convert OpenAI messages to Anthropic format
            # Key differences:
            # 1. System messages extracted to separate 'system' parameter
            # 2. Tool role messages → user messages with tool_result content blocks
            # 3. Assistant messages with tool_calls → tool_use content blocks
            # 4. Images: OpenAI image_url → Anthropic image source format
            system_message = None
            anthropic_messages = []
            
            for msg in messages:
                role = msg.get('role')
                content = msg.get('content')
                
                if role == 'system':
                    # Extract system message (Anthropic uses separate 'system' parameter)
                    system_message = content
                    logging.info(f"AnthropicProviderHandler: Extracted system message ({len(content) if content else 0} chars)")
                
                elif role == 'tool':
                    # Convert tool message to user message with tool_result content block
                    tool_call_id = msg.get('tool_call_id', msg.get('name', 'unknown'))
                    tool_result_block = {
                        'type': 'tool_result',
                        'tool_use_id': tool_call_id,
                        'content': content or ""
                    }
                    
                    # Merge into existing user message if last message is user
                    if anthropic_messages and anthropic_messages[-1]['role'] == 'user':
                        last_content = anthropic_messages[-1]['content']
                        if isinstance(last_content, str):
                            anthropic_messages[-1]['content'] = [
                                {'type': 'text', 'text': last_content},
                                tool_result_block
                            ]
                        elif isinstance(last_content, list):
                            anthropic_messages[-1]['content'].append(tool_result_block)
                        logging.info(f"AnthropicProviderHandler: Appended tool_result to existing user message")
                    else:
                        anthropic_messages.append({
                            'role': 'user',
                            'content': [tool_result_block]
                        })
                        logging.info(f"AnthropicProviderHandler: Created new user message with tool_result")
                
                elif role == 'assistant':
                    tool_calls = msg.get('tool_calls')
                    
                    if tool_calls:
                        # Convert to Anthropic format with tool_use content blocks
                        content_blocks = []
                        
                        # Add text content if present
                        if content and isinstance(content, str) and content.strip():
                            content_blocks.append({'type': 'text', 'text': content})
                        elif content and isinstance(content, list):
                            content_blocks.extend(content)
                        
                        # Add tool_use blocks
                        import json as _json
                        for tc in tool_calls:
                            tool_id = tc.get('id', f"toolu_{len(content_blocks)}")
                            function = tc.get('function', {})
                            tool_name = function.get('name', '')
                            arguments = function.get('arguments', {})
                            if isinstance(arguments, str):
                                try:
                                    arguments = _json.loads(arguments)
                                except _json.JSONDecodeError:
                                    logging.warning(f"AnthropicProviderHandler: Failed to parse tool arguments: {arguments}")
                                    arguments = {}
                            
                            content_blocks.append({
                                'type': 'tool_use',
                                'id': tool_id,
                                'name': tool_name,
                                'input': arguments
                            })
                            logging.info(f"AnthropicProviderHandler: Converted tool_call to tool_use: {tool_name}")
                        
                        if content_blocks:
                            anthropic_messages.append({
                                'role': 'assistant',
                                'content': content_blocks
                            })
                    else:
                        # Regular assistant message - handle potentially None content
                        if content is not None:
                            anthropic_messages.append({
                                'role': 'assistant',
                                'content': content
                            })
                        else:
                            # Skip assistant messages with None content (tool_calls-only messages
                            # that were already handled above shouldn't reach here)
                            logging.info(f"AnthropicProviderHandler: Skipping assistant message with None content")
                
                elif role == 'user':
                    # Handle multimodal content (images)
                    if isinstance(content, list):
                        content_blocks = []
                        for block in content:
                            if isinstance(block, dict):
                                block_type = block.get('type', '')
                                if block_type == 'text':
                                    content_blocks.append(block)
                                elif block_type == 'image_url':
                                    # Convert OpenAI image_url to Anthropic image source
                                    image_url_obj = block.get('image_url', {})
                                    url = image_url_obj.get('url', '') if isinstance(image_url_obj, dict) else ''
                                    if url.startswith('data:'):
                                        try:
                                            header, data = url.split(',', 1)
                                            media_type = header.split(';')[0].replace('data:', '')
                                            content_blocks.append({
                                                'type': 'image',
                                                'source': {
                                                    'type': 'base64',
                                                    'media_type': media_type,
                                                    'data': data
                                                }
                                            })
                                        except (ValueError, IndexError) as e:
                                            logging.warning(f"AnthropicProviderHandler: Failed to parse data URL: {e}")
                                    elif url.startswith(('http://', 'https://')):
                                        content_blocks.append({
                                            'type': 'image',
                                            'source': {
                                                'type': 'url',
                                                'url': url
                                            }
                                        })
                                else:
                                    content_blocks.append(block)
                            elif isinstance(block, str):
                                content_blocks.append({'type': 'text', 'text': block})
                        
                        anthropic_messages.append({
                            'role': 'user',
                            'content': content_blocks if content_blocks else content or ""
                        })
                    else:
                        anthropic_messages.append({
                            'role': 'user',
                            'content': content or ""
                        })
                
                else:
                    logging.warning(f"AnthropicProviderHandler: Unknown message role '{role}', treating as user")
                    anthropic_messages.append({
                        'role': 'user',
                        'content': content or ""
                    })
            
            logging.info(f"AnthropicProviderHandler: Converted {len(messages)} OpenAI messages to {len(anthropic_messages)} Anthropic messages")
            if system_message:
                logging.info(f"AnthropicProviderHandler: System message extracted ({len(system_message)} chars)")
            
            # Apply cache_control if native caching is enabled
            if enable_native_caching:
                cumulative_tokens = 0
                for i, msg in enumerate(anthropic_messages):
                    message_tokens = count_messages_tokens([{'role': msg['role'], 'content': msg['content'] if isinstance(msg['content'], str) else str(msg['content'])}], model)
                    cumulative_tokens += message_tokens
                    
                    if i < len(anthropic_messages) - 2 and cumulative_tokens >= min_cacheable_tokens:
                        content = msg.get('content')
                        if isinstance(content, str) and content.strip():
                            msg['content'] = [
                                {
                                    'type': 'text',
                                    'text': content,
                                    'cache_control': {'type': 'ephemeral'}
                                }
                            ]
                        elif isinstance(content, list) and content:
                            content[-1]['cache_control'] = {'type': 'ephemeral'}
                        logging.info(f"AnthropicProviderHandler: Applied cache_control to message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")
                
                # Also apply cache_control to system message if present
                if system_message:
                    system_message_param = [{
                        'type': 'text',
                        'text': system_message,
                        'cache_control': {'type': 'ephemeral'}
                    }]
                else:
                    system_message_param = None
            else:
                system_message_param = system_message
            
            # Convert OpenAI tools to Anthropic format
            anthropic_tools = None
            if tools:
                anthropic_tools = []
                for tool in tools:
                    if tool.get("type") == "function":
                        function = tool.get("function", {})
                        anthropic_tools.append({
                            "name": function.get("name", ""),
                            "description": function.get("description", ""),
                            "input_schema": function.get("parameters", {})
                        })
                        logging.info(f"AnthropicProviderHandler: Converted tool to Anthropic format: {function.get('name')}")
                if not anthropic_tools:
                    anthropic_tools = None
            
            # Convert OpenAI tool_choice to Anthropic format
            anthropic_tool_choice = None
            if tool_choice and anthropic_tools:
                if isinstance(tool_choice, str):
                    if tool_choice == "auto":
                        anthropic_tool_choice = {"type": "auto"}
                    elif tool_choice == "required":
                        anthropic_tool_choice = {"type": "any"}
                    elif tool_choice == "none":
                        anthropic_tool_choice = None
                elif isinstance(tool_choice, dict):
                    if tool_choice.get("type") == "function":
                        func_name = tool_choice.get("function", {}).get("name")
                        if func_name:
                            anthropic_tool_choice = {"type": "tool", "name": func_name}
            
            # Build API call parameters
            api_params = {
                'model': model,
                'messages': anthropic_messages,
                'max_tokens': max_tokens or 4096,
                'temperature': temperature,
            }
            
            if system_message_param:
                api_params['system'] = system_message_param
            
            if anthropic_tools:
                api_params['tools'] = anthropic_tools
            
            if anthropic_tool_choice:
                api_params['tool_choice'] = anthropic_tool_choice
            
            if AISBF_DEBUG:
                import json as _json
                logging.info(f"=== ANTHROPIC API REQUEST PAYLOAD ===")
                # Sanitize for logging (don't log full base64 images)
                debug_params = dict(api_params)
                logging.info(f"Request keys: {list(debug_params.keys())}")
                logging.info(f"Model: {debug_params.get('model')}")
                logging.info(f"Messages count: {len(debug_params.get('messages', []))}")
                logging.info(f"Tools count: {len(debug_params.get('tools', []) or [])}")
                logging.info(f"Tool choice: {debug_params.get('tool_choice')}")
                logging.info(f"System: {'present' if debug_params.get('system') else 'none'}")
                logging.info(f"Full payload: {_json.dumps(debug_params, indent=2, default=str)}")
                logging.info(f"=== END ANTHROPIC API REQUEST PAYLOAD ===")
            
            response = self.client.messages.create(**api_params)
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
                                import json as _json_tc
                                # Convert Anthropic tool_use to OpenAI tool_calls format
                                # OpenAI requires arguments to be a JSON string, not a dict
                                raw_input = block.input if hasattr(block, 'input') else {}
                                arguments_str = _json_tc.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
                                openai_tool_call = {
                                    "id": block.id if hasattr(block, 'id') else f"call_{call_id}",
                                    "type": "function",
                                    "function": {
                                        "name": block.name if hasattr(block, 'name') else "",
                                        "arguments": arguments_str
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
                    "prompt_tokens": getattr(getattr(response, "usage", None), "input_tokens", 0) or 0,
                    "completion_tokens": getattr(getattr(response, "usage", None), "output_tokens", 0) or 0,
                    "total_tokens": (getattr(getattr(response, "usage", None), "input_tokens", 0) or 0) + (getattr(getattr(response, "usage", None), "output_tokens", 0) or 0)
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
    Handler for Claude Code OAuth2 integration using Anthropic SDK.
    
    This handler uses OAuth2 authentication to access Claude models through
    the official Anthropic Python SDK. OAuth2 access tokens are passed as
    the api_key parameter to the SDK, which handles proper message formatting,
    retries, and streaming.
    
    Key benefits of using the SDK:
    - Proper message format conversion (OpenAI -> Anthropic)
    - Automatic retries with exponential backoff
    - Proper streaming event handling
    - Correct headers and beta features
    - Better error handling and rate limit management
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
        
        # HTTP client for direct API requests (OAuth2 requires direct HTTP, not SDK)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        
        # Streaming idle watchdog configuration (Phase 1.3)
        self.stream_idle_timeout = 90.0  # seconds - matches vendors/claude
        
        # Cache token tracking for analytics (Phase 2.3)
        self.cache_stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'cache_tokens_read': 0,
            'cache_tokens_created': 0,
            'total_requests': 0,
        }
        
        # Session management for quota tracking
        self.session_state = {
            'initialized': False,
            'session_id': None,
            'device_id': None,
            'account_uuid': None,
            'organization_id': None,
            'last_initialized': None,
            'quota_5h_reset': None,
            'quota_5h_utilization': None,
            'quota_7d_reset': None,
            'quota_7d_utilization': None,
            'representative_claim': None,
            'status': None,
            'session_timeout': 3600,  # 1 hour session timeout
        }
        
        # Initialize persistent identifiers for metadata
        self._init_session_identifiers()
    
    def _init_session_identifiers(self):
        """Initialize persistent session identifiers (device_id, account_uuid, session_id)."""
        import uuid
        import hashlib
        
        # Generate device_id (consistent hash based on provider_id)
        if not self.session_state.get('device_id'):
            device_seed = f"{self.provider_id}-{time.time()}"
            self.session_state['device_id'] = hashlib.sha256(device_seed.encode()).hexdigest()
        
        # Get account_uuid from OAuth2 credentials (persistent per user)
        if not self.session_state.get('account_uuid'):
            # Try to get from OAuth2 credentials first
            account_id = self.auth.get_account_id()
            if account_id:
                self.session_state['account_uuid'] = account_id
            else:
                # Fall back to UUID if not available
                self.session_state['account_uuid'] = str(uuid.uuid4())
        
        # Session ID will be generated on first use in _get_auth_headers
    
    async def _initialize_session(self):
        """
        Initialize session by sending a quota request to get rate limit information.
        
        This matches the claude-cli behavior of sending an initial "quota" request
        to obtain subscriber quota information from the API headers.
        """
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info("ClaudeProviderHandler: Initializing session for quota tracking")
        
        try:
            # Get auth headers (this will initialize session_id if needed)
            headers = self._get_auth_headers(stream=False)
            
            # Build minimal quota request (matching claude-cli)
            # Use persistent identifiers from session_state
            payload = {
                'model': 'claude-haiku-4-5-20251001',  # Use cheapest model for quota check
                'max_tokens': 1,
                'messages': [
                    {
                        'role': 'user',
                        'content': 'quota'
                    }
                ],
                'metadata': {
                    'user_id': json.dumps({
                        'device_id': self.session_state['device_id'],
                        'account_uuid': self.session_state['account_uuid'],
                        'session_id': self.session_state['session_id']
                    })
                }
            }
            
            # Send quota request
            api_url = 'https://api.anthropic.com/v1/messages?beta=true'
            response = await self.client.post(api_url, headers=headers, json=payload)
            
            if response.status_code == 200:
                # Parse rate limit headers
                headers_dict = dict(response.headers)
                
                self.session_state.update({
                    'initialized': True,
                    'last_initialized': time.time(),
                    'organization_id': headers_dict.get('anthropic-organization-id'),
                    'quota_5h_reset': headers_dict.get('anthropic-ratelimit-unified-5h-reset'),
                    'quota_5h_utilization': headers_dict.get('anthropic-ratelimit-unified-5h-utilization'),
                    'quota_7d_reset': headers_dict.get('anthropic-ratelimit-unified-7d-reset'),
                    'quota_7d_utilization': headers_dict.get('anthropic-ratelimit-unified-7d-utilization'),
                    'representative_claim': headers_dict.get('anthropic-ratelimit-unified-representative-claim'),
                    'status': headers_dict.get('anthropic-ratelimit-unified-status'),
                })
                
                logger.info(f"ClaudeProviderHandler: Session initialized successfully")
                logger.info(f"  Organization ID: {self.session_state['organization_id']}")
                logger.info(f"  5h utilization: {self.session_state['quota_5h_utilization']}")
                logger.info(f"  7d utilization: {self.session_state['quota_7d_utilization']}")
                logger.info(f"  Representative claim: {self.session_state['representative_claim']}")
                logger.info(f"  Status: {self.session_state['status']}")
                
                return True
            else:
                logger.warning(f"ClaudeProviderHandler: Session initialization failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: Session initialization error: {e}", exc_info=True)
            return False
    
    def _should_refresh_session(self) -> bool:
        """
        Check if session should be refreshed based on timeout or rate limit status.
        
        Returns:
            True if session needs refresh, False otherwise
        """
        if not self.session_state['initialized']:
            return True
        
        # Check session timeout
        if self.session_state['last_initialized']:
            age = time.time() - self.session_state['last_initialized']
            if age > self.session_state['session_timeout']:
                return True
        
        # Check if rate limited
        if self.session_state['status'] != 'allowed':
            return True
        
        return False
    
    async def _ensure_session(self):
        """
        Ensure session is initialized and valid before making requests.
        
        This is called before each request to maintain quota tracking.
        """
        if self._should_refresh_session():
            import logging
            logger = logging.getLogger(__name__)
            logger.info("ClaudeProviderHandler: Session needs refresh, initializing...")
            await self._initialize_session()
    
    def _update_session_from_headers(self, headers: Dict):
        """
        Update session state from response headers.
        
        This is called after each request to keep quota information current.
        
        Args:
            headers: Response headers dict
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Update quota information from headers
        if 'anthropic-ratelimit-unified-5h-utilization' in headers:
            old_util = self.session_state.get('quota_5h_utilization')
            new_util = headers.get('anthropic-ratelimit-unified-5h-utilization')
            
            self.session_state.update({
                'quota_5h_reset': headers.get('anthropic-ratelimit-unified-5h-reset'),
                'quota_5h_utilization': new_util,
                'quota_7d_reset': headers.get('anthropic-ratelimit-unified-7d-reset'),
                'quota_7d_utilization': headers.get('anthropic-ratelimit-unified-7d-utilization'),
                'representative_claim': headers.get('anthropic-ratelimit-unified-representative-claim'),
                'status': headers.get('anthropic-ratelimit-unified-status'),
            })
            
            if old_util != new_util:
                logger.debug(f"ClaudeProviderHandler: Quota utilization updated: {old_util} -> {new_util}")
    
    def _get_sdk_client(self):
        """
        Get or create an Anthropic SDK client configured with OAuth2 auth token.
        
        Claude Code uses the SDK with authToken parameter (not apiKey).
        See vendors/claude/src/services/api/client.ts lines 300-315:
        
            const clientConfig = {
              apiKey: isClaudeAISubscriber() ? null : apiKey || getAnthropicApiKey(),
              authToken: isClaudeAISubscriber()
                ? getClaudeAIOAuthTokens()?.accessToken
                : undefined,
            }
            return new Anthropic(clientConfig)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Get valid OAuth2 access token
        access_token = self.auth.get_valid_token()
        
        if not access_token:
            logger.error("ClaudeProviderHandler: No OAuth2 access token available")
            raise Exception("No OAuth2 access token. Please re-authenticate with /login")
        
        # Create SDK client with OAuth2 auth token (not API key)
        # This matches the Claude Code implementation exactly
        self._sdk_client = Anthropic(
            auth_token=access_token,  # OAuth2 token, not API key
            max_retries=3,  # SDK handles automatic retries
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
        
        logger.info("ClaudeProviderHandler: Created SDK client with OAuth2 auth token")
        return self._sdk_client
    
    def _get_auth_headers(self, stream: bool = False):
        """
        Get HTTP headers with OAuth2 Bearer token.
        Used for direct HTTP calls (not SDK).
        
        Headers match the original claude-cli client exactly.
        """
        import logging
        import uuid
        import platform
        logger = logging.getLogger(__name__)
        
        # Get valid OAuth2 access token
        access_token = self.auth.get_valid_token()
        
        # Use stored session ID (consistent across requests in the same session)
        # Generate new one only if not initialized
        if not self.session_state.get('session_id'):
            self.session_state['session_id'] = str(uuid.uuid4())
        
        session_id = self.session_state['session_id']
        request_id = str(uuid.uuid4())  # Request ID is unique per request
        
        # Build headers matching claude-cli implementation exactly
        # Reference: original claude code client request headers
        headers = {
            'accept': 'application/json',
            'anthropic-beta': 'oauth-2025-04-20,interleaved-thinking-2025-05-14,redact-thinking-2026-02-12,context-management-2025-06-27,prompt-caching-scope-2026-01-05,structured-outputs-2025-12-15',
            'anthropic-dangerous-direct-browser-access': 'true',
            'anthropic-version': '2023-06-01',
            'authorization': f'Bearer {access_token}',
            'content-type': 'application/json',
            'user-agent': 'claude-cli/99.0.0 (undefined, cli)',
            'x-app': 'cli',
            'x-claude-code-session-id': session_id,
            'x-client-request-id': request_id,
            'x-stainless-arch': platform.machine() or 'x64',
            'x-stainless-lang': 'js',
            'x-stainless-os': platform.system() or 'Linux',
            'x-stainless-package-version': '0.81.0',
            'x-stainless-retry-count': '0',
            'x-stainless-runtime': 'node',
            'x-stainless-runtime-version': 'v22.22.0',
            'x-stainless-timeout': '600',
        }
        
        # Override Accept and Accept-Encoding for streaming mode
        if stream:
            headers['accept'] = 'text/event-stream'
            headers['accept-encoding'] = 'identity'
        else:
            headers['accept-encoding'] = 'gzip, deflate, br, zstd'
        
        logger.info("ClaudeProviderHandler: Created auth headers matching claude-cli client")
        logger.debug(f"ClaudeProviderHandler: Session ID: {session_id}, Request ID: {request_id}")
        
        # Log full headers for debugging
        import json
        logger.debug(f"ClaudeProviderHandler: Full headers: {json.dumps(headers, indent=2)}")
        return headers
    
    def _sanitize_tool_call_id(self, tool_call_id: str) -> str:
        """
        Sanitize tool call ID for Claude API compatibility.
        
        Claude API requires tool call IDs to contain only alphanumeric characters,
        underscores, and hyphens. This replaces invalid characters with underscores.
        
        Reference: vendors/kilocode normalizeMessages() tool call ID sanitization
        
        Args:
            tool_call_id: Original tool call ID (may contain invalid chars)
            
        Returns:
            Sanitized tool call ID safe for Claude API
        """
        import re
        # Replace any character that is not alphanumeric, underscore, or hyphen
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', tool_call_id)
        return sanitized
    
    def _filter_empty_content(self, content: Union[str, List, None]) -> Union[str, List, None]:
        """
        Filter empty content from messages for Claude API compatibility.
        
        Claude API rejects messages with empty content strings or empty text
        parts in array content. This filters out empty content.
        
        Reference: vendors/kilocode normalizeMessages() empty content filtering
        
        Args:
            content: Message content (string, list of content blocks, or None)
            
        Returns:
            Filtered content, or None if all content was empty
        """
        if content is None:
            return None
        
        if isinstance(content, str):
            if content.strip() == "":
                return None
            return content
        
        if isinstance(content, list):
            # Filter out empty text parts and empty content blocks
            filtered = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get('type', '')
                    if block_type == 'text':
                        text = block.get('text', '')
                        if text and text.strip():
                            filtered.append(block)
                        # Skip empty text blocks
                    else:
                        # Keep non-text blocks (tool_use, tool_result, etc.)
                        filtered.append(block)
                else:
                    filtered.append(block)
            
            if not filtered:
                return None
            return filtered
        
        return content
    
    def _apply_cache_control(self, anthropic_messages: List[Dict], enable_caching: bool = True) -> List[Dict]:
        """
        Apply ephemeral cache_control to messages for prompt caching.
        
        Applies cache_control to system message and last 2 non-system messages
        to enable Anthropic's prompt caching feature.
        
        Reference: vendors/kilocode applyCaching()
        
        Args:
            anthropic_messages: Messages in Anthropic format
            enable_caching: Whether to enable caching (default True)
            
        Returns:
            Messages with cache_control applied
        """
        if not enable_caching or not anthropic_messages:
            return anthropic_messages
        
        import logging
        logger = logging.getLogger(__name__)
        
        # Only apply caching for conversations with enough messages
        if len(anthropic_messages) < 4:
            logger.debug(f"ClaudeProviderHandler: Skipping cache control (only {len(anthropic_messages)} messages)")
            return anthropic_messages
        
        # Find system message (if present as a separate message in the list)
        # Note: In our implementation, system is extracted separately, so we
        # apply caching to the last 2 messages in the list
        cache_indices = []
        
        # Cache the last 2 messages (these are the most recent conversation turns)
        for i in range(max(0, len(anthropic_messages) - 2), len(anthropic_messages)):
            cache_indices.append(i)
        
        # Apply cache_control to selected messages
        for idx in cache_indices:
            msg = anthropic_messages[idx]
            content = msg.get('content')
            
            if isinstance(content, str):
                # Convert string content to list with cache_control
                if content.strip():  # Only cache non-empty content
                    msg['content'] = [
                        {
                            'type': 'text',
                            'text': content,
                            'cache_control': {'type': 'ephemeral'}
                        }
                    ]
                    logger.debug(f"ClaudeProviderHandler: Applied cache_control to message {idx} (string content)")
            elif isinstance(content, list) and content:
                # Apply cache_control to the last content block
                last_block = content[-1]
                if isinstance(last_block, dict):
                    last_block['cache_control'] = {'type': 'ephemeral'}
                    logger.debug(f"ClaudeProviderHandler: Applied cache_control to message {idx} (list content)")
        
        logger.info(f"ClaudeProviderHandler: Applied cache_control to {len(cache_indices)} messages for prompt caching")
        return anthropic_messages
    
    def _validate_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Validate and normalize message roles for Claude API compatibility.
        
        Validates:
        - Message roles are one of: user, assistant, system, tool
        - System messages only appear at start
        - Alternating user/assistant roles (after system)
        - Tool messages have tool_call_id
        
        Auto-fixes:
        - Unknown roles → 'user'
        - Consecutive user messages → inserts synthetic assistant
        - Consecutive assistant messages → merges content
        
        Reference: vendors/kilocode normalizeMessages() + ensure_alternating_roles()
        
        Args:
            messages: OpenAI format messages
            
        Returns:
            Validated and normalized messages
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not messages:
            return messages
        
        valid_roles = {'user', 'assistant', 'system', 'tool'}
        normalized = []
        issues_found = 0
        
        for i, msg in enumerate(messages):
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            # Validate and normalize role
            if role not in valid_roles:
                logger.warning(f"ClaudeProviderHandler: Unknown message role '{role}' at index {i}, treating as 'user'")
                msg['role'] = 'user'
                role = 'user'
                issues_found += 1
            
            # Validate system messages only at start
            if role == 'system' and i > 0:
                logger.warning(f"ClaudeProviderHandler: System message at index {i} (not at start), converting to user")
                msg['role'] = 'user'
                role = 'user'
                issues_found += 1
            
            # Validate tool messages have tool_call_id
            if role == 'tool':
                tool_call_id = msg.get('tool_call_id') or msg.get('name')
                if not tool_call_id:
                    logger.warning(f"ClaudeProviderHandler: Tool message at index {i} missing tool_call_id, adding placeholder")
                    msg['tool_call_id'] = f"placeholder_{i}"
                    issues_found += 1
            
            # Check for consecutive same-role messages
            if normalized:
                last_role = normalized[-1].get('role', '')
                
                if role == 'user' and last_role == 'user':
                    # Insert synthetic assistant message
                    logger.debug(f"ClaudeProviderHandler: Inserting synthetic assistant message between consecutive user messages at index {i}")
                    normalized.append({
                        'role': 'assistant',
                        'content': '(empty)'
                    })
                    issues_found += 1
                
                elif role == 'assistant' and last_role == 'assistant':
                    # Merge with previous assistant message
                    logger.debug(f"ClaudeProviderHandler: Merging consecutive assistant messages at index {i}")
                    prev_content = normalized[-1].get('content', '')
                    if isinstance(prev_content, str) and isinstance(content, str):
                        normalized[-1]['content'] = f"{prev_content}\n{content}"
                    else:
                        normalized[-1]['content'] = content
                    issues_found += 1
                    continue  # Skip adding this message, already merged
            
            normalized.append(msg.copy())
        
        if issues_found:
            logger.info(f"ClaudeProviderHandler: Message validation fixed {issues_found} issue(s)")
        
        return normalized
    
    def _truncate_tool_result(self, content: str, max_chars: int = 100000) -> tuple[str, bool]:
        """
        Truncate tool result content if it exceeds the size limit.
        
        Claude API has limits on tool result sizes. This truncates oversized
        results and adds a truncation notice.
        
        Reference: vendors/claude applyToolResultBudget
        
        Args:
            content: Tool result content string
            max_chars: Maximum allowed characters (default 100000)
            
        Returns:
            Tuple of (truncated_content, was_truncated)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not content or len(content) <= max_chars:
            return content, False
        
        # Truncate and add notice
        truncation_notice = f"\n\n[Tool result truncated: exceeded {max_chars} character limit. Original length: {len(content)} characters.]"
        truncated = content[:max_chars - len(truncation_notice)] + truncation_notice
        
        logger.warning(f"ClaudeProviderHandler: Tool result truncated from {len(content)} to {max_chars} characters")
        return truncated, True
    
    def _get_cache_config(self) -> Dict:
        """
        Get prompt caching configuration from provider config.
        
        Returns:
            Dict with caching settings (enabled, min_messages, etc.)
        """
        cache_config = {
            'enabled': False,
            'min_messages': 4,  # Minimum messages before enabling cache
        }
        
        if self.provider_config:
            claude_config = getattr(self.provider_config, 'claude_config', None)
            if claude_config and isinstance(claude_config, dict):
                cache_config['enabled'] = claude_config.get('enable_prompt_caching', False)
                cache_config['min_messages'] = claude_config.get('cache_min_messages', 4)
        
        return cache_config
    
    def _get_fallback_models(self) -> List[str]:
        """
        Get list of fallback models from provider config.
        
        Returns:
            List of model IDs to try as fallbacks
        """
        fallback_models = []
        
        if self.provider_config:
            claude_config = getattr(self.provider_config, 'claude_config', None)
            if claude_config and isinstance(claude_config, dict):
                fallback_models = claude_config.get('fallback_models', [])
        
        return fallback_models
    
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
    
    def _extract_images_from_content(self, content: Union[str, List, None]) -> List[Dict]:
        """
        Extract images from OpenAI message content format.
        
        Handles OpenAI image formats:
        - {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
        - {"type": "image_url", "image_url": {"url": "https://..."}}
        
        Converts to Anthropic image source format:
        - {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}
        - {"type": "image", "source": {"type": "url", "url": "https://..."}}
        
        Args:
            content: Message content (string or list of content blocks)
            
        Returns:
            List of image content blocks in Anthropic format
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not isinstance(content, list):
            return []
        
        images = []
        max_image_size = 5 * 1024 * 1024  # 5MB limit for base64 images
        
        for block in content:
            if not isinstance(block, dict):
                continue
            
            block_type = block.get('type', '')
            
            if block_type == 'image_url':
                image_url_obj = block.get('image_url', {})
                url = image_url_obj.get('url', '') if isinstance(image_url_obj, dict) else ''
                
                if not url:
                    logger.warning("ClaudeProviderHandler: Empty image URL in content block")
                    continue
                
                if url.startswith('data:'):
                    # Handle base64 data URL
                    try:
                        # Parse data URL: data:image/jpeg;base64,/9j/4AAQ...
                        header, data = url.split(',', 1)
                        media_part = header.split(';')[0]  # "data:image/jpeg"
                        media_type = media_part.replace('data:', '')  # "image/jpeg"
                        
                        # Validate image size
                        if len(data) > max_image_size:
                            logger.warning(f"ClaudeProviderHandler: Image too large ({len(data)} bytes), skipping")
                            continue
                        
                        image_block = {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': media_type,
                                'data': data
                            }
                        }
                        images.append(image_block)
                        logger.debug(f"ClaudeProviderHandler: Extracted base64 image ({media_type}, {len(data)} bytes)")
                        
                    except (ValueError, IndexError) as e:
                        logger.warning(f"ClaudeProviderHandler: Failed to parse data URL: {e}")
                
                elif url.startswith(('http://', 'https://')):
                    # Handle URL-based image
                    image_block = {
                        'type': 'image',
                        'source': {
                            'type': 'url',
                            'url': url
                        }
                    }
                    images.append(image_block)
                    logger.debug(f"ClaudeProviderHandler: Extracted URL image: {url[:80]}...")
                
                else:
                    logger.warning(f"ClaudeProviderHandler: Unsupported image URL format: {url[:80]}...")
            
            elif block_type == 'image':
                # Already in Anthropic-like format, pass through
                if 'source' in block:
                    images.append(block)
                    logger.debug("ClaudeProviderHandler: Passed through existing image block")
        
        return images
    
    def _convert_messages_to_anthropic(self, messages: List[Dict]) -> tuple[Optional[str], List[Dict]]:
        """
        Convert OpenAI messages format to Anthropic format.
        Delegates to shared AnthropicFormatConverter.convert_messages_to_anthropic().
        """
        return AnthropicFormatConverter.convert_messages_to_anthropic(messages, sanitize_ids=True)
    
    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        # Get fallback models from config (Phase 3.3)
        fallback_models = self._get_fallback_models()
        models_to_try = [model] + fallback_models
        
        last_error = None
        
        for attempt, current_model in enumerate(models_to_try):
            try:
                if attempt > 0:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"ClaudeProviderHandler: Retrying with fallback model: {current_model} (original: {model})")
                
                result = await self._handle_request_with_model(
                    model=current_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    tools=tools,
                    tool_choice=tool_choice
                )
                
                # For streaming, we get a generator - wrap it to catch errors during consumption
                if stream:
                    return self._wrap_streaming_with_retry(result, current_model, messages, max_tokens, temperature, tools, tool_choice, models_to_try, attempt)
                
                return result
                
            except Exception as e:
                last_error = e
                import logging
                logger = logging.getLogger(__name__)
                
                # Check if we should try next fallback model
                error_str = str(e).lower()
                is_retryable = any(keyword in error_str for keyword in [
                    'rate limit', 'overloaded', 'too many requests', '429', '529', '503'
                ])
                
                if is_retryable and attempt < len(models_to_try) - 1:
                    logger.warning(f"ClaudeProviderHandler: Retryable error with {current_model}, trying next fallback model")
                    # Wait before retry with exponential backoff + jitter
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                    logger.info(f"ClaudeProviderHandler: Waiting {wait_time:.1f}s before retry")
                    await asyncio.sleep(wait_time)
                    continue
                
                # Not retryable or no more fallbacks
                logger.error(f"ClaudeProviderHandler: Error with model {current_model}: {str(e)}", exc_info=True)
                self.record_failure()
                raise e
        
        # All models failed
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"ClaudeProviderHandler: All models failed (tried: {models_to_try})")
        raise last_error
    
    async def _wrap_streaming_with_retry(self, stream_generator, current_model, messages, max_tokens, temperature, tools, tool_choice, models_to_try, attempt):
        """
        Wrapper that consumes the streaming generator and catches errors,
        allowing retry with fallback models if rate limited.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            async for chunk in stream_generator:
                yield chunk
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = any(keyword in error_str for keyword in [
                'rate limit', 'overloaded', 'too many requests', '429', '529', '503'
            ])
            
            # Check if we have more fallback models to try
            if is_retryable and attempt < len(models_to_try) - 1:
                next_model = models_to_try[attempt + 1]
                logger.warning(f"ClaudeProviderHandler: Streaming error with {current_model}, retrying with {next_model}")
                
                # Wait before retry
                wait_time = min(2 ** (attempt + 1) + random.uniform(0, 1), 30)
                logger.info(f"ClaudeProviderHandler: Waiting {wait_time:.1f}s before retry")
                await asyncio.sleep(wait_time)
                
                # Retry with next model
                try:
                    result = await self._handle_request_with_model(
                        model=next_model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stream=True,
                        tools=tools,
                        tool_choice=tool_choice
                    )
                    async for chunk in self._wrap_streaming_with_retry(result, next_model, messages, max_tokens, temperature, tools, tool_choice, models_to_try, attempt + 1):
                        yield chunk
                    return
                except Exception as retry_error:
                    logger.error(f"ClaudeProviderHandler: Retry with {next_model} also failed: {str(retry_error)}")
                    raise retry_error
            
            # No more fallbacks or not retryable
            logger.error(f"ClaudeProviderHandler: Streaming error: {str(e)}", exc_info=True)
            raise e
    
    async def _handle_request_with_model(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                                        temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                                        tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        """
        Handle request with a specific model using direct HTTP requests.
        
        OAuth2 authentication requires direct HTTP requests with Bearer token,
        as the Anthropic SDK doesn't support OAuth2 via auth_token parameter.
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        logger.info(f"ClaudeProviderHandler: Handling request for model {model} (Direct HTTP mode)")
        
        if AISBF_DEBUG:
            logger.info(f"ClaudeProviderHandler: Messages: {messages}")
        else:
            logger.info(f"ClaudeProviderHandler: Messages count: {len(messages)}")

        # Ensure session is initialized for quota tracking
        await self._ensure_session()

        # Apply rate limiting
        await self.apply_rate_limit()
        
        # Validate and normalize messages (Phase 3.1)
        validated_messages = self._validate_messages(messages)
        
        # Convert messages to Anthropic format (handles tool messages properly)
        system_message, anthropic_messages = self._convert_messages_to_anthropic(validated_messages)
        
        # Build request payload
        payload = {
            'model': model,
            'messages': anthropic_messages,
            'max_tokens': max_tokens or 4096,
        }
        
        # Only add temperature if not None and not 0.0
        if temperature is not None and temperature > 0:
            payload['temperature'] = temperature
        
        if system_message:
            # Format system message as Anthropic blocks with billing header
            # Matches claude-cli format for billing/tracking
            billing_header = {
                'type': 'text',
                'text': 'x-anthropic-billing-header: cc_version=99.0.0.e8c; cc_entrypoint=cli;'
            }
            claude_intro = {
                'type': 'text',
                'text': 'You are Claude Code, Anthropic\'s official CLI for Claude.'
            }
            user_system = {
                'type': 'text',
                'text': system_message
            }
            payload['system'] = [billing_header, claude_intro, user_system]
        
        # Add metadata with user_id (matching claude-cli format)
        payload['metadata'] = {
            'user_id': json.dumps({
                'device_id': self.session_state['device_id'],
                'account_uuid': self.session_state['account_uuid'],
                'session_id': self.session_state['session_id']
            })
        }
        
        # Convert OpenAI tools to Anthropic format
        if tools:
            anthropic_tools = self._convert_tools_to_anthropic(tools)
            if anthropic_tools:
                payload['tools'] = anthropic_tools
        
        # Convert OpenAI tool_choice format to Anthropic format
        if tool_choice and tools:
            anthropic_tool_choice = self._convert_tool_choice_to_anthropic(tool_choice)
            if anthropic_tool_choice:
                payload['tool_choice'] = anthropic_tool_choice
        
        # Get auth headers with OAuth2 Bearer token
        headers = self._get_auth_headers(stream=stream)
        
        # API endpoint
        api_url = 'https://api.anthropic.com/v1/messages?beta=true'
        
        # Log request for debugging
        logger.info(f"ClaudeProviderHandler: Request payload keys: {list(payload.keys())}")
        if AISBF_DEBUG:
            logger.info(f"ClaudeProviderHandler: Full payload: {json.dumps(payload, indent=2)}")
        
        try:
            if stream:
                # Add stream: true to payload for Anthropic API
                payload['stream'] = True
                # Streaming request using direct HTTP
                logger.info(f"ClaudeProviderHandler: Using direct HTTP streaming mode")
                return self._handle_streaming_request_with_retry(api_url, payload, headers, model)
            else:
                # Non-streaming request using direct HTTP
                logger.info(f"ClaudeProviderHandler: Using direct HTTP non-streaming mode")
                response = await self._request_with_retry(api_url, headers, payload, max_retries=3)
                
                logger.info(f"ClaudeProviderHandler: HTTP response received successfully")
                
                # Update session state from response headers
                self._update_session_from_headers(dict(response.headers))
                
                self.record_success()
                
                # Parse response
                response_data = response.json()
                
                # Dump raw response if AISBF_DEBUG is enabled
                if AISBF_DEBUG:
                    logger.info(f"=== RAW CLAUDE RESPONSE ===")
                    logger.info(f"Raw response data: {json.dumps(response_data, indent=2, default=str)}")
                    logger.info(f"=== END RAW CLAUDE RESPONSE ===")
                
                # Convert to OpenAI format
                openai_response = self._convert_to_openai_format(response_data, model)
                
                # Dump final response dict if AISBF_DEBUG is enabled
                if AISBF_DEBUG:
                    logger.info(f"=== FINAL CLAUDE RESPONSE DICT ===")
                    logger.info(f"Final response: {json.dumps(openai_response, indent=2, default=str)}")
                    logger.info(f"=== END FINAL CLAUDE RESPONSE DICT ===")
                
                return openai_response
                
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: HTTP request failed: {e}", exc_info=True)
            raise
    
    async def _request_with_retry(self, api_url: str, headers: Dict, payload: Dict, max_retries: int = 3):
        """
        Non-streaming request with automatic retry for transient errors (Phase 1.2).
        
        Retries on:
        - 429 rate limit errors (with x-should-retry: true header)
        - 529 overloaded errors
        - 503 service unavailable
        - Connection timeouts
        
        Uses exponential backoff with jitter between retries.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.client.post(api_url, headers=headers, json=payload)
                
                logger.info(f"ClaudeProviderHandler: Response status: {response.status_code} (attempt {attempt + 1}/{max_retries})")
                
                # Check for retryable errors
                if response.status_code in (429, 529, 503):
                    # Check if we should retry
                    should_retry = response.headers.get('x-should-retry', 'false').lower() == 'true'
                    
                    if should_retry or response.status_code in (529, 503):
                        if attempt < max_retries - 1:
                            # Calculate wait time with exponential backoff + jitter
                            wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                            
                            # Try to get wait time from response
                            try:
                                error_data = response.json()
                                error_message = error_data.get('error', {}).get('message', '')
                                logger.warning(f"ClaudeProviderHandler: Retryable error: {error_message}")
                            except Exception:
                                pass
                            
                            logger.info(f"ClaudeProviderHandler: Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            # Max retries exceeded, handle the error
                            try:
                                response_data = response.json()
                            except Exception:
                                response_data = response.text
                            
                            self.handle_429_error(response_data, dict(response.headers))
                            response.raise_for_status()
                
                # Check for other errors
                if response.status_code >= 400:
                    try:
                        error_body = response.json()
                        error_message = error_body.get('error', {}).get('message', 'Unknown error')
                        error_type = error_body.get('error', {}).get('type', 'unknown')
                        logger.error(f"ClaudeProviderHandler: API error response: {json.dumps(error_body, indent=2)}")
                        logger.error(f"ClaudeProviderHandler: Error type: {error_type}")
                        logger.error(f"ClaudeProviderHandler: Error message: {error_message}")
                    except Exception:
                        logger.error(f"ClaudeProviderHandler: API error response (text): {response.text}")
                    
                    response.raise_for_status()
                
                # Success
                return response
                
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                    logger.warning(f"ClaudeProviderHandler: Request timeout, retrying in {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"ClaudeProviderHandler: Request timeout after {max_retries} attempts")
                    raise
            
            except httpx.HTTPError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                    logger.warning(f"ClaudeProviderHandler: HTTP error, retrying in {wait_time:.1f}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"ClaudeProviderHandler: HTTP error after {max_retries} attempts: {e}")
                    raise
        
        # Should not reach here, but just in case
        raise last_error or Exception("Request failed after max retries")
    
    async def _handle_streaming_request_with_retry(self, api_url: str, payload: Dict, headers: Dict, model: str):
        """
        Wrapper for streaming request that catches rate limit errors at the call site.
        This ensures 429 errors are caught by the retry logic in handle_request.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            async for chunk in self._handle_streaming_request(api_url, payload, headers, model):
                yield chunk
        except Exception as e:
            error_str = str(e).lower()
            # Re-raise with rate limit keywords so outer retry logic can catch it
            if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                logger.error(f"ClaudeProviderHandler: Streaming rate limit error: {e}")
                raise Exception(f"Rate limit error: {e}")
            raise
    
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
                
                # Update session state from response headers (available at stream start)
                self._update_session_from_headers(dict(response.headers))
                
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
                        
                        # Raise a descriptive exception that includes rate limit keywords
                        # so the retry logic in handle_request can catch it
                        if response.status_code == 429:
                            raise Exception(f"Rate limit error (429): {error_type} - {error_message}")
                        else:
                            raise Exception(f"Claude API error ({response.status_code}): {error_message}")
                    except json.JSONDecodeError:
                        logger.error(f"ClaudeProviderHandler: Could not parse error response as JSON")
                        # Raise a descriptive exception for rate limits
                        if response.status_code == 429:
                            raise Exception(f"Rate limit error (429): Too Many Requests - {error_text.decode() if isinstance(error_text, bytes) else error_text}")
                        else:
                            raise Exception(f"Claude API error: {response.status_code} - {error_text.decode() if isinstance(error_text, bytes) else error_text}")
                
                # Generate completion ID and timestamps
                completion_id = f"claude-{int(time.time())}"
                created_time = int(time.time())
                
                # Track state for streaming
                first_chunk = True
                accumulated_content = ""
                accumulated_tool_calls = []
                
                # Track thinking blocks for streaming (Phase 2.1 extended)
                accumulated_thinking = ""
                thinking_signature = ""
                is_redacted_thinking = False
                
                # Process the streaming response (SSE format)
                # Track content blocks for tool call streaming (Phase 2.2)
                content_block_index = 0
                current_tool_calls = []
                
                # Streaming idle watchdog (Phase 1.3)
                last_event_time = time.time()
                idle_timeout = self.stream_idle_timeout
                
                # Track stop_reason from message_delta events
                stream_stop_reason = None
                
                async for line in response.aiter_lines():
                    # Check for idle timeout (Phase 1.3)
                    if time.time() - last_event_time > idle_timeout:
                        logger.error(f"ClaudeProviderHandler: Stream idle timeout ({idle_timeout}s)")
                        raise TimeoutError(f"Stream idle for {idle_timeout}s")
                    
                    if not line or not line.startswith('data: '):
                        continue
                    
                    # Remove 'data: ' prefix
                    data_str = line[6:]
                    
                    if data_str == '[DONE]':
                        break
                    
                    try:
                        chunk_data = json.loads(data_str)
                        
                        # Update idle watchdog (Phase 1.3)
                        last_event_time = time.time()
                        
                        # Handle different event types
                        event_type = chunk_data.get('type')
                        
                        if event_type == 'content_block_start':
                            # Track new content blocks for tool call streaming (Phase 2.2)
                            content_block = chunk_data.get('content_block', {})
                            block_type = content_block.get('type', '')
                            
                            if block_type == 'tool_use':
                                # Start of a tool use block - track for streaming
                                tool_call = {
                                    'index': content_block_index,
                                    'id': content_block.get('id', ''),
                                    'type': 'function',
                                    'function': {
                                        'name': content_block.get('name', ''),
                                        'arguments': ''
                                    }
                                }
                                current_tool_calls.append(tool_call)
                                logger.debug(f"ClaudeProviderHandler: Tool use block started: {tool_call['function']['name']}")
                            
                            elif block_type == 'thinking':
                                # Start of a thinking block - track for streaming (Phase 2.1 extended)
                                accumulated_thinking = ""
                                is_redacted_thinking = False
                                thinking_signature = ""
                                logger.debug(f"ClaudeProviderHandler: Thinking block started")
                            
                            elif block_type == 'redacted_thinking':
                                # Start of a redacted thinking block
                                accumulated_thinking = ""
                                is_redacted_thinking = True
                                thinking_signature = ""
                                logger.debug(f"ClaudeProviderHandler: Redacted thinking block started")
                            
                            content_block_index += 1
                        
                        elif event_type == 'content_block_delta':
                            delta = chunk_data.get('delta', {})
                            delta_type = delta.get('type', '')
                            
                            if delta_type == 'text_delta':
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
                            
                            elif delta_type == 'input_json_delta':
                                # Tool call argument streaming (Phase 2.2)
                                partial_json = delta.get('partial_json', '')
                                # Find the current tool call to append arguments
                                if current_tool_calls:
                                    current_tool_calls[-1]['function']['arguments'] += partial_json
                            
                            elif delta_type == 'thinking_delta':
                                # Thinking content streaming (Phase 2.1 extended)
                                thinking_text = delta.get('thinking', '')
                                accumulated_thinking += thinking_text
                                logger.debug(f"ClaudeProviderHandler: Thinking delta: {len(thinking_text)} chars")
                            
                            elif delta_type == 'signature_delta':
                                # Thinking block signature (Phase 2.1 extended)
                                signature = delta.get('signature', '')
                                thinking_signature = signature
                                logger.debug(f"ClaudeProviderHandler: Thinking signature received")
                        
                        elif event_type == 'content_block_stop':
                            # End of a content block - emit tool call if present (Phase 2.2)
                            if current_tool_calls:
                                tool_call = current_tool_calls[-1]
                                # Parse and validate the arguments
                                try:
                                    args = json.loads(tool_call['function']['arguments']) if tool_call['function']['arguments'] else {}
                                    tool_call['function']['arguments'] = json.dumps(args)
                                except json.JSONDecodeError:
                                    logger.warning(f"ClaudeProviderHandler: Invalid tool call arguments JSON")
                                    tool_call['function']['arguments'] = '{}'
                                
                                # Emit tool call in streaming format
                                tool_call_chunk = {
                                    'id': completion_id,
                                    'object': 'chat.completion.chunk',
                                    'created': created_time,
                                    'model': f'{self.provider_id}/{model}',
                                    'choices': [{
                                        'index': 0,
                                        'delta': {
                                            'tool_calls': [{
                                                'index': tool_call['index'],
                                                'id': tool_call['id'],
                                                'type': tool_call['type'],
                                                'function': tool_call['function']
                                            }]
                                        },
                                        'finish_reason': None
                                    }]
                                }
                                
                                yield f"data: {json.dumps(tool_call_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                                logger.debug(f"ClaudeProviderHandler: Emitted tool call: {tool_call['function']['name']}")
                            
                            elif accumulated_thinking:
                                # End of a thinking block - log but don't emit to client
                                # Thinking content is accumulated for the final response
                                block_type = "redacted_thinking" if is_redacted_thinking else "thinking"
                                logger.info(f"ClaudeProviderHandler: {block_type} block completed ({len(accumulated_thinking)} chars)")
                                # Reset for next thinking block
                                accumulated_thinking = ""
                                is_redacted_thinking = False
                                thinking_signature = ""
                        
                        elif event_type == 'message_delta':
                            # Handle usage metadata and stop_reason in streaming (Phase 2.3)
                            delta_data = chunk_data.get('delta', {})
                            usage = chunk_data.get('usage', {})
                            
                            # Extract stop_reason from message_delta (Anthropic sends it here)
                            stream_stop_reason = delta_data.get('stop_reason')
                            if stream_stop_reason:
                                logger.debug(f"ClaudeProviderHandler: Stream stop_reason: {stream_stop_reason}")
                            
                            if usage:
                                logger.debug(f"ClaudeProviderHandler: Streaming usage update: {usage}")
                                
                                # Track cache tokens for analytics (Phase 2.3)
                                cache_read = usage.get('cache_read_input_tokens', 0)
                                cache_creation = usage.get('cache_creation_input_tokens', 0)
                                if cache_read > 0:
                                    self.cache_stats['cache_hits'] += 1
                                    self.cache_stats['cache_tokens_read'] += cache_read
                                if cache_creation > 0:
                                    self.cache_stats['cache_misses'] += 1
                                    self.cache_stats['cache_tokens_created'] += cache_creation
                        
                        elif event_type == 'message_stop':
                            # Final chunk - map Anthropic stop_reason to OpenAI finish_reason
                            stop_reason_map = {
                                'end_turn': 'stop',
                                'max_tokens': 'length',
                                'stop_sequence': 'stop',
                                'tool_use': 'tool_calls'
                            }
                            # Use stop_reason from message_delta if available, otherwise check tool_calls
                            if stream_stop_reason:
                                finish_reason = stop_reason_map.get(stream_stop_reason, 'stop')
                            elif current_tool_calls:
                                finish_reason = 'tool_calls'
                            else:
                                finish_reason = 'stop'
                            logger.debug(f"ClaudeProviderHandler: Final finish_reason: {finish_reason}")
                            
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
        """Convert Claude API response to OpenAI format.
        
        This converts the raw Claude API response (in Anthropic format) to OpenAI chat
        completion format so it can be used seamlessly with other providers.
        
        Handles:
        - Text content blocks
        - Tool use blocks (function calls)
        - Thinking blocks (reasoning)
        - Redacted thinking blocks
        - Usage metadata including cache tokens
        - Stop reason mapping
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        logger.info(f"ClaudeProviderHandler: Converting response to OpenAI format")
        
        # Extract content
        content_text = ""
        tool_calls = []
        thinking_text = ""
        
        if 'content' in claude_response:
            for block in claude_response['content']:
                block_type = block.get('type', '')
                
                if block_type == 'text':
                    content_text += block.get('text', '')
                elif block_type == 'tool_use':
                    tool_calls.append({
                        'id': block.get('id', f"call_{len(tool_calls)}"),
                        'type': 'function',
                        'function': {
                            'name': block.get('name', ''),
                            'arguments': json.dumps(block.get('input', {}))
                        }
                    })
                elif block_type == 'thinking':
                    # Extract thinking/reasoning content (Phase 2.1)
                    thinking_text = block.get('thinking', '')
                    logger.debug(f"ClaudeProviderHandler: Extracted thinking block ({len(thinking_text)} chars)")
                elif block_type == 'redacted_thinking':
                    # Handle redacted thinking blocks
                    logger.debug(f"ClaudeProviderHandler: Found redacted_thinking block")
        
        # Map stop reason
        stop_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'tool_calls'
        }
        stop_reason = claude_response.get('stop_reason', 'end_turn')
        finish_reason = stop_reason_map.get(stop_reason, 'stop')
        
        # Extract detailed usage metadata including cache tokens (Phase 2.3)
        usage = claude_response.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cache_read_tokens = usage.get('cache_read_input_tokens', 0)
        cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
        
        # Log cache usage for analytics
        if cache_read_tokens or cache_creation_tokens:
            logger.info(f"ClaudeProviderHandler: Cache usage - read: {cache_read_tokens}, creation: {cache_creation_tokens}")
        
        # Build OpenAI-style response with extended usage metadata
        openai_response = {
            'id': f"claude-{model}-{int(time.time())}",
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{self.provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content_text if content_text else None
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                # Extended cache usage metadata (Phase 2.3)
                'prompt_tokens_details': {
                    'cached_tokens': cache_read_tokens,
                    'audio_tokens': 0
                },
                'completion_tokens_details': {
                    'reasoning_tokens': 0,
                    'audio_tokens': 0
                }
            }
        }
        
        # Add tool_calls if present
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        # Add thinking content to message if present (Phase 2.1)
        if thinking_text:
            # Store thinking in provider_options for downstream access
            openai_response['choices'][0]['message']['provider_options'] = {
                'anthropic': {
                    'thinking': thinking_text
                }
            }
            logger.debug(f"ClaudeProviderHandler: Added thinking content to response ({len(thinking_text)} chars)")
        
        return openai_response
    
    def _convert_sdk_response_to_openai(self, response, model: str) -> Dict:
        """
        Convert Anthropic SDK response object to OpenAI format.
        The SDK returns a Message object, not a dict.
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        # Build message content from SDK response
        message_content = ""
        tool_calls = []
        thinking_text = ""
        
        # SDK response has content as a list of ContentBlock objects
        for block in response.content:
            block_type = getattr(block, 'type', '')
            
            if block_type == 'text' or hasattr(block, 'text'):
                message_content += getattr(block, 'text', '')
            elif block_type == 'tool_use':
                tool_calls.append({
                    'id': getattr(block, 'id', f"call_{len(tool_calls)}"),
                    'type': 'function',
                    'function': {
                        'name': getattr(block, 'name', ''),
                        'arguments': json.dumps(getattr(block, 'input', {}))
                    }
                })
            elif block_type == 'thinking':
                thinking_text = getattr(block, 'thinking', '')
                logger.debug(f"ClaudeProviderHandler: Extracted thinking block ({len(thinking_text)} chars)")
            elif block_type == 'redacted_thinking':
                logger.debug(f"ClaudeProviderHandler: Found redacted_thinking block")
        
        # Map stop reason
        stop_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'tool_calls'
        }
        stop_reason = getattr(response, 'stop_reason', 'end_turn') or 'end_turn'
        finish_reason = stop_reason_map.get(stop_reason, 'stop')
        
        # Extract usage metadata
        usage = getattr(response, 'usage', None)
        input_tokens = getattr(usage, 'input_tokens', 0) if usage else 0
        output_tokens = getattr(usage, 'output_tokens', 0) if usage else 0
        cache_read_tokens = getattr(usage, 'cache_read_input_tokens', 0) if usage else 0
        cache_creation_tokens = getattr(usage, 'cache_creation_input_tokens', 0) if usage else 0
        
        # Log cache usage for analytics
        if cache_read_tokens or cache_creation_tokens:
            logger.info(f"ClaudeProviderHandler: Cache usage - read: {cache_read_tokens}, creation: {cache_creation_tokens}")
        
        # Build OpenAI-compatible response
        openai_response = {
            'id': getattr(response, 'id', f"claude-{model}-{int(time.time())}"),
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{self.provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': message_content if message_content else None,
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                # Extended cache usage metadata (Phase 2.3)
                'prompt_tokens_details': {
                    'cached_tokens': cache_read_tokens,
                    'audio_tokens': 0
                },
                'completion_tokens_details': {
                    'reasoning_tokens': 0,
                    'audio_tokens': 0
                }
            }
        }
        
        # Add tool_calls if present
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        # Add thinking content to message if present
        if thinking_text:
            openai_response['choices'][0]['message']['provider_options'] = {
                'anthropic': {
                    'thinking': thinking_text
                }
            }
            logger.debug(f"ClaudeProviderHandler: Added thinking content to response ({len(thinking_text)} chars)")
        
        return openai_response
    
    async def _handle_streaming_request_sdk(self, client, request_kwargs: Dict, model: str):
        """
        Handle streaming request using Anthropic SDK's async streaming API.
        
        Uses client.messages.create(..., stream=True) which returns an async iterator
        of ServerSentEvent objects. We parse these events and convert to OpenAI SSE chunks.
        """
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
        accumulated_thinking = ""
        thinking_signature = ""
        is_redacted_thinking = False
        content_block_index = 0
        current_tool_calls = []
        
        # Streaming idle watchdog
        last_event_time = time.time()
        idle_timeout = self.stream_idle_timeout
        
        try:
            # Use SDK's async streaming API - create(stream=True) returns async iterator
            stream = await client.messages.create(**request_kwargs, stream=True)
            
            async for event in stream:
                # Update idle watchdog
                last_event_time = time.time()
                
                # Check for idle timeout
                if time.time() - last_event_time > idle_timeout:
                    logger.error(f"ClaudeProviderHandler: Stream idle timeout ({idle_timeout}s)")
                    raise TimeoutError(f"Stream idle for {idle_timeout}s")
                
                # Handle different event types from SDK
                event_type = getattr(event, 'type', None)
                
                if event_type == 'content_block_start':
                    content_block = getattr(event, 'content_block', None)
                    if content_block:
                        block_type = getattr(content_block, 'type', '')
                        
                        if block_type == 'tool_use':
                            tool_call = {
                                'index': content_block_index,
                                'id': getattr(content_block, 'id', ''),
                                'type': 'function',
                                'function': {
                                    'name': getattr(content_block, 'name', ''),
                                    'arguments': ''
                                }
                            }
                            current_tool_calls.append(tool_call)
                            logger.debug(f"ClaudeProviderHandler: Tool use block started: {tool_call['function']['name']}")
                        
                        elif block_type == 'thinking':
                            accumulated_thinking = ""
                            is_redacted_thinking = False
                            thinking_signature = ""
                            logger.debug(f"ClaudeProviderHandler: Thinking block started")
                        
                        elif block_type == 'redacted_thinking':
                            accumulated_thinking = ""
                            is_redacted_thinking = True
                            thinking_signature = ""
                            logger.debug(f"ClaudeProviderHandler: Redacted thinking block started")
                        
                        content_block_index += 1
                
                elif event_type == 'content_block_delta':
                    delta = getattr(event, 'delta', None)
                    if delta:
                        delta_type = getattr(delta, 'type', '')
                        
                        if delta_type == 'text_delta':
                            text = getattr(delta, 'text', '')
                            accumulated_content += text
                            
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
                        
                        elif delta_type == 'input_json_delta':
                            partial_json = getattr(delta, 'partial_json', '')
                            if current_tool_calls:
                                current_tool_calls[-1]['function']['arguments'] += partial_json
                        
                        elif delta_type == 'thinking_delta':
                            thinking_text = getattr(delta, 'thinking', '')
                            accumulated_thinking += thinking_text
                            logger.debug(f"ClaudeProviderHandler: Thinking delta: {len(thinking_text)} chars")
                        
                        elif delta_type == 'signature_delta':
                            signature = getattr(delta, 'signature', '')
                            thinking_signature = signature
                            logger.debug(f"ClaudeProviderHandler: Thinking signature received")
                
                elif event_type == 'content_block_stop':
                    if current_tool_calls:
                        tool_call = current_tool_calls[-1]
                        try:
                            args = json.loads(tool_call['function']['arguments']) if tool_call['function']['arguments'] else {}
                            tool_call['function']['arguments'] = json.dumps(args)
                        except json.JSONDecodeError:
                            logger.warning(f"ClaudeProviderHandler: Invalid tool call arguments JSON")
                            tool_call['function']['arguments'] = '{}'
                        
                        tool_call_chunk = {
                            'id': completion_id,
                            'object': 'chat.completion.chunk',
                            'created': created_time,
                            'model': f'{self.provider_id}/{model}',
                            'choices': [{
                                'index': 0,
                                'delta': {
                                    'tool_calls': [{
                                        'index': tool_call['index'],
                                        'id': tool_call['id'],
                                        'type': tool_call['type'],
                                        'function': tool_call['function']
                                    }]
                                },
                                'finish_reason': None
                            }]
                        }
                        
                        yield f"data: {json.dumps(tool_call_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                        logger.debug(f"ClaudeProviderHandler: Emitted tool call: {tool_call['function']['name']}")
                    
                    elif accumulated_thinking:
                        block_type = "redacted_thinking" if is_redacted_thinking else "thinking"
                        logger.info(f"ClaudeProviderHandler: {block_type} block completed ({len(accumulated_thinking)} chars)")
                        accumulated_thinking = ""
                        is_redacted_thinking = False
                        thinking_signature = ""
                
                elif event_type == 'message_delta':
                    usage = getattr(event, 'usage', None)
                    if usage:
                        logger.debug(f"ClaudeProviderHandler: Streaming usage update: {usage}")
                        
                        # Track cache tokens for analytics
                        cache_read = getattr(usage, 'cache_read_input_tokens', 0)
                        cache_creation = getattr(usage, 'cache_creation_input_tokens', 0)
                        if cache_read > 0:
                            self.cache_stats['cache_hits'] += 1
                            self.cache_stats['cache_tokens_read'] += cache_read
                        if cache_creation > 0:
                            self.cache_stats['cache_misses'] += 1
                            self.cache_stats['cache_tokens_created'] += cache_creation
                
                elif event_type == 'message_stop':
                    final_chunk = {
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created_time,
                        'model': f'{self.provider_id}/{model}',
                        'choices': [{
                            'index': 0,
                            'delta': {},
                            'finish_reason': 'stop'
                        }]
                    }
                    
                    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                    yield b"data: [DONE]\n\n"
            
            logger.info(f"ClaudeProviderHandler: SDK streaming completed successfully")
            self.record_success()
            
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: SDK streaming error: {str(e)}", exc_info=True)
            raise
    
    def get_cache_stats(self) -> Dict:
        """
        Get cache usage statistics (Phase 2.3).
        
        Returns:
            Dict with cache statistics including hits, misses, and token counts.
        """
        total = self.cache_stats['cache_hits'] + self.cache_stats['cache_misses']
        hit_rate = (self.cache_stats['cache_hits'] / total * 100) if total > 0 else 0
        
        return {
            **self.cache_stats,
            'total_cache_events': total,
            'cache_hit_rate_percent': round(hit_rate, 2),
        }
    
    def get_cache_stats(self) -> Dict:
        """
        Get cache usage statistics (Phase 2.3).
        
        Returns:
            Dict with cache statistics including hits, misses, and token counts.
        """
        total = self.cache_stats['cache_hits'] + self.cache_stats['cache_misses']
        hit_rate = (self.cache_stats['cache_hits'] / total * 100) if total > 0 else 0
        
        return {
            **self.cache_stats,
            'total_cache_events': total,
            'cache_hit_rate_percent': round(hit_rate, 2),
        }
    
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
            
            # Dump final response dict if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== FINAL KIRO RESPONSE DICT ===")
                logging.info(f"Final response: {json.dumps(openai_response, indent=2, default=str)}")
                logging.info(f"=== END FINAL KIRO RESPONSE DICT ===")
            
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

class KiloProviderHandler(BaseProviderHandler):
    """
    Handler for Kilo Gateway (OpenAI-compatible with OAuth2 support).
    
    Kilo Gateway is an OpenAI-compatible API that supports OAuth2 Device Authorization
    Grant flow for authentication. This handler extends OpenAI compatibility with
    OAuth2 authentication support.
    """
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        super().__init__(provider_id, api_key)
        self.provider_config = config.get_provider(provider_id)
        
        # Get kilo-specific configuration
        kilo_config = getattr(self.provider_config, 'kilo_config', None)
        
        # Initialize OAuth2 client
        credentials_file = None
        api_base = None
        
        if kilo_config and isinstance(kilo_config, dict):
            credentials_file = kilo_config.get('credentials_file')
            api_base = kilo_config.get('api_base')
        
        from .kilo_oauth2 import KiloOAuth2
        self.oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
        
        # Use the configured endpoint, falling back to the canonical kilo.ai/api/openrouter/v1
        configured_endpoint = getattr(self.provider_config, 'endpoint', None)
        if configured_endpoint:
            # Ensure endpoint ends with /v1 for OpenAI SDK compatibility
            endpoint = configured_endpoint.rstrip('/')
            if not endpoint.endswith('/v1'):
                endpoint = endpoint + '/v1'
        else:
            endpoint = 'https://kilo.ai/api/openrouter/v1'
        
        self._kilo_endpoint = endpoint
        
        # Initialize OpenAI client (will use OAuth2 token as API key)
        self.client = OpenAI(base_url=endpoint, api_key=api_key or "placeholder")
    
    async def _ensure_authenticated(self) -> str:
        """
        Ensure user is authenticated and return valid token.
        
        Returns:
            Valid access token
            
        Raises:
            Exception: If authentication fails
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Check if we have a valid token
        token = self.oauth2.get_valid_token()
        
        if token:
            logger.info("KiloProviderHandler: Using existing OAuth2 token")
            return token
        
        # Check if API key was provided (alternative auth method)
        if self.api_key and self.api_key != "placeholder":
            logger.info("KiloProviderHandler: Using API key authentication")
            return self.api_key
        
        # Need to authenticate with OAuth2
        logger.info("KiloProviderHandler: No valid token, initiating OAuth2 flow")
        result = await self.oauth2.authenticate_with_device_flow()
        
        if result.get("type") == "success":
            token = result.get("token")
            logger.info(f"KiloProviderHandler: OAuth2 authentication successful")
            return token
        
        raise Exception("OAuth2 authentication failed")
    
    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            import json
            logging.info(f"KiloProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"KiloProviderHandler: Messages: {messages}")
                logging.info(f"KiloProviderHandler: Tools: {tools}")
            else:
                logging.info(f"KiloProviderHandler: Messages count: {len(messages)}")
                logging.info(f"KiloProviderHandler: Tools count: {len(tools) if tools else 0}")

            # Ensure we have a valid token
            token = await self._ensure_authenticated()
            
            # Update client with valid token
            self.client.api_key = token

            # Apply rate limiting
            await self.apply_rate_limit()

            # Build request parameters (same as OpenAI)
            request_params = {
                "model": model,
                "messages": [],
                "temperature": temperature,
                "stream": stream
            }
            
            # Only add max_tokens if it's not None
            if max_tokens is not None:
                request_params["max_tokens"] = max_tokens
            
            # Build messages with all fields
            for msg in messages:
                message = {"role": msg["role"]}
                
                # For tool role, tool_call_id is required
                if msg["role"] == "tool":
                    if "tool_call_id" in msg and msg["tool_call_id"] is not None:
                        message["tool_call_id"] = msg["tool_call_id"]
                    else:
                        # Skip tool messages without tool_call_id
                        logging.warning(f"Skipping tool message without tool_call_id: {msg}")
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

            # For streaming requests, use httpx async streaming directly
            # to avoid blocking the event loop with the synchronous OpenAI SDK
            if stream:
                logging.info(f"KiloProviderHandler: Using async httpx streaming mode")
                return await self._handle_streaming_request(request_params, token, model)

            # Non-streaming: use the synchronous OpenAI SDK client
            response = self.client.chat.completions.create(**request_params)
            logging.info(f"KiloProviderHandler: Response received: {response}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW KILO RESPONSE ===")
                logging.info(f"Raw response type: {type(response)}")
                logging.info(f"Raw response: {response}")
                logging.info(f"=== END RAW KILO RESPONSE ===")
            
            # Return raw response without any parsing or modification
            logging.info(f"KiloProviderHandler: Returning raw response without parsing")
            return response
        except Exception as e:
            import logging
            logging.error(f"KiloProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def _handle_streaming_request(self, request_params: Dict, token: str, model: str):
        """
        Handle streaming request to Kilo API using httpx async streaming.
        
        This method pre-validates the upstream response status BEFORE returning
        the streaming generator. This ensures that errors (404, 400, etc.) are
        raised immediately and returned as proper error responses to the client,
        rather than being swallowed after a 200 OK has already been sent.
        
        Uses direct async HTTP instead of the synchronous OpenAI SDK to avoid
        blocking the event loop and to provide better control over SSE parsing.
        
        Args:
            request_params: The OpenAI-compatible request parameters (with stream=True)
            token: The OAuth2/API key token for authentication
            model: The model name being used
            
        Returns:
            Async generator that yields OpenAI-compatible SSE chunks as bytes
            
        Raises:
            Exception: If the upstream provider returns an error response
        """
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info(f"KiloProviderHandler: Starting async streaming request to {self._kilo_endpoint}")
        
        # Build the full URL for chat completions
        api_url = f"{self._kilo_endpoint}/chat/completions"
        
        # Build headers
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
        }
        
        if AISBF_DEBUG:
            logger.info(f"=== KILO STREAMING REQUEST DETAILS ===")
            logger.info(f"URL: {api_url}")
            logger.info(f"Payload: {json.dumps(request_params, indent=2)}")
            logger.info(f"=== END KILO STREAMING REQUEST DETAILS ===")
        
        # Phase 1: Open connection and validate status BEFORE returning generator.
        # This ensures errors are raised immediately (before 200 OK is sent to client),
        # not lazily when the generator is consumed.
        streaming_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        
        try:
            request = streaming_client.build_request("POST", api_url, headers=headers, json=request_params)
            response = await streaming_client.send(request, stream=True)
            
            logger.info(f"KiloProviderHandler: Streaming response status: {response.status_code}")
            
            if response.status_code >= 400:
                error_text = await response.aread()
                await response.aclose()
                await streaming_client.aclose()
                logger.error(f"KiloProviderHandler: Streaming error response: {error_text}")
                
                try:
                    error_json = json.loads(error_text)
                    error_message = error_json.get('error', {}).get('message', 'Unknown error') if isinstance(error_json.get('error'), dict) else str(error_json.get('error', 'Unknown error'))
                except (json.JSONDecodeError, Exception):
                    error_message = error_text.decode('utf-8') if isinstance(error_text, bytes) else str(error_text)
                
                if response.status_code == 429:
                    self.handle_429_error(
                        error_json if 'error_json' in locals() else error_message,
                        dict(response.headers)
                    )
                
                self.record_failure()
                raise Exception(f"Kilo API streaming error ({response.status_code}): {error_message}")
        except Exception:
            # Ensure client is closed on any error during connection setup
            await streaming_client.aclose()
            raise
        
        # Phase 2: Connection is validated (2xx status), return the streaming generator.
        # The generator takes ownership of streaming_client and response and will close
        # them when done.
        return self._stream_kilo_response(streaming_client, response, model)
    
    async def _stream_kilo_response(self, streaming_client, response, model: str):
        """
        Yield SSE chunks from an already-validated Kilo streaming response.
        
        This generator is only called after the upstream response status has been
        verified as 2xx, so it only handles the happy path of streaming data.
        
        Takes ownership of streaming_client and response, closing them when done.
        
        Args:
            streaming_client: The httpx.AsyncClient that owns the connection
            response: The already-opened httpx streaming response (status validated)
            model: The model name being used
            
        Yields:
            OpenAI-compatible SSE chunks as bytes
        """
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        
        try:
            # Process the SSE stream line by line
            async for line in response.aiter_lines():
                if not line:
                    continue
                
                # SSE format: lines starting with "data: "
                if line.startswith('data: '):
                    data_str = line[6:]
                    
                    if data_str.strip() == '[DONE]':
                        yield b"data: [DONE]\n\n"
                        break
                    
                    try:
                        chunk_data = json.loads(data_str)
                        
                        # Pass through the chunk as-is (it's already in OpenAI format)
                        yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode('utf-8')
                        
                    except json.JSONDecodeError as e:
                        logger.warning(f"KiloProviderHandler: Failed to parse streaming chunk: {e}")
                        continue
                elif line.startswith(':'):
                    # SSE comment (keep-alive), skip
                    continue
            
            logger.info(f"KiloProviderHandler: Streaming completed successfully")
            self.record_success()
        finally:
            # Always close response and client when generator is done or on error
            await response.aclose()
            await streaming_client.aclose()

    async def get_models(self) -> List[Model]:
        try:
            import logging
            import json
            logging.info("KiloProviderHandler: Getting models list")

            # Ensure we have a valid token
            token = await self._ensure_authenticated()

            # Apply rate limiting
            await self.apply_rate_limit()

            # Use the correct Kilo models endpoint directly
            # The OpenAI SDK appends /models to the base_url (which includes /v1),
            # but Kilo's models endpoint is at the base path /models (without /v1)
            # Derive models_url from the configured endpoint by stripping /v1
            base_endpoint = self._kilo_endpoint.rstrip('/')
            if base_endpoint.endswith('/v1'):
                models_url = base_endpoint[:-3] + '/models'
            else:
                models_url = base_endpoint + '/models'
            logging.info(f"KiloProviderHandler: Fetching models from {models_url}")

            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                response = await client.get(models_url, headers=headers)

            logging.info(f"KiloProviderHandler: Models response status: {response.status_code}")

            if response.status_code != 200:
                logging.warning(f"KiloProviderHandler: Models endpoint returned {response.status_code}")
                try:
                    error_body = response.json()
                    logging.warning(f"KiloProviderHandler: Error response: {error_body}")
                except Exception:
                    logging.warning(f"KiloProviderHandler: Error response (text): {response.text[:200]}")
                response.raise_for_status()

            models_data = response.json()
            logging.info(f"KiloProviderHandler: Models received: {models_data}")

            # Parse response - expect OpenAI-compatible format with 'data' array
            models_list = models_data.get('data', []) if isinstance(models_data, dict) else models_data

            result = []
            for model_entry in models_list:
                if isinstance(model_entry, dict):
                    model_id = model_entry.get('id', '')
                    model_name = model_entry.get('name', model_id) or model_id

                    # Extract context size if available
                    context_size = (
                        model_entry.get('context_window') or
                        model_entry.get('context_length') or
                        model_entry.get('max_context_length')
                    )

                    if model_id:
                        result.append(Model(
                            id=model_id,
                            name=model_name,
                            provider_id=self.provider_id,
                            context_size=context_size,
                            context_length=context_size
                        ))
                elif hasattr(model_entry, 'id'):
                    # Handle OpenAI SDK model objects (fallback)
                    context_size = None
                    if hasattr(model_entry, 'context_window') and model_entry.context_window:
                        context_size = model_entry.context_window
                    elif hasattr(model_entry, 'context_length') and model_entry.context_length:
                        context_size = model_entry.context_length

                    result.append(Model(
                        id=model_entry.id,
                        name=model_entry.id,
                        provider_id=self.provider_id,
                        context_size=context_size,
                        context_length=context_size
                    ))

            logging.info(f"KiloProviderHandler: Parsed {len(result)} models")
            return result
        except Exception as e:
            import logging
            logging.error(f"KiloProviderHandler: Error getting models: {str(e)}", exc_info=True)
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
    'claude': ClaudeProviderHandler,
    'kilo': KiloProviderHandler,
    'kilocode': KiloProviderHandler  # Kilocode provider with OAuth2 support
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
