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
from typing import Dict, List, Optional
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse
from .providers import get_provider_handler
from .config import config


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
    def __init__(self):
        self.config = config

    async def handle_chat_completion(self, request: Request, provider_id: str, request_data: Dict) -> Dict:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== RequestHandler.handle_chat_completion START ===")
        logger.info(f"Provider ID: {provider_id}")
        logger.info(f"Request data: {request_data}")
        
        provider_config = self.config.get_provider(provider_id)
        logger.info(f"Provider config: {provider_config}")
        logger.info(f"Provider type: {provider_config.type}")
        logger.info(f"Provider endpoint: {provider_config.endpoint}")
        logger.info(f"API key required: {provider_config.api_key_required}")

        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            logger.info(f"API key from request: {'***' if api_key else 'None'}")
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
            logger.info("No API key required for this provider")

        logger.info(f"Getting provider handler for {provider_id}")
        handler = get_provider_handler(provider_id, api_key)
        logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")

        try:
            logger.info(f"Model requested: {request_data.get('model')}")
            logger.info(f"Messages count: {len(request_data.get('messages', []))}")
            logger.info(f"Max tokens: {request_data.get('max_tokens')}")
            logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
            logger.info(f"Stream: {request_data.get('stream', False)}")
            
            # Apply rate limiting
            logger.info("Applying rate limiting...")
            await handler.apply_rate_limit()
            logger.info("Rate limiting applied")

            logger.info(f"Sending request to provider handler...")
            response = await handler.handle_request(
                model=request_data['model'],
                messages=request_data['messages'],
                max_tokens=request_data.get('max_tokens'),
                temperature=request_data.get('temperature', 1.0),
                stream=request_data.get('stream', False),
                tools=request_data.get('tools'),
                tool_choice=request_data.get('tool_choice')
            )
            logger.info(f"Response received from provider")
            logger.info(f"Response type: {type(response)}")
            logger.info(f"Response: {response}")
            
            # For OpenAI-compatible providers, the response is already a response object
            # Just return it as-is without any parsing or modification
            handler.record_success()
            logger.info(f"=== RequestHandler.handle_chat_completion END ===")
            return response
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_streaming_chat_completion(self, request: Request, provider_id: str, request_data: Dict):
        provider_config = self.config.get_provider(provider_id)

        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None

        handler = get_provider_handler(provider_id, api_key)

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")

        # Generate system_fingerprint for this request
        # If seed is present in request, generate unique fingerprint per request
        seed = request_data.get('seed')
        system_fingerprint = generate_system_fingerprint(provider_id, seed)

        async def stream_generator():
            import logging
            import time
            import json
            logger = logging.getLogger(__name__)
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
                logger.info(f"Is Google streaming response: {is_google_stream} (provider type: {provider_config.type})")
                
                if is_google_stream:
                    # Handle Google's streaming response
                    # Google provider returns an async generator
                    # Note: Google returns accumulated text, so we need to track and send only deltas
                    chunk_id = 0
                    accumulated_text = ""  # Track text we've already sent
                    last_chunk_id = None  # Track the last chunk for finish_reason
                    created_time = int(time.time())
                    response_id = f"google-{request_data['model']}-{created_time}"
                    
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
                            
                            # Extract text from Google chunk (this is accumulated text)
                            chunk_text = ""
                            finish_reason = None
                            try:
                                if hasattr(chunk, 'candidates') and chunk.candidates:
                                    candidate = chunk.candidates[0] if chunk.candidates else None
                                    if candidate and hasattr(candidate, 'content') and candidate.content:
                                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                            for part in candidate.content.parts:
                                                if hasattr(part, 'text') and part.text:
                                                    chunk_text += part.text
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
                            
                            # Check if this is the last chunk
                            is_last_chunk = (chunk_idx == total_chunks - 1)
                            chunk_finish_reason = finish_reason if is_last_chunk else None
                            
                            # Only send if there's new content or it's the last chunk with finish_reason
                            if delta_text or is_last_chunk:
                                # Create OpenAI-compatible chunk with additional fields
                                openai_chunk = {
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
                                            "tool_calls": None
                                        },
                                        "finish_reason": chunk_finish_reason,
                                        "logprobs": None,
                                        "native_finish_reason": chunk_finish_reason
                                    }]
                                }
                                
                                chunk_id += 1
                                logger.debug(f"OpenAI chunk (delta length: {len(delta_text)}, finish: {chunk_finish_reason})")
                                
                                # Serialize as JSON
                                yield f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
                            
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
                    final_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": request_data['model'],
                        "service_tier": None,
                        "system_fingerprint": system_fingerprint,
                        "usage": {
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None
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
                    # Handle OpenAI/Anthropic streaming responses
                    # OpenAI SDK returns a sync Stream object, not an async iterator
                    # So we use a regular for loop, not async for
                    for chunk in response:
                        try:
                            # Debug: Log chunk type and content before serialization
                            logger.debug(f"Chunk type: {type(chunk)}")
                            logger.debug(f"Chunk: {chunk}")
                            
                            # For OpenAI-compatible providers, just pass through the raw chunk
                            # Convert chunk to dict and serialize as JSON
                            chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
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
            except Exception as e:
                handler.record_failure()
                error_dict = {"error": str(e)}
                yield f"data: {json.dumps(error_dict)}\n\n".encode('utf-8')

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    async def handle_model_list(self, request: Request, provider_id: str) -> List[Dict]:
        provider_config = self.config.get_provider(provider_id)

        if provider_config.api_key_required:
            api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None

        handler = get_provider_handler(provider_id, api_key)
        try:
            # Apply rate limiting
            await handler.apply_rate_limit()

            models = await handler.get_models()
            return [model.dict() for model in models]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

class RotationHandler:
    def __init__(self):
        self.config = config

    def _get_provider_type(self, provider_id: str) -> str:
        """Get the provider type from configuration"""
        provider_config = self.config.get_provider(provider_id)
        if provider_config:
            return provider_config.type
        return None

    async def handle_rotation_request(self, rotation_id: str, request_data: Dict):
        """
        Handle a rotation request.
        
        For streaming requests, returns a StreamingResponse with proper handling
        based on the selected provider's type (google vs others).
        For non-streaming requests, returns the response dict directly.
        """
        import logging
        import time
        logger = logging.getLogger(__name__)
        logger.info(f"=== RotationHandler.handle_rotation_request START ===")
        logger.info(f"Rotation ID: {rotation_id}")
        
        rotation_config = self.config.get_rotation(rotation_id)
        if not rotation_config:
            logger.error(f"Rotation {rotation_id} not found")
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")

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
            
            # Check if provider exists in configuration
            provider_config = self.config.get_provider(provider_id)
            if not provider_config:
                logger.error(f"  [ERROR] Provider {provider_id} not found in providers configuration")
                logger.error(f"  Available providers: {list(self.config.providers.keys())}")
                logger.error(f"  Skipping this provider")
                skipped_providers.append(provider_id)
                continue
            
            # Check if provider is rate limited/deactivated
            provider_handler = get_provider_handler(provider_id, provider.get('api_key'))
            if provider_handler.is_rate_limited():
                logger.warning(f"  [SKIPPED] Provider {provider_id} is rate limited/deactivated")
                logger.warning(f"  Reason: Provider has exceeded failure threshold or is in cooldown period")
                skipped_providers.append(provider_id)
                continue
            
            logger.info(f"  [AVAILABLE] Provider {provider_id} is active and ready")
            
            models_in_provider = len(provider['models'])
            total_models_considered += models_in_provider
            logger.info(f"  Found {models_in_provider} model(s) in this provider")
            
            for model in provider['models']:
                model_name = model['name']
                model_weight = model['weight']
                model_rate_limit = model.get('rate_limit', 'N/A')
                
                logger.info(f"    - Model: {model_name}")
                logger.info(f"      Weight (Priority): {model_weight}")
                logger.info(f"      Rate Limit: {model_rate_limit}")
                
                # Add provider_id and api_key to model for later use
                model_with_provider = model.copy()
                model_with_provider['provider_id'] = provider_id
                model_with_provider['api_key'] = provider.get('api_key')
                available_models.append(model_with_provider)

        logger.info(f"")
        logger.info(f"=== MODEL SELECTION SUMMARY ===")
        logger.info(f"Total providers scanned: {len(providers)}")
        logger.info(f"Providers skipped (rate limited): {len(skipped_providers)}")
        if skipped_providers:
            logger.info(f"Skipped providers: {', '.join(skipped_providers)}")
        logger.info(f"Total models considered: {total_models_considered}")
        logger.info(f"Total models available: {len(available_models)}")
        
        if not available_models:
            logger.error("No models available in rotation (all providers may be rate limited)")
            logger.error("All providers in this rotation are currently deactivated")
            raise HTTPException(status_code=503, detail="No models available in rotation (all providers may be rate limited)")

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
            handler = get_provider_handler(provider_id, api_key)
            logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

            if handler.is_rate_limited():
                logger.warning(f"Provider {provider_id} is rate limited, skipping to next model")
                continue
            
            try:
                logger.info(f"Model requested: {model_name}")
                logger.info(f"Messages count: {len(request_data.get('messages', []))}")
                logger.info(f"Max tokens: {request_data.get('max_tokens')}")
                logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
                logger.info(f"Stream: {request_data.get('stream', False)}")
                
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
                        request_data=request_data
                    )
                else:
                    logger.info("Returning non-streaming response")
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
        raise HTTPException(
            status_code=503,
            detail=f"All providers in rotation failed after {max_retries} attempts. Last error: {last_error}"
        )

    def _create_streaming_response(self, response, provider_type: str, provider_id: str, model_name: str, handler, request_data: Dict):
        """
        Create a StreamingResponse with proper handling based on provider type.
        
        Args:
            response: The streaming response from the provider handler
            provider_type: The type of provider (e.g., 'google', 'openai', 'anthropic')
            provider_id: The provider identifier from configuration
            model_name: The model name being used
            handler: The provider handler (for recording success/failure)
            request_data: The original request data
        
        Returns:
            StreamingResponse with appropriate generator for the provider type
        """
        import logging
        import time
        import json
        logger = logging.getLogger(__name__)
        
        # Check if this is a Google provider based on configuration
        is_google_provider = provider_type == 'google'
        logger.info(f"Creating streaming response for provider type: {provider_type}, is_google: {is_google_provider}")
        
        # Generate system_fingerprint for this request
        # If seed is present in request, generate unique fingerprint per request
        seed = request_data.get('seed')
        system_fingerprint = generate_system_fingerprint(provider_id, seed)
        
        async def stream_generator():
            try:
                if is_google_provider:
                    # Handle Google's streaming response
                    # Google provider returns an async generator
                    # Note: Google returns accumulated text, so we need to track and send only deltas
                    chunk_id = 0
                    accumulated_text = ""  # Track text we've already sent
                    created_time = int(time.time())
                    response_id = f"google-{model_name}-{created_time}"
                    
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
                            
                            # Extract text from Google chunk (this is accumulated text)
                            chunk_text = ""
                            finish_reason = None
                            try:
                                if hasattr(chunk, 'candidates') and chunk.candidates:
                                    candidate = chunk.candidates[0] if chunk.candidates else None
                                    if candidate and hasattr(candidate, 'content') and candidate.content:
                                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                            for part in candidate.content.parts:
                                                if hasattr(part, 'text') and part.text:
                                                    chunk_text += part.text
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
                            
                            # Check if this is the last chunk
                            is_last_chunk = (chunk_idx == total_chunks - 1)
                            chunk_finish_reason = finish_reason if is_last_chunk else None
                            
                            # Only send if there's new content or it's the last chunk with finish_reason
                            if delta_text or is_last_chunk:
                                # Create OpenAI-compatible chunk with additional fields
                                openai_chunk = {
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
                                            "content": delta_text if delta_text else "",
                                            "refusal": None,
                                            "role": "assistant",
                                            "tool_calls": None
                                        },
                                        "finish_reason": chunk_finish_reason,
                                        "logprobs": None,
                                        "native_finish_reason": chunk_finish_reason
                                    }]
                                }
                                
                                chunk_id += 1
                                logger.debug(f"OpenAI chunk (delta length: {len(delta_text)}, finish: {chunk_finish_reason})")
                                
                                yield f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
                            
                            chunk_idx += 1
                        except Exception as chunk_error:
                            error_msg = str(chunk_error)
                            logger.error(f"Error processing Google chunk: {error_msg}")
                            logger.error(f"Chunk type: {type(chunk)}")
                            logger.error(f"Chunk content: {chunk}")
                            chunk_idx += 1
                            continue
                    
                    # Send final chunk with usage statistics (empty content)
                    final_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model_name,
                        "service_tier": None,
                        "system_fingerprint": system_fingerprint,
                        "usage": {
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None
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
                    # Handle OpenAI/Anthropic streaming responses
                    # OpenAI SDK returns a sync Stream object, not an async iterator
                    # So we use a regular for loop, not async for
                    for chunk in response:
                        try:
                            logger.debug(f"Chunk type: {type(chunk)}")
                            logger.debug(f"Chunk: {chunk}")
                            
                            # For OpenAI-compatible providers, just pass through the raw chunk
                            chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
                            yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
                        except Exception as chunk_error:
                            error_msg = str(chunk_error)
                            logger.warning(f"Error serializing chunk: {error_msg}")
                            logger.warning(f"Chunk type: {type(chunk)}")
                            logger.warning(f"Chunk content: {chunk}")
                            continue
                
                handler.record_success()
            except Exception as e:
                handler.record_failure()
                error_dict = {"error": str(e)}
                yield f"data: {json.dumps(error_dict)}\n\n".encode('utf-8')
        
        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    async def handle_rotation_model_list(self, rotation_id: str) -> List[Dict]:
        rotation_config = self.config.get_rotation(rotation_id)
        if not rotation_config:
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")

        all_models = []
        for provider in rotation_config.providers:
            for model in provider['models']:
                all_models.append({
                    "id": f"{provider['provider_id']}/{model['name']}",
                    "name": model['name'],
                    "provider_id": provider['provider_id'],
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                })

        return all_models

class AutoselectHandler:
    def __init__(self):
        self.config = config
        self._skill_file_content = None

    def _get_skill_file_content(self) -> str:
        """Load the autoselect.md skill file content"""
        if self._skill_file_content is None:
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

    def _build_autoselect_prompt(self, user_prompt: str, autoselect_config) -> str:
        """Build the prompt for model selection"""
        skill_content = self._get_skill_file_content()
        
        # Build the available models list
        models_list = ""
        for model_info in autoselect_config.available_models:
            models_list += f"<model><model_id>{model_info.model_id}</model_id><model_description>{model_info.description}</model_description></model>\n"
        
        # Build the complete prompt
        prompt = f"""{skill_content}

<aisbf_user_prompt>{user_prompt}</aisbf_user_prompt>
<aisbf_autoselect_list>
{models_list}
</aisbf_autoselect_list>
<aisbf_autoselect_fallback>{autoselect_config.fallback}</aisbf_autoselect_fallback>
"""
        return prompt

    def _extract_model_selection(self, response: str) -> Optional[str]:
        """Extract the model_id from the autoselection response"""
        match = re.search(r'<aisbf_model_autoselection>(.*?)</aisbf_model_autoselection>', response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    async def _get_model_selection(self, prompt: str, autoselect_config) -> str:
        """Send the autoselect prompt to a model and get the selection"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT MODEL SELECTION START ===")
        logger.info(f"Using '{autoselect_config.selection_model}' rotation for model selection")
        
        # Use the first available provider/model for the selection
        # This is a simple implementation - could be enhanced to use a specific selection model
        rotation_handler = RotationHandler()
        
        # Create a minimal request for model selection
        selection_request = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,  # Low temperature for more deterministic selection
            "max_tokens": 100,   # We only need a short response
            "stream": False
        }
        
        logger.info(f"Selection request parameters:")
        logger.info(f"  Temperature: 0.1 (low for deterministic selection)")
        logger.info(f"  Max tokens: 100 (short response expected)")
        logger.info(f"  Stream: False")
        
        # Use the configured selection rotation for the selection
        try:
            logger.info(f"Sending selection request to rotation handler...")
            response = await rotation_handler.handle_rotation_request(autoselect_config.selection_model, selection_request)
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

    async def handle_autoselect_request(self, autoselect_id: str, request_data: Dict) -> Dict:
        """Handle an autoselect request"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT REQUEST START ===")
        logger.info(f"Autoselect ID: {autoselect_id}")
        
        autoselect_config = self.config.get_autoselect(autoselect_id)
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
        user_prompt = ""
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                # Handle complex content (e.g., with images)
                content = str(content)
            user_prompt += f"{role}: {content}\n"

        logger.info(f"User prompt length: {len(user_prompt)} characters")
        logger.info(f"User prompt preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"User prompt: {user_prompt}")

        # Build the autoselect prompt
        logger.info(f"Building autoselect prompt...")
        autoselect_prompt = self._build_autoselect_prompt(user_prompt, autoselect_config)
        logger.info(f"Autoselect prompt built (length: {len(autoselect_prompt)} characters)")

        # Get the model selection
        logger.info(f"Requesting model selection from AI...")
        selected_model_id = await self._get_model_selection(autoselect_prompt, autoselect_config)

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
        response = await rotation_handler.handle_rotation_request(selected_model_id, request_data)
        logger.info(f"=== AUTOSELECT REQUEST END ===")
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
        user_prompt = ""
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = str(content)
            user_prompt += f"{role}: {content}\n"

        logger.info(f"User prompt length: {len(user_prompt)} characters")
        logger.info(f"User prompt preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"User prompt: {user_prompt}")

        # Build the autoselect prompt
        logger.info(f"Building autoselect prompt...")
        autoselect_prompt = self._build_autoselect_prompt(user_prompt, autoselect_config)
        logger.info(f"Autoselect prompt built (length: {len(autoselect_prompt)} characters)")

        # Get the model selection
        logger.info(f"Requesting model selection from AI...")
        selected_model_id = await self._get_model_selection(autoselect_prompt, autoselect_config)

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

        # Now proxy the actual streaming request to the selected rotation
        # The rotation handler will return a StreamingResponse with proper handling
        # based on the selected provider's type (google vs others)
        logger.info(f"Proxying streaming request to rotation: {selected_model_id}")
        rotation_handler = RotationHandler()
        
        # The rotation handler handles streaming internally and returns a StreamingResponse
        response = await rotation_handler.handle_rotation_request(
            selected_model_id,
            {**request_data, "stream": True}
        )
        
        logger.info(f"=== AUTOSELECT STREAMING REQUEST END ===")
        # Return the StreamingResponse directly - rotation handler already handled the conversion
        return response

    async def handle_autoselect_model_list(self, autoselect_id: str) -> List[Dict]:
        """List available models for an autoselect endpoint"""
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
