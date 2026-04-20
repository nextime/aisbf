"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Qwen OAuth2 provider handler.

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
import asyncio
import time
import json
import platform
import uuid
from typing import Dict, List, Optional, Union
from openai import AsyncOpenAI
from ..models import Model
from ..config import config
from .base import BaseProviderHandler, AISBF_DEBUG


class QwenProviderHandler(BaseProviderHandler):
    """
    Handler for Qwen OAuth2 integration using OpenAI-compatible API.
    
    This handler uses OAuth2 authentication to access Qwen models through
    the DashScope OpenAI-compatible endpoint. OAuth2 access tokens are passed
    as the api_key parameter to the OpenAI SDK.
    
    For admin users (user_id=None), credentials are loaded from file.
    For non-admin users, credentials are loaded from the database.
    """
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None):
        super().__init__(provider_id, api_key)
        self.user_id = user_id
        self.provider_config = config.get_provider(provider_id)
        
        # Get credentials file path from config
        qwen_config = getattr(self.provider_config, 'qwen_config', None)
        credentials_file = None
        if qwen_config and isinstance(qwen_config, dict):
            credentials_file = qwen_config.get('credentials_file')
        
        # Only the ONE config admin (user_id=None from aisbf.json) uses file-based credentials
        # All other users (including database admins with user_id) use database credentials
        if user_id is not None:
            self.auth = self._load_auth_from_db(provider_id, credentials_file)
        else:
            # Config admin (from aisbf.json): use file-based credentials
            from ..auth.qwen import QwenOAuth2
            self.auth = QwenOAuth2(credentials_file=credentials_file)
        
        # HTTP client for direct API requests
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        
        # OpenAI SDK client (will be configured dynamically with OAuth token)
        self._sdk_client = None
    
    def _load_auth_from_db(self, provider_id: str, credentials_file: str):
        """
        Load OAuth2 credentials from database for non-admin users.
        Falls back to file-based credentials if not found in database.
        """
        try:
            from ..database import get_database
            from ..auth.qwen import QwenOAuth2
            db = get_database()
            if db:
                db_creds = db.get_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=provider_id,
                    auth_type='qwen_oauth2'
                )
                if db_creds and db_creds.get('credentials'):
                    # Create auth instance with database credentials
                    auth = QwenOAuth2(credentials_file=credentials_file)
                    # Override the loaded credentials with database credentials
                    auth.credentials = db_creds['credentials']
                    import logging
                    logging.getLogger(__name__).info(f"QwenProviderHandler: Loaded credentials from database for user {self.user_id}")
                    return auth
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"QwenProviderHandler: Failed to load credentials from database: {e}")
        
        # Fall back to file-based credentials
        from ..auth.qwen import QwenOAuth2
        import logging
        logging.getLogger(__name__).info(f"QwenProviderHandler: Falling back to file-based credentials for user {self.user_id}")
        return QwenOAuth2(credentials_file=credentials_file)
    
    async def _get_sdk_client(self):
        """Get or create an OpenAI SDK client configured with authentication (OAuth2 or API key)."""
        import logging
        logger = logging.getLogger(__name__)

        # Check if API key is configured (vs OAuth2)
        qwen_config = getattr(self.provider_config, 'qwen_config', None)
        api_key = None
        if qwen_config and isinstance(qwen_config, dict):
            api_key = qwen_config.get('api_key')

        if api_key:
            # Use API key authentication
            logger.info("QwenProviderHandler: Using API key authentication")
            auth_key = api_key
            # Use region-based endpoint for API key authentication
            base_url = self._get_region_endpoint(qwen_config)
        else:
            # Use OAuth2 authentication
            access_token = await self.auth.get_valid_token_with_refresh()

            if not access_token:
                logger.error("QwenProviderHandler: No OAuth2 access token available")
                raise Exception("No OAuth2 access token. Please re-authenticate")

            logger.info("QwenProviderHandler: Using OAuth2 authentication")
            auth_key = access_token
            # Get resource URL from auth and normalize it properly
            base_url = self.auth.get_resource_url()
            
            # Normalize endpoint exactly as specified in documentation
            if not base_url.startswith("http"):
                base_url = f"https://{base_url}"
            
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"
            
            logger.info(f"QwenProviderHandler: Final endpoint: {base_url}")

        # Build required DashScope headers
        import uuid
        user_agent = f"QwenCode/1.0.0 ({platform.system().lower()}; {platform.machine()})"
        default_headers = {
            "Accept": "application/json",
            "X-DashScope-CacheControl": "enable",
            "X-DashScope-UserAgent": user_agent,
            "X-DashScope-AuthType": "qwen-oauth",
            "x-request-id": str(uuid.uuid4()),
        }

        self._sdk_client = AsyncOpenAI(
            api_key=auth_key,
            base_url=base_url,
            max_retries=3,
            timeout=httpx.Timeout(300.0, connect=30.0),
            default_headers=default_headers,
        )

        logger.info(f"QwenProviderHandler: Created SDK client (endpoint: {base_url})")
        return self._sdk_client

    def _get_region_endpoint(self, qwen_config: Dict) -> str:
        """Get the appropriate endpoint URL based on the configured region."""
        region = qwen_config.get('region', 'china-beijing')  # Default to China (Beijing)

        region_endpoints = {
            'singapore': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
            'us-virginia': 'https://dashscope-us.aliyuncs.com/compatible-mode/v1',
            'china-beijing': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'china-hongkong': 'https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1',
            'germany-frankfurt': f"https://{qwen_config.get('workspace_id', 'Default Workspace')}.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
        }

        endpoint = region_endpoints.get(region, region_endpoints['china-beijing'])
        return endpoint
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get HTTP headers with authentication (OAuth2 or API key) and DashScope-specific headers."""
        import logging
        logger = logging.getLogger(__name__)

        # Check if API key is configured (vs OAuth2)
        qwen_config = getattr(self.provider_config, 'qwen_config', None)
        api_key = None
        if qwen_config and isinstance(qwen_config, dict):
            api_key = qwen_config.get('api_key')

        if api_key:
            # Use API key authentication
            auth_value = f"Bearer {api_key}"
            auth_type = "api-key"
        else:
            # Use OAuth2 authentication
            access_token = self.auth.get_valid_token()

            if not access_token:
                logger.error("QwenProviderHandler: No OAuth2 access token available")
                raise Exception("No OAuth2 access token. Please re-authenticate")

            auth_value = f"Bearer {access_token}"
            auth_type = "qwen-oauth"

        headers = {
            "Authorization": auth_value,
            "Content-Type": "application/json",
            "User-Agent": "QwenCode/1.0.0 (linux; x86_64)",
            "X-DashScope-CacheControl": "enable",
            "X-DashScope-UserAgent": "QwenCode/1.0.0 (linux; x86_64)",
            "X-DashScope-AuthType": auth_type,
        }

        logger.debug(f"QwenProviderHandler: Created auth headers with {auth_type} authentication")
        return headers
    
    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        """Handle chat completion request using OpenAI-compatible API."""
        import logging
        logger = logging.getLogger(__name__)
        
        if self.is_rate_limited():
            raise Exception("Provider rate limited")
        
        logger.info(f"QwenProviderHandler: Handling request for model {model}")
        
        if AISBF_DEBUG:
            logger.info(f"QwenProviderHandler: Messages: {messages}")
        else:
            logger.info(f"QwenProviderHandler: Messages count: {len(messages)}")
        
        await self.apply_rate_limit()
        
        # Get SDK client with current OAuth token
        client = await self._get_sdk_client()
        
        # Generate session tracking IDs
        session_id = str(uuid.uuid4())
        prompt_id = str(uuid.uuid4())
        
        # Build request parameters
        request_params = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or 4096,
            "stream": stream,
            "extra_body": {
                "metadata": {
                    "sessionId": session_id,
                    "promptId": prompt_id
                }
            }
        }
        
        if temperature is not None and temperature > 0:
            request_params["temperature"] = temperature
        
        if tools:
            request_params["tools"] = tools
        
        if tool_choice and tools:
            request_params["tool_choice"] = tool_choice
        
        # Add stream_options for streaming requests
        if stream:
            request_params["stream_options"] = {"include_usage": True}
        
        try:
            if stream:
                logger.info("QwenProviderHandler: Using streaming mode")
                return self._handle_streaming_request(client, request_params, model)
            else:
                logger.info("QwenProviderHandler: Using non-streaming mode")
                response = await client.chat.completions.create(**request_params)
                
                self.record_success()
                
                # Convert to OpenAI format dict
                openai_response = {
                    'id': response.id,
                    'object': 'chat.completion',
                    'created': response.created,
                    'model': f'{self.provider_id}/{model}',
                    'choices': [
                        {
                            'index': choice.index,
                            'message': {
                                'role': choice.message.role,
                                'content': choice.message.content,
                            },
                            'finish_reason': choice.finish_reason
                        }
                        for choice in response.choices
                    ],
                    'usage': {
                        'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                        'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                        'total_tokens': response.usage.total_tokens if response.usage else 0,
                    }
                }
                
                # Add tool calls if present
                for i, choice in enumerate(response.choices):
                    if choice.message.tool_calls:
                        openai_response['choices'][i]['message']['tool_calls'] = [
                            {
                                'id': tc.id,
                                'type': tc.type,
                                'function': {
                                    'name': tc.function.name,
                                    'arguments': tc.function.arguments
                                }
                            }
                            for tc in choice.message.tool_calls
                        ]
                
                if AISBF_DEBUG:
                    logger.info(f"QwenProviderHandler: Response: {json.dumps(openai_response, indent=2, default=str)}")
                
                return openai_response
                
        except Exception as e:
            logger.error(f"QwenProviderHandler: Request failed: {e}", exc_info=True)
            
            # Check if it's an auth error - try to refresh token
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ['401', '403', 'unauthorized', 'forbidden', 'invalid', 'token']):
                logger.info("QwenProviderHandler: Auth error detected, attempting token refresh")
                
                # Try to refresh token
                refresh_success = await self.auth.refresh_tokens()
                
                if refresh_success:
                    logger.info("QwenProviderHandler: Token refreshed, retrying request")
                    # Retry with new token
                    client = await self._get_sdk_client()
                    
                    if stream:
                        return self._handle_streaming_request(client, request_params, model)
                    else:
                        response = await client.chat.completions.create(**request_params)
                        self.record_success()
                        
                        # Convert to dict (same as above)
                        openai_response = {
                            'id': response.id,
                            'object': 'chat.completion',
                            'created': response.created,
                            'model': f'{self.provider_id}/{model}',
                            'choices': [
                                {
                                    'index': choice.index,
                                    'message': {
                                        'role': choice.message.role,
                                        'content': choice.message.content,
                                    },
                                    'finish_reason': choice.finish_reason
                                }
                                for choice in response.choices
                            ],
                            'usage': {
                                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                                'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                                'total_tokens': response.usage.total_tokens if response.usage else 0,
                            }
                        }
                        
                        for i, choice in enumerate(response.choices):
                            if choice.message.tool_calls:
                                openai_response['choices'][i]['message']['tool_calls'] = [
                                    {
                                        'id': tc.id,
                                        'type': tc.type,
                                        'function': {
                                            'name': tc.function.name,
                                            'arguments': tc.function.arguments
                                        }
                                    }
                                    for tc in choice.message.tool_calls
                                ]
                        
                        return openai_response
                else:
                    logger.error("QwenProviderHandler: Token refresh failed")
            
            self.record_failure()
            raise
    
    async def _handle_streaming_request(self, client, request_params: Dict, model: str):
        """Handle streaming request using OpenAI SDK."""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("QwenProviderHandler: Starting streaming request")
        
        try:
            stream = await client.chat.completions.create(**request_params)
            
            completion_id = f"qwen-{int(time.time())}"
            created_time = int(time.time())
            
            async for chunk in stream:
                # Convert SDK chunk to OpenAI format
                openai_chunk = {
                    'id': chunk.id or completion_id,
                    'object': 'chat.completion.chunk',
                    'created': chunk.created or created_time,
                    'model': f'{self.provider_id}/{model}',
                    'choices': []
                }
                
                for choice in chunk.choices:
                    choice_dict = {
                        'index': choice.index,
                        'delta': {},
                        'finish_reason': choice.finish_reason
                    }
                    
                    if choice.delta.role:
                        choice_dict['delta']['role'] = choice.delta.role
                    
                    if choice.delta.content:
                        choice_dict['delta']['content'] = choice.delta.content
                    
                    if choice.delta.tool_calls:
                        choice_dict['delta']['tool_calls'] = [
                            {
                                'index': tc.index,
                                'id': tc.id,
                                'type': tc.type,
                                'function': {
                                    'name': tc.function.name if tc.function else None,
                                    'arguments': tc.function.arguments if tc.function else None
                                }
                            }
                            for tc in choice.delta.tool_calls
                        ]
                    
                    openai_chunk['choices'].append(choice_dict)
                
                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
            
            # Send final [DONE] marker
            yield b"data: [DONE]\n\n"
            
            self.record_success()
            logger.info("QwenProviderHandler: Streaming completed successfully")
            
        except Exception as e:
            logger.error(f"QwenProviderHandler: Streaming error: {e}", exc_info=True)
            self.record_failure()
            raise
    
    async def get_models(self) -> List[Model]:
        """Return list of available Qwen models."""
        import logging
        logger = logging.getLogger(__name__)

        logger.info("QwenProviderHandler: Fetching available models")

        await self.apply_rate_limit()

        # Check if API token is configured (vs OAuth2)
        qwen_config = getattr(self.provider_config, 'qwen_config', None)
        using_api_key = qwen_config and isinstance(qwen_config, dict) and qwen_config.get('api_key')

        if not using_api_key:
            # OAuth2 authentication: return full model list
            logger.info("QwenProviderHandler: Using OAuth2 authentication, returning full model list")
            return [
                Model(
                    id="qwen-turbo",
                    name="Qwen Turbo",
                    provider_id=self.provider_id,
                    context_size=32000,
                    context_length=32000,
                ),
                Model(
                    id="qwen-plus",
                    name="Qwen Plus",
                    provider_id=self.provider_id,
                    context_size=128000,
                    context_length=128000,
                ),
                Model(
                    id="qwen-max",
                    name="Qwen Max",
                    provider_id=self.provider_id,
                    context_size=128000,
                    context_length=128000,
                ),
                Model(
                    id="qwen3-coder-plus",
                    name="Qwen 3 Coder Plus",
                    provider_id=self.provider_id,
                    context_size=128000,
                    context_length=128000,
                ),
            ]

        # API token authentication: fetch from models endpoint
        logger.info("QwenProviderHandler: Using API token authentication, fetching from models endpoint")

        # Check if models are already defined in provider configuration
        if self.provider_config.models and len(self.provider_config.models) > 0:
            # Models are defined in configuration, use those instead of fetching
            logger.info("QwenProviderHandler: Models defined in configuration, using configured models")
            models = []
            for model_config in self.provider_config.models:
                models.append(Model(
                    id=model_config.get('name', ''),
                    name=model_config.get('name', ''),
                    provider_id=self.provider_id,
                    context_size=model_config.get('context_size', 32000),
                    context_length=model_config.get('context_size', 32000),
                ))
            return models

        try:
            # Get SDK client with API key authentication
            client = await self._get_sdk_client()

            # List models using OpenAI SDK
            models_response = await client.models.list()

            models = []
            for model_data in models_response.data:
                model_id = model_data.id

                # Extract context size if available
                context_size = None
                if hasattr(model_data, 'context_window'):
                    context_size = model_data.context_window
                elif hasattr(model_data, 'max_model_len'):
                    context_size = model_data.max_model_len

                models.append(Model(
                    id=model_id,
                    name=model_id,
                    provider_id=self.provider_id,
                    context_size=context_size,
                    context_length=context_size,
                ))

                logger.debug(f"QwenProviderHandler: Found model: {model_id}")

            if not models:
                # Fallback to static model list
                logger.warning("QwenProviderHandler: No models returned from API, using static list")
                models = [
                    Model(id="qwen-turbo", name="Qwen Turbo", provider_id=self.provider_id, context_size=32000),
                    Model(id="qwen-plus", name="Qwen Plus", provider_id=self.provider_id, context_size=128000),
                    Model(id="qwen-max", name="Qwen Max", provider_id=self.provider_id, context_size=128000),
                    Model(id="qwen3-coder-plus", name="Qwen 3 Coder Plus", provider_id=self.provider_id, context_size=128000),
                ]

            logger.info(f"QwenProviderHandler: Returning {len(models)} models")
            return models

        except Exception as e:
            logger.error(f"QwenProviderHandler: Failed to fetch models: {e}", exc_info=True)

            # Return static fallback list
            logger.info("QwenProviderHandler: Using static fallback model list")
            return [
                Model(id="qwen-turbo", name="Qwen Turbo", provider_id=self.provider_id, context_size=32000),
                Model(id="qwen-plus", name="Qwen Plus", provider_id=self.provider_id, context_size=128000),
                Model(id="qwen-max", name="Qwen Max", provider_id=self.provider_id, context_size=128000),
                Model(id="qwen3-coder-plus", name="Qwen 3 Coder Plus", provider_id=self.provider_id, context_size=128000),
            ]
