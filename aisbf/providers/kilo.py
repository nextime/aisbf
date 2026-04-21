"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Kilo Gateway (OpenAI-compatible with OAuth2) provider handler.

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
import httpx
import time
import os
from typing import Dict, List, Optional, Union, Any
from openai import OpenAI
from ..models import Model
from ..config import config
from ..utils import count_messages_tokens
from .base import BaseProviderHandler, AISBF_DEBUG


class KiloProviderHandler(BaseProviderHandler):
    """
    Handler for Kilo Gateway (OpenAI-compatible with OAuth2 support).
    
    For admin users (user_id=None), credentials are loaded from file.
    For non-admin users, credentials are loaded from the database.
    """
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None, provider_config: Optional[Any] = None):
        super().__init__(provider_id, api_key, user_id=user_id)
        if provider_config is not None:
            # Use provider config passed from factory (user-specific config)
            self.provider_config = provider_config
        else:
            # Fallback to global config
            self.provider_config = config.get_provider(provider_id)
        
        # Unified auth config with backward compatibility
        # Handle both dict (user) and object (global) config formats
        if isinstance(self.provider_config, dict):
            kilo_config = self.provider_config.get('auth_config')
            if not kilo_config:
                kilo_config = self.provider_config.get('kilo_config')
            if not kilo_config:
                kilo_config = self.provider_config.get('kiro_config')
        else:
            kilo_config = getattr(self.provider_config, 'auth_config', None)
            if not kilo_config:
                kilo_config = getattr(self.provider_config, 'kilo_config', None)
            if not kilo_config:
                kilo_config = getattr(self.provider_config, 'kiro_config', None)
        
        self._credentials_file = None
        self._api_base = None
        self._use_api_key_auth = False
        
        # If explicit API key is provided OR provider config has API key configured, use direct API key authentication - NO OAUTH
        if isinstance(self.provider_config, dict):
            configured_api_key = self.provider_config.get('api_key')
        else:
            configured_api_key = getattr(self.provider_config, 'api_key', None)
        if (self.api_key and self.api_key != "placeholder") or (configured_api_key and configured_api_key != "placeholder"):
            self._use_api_key_auth = True
            self.oauth2 = None
            # Use the configured provider api key if not explicitly passed
            if not self.api_key or self.api_key == "placeholder":
                self.api_key = configured_api_key
        else:
            # No API key provided - use OAuth2 flow
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"KiloProviderHandler.__init__: provider_id={provider_id}, user_id={user_id}")
            logger.info(f"KiloProviderHandler.__init__: kilo_config type={type(kilo_config)}, value={kilo_config}")
            
            if kilo_config and isinstance(kilo_config, dict):
                # Check both 'credentials_file' and 'creds_file' for backward compatibility
                credentials_path = kilo_config.get('credentials_file') or kilo_config.get('creds_file')
                logger.info(f"KiloProviderHandler.__init__: credentials_path={credentials_path}")
                if credentials_path:
                    self._credentials_file = os.path.expanduser(credentials_path)
                self._api_base = kilo_config.get('api_base')
            else:
                # Set default credentials file path when not explicitly configured
                self._credentials_file = os.path.expanduser("~/.kilo_credentials.json")
                self._api_base = None
            
            logger.info(f"KiloProviderHandler.__init__: self._credentials_file={self._credentials_file}")
            
            # Only the ONE config admin (user_id=None from aisbf.json) uses file-based credentials
            # All other users (including database admins with user_id) use database credentials
            if user_id is not None:
                logger.info(f"KiloProviderHandler.__init__: Loading from DB for user {user_id}")
                self.oauth2 = self._load_oauth2_from_db(provider_id, self._credentials_file, self._api_base)
            else:
                # Config admin (from aisbf.json): use file-based credentials
                logger.info(f"KiloProviderHandler.__init__: Loading from file for config admin")
                from ..auth.kilo import KiloOAuth2
                self.oauth2 = KiloOAuth2(credentials_file=self._credentials_file, api_base=self._api_base)
            
            logger.info(f"KiloProviderHandler.__init__: self.oauth2 type={type(self.oauth2)}, value={self.oauth2}")
        
        if isinstance(self.provider_config, dict):
            configured_endpoint = self.provider_config.get('endpoint')
        else:
            configured_endpoint = getattr(self.provider_config, 'endpoint', None)
        if configured_endpoint:
            endpoint = configured_endpoint.rstrip('/')
            if not endpoint.endswith('/v1'):
                endpoint = endpoint + '/v1'
        else:
            endpoint = 'https://kilo.ai/api/openrouter/v1'
        
        self._kilo_endpoint = endpoint
        
        self.client = OpenAI(base_url=endpoint, api_key=api_key or "placeholder")
    
    def _load_oauth2_from_db(self, provider_id: str, credentials_file: str, api_base: str):
        """
        Load OAuth2 credentials:
        - Admin users (user_id=None): ONLY load from file
        - Regular users: ONLY load from database, NO file fallback
        """
        from ..auth.kilo import KiloOAuth2
        import logging
        
        if self.user_id is None:
            # Admin user: ONLY use file-based credentials
            logging.getLogger(__name__).info(f"KiloProviderHandler: Admin user, loading credentials from file: {credentials_file}")
            return KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
        
        # Regular user: ONLY use database credentials, NO file fallback
        try:
            from ..database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            if db:
                db_creds = db.get_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=provider_id,
                    auth_type='kilo_oauth2'
                )
                if db_creds and db_creds.get('credentials'):
                    # Create OAuth2 instance with skip_initial_load=True to avoid file read
                    # Pass save callback to save credentials back to database
                    oauth2 = KiloOAuth2(
                        credentials_file=credentials_file, 
                        api_base=api_base, 
                        skip_initial_load=True,
                        save_callback=lambda creds: self._save_oauth2_to_db(creds)
                    )
                    # Set credentials directly from database
                    oauth2.credentials = db_creds['credentials']
                    logging.getLogger(__name__).info(f"KiloProviderHandler: Loaded credentials from database for user {self.user_id}")
                    return oauth2
        except Exception as e:
            logging.getLogger(__name__).warning(f"KiloProviderHandler: Failed to load credentials from database: {e}")
        
        # For regular users, NO file fallback - return empty auth instance
        logging.getLogger(__name__).info(f"KiloProviderHandler: No database credentials found for user {self.user_id}, returning unauthenticated instance")
        return KiloOAuth2(
            credentials_file=credentials_file, 
            api_base=api_base, 
            skip_initial_load=True,
            save_callback=lambda creds: self._save_oauth2_to_db(creds)
        )
    
    def _save_oauth2_to_db(self, credentials: Dict) -> None:
        """
        Save OAuth2 credentials to database for non-admin users.
        This is called after successful device flow authentication.
        """
        if self.user_id is None:
            # Admin user uses file-based credentials, nothing to save to DB
            return
        
        try:
            from ..database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            if db:
                db.save_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=self.provider_id,
                    auth_type='kilo_oauth2',
                    credentials=credentials
                )
                import logging
                logging.getLogger(__name__).info(f"KiloProviderHandler: Saved credentials to database for user {self.user_id}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"KiloProviderHandler: Failed to save credentials to database: {e}")
    
    async def _ensure_authenticated(self):
        """Ensure user is authenticated and return valid token.
        
        Returns immediately with status, never blocks polling in HTTP request.
        For device flow: only initiates flow, does NOT poll inside handler.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # DEBUG: Check self.oauth2 before using it
        logger.info(f"KiloProviderHandler._ensure_authenticated: self.oauth2 type={type(self.oauth2)}, value={self.oauth2}")
        logger.info(f"KiloProviderHandler._ensure_authenticated: self._use_api_key_auth={self._use_api_key_auth}")
        
        # If API key authentication is configured, use it directly - NO OAUTH EVER
        if self._use_api_key_auth:
            logger.info("KiloProviderHandler: Using configured API key authentication - skipping OAuth2 flow")
            return {
                "status": "authenticated",
                "token": self.api_key
            }

        logger.info(f"KiloProviderHandler._ensure_authenticated: About to call self.oauth2.get_valid_token()")
        token = self.oauth2.get_valid_token()  # NOT async - don't await

        if token:
            logger.info("KiloProviderHandler: Using existing OAuth2 token")
            return {
                "status": "authenticated",
                "token": token
            }
            
        # Try to reload credentials one more time - this handles the case where credentials
        # were saved by another process/handler instance after this handler was created
        self.oauth2._load_credentials()
        token = self.oauth2.get_valid_token()  # NOT async - don't await
        
        if token:
            logger.info("KiloProviderHandler: Found OAuth2 token after reloading credentials")
            return {
                "status": "authenticated",
                "token": token
            }
        
        logger.info("KiloProviderHandler: No valid OAuth2 token, initiating device flow")
        
        # Start the non-blocking device flow - ONLY initiate, DO NOT poll
        flow_info = await self.oauth2.initiate_device_flow()
        
        # Return immediately with pending status - NEVER block on poll in HTTP handler
        return {
            "status": "pending_authorization",
            "verification_url": flow_info["verification_url"],
            "code": flow_info["code"],
            "expires_in": flow_info["expires_in"],
            "poll_interval": flow_info["poll_interval"]
        }
    
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

            auth_result = await self._ensure_authenticated()
            
            if auth_result["status"] == "pending_authorization":
                # Return authorization required status instead of proceeding
                raise Exception(f"AUTHORIZATION_REQUIRED:{json.dumps(auth_result)}")
            
            token = auth_result["token"]
            
            self.client.api_key = token

            await self.apply_rate_limit()

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1024)
            prompt_cache_key = getattr(provider_config, 'prompt_cache_key', None)

            logging.info(f"KiloProviderHandler: Native caching enabled: {enable_native_caching}")
            if enable_native_caching:
                logging.info(f"KiloProviderHandler: Min cacheable tokens: {min_cacheable_tokens}, prompt_cache_key: {prompt_cache_key}")

            request_params = {
                "model": model,
                "messages": [],
                "temperature": temperature,
                "stream": stream
            }
            
            if max_tokens is not None:
                request_params["max_tokens"] = max_tokens
            
            # Add prompt_cache_key if provided (for OpenAI-compatible load balancer routing optimization)
            if enable_native_caching and prompt_cache_key:
                request_params["prompt_cache_key"] = prompt_cache_key
                logging.info(f"KiloProviderHandler: Added prompt_cache_key to request")
            
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
                        logging.info(f"KiloProviderHandler: Applied cache_control to message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")
                    
                    request_params["messages"].append(message)
            else:
                # Native caching disabled - build messages without cache_control
                for msg in messages:
                    message = {"role": msg["role"]}
                    
                    if msg["role"] == "tool":
                        if "tool_call_id" in msg and msg["tool_call_id"] is not None:
                            message["tool_call_id"] = msg["tool_call_id"]
                        else:
                            logging.warning(f"Skipping tool message without tool_call_id: {msg}")
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

            if stream:
                logging.info(f"KiloProviderHandler: Using async httpx streaming mode")
                return await self._handle_streaming_request(request_params, token, model)

            response = self.client.chat.completions.create(**request_params)
            logging.info(f"KiloProviderHandler: Response received: {response}")
            self.record_success()
            
            if AISBF_DEBUG:
                logging.info(f"=== RAW KILO RESPONSE ===")
                logging.info(f"Raw response type: {type(response)}")
                logging.info(f"Raw response: {response}")
                logging.info(f"=== END RAW KILO RESPONSE ===")
            
            logging.info(f"KiloProviderHandler: Returning raw response without parsing")
            return response
        except Exception as e:
            import logging
            logging.error(f"KiloProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def _handle_streaming_request(self, request_params: Dict, token: str, model: str):
        """Handle streaming request to Kilo API using httpx async streaming."""
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info(f"KiloProviderHandler: Starting async streaming request to {self._kilo_endpoint}")
        
        api_url = f"{self._kilo_endpoint}/chat/completions"
        
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
            await streaming_client.aclose()
            raise
        
        return self._stream_kilo_response(streaming_client, response, model)
    
    async def _stream_kilo_response(self, streaming_client, response, model: str):
        """Yield SSE chunks from an already-validated Kilo streaming response."""
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        
        try:
            async for line in response.aiter_lines():
                if not line:
                    continue
                
                if line.startswith('data: '):
                    data_str = line[6:]
                    
                    if data_str.strip() == '[DONE]':
                        yield b"data: [DONE]\n\n"
                        break
                    
                    try:
                        chunk_data = json.loads(data_str)
                        
                        yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode('utf-8')
                        
                    except json.JSONDecodeError as e:
                        logger.warning(f"KiloProviderHandler: Failed to parse streaming chunk: {e}")
                        continue
                elif line.startswith(':'):
                    continue
            
            logger.info(f"KiloProviderHandler: Streaming completed successfully")
            self.record_success()
        finally:
            await response.aclose()
            await streaming_client.aclose()

    async def get_models(self):
        try:
            import logging
            import json
            logging.info("KiloProviderHandler: Getting models list")

            auth_result = await self._ensure_authenticated()
            
            if auth_result["status"] == "pending_authorization":
                # Return authorization required status instead of models list
                logging.info("KiloProviderHandler: Returning pending authorization status for models request")
                return auth_result
            
            token = auth_result["token"]

            await self.apply_rate_limit()

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
            if AISBF_DEBUG:
                response_str = str(models_data)
                if len(response_str) > 1024:
                    response_str = response_str[:1024] + f" ... [TRUNCATED, total length: {len(response_str)} chars]"
                logging.info(f"KiloProviderHandler: Models received: {response_str}")
            else:
                model_count = len(models_data) if isinstance(models_data, (list, dict)) else 'N/A'
                logging.info(f"KiloProviderHandler: Models received: {model_count} models")

            models_list = models_data.get('data', []) if isinstance(models_data, dict) else models_data

            result = []
            for model_entry in models_list:
                if isinstance(model_entry, dict):
                    model_id = model_entry.get('id', '')
                    model_name = model_entry.get('name', model_id) or model_id

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
