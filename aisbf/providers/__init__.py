"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Provider handlers for AISBF.

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

Provider handlers for AISBF.
"""
from typing import Optional

from .base import (
    BaseProviderHandler,
    AnthropicFormatConverter,
    AdaptiveRateLimiter,
    get_adaptive_rate_limiter,
    get_all_adaptive_rate_limiters,
    AISBF_DEBUG,
)
from .google import GoogleProviderHandler
from .openai import OpenAIProviderHandler
from .anthropic import AnthropicProviderHandler
from .claude import ClaudeProviderHandler
from .kiro import KiroProviderHandler
from .kilo import KiloProviderHandler
from .ollama import OllamaProviderHandler
from .codex import CodexProviderHandler
from .qwen import QwenProviderHandler
from ..config import config


PROVIDER_HANDLERS = {
    'google': GoogleProviderHandler,
    'openai': OpenAIProviderHandler,
    'anthropic': AnthropicProviderHandler,
    'ollama': OllamaProviderHandler,
    'kiro': KiroProviderHandler,
    'claude': ClaudeProviderHandler,
    'kilo': KiloProviderHandler,
    'kilocode': KiloProviderHandler,  # Kilocode provider with OAuth2 support
    'codex': CodexProviderHandler,  # Codex provider with OAuth2 support (OpenAI protocol)
    'qwen': QwenProviderHandler  # Qwen provider with OAuth2 support (OpenAI-compatible)
}


def get_provider_handler(provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None) -> BaseProviderHandler:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"=== get_provider_handler START ===")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"API key provided: {bool(api_key)}")
    logger.info(f"User ID: {user_id}")
    
    # First check for user-specific provider configuration if user_id is provided
    provider_config = None
    if user_id is not None:
        try:
            from ..database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            user_provider = db.get_user_provider(user_id, provider_id)
            if user_provider:
                provider_config = user_provider['config']
                logger.info(f"Using user-specific provider configuration for user {user_id}")
        except Exception as e:
            logger.debug(f"Failed to load user-specific provider config: {e}")
    
    # For authenticated users: NO fallback to global providers
    if user_id is not None and not provider_config:
        logger.error(f"User {user_id} attempted to access provider '{provider_id}' which does not exist in their configuration")
        raise ValueError(f"Provider '{provider_id}' not found in user configuration")
    
    # Fallback to global config only if no user_id is provided
    if not provider_config:
        provider_config = config.get_provider(provider_id)
        logger.info(f"Using global provider configuration")
    
    logger.info(f"Provider config: {provider_config}")
    
    # Handle both dict (user providers) and object (global providers)
    if isinstance(provider_config, dict):
        provider_type = provider_config.get('type')
        api_key = provider_config.get('api_key')
    else:
        provider_type = provider_config.type
        api_key = provider_config.api_key if hasattr(provider_config, 'api_key') else None
    
    logger.info(f"Provider type: {provider_type}")
    
    handler_class = PROVIDER_HANDLERS.get(provider_type)
    logger.info(f"Handler class: {handler_class.__name__ if handler_class else 'None'}")
    logger.info(f"Available handler types: {list(PROVIDER_HANDLERS.keys())}")
    
    if not handler_class:
        logger.error(f"Unsupported provider type: {provider_type}")
        raise ValueError(f"Unsupported provider type: {provider_type}")
    
    # Check if handler supports user_id parameter
    import inspect
    sig = inspect.signature(handler_class.__init__)
    if 'user_id' in sig.parameters:
        logger.info(f"Creating handler with provider_id, api_key, and user_id")
        handler = handler_class(provider_id, api_key, user_id=user_id)
    else:
        # For older providers that don't accept user_id parameter
        logger.info(f"Creating handler with provider_id and api_key (no user_id support)")
        # Create a patched instance with user_id for base class initialization
        handler = handler_class(provider_id, api_key)
        # Set user_id manually for base class compatibility
        handler.user_id = user_id
        # Base class already handles default error tracking and rate limit for user providers
    
    # Store user provider config on the handler for later use
    if user_id is not None and provider_config is not None:
        handler.user_provider_config = provider_config
    
    logger.info(f"Handler created: {handler.__class__.__name__}")
    logger.info(f"=== get_provider_handler END ===")
    return handler
