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
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import json
import shutil
from pathlib import Path

class ProviderConfig(BaseModel):
    id: str
    name: str
    endpoint: str
    type: str
    api_key_required: bool

class RotationConfig(BaseModel):
    providers: List[Dict]

class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    rotations: Dict[str, RotationConfig]
    error_tracking: Dict[str, Dict]

class Config:
    def __init__(self):
        self._ensure_config_directory()
        self._load_providers()
        self._load_rotations()
        self._initialize_error_tracking()

    def _get_config_source_dir(self):
        """Get the directory containing default config files"""
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
        source_dir = Path(__file__).parent.parent.parent / 'config'
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
        for config_file in ['providers.json', 'rotations.json']:
            src = source_dir / config_file
            dst = config_dir / config_file
            
            if not dst.exists() and src.exists():
                shutil.copy2(src, dst)
                print(f"Created default config file: {dst}")

    def _load_providers(self):
        providers_path = Path.home() / '.aisbf' / 'providers.json'
        if not providers_path.exists():
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                providers_path = source_dir / 'providers.json'
            except FileNotFoundError:
                raise FileNotFoundError("Could not find providers.json configuration file")
        
        with open(providers_path) as f:
            data = json.load(f)
            self.providers = {k: ProviderConfig(**v) for k, v in data['providers'].items()}

    def _load_rotations(self):
        rotations_path = Path.home() / '.aisbf' / 'rotations.json'
        if not rotations_path.exists():
            # Fallback to source config if user config doesn't exist
            try:
                source_dir = self._get_config_source_dir()
                rotations_path = source_dir / 'rotations.json'
            except FileNotFoundError:
                raise FileNotFoundError("Could not find rotations.json configuration file")
        
        with open(rotations_path) as f:
            data = json.load(f)
            self.rotations = {k: RotationConfig(**v) for k, v in data['rotations'].items()}

    def _initialize_error_tracking(self):
        self.error_tracking = {}
        for provider_id in self.providers:
            self.error_tracking[provider_id] = {
                'failures': 0,
                'last_failure': None,
                'disabled_until': None
            }

    def get_provider(self, provider_id: str) -> ProviderConfig:
        return self.providers.get(provider_id)

    def get_rotation(self, rotation_id: str) -> RotationConfig:
        return self.rotations.get(rotation_id)

config = Config()
