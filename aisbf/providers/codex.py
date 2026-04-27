"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Codex provider handler.
Supports both API key mode (OpenAI API) and OAuth2 mode (ChatGPT Responses API).

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
import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Union, AsyncIterator, Tuple

from openai import OpenAI
import httpx

from ..models import Model
from ..config import config
from ..utils import count_messages_tokens
from .base import BaseProviderHandler, AISBF_DEBUG
from ..auth.codex import CodexOAuth2

logger = logging.getLogger(__name__)


class CodexProviderHandler(BaseProviderHandler):
    """
    Codex provider handler with dual-mode support.
    
    **API Key Mode** (api_key provided):
    - Uses standard OpenAI API: https://api.openai.com/v1
    - Uses Chat Completions endpoint: /v1/chat/completions
    - Standard OpenAI protocol with Bearer token
    
    **OAuth2 Mode** (no api_key, OAuth2 credentials):
    - Uses ChatGPT backend API: https://chatgpt.com/backend-api
    - Uses Responses API endpoint: /codex/responses
    - ChatGPT-specific protocol with SSE streaming
    - Includes ChatGPT-Account-ID header
    
    For admin users (user_id=None), credentials are loaded from file.
    For non-admin users, credentials are loaded from the database.
    """
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None):
        super().__init__(provider_id, api_key, user_id=user_id)
        
        # Get provider config
        provider_config = config.providers.get(provider_id)
        
        # Initialize OAuth2 client
        codex_config = getattr(provider_config, 'codex_config', {}) if provider_config else {}
        credentials_file = codex_config.get('credentials_file', '~/.aisbf/codex_credentials.json')
        issuer = codex_config.get('issuer', 'https://auth.openai.com')
        
        # Only the ONE config admin (user_id=None from aisbf.json) uses file-based credentials
        # All other users (including database admins with user_id) use database credentials
        if user_id is not None:
            self.oauth2 = self._load_oauth2_from_db(provider_id, credentials_file, issuer)
        else:
            # Config admin (from aisbf.json): use file-based credentials
            self.oauth2 = CodexOAuth2(
                credentials_file=credentials_file,
                issuer=issuer,
            )
        
        # Determine mode: API key mode or OAuth2 mode
        self._use_api_key_mode = bool(api_key or (provider_config and provider_config.api_key))
        self._account_id = None  # Will be extracted from ID token in OAuth2 mode
        
        # Set base URL from config (default endpoint)
        # This will be overridden for OAuth2 mode when credentials are validated
        self.base_url = provider_config.endpoint if provider_config else "https://api.openai.com/v1"
        
        # API Key Mode: Initialize OpenAI client with configured endpoint
        if self._use_api_key_mode:
            resolved_api_key = api_key or (provider_config.api_key if provider_config else None)
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=resolved_api_key or "dummy",
                default_headers={
                    "User-Agent": "codex-cli/1.0.0",
                }
            )
            logger.info(f"CodexProviderHandler: Initialized in API Key mode with endpoint: {self.base_url}")
        else:
            # OAuth2 Mode: Check if OAuth2 is authenticated
            # If authenticated, use ChatGPT backend; otherwise use configured endpoint
            if self.oauth2.is_authenticated():
                self.base_url = "https://chatgpt.com/backend-api"
                logger.info(f"CodexProviderHandler: Initialized in OAuth2 mode with ChatGPT backend: {self.base_url}")
            else:
                # Not yet authenticated, keep configured endpoint
                logger.info(f"CodexProviderHandler: Initialized in OAuth2 mode (not authenticated yet) with endpoint: {self.base_url}")
            self.client = None  # Not used in OAuth2 mode
    
    def _load_oauth2_from_db(self, provider_id: str, credentials_file: str, issuer: str) -> CodexOAuth2:
        """
        Load OAuth2 credentials:
        - Admin users (user_id=None): ONLY load from file
        - Regular users: ONLY load from database, NO file fallback
        """
        from ..auth.codex import CodexOAuth2
        import logging
        
        if self.user_id is None:
            # Admin user: ONLY use file-based credentials
            logging.getLogger(__name__).info(f"CodexProviderHandler: Admin user, loading credentials from file: {credentials_file}")
            return CodexOAuth2(
                credentials_file=credentials_file,
                issuer=issuer,
            )
        
        # Regular user: ONLY use database credentials, NO file fallback
        try:
            from ..database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            if db:
                db_creds = db.get_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=provider_id,
                    auth_type='codex_oauth2'
                )
                if db_creds and db_creds.get('credentials'):
                    # Create OAuth2 instance with skip_initial_load=True to avoid file read
                    # Pass save callback to save credentials back to database
                    oauth2 = CodexOAuth2(
                        credentials_file=credentials_file,
                        issuer=issuer,
                        skip_initial_load=True,
                        save_callback=lambda creds: self._save_oauth2_to_db(creds)
                    )
                    # Set credentials directly from database
                    oauth2.credentials = db_creds['credentials']
                    logging.getLogger(__name__).info(f"CodexProviderHandler: Loaded credentials from database for user {self.user_id}")
                    return oauth2
        except Exception as e:
            logging.getLogger(__name__).warning(f"CodexProviderHandler: Failed to load credentials from database: {e}")
        
        # For regular users, NO file fallback - return empty auth instance
        logging.getLogger(__name__).info(f"CodexProviderHandler: No database credentials found for user {self.user_id}, returning unauthenticated instance")
        return CodexOAuth2(
            credentials_file=credentials_file,
            issuer=issuer,
            skip_initial_load=True,
            save_callback=lambda creds: self._save_oauth2_to_db(creds)
        )
    
    async def _get_valid_api_key(self) -> str:
        """Get a valid API key, refreshing OAuth2 if needed."""
        # If we have an API key from config, use it
        provider_config = config.providers.get(self.provider_id)
        if provider_config and provider_config.api_key:
            return provider_config.api_key
        
        # Try OAuth2 token
        token = await self.oauth2.get_valid_token_with_refresh()
        if token:
            # Extract account ID from credentials if available
            if self.oauth2.credentials and self.oauth2.credentials.get('tokens'):
                self._account_id = self.oauth2.credentials['tokens'].get('account_id')
            
            # Switch to ChatGPT backend if OAuth2 is now authenticated
            if not self._use_api_key_mode and self.base_url != "https://chatgpt.com/backend-api":
                self.base_url = "https://chatgpt.com/backend-api"
                logger.info(f"CodexProviderHandler: Switched to ChatGPT backend after OAuth2 authentication: {self.base_url}")
                
                # Update the configuration with the new endpoint
                await self._update_provider_endpoint(self.base_url)
            
            return token
        
        raise Exception("Codex authentication required. Please authenticate via dashboard or provide API key.")
    
    async def _update_provider_endpoint(self, new_endpoint: str) -> None:
        """Update the provider endpoint in configuration."""
        try:
            provider_config = config.providers.get(self.provider_id)
            if provider_config:
                # Update the endpoint in the config object
                provider_config.endpoint = new_endpoint
                
                # Save to configuration file or database
                if self.user_id is not None:
                    # User-specific provider: update in database
                    from ..database import DatabaseRegistry
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        # Update user provider endpoint in database
                        db.update_user_provider_endpoint(
                            user_id=self.user_id,
                            provider_id=self.provider_id,
                            endpoint=new_endpoint
                        )
                        logger.info(f"CodexProviderHandler: Updated endpoint in database for user {self.user_id}: {new_endpoint}")
                else:
                    # Global provider: update in config file
                    config.save_providers()
                    logger.info(f"CodexProviderHandler: Updated endpoint in config file: {new_endpoint}")
        except Exception as e:
            logger.warning(f"CodexProviderHandler: Failed to update endpoint in configuration: {e}")
    
    # =========================================================================
    # API Key Mode Methods (Standard OpenAI API)
    # =========================================================================
    
    async def _handle_request_api_key_mode(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 1.0,
        stream: Optional[bool] = False,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[Union[str, Dict]] = None,
    ) -> Union[Dict, object]:
        """Handle request using standard OpenAI Chat Completions API."""
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
        
        # Build messages with all fields
        for msg in messages:
            message = {"role": msg["role"]}
            
            if msg["role"] == "tool":
                if "tool_call_id" in msg and msg["tool_call_id"] is not None:
                    message["tool_call_id"] = msg["tool_call_id"]
                else:
                    logger.warning(f"Skipping tool message without tool_call_id: {msg}")
                    continue
            
            if "content" in msg and msg["content"] is not None:
                message["content"] = msg["content"]
            if "tool_calls" in msg and msg["tool_calls"] is not None:
                message["tool_calls"] = msg["tool_calls"]
            if "name" in msg and msg["name"] is not None:
                message["name"] = msg["name"]
            request_params["messages"].append(message)
        
        if tools is not None:
            request_params["tools"] = tools
        if tool_choice is not None:
            request_params["tool_choice"] = tool_choice

        response = self.client.chat.completions.create(**request_params)
        return response
    
    # =========================================================================
    # OAuth2 Mode Methods (ChatGPT Responses API)
    # =========================================================================
    
    def _convert_messages_to_responses_format(self, messages: List[Dict]) -> Tuple[List[Dict], Optional[str]]:
        """
        Convert OpenAI Chat Completions messages to Responses API format.
        
        OpenAI format: {"role": "user", "content": "text"}
        Responses format: {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "text"}]}
        
        Returns:
            tuple: (converted_messages, system_instruction)
                - converted_messages: List of messages in Responses API format
                - system_instruction: Combined system message content (if any)
        """
        result = []
        system_instructions = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Handle system messages - extract for instructions field
            if role == "system":
                if isinstance(content, str):
                    system_instructions.append(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            system_instructions.append(item.get("text", ""))
                continue
            
            # Handle tool messages
            if role == "tool":
                result.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": content
                })
                continue
            
            # Handle assistant messages with tool calls
            if role == "assistant" and "tool_calls" in msg:
                # Add the assistant message first
                if content:
                    result.append({
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}]
                    })
                
                # Add function calls
                for tool_call in msg.get("tool_calls") or []:
                    result.append({
                        "type": "function_call",
                        "call_id": tool_call.get("id", ""),
                        "name": tool_call.get("function", {}).get("name", ""),
                        "arguments": tool_call.get("function", {}).get("arguments", "{}")
                    })
                continue
            
            # Handle regular messages (user, developer, assistant)
            content_items = []
            if isinstance(content, str):
                content_type = "input_text" if role in ["user", "developer"] else "output_text"
                content_items.append({"type": content_type, "text": content})
            elif isinstance(content, list):
                # Handle multimodal content
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            content_type = "input_text" if role in ["user", "developer"] else "output_text"
                            content_items.append({"type": content_type, "text": item.get("text", "")})
                        elif item.get("type") == "image_url":
                            content_items.append({
                                "type": "input_image",
                                "image_url": item.get("image_url", {}).get("url", "")
                            })
            
            if content_items:
                result.append({
                    "type": "message",
                    "role": role,
                    "content": content_items
                })
        
        # Combine system instructions
        combined_system = " ".join(system_instructions) if system_instructions else None
        
        return result, combined_system
    
    def _convert_tools_to_codex_format(self, tools: Optional[List[Dict]]) -> List[Dict]:
        """
        Convert OpenAI tool format to Codex/ChatGPT format.
        
        OpenAI format: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        Codex format: {"type": "function", "name": "...", "description": "...", "parameters": {...}}
        
        Key difference: No nested "function" object in Codex format.
        """
        if not tools:
            return []
        
        converted_tools = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                # OpenAI format - flatten it
                func = tool["function"]
                converted_tool = {
                    "type": "function",
                    "name": func.get("name"),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                }
                converted_tools.append(converted_tool)
            else:
                # Already in Codex format or other type
                converted_tools.append(tool)
        
        return converted_tools
    
    def _build_responses_request(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 1.0,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[Union[str, Dict]] = None,
    ) -> Dict:
        """Build a Responses API request payload."""
        # Convert messages to Responses format and extract system instructions
        input_items, system_instruction = self._convert_messages_to_responses_format(messages)
        
        # Use system instruction from messages if available, otherwise use default
        instructions = system_instruction if system_instruction else "You are Codex, a helpful AI assistant for coding tasks."
        
        # Convert tools to Codex format (flatten the structure)
        codex_tools = self._convert_tools_to_codex_format(tools)
        
        # Build base request
        request = {
            "model": model,
            "instructions": instructions,
            "input": input_items,
            "stream": True,
            "store": False,
            "tools": codex_tools,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        
        # Add optional parameters
        # Note: temperature and max_tokens are not supported by /codex/responses endpoint
        # They are handled internally by the model
        
        # Override tool_choice if explicitly provided
        if tool_choice:
            request["tool_choice"] = tool_choice if isinstance(tool_choice, str) else "auto"
        
        return request
    
    def _build_headers(self, api_key: str, conversation_id: Optional[str] = None) -> Dict[str, str]:
        """Build request headers for Responses API."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "codex-cli/1.0.0",
            "originator": "codex_cli_rs",
        }
        
        # Add ChatGPT-Account-ID if available (OAuth2 mode)
        if self._account_id:
            headers["ChatGPT-Account-ID"] = self._account_id
        
        # Add conversation tracking headers
        if conversation_id:
            headers["x-client-request-id"] = conversation_id
            headers["session_id"] = conversation_id
        
        return headers
    
    async def _parse_sse_stream(self, response: httpx.Response) -> AsyncIterator[Dict]:
        """Parse Server-Sent Events stream from Responses API."""
        buffer = ""
        event_type = None
        
        async for line in response.aiter_lines():
            if not line:
                # Empty line marks end of event
                if buffer and event_type:
                    try:
                        data = json.loads(buffer)
                        yield {"event": event_type, "data": data}
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse SSE data: {e}")
                    buffer = ""
                    event_type = None
                continue
            
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_line = line[5:].strip()
                if buffer:
                    buffer += "\n" + data_line
                else:
                    buffer = data_line
    
    def _convert_sse_to_openai_format(self, events: List[Dict], model: str) -> Dict:
        """Convert Responses API SSE events to OpenAI Chat Completions format."""
        response_id = None
        content = ""
        tool_calls = []
        raw_finish_reason = None
        usage = {}

        for event in events:
            event_type = event.get("event")
            data = event.get("data", {})

            if event_type == "response.created":
                response_id = data.get("response_id")

            elif event_type in ("response.output_text.delta",):
                # Primary text-delta event from the Responses API
                text = data.get("delta", "")
                if text:
                    content += text

            elif event_type == "response.content_part.delta":
                # Alternative text-delta form: delta is a dict with a "text" key
                delta = data.get("delta", {})
                text = delta.get("text", "") if isinstance(delta, dict) else str(delta)
                if text:
                    content += text

            elif event_type == "response.output_item.done":
                item = data.get("item", {})
                if item.get("type") == "function_call":
                    tool_calls.append({
                        "id": item.get("call_id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": item.get("arguments", "{}")
                        }
                    })

            elif event_type == "response.done":
                raw_finish_reason = data.get("status", "stop")
                usage = data.get("usage", {})

        # Map Responses API status → OpenAI finish_reason
        if tool_calls:
            finish_reason = "tool_calls"
        elif raw_finish_reason in (None, "completed"):
            finish_reason = "stop"
        else:
            finish_reason = raw_finish_reason

        message = {
            "role": "assistant",
            "content": content if content else None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        return {
            "id": response_id or f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }

    async def _stream_oauth2_response(
        self,
        url: str,
        headers: Dict[str, str],
        request_payload: Dict,
        model: str,
    ) -> AsyncIterator[Dict]:
        """
        Async generator: converts ChatGPT Responses API SSE events into
        OpenAI-compatible streaming chunks (dicts).  Yields a raw bytes
        ``data: [DONE]\\n\\n`` sentinel at the end so clients know the stream
        is finished.
        """
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created_time = int(time.time())
        tool_call_index = 0

        if AISBF_DEBUG:
            logger.info(f"CodexProviderHandler: Starting OAuth2 SSE stream to {url}")

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=request_payload,
            ) as response:
                if response.status_code >= 400:
                    error_body = await response.aread()
                    logger.error(
                        f"CodexProviderHandler: Streaming error {response.status_code}: "
                        f"{error_body.decode('utf-8')}"
                    )
                    response.raise_for_status()

                async for event in self._parse_sse_stream(response):
                    event_type = event.get("event")
                    data = event.get("data", {})

                    if event_type == "response.created":
                        if data.get("response_id"):
                            response_id = data["response_id"]

                    elif event_type in ("response.output_text.delta",):
                        # Primary text delta
                        text = data.get("delta", "")
                        if text:
                            yield {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                            }

                    elif event_type == "response.content_part.delta":
                        # Alternative text delta: delta is {"text": "..."}
                        delta = data.get("delta", {})
                        text = delta.get("text", "") if isinstance(delta, dict) else str(delta)
                        if text:
                            yield {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                            }

                    elif event_type == "response.output_item.added":
                        # A new output item started (function-call header)
                        item = data.get("item", {})
                        if item.get("type") == "function_call":
                            yield {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": tool_call_index,
                                            "id": item.get("call_id", ""),
                                            "type": "function",
                                            "function": {"name": item.get("name", ""), "arguments": ""},
                                        }]
                                    },
                                    "finish_reason": None,
                                }],
                            }

                    elif event_type == "response.function_call_arguments.delta":
                        # Streaming function-call argument tokens
                        arguments_delta = data.get("delta", "")
                        if arguments_delta:
                            yield {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": tool_call_index,
                                            "function": {"arguments": arguments_delta},
                                        }]
                                    },
                                    "finish_reason": None,
                                }],
                            }

                    elif event_type == "response.output_item.done":
                        item = data.get("item", {})
                        if item.get("type") == "function_call":
                            tool_call_index += 1

                    elif event_type == "response.done":
                        raw_status = data.get("status", "stop")
                        usage = data.get("usage", {})
                        # Map Responses API status → OpenAI finish_reason
                        if tool_call_index > 0:
                            finish_reason = "tool_calls"
                        elif raw_status in (None, "completed"):
                            finish_reason = "stop"
                        else:
                            finish_reason = raw_status

                        yield {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                            "usage": {
                                "prompt_tokens": usage.get("input_tokens", 0),
                                "completion_tokens": usage.get("output_tokens", 0),
                                "total_tokens": usage.get("total_tokens", 0),
                            },
                        }

        # SSE end-of-stream sentinel (passed through as raw bytes by the handler)
        yield b"data: [DONE]\n\n"

    async def _handle_request_oauth2_mode(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 1.0,
        stream: Optional[bool] = False,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[Union[str, Dict]] = None,
    ) -> Union[Dict, object]:
        """Handle request using ChatGPT Responses API."""
        api_key = await self._get_valid_api_key()

        request_payload = self._build_responses_request(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
        )
        conversation_id = str(uuid.uuid4())
        headers = self._build_headers(api_key, conversation_id)
        url = f"{self.base_url}/codex/responses"

        logger.info(f"CodexProviderHandler: Sending {'streaming' if stream else 'non-streaming'} OAuth2 request to {url}")
        if AISBF_DEBUG:
            logger.info(f"CodexProviderHandler: Request payload: {json.dumps(request_payload, indent=2)}")
            logger.info(f"CodexProviderHandler: Request headers: {json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}, indent=2)}")

        if stream:
            # Return an async generator so the streaming handler can iterate it
            # directly and forward chunks to the client as they arrive.
            return self._stream_oauth2_response(url, headers, request_payload, model)

        # Non-streaming: collect all Responses API SSE events then convert.
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=request_payload,
            ) as response:
                if response.status_code >= 400:
                    error_body = await response.aread()
                    logger.error(f"CodexProviderHandler: Error response status: {response.status_code}")
                    logger.error(f"CodexProviderHandler: Error response body: {error_body.decode('utf-8')}")

                response.raise_for_status()

                events = []
                async for event in self._parse_sse_stream(response):
                    events.append(event)

                return self._convert_sse_to_openai_format(events, model)
    
    # =========================================================================
    # Main Request Handler (Routes to appropriate mode)
    # =========================================================================
    
    async def handle_request(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 1.0,
        stream: Optional[bool] = False,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[Union[str, Dict]] = None,
    ) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            logger.info(f"CodexProviderHandler: Handling request for model {model} (mode: {'API Key' if self._use_api_key_mode else 'OAuth2'})")
            if AISBF_DEBUG:
                logger.info(f"CodexProviderHandler: Messages: {messages}")
            else:
                logger.info(f"CodexProviderHandler: Messages count: {len(messages)}")

            # Apply rate limiting
            await self.apply_rate_limit()
            
            # Route to appropriate handler based on mode
            if self._use_api_key_mode:
                response = await self._handle_request_api_key_mode(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    tools=tools,
                    tool_choice=tool_choice
                )
            else:
                response = await self._handle_request_oauth2_mode(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    tools=tools,
                    tool_choice=tool_choice
                )
            
            logger.info(f"CodexProviderHandler: Response received")
            self.record_success()
            
            if AISBF_DEBUG:
                logger.info(f"=== RAW CODEX RESPONSE ===")
                logger.info(f"Raw response: {response}")
                logger.info(f"=== END RAW CODEX RESPONSE ===")
            
            return response
                
        except Exception as e:
            logger.error(f"CodexProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        try:
            logger.info("CodexProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()
            
            # Route to appropriate endpoint based on mode
            if self._use_api_key_mode:
                # API Key Mode: Use standard OpenAI models endpoint
                models_url = f"{self.base_url}/models"
                headers = {
                    "Authorization": f"Bearer {self.client.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "codex-cli/1.0.0",
                }
            else:
                # OAuth2 Mode: Use ChatGPT backend models endpoint
                # https://chatgpt.com/backend-api/codex/models
                api_key = await self._get_valid_api_key()
                models_url = "https://chatgpt.com/backend-api/codex/models"
                headers = self._build_headers(api_key)
                headers["Accept"] = "application/json"  # Not SSE for models
            
            logger.info(f"CodexProviderHandler: Using models endpoint: {models_url}")
            
            async with httpx.AsyncClient() as client:
                params = {"client_version": "1.0.0"} if not self._use_api_key_mode else {}
                response = await client.get(
                    models_url,
                    headers=headers,
                    params=params,
                    timeout=30.0
                )
                
                logger.info(f"CodexProviderHandler: Response status: {response.status_code}")
                
                if response.status_code == 403:
                    logger.error(f"CodexProviderHandler: 403 Unauthorized - Full response: {response.text}")
                
                response.raise_for_status()
                models_data = response.json()
            
            logger.info(f"CodexProviderHandler: Models data received")
            
            # Parse response based on mode
            result = []
            if self._use_api_key_mode:
                # Standard OpenAI format: {"data": [{"id": "...", ...}], "object": "list"}
                if isinstance(models_data, dict) and 'data' in models_data:
                    for model_info in models_data['data']:
                        model_id = model_info.get('id')
                        if model_id:
                            result.append(Model(
                                id=model_id,
                                name=model_info.get('name', model_id),
                                provider_id=self.provider_id,
                                context_size=model_info.get('context_window') or model_info.get('context_length'),
                                context_length=model_info.get('context_length') or model_info.get('context_window'),
                                pricing=model_info.get('pricing')
                            ))
            else:
                # Codex format: {"models": [{"slug": "...", "display_name": "...", ...}]}
                if isinstance(models_data, dict) and 'models' in models_data:
                    for model_info in models_data['models']:
                        model_id = model_info.get('slug') or model_info.get('id')
                        if model_id:
                            result.append(Model(
                                id=model_id,
                                name=model_info.get('display_name', model_id),
                                provider_id=self.provider_id,
                                context_size=model_info.get('context_window'),
                                context_length=model_info.get('context_window'),
                                pricing=None
                            ))
            
            logger.info(f"CodexProviderHandler: Parsed {len(result)} models")
            return result
            
        except Exception as e:
            error_msg = str(e)
            
            logger.error(f"CodexProviderHandler: Full error type: {type(e).__name__}")
            logger.error(f"CodexProviderHandler: Full error message: {error_msg}")
            
            # Return default known Codex models as fallback
            logger.warning(f"CodexProviderHandler: Returning default Codex models")
            
            default_models = [
                Model(id="gpt-4o", name="GPT-4o", provider_id=self.provider_id, context_size=128000, context_length=128000),
                Model(id="gpt-4o-mini", name="GPT-4o Mini", provider_id=self.provider_id, context_size=128000, context_length=128000),
                Model(id="gpt-4-turbo", name="GPT-4 Turbo", provider_id=self.provider_id, context_size=128000, context_length=128000),
                Model(id="gpt-4", name="GPT-4", provider_id=self.provider_id, context_size=8192, context_length=8192),
                Model(id="o1-preview", name="O1 Preview", provider_id=self.provider_id, context_size=128000, context_length=128000),
            ]
            
            logger.info(f"CodexProviderHandler: Returned {len(default_models)} default models as fallback")
            return default_models

    def supports_usage(self) -> bool:
        return not self._use_api_key_mode and self.oauth2.is_authenticated()

    async def get_usage(self) -> Optional[Dict]:
        try:
            # Always use the OAuth2 token — /wham/usage is a ChatGPT backend endpoint
            # that requires an OAuth2 bearer token, not an API key.
            token = await self.oauth2.get_valid_token_with_refresh()
            if not token:
                logger.warning(f"CodexProviderHandler: No OAuth2 token available for usage fetch")
                return None
            logger.debug(f"CodexProviderHandler: Fetching usage with OAuth2 token (len={len(token)})")
            headers = self._build_headers(token)
            headers["Accept"] = "application/json"
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://chatgpt.com/backend-api/wham/usage",
                    headers=headers,
                    timeout=10.0
                )
                logger.debug(f"CodexProviderHandler: Usage response status={response.status_code} headers={dict(response.headers)}")
                response.raise_for_status()
                data = response.json()
                import json as _json
                logger.debug(f"CodexProviderHandler: Usage raw body for {self.provider_id}:\n{_json.dumps(data, indent=2)}")
                return data
        except Exception as e:
            logger.warning(f"CodexProviderHandler: Failed to fetch usage: {e}")
            return None
