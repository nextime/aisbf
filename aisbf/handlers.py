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
                context_manager = ContextManager(context_config, handler, self.config.get_condensation())
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
                    logger.info(f"=== RequestHandler.handle_chat_completion END ===")
                    return response
            
            # Apply rate limiting
            logger.info("Applying rate limiting...")
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

        async def stream_generator(effective_context):
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
                    seen_tool_call_ids = set()  # Track which tool call IDs we've already sent
                    last_chunk_id = None  # Track the last chunk for finish_reason
                    created_time = int(time.time())
                    response_id = f"google-{request_data['model']}-{created_time}"
                    
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
                            
                            # Calculate delta tool calls (only tool calls we haven't seen before)
                            delta_tool_calls = []
                            for tool_call in chunk_tool_calls:
                                if tool_call["id"] not in seen_tool_call_ids:
                                    delta_tool_calls.append(tool_call)
                                    seen_tool_call_ids.add(tool_call["id"])
                            
                            # Check if this is the last chunk
                            is_last_chunk = (chunk_idx == total_chunks - 1)
                            chunk_finish_reason = finish_reason if is_last_chunk else None
                            
                            # Debug logging
                            logger.debug(f"Chunk {chunk_idx}/{total_chunks}: delta_text='{delta_text}', delta_tool_calls={len(delta_tool_calls)}, is_last={is_last_chunk}, condition={bool(delta_text or delta_tool_calls or is_last_chunk)}")
                            
                            # Only send if there's new content, new tool calls, or it's the last chunk with finish_reason
                            if delta_text or delta_tool_calls or is_last_chunk:
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
                                            "tool_calls": delta_tool_calls if delta_tool_calls else None
                                        },
                                        "finish_reason": chunk_finish_reason,
                                        "logprobs": None,
                                        "native_finish_reason": chunk_finish_reason
                                    }]
                                }
                                
                                chunk_id += 1
                                logger.debug(f"OpenAI chunk (delta length: {len(delta_text)}, finish: {chunk_finish_reason})")
                                
                                # Track completion tokens for Google responses
                                if delta_text:
                                    accumulated_response_text += delta_text
                                
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
                    # Handle OpenAI/Anthropic streaming responses
                    # OpenAI SDK returns a sync Stream object, not an async iterator
                    # So we use a regular for loop, not async for
                    accumulated_response_text = ""  # Track full response for token counting
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
            except Exception as e:
                handler.record_failure()
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
            
            # Check if provider exists in configuration
            provider_config = self.config.get_provider(provider_id)
            if not provider_config:
                logger.error(f"  [ERROR] Provider {provider_id} not found in providers configuration")
                logger.error(f"  Available providers: {list(self.config.providers.keys())}")
                logger.error(f"  Skipping this provider")
                skipped_providers.append(provider_id)
                continue
            
            # Get API key: first from provider config, then from rotation config
            api_key = self._get_api_key(provider_id, provider.get('api_key'))
            
            # Check if provider is rate limited/deactivated
            provider_handler = get_provider_handler(provider_id, api_key)
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
            handler = get_provider_handler(provider_id, api_key)
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
                    context_manager = ContextManager(context_config, handler, self.config.get_condensation())
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
                    except:
                        error_details.append(f"**Last error:**")
                        error_details.append(f"{last_error}")
                else:
                    error_details.append(f"**Last error:**")
                    error_details.append(f"{last_error}")
            else:
                error_details.append(f"**Last error:**")
                error_details.append(f"{last_error}")
        except:
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
            
            # Send [DONE] marker
            yield b"data: [DONE]\n\n"
        
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
        
        # Check if this is a Google provider based on configuration
        is_google_provider = provider_type == 'google'
        logger.info(f"Creating streaming response for provider type: {provider_type}, is_google: {is_google_provider}")
        
        # Generate system_fingerprint for this request
        # If seed is present in request, generate unique fingerprint per request
        seed = request_data.get('seed')
        system_fingerprint = generate_system_fingerprint(provider_id, seed)
        
        async def stream_generator(effective_context):
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
                else:
                    # Handle OpenAI/Anthropic streaming responses
                    # OpenAI SDK returns a sync Stream object, not an async iterator
                    # So we use a regular for loop, not async for
                    accumulated_response_text = ""  # Track full response for token counting
                    for chunk in response:
                        try:
                            logger.debug(f"Chunk type: {type(chunk)}")
                            logger.debug(f"Chunk: {chunk}")
                            
                            # For OpenAI-compatible providers, just pass through the raw chunk
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
                                            completion_tokens = count_messages_tokens([{"role": "assistant", "content": accumulated_response_text}], model_name)
                                        else:
                                            completion_tokens = 0
                                        total_tokens = effective_context + completion_tokens
                                        chunk_dict['usage']['prompt_tokens'] = effective_context
                                        chunk_dict['usage']['completion_tokens'] = completion_tokens
                                        chunk_dict['usage']['total_tokens'] = total_tokens
                            
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
        
        return StreamingResponse(stream_generator(effective_context), media_type="text/event-stream")

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
