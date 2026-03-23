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
    kiro_config: Optional[Dict] = None  # Optional Kiro-specific configuration (credentials, region, etc.)
    # Default settings for models in this provider
    default_rate_limit: Optional[float] = None
    default_max_request_tokens: Optional[int] = None
    default_rate_limit_TPM: Optional[int] = None
    default_rate_limit_TPH: Optional[int] = None
    default_rate_limit_TPD: Optional[int] = None
    default_context_size: Optional[int] = None
    default_condense_context: Optional[int] = None
    default_condense_method: Optional[Union[str, List[str]]] = None

class RotationConfig(BaseModel):
    model_name: str
    providers: List[Dict]
    notifyerrors: bool = False
    # Default settings for models in this rotation
    default_rate_limit: Optional[float] = None
    default_max_request_tokens: Optional[int] = None
    default_rate_limit_TPM: Optional[int] = None
    default_rate_limit_TPH: Optional[int] = None
    default_rate_limit_TPD: Optional[int] = None
    default_context_size: Optional[int] = None
    default_condense_context: Optional[int] = None
    default_condense_method: Optional[Union[str, List[str]]] = None

class AutoselectModelInfo(BaseModel):
    model_id: str
    description: str

class AutoselectConfig(BaseModel):
    model_name: str
    description: str
    selection_model: str = "general"
    fallback: str
    available_models: List[AutoselectModelInfo]

class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    rotations: Dict[str, RotationConfig]
    autoselect: Dict[str, AutoselectConfig]
    condensation: Optional[CondensationConfig] = None
    error_tracking: Dict[str, Dict]

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
        self._load_autoselect()
        self._load_condensation()
        self._initialize_error_tracking()
        self._log_configuration_summary()

    def _get_config_source_dir(self):
        """Get the directory containing default config files"""
        # If custom config directory is set, use it first
        if self._custom_config_dir and self._custom_config_dir.exists():
            if (self._custom_config_dir / 'providers.json').exists():
                return self._custom_config_dir
        
        # Try installed location first
        installed_dirs = [
            Path('/usr/share/aisbf'),
            Path.home() / '.local' / 'share' / 'aisbf',
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
        for config_file in ['providers.json', 'rotations.json', 'autoselect.json']:
            src = source_dir / config_file
            dst = config_dir / config_file
            
            if not dst.exists() and src.exists():
                shutil.copy2(src, dst)
                print(f"Created default config file: {dst}")

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
        with open(providers_path) as f:
            data = json.load(f)
            self.providers = {k: ProviderConfig(**v) for k, v in data['providers'].items()}
            self._loaded_files['providers'] = str(providers_path.absolute())
            logger.info(f"Loaded {len(self.providers)} providers: {list(self.providers.keys())}")
            for provider_id, provider_config in self.providers.items():
                logger.info(f"  - {provider_id}: type={provider_config.type}, endpoint={provider_config.endpoint}")
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
        with open(rotations_path) as f:
            data = json.load(f)
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
            
            logger.info(f"=== Config._load_rotations END ===")

    def _load_autoselect(self):
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
        with open(autoselect_path) as f:
            data = json.load(f)
            self.autoselect = {k: AutoselectConfig(**v) for k, v in data.items()}
            self._loaded_files['autoselect'] = str(autoselect_path.absolute())
            logger.info(f"Loaded {len(self.autoselect)} autoselect configurations: {list(self.autoselect.keys())}")
            logger.info(f"=== Config._load_autoselect END ===")
    
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

    def get_provider(self, provider_id: str) -> ProviderConfig:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Config.get_provider called with provider_id: {provider_id}")
        logger.info(f"Available providers: {list(self.providers.keys())}")
        result = self.providers.get(provider_id)
        if result:
            logger.info(f"Found provider: {result}")
        else:
            logger.warning(f"Provider {provider_id} not found!")
        return result

    def get_rotation(self, rotation_id: str) -> RotationConfig:
        return self.rotations.get(rotation_id)

    def get_autoselect(self, autoselect_id: str) -> AutoselectConfig:
        return self.autoselect.get(autoselect_id)
    
    def get_condensation(self) -> CondensationConfig:
        return self.condensation

config = Config()
