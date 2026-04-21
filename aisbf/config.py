"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Configuration management for AISBF.

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

Configuration management for AISBF.
"""
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field
import json
import shutil
import os
from pathlib import Path

class ProviderModelConfig(BaseModel):
    """Model configuration within a provider"""
    name: str
    rate_limit: Optional[float] = None
    max_request_tokens: Optional[int] = None
    error_cooldown: Optional[int] = None  # Cooldown period in seconds after 3 consecutive failures
    # OpenRouter-style extended fields
    description: Optional[str] = None
    context_length: Optional[int] = None
    architecture: Optional[Dict] = None  # modality, input_modalities, output_modalities, tokenizer, instruct_type
    pricing: Optional[Dict] = None  # prompt, completion, input_cache_read
    top_provider: Optional[Dict] = None  # context_length, max_completion_tokens, is_moderated
    supported_parameters: Optional[List[str]] = None
    default_parameters: Optional[Dict] = None
    # Content classification flags
    nsfw: bool = False  # Model can handle NSFW content
    privacy: bool = False  # Model can handle privacy-sensitive content
    # Response caching control
    enable_response_cache: Optional[bool] = None  # Enable/disable response caching for this model (None = use provider default)


class CondensationConfig(BaseModel):
    """Configuration for context condensation"""
    provider_id: Optional[str] = None
    model: Optional[str] = None
    rotation_id: Optional[str] = None
    enabled: bool = True
    max_context: Optional[int] = None  # Maximum context size for condensation model


class ProviderConfig(BaseModel):
    id: str
    name: str
    endpoint: str
    type: str
    api_key_required: bool
    rate_limit: float = 0.0
    api_key: Optional[str] = None  # Optional API key in provider config
    models: Optional[List[ProviderModelConfig]] = None  # Optional list of models with their configs
    auth_config: Optional[Dict] = None  # Unified provider authentication configuration (for all provider types)
    kiro_config: Optional[Dict] = None  # Optional Kiro-specific configuration (credentials, region, etc.) - DEPRECATED
    kilo_config: Optional[Dict] = None  # Optional Kilo-specific configuration (credentials file path) - DEPRECATED
    claude_config: Optional[Dict] = None  # Optional Claude-specific configuration (credentials file path) - DEPRECATED
    codex_config: Optional[Dict] = None  # Optional Codex-specific configuration - DEPRECATED
    qwen_config: Optional[Dict] = None  # Optional Qwen-specific configuration - DEPRECATED
    # Default settings for models in this provider
    default_rate_limit: Optional[float] = None
    default_max_request_tokens: Optional[int] = None
    default_rate_limit_TPM: Optional[int] = None
    default_rate_limit_TPH: Optional[int] = None
    default_rate_limit_TPD: Optional[int] = None
    default_context_size: Optional[int] = None
    default_condense_context: Optional[int] = None
    default_condense_method: Optional[Union[str, List[str]]] = None
    default_error_cooldown: Optional[int] = None  # Default cooldown period in seconds after 3 consecutive failures (default: 300)
    # Provider-native caching configuration
    enable_native_caching: bool = False  # Enable provider-native caching (Anthropic cache_control, Google Context Caching, OpenAI and Kilo-compatible APIs)
    cache_ttl: Optional[int] = None  # Cache TTL in seconds for Google Context Caching API
    min_cacheable_tokens: Optional[int] = 1024  # Minimum token count for content to be cacheable (default matches OpenAI)
    prompt_cache_key: Optional[str] = None  # Optional cache key for OpenAI's load balancer routing optimization
    # Response caching control
    enable_response_cache: Optional[bool] = None  # Enable/disable response caching for this provider (None = use global default)

class RotationConfig(BaseModel):
    model_name: str
    providers: List[Dict]
    notifyerrors: bool = False
    capabilities: Optional[List[str]] = None  # Capabilities for this rotation
    # Content classification flags
    nsfw: bool = False  # Model can handle NSFW content
    privacy: bool = False  # Model can handle privacy-sensitive content
    # OpenRouter-style extended fields
    description: Optional[str] = None
    context_length: Optional[int] = None
    architecture: Optional[Dict] = None
    pricing: Optional[Dict] = None
    supported_parameters: Optional[List[str]] = None
    default_parameters: Optional[Dict] = None
    # Default settings for models in this rotation
    default_rate_limit: Optional[float] = None
    default_max_request_tokens: Optional[int] = None
    default_rate_limit_TPM: Optional[int] = None
    default_rate_limit_TPH: Optional[int] = None
    default_rate_limit_TPD: Optional[int] = None
    default_context_size: Optional[int] = None
    default_condense_context: Optional[int] = None
    default_condense_method: Optional[Union[str, List[str]]] = None
    default_error_cooldown: Optional[int] = None  # Default cooldown period in seconds after 3 consecutive failures (default: 300)
    # Response caching control
    enable_response_cache: Optional[bool] = None  # Enable/disable response caching for this rotation (None = use global default)

class AutoselectModelInfo(BaseModel):
    model_id: str
    description: str
    nsfw: bool = False  # Model can handle NSFW content
    privacy: bool = False  # Model can handle privacy-sensitive content

class AutoselectConfig(BaseModel):
    model_name: str
    description: str
    selection_model: str = "general"
    fallback: str
    available_models: List[AutoselectModelInfo]
    capabilities: Optional[List[str]] = None  # Capabilities for this autoselect configuration
    # Content classification flags
    nsfw: bool = False  # Model can handle NSFW content
    privacy: bool = False  # Model can handle privacy-sensitive content
    classify_nsfw: bool = False  # Enable NSFW classification for this autoselect
    classify_privacy: bool = False  # Enable privacy classification for this autoselect
    classify_semantic: bool = False  # Enable semantic classification for this autoselect
    # OpenRouter-style extended fields
    context_length: Optional[int] = None
    architecture: Optional[Dict] = None
    pricing: Optional[Dict] = None
    supported_parameters: Optional[List[str]] = None
    default_parameters: Optional[Dict] = None
    # Default settings for models in this autoselect
    default_rate_limit: Optional[float] = None
    default_max_request_tokens: Optional[int] = None
    default_rate_limit_TPM: Optional[int] = None
    default_rate_limit_TPH: Optional[int] = None
    default_rate_limit_TPD: Optional[int] = None
    default_context_size: Optional[int] = None
    default_condense_context: Optional[int] = None
    default_condense_method: Optional[Union[str, List[str]]] = None
    default_error_cooldown: Optional[int] = None  # Default cooldown period in seconds after 3 consecutive failures (default: 300)
    # Response caching control
    enable_response_cache: Optional[bool] = None  # Enable/disable response caching for this autoselect (None = use global default)

class ResponseCacheConfig(BaseModel):
    """Configuration for response caching with semantic deduplication"""
    enabled: bool = True
    backend: str = "memory"  # 'redis', 'sqlite', 'mysql', or 'memory'
    ttl: int = 600  # Default TTL in seconds (10 minutes)
    max_memory_cache: int = 1000  # Max items for memory cache
    # Redis configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_key_prefix: str = "aisbf:response:"
    # SQLite configuration
    sqlite_path: str = "~/.aisbf/response_cache.db"
    # MySQL configuration
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "aisbf"
    mysql_password: str = ""
    mysql_database: str = "aisbf_response_cache"


class TorConfig(BaseModel):
    """Configuration for TOR hidden service"""
    enabled: bool = False
    control_port: int = 9051
    control_host: str = "127.0.0.1"
    control_password: Optional[str] = None
    hidden_service_dir: Optional[str] = None
    hidden_service_port: int = 80
    socks_port: int = 9050
    socks_host: str = "127.0.0.1"

class BatchingConfig(BaseModel):
    """Configuration for request batching"""
    enabled: bool = False
    window_ms: int = 100  # Batching window in milliseconds
    max_batch_size: int = 8  # Maximum number of requests per batch
    provider_settings: Optional[Dict[str, Dict]] = None  # Provider-specific settings


class AdaptiveRateLimitingConfig(BaseModel):
    """Configuration for adaptive rate limiting"""
    enabled: bool = True  # Enable adaptive rate limiting
    initial_rate_limit: float = 0.0  # Initial rate limit in seconds (0 = no rate limiting)
    learning_rate: float = 0.1  # How fast to learn from 429s (0.1 = 10% adjustment)
    headroom_percent: int = 10  # Percentage to stay below learned limit (10 = 10% headroom)
    recovery_rate: float = 0.05  # Rate of recovery after successful requests (0.05 = 5% per success)
    max_rate_limit: float = 60.0  # Maximum rate limit in seconds
    min_rate_limit: float = 0.1  # Minimum rate limit in seconds
    backoff_base: float = 2.0  # Base for exponential backoff
    jitter_factor: float = 0.25  # Jitter factor for backoff (0.25 = 25%)
    history_window: int = 3600  # History window in seconds (1 hour)
    consecutive_successes_for_recovery: int = 10  # Successes needed before recovery starts

class SignupConfig(BaseModel):
    """Configuration for user signup functionality"""
    enabled: bool = False
    require_email_verification: bool = True
    verification_token_expiry_hours: int = 24
    
class PaymentGatewayConfig(BaseModel):
    """Configuration for payment gateways"""
    enabled: bool = False
    public_key: Optional[str] = None
    secret_key: Optional[str] = None
    webhook_secret: Optional[str] = None
    api_url: Optional[str] = None
    wallet_address: Optional[str] = None
    minimum_amount: Optional[float] = None
    additional_config: Optional[Dict] = None

class CurrencyConfig(BaseModel):
    """Global currency configuration"""
    code: str = "USD"
    symbol: str = "$"
    decimal_places: int = 2
    position: str = "left"

class SMTPConfig(BaseModel):
    """Configuration for SMTP email sending"""
    enabled: bool = False
    host: str = "localhost"
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    from_email: str = ""
    from_name: str = "AISBF"

class OAuth2ProviderConfig(BaseModel):
    """Configuration for an OAuth2 provider"""
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    scopes: List[str] = []

class OAuth2Config(BaseModel):
    """Configuration for OAuth2 authentication providers"""
    google: Optional[OAuth2ProviderConfig] = None
    github: Optional[OAuth2ProviderConfig] = None

class AISBFConfig(BaseModel):
    """Global AISBF configuration from aisbf.json"""
    classify_nsfw: bool = False
    classify_privacy: bool = False
    classify_semantic: bool = False
    server: Optional[Dict] = None
    auth: Optional[Dict] = None
    mcp: Optional[Dict] = None
    dashboard: Optional[Dict] = None
    internal_model: Optional[Dict] = None
    tor: Optional[Dict] = None
    database: Optional[Dict] = None
    cache: Optional[Dict] = None
    response_cache: Optional[ResponseCacheConfig] = None
    batching: Optional[BatchingConfig] = None
    adaptive_rate_limiting: Optional[AdaptiveRateLimitingConfig] = None
    signup: Optional[SignupConfig] = None
    smtp: Optional[SMTPConfig] = None
    oauth2: Optional[OAuth2Config] = None
    currency: Optional[CurrencyConfig] = None
    payment_gateways: Optional[Dict[str, PaymentGatewayConfig]] = None


class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    rotations: Dict[str, RotationConfig]
    autoselect: Dict[str, AutoselectConfig]
    condensation: Optional[CondensationConfig] = None
    error_tracking: Dict[str, Dict]
    tor: Optional[TorConfig] = None
    aisbf: Optional[AISBFConfig] = None  # Global AISBF config

class Config:
    def __init__(self):
        self._custom_config_dir = None
        # Check for custom config directory from environment variable
        custom_dir = os.environ.get('AISBF_CONFIG_DIR')
        if custom_dir:
            self._custom_config_dir = Path(custom_dir)
        
        # Track loaded file paths for summary
        self._loaded_files = {}
        
        self._ensure_config_directory()
        self._load_providers()
        self._load_rotations()
        self._load_condensation()
        self._load_tor()
        self._load_aisbf_config()
        self._load_autoselect()  # Load autoselect after aisbf config so cache is available
        self._initialize_error_tracking()
        self._log_configuration_summary()

    def reload(self):
        """Reload all configuration files from disk"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("=== Config.reload() START ===")

        # Clear existing config
        self.providers.clear()
        self.rotations.clear()
        self.autoselect.clear()
        self.error_tracking.clear()
        self._loaded_files.clear()

        # Re-load everything
        self._load_providers()
        self._load_rotations()
        self._load_condensation()
        self._load_tor()
        self._load_aisbf_config()
        self._load_autoselect()
        self._initialize_error_tracking()
        self._log_configuration_summary()

        logger.info("=== Config.reload() END ===")

    def _get_config_source_dir(self):
        """Get the directory containing default config files"""
        # If custom config directory is set, use it first
        if self._custom_config_dir and self._custom_config_dir.exists():
            if (self._custom_config_dir / 'providers.json').exists():
                return self._custom_config_dir
        
        # Try installed locations in order of preference
        # 1. User-local installation (pip install --user)
        # 2. System-wide installation (sudo pip install)
        # 3. Alternative system location
        installed_dirs = [
            Path.home() / '.local' / 'share' / 'aisbf',
            Path('/usr/local/share/aisbf'),
            Path('/usr/share/aisbf'),
        ]
        
        for installed_dir in installed_dirs:
            if installed_dir.exists() and (installed_dir / 'providers.json').exists():
                return installed_dir
        
        # Fallback to source tree config directory
        # This is for development mode
        source_dir = Path(__file__).parent.parent / 'config'
        if source_dir.exists() and (source_dir / 'providers.json').exists():
            return source_dir
        
        # Last resort: try the old location in the package directory
        package_dir = Path(__file__).parent
        if (package_dir / 'providers.json').exists():
            return package_dir
        
        raise FileNotFoundError("Could not find configuration files")

    def _ensure_config_directory(self):
        """Ensure ~/.aisbf/ directory exists and copy default config files if needed"""
        config_dir = Path.home() / '.aisbf'
        
        # Create config directory if it doesn't exist
        config_dir.mkdir(exist_ok=True)
        
        # Get the source directory for default config files
        try:
            source_dir = self._get_config_source_dir()
        except FileNotFoundError:
            print("Warning: Could not find default configuration files")
            return
        
        # Copy default config files if they don't exist
        for config_file in ['providers.json', 'rotations.json', 'autoselect.json', 'aisbf.json']:
            src = source_dir / config_file
            dst = config_dir / config_file
            
            if not dst.exists() and src.exists():
                shutil.copy2(src, dst)
                print(f"Created default config file: {dst}")
        
        # Copy markdown prompt files if they don't exist
        for prompt_file in ['condensation_conversational.md', 'condensation_semantic.md', 'autoselect.md']:
            src = source_dir / prompt_file
            dst = config_dir / prompt_file
            
            if not dst.exists() and src.exists():
                shutil.copy2(src, dst)
                print(f"Created default prompt file: {dst}")

    def _load_providers(self):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Config._load_providers START ===")
        
        providers_path = Path.home() / '.aisbf' / 'providers.json'
        logger.info(f"Looking for providers at: {providers_path}")
        
        if not providers_path.exists():
            logger.info(f"User config not found, falling back to source config")
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                providers_path = source_dir / 'providers.json'
                logger.info(f"Using source config at: {providers_path}")
            except FileNotFoundError:
                logger.error("Could not find providers.json configuration file")
                raise FileNotFoundError("Could not find providers.json configuration file")
        
        logger.info(f"Loading providers from: {providers_path}")
        try:
            with open(providers_path) as f:
                data = json.load(f)
                
                # Validate JSON structure
                if not data or 'providers' not in data:
                    logger.error(f"Invalid providers.json: missing 'providers' key")
                    raise ValueError("Invalid providers.json: missing 'providers' key")
                
                if not isinstance(data['providers'], dict):
                    logger.error(f"Invalid providers.json: 'providers' must be a dictionary")
                    raise ValueError("Invalid providers.json: 'providers' must be a dictionary")
                
                self.providers = {k: ProviderConfig(**v) for k, v in data['providers'].items()}
                self._loaded_files['providers'] = str(providers_path.absolute())
                logger.info(f"Loaded {len(self.providers)} providers: {list(self.providers.keys())}")
                for provider_id, provider_config in self.providers.items():
                    logger.info(f"  - {provider_id}: type={provider_config.type}, endpoint={provider_config.endpoint}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse providers.json: {e}")
            raise ValueError(f"Invalid JSON in providers.json: {e}")
        except Exception as e:
            logger.error(f"Failed to load providers.json: {e}")
            raise
        
        logger.info(f"=== Config._load_providers END ===")

    def _load_rotations(self):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Config._load_rotations START ===")
        
        rotations_path = Path.home() / '.aisbf' / 'rotations.json'
        logger.info(f"Looking for rotations at: {rotations_path}")
        
        if not rotations_path.exists():
            logger.info(f"User config not found, falling back to source config")
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                rotations_path = source_dir / 'rotations.json'
                logger.info(f"Using source config at: {rotations_path}")
            except FileNotFoundError:
                logger.error("Could not find rotations.json configuration file")
                raise FileNotFoundError("Could not find rotations.json configuration file")
        
        logger.info(f"Loading rotations from: {rotations_path}")
        try:
            with open(rotations_path) as f:
                data = json.load(f)
                
                # Validate JSON structure
                if not data or 'rotations' not in data:
                    logger.error(f"Invalid rotations.json: missing 'rotations' key")
                    raise ValueError("Invalid rotations.json: missing 'rotations' key")
                
                if not isinstance(data['rotations'], dict):
                    logger.error(f"Invalid rotations.json: 'rotations' must be a dictionary")
                    raise ValueError("Invalid rotations.json: 'rotations' must be a dictionary")
                
                self._loaded_files['rotations'] = str(rotations_path.absolute())
                
                # Extract global notifyerrors setting (top-level, outside rotations)
                self.global_notifyerrors = data.get('notifyerrors', False)
                logger.info(f"Global notifyerrors setting: {self.global_notifyerrors}")
                
                # Load rotations, merging global notifyerrors with rotation-specific settings
                self.rotations = {}
                for k, v in data['rotations'].items():
                    # If rotation doesn't have its own notifyerrors, use global setting
                    if 'notifyerrors' not in v:
                        v['notifyerrors'] = self.global_notifyerrors
                        logger.info(f"Rotation '{k}' using global notifyerrors: {self.global_notifyerrors}")
                    else:
                        logger.info(f"Rotation '{k}' has own notifyerrors: {v['notifyerrors']}")
                    self.rotations[k] = RotationConfig(**v)
                
                logger.info(f"Loaded {len(self.rotations)} rotations: {list(self.rotations.keys())}")
                
                # Validate that all providers referenced in rotations exist
                logger.info(f"=== VALIDATING ROTATION PROVIDERS ===")
                available_providers = list(self.providers.keys())
                logger.info(f"Available providers: {available_providers}")
                
                for rotation_id, rotation_config in self.rotations.items():
                    logger.info(f"Validating rotation: {rotation_id}")
                    for provider in rotation_config.providers:
                        provider_id = provider['provider_id']
                        if provider_id not in self.providers:
                            logger.warning(f"!!! CONFIGURATION WARNING !!!")
                            logger.warning(f"Rotation '{rotation_id}' references provider '{provider_id}' which is NOT defined in providers.json")
                            logger.warning(f"Available providers: {available_providers}")
                            logger.warning(f"This provider will be SKIPPED during rotation requests")
                            logger.warning(f"Please add the provider to providers.json or remove it from the rotation configuration")
                            logger.warning(f"!!! END WARNING !!!")
                        else:
                            logger.info(f"  ✓ Provider '{provider_id}' is available")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse rotations.json: {e}")
            raise ValueError(f"Invalid JSON in rotations.json: {e}")
        except Exception as e:
            logger.error(f"Failed to load rotations.json: {e}")
            raise
        
        logger.info(f"=== Config._load_rotations END ===")

    def _load_autoselect(self):
        """Load autoselect configuration and build model embeddings for semantic matching."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Config._load_autoselect START ===")
        
        autoselect_path = Path.home() / '.aisbf' / 'autoselect.json'
        logger.info(f"Looking for autoselect at: {autoselect_path}")
        
        if not autoselect_path.exists():
            logger.info(f"User config not found, falling back to source config")
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                autoselect_path = source_dir / 'autoselect.json'
                logger.info(f"Using source config at: {autoselect_path}")
            except FileNotFoundError:
                logger.error("Could not find autoselect.json configuration file")
                raise FileNotFoundError("Could not find autoselect.json configuration file")
        
        logger.info(f"Loading autoselect from: {autoselect_path}")
        try:
            with open(autoselect_path) as f:
                data = json.load(f)
                
                # Validate JSON structure
                if not data:
                    logger.error(f"Invalid autoselect.json: empty file")
                    raise ValueError("Invalid autoselect.json: empty file")
                
                self.autoselect = {k: AutoselectConfig(**v) for k, v in data.items()}
                self._loaded_files['autoselect'] = str(autoselect_path.absolute())
                logger.info(f"Loaded {len(self.autoselect)} autoselect configurations: {list(self.autoselect.keys())}")
                
                # Build and cache model embeddings for semantic matching
                self._build_model_embeddings()
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse autoselect.json: {e}")
            raise ValueError(f"Invalid JSON in autoselect.json: {e}")
        except Exception as e:
            logger.error(f"Failed to load autoselect.json: {e}")
            raise
            
        logger.info(f"=== Config._load_autoselect END ===")
    
    def _build_model_embeddings(self):
        """
        Build and cache vectorized versions of model descriptions for semantic matching.
        Uses the configured cache backend (Redis, file, or memory).
        """
        import logging
        logger = logging.getLogger(__name__)

        # Collect all model descriptions from all autoselect configs
        model_library = {}
        for autoselect_id, autoselect_config in self.autoselect.items():
            for model_info in autoselect_config.available_models:
                model_library[model_info.model_id] = model_info.description

        if not model_library:
            logger.info("No models to vectorize")
            self._model_embeddings = None
            self._model_embeddings_meta = []
            return

        # Get cache manager
        from .cache import get_cache_manager
        cache_config = self.aisbf.cache if self.aisbf and self.aisbf.cache else None
        cache_manager = get_cache_manager(cache_config)

        # Cache key for embeddings
        embeddings_key = "model_embeddings"

        # Check if embeddings exist in cache and are up-to-date
        rebuild_needed = True
        cached_meta = cache_manager.get(f"{embeddings_key}_meta")

        if cached_meta and cached_meta == list(model_library.keys()):
            # Try to load from numpy file cache (always file-based for large arrays)
            embeddings, _ = cache_manager.load_numpy_array(embeddings_key)
            if embeddings is not None:
                logger.info(f"Loading cached model embeddings from cache")
                self._model_embeddings = embeddings
                self._model_embeddings_meta = cached_meta
                rebuild_needed = False
                logger.info(f"Loaded {len(self._model_embeddings)} model embeddings")
            else:
                logger.warning("Cached embeddings metadata exists but array not found, rebuilding")

        if rebuild_needed:
            logger.info(f"Building model embeddings for {len(model_library)} models...")

            try:
                from sentence_transformers import SentenceTransformer
                import numpy as np

                # Use CPU-friendly model from config
                model_id = "sentence-transformers/all-MiniLM-L6-v2"

                # Check if custom model is configured in aisbf.json
                if self.aisbf and self.aisbf.internal_model:
                    custom_model = self.aisbf.internal_model.get('semantic_vectorization')
                    if custom_model:
                        model_id = custom_model

                logger.info(f"Using embedding model: {model_id}")
                embedder = SentenceTransformer(model_id)

                names = list(model_library.keys())
                descriptions = list(model_library.values())

                logger.info(f"Vectorizing {len(names)} model descriptions on CPU...")
                embeddings = embedder.encode(descriptions, show_progress_bar=True)

                # Save to numpy file cache
                cache_manager.save_numpy_array(embeddings_key, embeddings)

                # Save metadata to cache
                cache_manager.set(f"{embeddings_key}_meta", names)

                self._model_embeddings = embeddings
                self._model_embeddings_meta = names

                logger.info(f"Saved embeddings to cache")
                logger.info(f"Embedding shape: {embeddings.shape}")

            except ImportError as e:
                logger.warning(f"sentence-transformers not installed, skipping embeddings: {e}")
                self._model_embeddings = None
                self._model_embeddings_meta = []
            except Exception as e:
                logger.warning(f"Failed to build model embeddings: {e}")
                self._model_embeddings = None
                self._model_embeddings_meta = []
    
    def find_similar_models(self, query: str, top_k: int = 3) -> List[str]:
        """
        Find the most similar models to a query based on embeddings.
        
        Args:
            query: The user query/description to match against
            top_k: Number of top matches to return
            
        Returns:
            List of model_ids sorted by similarity (best match first)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if self._model_embeddings is None or self._model_embeddings_meta is None:
            logger.debug("No embeddings available, returning empty list")
            return []
        
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
            
            # Load embedder
            model_id = "sentence-transformers/all-MiniLM-L6-v2"
            if self.aisbf and self.aisbf.internal_model:
                custom_model = self.aisbf.internal_model.get('semantic_vectorization')
                if custom_model:
                    model_id = custom_model
            
            embedder = SentenceTransformer(model_id)
            
            # Encode query
            query_embedding = embedder.encode([query])
            
            # Calculate cosine similarity
            query_norm = query_embedding / np.linalg.norm(query_embedding, axis=1, keepdims=True)
            embeddings_norm = self._model_embeddings / np.linalg.norm(self._model_embeddings, axis=1, keepdims=True)
            
            # Compute similarities
            similarities = np.dot(query_norm, embeddings_norm.T)[0]
            
            # Get top_k indices
            top_indices = np.argsort(similarities)[::-1][:top_k]
            
            # Return model_ids in order of similarity
            results = [self._model_embeddings_meta[i] for i in top_indices]
            logger.debug(f"Found similar models: {results}")
            
            return results
            
        except Exception as e:
            logger.warning(f"Error finding similar models: {e}")
            return []
    
    def _load_condensation(self):
        """Load condensation configuration from providers.json"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Config._load_condensation START ===")
        
        providers_path = Path.home() / '.aisbf' / 'providers.json'
        logger.info(f"Looking for condensation config in: {providers_path}")
        
        if not providers_path.exists():
            logger.info(f"User config not found, falling back to source config")
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                providers_path = source_dir / 'providers.json'
                logger.info(f"Using source config at: {providers_path}")
            except FileNotFoundError:
                logger.warning("Could not find providers.json for condensation config")
                self.condensation = CondensationConfig()
                return
        
        logger.info(f"Loading condensation config from: {providers_path}")
        with open(providers_path) as f:
            data = json.load(f)
            condensation_data = data.get('condensation', {})
            self.condensation = CondensationConfig(**condensation_data)
            self._loaded_files['condensation'] = str(providers_path.absolute())
            logger.info(f"Loaded condensation config: provider_id={self.condensation.provider_id}, model={self.condensation.model}, enabled={self.condensation.enabled}")
            logger.info(f"=== Config._load_condensation END ===")
    
    def _load_tor(self):
        """Load TOR configuration from aisbf.json"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Config._load_tor START ===")
        
        aisbf_path = Path.home() / '.aisbf' / 'aisbf.json'
        logger.info(f"Looking for TOR config in: {aisbf_path}")
        
        if not aisbf_path.exists():
            logger.info(f"User config not found, falling back to source config")
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                aisbf_path = source_dir / 'aisbf.json'
                logger.info(f"Using source config at: {aisbf_path}")
            except FileNotFoundError:
                logger.warning("Could not find aisbf.json for TOR config")
                self.tor = TorConfig()
                return
        
        logger.info(f"Loading TOR config from: {aisbf_path}")
        with open(aisbf_path) as f:
            data = json.load(f)
            tor_data = data.get('tor', {})
            self.tor = TorConfig(**tor_data)
            self._loaded_files['tor'] = str(aisbf_path.absolute())
            logger.info(f"Loaded TOR config: enabled={self.tor.enabled}, control_port={self.tor.control_port}, hidden_service_port={self.tor.hidden_service_port}")
            logger.info(f"=== Config._load_tor END ===")
    
    def _load_aisbf_config(self):
        """Load global AISBF configuration from aisbf.json"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== Config._load_aisbf_config START ===")
        
        aisbf_path = Path.home() / '.aisbf' / 'aisbf.json'
        logger.info(f"Looking for AISBF config in: {aisbf_path}")
        
        if not aisbf_path.exists():
            logger.info(f"User config not found, falling back to source config")
            try:
                source_dir = self._get_config_source_dir()
                aisbf_path = source_dir / 'aisbf.json'
                logger.info(f"Using source config at: {aisbf_path}")
            except FileNotFoundError:
                logger.warning("Could not find aisbf.json for AISBF config")
                self.aisbf = AISBFConfig()
                return
        
        logger.info(f"Loading AISBF config from: {aisbf_path}")
        with open(aisbf_path) as f:
            data = json.load(f)
            # Parse response_cache separately if present
            response_cache_data = data.get('response_cache')
            if response_cache_data:
                data['response_cache'] = ResponseCacheConfig(**response_cache_data)
            # Parse batching separately if present
            batching_data = data.get('batching')
            if batching_data:
                data['batching'] = BatchingConfig(**batching_data)
            # Parse adaptive_rate_limiting separately if present
            adaptive_data = data.get('adaptive_rate_limiting')
            if adaptive_data:
                data['adaptive_rate_limiting'] = AdaptiveRateLimitingConfig(**adaptive_data)
            # Parse signup separately if present
            signup_data = data.get('signup')
            if signup_data:
                data['signup'] = SignupConfig(**signup_data)
            # Parse smtp separately if present
            smtp_data = data.get('smtp')
            if smtp_data:
                data['smtp'] = SMTPConfig(**smtp_data)
            # Parse currency separately if present
            currency_data = data.get('currency')
            if currency_data:
                data['currency'] = CurrencyConfig(**currency_data)
            # Parse payment gateways separately if present
            payment_gateways_data = data.get('payment_gateways')
            if payment_gateways_data:
                data['payment_gateways'] = {k: PaymentGatewayConfig(**v) for k, v in payment_gateways_data.items()}
            self.aisbf = AISBFConfig(**data)
            self._loaded_files['aisbf'] = str(aisbf_path.absolute())
            logger.info(f"Loaded AISBF config: classify_nsfw={self.aisbf.classify_nsfw}, classify_privacy={self.aisbf.classify_privacy}")
            if self.aisbf.response_cache:
                logger.info(f"Response cache config: enabled={self.aisbf.response_cache.enabled}, backend={self.aisbf.response_cache.backend}, ttl={self.aisbf.response_cache.ttl}")
            if self.aisbf.batching:
                logger.info(f"Batching config: enabled={self.aisbf.batching.enabled}, window_ms={self.aisbf.batching.window_ms}, max_batch_size={self.aisbf.batching.max_batch_size}")
            if self.aisbf.adaptive_rate_limiting:
                logger.info(f"Adaptive rate limiting: enabled={self.aisbf.adaptive_rate_limiting.enabled}, initial_rate_limit={self.aisbf.adaptive_rate_limiting.initial_rate_limit}")
            if self.aisbf.signup:
                logger.info(f"Signup config: enabled={self.aisbf.signup.enabled}, require_email_verification={self.aisbf.signup.require_email_verification}")
            if self.aisbf.smtp:
                logger.info(f"SMTP config: host={self.aisbf.smtp.host}, port={self.aisbf.smtp.port}, from_email={self.aisbf.smtp.from_email}")
            logger.info(f"=== Config._load_aisbf_config END ===")

    def _initialize_error_tracking(self):
        self.error_tracking = {}
        for provider_id in self.providers:
            self.error_tracking[provider_id] = {
                'failures': 0,
                'last_failure': None,
                'disabled_until': None
            }
    
    def _log_configuration_summary(self):
        """Log a summary of all loaded configuration files"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("=== CONFIGURATION FILES LOADED ===")
        logger.info("=" * 80)
        
        if 'providers' in self._loaded_files:
            logger.info(f"Providers:    {self._loaded_files['providers']}")
        
        if 'rotations' in self._loaded_files:
            logger.info(f"Rotations:    {self._loaded_files['rotations']}")
        
        if 'autoselect' in self._loaded_files:
            logger.info(f"Autoselect:   {self._loaded_files['autoselect']}")
        
        if 'condensation' in self._loaded_files:
            logger.info(f"Condensation: {self._loaded_files['condensation']}")
        
        logger.info("=" * 80)
        logger.info("")

    def get_provider(self, provider_id: str, warn: bool = True) -> ProviderConfig:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Config.get_provider called with provider_id: {provider_id}")
        logger.info(f"Available providers: {list(self.providers.keys())}")
        result = self.providers.get(provider_id)
        if result:
            logger.info(f"Found provider: {result}")
        else:
            if warn:
                logger.warning(f"Provider {provider_id} not found!")
        return result

    def get_rotation(self, rotation_id: str) -> RotationConfig:
        return self.rotations.get(rotation_id)

    def get_autoselect(self, autoselect_id: str) -> AutoselectConfig:
        return self.autoselect.get(autoselect_id)
    
    def get_condensation(self) -> CondensationConfig:
        return self.condensation
    
    def get_tor(self) -> TorConfig:
        return self.tor
    
    def get_aisbf_config(self) -> AISBFConfig:
        return self.aisbf

config = Config()

def get_config():
    return config
