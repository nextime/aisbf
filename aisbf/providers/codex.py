"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Codex provider handler.
Uses the same protocol as OpenAI but with OAuth2 authentication.

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
import logging
import time
from typing import Dict, List, Optional, Union

from openai import OpenAI

from ..models import Model
from ..config import config
from ..utils import count_messages_tokens
from .base import BaseProviderHandler, AISBF_DEBUG
from ..auth.codex import CodexOAuth2


class CodexProviderHandler(BaseProviderHandler):
    """
    Codex provider handler.
    
    Uses the same OpenAI-compatible protocol but authenticates via OAuth2
    using the Codex OAuth2 flow (device code or browser-based PKCE).
    
    For admin users (user_id=None), credentials are loaded from file.
    For non-admin users, credentials are loaded from the database.
    """
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None):
        super().__init__(provider_id, api_key)
        self.user_id = user_id
        
        # Get provider config
        provider_config = config.providers.get(provider_id)
        endpoint = provider_config.endpoint if provider_config else "https://api.openai.com/v1"
        
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
        
        # Resolve API key: use provided key, or get from OAuth2, or use stored API key
        resolved_api_key = api_key
        if not resolved_api_key:
            # Try to get OAuth2 access token
            resolved_api_key = self.oauth2.get_valid_token()
        
        if not resolved_api_key:
            # Fall back to provider config API key
            if provider_config and provider_config.api_key:
                resolved_api_key = provider_config.api_key
        
        self.client = OpenAI(base_url=endpoint, api_key=resolved_api_key or "dummy")
        self._oauth2_enabled = not api_key and provider_config and not provider_config.api_key_required
    
    def _load_oauth2_from_db(self, provider_id: str, credentials_file: str, issuer: str) -> CodexOAuth2:
        """
        Load OAuth2 credentials from database for non-admin users.
        Falls back to file-based credentials if not found in database.
        """
        try:
            from ..database import get_database
            db = get_database()
            if db:
                db_creds = db.get_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=provider_id,
                    auth_type='codex_oauth2'
                )
                if db_creds and db_creds.get('credentials'):
                    # Create OAuth2 instance with database credentials
                    oauth2 = CodexOAuth2(
                        credentials_file=credentials_file,
                        issuer=issuer,
                    )
                    # Override the loaded credentials with database credentials
                    oauth2.credentials = db_creds['credentials']
                    logger.info(f"CodexProviderHandler: Loaded credentials from database for user {self.user_id}")
                    return oauth2
        except Exception as e:
            logger.warning(f"CodexProviderHandler: Failed to load credentials from database: {e}")
        
        # Fall back to file-based credentials
        logger.info(f"CodexProviderHandler: Falling back to file-based credentials for user {self.user_id}")
        return CodexOAuth2(
            credentials_file=credentials_file,
            issuer=issuer,
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
            return token
        
        raise Exception("Codex authentication required. Please authenticate via dashboard or provide API key.")
    
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
            logger = logging.getLogger(__name__)
            logger.info(f"CodexProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logger.info(f"CodexProviderHandler: Messages: {messages}")
            else:
                logger.info(f"CodexProviderHandler: Messages count: {len(messages)}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Get valid API key (with OAuth2 refresh if needed)
            api_key = await self._get_valid_api_key()
            
            # Re-initialize client with fresh token if OAuth2 is enabled
            if self._oauth2_enabled:
                provider_config = config.providers.get(self.provider_id)
                endpoint = provider_config.endpoint if provider_config else "https://api.openai.com/v1"
                self.client = OpenAI(base_url=endpoint, api_key=api_key)

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1024)
            prompt_cache_key = getattr(provider_config, 'prompt_cache_key', None)

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
            
            # Add prompt_cache_key if provided
            if enable_native_caching and prompt_cache_key:
                request_params["prompt_cache_key"] = prompt_cache_key
            
            # Build messages with all fields
            if enable_native_caching:
                cumulative_tokens = 0
                for i, msg in enumerate(messages):
                    message_tokens = count_messages_tokens([msg], model)
                    cumulative_tokens += message_tokens

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
                    
                    if (msg["role"] == "system" or
                        (i < len(messages) - 2 and cumulative_tokens >= min_cacheable_tokens)):
                        message["cache_control"] = {"type": "ephemeral"}
                    
                    request_params["messages"].append(message)
            else:
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
            logger.info(f"CodexProviderHandler: Response received")
            self.record_success()
            
            if AISBF_DEBUG:
                logger.info(f"=== RAW CODEX RESPONSE ===")
                logger.info(f"Raw response type: {type(response)}")
                logger.info(f"Raw response: {response}")
                logger.info(f"=== END RAW CODEX RESPONSE ===")
            
            return response
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"CodexProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        try:
            logger = logging.getLogger(__name__)
            logger.info("CodexProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Get valid API key for models list
            api_key = await self._get_valid_api_key()
            provider_config = config.providers.get(self.provider_id)
            endpoint = provider_config.endpoint if provider_config else "https://api.openai.com/v1"
            
            # Create temporary client with fresh token
            temp_client = OpenAI(base_url=endpoint, api_key=api_key)
            
            models = temp_client.models.list()
            logger.info(f"CodexProviderHandler: Models received")

            result = []
            for model in models:
                context_size = None
                if hasattr(model, 'context_window') and model.context_window:
                    context_size = model.context_window
                elif hasattr(model, 'context_length') and model.context_length:
                    context_size = model.context_length
                elif hasattr(model, 'max_context_length') and model.max_context_length:
                    context_size = model.max_context_length
                
                pricing = None
                if hasattr(model, 'pricing') and model.pricing:
                    pricing = model.pricing
                elif hasattr(model, 'top_provider') and model.top_provider:
                    top_provider = model.top_provider
                    if hasattr(top_provider, 'dict'):
                        top_provider = top_provider.dict()
                    if isinstance(top_provider, dict):
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
            logger = logging.getLogger(__name__)
            logger.error(f"CodexProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e
