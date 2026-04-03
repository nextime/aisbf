"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

OpenAI provider handler.

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
import time
from typing import Dict, List, Optional, Union
from openai import OpenAI
from ..models import Model
from ..config import config
from ..utils import count_messages_tokens
from .base import BaseProviderHandler, AISBF_DEBUG


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
                            logging.warning(f"Skipping tool message without tool_call_id: {msg}")
                            continue
                    
                    if "content" in msg and msg["content"] is not None:
                        message["content"] = msg["content"]
                    if "tool_calls" in msg and msg["tool_calls"] is not None:
                        message["tool_calls"] = msg["tool_calls"]
                    if "name" in msg and msg["name"] is not None:
                        message["name"] = msg["name"]
                    
                    # Apply cache_control based on position and token count
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
