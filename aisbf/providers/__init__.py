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
    'codex': CodexProviderHandler  # Codex provider with OAuth2 support (OpenAI protocol)
}


def get_provider_handler(provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None) -> BaseProviderHandler:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"=== get_provider_handler START ===")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"API key provided: {bool(api_key)}")
    logger.info(f"User ID: {user_id}")
    
    provider_config = config.get_provider(provider_id)
    logger.info(f"Provider config: {provider_config}")
    logger.info(f"Provider type: {provider_config.type}")
    logger.info(f"Provider endpoint: {provider_config.endpoint}")
    
    handler_class = PROVIDER_HANDLERS.get(provider_config.type)
    logger.info(f"Handler class: {handler_class.__name__ if handler_class else 'None'}")
    logger.info(f"Available handler types: {list(PROVIDER_HANDLERS.keys())}")
    
    if not handler_class:
        logger.error(f"Unsupported provider type: {provider_config.type}")
        raise ValueError(f"Unsupported provider type: {provider_config.type}")
    
    # Check if handler supports user_id parameter (CodexProviderHandler does)
    import inspect
    sig = inspect.signature(handler_class.__init__)
    if 'user_id' in sig.parameters:
        logger.info(f"Creating handler with provider_id, optional api_key, and user_id")
        handler = handler_class(provider_id, api_key, user_id=user_id)
    else:
        logger.info(f"Creating handler with provider_id and optional api_key")
        handler = handler_class(provider_id, api_key)
    
    logger.info(f"Handler created: {handler.__class__.__name__}")
    logger.info(f"=== get_provider_handler END ===")
    return handler
