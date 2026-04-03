"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Base provider handler and shared utilities for all provider implementations.

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
"""
import asyncio
import time
import os
import random
from typing import Dict, List, Optional, Union
from ..models import Provider, Model, ErrorTracking
from ..config import config
from ..utils import count_messages_tokens
from ..database import get_database
from ..batching import get_request_batcher

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
        """
        import logging
        from ..config import config
        
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
