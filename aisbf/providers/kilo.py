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
from typing import Dict, List, Optional, Union
from openai import OpenAI
from ..models import Model
from ..config import config
from .base import BaseProviderHandler, AISBF_DEBUG


class KiloProviderHandler(BaseProviderHandler):
    """
    Handler for Kilo Gateway (OpenAI-compatible with OAuth2 support).
    
    For admin users (user_id=None), credentials are loaded from file.
    For non-admin users, credentials are loaded from the database.
    """
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None):
        super().__init__(provider_id, api_key)
        self.user_id = user_id
        self.provider_config = config.get_provider(provider_id)
        
        kilo_config = getattr(self.provider_config, 'kilo_config', None)
        
        credentials_file = None
        api_base = None
        
        if kilo_config and isinstance(kilo_config, dict):
            credentials_file = kilo_config.get('credentials_file')
            api_base = kilo_config.get('api_base')
        
        # Only the ONE config admin (user_id=None from aisbf.json) uses file-based credentials
        # All other users (including database admins with user_id) use database credentials
        if user_id is not None:
            self.oauth2 = self._load_oauth2_from_db(provider_id, credentials_file, api_base)
        else:
            # Config admin (from aisbf.json): use file-based credentials
            from ..auth.kilo import KiloOAuth2
            self.oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
        
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
        Load OAuth2 credentials from database for non-admin users.
        Falls back to file-based credentials if not found in database.
        """
        try:
            from ..database import get_database
            from ..auth.kilo import KiloOAuth2
            db = get_database()
            if db:
                db_creds = db.get_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=provider_id,
                    auth_type='kilo_oauth2'
                )
                if db_creds and db_creds.get('credentials'):
                    # Create OAuth2 instance with database credentials
                    oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
                    # Override the loaded credentials with database credentials
                    oauth2.credentials = db_creds['credentials']
                    import logging
                    logging.getLogger(__name__).info(f"KiloProviderHandler: Loaded credentials from database for user {self.user_id}")
                    return oauth2
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"KiloProviderHandler: Failed to load credentials from database: {e}")
        
        # Fall back to file-based credentials
        from ..auth.kilo import KiloOAuth2
        import logging
        logging.getLogger(__name__).info(f"KiloProviderHandler: Falling back to file-based credentials for user {self.user_id}")
        return KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
    
    async def _ensure_authenticated(self) -> str:
        """Ensure user is authenticated and return valid token."""
        import logging
        logger = logging.getLogger(__name__)
        
        token = self.oauth2.get_valid_token()
        
        if token:
            logger.info("KiloProviderHandler: Using existing OAuth2 token")
            return token
        
        if self.api_key and self.api_key != "placeholder":
            logger.info("KiloProviderHandler: Using API key authentication")
            return self.api_key
        
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

            token = await self._ensure_authenticated()
            
            self.client.api_key = token

            await self.apply_rate_limit()

            request_params = {
                "model": model,
                "messages": [],
                "temperature": temperature,
                "stream": stream
            }
            
            if max_tokens is not None:
                request_params["max_tokens"] = max_tokens
            
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

    async def get_models(self) -> List[Model]:
        try:
            import logging
            import json
            logging.info("KiloProviderHandler: Getting models list")

            token = await self._ensure_authenticated()

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
            logging.info(f"KiloProviderHandler: Models received: {models_data}")

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
