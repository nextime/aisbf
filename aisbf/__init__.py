"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations.

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

A modular proxy server for managing multiple AI provider integrations.
"""

from .config import config, Config, ProviderConfig, RotationConfig, AppConfig, AutoselectConfig, AutoselectModelInfo, CondensationConfig
from .context import ContextManager, get_context_config_for_model
from .database import DatabaseManager, get_database, initialize_database
from .models import (
    Message,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Model,
    Provider,
    ErrorTracking
)
from .providers import (
    BaseProviderHandler,
    GoogleProviderHandler,
    OpenAIProviderHandler,
    AnthropicProviderHandler,
    ClaudeProviderHandler,
    KiloProviderHandler,
    OllamaProviderHandler,
    QwenProviderHandler,
    get_provider_handler,
    PROVIDER_HANDLERS
)
from .providers.kiro import KiroProviderHandler
from .auth.kiro import KiroAuthManager
from .auth.claude import ClaudeAuth
from .auth.kilo import KiloOAuth2
from .auth.qwen import QwenOAuth2
from .handlers import RequestHandler, RotationHandler, AutoselectHandler
from .utils import count_messages_tokens, split_messages_into_chunks, get_max_request_tokens_for_model

__version__ = "0.99.2"
__all__ = [
    # Config
    "config",
    "Config",
    "ProviderConfig",
    "RotationConfig",
    "AppConfig",
    "AutoselectConfig",
    "AutoselectModelInfo",
    # Models
    "Message",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "Model",
    "Provider",
    "ErrorTracking",
    "AutoselectModelInfo",
    "AutoselectConfig",
    # Providers
    "BaseProviderHandler",
    "GoogleProviderHandler",
    "OpenAIProviderHandler",
    "AnthropicProviderHandler",
    "OllamaProviderHandler",
    "ClaudeProviderHandler",
    "KiloProviderHandler",
    "KiroProviderHandler",
    "QwenProviderHandler",
    "get_provider_handler",
    "PROVIDER_HANDLERS",
    # Auth
    "KiroAuthManager",
    "ClaudeAuth",
    "KiloOAuth2",
    "QwenOAuth2",
    # Handlers
    "RequestHandler",
    "RotationHandler",
    "AutoselectHandler",
    # Context
    "ContextManager",
    "get_context_config_for_model",
    # Utils
    "count_messages_tokens",
    "split_messages_into_chunks",
    "get_max_request_tokens_for_model",
]
