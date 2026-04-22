"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Request handlers for AISBF.

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

Request handlers for AISBF.
"""
import asyncio
import re
import uuid
import hashlib
import time as time_module
from typing import Dict, List, Optional, Union
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse
from .providers import get_provider_handler
from .config import config
from .utils import (
    count_messages_tokens,
    split_messages_into_chunks,
    get_max_request_tokens_for_model
)
from .context import ContextManager, get_context_config_for_model
from .classifier import content_classifier
from .classifier import SemanticClassifier
from .cache import get_response_cache
import time as time_module
from .analytics import get_analytics
from .streaming_optimization import (
    get_streaming_optimizer,
    StreamingConfig,
    calculate_google_delta,
    KiroSSEParser,
    OptimizedTextAccumulator,
    optimize_sse_chunk
)


def generate_system_fingerprint(provider_id: str, seed: Optional[int] = None) -> str:
    """
    Generate a unique system_fingerprint for OpenAI-compatible responses.
    
    The fingerprint is:
    - Unique per provider (based on provider_id)
    - Different for every request if seed is present in the request
    - Consistent for the same provider_id + seed combination
    
    Args:
        provider_id: The provider identifier from configuration
        seed: Optional seed from the request (if present, generates unique fingerprint per request)
    
    Returns:
        A fingerprint string in format "fp_<hash>"
    """
    if seed is not None:
        # If seed is provided, generate a unique fingerprint for this specific request
        # Combine provider_id, seed, and a timestamp component for uniqueness
        unique_data = f"{provider_id}:{seed}:{uuid.uuid4()}"
        hash_value = hashlib.md5(unique_data.encode()).hexdigest()[:24]
    else:
        # Without seed, generate a consistent fingerprint per provider
        # This is still unique per provider but consistent across requests
        unique_data = f"{provider_id}:aisbf:fingerprint"
        hash_value = hashlib.md5(unique_data.encode()).hexdigest()[:24]
    
    return f"fp_{hash_value}"

class RequestHandler:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.config = config
        # Load user-specific configs if user_id is provided
        if user_id:
            self._load_user_configs()
        else:
            self.user_providers = {}
            self.user_rotations = {}
            self.user_autoselects = {}

    def _load_user_configs(self):
        """Load user-specific configurations from database"""
        self.reload_user_config()

    def reload_user_config(self):
        """Reload user configuration from database"""
        import logging
        logger = logging.getLogger(__name__)
        from .database import DatabaseRegistry
        db = DatabaseRegistry.get_config_database()
        
        # Convert list to dictionary with id as key
        providers = db.get_user_providers(self.user_id)
        self.user_providers = {p['provider_id']: p['config'] for p in providers}
        
        rotations = db.get_user_rotations(self.user_id)
        self.user_rotations = {r['rotation_id']: r['config'] for r in rotations}
        
        autoselects = db.get_user_autoselects(self.user_id)
        self.user_autoselects = {a['autoselect_id']: a['config'] for a in autoselects}
        
        logger.info(f"Reloaded user configuration for user_id={self.user_id}")
        logger.info(f"  Loaded {len(self.user_providers)} user providers")
        logger.info(f"  Loaded {len(self.user_rotations)} user rotations")
        logger.info(f"  Loaded {len(self.user_autoselects)} user autoselects")

    def _should_cache_response(self, provider_config=None, model_config=None, rotation_config=None, autoselect_config=None):
        """
        Determine if response caching should be enabled based on configuration hierarchy.
        
        Priority order (highest to lowest):
        1. Model-level enable_response_cache setting
        2. Provider-level enable_response_cache setting
        3. Rotation-level enable_response_cache setting
        4. Autoselect-level enable_response_cache setting
        5. Global response_cache.enabled setting
        
        Args:
            provider_config: Provider configuration object
            model_config: Model configuration object or dict
            rotation_config: Rotation configuration object
            autoselect_config: Autoselect configuration object
            
        Returns:
            bool: True if caching should be enabled, False otherwise
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Check model-level setting (highest priority)
        if model_config:
            model_cache_setting = None
            if isinstance(model_config, dict):
                model_cache_setting = model_config.get('enable_response_cache')
            else:
                model_cache_setting = getattr(model_config, 'enable_response_cache', None)
            
            if model_cache_setting is not None:
                logger.debug(f"Using model-level cache setting: {model_cache_setting}")
                return model_cache_setting
        
        # Check provider-level setting
        if provider_config:
            provider_cache_setting = getattr(provider_config, 'enable_response_cache', None)
            if provider_cache_setting is not None:
                logger.debug(f"Using provider-level cache setting: {provider_cache_setting}")
                return provider_cache_setting
        
        # Check rotation-level setting
        if rotation_config:
            rotation_cache_setting = getattr(rotation_config, 'enable_response_cache', None)
            if rotation_cache_setting is not None:
                logger.debug(f"Using rotation-level cache setting: {rotation_cache_setting}")
                return rotation_cache_setting
        
        # Check autoselect-level setting
        if autoselect_config:
            autoselect_cache_setting = getattr(autoselect_config, 'enable_response_cache', None)
            if autoselect_cache_setting is not None:
                logger.debug(f"Using autoselect-level cache setting: {autoselect_cache_setting}")
                return autoselect_cache_setting
        
        # Fall back to global setting
        aisbf_config = self.config.get_aisbf_config()
        if aisbf_config and aisbf_config.response_cache:
            global_setting = aisbf_config.response_cache.enabled
            logger.debug(f"Using global cache setting: {global_setting}")
            return global_setting
        
        # Default to False if no configuration found
        logger.debug("No cache configuration found, defaulting to False")
        return False

    async def _handle_chunked_request(
        self,
        handler,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int],
        temperature: float,
        stream: bool,
        tools: Optional[List[Dict]],
        tool_choice: Optional[Union[str, Dict]],
        max_request_tokens: int,
        provider_id: str,
        logger
    ) -> Dict:
        """
        Handle a request that needs to be split into multiple chunks due to token limits.
        
        This method splits the request into chunks, sends each chunk sequentially,
        and combines the responses into a single response.
        
        Args:
            handler: The provider handler
            model: The model name
            messages: The messages to send
            max_tokens: Max output tokens
            temperature: Temperature setting
            stream: Whether to stream (not supported for chunked requests)
            tools: Tool definitions
            tool_choice: Tool choice setting
            max_request_tokens: Maximum tokens per request
            provider_id: Provider identifier
            logger: Logger instance
        
        Returns:
            Combined response from all chunks
        """
        import time
        
        logger.info(f"=== CHUNKED REQUEST HANDLING START ===")
        logger.info(f"Max request tokens per chunk: {max_request_tokens}")
        
        # Split messages into chunks
        message_chunks = split_messages_into_chunks(messages, max_request_tokens, model)
        logger.info(f"Split into {len(message_chunks)} message chunks")
        
        if stream:
            logger.warning("Streaming is not supported for chunked requests, falling back to non-streaming")
        
        # Process each chunk and collect responses
        all_responses = []
        combined_content = ""
        total_prompt_tokens = 0
        total_completion_tokens = 0
        created_time = int(time_module.time())
        response_id = f"chunked-{provider_id}-{model}-{created_time}"
        
        for chunk_idx, chunk_messages in enumerate(message_chunks):
            logger.info(f"Processing chunk {chunk_idx + 1}/{len(message_chunks)}")
            logger.info(f"Chunk messages count: {len(chunk_messages)}")
            
            # Apply rate limiting between chunks
            if chunk_idx > 0:
                await handler.apply_rate_limit()
            
            try:
                chunk_response = await handler.handle_request(
                    model=model,
                    messages=chunk_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=False,  # Always non-streaming for chunked requests
                    tools=tools if chunk_idx == 0 else None,  # Only first chunk uses tools
                    tool_choice=tool_choice if chunk_idx == 0 else None
                )
                
                # Extract content from response
                if isinstance(chunk_response, dict):
                    choices = chunk_response.get('choices', [])
                    if choices:
                        content = choices[0].get('message', {}).get('content', '')
                        combined_content += content
                        
                        # Accumulate token usage
                        usage = chunk_response.get('usage', {})
                        total_prompt_tokens += usage.get('prompt_tokens', 0)
                        total_completion_tokens += usage.get('completion_tokens', 0)
                
                all_responses.append(chunk_response)
                logger.info(f"Chunk {chunk_idx + 1} processed successfully")
                
            except Exception as e:
                logger.error(f"Error processing chunk {chunk_idx + 1}: {e}")
                # If a chunk fails, we still try to return what we have
                if all_responses:
                    logger.warning("Returning partial results from successful chunks")
                    break
                else:
                    raise e
        
        # Build combined response
        combined_response = {
            "id": response_id,
            "object": "chat.completion",
            "created": created_time,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": combined_content
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens
            },
            "aisbf_chunked": True,
            "aisbf_total_chunks": len(message_chunks)
        }
        
        logger.info(f"=== CHUNKED REQUEST HANDLING END ===")
        logger.info(f"Combined content length: {len(combined_content)} characters")
        logger.info(f"Total chunks processed: {len(all_responses)}")
        
        return combined_response

    async def handle_chat_completion(self, request: Request, provider_id: str, request_data: Dict) -> Dict:
        import logging
        import time
        logger = logging.getLogger(__name__)
        logger.info(f"=== RequestHandler.handle_chat_completion START ===")
        logger.info(f"Provider ID: {provider_id}")
        logger.info(f"User ID: {self.user_id}")
        logger.info(f"Request data: {request_data}")
        
        # Track request start time for analytics
        request_start_time = time.time()
        model_name = request_data.get('model', 'unknown')

        # Check for user-specific provider config first
        if self.user_id and provider_id in self.user_providers:
            provider_config = self.user_providers[provider_id]
            logger.info(f"Using user-specific provider config for {provider_id}")
        else:
            provider_config = self.config.get_provider(provider_id)
            logger.info(f"Using global provider config for {provider_id}")

        # Check response cache for non-streaming requests
        stream = request_data.get('stream', False)
        if not stream:
            try:
                aisbf_config = self.config.get_aisbf_config()
                if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                    response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                    cached_response = response_cache.get(request_data, user_id=self.user_id)
                    if cached_response:
                        logger.info(f"Cache hit for request to provider {provider_id}")
                        return cached_response
                    else:
                        logger.debug(f"Cache miss for request to provider {provider_id}")
            except Exception as cache_error:
                logger.warning(f"Response cache check failed: {cache_error}")

        logger.info(f"Provider config: {provider_config}")
        # Handle both dict (user providers) and object (global providers) formats
        if isinstance(provider_config, dict):
            provider_type = provider_config.get('type')
            provider_endpoint = provider_config.get('endpoint')
            api_key_required = provider_config.get('api_key_required', False)
        else:
            provider_type = provider_config.type
            provider_endpoint = provider_config.endpoint
            api_key_required = provider_config.api_key_required
            
        logger.info(f"Provider type: {provider_type}")
        logger.info(f"Provider endpoint: {provider_endpoint}")
        logger.info(f"API key required: {api_key_required}")

        if api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            logger.info(f"API key from request: {'***' if api_key else 'None'}")
            if not api_key:
                # Record analytics for authentication failure
                try:
                    analytics = get_analytics()
                    # Calculate latency for auth failure
                    latency_ms = (time.time() - request_start_time) * 1000
                    
                    # Estimate tokens for the request
                    try:
                        messages = request_data.get('messages', [])
                        model_name = request_data.get('model', 'unknown')
                        estimated_tokens = count_messages_tokens(messages, model_name)
                    except Exception:
                        estimated_tokens = 50
                    
                    analytics.record_request(
                        provider_id=provider_id,
                        model_name=request_data.get('model', 'unknown'),
                        tokens_used=estimated_tokens,
                        latency_ms=latency_ms,
                        success=False,
                        error_type='AuthenticationError',
                        user_id=getattr(request.state, 'user_id', None),
                        token_id=getattr(request.state, 'token_id', None),
                        prompt_tokens=estimated_tokens,
                        completion_tokens=0,
                        actual_cost=None
                    )
                except Exception as analytics_error:
                    logger.warning(f"Analytics recording for auth failure failed: {analytics_error}")
                
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
            logger.info("No API key required for this provider")

        logger.info(f"Getting provider handler for {provider_id}")
        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
        logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")

        try:
            model = request_data.get('model')
            messages = request_data.get('messages', [])
            
            logger.info(f"Model requested: {model}")
            logger.info(f"Messages count: {len(messages)}")
            logger.info(f"Max tokens: {request_data.get('max_tokens')}")
            logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
            logger.info(f"Stream: {request_data.get('stream', False)}")
            
            # Get context configuration
            context_config = get_context_config_for_model(
                model_name=model,
                provider_config=provider_config,
                rotation_model_config=None
            )
            logger.info(f"Context config: {context_config}")
            
            # Check for max_request_tokens in provider config
            max_request_tokens = get_max_request_tokens_for_model(
                model_name=model,
                provider_config=provider_config,
                rotation_model_config=None
            )
            
            # Calculate effective context (total tokens used)
            effective_context = count_messages_tokens(messages, model)
            logger.info(f"Effective context: {effective_context} tokens")
            
            # Apply context condensation if needed
            if context_config.get('condense_context', 0) > 0:
                context_manager = ContextManager(context_config, handler, self.config.get_condensation(), self.user_id)
                if context_manager.should_condense(messages, model):
                    logger.info("Context condensation triggered")
                    messages = await context_manager.condense_context(messages, model)
                    effective_context = count_messages_tokens(messages, model)
                    logger.info(f"Condensed effective context: {effective_context} tokens")
            
            if max_request_tokens:
                # Count tokens in the request
                request_tokens = count_messages_tokens(messages, model)
                logger.info(f"Request tokens: {request_tokens}, max_request_tokens: {max_request_tokens}")
                
                if request_tokens > max_request_tokens:
                    logger.info(f"Request exceeds max_request_tokens, will split into chunks")
                    
                    # Apply rate limiting
                    logger.info("Applying rate limiting...")
                    await handler.apply_rate_limit()
                    logger.info("Rate limiting applied")
                    
                    # Handle as chunked request
                    response = await self._handle_chunked_request(
                        handler=handler,
                        model=model,
                        messages=messages,
                        max_tokens=request_data.get('max_tokens'),
                        temperature=request_data.get('temperature', 1.0),
                        stream=request_data.get('stream', False),
                        tools=request_data.get('tools'),
                        tool_choice=request_data.get('tool_choice'),
                        max_request_tokens=max_request_tokens,
                        provider_id=provider_id,
                        logger=logger
                    )
                    
                    handler.record_success()
                    
                    # Cache the response for non-streaming chunked requests
                    if not stream:
                        try:
                            aisbf_config = self.config.get_aisbf_config()
                            if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                                response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                                response_cache.set(request_data, response, user_id=self.user_id)
                                logger.debug(f"Cached chunked response for request to provider {provider_id}")
                        except Exception as cache_error:
                            logger.warning(f"Response cache set failed for chunked request: {cache_error}")
                    
                    logger.info(f"=== RequestHandler.handle_chat_completion END ===")
                    return response
            
            # Apply rate limiting
            logger.info("Applying rate limiting...")
            await handler.apply_rate_limit()
            await handler.apply_rate_limit()
            logger.info("Rate limiting applied")

            logger.info(f"Sending request to provider handler...")
            response = await handler.handle_request(
                model=model,
                messages=messages,
                max_tokens=request_data.get('max_tokens'),
                temperature=request_data.get('temperature', 1.0),
                stream=request_data.get('stream', False),
                tools=request_data.get('tools'),
                tool_choice=request_data.get('tool_choice')
            )
            logger.info(f"Response received from provider")
            logger.info(f"Response type: {type(response)}")
            logger.info(f"Response: {response}")
            
            # Add effective context to response for non-streaming
            if isinstance(response, dict) and 'usage' in response:
                response['usage']['effective_context'] = effective_context
                logger.info(f"Added effective_context to response: {effective_context}")
            
            # For OpenAI-compatible providers, the response is already a response object
            # Just return it as-is without any parsing or modification
            
            # Cache the response for non-streaming requests
            if not stream:
                try:
                    aisbf_config = self.config.get_aisbf_config()
                    if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                        response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                        response_cache.set(request_data, response, user_id=self.user_id)
                        logger.debug(f"Cached response for request to provider {provider_id}")
                except Exception as cache_error:
                    logger.warning(f"Response cache set failed: {cache_error}")
            
            handler.record_success()
            
            # Record analytics for token usage
            try:
                analytics = get_analytics()
                latency_ms = (time.time() - request_start_time) * 1000
                logger.info(f"Analytics: latency_ms={latency_ms:.2f}, request_start_time={request_start_time}, current_time={time.time()}")
                
                if response:
                    # Handle both dict responses and OpenAI objects
                    usage = None
                    if isinstance(response, dict):
                        # Dict response (traditional API format)
                        usage = response.get('usage', {})
                        total_tokens = usage.get('total_tokens', 0)
                        prompt_tokens = usage.get('prompt_tokens', 0)
                        completion_tokens = usage.get('completion_tokens', 0)
                    elif hasattr(response, 'usage') and response.usage:
                        # OpenAI/Pydantic object with usage attribute
                        usage = response.usage
                        total_tokens = getattr(usage, 'total_tokens', 0)
                        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                        completion_tokens = getattr(usage, 'completion_tokens', 0)
                        logger.debug(f"Extracted usage from OpenAI object: total={total_tokens}, prompt={prompt_tokens}, completion={completion_tokens}")
                    
                     # Try to extract actual cost from provider response
                    try:
                        from .cost_extractor import extract_cost_from_response
                        actual_cost = extract_cost_from_response(response, provider_id)
                    except ImportError:
                        actual_cost = None
                    
                    # Calculate estimated cost and log breakdown
                    try:
                        estimated_cost = analytics.estimate_cost(provider_id, total_tokens, prompt_tokens, completion_tokens)
                        logger.info(f"💰 Cost calculation breakdown for {provider_id}:")
                        logger.info(f"  Tokens: total={total_tokens}, prompt={prompt_tokens}, completion={completion_tokens}")
                        logger.info(f"  Estimated cost: ${estimated_cost:.8f} USD")
                        if actual_cost is not None:
                            logger.info(f"  Actual cost: ${actual_cost:.8f} USD")
                    except Exception as cost_error:
                        logger.debug(f"Cost calculation failed: {cost_error}")
                        estimated_cost = 0.0
                    
                    # If no token usage provided, estimate it with improved accuracy
                    if total_tokens == 0:
                        try:
                            messages = request_data.get('messages', [])
                            estimated_prompt_tokens = count_messages_tokens(messages, model_name)
                            
                            # Count actual completion tokens from response instead of estimating
                            response_content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
                            if response_content:
                                completion_tokens = count_messages_tokens([{
                                    "role": "assistant",
                                    "content": response_content
                                }], model_name)
                            else:
                                # Fallback to estimation if no content
                                max_tokens = request_data.get('max_tokens', 0)
                                if max_tokens > 0:
                                    completion_tokens = min(max_tokens, estimated_prompt_tokens * 2)
                                else:
                                    completion_tokens = max(estimated_prompt_tokens, 50)
                            
                            total_tokens = estimated_prompt_tokens + completion_tokens
                            prompt_tokens = estimated_prompt_tokens
                            logger.debug(f"Counted token usage: {total_tokens} (prompt: {estimated_prompt_tokens}, completion: {completion_tokens})")
                        except Exception as est_error:
                            logger.debug(f"Token counting failed: {est_error}")
                            # Use a more realistic default if counting fails
                            total_tokens = 150
                            prompt_tokens = 0
                            completion_tokens = 0
                    
                    # Always record analytics, even with estimated tokens
                    analytics.record_request(
                        provider_id=provider_id,
                        model_name=model_name,
                        tokens_used=total_tokens,
                        latency_ms=latency_ms,
                        success=True,
                        user_id=getattr(request.state, 'user_id', None),
                        token_id=getattr(request.state, 'token_id', None),
                        prompt_tokens=prompt_tokens if prompt_tokens > 0 else None,
                        completion_tokens=completion_tokens if completion_tokens > 0 else None,
                        actual_cost=actual_cost
                    )
                    
                    # Record context dimensions for model performance tracking
                    try:
                        from aisbf.database import DatabaseRegistry
                        db = DatabaseRegistry.get_config_database()
                        context_config = context_config or {}
                        db.record_context_dimension(
                            provider_id=provider_id,
                            model_name=model_name,
                            context_size=context_config.get('context_size'),
                            condense_context=context_config.get('condense_context'),
                            condense_method=context_config.get('condense_method')
                        )
                    except Exception as context_error:
                        logger.debug(f"Context dimension recording failed: {context_error}")
            except Exception as analytics_error:
                logger.warning(f"Analytics recording failed: {analytics_error}")
            
            logger.info(f"=== RequestHandler.handle_chat_completion END ===")
            return response
        except Exception as e:
            handler.record_failure()
            
            # Record failed request analytics
            try:
                analytics = get_analytics()
                latency_ms = (time.time() - request_start_time) * 1000
                
                # Estimate tokens for failed request
                try:
                    messages = request_data.get('messages', [])
                    estimated_tokens = count_messages_tokens(messages, model_name)
                    total_tokens = estimated_tokens
                    prompt_tokens = estimated_tokens
                    completion_tokens = 0  # No completion for failed requests
                except Exception:
                    total_tokens = 50  # Minimal estimate for failed requests
                    prompt_tokens = 50
                    completion_tokens = 0
                
                analytics.record_request(
                    provider_id=provider_id,
                    model_name=model_name,
                    tokens_used=total_tokens,
                    latency_ms=latency_ms,
                    success=False,
                    error_type=type(e).__name__,
                    user_id=getattr(request.state, 'user_id', None),
                    token_id=getattr(request.state, 'token_id', None),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    actual_cost=None
                )
            except Exception as analytics_error:
                logger.warning(f"Analytics recording for failed request failed: {analytics_error}")
            
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_streaming_chat_completion(self, request: Request, provider_id: str, request_data: Dict):
        # Check for user-specific provider config first
        if self.user_id and provider_id in self.user_providers:
            provider_config = self.user_providers[provider_id]
        else:
            provider_config = self.config.get_provider(provider_id)

        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None

        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")

        # Generate system_fingerprint for this request
        # If seed is present in request, generate unique fingerprint per request
        seed = request_data.get('seed')
        system_fingerprint = generate_system_fingerprint(provider_id, seed)
        
        # Get context configuration and calculate effective context
        model = request_data.get('model')
        messages = request_data.get('messages', [])
        
        context_config = get_context_config_for_model(
            model_name=model,
            provider_config=provider_config,
            rotation_model_config=None
        )
        
        effective_context = count_messages_tokens(messages, model)
        
        # Apply context condensation if needed
        if context_config.get('condense_context', 0) > 0:
            context_manager = ContextManager(context_config, handler, self.config.get_condensation())
            if context_manager.should_condense(messages, model):
                import logging
                logger = logging.getLogger(__name__)
                logger.info("Context condensation triggered for streaming request")
                messages = await context_manager.condense_context(messages, model)
                effective_context = count_messages_tokens(messages, model)
                logger.info(f"Condensed effective context: {effective_context} tokens")
        
        # Update request_data with condensed messages
        request_data['messages'] = messages

        # Initialize streaming optimizer for this request
        stream_config = StreamingConfig(
            enable_chunk_pooling=True,
            max_pooled_chunks=20,
            chunk_reuse_enabled=True,
            enable_backpressure=True,
            max_pending_chunks=15,
            google_delta_calculation=True,
            kiro_sse_optimization=True
        )
        optimizer = get_streaming_optimizer(stream_config)

        async def stream_generator(effective_context):
            import logging
            import time
            import json
            logger = logging.getLogger(__name__)
            # Track request start time for latency calculation
            request_start_time = time.time()
            try:
                # Apply rate limiting
                await handler.apply_rate_limit()

                response = await handler.handle_request(
                    model=request_data['model'],
                    messages=request_data['messages'],
                    max_tokens=request_data.get('max_tokens'),
                    temperature=request_data.get('temperature', 1.0),
                    stream=True,
                    tools=request_data.get('tools'),
                    tool_choice=request_data.get('tool_choice')
                )
                
                # Check if this is a Google streaming response by checking provider type from config
                # This is more reliable than checking response iterability which can cause false positives
                is_google_stream = provider_config.type == 'google'
                is_kiro_stream = provider_config.type == 'kiro'
                is_kilo_stream = provider_config.type in ('kilo', 'kilocode')
                logger.info(f"Is Google streaming response: {is_google_stream} (provider type: {provider_config.type})")
                logger.info(f"Is Kiro streaming response: {is_kiro_stream} (provider type: {provider_config.type})")
                logger.info(f"Is Kilo streaming response: {is_kilo_stream} (provider type: {provider_config.type})")

                if is_kilo_stream:
                    # Handle Kilo/KiloCode streaming response
                    # Kilo returns an async generator that yields OpenAI-compatible SSE bytes directly
                    # We parse these and pass through with minimal processing
                    
                    accumulated_response_text = ""  # Track full response for token counting
                    chunk_count = 0
                    tool_calls_from_stream = []  # Track tool calls from stream

                    async for chunk in response:
                        chunk_count += 1
                        try:
                            logger.debug(f"Kilo chunk type: {type(chunk)}")

                            # Parse SSE chunk to extract JSON data
                            chunk_data = None
                            
                            if isinstance(chunk, bytes):
                                try:
                                    chunk_str = chunk.decode('utf-8')
                                    # May contain multiple SSE lines
                                    for sse_line in chunk_str.split('\n'):
                                        sse_line = sse_line.strip()
                                        if sse_line.startswith('data: '):
                                            data_str = sse_line[6:].strip()
                                            if data_str and data_str != '[DONE]':
                                                try:
                                                    chunk_data = json.loads(data_str)
                                                except json.JSONDecodeError:
                                                    pass
                                except (UnicodeDecodeError, Exception) as e:
                                    logger.warning(f"Failed to parse Kilo bytes chunk: {e}")
                            elif isinstance(chunk, str):
                                if chunk.startswith('data: '):
                                    data_str = chunk[6:].strip()
                                    if data_str and data_str != '[DONE]':
                                        try:
                                            chunk_data = json.loads(data_str)
                                        except json.JSONDecodeError:
                                            pass
                            
                            if chunk_data:
                                # Extract content and tool calls from chunk
                                choices = chunk_data.get('choices', [])
                                if choices:
                                    delta = choices[0].get('delta', {})
                                    
                                    # Track content
                                    delta_content = delta.get('content', '')
                                    if delta_content:
                                        accumulated_response_text += delta_content
                                    
                                    # Track tool calls
                                    delta_tool_calls = delta.get('tool_calls', [])
                                    if delta_tool_calls:
                                        for tc in delta_tool_calls:
                                            tool_calls_from_stream.append(tc)
                            
                            # Pass through the chunk as-is
                            if isinstance(chunk, bytes):
                                yield chunk
                            elif isinstance(chunk, str):
                                yield chunk.encode('utf-8')
                            else:
                                yield f"data: {json.dumps(chunk)}\n\n".encode('utf-8')

                        except Exception as chunk_error:
                            logger.warning(f"Error processing Kilo chunk: {chunk_error}")
                            continue

                    logger.info(f"Kilo streaming processed {chunk_count} chunks total")

                elif is_kiro_stream:
                    # Handle Kiro streaming response
                    # Kiro returns an async generator that yields OpenAI-compatible SSE strings directly
                    # We need to parse these and handle tool calls properly
                    
                    # Use optimized SSE parser for Kiro
                    if stream_config.kiro_sse_optimization:
                        kiro_parser = KiroSSEParser(buffer_size=stream_config.kiro_buffer_size)
                    else:
                        kiro_parser = None
                    
                    accumulated_response_text = ""  # Track full response for token counting
                    chunk_count = 0
                    tool_calls_from_stream = []  # Track tool calls from stream
                    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                    created_time = int(time.time())

                    # Use optimized text accumulator for Kiro
                    kiro_text_accumulator = OptimizedTextAccumulator(
                        max_size=stream_config.max_accumulated_text,
                        enable_truncation=stream_config.enable_text_truncation
                    )

                    async for chunk in response:
                        chunk_count += 1
                        try:
                            logger.debug(f"Kiro chunk type: {type(chunk)}")
                            logger.debug(f"Kiro chunk: {chunk}")

                            # Parse SSE chunk to extract JSON data
                            chunk_data = None
                            
                            if kiro_parser and isinstance(chunk, bytes):
                                # Use optimized parser
                                events = kiro_parser.feed(chunk)
                                for event in events:
                                    if event.get('type') == 'data':
                                        chunk_data = event.get('data')
                                        break
                            elif isinstance(chunk, str) and chunk.startswith('data: '):
                                data_str = chunk[6:].strip()  # Remove 'data: ' prefix
                                if data_str and data_str != '[DONE]':
                                    try:
                                        chunk_data = json.loads(data_str)
                                    except json.JSONDecodeError:
                                        logger.warning(f"Failed to parse Kiro chunk JSON: {data_str}")
                                        continue
                            elif isinstance(chunk, bytes):
                                # Try to decode bytes as SSE
                                try:
                                    chunk_str = chunk.decode('utf-8')
                                    if chunk_str.startswith('data: '):
                                        data_str = chunk_str[6:].strip()
                                        if data_str and data_str != '[DONE]':
                                            chunk_data = json.loads(data_str)
                                except (UnicodeDecodeError, json.JSONDecodeError):
                                    logger.warning(f"Failed to parse Kiro bytes chunk")
                                    continue
                            
                            if chunk_data:
                                # Extract content and tool calls from chunk
                                choices = chunk_data.get('choices', [])
                                if choices:
                                    delta = choices[0].get('delta', {})
                                    
                                    # Track content using optimized accumulator
                                    delta_content = delta.get('content', '')
                                    if delta_content:
                                        accumulated_response_text = kiro_text_accumulator.append(delta_content)
                                    
                                    # Track tool calls
                                    delta_tool_calls = delta.get('tool_calls', [])
                                    if delta_tool_calls:
                                        for tc in delta_tool_calls:
                                            tool_calls_from_stream.append(tc)
                                            logger.debug(f"Collected tool call from Kiro stream: {tc}")
                                
                                # Pass through the chunk as-is
                                if isinstance(chunk, str):
                                    yield chunk.encode('utf-8')
                                elif isinstance(chunk, bytes):
                                    yield chunk
                                else:
                                    yield f"data: {json.dumps(chunk_data)}\n\n".encode('utf-8')
                            else:
                                # Pass through non-data chunks as-is (like [DONE])
                                if isinstance(chunk, str):
                                    yield chunk.encode('utf-8')
                                elif isinstance(chunk, bytes):
                                    yield chunk
                                else:
                                    yield f"data: {json.dumps(chunk)}\n\n".encode('utf-8')

                        except Exception as chunk_error:
                            error_msg = str(chunk_error)
                            logger.warning(f"Error processing Kiro chunk: {error_msg}")
                            logger.warning(f"Chunk type: {type(chunk)}")
                            logger.warning(f"Chunk content: {chunk}")
                            continue

                    # After stream ends, process collected tool calls
                    if tool_calls_from_stream:
                        logger.info(f"Processing {len(tool_calls_from_stream)} tool calls from Kiro stream")
                        
                        # Add required index field to each tool_call
                        # according to OpenAI API specification for streaming
                        indexed_tool_calls = []
                        for idx, tc in enumerate(tool_calls_from_stream):
                            # Extract function with None protection
                            func = tc.get("function") or {}
                            # Use "or" for protection against explicit None in values
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
                            "model": request_data['model'],
                            "choices": [{
                                "index": 0,
                                "delta": {"tool_calls": indexed_tool_calls},
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(tool_calls_chunk, ensure_ascii=False)}\n\n".encode('utf-8')

                    logger.info(f"Kiro streaming processed {chunk_count} chunks total")

                elif is_google_stream:
                    # Handle Google's streaming response
                    # Google provider returns an async generator
                    # Note: Google returns accumulated text, so we need to track and send only deltas
                    chunk_id = 0
                    accumulated_text = ""  # Track text we've already sent
                    seen_tool_call_ids = set()  # Track which tool call IDs we've already sent
                    last_chunk_id = None  # Track the last chunk for finish_reason
                    created_time = int(time.time())
                    response_id = f"google-{request_data['model']}-{created_time}"
                    
                    # Track completion tokens for Google responses (since Google doesn't provide them)
                    completion_tokens = 0
                    accumulated_response_text = ""  # Track full response for token counting
                    
                    # Use optimized text accumulator for memory efficiency
                    text_accumulator = OptimizedTextAccumulator(
                        max_size=stream_config.google_accumulated_text_limit,
                        enable_truncation=stream_config.enable_text_truncation
                    )
                    
                    # Collect all chunks first to know when we're at the last one
                    chunks_list = []
                    async for chunk in response:
                        chunks_list.append(chunk)
                    
                    total_chunks = len(chunks_list)
                    chunk_idx = 0
                    
                    for chunk in chunks_list:
                        try:
                            logger.debug(f"Google chunk type: {type(chunk)}")
                            logger.debug(f"Google chunk: {chunk}")
                            
                            # Extract text and tool calls from Google chunk (this is accumulated text)
                            chunk_text = ""
                            chunk_tool_calls = []
                            finish_reason = None
                            try:
                                if hasattr(chunk, 'candidates') and chunk.candidates:
                                    candidate = chunk.candidates[0] if chunk.candidates else None
                                    if candidate and hasattr(candidate, 'content') and candidate.content:
                                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                            for part in candidate.content.parts:
                                                # Extract text content
                                                if hasattr(part, 'text') and part.text:
                                                    chunk_text += part.text
                                                # Extract function calls (Google's format)
                                                if hasattr(part, 'function_call') and part.function_call:
                                                    function_call = part.function_call
                                                    # Convert Google function call to OpenAI format
                                                    import json
                                                    openai_tool_call = {
                                                        "id": f"call_{len(chunk_tool_calls)}",
                                                        "type": "function",
                                                        "function": {
                                                            "name": function_call.name,
                                                            "arguments": json.dumps(function_call.args) if hasattr(function_call, 'args') else "{}"
                                                        }
                                                    }
                                                    chunk_tool_calls.append(openai_tool_call)
                                                    logger.info(f"Extracted tool call from Google chunk: {openai_tool_call}")
                                    # Check for finish reason in candidate
                                    if hasattr(candidate, 'finish_reason'):
                                        google_finish = str(candidate.finish_reason)
                                        if google_finish in ('STOP', 'END_TURN', 'FINISH_REASON_UNSPECIFIED'):
                                            finish_reason = "stop"
                                        elif google_finish == 'MAX_TOKENS':
                                            finish_reason = "length"
                            except Exception as e:
                                logger.error(f"Error extracting text from Google chunk: {e}")
                            
                            # Calculate the delta (only the new text since last chunk) using optimized function
                            if stream_config.google_delta_calculation:
                                delta_text = calculate_google_delta(chunk_text, accumulated_text)
                            else:
                                delta_text = chunk_text[len(accumulated_text):] if chunk_text.startswith(accumulated_text) else chunk_text
                            accumulated_text = chunk_text  # Update accumulated text for next iteration
                            
                            # Calculate delta tool calls (only tool calls we haven't seen before)
                            delta_tool_calls = []
                            for tool_call in chunk_tool_calls:
                                if tool_call["id"] not in seen_tool_call_ids:
                                    delta_tool_calls.append(tool_call)
                                    seen_tool_call_ids.add(tool_call["id"])
                                    logger.info(f"Adding tool call to delta: {tool_call}")
                            
                            # Check if this is the last chunk
                            is_last_chunk = (chunk_idx == total_chunks - 1)
                            chunk_finish_reason = finish_reason if is_last_chunk else None
                            
                            # Debug logging
                            logger.debug(f"Chunk {chunk_idx}/{total_chunks}: delta_text='{delta_text}', delta_tool_calls={len(delta_tool_calls)}, is_last={is_last_chunk}, condition={bool(delta_text or delta_tool_calls or is_last_chunk)}")
                            
                            # Only send if there's new content, new tool calls, or it's the last chunk with finish_reason
                            if delta_tool_calls or delta_text or is_last_chunk:
                                # Use optimized chunk from pool
                                openai_chunk = optimizer.chunk_pool.acquire()
                                try:
                                    openai_chunk.update({
                                        "id": response_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_time,
                                        "model": request_data['model'],
                                        "service_tier": None,
                                        "system_fingerprint": system_fingerprint,
                                        "usage": None,
                                        "provider": provider_id,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {
                                                "content": delta_text if delta_text else "",
                                                "refusal": None,
                                                "role": "assistant",
                                                "tool_calls": delta_tool_calls if len(delta_tool_calls) > 0 else None
                                            },
                                            "finish_reason": chunk_finish_reason,
                                            "logprobs": None,
                                            "native_finish_reason": chunk_finish_reason
                                        }]
                                    })
                                    
                                    chunk_id += 1
                                    logger.debug(f"OpenAI chunk (delta length: {len(delta_text)}, finish: {chunk_finish_reason})")
                                    
                                    # Track completion tokens for Google responses using optimized accumulator
                                    if delta_text:
                                        accumulated_response_text = text_accumulator.append(delta_text)
                                    
                                    # Serialize as JSON and yield
                                    yield f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
                                finally:
                                    optimizer.chunk_pool.release(openai_chunk)
                            
                            chunk_idx += 1
                        except Exception as chunk_error:
                            error_msg = str(chunk_error)
                            logger.error(f"Error processing Google chunk: {error_msg}")
                            logger.error(f"Chunk type: {type(chunk)}")
                            logger.error(f"Chunk content: {chunk}")
                            # Skip this chunk and continue
                            chunk_idx += 1
                            continue
                    
                    # Send final chunk with usage statistics (empty content)
                    # Calculate completion tokens for Google responses (count tokens in full response)
                    if accumulated_response_text:
                        completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], request_data['model'])
                    total_tokens = effective_context + completion_tokens
                    final_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": request_data['model'],
                        "service_tier": None,
                        "system_fingerprint": system_fingerprint,
                        "usage": {
                            "prompt_tokens": effective_context,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "effective_context": effective_context
                        },
                        "provider": provider_id,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "content": "",
                                "function_call": None,
                                "refusal": None,
                                "role": "assistant",
                                "tool_calls": None
                            },
                            "finish_reason": None,
                            "logprobs": None,
                            "native_finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n".encode('utf-8')
                else:
                    # Handle OpenAI/Anthropic/Claude streaming responses
                    # Some providers return async generators, others return sync iterables
                    accumulated_response_text = ""  # Track full response for token counting
                    
                    # Check if response is an async generator
                    import inspect
                    if inspect.iscoroutinefunction(response) or hasattr(response, '__aiter__'):
                        # Handle async generator (like Claude, Kiro)
                        logger.info(f"Detected async generator response, using async for loop")
                        async for chunk in response:
                            try:
                                logger.debug(f"Async chunk type: {type(chunk)}")
                                logger.debug(f"Async chunk: {chunk}")
                                
                                # For async generators, chunks might be bytes (SSE format)
                                if isinstance(chunk, bytes):
                                    logger.debug(f"Yielding raw bytes chunk: {len(chunk)} bytes")
                                    yield chunk
                                else:
                                    # Fallback: treat as dict and serialize
                                    chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
                                    
                                    # Track response content for token calculation
                                    if isinstance(chunk_dict, dict):
                                        choices = chunk_dict.get('choices', [])
                                        if choices:
                                            delta = choices[0].get('delta', {})
                                            delta_content = delta.get('content', '')
                                            if delta_content:
                                                accumulated_response_text += delta_content
                                    
                                    # Add effective_context to the last chunk (when finish_reason is present)
                                    if isinstance(chunk_dict, dict):
                                        choices = chunk_dict.get('choices', [])
                                        if choices and choices[0].get('finish_reason') is not None:
                                            # This is the last chunk, add effective_context
                                            if 'usage' not in chunk_dict:
                                                chunk_dict['usage'] = {}
                                            chunk_dict['usage']['effective_context'] = effective_context
                                            
                                            # If provider doesn't provide token counts, calculate them
                                            if chunk_dict['usage'].get('total_tokens') is None:
                                                # Calculate completion tokens from accumulated response
                                                if accumulated_response_text:
                                                    completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], request_data['model'])
                                                else:
                                                    completion_tokens = 0
                                                total_tokens = effective_context + completion_tokens
                                                chunk_dict['usage']['prompt_tokens'] = effective_context
                                                chunk_dict['usage']['completion_tokens'] = completion_tokens
                                                chunk_dict['usage']['total_tokens'] = total_tokens
                                    
                                    yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
                            except Exception as chunk_error:
                                error_msg = str(chunk_error)
                                logger.warning(f"Error processing async chunk: {error_msg}")
                                logger.warning(f"Chunk type: {type(chunk)}")
                                logger.warning(f"Chunk content: {chunk}")
                                continue
                    else:
                        # Handle sync iterable (like OpenAI SDK)
                        logger.info(f"Detected sync iterable response, using regular for loop")
                        for chunk in response:
                            try:
                                # Debug: Log chunk type and content before serialization
                                logger.debug(f"Chunk type: {type(chunk)}")
                                logger.debug(f"Chunk: {chunk}")
                                
                                # For OpenAI-compatible providers, just pass through the raw chunk
                                # Convert chunk to dict and serialize as JSON
                                chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
                                
                                # Track response content for token calculation
                                if isinstance(chunk_dict, dict):
                                    choices = chunk_dict.get('choices', [])
                                    if choices:
                                        delta = choices[0].get('delta', {})
                                        delta_content = delta.get('content', '')
                                        if delta_content:
                                            accumulated_response_text += delta_content
                                
                                # Add effective_context to the last chunk (when finish_reason is present)
                                if isinstance(chunk_dict, dict):
                                    choices = chunk_dict.get('choices', [])
                                    if choices and choices[0].get('finish_reason') is not None:
                                        # This is the last chunk, add effective_context
                                        if 'usage' not in chunk_dict:
                                            chunk_dict['usage'] = {}
                                        chunk_dict['usage']['effective_context'] = effective_context
                                        
                                        # If provider doesn't provide token counts, calculate them
                                        if chunk_dict['usage'].get('total_tokens') is None:
                                            # Calculate completion tokens from accumulated response
                                            if accumulated_response_text:
                                                completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], request_data['model'])
                                            else:
                                                completion_tokens = 0
                                            total_tokens = effective_context + completion_tokens
                                            chunk_dict['usage']['prompt_tokens'] = effective_context
                                            chunk_dict['usage']['completion_tokens'] = completion_tokens
                                            chunk_dict['usage']['total_tokens'] = total_tokens
                                
                                yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
                            except Exception as chunk_error:
                                # Handle errors during chunk serialization
                                error_msg = str(chunk_error)
                                logger.warning(f"Error serializing chunk: {error_msg}")
                                logger.warning(f"Chunk type: {type(chunk)}")
                                logger.warning(f"Chunk content: {chunk}")
                                # Skip this chunk and continue with the next one
                                continue
                handler.record_success()
                
                # Record analytics for streaming request
                try:
                    analytics = get_analytics()
                    # Calculate latency
                    latency_ms = (time.time() - request_start_time) * 1000
                    logger.info(f"Streaming Analytics: latency_ms={latency_ms:.2f}")
                    
                    # Calculate total tokens from accumulated response
                    if accumulated_response_text:
                        completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], request_data['model'])
                    else:
                        completion_tokens = 0
                    total_tokens = effective_context + completion_tokens
                    
                    analytics.record_request(
                        provider_id=provider_id,
                        model_name=request_data['model'],
                        tokens_used=total_tokens,
                        latency_ms=latency_ms,
                        success=True,
                        user_id=getattr(request.state, 'user_id', None),
                        token_id=getattr(request.state, 'token_id', None),
                        prompt_tokens=effective_context,
                        completion_tokens=completion_tokens,
                        actual_cost=None  # Streaming responses typically don't include cost
                    )
                except Exception as analytics_error:
                    logger.warning(f"Analytics recording for streaming request failed: {analytics_error}")
                
            except Exception as e:
                handler.record_failure()
                
                # Record analytics for failed streaming request
                try:
                    analytics = get_analytics()
                    # Calculate latency
                    latency_ms = (time.time() - request_start_time) * 1000
                    logger.info(f"Failed Streaming Analytics: latency_ms={latency_ms:.2f}")
                    
                    # Estimate tokens for failed request
                    try:
                        messages = request_data.get('messages', [])
                        estimated_tokens = count_messages_tokens(messages, request_data['model'])
                        total_tokens = estimated_tokens
                        prompt_tokens = estimated_tokens
                        completion_tokens = 0
                    except Exception:
                        total_tokens = 50  # Minimal estimate for failed requests
                        prompt_tokens = 50
                        completion_tokens = 0
                    
                    analytics.record_request(
                        provider_id=provider_id,
                        model_name=request_data['model'],
                        tokens_used=total_tokens,
                        latency_ms=latency_ms,
                        success=False,
                        error_type=type(e).__name__,
                        user_id=getattr(request.state, 'user_id', None),
                        token_id=getattr(request.state, 'token_id', None),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        actual_cost=None
                    )
                except Exception as analytics_error:
                    logger.warning(f"Analytics recording for failed streaming request failed: {analytics_error}")
                
                error_dict = {"error": str(e)}
                yield f"data: {json.dumps(error_dict)}\n\n".encode('utf-8')

        return StreamingResponse(stream_generator(effective_context), media_type="text/event-stream")

    async def handle_model_list(self, request: Request, provider_id: str) -> List[Dict]:
        provider_config = self.config.get_provider(provider_id)

        if provider_config.api_key_required:
            api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None

        # First check if we already have models for same provider type + same endpoint from same user
        import logging
        logger = logging.getLogger(__name__)
        
        # Check all other providers with same type, same endpoint and same user
        same_providers = []
        if self.user_id:
            # Check user providers
            for pid, pconfig in self.user_providers.items():
                if pid != provider_id and pconfig.type == provider_config.type and pconfig.endpoint == provider_config.endpoint:
                    same_providers.append(pid)
        else:
            # Check global providers
            for pid, pconfig in self.config.providers.items():
                if pid != provider_id and pconfig.type == provider_config.type and pconfig.endpoint == provider_config.endpoint:
                    same_providers.append(pid)
        
        # If there are matching providers, check if they have cached models
        for same_pid in same_providers:
            # Check if this provider already has models loaded
            try:
                same_handler = get_provider_handler(same_pid, user_id=self.user_id)
                if hasattr(same_handler, '_cached_models') and same_handler._cached_models and len(same_handler._cached_models) > 0:
                    logger.info(f"Reusing models from existing provider {same_pid} for {provider_id} (same type and endpoint)")
                    # Copy models and apply correct provider_id
                    models = []
                    for model in same_handler._cached_models:
                        # Create new model instance with correct provider_id
                        model_copy = model.copy()
                        model_copy.provider_id = provider_id
                        models.append(model_copy)
                    
                    # Also cache on this handler
                    handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
                    handler._cached_models = models
                    
                    # Skip rate limit and direct model fetch
                    model_filter = getattr(provider_config, 'model_filter', None)
                    if model_filter and (not getattr(provider_config, "models", []) or len(getattr(provider_config, "models", [])) == 0):
                        logger.info(f"Applying model filter '{model_filter}' to provider {provider_id}")
                        original_count = len(models)
                        models = [m for m in models if model_filter.lower() in m.id.lower()]
                        logger.info(f"Model filter applied: {original_count} -> {len(models)} models")
                    
                    # Enhance model information with context window and capabilities
                    enhanced_models = []
                    current_time = int(time_module.time())
                    for model in models:
                        model_dict = model.dict()
                        model_name = model_dict.get('id', '')
                        
                        # Add OpenAI-compatible required fields
                        model_dict['object'] = 'model'
                        model_dict['created'] = current_time
                        model_dict['owned_by'] = provider_config.name
                        
                        # Try to find model config in provider config
                        model_config = None
                        if getattr(provider_config, "models", []):
                            for m in getattr(provider_config, "models", []):
                                if m.name == model_name:
                                    model_config = m
                                    break
                        
                        # Add context window information - use dynamically fetched value unless manually configured
                        # Priority: manually configured > dynamically fetched > inferred
                        if model_config and hasattr(model_config, 'context_size') and model_config.context_size:
                            # Manually configured - use this value
                            model_dict['context_window'] = model_config.context_size
                        elif model_dict.get('context_size'):
                            # Dynamically fetched from provider - use this value
                            model_dict['context_window'] = model_dict['context_size']
                        else:
                            # Fall back to inference
                            model_dict['context_window'] = self._infer_context_window(model_name, provider_config.type)
                        
                        # Add context_length for compatibility - same priority order as context_window
                        if model_config and hasattr(model_config, 'context_size') and model_config.context_size:
                            model_dict['context_length'] = model_config.context_size
                        elif model_dict.get('context_size'):
                            model_dict['context_length'] = model_dict['context_size']
                        elif model_dict.get('context_length'):
                            model_dict['context_length'] = model_dict['context_length']
                        
                        # Add pricing if available (from dynamic fetch)
                        if model_dict.get('pricing'):
                            model_dict['pricing'] = model_dict['pricing']
                        
                        # Add description if available (from dynamic fetch)
                        if model_dict.get('description'):
                            model_dict['description'] = model_dict['description']
                        
                        # Add top_provider info if available (from dynamic fetch)
                        if model_dict.get('top_provider'):
                            model_dict['top_provider'] = model_dict['top_provider']
                        
                        # Add supported_parameters if available (from dynamic fetch)
                        if model_dict.get('supported_parameters'):
                            model_dict['supported_parameters'] = model_dict['supported_parameters']
                        
                        # Add capabilities information
                        if model_config and hasattr(model_config, 'capabilities'):
                            model_dict['capabilities'] = model_config.capabilities
                        elif 'capabilities' not in model_dict:
                            # Auto-detect capabilities based on model name and provider type
                            model_dict['capabilities'] = self._detect_capabilities(model_name, provider_config.type)
                        
                        enhanced_models.append(model_dict)
                    
                    return enhanced_models
            except Exception as e:
                logger.debug(f"Failed to reuse models from {same_pid}: {e}")
                continue
        
        # No existing models found, proceed normally
        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
        try:
            # Apply rate limiting
            await handler.apply_rate_limit()

            models = await handler.get_models()
            
            # Check if this is an auth status response (dictionary instead of Model list)
            # Some providers (Kilo, Qwen, Claude) return auth status instead of models when not authenticated
            if isinstance(models, dict) and 'status' in models:
                logger.info(f"Provider {provider_id} returned auth status instead of models: {models.get('status')}")
                # Return empty models list but include auth status in response headers
                models = []
            
            # Cache the models on the handler
            handler._cached_models = models
            
            # Apply model filter if configured and no models are manually specified
            model_filter = getattr(provider_config, 'model_filter', None)
            if model_filter and (not getattr(provider_config, "models", []) or len(getattr(provider_config, "models", [])) == 0):
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Applying model filter '{model_filter}' to provider {provider_id}")
                
                # Filter models whose ID contains the filter word (case-insensitive)
                original_count = len(models)
                models = [m for m in models if model_filter.lower() in m.id.lower()]
                logger.info(f"Model filter applied: {original_count} -> {len(models)} models")
            
            # Enhance model information with context window and capabilities
            enhanced_models = []
            current_time = int(time_module.time())
            for model in models:
                model_dict = model.dict()
                model_name = model_dict.get('id', '')
                
                # Add OpenAI-compatible required fields
                model_dict['object'] = 'model'
                model_dict['created'] = current_time
                model_dict['owned_by'] = provider_config.name
                
                # Try to find model config in provider config
                model_config = None
                if getattr(provider_config, "models", []):
                    for m in getattr(provider_config, "models", []):
                        if m.name == model_name:
                            model_config = m
                            break
                
                # Add context window information - use dynamically fetched value unless manually configured
                # Priority: manually configured > dynamically fetched > inferred
                if model_config and hasattr(model_config, 'context_size') and model_config.context_size:
                    # Manually configured - use this value
                    model_dict['context_window'] = model_config.context_size
                elif model_dict.get('context_size'):
                    # Dynamically fetched from provider - use this value
                    model_dict['context_window'] = model_dict['context_size']
                else:
                    # Fall back to inference
                    model_dict['context_window'] = self._infer_context_window(model_name, provider_config.type)
                
                # Add context_length for compatibility - same priority order as context_window
                if model_config and hasattr(model_config, 'context_size') and model_config.context_size:
                    model_dict['context_length'] = model_config.context_size
                elif model_dict.get('context_size'):
                    model_dict['context_length'] = model_dict['context_size']
                elif model_dict.get('context_length'):
                    model_dict['context_length'] = model_dict['context_length']
                
                # Add pricing if available (from dynamic fetch)
                if model_dict.get('pricing'):
                    model_dict['pricing'] = model_dict['pricing']
                
                # Add description if available (from dynamic fetch)
                if model_dict.get('description'):
                    model_dict['description'] = model_dict['description']
                
                # Add top_provider info if available (from dynamic fetch)
                if model_dict.get('top_provider'):
                    model_dict['top_provider'] = model_dict['top_provider']
                
                # Add supported_parameters if available (from dynamic fetch)
                if model_dict.get('supported_parameters'):
                    model_dict['supported_parameters'] = model_dict['supported_parameters']
                
                # Add capabilities information
                if model_config and hasattr(model_config, 'capabilities'):
                    model_dict['capabilities'] = model_config.capabilities
                elif 'capabilities' not in model_dict:
                    # Auto-detect capabilities based on model name and provider type
                    model_dict['capabilities'] = self._detect_capabilities(model_name, provider_config.type)
                
                enhanced_models.append(model_dict)
            
            return enhanced_models
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    def _infer_context_window(self, model_name: str, provider_type: str) -> int:
        """Infer context window size from model name or provider type"""
        model_lower = model_name.lower()
        
        # Known model patterns
        if 'gpt-4' in model_lower:
            if 'turbo' in model_lower or '1106' in model_lower or '0125' in model_lower:
                return 128000
            return 8192
        elif 'gpt-3.5' in model_lower:
            if 'turbo' in model_lower and ('1106' in model_lower or '0125' in model_lower):
                return 16385
            return 4096
        elif 'claude-3' in model_lower:
            return 200000
        elif 'claude-2' in model_lower:
            return 100000
        elif 'gemini' in model_lower:
            if '1.5' in model_lower:
                return 2000000 if 'pro' in model_lower else 1000000
            elif '2.0' in model_lower:
                return 1000000
            return 32000
        elif 'llama' in model_lower:
            if '3' in model_lower:
                return 128000
            return 4096
        elif 'mistral' in model_lower:
            if 'large' in model_lower:
                return 32000
            return 8192
        
        # Default based on provider type
        if provider_type == 'google':
            return 32000
        elif provider_type == 'anthropic':
            return 100000
        elif provider_type == 'openai':
            return 8192
        
        # Generic default
        return 4096
    
    def _detect_capabilities(self, model_name: str, provider_type: str) -> List[str]:
        """Auto-detect model capabilities based on model name and provider type"""
        model_lower = model_name.lower()
        capabilities = []
        
        # Text-to-text (default for most models)
        if not any(keyword in model_lower for keyword in ['embedding', 'embed', 'whisper', 'tts', 'dall-e', 'stable-diffusion']):
            capabilities.append('t2t')
        
        # Text-to-image generation
        if any(keyword in model_lower for keyword in ['dall-e', 'dalle', 'stable-diffusion', 'sd-', 'sdxl', 'midjourney', 'imagen', 'flux']):
            capabilities.append('t2i')
        
        # Image-to-image (editing, style transfer)
        if any(keyword in model_lower for keyword in ['stable-diffusion', 'sd-', 'sdxl', 'controlnet', 'img2img']):
            capabilities.append('i2i')
        
        # Vision/Image understanding (image-to-text)
        if any(keyword in model_lower for keyword in ['vision', 'gpt-4-turbo', 'gpt-4o', 'claude-3', 'gemini-1.5', 'gemini-2.0', 'gemini-pro-vision', 'llava', 'blip']):
            capabilities.append('vision')
            capabilities.append('i2t')
        
        # Audio transcription (audio-to-text)
        if any(keyword in model_lower for keyword in ['whisper', 'transcribe', 'speech-to-text', 'stt']):
            capabilities.append('transcription')
            capabilities.append('a2t')
        
        # Text-to-speech
        if any(keyword in model_lower for keyword in ['tts', 'text-to-speech', 'elevenlabs', 'bark', 'tortoise']):
            capabilities.append('tts')
            capabilities.append('t2a')
        
        # Text-to-video generation
        if any(keyword in model_lower for keyword in ['sora', 'runway', 'pika', 'text-to-video', 't2v']):
            capabilities.append('t2v')
        
        # Image-to-video generation
        if any(keyword in model_lower for keyword in ['runway', 'pika', 'img2video', 'i2v']):
            capabilities.append('i2v')
        
        # Video-to-video (editing)
        if any(keyword in model_lower for keyword in ['runway', 'video-edit', 'v2v']):
            capabilities.append('v2v')
        
        # Video understanding (video-to-text)
        if any(keyword in model_lower for keyword in ['video-llama', 'video-chat', 'v2t']):
            capabilities.append('v2t')
        
        # Audio-to-audio (music generation, audio processing)
        if any(keyword in model_lower for keyword in ['musicgen', 'audiogen', 'riffusion', 'a2a']):
            capabilities.append('a2a')
        
        # Text embeddings
        if any(keyword in model_lower for keyword in ['embedding', 'embed', 'ada-002', 'bge', 'e5', 'instructor']):
            capabilities.append('embeddings')
        
        # Function calling / tool use
        if any(keyword in model_lower for keyword in ['gpt-4', 'gpt-3.5-turbo', 'claude-3', 'gemini', 'function', 'tool']):
            capabilities.append('function_calling')
        
        # Code generation
        if any(keyword in model_lower for keyword in ['codex', 'code-', 'starcoder', 'codellama', 'deepseek-coder', 'phind']):
            capabilities.append('code_generation')
            capabilities.append('code_completion')
        
        # Translation
        if any(keyword in model_lower for keyword in ['translate', 'translation', 'm2m', 'nllb']):
            capabilities.append('translation')
        
        # Summarization
        if any(keyword in model_lower for keyword in ['summarize', 'summary', 'bart', 'pegasus']):
            capabilities.append('summarization')
        
        # Classification
        if any(keyword in model_lower for keyword in ['classifier', 'classification', 'bert-', 'roberta-']):
            capabilities.append('classification')
        
        # Sentiment analysis
        if any(keyword in model_lower for keyword in ['sentiment', 'emotion']):
            capabilities.append('sentiment_analysis')
        
        # Named Entity Recognition
        if any(keyword in model_lower for keyword in ['ner', 'entity', 'spacy']):
            capabilities.append('ner')
        
        # Question answering
        if any(keyword in model_lower for keyword in ['qa', 'question', 'squad']):
            capabilities.append('question_answering')
        
        # Reasoning (chain-of-thought)
        if any(keyword in model_lower for keyword in ['reasoning', 'cot', 'o1', 'o3']):
            capabilities.append('reasoning')
        
        # Search / RAG
        if any(keyword in model_lower for keyword in ['search', 'retrieval', 'rag']):
            capabilities.append('search')
        
        # Content moderation
        if any(keyword in model_lower for keyword in ['moderation', 'safety', 'content-filter']):
            capabilities.append('moderation')
        
        # Fine-tuning support
        if any(keyword in model_lower for keyword in ['fine-tune', 'finetune', 'ft-']):
            capabilities.append('fine_tuning')
        
        # Multimodal (multiple input/output types)
        if any(keyword in model_lower for keyword in ['gpt-4o', 'gemini', 'claude-3', 'multimodal', 'mm-']):
            capabilities.append('multimodal')
        
        # OCR (Optical Character Recognition)
        if any(keyword in model_lower for keyword in ['ocr', 'tesseract', 'paddleocr', 'easyocr']):
            capabilities.append('ocr')
        
        # Image captioning
        if any(keyword in model_lower for keyword in ['caption', 'blip', 'git-']):
            capabilities.append('image_captioning')
        
        # Object detection
        if any(keyword in model_lower for keyword in ['yolo', 'detection', 'rcnn', 'detr']):
            capabilities.append('object_detection')
        
        # Segmentation
        if any(keyword in model_lower for keyword in ['segment', 'sam', 'mask']):
            capabilities.append('segmentation')
        
        # 3D generation
        if any(keyword in model_lower for keyword in ['3d', 'nerf', 'gaussian', 'mesh']):
            capabilities.append('3d_generation')
        
        # Animation
        if any(keyword in model_lower for keyword in ['animate', 'motion', 'pose']):
            capabilities.append('animation')
        
        return capabilities
    
    async def handle_audio_transcription(self, request: Request, provider_id: str, form_data) -> Dict:
        """Handle audio transcription requests"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Audio Transcription Handler START ===")
        
        provider_config = self.config.get_provider(provider_id)
        
        if provider_config.api_key_required:
            api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
        
        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
        
        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")
        
        try:
            await handler.apply_rate_limit()
            result = await handler.handle_audio_transcription(form_data)
            handler.record_success()
            return result
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))
    
    async def handle_text_to_speech(self, request: Request, provider_id: str, request_data: Dict) -> StreamingResponse:
        """Handle text-to-speech requests"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Text-to-Speech Handler START ===")
        
        provider_config = self.config.get_provider(provider_id)
        
        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
        
        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
        
        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")
        
        try:
            await handler.apply_rate_limit()
            result = await handler.handle_text_to_speech(request_data)
            handler.record_success()
            return result
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))
    
    async def handle_image_generation(self, request: Request, provider_id: str, request_data: Dict) -> Dict:
        """Handle image generation requests with URL rewriting"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Image Generation Handler START ===")
        
        provider_config = self.config.get_provider(provider_id)
        
        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
        
        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
        
        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")
        
        try:
            await handler.apply_rate_limit()
            result = await handler.handle_image_generation(request_data)
            
            # Rewrite URLs in the response to point to our proxy
            result = self._rewrite_content_urls(result, request)
            
            handler.record_success()
            return result
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))
    
    async def handle_embeddings(self, request: Request, provider_id: str, request_data: Dict) -> Dict:
        """Handle embeddings requests"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Embeddings Handler START ===")
        
        provider_config = self.config.get_provider(provider_id)
        
        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
        
        handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
        
        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")
        
        try:
            await handler.apply_rate_limit()
            result = await handler.handle_embeddings(request_data)
            handler.record_success()
            return result
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))
    
    def _rewrite_content_urls(self, response: Dict, request: Request) -> Dict:
        """Rewrite content URLs to point to our proxy endpoint"""
        import logging
        import hashlib
        import json
        logger = logging.getLogger(__name__)
        
        # Get the base URL from the request
        scheme = request.url.scheme
        host = request.headers.get('host', request.url.netloc)
        base_url = f"{scheme}://{host}"
        
        # Store URL mappings in a simple in-memory cache (in production, use Redis or similar)
        if not hasattr(self, '_url_cache'):
            self._url_cache = {}
        
        def rewrite_url(original_url: str) -> str:
            """Rewrite a single URL"""
            # Check if URL is already public and accessible
            if self._is_public_url(original_url):
                logger.info(f"URL is public, passing through: {original_url}")
                return original_url
            
            # Generate a unique ID for this URL
            url_hash = hashlib.md5(original_url.encode()).hexdigest()[:16]
            
            # Store the mapping
            self._url_cache[url_hash] = original_url
            
            # Return the proxy URL
            proxy_url = f"{base_url}/api/proxy/{url_hash}"
            logger.info(f"Rewrote URL: {original_url} -> {proxy_url}")
            return proxy_url
        
        # Recursively rewrite URLs in the response
        def rewrite_recursive(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ['url', 'image_url', 'audio_url', 'video_url'] and isinstance(value, str):
                        obj[key] = rewrite_url(value)
                    else:
                        obj[key] = rewrite_recursive(value)
            elif isinstance(obj, list):
                return [rewrite_recursive(item) for item in obj]
            return obj
        
        return rewrite_recursive(response)
    
    def _is_public_url(self, url: str) -> bool:
        """Check if a URL is publicly accessible (doesn't need proxying)"""
        # URLs from major CDNs and public services don't need proxying
        public_domains = [
            'cloudflare.com',
            'amazonaws.com',
            'googleusercontent.com',
            'azure.com',
            'cdn.',
            'storage.googleapis.com'
        ]
        
        return any(domain in url.lower() for domain in public_domains)
    
    async def handle_content_proxy(self, content_id: str) -> StreamingResponse:
        """Proxy content from the original URL"""
        import logging
        import httpx
        logger = logging.getLogger(__name__)
        
        # Get the original URL from cache
        if not hasattr(self, '_url_cache'):
            self._url_cache = {}
        
        original_url = self._url_cache.get(content_id)
        if not original_url:
            raise HTTPException(status_code=404, detail="Content not found")
        
        logger.info(f"Proxying content: {content_id} -> {original_url}")
        
        try:
            # Fetch the content from the original URL
            async with httpx.AsyncClient() as client:
                response = await client.get(original_url, follow_redirects=True)
                response.raise_for_status()
                
                # Determine content type
                content_type = response.headers.get('content-type', 'application/octet-stream')
                
                # Return the content as a streaming response
                return StreamingResponse(
                    iter([response.content]),
                    media_type=content_type,
                    headers={
                        'Content-Disposition': response.headers.get('content-disposition', ''),
                        'Cache-Control': 'public, max-age=3600'
                    }
                )
        except Exception as e:
            logger.error(f"Error proxying content: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error fetching content: {str(e)}")

class RotationHandler:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.config = config
        # Load user-specific configs if user_id is provided
        if user_id:
            self._load_user_configs()
            # Override config to only use user-specific configs with NO global fallback
            self.rotations = {}
            for rotation in self.user_rotations:
                self.rotations[rotation['rotation_id']] = rotation['config']
        else:
            self.user_providers = {}
            self.user_rotations = {}
            self.user_autoselects = {}
            self.rotations = self.config.rotations if hasattr(self.config, 'rotations') else {}

    def _load_user_configs(self):
        """Load user-specific configurations from database"""
        from .database import DatabaseRegistry
        db = DatabaseRegistry.get_config_database()
        self.user_providers = db.get_user_providers(self.user_id)
        self.user_rotations = db.get_user_rotations(self.user_id)
        self.user_autoselects = db.get_user_autoselects(self.user_id)

    def reload_user_configs(self):
        """Reload user-specific configurations from database"""
        if self.user_id:
            self._load_user_configs()
            # Refresh rotations dict after reload
            self.rotations = {}
            for rotation in self.user_rotations:
                self.rotations[rotation['rotation_id']] = rotation['config']

    def _get_provider_type(self, provider_id: str) -> str:
        """Get the provider type from configuration"""
        provider_config = self.config.get_provider(provider_id)
        if provider_config:
            return provider_config.type
        return None
    
    def _apply_defaults_to_model(self, model: Dict, provider_config, rotation_config) -> Dict:
        """
        Apply default settings to a model configuration.
        
        Priority order:
        1. Model-specific settings (highest priority)
        2. Rotation default settings
        3. Provider default settings
        4. Auto-derived from first model in provider (lowest priority)
        
        Args:
            model: The model configuration dict
            provider_config: The provider configuration
            rotation_config: The rotation configuration
            
        Returns:
            Model dict with defaults applied
        """
        # List of fields that can have defaults
        default_fields = [
            'rate_limit',
            'max_request_tokens',
            'rate_limit_TPM',
            'rate_limit_TPH',
            'rate_limit_TPD',
            'context_size',
            'condense_context',
            'condense_method'
        ]
        
        for field in default_fields:
            # If field is not set in model, try rotation defaults, then provider defaults
            if field not in model or model[field] is None:
                # Try rotation defaults first
                rotation_default = getattr(rotation_config, f'default_{field}', None)
                if rotation_default is not None:
                    model[field] = rotation_default
                else:
                    # Try provider defaults
                    provider_default = getattr(provider_config, f'default_{field}', None)
                    if provider_default is not None:
                        model[field] = provider_default
                    else:
                        # Auto-derive from first model in provider config if available
                        if provider_config and getattr(provider_config, "models", []) and len(getattr(provider_config, "models", [])) > 0:
                            first_model = getattr(provider_config, "models", [])[0]
                            # For context_size, check multiple field names (from dynamic fetch)
                            if field == 'context_size':
                                model_field = getattr(first_model, 'context_size', None)
                                if model_field is None:
                                    model_field = getattr(first_model, 'context_window', None)
                                if model_field is None:
                                    model_field = getattr(first_model, 'context_length', None)
                            else:
                                model_field = getattr(first_model, field, None)
                            if model_field is not None:
                                model[field] = model_field
        
        return model

    def _apply_defaults_to_autoselect_model(self, model_config: Dict, autoselect_config) -> Dict:
        """
        Apply default settings to an autoselect model configuration.
        
        Priority order:
        1. Model-specific settings (highest priority)
        2. Autoselect default settings
        3. Auto-derived from first model in rotation (lowest priority)
        
        Args:
            model_config: The model configuration dict (typically a rotation_id from autoselect)
            autoselect_config: The autoselect configuration
            
        Returns:
            Model dict with defaults applied
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # List of fields that can have defaults
        default_fields = [
            'rate_limit',
            'max_request_tokens',
            'rate_limit_TPM',
            'rate_limit_TPH',
            'rate_limit_TPD',
            'context_size',
            'condense_context',
            'condense_method'
        ]
        
        # First, check if the model_config is a rotation ID and get its settings
        model_id = model_config.get('model_id') or model_config.get('name') or model_config.get('id', '')
        
        # Try to get defaults from the referenced rotation (first model in the rotation)
        if self.user_id and model_id in self.rotations:
            rotation_config = self.rotations[model_id]
        elif model_id in self.config.rotations:
            rotation_config = self.config.rotations[model_id]
            
            # Check each default field
            for field in default_fields:
                # If field is not set in model, try autoselect defaults, then rotation defaults
                if field not in model_config or model_config.get(field) is None:
                    # Try autoselect defaults first
                    autoselect_default = getattr(autoselect_config, f'default_{field}', None)
                    if autoselect_default is not None:
                        model_config[field] = autoselect_default
                        logger.debug(f"Applied autoselect default_{field}: {autoselect_default} to model {model_id}")
                    else:
                        # Try rotation defaults
                        rotation_default = getattr(rotation_config, f'default_{field}', None)
                        if rotation_default is not None:
                            model_config[field] = rotation_default
                            logger.debug(f"Applied rotation default_{field}: {rotation_default} to model {model_id}")
                        else:
                            # Auto-derive from first provider in rotation, then first model
                            if rotation_config.providers and len(rotation_config.providers) > 0:
                                first_provider = rotation_config.providers[0]
                                provider_id = first_provider.get('provider_id')
                                provider_config = self.config.get_provider(provider_id)
                                
                                if provider_config and getattr(provider_config, "models", []) and len(getattr(provider_config, "models", [])) > 0:
                                    first_model = getattr(provider_config, "models", [])[0]
                                    # Check for context_size, context_window, or context_length
                                    if field == 'context_size':
                                        model_field = getattr(first_model, 'context_size', None)
                                        if model_field is None:
                                            model_field = getattr(first_model, 'context_window', None)
                                        if model_field is None:
                                            model_field = getattr(first_model, 'context_length', None)
                                    else:
                                        model_field = getattr(first_model, field, None)
                                    if model_field is not None:
                                        model_config[field] = model_field
                                        logger.debug(f"Auto-derived default_{field}: {model_field} from first model in {provider_id}")
        else:
            # Not a rotation, apply autoselect defaults directly
            for field in default_fields:
                if field not in model_config or model_config.get(field) is None:
                    autoselect_default = getattr(autoselect_config, f'default_{field}', None)
                    if autoselect_default is not None:
                        model_config[field] = autoselect_default
        
        return model_config

    async def _handle_chunked_rotation_request(
        self,
        handler,
        model_name: str,
        messages: List[Dict],
        max_tokens: Optional[int],
        temperature: float,
        stream: bool,
        tools: Optional[List[Dict]],
        tool_choice: Optional[Union[str, Dict]],
        max_request_tokens: int,
        provider_id: str,
        logger
    ) -> Dict:
        """
        Handle a rotation request that needs to be split into multiple chunks due to token limits.
        
        This method splits the request into chunks, sends each chunk sequentially,
        and combines the responses into a single response.
        
        Args:
            handler: The provider handler
            model_name: The model name
            messages: The messages to send
            max_tokens: Max output tokens
            temperature: Temperature setting
            stream: Whether to stream (not supported for chunked requests)
            tools: Tool definitions
            tool_choice: Tool choice setting
            max_request_tokens: Maximum tokens per request
            provider_id: Provider identifier
            logger: Logger instance
        
        Returns:
            Combined response from all chunks
        """
        logger.info(f"=== ROTATION CHUNKED REQUEST HANDLING START ===")
        logger.info(f"Max request tokens per chunk: {max_request_tokens}")
        
        # Split messages into chunks
        message_chunks = split_messages_into_chunks(messages, max_request_tokens, model_name)
        logger.info(f"Split into {len(message_chunks)} message chunks")
        
        if stream:
            logger.warning("Streaming is not supported for chunked rotation requests, falling back to non-streaming")
        
        # Process each chunk and collect responses
        all_responses = []
        combined_content = ""
        total_prompt_tokens = 0
        total_completion_tokens = 0
        created_time = int(time_module.time())
        response_id = f"chunked-rotation-{provider_id}-{model_name}-{created_time}"
        
        for chunk_idx, chunk_messages in enumerate(message_chunks):
            logger.info(f"Processing chunk {chunk_idx + 1}/{len(message_chunks)}")
            logger.info(f"Chunk messages count: {len(chunk_messages)}")
            
            # Apply rate limiting between chunks
            if chunk_idx > 0:
                await handler.apply_rate_limit()
            
            try:
                chunk_response = await handler.handle_request(
                    model=model_name,
                    messages=chunk_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=False,  # Always non-streaming for chunked requests
                    tools=tools if chunk_idx == 0 else None,  # Only first chunk uses tools
                    tool_choice=tool_choice if chunk_idx == 0 else None
                )
                
                # Extract content from response
                if isinstance(chunk_response, dict):
                    choices = chunk_response.get('choices', [])
                    if choices:
                        content = choices[0].get('message', {}).get('content', '')
                        combined_content += content
                        
                        # Accumulate token usage
                        usage = chunk_response.get('usage', {})
                        chunk_total_tokens = usage.get('total_tokens', 0)
                        total_prompt_tokens += usage.get('prompt_tokens', 0)
                        total_completion_tokens += usage.get('completion_tokens', 0)
                        
                        # Record token usage for rate limit tracking
                        if chunk_total_tokens > 0:
                            handler._record_token_usage(model_name, chunk_total_tokens)
                            logger.info(f"Recorded {chunk_total_tokens} tokens for chunk {chunk_idx + 1}")
                
                all_responses.append(chunk_response)
                logger.info(f"Chunk {chunk_idx + 1} processed successfully")
                
            except Exception as e:
                logger.error(f"Error processing chunk {chunk_idx + 1}: {e}")
                # If a chunk fails, we still try to return what we have
                if all_responses:
                    logger.warning("Returning partial results from successful chunks")
                    break
                else:
                    raise e
        
        # Build combined response
        combined_response = {
            "id": response_id,
            "object": "chat.completion",
            "created": created_time,
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": combined_content
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens
            },
            "aisbf_chunked": True,
            "aisbf_total_chunks": len(message_chunks)
        }
        
        logger.info(f"=== ROTATION CHUNKED REQUEST HANDLING END ===")
        logger.info(f"Combined content length: {len(combined_content)} characters")
        logger.info(f"Total chunks processed: {len(all_responses)}")
        
        return combined_response

    def _get_api_key(self, provider_id: str, rotation_api_key: Optional[str] = None) -> Optional[str]:
        """
        Get the API key for a provider.
        
        Priority order:
        1. API key from provider config (providers.json)
        2. API key from rotation config (rotations.json)
        
        Args:
            provider_id: The provider identifier
            rotation_api_key: Optional API key from rotation configuration
            
        Returns:
            The API key to use, or None if not found
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # First check provider config for api_key
        provider_config = self.config.get_provider(provider_id)
        if provider_config and hasattr(provider_config, 'api_key') and provider_config.api_key:
            logger.info(f"Using API key from provider config for {provider_id}")
            return provider_config.api_key
        
        # Fall back to rotation api_key
        if rotation_api_key:
            logger.info(f"Using API key from rotation config for {provider_id}")
            return rotation_api_key
        
        logger.info(f"No API key found for {provider_id}")
        return None

    async def handle_rotation_request(self, rotation_id: str, request_data: Dict, user_id: Optional[int] = None, token_id: Optional[int] = None):
        """
        Handle a rotation request.

        For streaming requests, returns a StreamingResponse with proper handling
        based on the selected provider's type (google vs others).
        For non-streaming requests, returns the response dict directly.
        """
        import logging
        import time
        logger = logging.getLogger(__name__)
        # Track request start time for latency calculation
        request_start_time = time.time()
        logger.info(f"=== RotationHandler.handle_rotation_request START ===")
        logger.info(f"Rotation ID: {rotation_id}")
        logger.info(f"User ID: {self.user_id}")

        # Check for user-specific rotation config first
        if self.user_id:
            # Database user: ONLY use user-specific configs - NO global fallback
            if rotation_id not in self.rotations:
                logger.error(f"User rotation {rotation_id} not found - NO global fallback")
                raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found for this user")
            rotation_config = self.rotations[rotation_id]
            logger.info(f"Using user-specific rotation config for {rotation_id}")
        else:
            # Admin user: use global config
            rotation_config = self.config.get_rotation(rotation_id)
            logger.info(f"Using global rotation config for {rotation_id}")

        # Check response cache for non-streaming requests
        stream = request_data.get('stream', False)
        if not stream:
            try:
                aisbf_config = self.config.get_aisbf_config()
                if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                    response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                    cached_response = response_cache.get(request_data, user_id=self.user_id)
                    if cached_response:
                        logger.info(f"Cache hit for rotation request {rotation_id}")
                        return cached_response
                    else:
                        logger.debug(f"Cache miss for rotation request {rotation_id}")
            except Exception as cache_error:
                logger.warning(f"Response cache check failed: {cache_error}")

        if not rotation_config:
            logger.error(f"Rotation {rotation_id} not found")
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")
        
        # Check if notifyerrors is enabled for this rotation
        notify_errors = getattr(rotation_config, 'notifyerrors', False)
        logger.info(f"notifyerrors setting for rotation '{rotation_id}': {notify_errors}")
        
        # Extract stream setting early - needed for error handling
        stream = request_data.get('stream', False)
        logger.info(f"Request stream mode: {stream}")

        logger.info(f"Rotation config loaded successfully")
        providers = rotation_config.providers
        logger.info(f"Number of providers in rotation: {len(providers)}")
        
        # Collect all available models with their weights
        available_models = []
        skipped_providers = []
        total_models_considered = 0

        logger.info(f"=== MODEL SELECTION PROCESS START ===")
        logger.info(f"Scanning providers for available models...")
        
        for provider in providers:
            provider_id = provider['provider_id']
            logger.info(f"")
            logger.info(f"--- Processing provider: {provider_id} ---")
            
            # Check if provider exists in configuration (user-specific first, then global)
            if self.user_id and provider_id in self.user_providers:
                provider_config = self.user_providers[provider_id]
                logger.info(f"  [USER] Using user-specific provider config for {provider_id}")
            else:
                provider_config = self.config.get_provider(provider_id)
                logger.info(f"  [GLOBAL] Using global provider config for {provider_id}")

            if not provider_config:
                logger.error(f"  [ERROR] Provider {provider_id} not found in providers configuration")
                logger.error(f"  Available providers: {list(self.config.providers.keys()) if not self.user_id else list(self.user_providers.keys())}")
                logger.error(f"  Skipping this provider")
                skipped_providers.append(provider_id)
                continue
            
            # Get API key: first from provider config, then from rotation config
            api_key = self._get_api_key(provider_id, provider.get('api_key'))
            
            # Check if provider is rate limited/deactivated
            provider_handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
            if provider_handler.is_rate_limited():
                logger.warning(f"  [SKIPPED] Provider {provider_id} is rate limited/deactivated")
                logger.warning(f"  Reason: Provider has exceeded failure threshold or is in cooldown period")
                skipped_providers.append(provider_id)
                continue
            
            logger.info(f"  [AVAILABLE] Provider {provider_id} is active and ready")
            
            # Check if provider-level weight is specified
            provider_weight = provider.get('weight', 1)  # Default to 1 if not specified
            if provider.get('weight') is not None:
                logger.info(f"  Provider-level weight: {provider_weight}")
            
            # Check if models are specified in rotation config
            # If not, use models from provider config
            rotation_models = provider.get('models')
            if not rotation_models:
                logger.info(f"  No models specified in rotation config for {provider_id}")
                logger.info(f"  Will use models from provider configuration")
                
                # Get models from provider config
                if getattr(provider_config, "models", []):
                    # Use models from provider config with provider-level weight
                    rotation_models = []
                    for provider_model in getattr(provider_config, "models", []):
                        model_dict = {
                            'name': provider_model.name,
                            'weight': provider_weight,  # Use provider-level weight
                            'rate_limit': provider_model.rate_limit,
                            'max_request_tokens': provider_model.max_request_tokens,
                            'nsfw': getattr(provider_model, 'nsfw', False),
                            'privacy': getattr(provider_model, 'privacy', False)
                        }
                        rotation_models.append(model_dict)
                    logger.info(f"  Loaded {len(rotation_models)} model(s) from provider config with weight {provider_weight}")
                else:
                    logger.warning(f"  No models defined in provider config for {provider_id}")
                    logger.warning(f"  Skipping this provider")
                    skipped_providers.append(provider_id)
                    continue
            
            models_in_provider = len(rotation_models)
            total_models_considered += models_in_provider
            logger.info(f"  Found {models_in_provider} model(s) in this provider")
            
            for model in rotation_models:
                # Apply defaults: model-specific > rotation defaults > provider defaults
                model = self._apply_defaults_to_model(model, provider_config, rotation_config)
                
                model_name = model['name']
                model_weight = model['weight']
                model_rate_limit = model.get('rate_limit', 'N/A')
                
                logger.info(f"    - Model: {model_name}")
                logger.info(f"      Weight (Priority): {model_weight}")
                logger.info(f"      Rate Limit: {model_rate_limit}")
                
                # Add provider_id and api_key to model for later use
                # Use resolved api_key (from provider config or rotation config)
                model_with_provider = model.copy()
                model_with_provider['provider_id'] = provider_id
                model_with_provider['api_key'] = api_key
                available_models.append(model_with_provider)

        logger.info(f"")
        logger.info(f"=== MODEL SELECTION SUMMARY ===")
        logger.info(f"Total providers scanned: {len(providers)}")
        logger.info(f"Providers skipped (rate limited): {len(skipped_providers)}")
        if skipped_providers:
            logger.info(f"Skipped providers: {', '.join(skipped_providers)}")
        logger.info(f"Total models considered: {total_models_considered}")
        logger.info(f"Total models available: {len(available_models)}")
        
        # Apply NSFW/Privacy content classification filtering
        # Only classify the immediate intent (last 3 messages + current query) to avoid
        # huge context issues and long classification times
        aisbf_config = self.config.get_aisbf_config()
        if aisbf_config and (aisbf_config.classify_nsfw or aisbf_config.classify_privacy):
            logger.info(f"=== CONTENT CLASSIFICATION FILTERING ===")
            
            # Get messages for classification - only last 3 user messages + current query
            messages = request_data.get('messages', [])
            
            # Extract last 3 user messages for classification window
            recent_user_messages = []
            for msg in reversed(messages):
                if msg.get('role') == 'user':
                    content = msg.get('content', '')
                    if isinstance(content, str):
                        recent_user_messages.append(content)
                        if len(recent_user_messages) >= 3:
                            break
            
            # Build the classification prompt from recent messages only
            # Reverse to get correct order (oldest first)
            recent_user_messages.reverse()
            user_prompt = " ".join(recent_user_messages)
            
            logger.info(f"Classifying only recent context ({len(recent_user_messages)} messages))")
            logger.info(f"Recent context preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"Recent context: {user_prompt}")
            logger.info(f"Classify NSFW: {aisbf_config.classify_nsfw}")
            logger.info(f"Classify privacy: {aisbf_config.classify_privacy}")
            
            # Check if content classification is needed
            check_nsfw = aisbf_config.classify_nsfw
            check_privacy = aisbf_config.classify_privacy
            
            if check_nsfw or check_privacy:
                # Initialize classifier with models from config
                internal_model_config = aisbf_config.internal_model or {}
                nsfw_model = internal_model_config.get('nsfw_classifier')
                privacy_model = internal_model_config.get('privacy_classifier')
                
                content_classifier.initialize(nsfw_model, privacy_model)
                
                # Check user prompt for NSFW/privacy content
                is_safe, message = content_classifier.check_content(
                    user_prompt, 
                    check_nsfw=check_nsfw, 
                    check_privacy=check_privacy
                )
                
                logger.info(f"Content classification result: {message}")
                
                if not is_safe:
                    # Content is flagged - filter to only nsfw=True or privacy=True models
                    logger.info(f"Content flagged - filtering available models")
                    
                    if check_nsfw and not check_privacy:
                        # Only NSFW filtering needed
                        original_count = len(available_models)
                        available_models = [m for m in available_models if m.get('nsfw', False)]
                        logger.info(f"NSFW filtering: {original_count} -> {len(available_models)} models")
                    elif check_privacy and not check_nsfw:
                        # Only privacy filtering needed
                        original_count = len(available_models)
                        available_models = [m for m in available_models if m.get('privacy', False)]
                        logger.info(f"Privacy filtering: {original_count} -> {len(available_models)} models")
                    elif check_nsfw and check_privacy:
                        # Both filtering - need models with EITHER flag
                        original_count = len(available_models)
                        available_models = [m for m in available_models if m.get('nsfw', False) or m.get('privacy', False)]
                        logger.info(f"NSFW+Privacy filtering: {original_count} -> {len(available_models)} models")
            
            logger.info(f"=== CONTENT CLASSIFICATION FILTERING END ===")
        
        # Check if rotation-level nsfw/privacy flags also apply
        rotation_nsfw = getattr(rotation_config, 'nsfw', False)
        rotation_privacy = getattr(rotation_config, 'privacy', False)
        
        if rotation_nsfw or rotation_privacy:
            logger.info(f"=== ROTATION-LEVEL CONTENT FLAGS ===")
            logger.info(f"Rotation nsfw: {rotation_nsfw}, privacy: {rotation_privacy}")
            
            # If rotation explicitly allows NSFW content, keep models that can handle it
            # If rotation explicitly allows Privacy content, keep models that can handle it
            if rotation_nsfw:
                logger.info(f"Rotation allows NSFW content - keeping models that support it")
            if rotation_privacy:
                logger.info(f"Rotation allows Privacy content - keeping models that support it")
        
        if not available_models:
            logger.error("No models available in rotation (all providers may be rate limited)")
            logger.error("All providers in this rotation are currently deactivated")
            logger.info(f"notifyerrors setting: {notify_errors}")
            
            # Build detailed error message with provider status information
            error_details = []
            error_details.append(f"No models available in rotation '{rotation_id}'. Details:")
            error_details.append("")
            error_details.append(f"**Total providers in rotation:** {len(providers)}")
            error_details.append(f"**Providers skipped (rate limited):** {len(skipped_providers)}")
            
            if skipped_providers:
                error_details.append("")
                error_details.append("**Skipped providers:**")
                for provider_id in skipped_providers:
                    provider_config = self.config.get_provider(provider_id)
                    if provider_config:
                        error_tracking = config.error_tracking.get(provider_id, {})
                        disabled_until = error_tracking.get('disabled_until')
                        failures = error_tracking.get('failures', 0)
                        
                        if disabled_until:
                            import time
                            cooldown_remaining = int(disabled_until - time.time())
                            if cooldown_remaining > 0:
                                error_details.append(f"• {provider_id}: Rate limited (cooldown: {cooldown_remaining}s remaining, failures: {failures})")
                            else:
                                error_details.append(f"• {provider_id}: Rate limited (cooldown expired, failures: {failures})")
                        else:
                            error_details.append(f"• {provider_id}: Rate limited (failures: {failures})")
                    else:
                        error_details.append(f"• {provider_id}: Not configured")
            
            # Check if notifyerrors is enabled - if so, return error as normal message instead of HTTP 503
            logger.info(f"Checking notifyerrors: {notify_errors}")
            if notify_errors:
                logger.info(f"notifyerrors is enabled for rotation '{rotation_id}', returning error as normal message")
                # Return a normal response with error message instead of HTTP 503
                error_message = f"All providers in rotation '{rotation_id}' failed. Details:\n{chr(10).join(error_details[1:])}"
                error_response = {
                    "id": f"error-{rotation_id}-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": rotation_id,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": error_message
                        },
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": len(error_message),
                        "total_tokens": len(error_message)
                    },
                    "aisbf_error": True,
                    "rotation_id": rotation_id,
                    "error_details": error_details
                }
                # For streaming requests, wrap in a simple streaming response
                if stream:
                    return self._create_error_streaming_response(error_response)
                else:
                    return error_response
            else:
                logger.info(f"notifyerrors is disabled for rotation '{rotation_id}', returning error with status code 429")
                # Return a normal response with error message and status code 429
                error_message = f"All providers in rotation '{rotation_id}' failed. Details:\n{chr(10).join(error_details[1:])}"
                error_response = {
                    "id": f"error-{rotation_id}-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": rotation_id,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": error_message
                        },
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": len(error_message),
                        "total_tokens": len(error_message)
                    },
                    "aisbf_error": True,
                    "rotation_id": rotation_id,
                    "error_details": error_details
                }
                # For streaming requests, wrap in a simple streaming response
                if stream:
                    return self._create_error_streaming_response(error_response, status_code=429)
                else:
                    return JSONResponse(status_code=429, content=error_response)

        # Sort models by weight in descending order (higher weight = higher priority)
        available_models.sort(key=lambda m: m['weight'], reverse=True)
        
        logger.info(f"")
        logger.info(f"=== PRIORITY-BASED SELECTION ===")
        logger.info(f"Models sorted by weight (descending priority):")
        for idx, model in enumerate(available_models, 1):
            logger.info(f"  {idx}. {model['name']} (provider: {model['provider_id']}, weight: {model['weight']})")

        # Find the highest weight
        highest_weight = available_models[0]['weight']
        logger.info(f"")
        logger.info(f"Highest priority weight: {highest_weight}")

        # Filter models with the highest weight
        highest_weight_models = [m for m in available_models if m['weight'] == highest_weight]
        logger.info(f"Models with highest priority ({highest_weight}): {len(highest_weight_models)}")
        for model in highest_weight_models:
            logger.info(f"  - {model['name']} (provider: {model['provider_id']})")

        # If multiple models have the same highest weight, randomly select among them
        import random
        if len(highest_weight_models) > 1:
            logger.info(f"Multiple models with same highest priority - performing random selection")
            selected_model = random.choice(highest_weight_models)
            logger.info(f"Randomly selected from {len(highest_weight_models)} candidates")
        else:
            selected_model = highest_weight_models[0]
            logger.info(f"Single model with highest priority - deterministic selection")
        
        logger.info(f"")
        logger.info(f"=== FINAL SELECTION ===")
        logger.info(f"Selected model: {selected_model['name']}")
        logger.info(f"Selected provider: {selected_model['provider_id']}")
        logger.info(f"Model weight (priority): {selected_model['weight']}")
        logger.info(f"Model rate limit: {selected_model.get('rate_limit', 'N/A')}")
        logger.info(f"=== MODEL SELECTION PROCESS END ===")

        # Retry logic: Try up to 5 times, allowing model retries with rate limiting
        max_retries = 5
        tried_models = []  # Track which models have been tried
        model_retry_counts = {}  # Track retry count per model
        last_error = None
        successful_model = None
        successful_handler = None
        successful_response = None
        
        for attempt in range(max_retries):
            logger.info(f"")
            logger.info(f"=== ATTEMPT {attempt + 1}/{max_retries} ===")
            
            # Select a model that hasn't been tried yet, or retry a failed model with rate limiting
            remaining_models = [m for m in available_models if m not in tried_models]
            
            if not remaining_models:
                logger.error(f"No more models available to try")
                logger.error(f"All {len(available_models)} models have been attempted")
                break
            
            # Sort remaining models by weight and select the best one
            remaining_models.sort(key=lambda m: m['weight'], reverse=True)
            current_model = remaining_models[0]
            
            # Check if this model has been retried too many times
            model_key = f"{current_model['provider_id']}:{current_model['name']}"
            retry_count = model_retry_counts.get(model_key, 0)
            
            if retry_count >= 2:  # Max 2 retries per model
                logger.warning(f"Model {current_model['name']} has reached max retry count, skipping")
                tried_models.append(current_model)
                continue
            
            logger.info(f"Trying model: {current_model['name']} (provider: {current_model['provider_id']})")
            logger.info(f"Attempt {attempt + 1} of {max_retries}")
            logger.info(f"Model retry count: {retry_count}")
            
            provider_id = current_model['provider_id']
            api_key = current_model.get('api_key')
            model_name = current_model['name']
            
            logger.info(f"Getting provider handler for {provider_id}")
            handler = get_provider_handler(provider_id, api_key, user_id=self.user_id)
            logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

            if handler.is_rate_limited():
                logger.warning(f"Provider {provider_id} is rate limited, skipping to next model")
                continue
            
            # Check token rate limits for this model
            request_tokens = count_messages_tokens(request_data['messages'], model_name)
            if handler._check_token_rate_limit(model_name, request_tokens):
                logger.warning(f"Model {model_name} would exceed token rate limit, skipping to next model")
                # Determine which limit was exceeded and disable provider accordingly
                model_config = current_model
                if model_config.get('rate_limit_TPM'):
                    handler._disable_provider_for_duration("1m")
                    logger.warning(f"Provider {provider_id} disabled for 1 minute due to TPM limit")
                elif model_config.get('rate_limit_TPH'):
                    handler._disable_provider_for_duration("1h")
                    logger.warning(f"Provider {provider_id} disabled for 1 hour due to TPH limit")
                elif model_config.get('rate_limit_TPD'):
                    handler._disable_provider_for_duration("1d")
                    logger.warning(f"Provider {provider_id} disabled for 1 day due to TPD limit")
                continue
            
            try:
                logger.info(f"Model requested: {model_name}")
                logger.info(f"Messages count: {len(request_data.get('messages', []))}")
                logger.info(f"Max tokens: {request_data.get('max_tokens')}")
                logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
                logger.info(f"Stream: {request_data.get('stream', False)}")
                
                # Get context configuration
                context_config = get_context_config_for_model(
                    model_name=model_name,
                    provider_config=None,
                    rotation_model_config=current_model
                )
                logger.info(f"Context config: {context_config}")
                
                # Calculate effective context
                messages = request_data['messages']
                effective_context = count_messages_tokens(messages, model_name)
                logger.info(f"Effective context: {effective_context} tokens")
                
                # Apply context condensation if needed
                if context_config.get('condense_context', 0) > 0:
                    context_manager = ContextManager(context_config, handler, self.config.get_condensation(), self.user_id)
                    if context_manager.should_condense(messages, model_name):
                        logger.info("Context condensation triggered")
                        messages = await context_manager.condense_context(messages, model_name)
                        effective_context = count_messages_tokens(messages, model_name)
                        logger.info(f"Condensed effective context: {effective_context} tokens")
                    # Update request_data with condensed messages
                    request_data['messages'] = messages
                
                # Check for max_request_tokens in rotation model config
                max_request_tokens = current_model.get('max_request_tokens')
                if max_request_tokens:
                    # Count tokens in the request
                    request_tokens = count_messages_tokens(request_data['messages'], model_name)
                    logger.info(f"Request tokens: {request_tokens}, max_request_tokens: {max_request_tokens}")
                    
                    if request_tokens > max_request_tokens:
                        logger.info(f"Request exceeds max_request_tokens, will split into chunks")
                        
                        # Apply rate limiting
                        logger.info("Applying rate limiting...")
                        await handler.apply_rate_limit()
                        logger.info("Rate limiting applied")
                        
                        # Handle as chunked request
                        response = await self._handle_chunked_rotation_request(
                            handler=handler,
                            model_name=model_name,
                            messages=request_data['messages'],
                            max_tokens=request_data.get('max_tokens'),
                            temperature=request_data.get('temperature', 1.0),
                            stream=request_data.get('stream', False),
                            tools=request_data.get('tools'),
                            tool_choice=request_data.get('tool_choice'),
                            max_request_tokens=max_request_tokens,
                            provider_id=provider_id,
                            logger=logger
                        )
                        
                        handler.record_success()
                        logger.info(f"=== RotationHandler.handle_rotation_request END ===")
                        logger.info(f"Request succeeded on attempt {attempt + 1}")
                        logger.info(f"Successfully used model: {model_name} (provider: {provider_id})")
                        
                        # Check if response is a streaming request
                        is_streaming = request_data.get('stream', False)
                        if is_streaming:
                            # Get provider type from configuration for proper streaming handling
                            provider_type = self._get_provider_type(provider_id)
                            logger.info(f"Returning streaming response for provider type: {provider_type}")
                            return self._create_streaming_response(
                                response=response,
                                provider_type=provider_type,
                                provider_id=provider_id,
                                model_name=model_name,
                                handler=handler,
                                request_data=request_data,
                                effective_context=effective_context
                            )
                        else:
                            # Cache the response for non-streaming chunked requests
                            try:
                                aisbf_config = self.config.get_aisbf_config()
                                if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                                    response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                                    response_cache.set(request_data, response, user_id=self.user_id)
                                    logger.debug(f"Cached chunked response for rotation request {rotation_id}")
                            except Exception as cache_error:
                                logger.warning(f"Response cache set failed for chunked request: {cache_error}")
                            
                            logger.info("Returning non-streaming response")
                            return response
                
                # Apply model-specific rate limiting
                rate_limit = current_model.get('rate_limit')
                logger.info(f"Model-specific rate limit: {rate_limit}")
                logger.info("Applying model-level rate limiting...")
                await handler.apply_model_rate_limit(model_name, rate_limit)
                logger.info("Model-level rate limiting applied")

                logger.info(f"Sending request to provider handler...")
                response = await handler.handle_request(
                    model=model_name,
                    messages=request_data['messages'],
                    max_tokens=request_data.get('max_tokens'),
                    temperature=request_data.get('temperature', 1.0),
                    stream=request_data.get('stream', False),
                    tools=request_data.get('tools'),
                    tool_choice=request_data.get('tool_choice')
                )
                logger.info(f"Response received from provider")
                logger.info(f"Response type: {type(response)}")
                
                # Record token usage for rate limit tracking
                if isinstance(response, dict):
                    usage = response.get('usage', {})
                    total_tokens = usage.get('total_tokens', 0)
                    if total_tokens > 0:
                        handler._record_token_usage(model_name, total_tokens)
                        logger.info(f"Recorded {total_tokens} tokens for model {model_name}")
                    
                    # Add effective context to response for non-streaming
                    usage['effective_context'] = effective_context
                    logger.info(f"Added effective_context to response: {effective_context}")
                
                handler.record_success()
                
                # Update successful variables to the ones that worked
                successful_model = current_model
                successful_handler = handler
                successful_response = response
                
                logger.info(f"=== RotationHandler.handle_rotation_request END ===")
                logger.info(f"Request succeeded on attempt {attempt + 1}")
                logger.info(f"Successfully used model: {successful_model['name']} (provider: {successful_model['provider_id']})")
                
                # Check if response is a streaming request
                is_streaming = request_data.get('stream', False)
                if is_streaming:
                    # Get provider type from configuration for proper streaming handling
                    provider_type = self._get_provider_type(provider_id)
                    logger.info(f"Returning streaming response for provider type: {provider_type}")
                    return self._create_streaming_response(
                        response=response,
                        provider_type=provider_type,
                        provider_id=provider_id,
                        model_name=model_name,
                        handler=handler,
                        request_data=request_data,
                        effective_context=effective_context
                    )
                else:
                    # Cache the response for non-streaming requests
                    try:
                        aisbf_config = self.config.get_aisbf_config()
                        if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                            response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                            response_cache.set(request_data, response, user_id=self.user_id)
                            logger.debug(f"Cached response for rotation request {rotation_id}")
                    except Exception as cache_error:
                        logger.warning(f"Response cache set failed: {cache_error}")
                    
                    logger.info("Returning non-streaming response")
                    
                    # Record analytics for token usage
                    try:
                        analytics = get_analytics()
                        if response and isinstance(response, dict):
                            usage = response.get('usage', {})
                            total_tokens = usage.get('total_tokens', 0)
                            prompt_tokens = usage.get('prompt_tokens', 0)
                            completion_tokens = usage.get('completion_tokens', 0)
                            
                            # If no token usage provided, estimate it
                            if total_tokens == 0:
                                try:
                                    messages = request_data.get('messages', [])
                                    estimated_prompt_tokens = count_messages_tokens(messages, model_name)
                                    
                                    # More realistic completion estimate
                                    max_tokens = request_data.get('max_tokens', 0)
                                    if max_tokens > 0:
                                        estimated_completion = min(max_tokens, estimated_prompt_tokens * 2)
                                    else:
                                        estimated_completion = max(estimated_prompt_tokens, 50)
                                    
                                    total_tokens = estimated_prompt_tokens + estimated_completion
                                    prompt_tokens = estimated_prompt_tokens
                                    completion_tokens = estimated_completion
                                    logger.debug(f"Estimated token usage for rotation: {total_tokens}")
                                except Exception as est_error:
                                    logger.debug(f"Token estimation failed: {est_error}")
                                    total_tokens = 150
                                    prompt_tokens = 0
                                    completion_tokens = 0
                            
                            # Try to extract actual cost from provider response
                            from ..cost_extractor import extract_cost_from_response
                            actual_cost = extract_cost_from_response(response, provider_id)
                            
                            # Always record analytics
                            analytics.record_request(
                                provider_id=provider_id,
                                model_name=model_name,
                                tokens_used=total_tokens,
                                latency_ms=(time.time() - request_start_time) * 1000,
                                success=True,
                                rotation_id=rotation_id,
                                user_id=user_id,
                                token_id=token_id,
                                prompt_tokens=prompt_tokens if prompt_tokens > 0 else None,
                                completion_tokens=completion_tokens if completion_tokens > 0 else None,
                                actual_cost=actual_cost
                            )
                    except Exception as analytics_error:
                        logger.warning(f"Analytics recording failed: {analytics_error}")
                    
                    return response
            except Exception as e:
                last_error = str(e)
                handler.record_failure()
                
                # Increment retry count for this model
                model_retry_counts[model_key] = retry_count + 1
                
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                logger.error(f"Error type: {type(e).__name__}")
                logger.error(f"Model retry count: {model_retry_counts[model_key]}")
                
                # If this is the first failure for this model, allow retry with rate limiting
                if model_retry_counts[model_key] < 2:
                    logger.info(f"Will retry model {model_name} with rate limiting...")
                    continue
                else:
                    logger.error(f"Model {model_name} has failed too many times, moving to next model...")
                    tried_models.append(current_model)
                    continue
        
        # All retries exhausted
        logger.error(f"")
        logger.error(f"=== ALL RETRIES EXHAUSTED ===")
        logger.error(f"Attempted {len(tried_models)} different model(s): {[m['name'] for m in tried_models]}")
        logger.error(f"Last error: {last_error}")
        logger.error(f"Max retries ({max_retries}) reached without success")
        
        # Record analytics for failed rotation request
        try:
            analytics = get_analytics()
            # Calculate latency
            latency_ms = (time.time() - request_start_time) * 1000
            logger.info(f"Failed Rotation Analytics: latency_ms={latency_ms:.2f}")
            
            # Estimate tokens for failed request
            try:
                messages = request_data.get('messages', [])
                estimated_tokens = count_messages_tokens(messages, rotation_id)
                total_tokens = estimated_tokens
                prompt_tokens = estimated_tokens
                completion_tokens = 0
            except Exception:
                total_tokens = 50  # Minimal estimate for failed requests
                prompt_tokens = 50
                completion_tokens = 0
            
            analytics.record_request(
                provider_id='rotation',
                model_name=rotation_id,
                tokens_used=total_tokens,
                latency_ms=latency_ms,
                success=False,
                error_type='RotationFailure',
                rotation_id=rotation_id,
                user_id=user_id,
                token_id=token_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                actual_cost=None
            )
        except Exception as analytics_error:
            logger.warning(f"Analytics recording for failed rotation failed: {analytics_error}")
        
        # Build detailed error message
        error_details = []
        error_details.append(f"All providers in rotation '{rotation_id}' failed after {max_retries} attempts. Details:")
        error_details.append("")
        error_details.append(f"**Attempted models:**")
        error_details.append(f"{[m['name'] for m in tried_models]}")
        error_details.append("")
        
        # Format last error with JSON indentation if it contains JSON
        try:
            # Check if last_error contains JSON-like structure
            if '{' in last_error or '[' in last_error:
                # Try to extract and format JSON
                import json
                # Find JSON start and end
                json_start = last_error.find('{') if '{' in last_error else last_error.find('[')
                if json_start != -1:
                    json_end = last_error.rfind('}') + 1 if '{' in last_error else last_error.rfind(']') + 1
                    json_str = last_error[json_start:json_end]
                    try:
                        # Prettify JSON
                        parsed_json = json.loads(json_str)
                        formatted_json = json.dumps(parsed_json, indent=2)
                        # Replace JSON part with formatted version
                        error_part = last_error[:json_start]
                        error_details.append(f"**Last error:** {error_part}")
                        error_details.append(f"```json\n{formatted_json}\n```")
                    except Exception:
                        error_details.append(f"**Last error:**")
                        error_details.append(f"{last_error}")
                else:
                    error_details.append(f"**Last error:**")
                    error_details.append(f"{last_error}")
            else:
                error_details.append(f"**Last error:**")
                error_details.append(f"{last_error}")
        except Exception:
            error_details.append(f"**Last error:**")
            error_details.append(f"{last_error}")
        
        error_details.append("")
        error_details.append("**Provider status:**")
        for provider in providers:
            provider_id = provider['provider_id']
            provider_config = self.config.get_provider(provider_id)
            if provider_config:
                error_tracking = config.error_tracking.get(provider_id, {})
                disabled_until = error_tracking.get('disabled_until')
                failures = error_tracking.get('failures', 0)
                
                if disabled_until:
                    import time
                    cooldown_remaining = int(disabled_until - time.time())
                    if cooldown_remaining > 0:
                        error_details.append(f"• {provider_id}: Rate limited (cooldown: {cooldown_remaining}s remaining, failures: {failures})")
                    else:
                        error_details.append(f"• {provider_id}: Rate limited (cooldown expired, failures: {failures})")
                else:
                    error_details.append(f"• {provider_id}: Available (failures: {failures})")
            else:
                error_details.append(f"• {provider_id}: Not configured")
        
        # Check if notifyerrors is enabled - if so, return error as normal message instead of HTTP 503
        # Get stream parameter from request_data to determine response type
        stream = request_data.get('stream', False)
        logger.info(f"Request stream mode: {stream}")
        
        if notify_errors:
            logger.info(f"notifyerrors is enabled for rotation '{rotation_id}', returning error as normal message")
            # Return a normal response with error message instead of HTTP 503
            error_message = f"All providers in rotation '{rotation_id}' failed after {max_retries} attempts. Details:\n{chr(10).join(error_details[1:])}"
            error_response = {
                "id": f"error-{rotation_id}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": rotation_id,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": error_message
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": len(error_message),
                    "total_tokens": len(error_message)
                },
                "aisbf_error": True,
                "rotation_id": rotation_id,
                "attempted_models": [m['name'] for m in tried_models],
                "attempted_count": len(tried_models),
                "max_retries": max_retries,
                "last_error": last_error,
                "error_details": error_details
            }
            # For streaming requests, wrap in a simple streaming response
            if stream:
                return self._create_error_streaming_response(error_response)
            else:
                return error_response
        else:
            logger.info(f"notifyerrors is disabled for rotation '{rotation_id}', returning error with status code 429")
            # Return a normal response with error message and status code 429
            error_message = f"All providers in rotation '{rotation_id}' failed after {max_retries} attempts. Details:\n{chr(10).join(error_details[1:])}"
            error_response = {
                "id": f"error-{rotation_id}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": rotation_id,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": error_message
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": len(error_message),
                    "total_tokens": len(error_message)
                },
                "aisbf_error": True,
                "rotation_id": rotation_id,
                "attempted_models": [m['name'] for m in tried_models],
                "attempted_count": len(tried_models),
                "max_retries": max_retries,
                "last_error": last_error,
                "error_details": error_details
            }
            # For streaming requests, wrap in a simple streaming response
            if stream:
                return self._create_error_streaming_response(error_response, status_code=429)
            else:
                return JSONResponse(status_code=429, content=error_response)

    def _create_error_streaming_response(self, error_response: Dict, status_code: int = 200):
        """
        Create a simple StreamingResponse for error messages.
        
        This is used when notifyerrors is enabled and we need to return
        an error as a streaming response instead of raising an HTTPException.
        
        Args:
            error_response: The error response dict to stream
            status_code: The HTTP status code to return (default: 200)
        
        Returns:
            StreamingResponse with the error response in OpenAI-compatible streaming format
        """
        import json
        import time
        
        # Extract values from error_response for proper streaming format
        response_id = error_response.get('id', f"error-{int(time.time())}")
        created = error_response.get('created', int(time.time()))
        model = error_response.get('model', 'unknown')
        content = error_response.get('choices', [{}])[0].get('message', {}).get('content', '')
        
        async def error_stream_generator():
            # First chunk: role and content
            chunk_with_role = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk_with_role)}\n\n".encode('utf-8')
            
            # Final chunk: finish_reason and usage
            final_chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }],
                "usage": error_response.get('usage', {
                    "prompt_tokens": 0,
                    "completion_tokens": len(content),
                    "total_tokens": len(content)
                })
            }
            yield f"data: {json.dumps(final_chunk)}\n\n".encode('utf-8')
            # Yield control to event loop to ensure chunk is flushed to client
            await asyncio.sleep(0)
            
            # Send [DONE] marker
            yield b"data: [DONE]\n\n"
            # Final flush to ensure all buffered data reaches the client
            await asyncio.sleep(0)
        
        return StreamingResponse(error_stream_generator(), media_type="text/event-stream", status_code=status_code)

    def _create_streaming_response(self, response, provider_type: str, provider_id: str, model_name: str, handler, request_data: Dict, effective_context: int):
        """
        Create a StreamingResponse with proper handling based on provider type.
        
        Args:
            response: The streaming response from the provider handler
            provider_type: The type of provider (e.g., 'google', 'openai', 'anthropic')
            provider_id: The provider identifier from configuration
            model_name: The model name being used
            handler: The provider handler (for recording success/failure)
            request_data: The original request data
            effective_context: The effective context (total tokens used)
        
        Returns:
            StreamingResponse with appropriate generator for the provider type
        """
        import logging
        import time
        import json
        logger = logging.getLogger(__name__)
        
        # Check if this is a Google or Kilo provider based on configuration
        is_google_provider = provider_type == 'google'
        is_kilo_provider = provider_type in ('kilo', 'kilocode')
        logger.info(f"Creating streaming response for provider type: {provider_type}, is_google: {is_google_provider}, is_kilo: {is_kilo_provider}")
        
        # Generate system_fingerprint for this request
        # If seed is present in request, generate unique fingerprint per request
        seed = request_data.get('seed')
        system_fingerprint = generate_system_fingerprint(provider_id, seed)
        
        async def stream_generator(effective_context):
            import json
            try:
                if is_google_provider:
                    # Handle Google's streaming response
                    # Google provider returns an async generator
                    # Note: Google returns accumulated text, so we need to track and send only deltas
                    chunk_id = 0
                    accumulated_text = ""  # Track text we've already sent
                    accumulated_tool_calls = []  # Track tool calls we've already sent
                    created_time = int(time.time())
                    response_id = f"google-{model_name}-{created_time}"
                    
                    # Track completion tokens for Google responses (since Google doesn't provide them)
                    completion_tokens = 0
                    accumulated_response_text = ""  # Track full response for token counting
                    
                    # Collect all chunks first to know when we're at the last one
                    chunks_list = []
                    async for chunk in response:
                        chunks_list.append(chunk)
                    
                    total_chunks = len(chunks_list)
                    chunk_idx = 0
                    
                    for chunk in chunks_list:
                        try:
                            logger.debug(f"Google chunk type: {type(chunk)}")
                            logger.debug(f"Google chunk: {chunk}")
                            
                            # Extract text and tool calls from Google chunk (this is accumulated text)
                            chunk_text = ""
                            chunk_tool_calls = []
                            finish_reason = None
                            try:
                                if hasattr(chunk, 'candidates') and chunk.candidates:
                                    candidate = chunk.candidates[0] if chunk.candidates else None
                                    if candidate and hasattr(candidate, 'content') and candidate.content:
                                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                            for part in candidate.content.parts:
                                                # Extract text content
                                                if hasattr(part, 'text') and part.text:
                                                    chunk_text += part.text
                                                # Extract function calls (Google's format)
                                                if hasattr(part, 'function_call') and part.function_call:
                                                    function_call = part.function_call
                                                    # Convert Google function call to OpenAI format
                                                    import json
                                                    openai_tool_call = {
                                                        "id": f"call_{len(chunk_tool_calls)}",
                                                        "type": "function",
                                                        "function": {
                                                            "name": function_call.name,
                                                            "arguments": json.dumps(function_call.args) if hasattr(function_call, 'args') else "{}"
                                                        }
                                                    }
                                                    chunk_tool_calls.append(openai_tool_call)
                                                    logger.info(f"Extracted tool call from Google chunk: {openai_tool_call}")
                                    # Check for finish reason in candidate
                                    if hasattr(candidate, 'finish_reason'):
                                        google_finish = str(candidate.finish_reason)
                                        if google_finish in ('STOP', 'END_TURN', 'FINISH_REASON_UNSPECIFIED'):
                                            finish_reason = "stop"
                                        elif google_finish == 'MAX_TOKENS':
                                            finish_reason = "length"
                            except Exception as e:
                                logger.error(f"Error extracting text from Google chunk: {e}")
                            
                            # Calculate the delta (only the new text since last chunk)
                            delta_text = chunk_text[len(accumulated_text):] if chunk_text.startswith(accumulated_text) else chunk_text
                            accumulated_text = chunk_text  # Update accumulated text for next iteration
                            
                            # Track completion tokens for Google responses
                            if delta_text:
                                accumulated_response_text += delta_text
                            
                            chunk_idx += 1
                        except Exception as chunk_error:
                            error_msg = str(chunk_error)
                            logger.error(f"Error processing Google chunk: {error_msg}")
                            logger.error(f"Chunk type: {type(chunk)}")
                            logger.error(f"Chunk content: {chunk}")
                            chunk_idx += 1
                            continue
                    
                    # After collecting all chunks, check if the accumulated text contains a tool call pattern
                    # This handles models that return tool calls as text instead of using function_call attributes
                    tool_calls = None
                    final_text = accumulated_response_text
                    
                    # Check for tool call patterns in the accumulated text
                    if accumulated_response_text:
                        import re as re_module
                        
                        # Simple approach: just look for "tool: {...}" pattern and extract the JSON
                        # This avoids complex nested parsing issues
                        tool_pattern = r'tool:\s*(\{[^{}]*\{[^{}]*\}[^{}]*\}|\{[^{}]+\})'
                        tool_match = re_module.search(tool_pattern, accumulated_response_text, re_module.DOTALL)
                        
                        if tool_match:
                            try:
                                # Extract the tool JSON using brace counting for robustness
                                tool_start = accumulated_response_text.find('tool:')
                                if tool_start != -1:
                                    json_start = accumulated_response_text.find('{', tool_start)
                                    if json_start != -1:
                                        brace_count = 0
                                        json_end = json_start
                                        for i, c in enumerate(accumulated_response_text[json_start:], json_start):
                                            if c == '{':
                                                brace_count += 1
                                            elif c == '}':
                                                brace_count -= 1
                                                if brace_count == 0:
                                                    json_end = i + 1
                                                    break
                                        
                                        tool_json_str = accumulated_response_text[json_start:json_end]
                                        logger.debug(f"Extracted tool JSON: {tool_json_str[:200]}...")
                                        
                                        try:
                                            parsed_tool = json.loads(tool_json_str)
                                        except json.JSONDecodeError:
                                            # Try fixing common issues: single quotes, trailing commas
                                            fixed_json = tool_json_str.replace("'", '"')
                                            fixed_json = re_module.sub(r',\s*}', '}', fixed_json)
                                            fixed_json = re_module.sub(r',\s*]', ']', fixed_json)
                                            parsed_tool = json.loads(fixed_json)
                                        
                                        # Convert to OpenAI tool_calls format
                                        tool_calls = [{
                                            "id": f"call_0",
                                            "type": "function",
                                            "function": {
                                                "name": parsed_tool.get('action', parsed_tool.get('name', 'unknown')),
                                                "arguments": json.dumps({k: v for k, v in parsed_tool.items() if k not in ['action', 'name']})
                                            }
                                        }]
                                        logger.info(f"Converted streaming tool call to OpenAI format: {tool_calls}")
                                        
                                        # Extract final assistant text after the tool JSON
                                        # Look for pattern: }\\nassistant: [{'type': 'text', 'text': "..."}]
                                        # or just return empty since the tool call is the main content
                                        after_tool = accumulated_response_text[json_end:]
                                        assistant_pattern = r"assistant:\s*\[.*'text':\s*['\"](.+?)['\"].*\]\s*\]?\s*$"
                                        assistant_match = re_module.search(assistant_pattern, after_tool, re_module.DOTALL)
                                        if assistant_match:
                                            final_text = assistant_match.group(1)
                                            # Unescape common escape sequences
                                            final_text = final_text.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')
                                        else:
                                            final_text = ""
                            except (json.JSONDecodeError, ValueError, SyntaxError, Exception) as e:
                                logger.debug(f"Failed to parse tool JSON in streaming: {e}")
                    
                    # Now send the response chunks
                    # If we detected tool calls, send them in the first chunk with role
                    if tool_calls:
                        # First chunk with tool_calls
                        tool_chunk = {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model_name,
                            "service_tier": None,
                            "system_fingerprint": system_fingerprint,
                            "usage": None,
                            "provider": provider_id,
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "content": None,
                                    "refusal": None,
                                    "role": "assistant",
                                    "tool_calls": tool_calls
                                },
                                "finish_reason": None,
                                "logprobs": None,
                                "native_finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(tool_chunk)}\n\n".encode('utf-8')
                        
                        # If there's final assistant text, send it
                        if final_text:
                            text_chunk = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model_name,
                                "service_tier": None,
                                "system_fingerprint": system_fingerprint,
                                "usage": None,
                                "provider": provider_id,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "content": final_text,
                                        "refusal": None,
                                        "role": None,
                                        "tool_calls": None
                                    },
                                    "finish_reason": None,
                                    "logprobs": None,
                                    "native_finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(text_chunk)}\n\n".encode('utf-8')
                    else:
                        # No tool calls detected, send text normally
                        # Send the accumulated text as a single chunk
                        if accumulated_response_text:
                            text_chunk = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model_name,
                                "service_tier": None,
                                "system_fingerprint": system_fingerprint,
                                "usage": None,
                                "provider": provider_id,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "content": accumulated_response_text,
                                        "refusal": None,
                                        "role": "assistant",
                                        "tool_calls": None
                                    },
                                    "finish_reason": None,
                                    "logprobs": None,
                                    "native_finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(text_chunk)}\n\n".encode('utf-8')
                    
                    # Send final chunk with finish reason and usage statistics
                    if accumulated_response_text:
                        completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], model_name)
                    total_tokens = effective_context + completion_tokens
                    final_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model_name,
                        "service_tier": None,
                        "system_fingerprint": system_fingerprint,
                        "usage": {
                            "prompt_tokens": effective_context,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "effective_context": effective_context
                        },
                        "provider": provider_id,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "content": "",
                                "function_call": None,
                                "refusal": None,
                                "role": None,
                                "tool_calls": None
                            },
                            "finish_reason": "stop",
                            "logprobs": None,
                            "native_finish_reason": "stop"
                        }]
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n".encode('utf-8')
                    # Yield control to event loop to ensure final chunk is flushed to client
                    await asyncio.sleep(0)
                elif is_kilo_provider:
                    # Handle Kilo/KiloCode streaming response
                    # Kilo returns an async generator that yields OpenAI-compatible SSE bytes
                    accumulated_response_text = ""
                    chunk_count = 0

                    async for chunk in response:
                        chunk_count += 1
                        try:
                            # Pass through the chunk as-is (already in SSE format)
                            if isinstance(chunk, bytes):
                                # Parse to track content for token counting
                                try:
                                    chunk_str = chunk.decode('utf-8')
                                    for sse_line in chunk_str.split('\n'):
                                        sse_line = sse_line.strip()
                                        if sse_line.startswith('data: '):
                                            data_str = sse_line[6:].strip()
                                            if data_str and data_str != '[DONE]':
                                                try:
                                                    chunk_data = json.loads(data_str)
                                                    choices = chunk_data.get('choices', [])
                                                    if choices:
                                                        delta = choices[0].get('delta', {})
                                                        delta_content = delta.get('content', '')
                                                        if delta_content:
                                                            accumulated_response_text += delta_content
                                                except json.JSONDecodeError:
                                                    pass
                                except (UnicodeDecodeError, Exception):
                                    pass
                                yield chunk
                            elif isinstance(chunk, str):
                                yield chunk.encode('utf-8')
                            else:
                                yield f"data: {json.dumps(chunk)}\n\n".encode('utf-8')
                        except Exception as chunk_error:
                            logger.warning(f"Error processing Kilo chunk: {chunk_error}")
                            continue

                    logger.info(f"Kilo streaming processed {chunk_count} chunks total")
                else:
                    # Handle OpenAI/Anthropic/Kiro streaming responses
                    # Some providers return async generators, others return sync iterables
                    accumulated_response_text = ""  # Track full response for token counting

                    # Check if response is an async generator
                    import inspect
                    if inspect.iscoroutinefunction(response) or hasattr(response, '__aiter__'):
                        # Handle async generator (like Kiro)
                        logger.info(f"Detected async generator response, using async for loop")
                        chunk_count = 0
                        try:
                            async for chunk in response:
                                chunk_count += 1
                                try:
                                    logger.debug(f"Async chunk type: {type(chunk)}")
                                    logger.debug(f"Async chunk: {chunk}")

                                    # For Kiro, chunks are already properly formatted SSE bytes
                                    # Just pass them through directly
                                    if isinstance(chunk, bytes):
                                        logger.debug(f"Yielding raw bytes chunk: {len(chunk)} bytes")
                                        yield chunk
                                    else:
                                        # Fallback: treat as dict and serialize
                                        chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
                                        yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
                                except Exception as chunk_error:
                                    error_msg = str(chunk_error)
                                    logger.warning(f"Error processing async chunk: {error_msg}")
                                    logger.warning(f"Chunk type: {type(chunk)}")
                                    logger.warning(f"Chunk content: {chunk}")
                                    continue
                        except Exception as async_error:
                            logger.error(f"Error in async for loop: {async_error}")
                            logger.error(f"Response type: {type(response)}")
                            logger.error(f"Response has __aiter__: {hasattr(response, '__aiter__')}")
                            logger.error(f"Response is coroutine function: {inspect.iscoroutinefunction(response)}")
                            # Re-raise to trigger failure recording
                            raise async_error
                        finally:
                            logger.info(f"Async generator processed {chunk_count} chunks total")
                    else:
                        # Handle sync iterable (like OpenAI SDK)
                        logger.info(f"Detected sync iterable response, using regular for loop")
                        for chunk in response:
                            try:
                                logger.debug(f"Sync chunk type: {type(chunk)}")
                                logger.debug(f"Sync chunk: {chunk}")

                                # For OpenAI-compatible providers, just pass through the raw chunk
                                # Convert chunk to dict and serialize as JSON
                                chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk

                                # Track response content for token calculation
                                if isinstance(chunk_dict, dict):
                                    choices = chunk_dict.get('choices', [])
                                    if choices:
                                        delta = choices[0].get('delta', {})
                                        delta_content = delta.get('content', '')
                                        if delta_content:
                                            accumulated_response_text += delta_content

                                # Add effective_context to the last chunk (when finish_reason is present)
                                if isinstance(chunk_dict, dict):
                                    choices = chunk_dict.get('choices', [])
                                    if choices and choices[0].get('finish_reason') is not None:
                                        # This is the last chunk, add effective_context
                                        if 'usage' not in chunk_dict:
                                            chunk_dict['usage'] = {}
                                        chunk_dict['usage']['effective_context'] = effective_context

                                        # If provider doesn't provide token counts, calculate them
                                        if chunk_dict['usage'].get('total_tokens') is None:
                                            # Calculate completion tokens from accumulated response
                                            if accumulated_response_text:
                                                completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], request_data['model'])
                                            else:
                                                completion_tokens = 0
                                            total_tokens = effective_context + completion_tokens
                                            chunk_dict['usage']['prompt_tokens'] = effective_context
                                            chunk_dict['usage']['completion_tokens'] = completion_tokens
                                            chunk_dict['usage']['total_tokens'] = total_tokens

                                yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
                            except Exception as chunk_error:
                                error_msg = str(chunk_error)
                                logger.warning(f"Error serializing sync chunk: {error_msg}")
                                logger.warning(f"Chunk type: {type(chunk)}")
                                logger.warning(f"Chunk content: {chunk}")
                                continue
                
                handler.record_success()
            except Exception as e:
                handler.record_failure()
                error_dict = {"error": str(e)}
                yield f"data: {json.dumps(error_dict)}\n\n".encode('utf-8')
        
        return StreamingResponse(stream_generator(effective_context), media_type="text/event-stream")

    async def handle_rotation_model_list(self, rotation_id: str) -> List[Dict]:
        rotation_config = self.config.get_rotation(rotation_id)
        if not rotation_config:
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")

        all_models = []
        for provider in rotation_config.providers:
            provider_id = provider['provider_id']
            provider_config = self.config.get_provider(provider_id)
            
            for model in provider['models']:
                model_name = model['name']
                model_dict = {
                    "id": f"{provider_id}/{model_name}",
                    "name": model_name,
                    "provider_id": provider_id,
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                }
                
                # Add context window information
                # Priority: model config in rotation > provider config > first model in provider
                if model.get('context_size'):
                    model_dict['context_window'] = model['context_size']
                elif provider_config:
                    # Try to find in provider config
                    found_in_provider = False
                    for pm in getattr(provider_config, "models", []) or []:
                        if pm.name == model_name and hasattr(pm, 'context_size') and pm.context_size:
                            model_dict['context_window'] = pm.context_size
                            found_in_provider = True
                            break
                    if not found_in_provider:
                        # Auto-derive from first model in provider (which has context_size from dynamic fetch)
                        if getattr(provider_config, "models", []) and len(getattr(provider_config, "models", [])) > 0:
                            first_model = getattr(provider_config, "models", [])[0]
                            if hasattr(first_model, 'context_size') and first_model.context_size:
                                model_dict['context_window'] = first_model.context_size
                            elif hasattr(first_model, 'context_window') and first_model.context_window:
                                model_dict['context_window'] = first_model.context_window
                            elif hasattr(first_model, 'context_length') and first_model.context_length:
                                model_dict['context_window'] = first_model.context_length
                            else:
                                model_dict['context_window'] = self._infer_context_window(model_name, provider_config.type)
                        else:
                            model_dict['context_window'] = self._infer_context_window(model_name, provider_config.type)
                
                # Add capabilities information
                if model.get('capabilities'):
                    model_dict['capabilities'] = model['capabilities']
                elif provider_config:
                    # Try to find in provider config
                    for pm in getattr(provider_config, "models", []) or []:
                        if pm.name == model_name and hasattr(pm, 'capabilities'):
                            model_dict['capabilities'] = pm.capabilities
                            break
                    if 'capabilities' not in model_dict:
                        model_dict['capabilities'] = self._detect_capabilities(model_name, provider_config.type)
                
                all_models.append(model_dict)

        return all_models
    
    def _infer_context_window(self, model_name: str, provider_type: str) -> int:
        """Infer context window size from model name or provider type"""
        model_lower = model_name.lower()
        
        # Known model patterns
        if 'gpt-4' in model_lower:
            if 'turbo' in model_lower or '1106' in model_lower or '0125' in model_lower:
                return 128000
            return 8192
        elif 'gpt-3.5' in model_lower:
            if 'turbo' in model_lower and ('1106' in model_lower or '0125' in model_lower):
                return 16385
            return 4096
        elif 'claude-3' in model_lower:
            return 200000
        elif 'claude-2' in model_lower:
            return 100000
        elif 'gemini' in model_lower:
            if '1.5' in model_lower:
                return 2000000 if 'pro' in model_lower else 1000000
            elif '2.0' in model_lower:
                return 1000000
            return 32000
        elif 'llama' in model_lower:
            if '3' in model_lower:
                return 128000
            return 4096
        elif 'mistral' in model_lower:
            if 'large' in model_lower:
                return 32000
            return 8192
        
        # Default based on provider type
        if provider_type == 'google':
            return 32000
        elif provider_type == 'anthropic':
            return 100000
        elif provider_type == 'openai':
            return 8192
        
        # Generic default
        return 4096
    
    def _detect_capabilities(self, model_name: str, provider_type: str) -> List[str]:
        """Auto-detect model capabilities based on model name and provider type"""
        model_lower = model_name.lower()
        capabilities = []
        
        # Text-to-text is the default capability for all models
        capabilities.append('t2t')
        
        # Image generation models
        if any(keyword in model_lower for keyword in ['dall-e', 'dalle', 'stable-diffusion', 'sd-', 'midjourney', 'imagen']):
            capabilities.append('t2i')
        
        # Vision models (can process images)
        if any(keyword in model_lower for keyword in ['vision', 'gpt-4-turbo', 'gpt-4o', 'claude-3', 'gemini-1.5', 'gemini-2.0']):
            capabilities.append('vision')
        
        # Audio transcription models
        if any(keyword in model_lower for keyword in ['whisper', 'transcribe']):
            capabilities.append('transcription')
        
        # Text-to-speech models
        if any(keyword in model_lower for keyword in ['tts', 'text-to-speech', 'elevenlabs']):
            capabilities.append('tts')
        
        # Video generation models
        if any(keyword in model_lower for keyword in ['sora', 'runway', 'pika', 'video']):
            capabilities.append('i2v')
        
        # Embedding models
        if any(keyword in model_lower for keyword in ['embedding', 'embed', 'ada-002']):
            capabilities.append('embeddings')
        
        # Function calling / tool use
        if any(keyword in model_lower for keyword in ['gpt-4', 'gpt-3.5-turbo', 'claude-3', 'gemini']):
            capabilities.append('function_calling')
        
        return capabilities

class AutoselectHandler:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.config = config
        self._skill_file_content = None
        self._internal_model = None
        self._internal_tokenizer = None
        self._internal_model_lock = None
        # Load user-specific configs if user_id is provided
        if user_id:
            self._load_user_configs()
            # Override config to only use user-specific configs with NO global fallback
            self.autoselects = {}
            for autoselect in self.user_autoselects:
                self.autoselects[autoselect['autoselect_id']] = autoselect['config']
        else:
            self.user_providers = {}
            self.user_rotations = {}
            self.user_autoselects = {}
            self.autoselects = self.config.autoselect if hasattr(self.config, 'autoselect') else {}

    def _load_user_configs(self):
        """Load user-specific configurations from database"""
        from .database import DatabaseRegistry
        db = DatabaseRegistry.get_config_database()
        self.user_providers = db.get_user_providers(self.user_id)
        self.user_rotations = db.get_user_rotations(self.user_id)
        self.user_autoselects = db.get_user_autoselects(self.user_id)
        
    def reload_user_configs(self):
        """Reload user-specific configurations from database"""
        if self.user_id:
            self._load_user_configs()
            # Refresh autoselects dict after reload
            self.autoselects = {}
            for autoselect in self.user_autoselects:
                self.autoselects[autoselect['autoselect_id']] = autoselect['config']

    def _get_skill_file_content(self) -> str:
        """Load the autoselect.md skill file content"""
        if self._skill_file_content is None:
            # Check for user-specific prompt first if user_id is present
            if self.user_id is not None:
                from .database import DatabaseRegistry
                db = DatabaseRegistry.get_config_database()
                user_prompt = db.get_user_prompt(self.user_id, 'autoselect')
                if user_prompt is not None:
                    self._skill_file_content = user_prompt
                    return self._skill_file_content

            # Try installed locations first
            installed_dirs = [
                Path('/usr/share/aisbf'),
                Path.home() / '.local' / 'share' / 'aisbf',
            ]
            
            for installed_dir in installed_dirs:
                skill_file = installed_dir / 'autoselect.md'
                if skill_file.exists():
                    with open(skill_file) as f:
                        self._skill_file_content = f.read()
                    return self._skill_file_content
            
            # Fallback to source tree config directory
            source_dir = Path(__file__).parent.parent / 'config'
            skill_file = source_dir / 'autoselect.md'
            if skill_file.exists():
                with open(skill_file) as f:
                    self._skill_file_content = f.read()
                return self._skill_file_content
            
            raise FileNotFoundError("Could not find autoselect.md skill file")
        
        return self._skill_file_content
    
    def _initialize_internal_model(self):
        """Initialize the internal HuggingFace model for selection (lazy loading)"""
        import logging
        import json
        from pathlib import Path
        logger = logging.getLogger(__name__)
        
        if self._internal_model is not None:
            return  # Already initialized
        
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import threading
            
            logger.info("=== INITIALIZING INTERNAL SELECTION MODEL ===")
            
            # Load model name from config
            config_path = Path.home() / '.aisbf' / 'aisbf.json'
            if not config_path.exists():
                # Try installed locations
                installed_dirs = [
                    Path('/usr/share/aisbf'),
                    Path.home() / '.local' / 'share' / 'aisbf',
                ]
                for installed_dir in installed_dirs:
                    test_path = installed_dir / 'aisbf.json'
                    if test_path.exists():
                        config_path = test_path
                        break
                else:
                    # Fallback to source tree
                    config_path = Path(__file__).parent.parent / 'config' / 'aisbf.json'
            
            model_name = "huihui-ai/Qwen2.5-0.5B-Instruct-abliterated-v3"  # Default
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        aisbf_config = json.load(f)
                        model_name = aisbf_config.get('internal_model', {}).get('autoselect_model_id', model_name)
                except Exception as e:
                    logger.warning(f"Error loading autoselect model config: {e}, using default")
            
            logger.info(f"Model: {model_name}")
            
            # Check for GPU availability
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Device: {device}")
            
            # Load tokenizer
            logger.info("Loading tokenizer...")
            self._internal_tokenizer = AutoTokenizer.from_pretrained(model_name)
            logger.info("Tokenizer loaded")
            
            # Load model
            logger.info("Loading model...")
            self._internal_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map="auto" if device == "cuda" else None
            )
            
            if device == "cpu":
                self._internal_model = self._internal_model.to(device)
            
            logger.info("Model loaded successfully")
            
            # Initialize thread lock for model access
            self._internal_model_lock = threading.Lock()
            
            logger.info("=== INTERNAL SELECTION MODEL READY ===")
        except ImportError as e:
            logger.error(f"Failed to import required libraries for internal model: {e}")
            logger.error("Please install: pip install torch transformers")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize internal model: {e}", exc_info=True)
            raise
    
    async def _run_internal_model_selection(self, prompt: str) -> str:
        """Run the internal model for selection in a separate thread"""
        import logging
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        logger = logging.getLogger(__name__)
        
        # Initialize model if needed
        if self._internal_model is None:
            self._initialize_internal_model()
        
        def run_inference():
            """Run inference in a separate thread"""
            with self._internal_model_lock:
                try:
                    import torch
                    
                    # Tokenize input
                    inputs = self._internal_tokenizer(prompt, return_tensors="pt")
                    
                    # Move to same device as model
                    device = next(self._internal_model.parameters()).device
                    inputs = {k: v.to(device) for k, v in inputs.items()}
                    
                    # Generate response
                    with torch.no_grad():
                        outputs = self._internal_model.generate(
                            **inputs,
                            max_new_tokens=100,
                            temperature=0.1,
                            do_sample=True,
                            pad_token_id=self._internal_tokenizer.eos_token_id
                        )
                    
                    # Decode response
                    response = self._internal_tokenizer.decode(outputs[0], skip_special_tokens=True)
                    
                    # Extract only the generated part (remove the prompt)
                    if response.startswith(prompt):
                        response = response[len(prompt):].strip()
                    
                    return response
                except Exception as e:
                    logger.error(f"Error during internal model inference: {e}", exc_info=True)
                    return None
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, run_inference)
        
        return result

    def _build_autoselect_messages(self, user_prompt: str, autoselect_config) -> List[Dict]:
        """Build the messages for model selection (system + user)"""
        skill_content = self._get_skill_file_content()
        
        # Build the available models list
        models_list = ""
        for model_info in autoselect_config.available_models:
            models_list += f"<model><model_id>{model_info.model_id}</model_id><model_description>{model_info.description}</model_description></model>\n"
        
        # System message with the skill content
        system_message = skill_content
        
        # User message with the prompt and model list
        user_message = f"""<aisbf_user_prompt>{user_prompt}</aisbf_user_prompt>
<aisbf_autoselect_list>
{models_list}
</aisbf_autoselect_list>
<aisbf_autoselect_fallback>{autoselect_config.fallback}</aisbf_autoselect_fallback>"""
        
        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]

    def _extract_model_selection(self, response: str) -> Optional[str]:
        """Extract the model_id from the autoselection response"""
        match = re.search(r'<aisbf_model_autoselection>(.*?)</aisbf_model_autoselection>', response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    async def _get_model_selection(self, user_prompt: str, autoselect_config) -> str:
        """Send the autoselect prompt to a model and get the selection"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT MODEL SELECTION START ===")

        # Check if semantic classification is enabled
        if autoselect_config.classify_semantic:
            logger.info("=== SEMANTIC CLASSIFICATION ENABLED ===")
            logger.info(f"Using semantic classification for model selection")

            try:
                # Initialize semantic classifier
                semantic_classifier = SemanticClassifier()
                semantic_classifier.initialize()

                # Build model library for semantic search (model_id -> description)
                model_library = {}
                for model_info in autoselect_config.available_models:
                    model_library[model_info.model_id] = model_info.description

                # Extract recent chat history (last 3 messages)
                # Split user_prompt into messages (it's formatted as "role: content\nrole: content\n...")
                chat_history = []
                if user_prompt:
                    lines = user_prompt.strip().split('\n')
                    for line in lines[-3:]:  # Last 3 messages
                        if ': ' in line:
                            role, content = line.split(': ', 1)
                            chat_history.append(content)

                # Perform hybrid BM25 + semantic re-ranking
                results = semantic_classifier.hybrid_model_search(user_prompt, chat_history, model_library, top_k=1)

                if results:
                    selected_model_id, score = results[0]
                    logger.info(f"=== SEMANTIC CLASSIFICATION SUCCESS ===")
                    logger.info(f"Selected model ID: {selected_model_id} (score: {score:.4f})")
                    return selected_model_id
                else:
                    logger.warning(f"=== SEMANTIC CLASSIFICATION FAILED ===")
                    logger.warning("No models returned from semantic search, falling back to AI model selection")

            except Exception as e:
                logger.error(f"=== SEMANTIC CLASSIFICATION ERROR ===")
                logger.error(f"Error during semantic classification: {str(e)}")
                logger.warning("Falling back to AI model selection")

        logger.info(f"Using '{autoselect_config.selection_model}' for model selection")

        # Build messages (system + user)
        messages = self._build_autoselect_messages(user_prompt, autoselect_config)
        
        # Create a minimal request for model selection
        selection_request = {
            "messages": messages,
            "temperature": 0,  # Deterministic selection
            "max_tokens": 100,   # We only need a short response
            "stream": False,
            "stop": ["</aisbf_model_autoselection>"]  # Stop at the closing tag
        }
        
        logger.info(f"Selection request parameters:")
        logger.info(f"  Temperature: 0 (deterministic)")
        logger.info(f"  Max tokens: 100 (short response expected)")
        logger.info(f"  Stream: False")
        logger.info(f"  Stop: </aisbf_model_autoselection>")
        
        # Determine if selection_model is a rotation, provider, or special keyword
        selection_model = autoselect_config.selection_model
        
        try:
            # Check if it's the special "internal" keyword
            if selection_model == "internal":
                logger.info(f"Selection model is 'internal' - using local HuggingFace model")
                # For internal model, build the full prompt (system + user combined)
                full_prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]
                response_content = await self._run_internal_model_selection(full_prompt)
                
                if not response_content:
                    logger.error("Internal model returned no response")
                    return None
                
                logger.info(f"Internal model response: {response_content[:200]}..." if len(response_content) > 200 else f"Internal model response: {response_content}")
                
                # Extract model selection from response
                model_id = self._extract_model_selection(response_content)
                
                if model_id:
                    logger.info(f"=== AUTOSELECT MODEL SELECTION SUCCESS ===")
                    logger.info(f"Selected model ID: {model_id}")
                else:
                    logger.warning(f"=== AUTOSELECT MODEL SELECTION FAILED ===")
                    logger.warning(f"Could not extract model ID from internal model response")
                
                return model_id
            # Check if it's a rotation
            elif (self.user_id and selection_model in self.rotations) or selection_model in self.config.rotations:
                logger.info(f"Selection model '{selection_model}' is a rotation")
                rotation_handler = RotationHandler(user_id=self.user_id)
                response = await rotation_handler.handle_rotation_request(selection_model, selection_request)
            # Check if it's a provider/model format (e.g., "gemini/gemini-pro")
            elif '/' in selection_model:
                provider_id, model_name = selection_model.split('/', 1)
                logger.info(f"Selection model '{selection_model}' is a direct provider model")
                logger.info(f"  Provider: {provider_id}, Model: {model_name}")
                
                if provider_id not in self.config.providers:
                    logger.error(f"Provider '{provider_id}' not found in configuration")
                    return None
                
                # Use the direct provider handler
                request_handler = RequestHandler()
                selection_request['model'] = model_name
                response = await request_handler.handle_chat_completion(
                    request=None,  # No HTTP request object needed
                    provider_id=provider_id,
                    request_data=selection_request
                )
            # Check if it's just a provider ID (use any model from that provider)
            elif selection_model in self.config.providers:
                logger.info(f"Selection model '{selection_model}' is a provider (will use first available model)")
                provider_config = self.config.get_provider(selection_model)
                
                # Get first available model from provider
                if getattr(provider_config, "models", []) and len(getattr(provider_config, "models", [])) > 0:
                    model_name = getattr(provider_config, "models", [])[0].name
                    logger.info(f"  Using model: {model_name}")
                    
                    request_handler = RequestHandler()
                    selection_request['model'] = model_name
                    response = await request_handler.handle_chat_completion(
                        request=None,
                        provider_id=selection_model,
                        request_data=selection_request
                    )
                else:
                    logger.error(f"Provider '{selection_model}' has no models configured")
                    return None
            else:
                logger.error(f"Selection model '{selection_model}' not found in rotations or providers")
                return None
            
            logger.info(f"Selection response received")
            
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            logger.info(f"Raw response content: {content[:200]}..." if len(content) > 200 else f"Raw response content: {content}")
            
            model_id = self._extract_model_selection(content)
            
            if model_id:
                logger.info(f"=== AUTOSELECT MODEL SELECTION SUCCESS ===")
                logger.info(f"Selected model ID: {model_id}")
            else:
                logger.warning(f"=== AUTOSELECT MODEL SELECTION FAILED ===")
                logger.warning(f"Could not extract model ID from response")
                logger.warning(f"Response content: {content}")
            
            return model_id
        except Exception as e:
            logger.error(f"=== AUTOSELECT MODEL SELECTION ERROR ===")
            logger.error(f"Error during model selection: {str(e)}")
            logger.error(f"Will use fallback model")
            # If selection fails, we'll handle it in the main handler
            return None

    async def handle_autoselect_request(self, autoselect_id: str, request_data: Dict, user_id: Optional[int] = None, token_id: Optional[int] = None) -> Dict:
        """Handle an autoselect request"""
        import logging
        import time
        logger = logging.getLogger(__name__)
        # Track request start time for latency calculation
        request_start_time = time.time()
        logger.info(f"=== AUTOSELECT REQUEST START ===")
        logger.info(f"Autoselect ID: {autoselect_id}")
        logger.info(f"User ID: {self.user_id}")

        # Check response cache for non-streaming requests
        stream = request_data.get('stream', False)
        if not stream:
            try:
                aisbf_config = self.config.get_aisbf_config()
                if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                    response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                    cached_response = response_cache.get(request_data, user_id=self.user_id)
                    if cached_response:
                        logger.info(f"Cache hit for autoselect request {autoselect_id}")
                        return cached_response
                    else:
                        logger.debug(f"Cache miss for autoselect request {autoselect_id}")
            except Exception as cache_error:
                logger.warning(f"Response cache check failed: {cache_error}")

        # Check for user-specific autoselect config first
        if self.user_id:
            # Database user: ONLY use user-specific configs - NO global fallback
            autoselect_config = next((aut['config'] for aut in self.user_autoselects if aut['autoselect_id'] == autoselect_id), None)
            if autoselect_config:
                logger.info(f"Using user-specific autoselect config for {autoselect_id}")
            else:
                logger.error(f"User autoselect {autoselect_id} not found - NO global fallback")
                raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found for this user")
        else:
            # Admin user: use global config
            autoselect_config = self.config.get_autoselect(autoselect_id)
            logger.info(f"Using global autoselect config for {autoselect_id}")

        if not autoselect_config:
            logger.error(f"Autoselect {autoselect_id} not found")
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        logger.info(f"Autoselect config loaded")
        logger.info(f"Available models for selection: {len(autoselect_config.available_models)}")
        for model_info in autoselect_config.available_models:
            logger.info(f"  - {model_info.model_id}: {model_info.description}")
        logger.info(f"Selection model: {autoselect_config.selection_model}")
        logger.info(f"Fallback model: {autoselect_config.fallback}")

        # Extract the user prompt from the request
        user_messages = request_data.get('messages', [])
        if not user_messages:
            logger.error("No messages provided")
            raise HTTPException(status_code=400, detail="No messages provided")
        
        logger.info(f"User messages count: {len(user_messages)}")
        
        # Build a string representation of the user prompt
        # Limit to last 10 messages or 8000 tokens, whichever comes first
        MAX_SELECTION_MESSAGES = 10
        MAX_SELECTION_TOKENS = 8000
        
        # Take the last N messages
        limited_messages = user_messages[-MAX_SELECTION_MESSAGES:] if len(user_messages) > MAX_SELECTION_MESSAGES else user_messages
        logger.info(f"Limited to last {len(limited_messages)} messages for selection")
        
        # Build prompt and check token count
        user_prompt = ""
        final_messages = []
        for msg in limited_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                # Handle complex content (e.g., with images)
                content = str(content)
            
            # Check if adding this message would exceed token limit
            test_prompt = user_prompt + f"{role}: {content}\n"
            # Use a simple token estimation (rough approximation: 1 token ≈ 4 chars)
            estimated_tokens = len(test_prompt) // 4
            
            if estimated_tokens > MAX_SELECTION_TOKENS:
                logger.info(f"Reached token limit ({estimated_tokens} > {MAX_SELECTION_TOKENS}), stopping at {len(final_messages)} messages")
                break
            
            user_prompt = test_prompt
            final_messages.append(msg)
        
        logger.info(f"Final message count for selection: {len(final_messages)}")
        logger.info(f"User prompt length: {len(user_prompt)} characters (est. {len(user_prompt) // 4} tokens)")
        logger.info(f"User prompt preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"User prompt: {user_prompt}")

        # Get the model selection
        logger.info(f"Requesting model selection from AI...")
        selected_model_id = await self._get_model_selection(user_prompt, autoselect_config)

        # Validate the selected model
        logger.info(f"=== MODEL VALIDATION ===")
        if not selected_model_id:
            # Fallback to the configured fallback model
            logger.warning(f"No model ID returned from selection")
            logger.warning(f"Using fallback model: {autoselect_config.fallback}")
            selected_model_id = autoselect_config.fallback
        else:
            # Check if the selected model is in the available models list
            available_ids = [m.model_id for m in autoselect_config.available_models]
            if selected_model_id not in available_ids:
                logger.warning(f"Selected model '{selected_model_id}' not in available models list")
                logger.warning(f"Available models: {available_ids}")
                logger.warning(f"Using fallback model: {autoselect_config.fallback}")
                selected_model_id = autoselect_config.fallback
            else:
                logger.info(f"Selected model '{selected_model_id}' is valid and available")

        logger.info(f"=== FINAL MODEL CHOICE ===")
        logger.info(f"Selected model ID: {selected_model_id}")
        logger.info(f"Selection method: {'AI-selected' if selected_model_id != autoselect_config.fallback else 'Fallback'}")

        # Now proxy the actual request to the selected rotation
        logger.info(f"Proxying request to rotation: {selected_model_id}")
        rotation_handler = RotationHandler()
        
        try:
            response = await rotation_handler.handle_rotation_request(selected_model_id, request_data, user_id, token_id)
        except Exception as e:
            # Record analytics for failed autoselect request
            logger.error(f"Autoselect request failed: {str(e)}")
            try:
                analytics = get_analytics()
                # Calculate latency
                latency_ms = (time.time() - request_start_time) * 1000
                logger.info(f"Failed Autoselect Analytics: latency_ms={latency_ms:.2f}")
                
                # Estimate tokens for failed request
                try:
                    messages = request_data.get('messages', [])
                    estimated_tokens = count_messages_tokens(messages, autoselect_id)
                    total_tokens = estimated_tokens
                    prompt_tokens = estimated_tokens
                    completion_tokens = 0
                except Exception:
                    total_tokens = 50  # Minimal estimate for failed requests
                    prompt_tokens = 50
                    completion_tokens = 0
                
                analytics.record_request(
                    provider_id='autoselect',
                    model_name=autoselect_id,
                    tokens_used=total_tokens,
                    latency_ms=latency_ms,
                    success=False,
                    error_type=type(e).__name__,
                    autoselect_id=autoselect_id,
                    user_id=user_id,
                    token_id=token_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    actual_cost=None
                )
            except Exception as analytics_error:
                logger.warning(f"Analytics recording for failed autoselect failed: {analytics_error}")
            
            # Re-raise the exception
            raise
        
        # Cache the response for non-streaming requests
        if not stream:
            try:
                aisbf_config = self.config.get_aisbf_config()
                if aisbf_config and aisbf_config.response_cache and aisbf_config.response_cache.enabled:
                    response_cache = get_response_cache(aisbf_config.response_cache.model_dump())
                    response_cache.set(request_data, response, user_id=self.user_id)
                    logger.debug(f"Cached response for autoselect request {autoselect_id}")
            except Exception as cache_error:
                logger.warning(f"Response cache set failed: {cache_error}")
        
        logger.info(f"=== AUTOSELECT REQUEST END ===")
        
        # Record analytics for token usage
        try:
            analytics = get_analytics()
            if response and isinstance(response, dict):
                usage = response.get('usage', {})
                total_tokens = usage.get('total_tokens', 0)
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
                
                # If no token usage provided, estimate it
                if total_tokens == 0:
                    try:
                        messages = request_data.get('messages', [])
                        model_name = response.get('model', 'unknown')
                        estimated_prompt_tokens = count_messages_tokens(messages, model_name)
                        
                        # More realistic completion estimate
                        max_tokens = request_data.get('max_tokens', 0)
                        if max_tokens > 0:
                            estimated_completion = min(max_tokens, estimated_prompt_tokens * 2)
                        else:
                            estimated_completion = max(estimated_prompt_tokens, 50)
                        
                        total_tokens = estimated_prompt_tokens + estimated_completion
                        prompt_tokens = estimated_prompt_tokens
                        completion_tokens = estimated_completion
                        logger.debug(f"Estimated token usage for autoselect: {total_tokens}")
                    except Exception as est_error:
                        logger.debug(f"Token estimation failed: {est_error}")
                        total_tokens = 150
                        prompt_tokens = 0
                        completion_tokens = 0
                
                # Try to extract actual cost from provider response
                from ..cost_extractor import extract_cost_from_response
                actual_cost = extract_cost_from_response(response, 'autoselect')
                
                # Always record analytics
                # The actual provider/model info is in the response model field
                model_name = response.get('model', 'unknown')
                # Calculate latency
                latency_ms = (time.time() - request_start_time) * 1000
                logger.info(f"Autoselect Analytics: latency_ms={latency_ms:.2f}")
                
                analytics.record_request(
                    provider_id='autoselect',
                    model_name=model_name,
                    tokens_used=total_tokens,
                    latency_ms=latency_ms,
                    success=True,
                    autoselect_id=autoselect_id,
                    user_id=user_id,
                    token_id=token_id,
                    prompt_tokens=prompt_tokens if prompt_tokens > 0 else None,
                    completion_tokens=completion_tokens if completion_tokens > 0 else None,
                    actual_cost=actual_cost
                )
        except Exception as analytics_error:
            logger.warning(f"Analytics recording failed: {analytics_error}")
        
        return response

    async def handle_autoselect_streaming_request(self, autoselect_id: str, request_data: Dict):
        """
        Handle an autoselect streaming request.
        
        The rotation handler handles the streaming conversion internally based on
        the selected provider's type, so we just pass through the response.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT STREAMING REQUEST START ===")
        logger.info(f"Autoselect ID: {autoselect_id}")
        
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            logger.error(f"Autoselect {autoselect_id} not found")
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        logger.info(f"Autoselect config loaded")
        logger.info(f"Available models for selection: {len(autoselect_config.available_models)}")
        for model_info in autoselect_config.available_models:
            logger.info(f"  - {model_info.model_id}: {model_info.description}")
        logger.info(f"Fallback model: {autoselect_config.fallback}")

        # Extract the user prompt from the request
        user_messages = request_data.get('messages', [])
        if not user_messages:
            logger.error("No messages provided")
            raise HTTPException(status_code=400, detail="No messages provided")
        
        logger.info(f"User messages count: {len(user_messages)}")
        
        # Build a string representation of the user prompt
        # Limit to last 10 messages or 8000 tokens, whichever comes first
        MAX_SELECTION_MESSAGES = 10
        MAX_SELECTION_TOKENS = 8000
        
        # Take the last N messages
        limited_messages = user_messages[-MAX_SELECTION_MESSAGES:] if len(user_messages) > MAX_SELECTION_MESSAGES else user_messages
        logger.info(f"Limited to last {len(limited_messages)} messages for selection")
        
        # Build prompt and check token count
        user_prompt = ""
        final_messages = []
        for msg in limited_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = str(content)
            
            # Check if adding this message would exceed token limit
            test_prompt = user_prompt + f"{role}: {content}\n"
            # Use a simple token estimation (rough approximation: 1 token ≈ 4 chars)
            estimated_tokens = len(test_prompt) // 4
            
            if estimated_tokens > MAX_SELECTION_TOKENS:
                logger.info(f"Reached token limit ({estimated_tokens} > {MAX_SELECTION_TOKENS}), stopping at {len(final_messages)} messages")
                break
            
            user_prompt = test_prompt
            final_messages.append(msg)
        
        logger.info(f"Final message count for selection: {len(final_messages)}")
        logger.info(f"User prompt length: {len(user_prompt)} characters (est. {len(user_prompt) // 4} tokens)")
        logger.info(f"User prompt preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"User prompt: {user_prompt}")

        # Get the model selection
        logger.info(f"Requesting model selection from AI...")
        selected_model_id = await self._get_model_selection(user_prompt, autoselect_config)

        # Validate the selected model
        logger.info(f"=== MODEL VALIDATION ===")
        if not selected_model_id:
            logger.warning(f"No model ID returned from selection")
            logger.warning(f"Using fallback model: {autoselect_config.fallback}")
            selected_model_id = autoselect_config.fallback
        else:
            available_ids = [m.model_id for m in autoselect_config.available_models]
            if selected_model_id not in available_ids:
                logger.warning(f"Selected model '{selected_model_id}' not in available models list")
                logger.warning(f"Available models: {available_ids}")
                logger.warning(f"Using fallback model: {autoselect_config.fallback}")
                selected_model_id = autoselect_config.fallback
            else:
                logger.info(f"Selected model '{selected_model_id}' is valid and available")

        logger.info(f"=== FINAL MODEL CHOICE ===")
        logger.info(f"Selected model ID: {selected_model_id}")
        logger.info(f"Selection method: {'AI-selected' if selected_model_id != autoselect_config.fallback else 'Fallback'}")
        logger.info(f"Request mode: Streaming")

        # Proxy the streaming request to the selected model (rotation or direct provider)
        try:
            # Ensure stream is set to True
            request_data['stream'] = True
            
            # Check if it's a rotation first
            if (self.user_id and selected_model_id in self.rotations) or selected_model_id in self.config.rotations:
                logger.info(f"Proxying streaming request to rotation: {selected_model_id}")
                rotation_handler = RotationHandler(user_id=self.user_id)
                response = await rotation_handler.handle_rotation_request(selected_model_id, request_data)
            # Check if it's a provider/model format (e.g., "gemini/gemini-pro")
            elif '/' in selected_model_id:
                provider_id, model_name = selected_model_id.split('/', 1)
                logger.info(f"Proxying streaming request to direct provider model: {selected_model_id}")
                logger.info(f"  Provider: {provider_id}, Model: {model_name}")
                
                if provider_id not in self.config.providers:
                    logger.error(f"Provider '{provider_id}' not found in configuration")
                    raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")
                
                # Use the direct provider handler
                request_handler = RequestHandler()
                request_data['model'] = model_name
                response = await request_handler.handle_streaming_chat_completion(
                    request=None,
                    provider_id=provider_id,
                    request_data=request_data
                )
            # Check if it's just a provider ID (use first available model)
            elif selected_model_id in self.config.providers:
                logger.info(f"Proxying streaming request to provider: {selected_model_id} (will use first available model)")
                provider_config = self.config.get_provider(selected_model_id)
                
                # Get first available model from provider
                if getattr(provider_config, "models", []) and len(getattr(provider_config, "models", [])) > 0:
                    model_name = getattr(provider_config, "models", [])[0].name
                    logger.info(f"  Using model: {model_name}")
                    
                    request_handler = RequestHandler()
                    request_data['model'] = model_name
                    response = await request_handler.handle_streaming_chat_completion(
                        request=None,
                        provider_id=selected_model_id,
                        request_data=request_data
                    )
                else:
                    logger.error(f"Provider '{selected_model_id}' has no models configured")
                    raise HTTPException(status_code=400, detail=f"Provider {selected_model_id} has no models configured")
            else:
                logger.error(f"Selected model '{selected_model_id}' not found in rotations or providers")
                raise HTTPException(status_code=400, detail=f"Model {selected_model_id} not found")
            
            logger.info(f"=== AUTOSELECT STREAMING REQUEST END ===")
            return response
        except Exception as e:
            logger.error(f"Error proxying to selected model: {str(e)}", exc_info=True)
            raise

    async def handle_autoselect_model_list(self, autoselect_id: str) -> List[Dict]:
        """List the available models for an autoselect endpoint"""
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        # Return the available models that can be selected
        return [
            {
                "id": model_info.model_id,
                "name": model_info.model_id,
                "description": model_info.description
            }
            for model_info in autoselect_config.available_models
        ]
