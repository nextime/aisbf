"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Main application for AISBF.

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

Main application for AISBF.
"""
from fastapi import FastAPI, HTTPException, Request, status, Form
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates
from aisbf.models import ChatCompletionRequest, ChatCompletionResponse
from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
from aisbf.mcp import mcp_server, MCPAuthLevel, load_mcp_config
from aisbf.database import initialize_database
from aisbf.tor import setup_tor_hidden_service, TorHiddenService
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers
from itsdangerous import URLSafeTimedSerializer
import time
import logging
import sys
import os
import argparse
import secrets
import hashlib
import asyncio
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import json
import markdown
from urllib.parse import urljoin

# Global variable to store custom config directory
_custom_config_dir = None

# Global variable to store original command line arguments for restart
_original_argv = None

def set_config_dir(config_dir: str):
    """Set custom config directory before importing config"""
    global _custom_config_dir
    _custom_config_dir = config_dir
    os.environ['AISBF_CONFIG_DIR'] = config_dir

def get_config_dir():
    """Get custom config directory if set"""
    return _custom_config_dir or os.environ.get('AISBF_CONFIG_DIR')

def generate_self_signed_cert(cert_file: Path, key_file: Path):
    """Generate self-signed SSL certificate"""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from datetime import datetime, timedelta
        
        logger = logging.getLogger(__name__)
        logger.info("Generating self-signed SSL certificate...")
        
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Generate certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "State"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "City"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AISBF"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        # Write private key
        key_file.parent.mkdir(parents=True, exist_ok=True)
        with open(key_file, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        # Write certificate
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        logger.info(f"Generated self-signed certificate: {cert_file}")
        logger.info(f"Generated private key: {key_file}")
        
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.error("cryptography library not installed. Install with: pip install cryptography")
        raise

def load_server_config(custom_config_dir=None):
    """Load server configuration from aisbf.json"""
    # If custom config directory is provided, try it first
    if custom_config_dir:
        config_path = Path(custom_config_dir) / 'aisbf.json'
        if config_path.exists():
            pass  # Use this path
        else:
            # Fall through to default locations
            config_path = None
    else:
        config_path = None
    
    # Try user config first if not found in custom dir
    if not config_path or not config_path.exists():
        config_path = Path.home() / '.aisbf' / 'aisbf.json'
    
    if not config_path.exists():
        # Try installed locations
        installed_dirs = [
            Path('/usr/share/aisbf'),
            Path.home() / '.local' / 'share' / 'aisbf',
        ]
        
        for installed_dir in installed_dirs:
            test_path = installed_dir / 'aisbf.json'
            if test_path.exists():
                config_path = test_path
                break
        else:
            # Fallback to source tree config directory
            source_dir = Path(__file__).parent / 'config'
            test_path = source_dir / 'aisbf.json'
            if test_path.exists():
                config_path = test_path
    
    # Load config or use defaults
    if config_path.exists():
        try:
            with open(config_path) as f:
                config_data = json.load(f)
                server_config = config_data.get('server', {})
                auth_config = config_data.get('auth', {})
                
                protocol = server_config.get('protocol', 'http')
                ssl_certfile = server_config.get('ssl_certfile')
                ssl_keyfile = server_config.get('ssl_keyfile')
                
                # Handle HTTPS with auto-generated certificates
                if protocol == 'https':
                    if not ssl_certfile or not ssl_keyfile:
                        # Auto-generate paths
                        ssl_dir = Path.home() / '.aisbf' / 'ssl'
                        ssl_certfile = str(ssl_dir / 'cert.pem')
                        ssl_keyfile = str(ssl_dir / 'key.pem')
                    
                    cert_path = Path(ssl_certfile).expanduser()
                    key_path = Path(ssl_keyfile).expanduser()
                    
                    # Generate if they don't exist
                    if not cert_path.exists() or not key_path.exists():
                        generate_self_signed_cert(cert_path, key_path)
                
                return {
                    'host': server_config.get('host', '0.0.0.0'),
                    'port': server_config.get('port', 17765),
                    'protocol': protocol,
                    'ssl_certfile': ssl_certfile if protocol == 'https' else None,
                    'ssl_keyfile': ssl_keyfile if protocol == 'https' else None,
                    'auth_enabled': auth_config.get('enabled', False),
                    'auth_tokens': auth_config.get('tokens', [])
                }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Error loading aisbf.json: {e}, using defaults")
    
    # Return defaults
    return {
        'host': '0.0.0.0',
        'port': 17765,
        'protocol': 'http',
        'ssl_certfile': None,
        'ssl_keyfile': None,
        'auth_enabled': False,
        'auth_tokens': []
    }

class BrokenPipeFilter(logging.Filter):
    """Filter to suppress BrokenPipeError logging errors"""
    def filter(self, record):
        # Filter out BrokenPipeError and related logging errors
        if record.getMessage().startswith('--- Logging error ---'):
            return False
        if 'BrokenPipeError' in record.getMessage():
            return False
        return True

class SafeStderr:
    """Safe stderr wrapper that handles BrokenPipeError gracefully"""
    def __init__(self, original_stderr, log_file_path):
        self.original_stderr = original_stderr
        self.log_file = None
        try:
            self.log_file = open(log_file_path, 'a')
        except Exception:
            pass
    
    def write(self, data):
        # Filter out BrokenPipeError and related logging errors
        if '--- Logging error ---' in data or 'BrokenPipeError' in data:
            return
        if self.log_file:
            try:
                self.log_file.write(data)
                self.log_file.flush()
            except (BrokenPipeError, OSError):
                pass
        else:
            try:
                self.original_stderr.write(data)
            except (BrokenPipeError, OSError):
                pass
    
    def flush(self):
        if self.log_file:
            try:
                self.log_file.flush()
            except (BrokenPipeError, OSError):
                pass
        else:
            try:
                self.original_stderr.flush()
            except (BrokenPipeError, OSError):
                pass

def setup_logging():
    """Setup logging with rotating file handlers"""
    # Determine log directory based on user
    if os.geteuid() == 0:
        # Running as root - use /var/log/aisbf
        log_dir = Path('/var/log/aisbf')
    else:
        # Running as user - use ~/.local/var/log/aisbf
        log_dir = Path.home() / '.local' / 'var' / 'log' / 'aisbf'
    
    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if debug mode is enabled
    AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')
    
    # Setup rotating file handler for general logs
    log_file = log_dir / 'aisbf.log'
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=50*1024*1024,  # 50 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Setup rotating file handler for error logs
    error_log_file = log_dir / 'aisbf_error.log'
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=50*1024*1024,  # 50 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    
    # Setup console handler - use DEBUG level if AISBF_DEBUG is enabled
    console_handler = logging.StreamHandler(sys.stdout)
    if AISBF_DEBUG:
        console_handler.setLevel(logging.DEBUG)
        print("=== AISBF DEBUG MODE ENABLED ===")
        print("All debug messages will be shown in console")
        print("Raw responses from providers will be logged")
        print("=== END AISBF DEBUG MODE ===")
    else:
        console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    
    # Add BrokenPipeError filter to all handlers
    broken_pipe_filter = BrokenPipeFilter()
    file_handler.addFilter(broken_pipe_filter)
    error_handler.addFilter(broken_pipe_filter)
    console_handler.addFilter(broken_pipe_filter)
    
    # Redirect stderr to error log with error handling and BrokenPipeError filtering
    try:
        sys.stderr = SafeStderr(sys.stderr, log_dir / 'aisbf_stderr.log')
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not redirect stderr: {e}")
    
    return logging.getLogger(__name__)

# Configure logging
logger = setup_logging()

class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle proxy headers and make the application proxy-aware.
    
    Supports standard proxy headers:
    - X-Forwarded-Proto: Original protocol (http/https)
    - X-Forwarded-Host: Original host
    - X-Forwarded-Port: Original port
    - X-Forwarded-Prefix or X-Script-Name: URL prefix/subpath
    - X-Forwarded-For: Client IP address
    """
    
    async def dispatch(self, request: Request, call_next):
        # Get proxy headers
        forwarded_proto = request.headers.get("X-Forwarded-Proto")
        forwarded_host = request.headers.get("X-Forwarded-Host")
        forwarded_port = request.headers.get("X-Forwarded-Port")
        forwarded_prefix = request.headers.get("X-Forwarded-Prefix") or request.headers.get("X-Script-Name")
        forwarded_for = request.headers.get("X-Forwarded-For")
        
        # Update request scope with proxy information
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto
        
        if forwarded_host:
            # Handle host:port format
            if ":" in forwarded_host and not forwarded_port:
                host_parts = forwarded_host.split(":", 1)
                request.scope["server"] = (host_parts[0], int(host_parts[1]))
            else:
                port = int(forwarded_port) if forwarded_port else (443 if forwarded_proto == "https" else 80)
                request.scope["server"] = (forwarded_host, port)
        elif forwarded_port:
            # Only port was forwarded, keep existing host
            current_host = request.scope.get("server", ("localhost", 80))[0]
            request.scope["server"] = (current_host, int(forwarded_port))
        
        # Handle URL prefix/subpath
        if forwarded_prefix:
            # Remove trailing slash from prefix
            forwarded_prefix = forwarded_prefix.rstrip("/")
            request.scope["root_path"] = forwarded_prefix
            
            # Update path to remove prefix if present
            original_path = request.scope.get("path", "")
            if original_path.startswith(forwarded_prefix):
                request.scope["path"] = original_path[len(forwarded_prefix):] or "/"
        
        # Store client IP from X-Forwarded-For
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one (original client)
            client_ip = forwarded_for.split(",")[0].strip()
            request.scope["client"] = (client_ip, request.scope.get("client", ("", 0))[1])
        
        response = await call_next(request)
        return response

def get_base_url(request: Request) -> str:
    """
    Get the base URL for the application, respecting proxy headers.
    
    Returns the full base URL including scheme, host, port, and prefix.
    Example: https://example.com:8443/aisbf
    """
    scheme = request.scope.get("scheme", "http")
    server = request.scope.get("server", ("localhost", 80))
    host = server[0]
    port = server[1]
    root_path = request.scope.get("root_path", "")
    
    # Don't include port in URL if it's the default for the scheme
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        base_url = f"{scheme}://{host}{root_path}"
    else:
        base_url = f"{scheme}://{host}:{port}{root_path}"
    
    return base_url

def url_for(request: Request, path: str) -> str:
    """
    Generate a proxy-aware URL for the given path.
    
    Args:
        request: The current request object
        path: The path to generate URL for (should start with /)
    
    Returns:
        Full URL respecting proxy configuration
    """
    base_url = get_base_url(request)
    
    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path
    
    return f"{base_url}{path}"

# Note: config will be imported after parsing CLI args if --config is provided
# For now, we'll delay the import and initialization
app = FastAPI(title="AI Proxy Server")

# Add proxy headers middleware (must be added before other middleware)
app.add_middleware(ProxyHeadersMiddleware)

# Initialize Jinja2 templates with custom globals for proxy-aware URLs
templates = Jinja2Templates(directory="templates")

# Add custom template globals for proxy-aware URL generation
def setup_template_globals():
    """Setup Jinja2 template globals for proxy-aware URLs"""
    templates.env.globals['url_for'] = url_for
    templates.env.globals['get_base_url'] = get_base_url

# Call setup after templates are initialized
setup_template_globals()

# Add session middleware at module level with a temporary secret key
# This is needed for uvicorn import (when main() doesn't run)
_default_session_secret = secrets.token_urlsafe(32)
app.add_middleware(SessionMiddleware, secret_key=_default_session_secret)

# These will be initialized in startup event or main() after config is loaded
request_handler = None
rotation_handler = None
autoselect_handler = None
server_config = None
config = None
_initialized = False
tor_service = None

# Model cache for dynamically fetched provider models
_model_cache = {}
_model_cache_timestamps = {}
_cache_refresh_interval = 4 * 3600  # 4 hours in seconds
_cache_refresh_task = None

def initialize_app(custom_config_dir=None):
    """Initialize app globals. Called by startup event or main()."""
    global config, request_handler, rotation_handler, autoselect_handler, server_config, _initialized
    
    if _initialized:
        return
    
    # Set custom config directory if provided
    if custom_config_dir:
        set_config_dir(custom_config_dir)
        logger.info(f"Using custom config directory: {custom_config_dir}")
    
    # Import config
    from aisbf.config import config as cfg
    from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
    
    config = cfg
    request_handler = RequestHandler()
    rotation_handler = RotationHandler()
    autoselect_handler = AutoselectHandler()
    
    # Load server configuration
    server_config = load_server_config(custom_config_dir)
    
    # Load dashboard config
    aisbf_config_path = Path.home() / '.aisbf' / 'aisbf.json'
    if not aisbf_config_path.exists():
        if custom_config_dir:
            aisbf_config_path = Path(custom_config_dir) / 'aisbf.json'
        else:
            # Try installed location first
            installed_path = Path(__file__).parent / 'aisbf.json'
            if installed_path.exists():
                aisbf_config_path = installed_path
            else:
                # Fall back to config subdirectory
                aisbf_config_path = Path(__file__).parent / 'config' / 'aisbf.json'
    
    if aisbf_config_path.exists():
        with open(aisbf_config_path) as f:
            aisbf_config = json.load(f)
            server_config['dashboard_config'] = aisbf_config.get('dashboard', {})
    else:
        # Default with hashed password for 'admin'
        server_config['dashboard_config'] = {
            'username': 'admin', 
            'password': '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'
        }
    
    _initialized = True
    logger.info("App initialization complete")

async def fetch_provider_models(provider_id: str) -> list:
    """Fetch models from provider API and cache them"""
    global _model_cache, _model_cache_timestamps
    
    try:
        logger.debug(f"Fetching models from provider: {provider_id}")
        # Create a dummy request object for the handler
        from starlette.requests import Request
        from starlette.datastructures import Headers
        
        scope = {
            "type": "http",
            "method": "GET",
            "headers": [],
            "query_string": b"",
            "path": f"/api/{provider_id}/models",
        }
        dummy_request = Request(scope)
        
        # Fetch models from provider API
        models = await request_handler.handle_model_list(dummy_request, provider_id)
        
        # Cache the results
        _model_cache[provider_id] = models
        _model_cache_timestamps[provider_id] = time.time()
        
        logger.info(f"Cached {len(models)} models from provider: {provider_id}")
        return models
    except Exception as e:
        logger.warning(f"Failed to fetch models from provider {provider_id}: {e}")
        return []

async def refresh_model_cache():
    """Background task to refresh model cache periodically"""
    global _model_cache, _model_cache_timestamps
    
    while True:
        try:
            await asyncio.sleep(_cache_refresh_interval)
            logger.info("Starting periodic model cache refresh...")
            
            # Refresh cache for all providers without local model config
            for provider_id, provider_config in config.providers.items():
                if not (hasattr(provider_config, 'models') and provider_config.models):
                    await fetch_provider_models(provider_id)
            
            logger.info("Model cache refresh complete")
        except Exception as e:
            logger.error(f"Error in model cache refresh task: {e}")

def validate_kiro_credentials(provider_id: str, provider_config) -> bool:
    """
    Validate that kiro/kiro-cli credentials are available and accessible.
    
    Args:
        provider_id: Provider identifier (e.g., 'kiro', 'kiro-cli')
        provider_config: Provider configuration object
    
    Returns:
        True if credentials are valid and accessible, False otherwise
    """
    # Only validate kiro-type providers
    if not hasattr(provider_config, 'type') or provider_config.type != 'kiro':
        return True  # Not a kiro provider, no validation needed
    
    # Check if kiro_config exists
    if not hasattr(provider_config, 'kiro_config'):
        logger.debug(f"Provider {provider_id}: No kiro_config found")
        return False
    
    kiro_config = provider_config.kiro_config
    
    # Handle both dict and object access patterns
    def get_config_value(config, key):
        """Get value from config whether it's a dict or object"""
        if isinstance(config, dict):
            return config.get(key)
        return getattr(config, key, None)
    
    # Check for credentials file (kiro IDE)
    creds_file_path = get_config_value(kiro_config, 'creds_file')
    if creds_file_path:
        creds_file = Path(creds_file_path).expanduser()
        if not creds_file.exists():
            logger.debug(f"Provider {provider_id}: Credentials file not found: {creds_file}")
            return False
        
        # Try to load and validate the credentials file
        try:
            with open(creds_file, 'r') as f:
                data = json.load(f)
            
            # Check for required fields
            if not data.get('refreshToken') and not data.get('accessToken'):
                logger.debug(f"Provider {provider_id}: No valid tokens in credentials file")
                return False
            
            logger.debug(f"Provider {provider_id}: Valid credentials file found")
            return True
        except Exception as e:
            logger.debug(f"Provider {provider_id}: Error reading credentials file: {e}")
            return False
    
    # Check for SQLite database (kiro-cli)
    sqlite_db_path = get_config_value(kiro_config, 'sqlite_db')
    if sqlite_db_path:
        sqlite_db = Path(sqlite_db_path).expanduser()
        if not sqlite_db.exists():
            logger.debug(f"Provider {provider_id}: SQLite database not found: {sqlite_db}")
            return False
        
        # Try to check if the database has valid tokens
        try:
            import sqlite3
            conn = sqlite3.connect(str(sqlite_db))
            cursor = conn.cursor()
            
            # Check for token keys
            token_keys = [
                "kirocli:social:token",
                "kirocli:odic:token",
                "codewhisperer:odic:token"
            ]
            
            found_token = False
            for key in token_keys:
                cursor.execute("SELECT value FROM auth_kv WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    try:
                        token_data = json.loads(row[0])
                        if token_data.get('access_token') or token_data.get('refresh_token'):
                            found_token = True
                            break
                    except:
                        pass
            
            conn.close()
            
            if not found_token:
                logger.debug(f"Provider {provider_id}: No valid tokens in SQLite database")
                return False
            
            logger.debug(f"Provider {provider_id}: Valid SQLite credentials found")
            return True
        except Exception as e:
            logger.debug(f"Provider {provider_id}: Error reading SQLite database: {e}")
            return False
    
    # No valid credential source found
    logger.debug(f"Provider {provider_id}: No valid credential source configured")
    return False

async def get_provider_models(provider_id: str, provider_config) -> list:
    """Get models for a provider from local config or cache"""
    global _model_cache, _model_cache_timestamps
    
    # Check if provider requires API key and if it's configured
    api_key_required = getattr(provider_config, 'api_key_required', False)
    api_key = getattr(provider_config, 'api_key', None)
    
    # If API key is required but not configured or is placeholder, skip this provider
    if api_key_required:
        if not api_key or api_key.startswith('YOUR_'):
            logger.debug(f"Skipping provider {provider_id}: API key required but not configured")
            return []
    
    # Validate kiro/kiro-cli credentials
    if not validate_kiro_credentials(provider_id, provider_config):
        logger.debug(f"Skipping provider {provider_id}: Kiro credentials not available or invalid")
        return []
    
    current_time = int(time.time())
    
    # If provider has local model config, use it
    if hasattr(provider_config, 'models') and provider_config.models:
        models = []
        for model in provider_config.models:
            model_id = f"{provider_id}/{model.name}"
            models.append({
                'id': model_id,
                'object': 'model',
                'created': current_time,
                'owned_by': provider_config.name,
                'provider': provider_id,
                'type': 'provider',
                'model_name': model.name,
                'context_size': getattr(model, 'context_size', None),
                'capabilities': getattr(model, 'capabilities', []),
                'description': getattr(model, 'description', None),
                'architecture': getattr(model, 'architecture', None),
                'pricing': getattr(model, 'pricing', None),
                'top_provider': getattr(model, 'top_provider', None),
                'supported_parameters': getattr(model, 'supported_parameters', None),
                'default_parameters': getattr(model, 'default_parameters', None),
                'source': 'local_config'
            })
        return models
    
    # Check if we have cached models
    if provider_id in _model_cache:
        cache_age = time.time() - _model_cache_timestamps.get(provider_id, 0)
        if cache_age < _cache_refresh_interval:
            # Cache is still fresh, use it
            cached_models = _model_cache[provider_id]
            if cached_models:  # Only return if we have actual models
                # Add provider prefix to model IDs and ensure all required fields
                models = []
                for model in cached_models:
                    model_copy = model.copy()
                    model_copy['id'] = f"{provider_id}/{model.get('id', model.get('name', ''))}"
                    # Ensure OpenAI-compatible required fields are present
                    if 'object' not in model_copy:
                        model_copy['object'] = 'model'
                    if 'created' not in model_copy:
                        model_copy['created'] = current_time
                    if 'owned_by' not in model_copy:
                        model_copy['owned_by'] = provider_config.name
                    model_copy['provider'] = provider_id
                    model_copy['type'] = 'provider'
                    model_copy['source'] = 'api_cache'
                    models.append(model_copy)
                return models
    
    # No local config and no cache, try to fetch from API (only if API key is valid or not required)
    if not api_key_required or (api_key and not api_key.startswith('YOUR_')):
        try:
            fetched_models = await fetch_provider_models(provider_id)
            if fetched_models:
                # Add provider prefix to model IDs and ensure all required fields
                models = []
                for model in fetched_models:
                    model_copy = model.copy()
                    model_copy['id'] = f"{provider_id}/{model.get('id', model.get('name', ''))}"
                    # Ensure OpenAI-compatible required fields are present
                    if 'object' not in model_copy:
                        model_copy['object'] = 'model'
                    if 'created' not in model_copy:
                        model_copy['created'] = current_time
                    if 'owned_by' not in model_copy:
                        model_copy['owned_by'] = provider_config.name
                    model_copy['provider'] = provider_id
                    model_copy['type'] = 'provider'
                    model_copy['source'] = 'api_cache'
                    models.append(model_copy)
                return models
        except Exception as e:
            logger.debug(f"Failed to fetch models for provider {provider_id}: {e}")
    
    # No models available - return empty list (don't show generic fallback)
    return []

@app.on_event("startup")
async def startup_event():
    """Initialize app on startup (for uvicorn import case)."""
    global config, server_config, _cache_refresh_task, tor_service
    if not _initialized:
        # Use environment variable for config dir if set
        custom_config_dir = get_config_dir()
        initialize_app(custom_config_dir)
        
        # Initialize database
        try:
            initialize_database()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            # Continue startup even if database fails
    
    # Log configuration files loaded
    if config and hasattr(config, '_loaded_files'):
        logger.info("")
        logger.info("=" * 80)
        logger.info("=== CONFIGURATION FILES LOADED ===")
        logger.info("=" * 80)
        
        if 'providers' in config._loaded_files:
            logger.info(f"Providers:    {config._loaded_files['providers']}")
        
        if 'rotations' in config._loaded_files:
            logger.info(f"Rotations:    {config._loaded_files['rotations']}")
        
        if 'autoselect' in config._loaded_files:
            logger.info(f"Autoselect:   {config._loaded_files['autoselect']}")
        
        if 'condensation' in config._loaded_files:
            logger.info(f"Condensation: {config._loaded_files['condensation']}")
        
        if 'tor' in config._loaded_files:
            logger.info(f"TOR:          {config._loaded_files['tor']}")
        
        logger.info("=" * 80)
        logger.info("")
    
    # Setup TOR hidden service if enabled
    if config and hasattr(config, 'tor') and config.tor:
        tor_config = config.tor
        if tor_config.enabled:
            local_port = server_config.get('port', 17765) if server_config else 17765
            tor_service = setup_tor_hidden_service(tor_config, local_port)
            if tor_service:
                logger.info("TOR hidden service successfully initialized")
            else:
                logger.warning("TOR hidden service initialization failed")
    
    # Start background task for model cache refresh
    if _cache_refresh_task is None:
        _cache_refresh_task = asyncio.create_task(refresh_model_cache())
        logger.info(f"Started model cache refresh task (interval: {_cache_refresh_interval/3600} hours)")
    
    # In debug mode, validate provider configurations
    AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')
    if AISBF_DEBUG and config:
        logger.info("")
        logger.info("=" * 80)
        logger.info("=== PROVIDER CONFIGURATION VALIDATION (DEBUG MODE) ===")
        logger.info("=" * 80)
        
        for provider_id, provider_config in config.providers.items():
            logger.info(f"")
            logger.info(f"Provider: {provider_id}")
            logger.info(f"  Type: {provider_config.type}")
            logger.info(f"  Endpoint: {provider_config.endpoint}")
            logger.info(f"  API Key Required: {provider_config.api_key_required}")
            
            # Check if API key is configured
            if provider_config.api_key_required:
                if provider_config.api_key:
                    logger.info(f"  API Key: Configured ✓")
                    logger.info(f"  Status: Ready to use")
                else:
                    logger.warning(f"  API Key: NOT CONFIGURED ✗")
                    logger.warning(f"  Status: WILL BE SKIPPED - API key required but not provided")
                    logger.warning(f"  Action: Add api_key to provider configuration in providers.json")
            else:
                logger.info(f"  API Key: Not required")
                logger.info(f"  Status: Ready to use")
            
            # Show model count if available
            if provider_config.models:
                logger.info(f"  Models Configured: {len(provider_config.models)}")
                for model in provider_config.models[:3]:  # Show first 3 models
                    logger.info(f"    - {model.name}")
                if len(provider_config.models) > 3:
                    logger.info(f"    ... and {len(provider_config.models) - 3} more")
            else:
                logger.info(f"  Models Configured: None (will use provider's default models)")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("")
    
    logger.info(f"=== AISBF Server Started ===")
    logger.info(f"Available providers: {list(config.providers.keys()) if config else []}")
    logger.info(f"Available rotations: {list(config.rotations.keys()) if config else []}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys()) if config else []}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global tor_service
    
    # Cleanup TOR hidden service
    if tor_service:
        logger.info("Shutting down TOR hidden service...")
        tor_service.disconnect()
        logger.info("TOR hidden service shutdown complete")

# Authentication middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Check API token authentication if enabled"""
    if server_config and server_config.get('auth_enabled', False):
        # Skip auth for root endpoint and dashboard routes
        if request.url.path == "/" or request.url.path.startswith("/dashboard"):
            response = await call_next(request)
            return response
        
        # Skip auth for public models endpoints (GET only)
        if request.method == "GET" and request.url.path in ["/api/models", "/api/v1/models"]:
            response = await call_next(request)
            return response
        
        # Check for Authorization header
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header. Use: Authorization: Bearer <token>"}
            )
        
        token = auth_header.replace('Bearer ', '')
        allowed_tokens = server_config.get('auth_tokens', [])
        
        if token not in allowed_tokens:
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid authentication token"}
            )
    
    response = await call_next(request)
    return response

# Exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors and log details"""
    print(f"\n=== VALIDATION ERROR (422) ===")
    print(f"Request path: {request.url.path}")
    print(f"Request method: {request.method}")
    print(f"Request headers: {dict(request.headers)}")
    
    # Try to get raw body
    try:
        raw_body = await request.body()
        print(f"Raw request body: {raw_body.decode('utf-8')}")
    except Exception as e:
        print(f"Error reading raw body: {str(e)}")
    
    print(f"Validation error details: {exc.errors()}")
    print(f"=== END VALIDATION ERROR ===\n")
    
    logger.error(f"=== VALIDATION ERROR (422) ===")
    logger.error(f"Request path: {request.url.path}")
    logger.error(f"Request method: {request.method}")
    logger.error(f"Request headers: {dict(request.headers)}")
    
    # Try to get raw body
    try:
        raw_body = await request.body()
        logger.error(f"Raw request body: {raw_body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"Error reading raw body: {str(e)}")
    
    logger.error(f"Validation error details: {exc.errors()}")
    logger.error(f"=== END VALIDATION ERROR ===")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": exc.body}
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard routes
@app.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page(request: Request):
    """Show dashboard login page"""
    return templates.TemplateResponse("dashboard/login.html", {"request": request})

@app.post("/dashboard/login")
async def dashboard_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle dashboard login"""
    dashboard_config = server_config.get('dashboard_config', {}) if server_config else {}
    stored_username = dashboard_config.get('username', 'admin')
    stored_password_hash = dashboard_config.get('password', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918')
    
    # Hash the submitted password
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    # Compare username and hashed password
    if username == stored_username and password_hash == stored_password_hash:
        request.session['logged_in'] = True
        request.session['username'] = username
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)
    return templates.TemplateResponse("dashboard/login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/dashboard/logout")
async def dashboard_logout(request: Request):
    """Handle dashboard logout"""
    request.session.clear()
    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

def require_dashboard_auth(request: Request):
    """Check if user is logged in to dashboard"""
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    return None

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    """Dashboard overview page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    if request.session.get('role') == 'admin':
        # Admin dashboard
        return templates.TemplateResponse("dashboard/index.html", {
            "request": request,
            "session": request.session,
            "providers_count": len(config.providers) if config else 0,
            "rotations_count": len(config.rotations) if config else 0,
            "autoselect_count": len(config.autoselect) if config else 0,
            "server_config": server_config or {}
        })
    else:
        # User dashboard - show user stats
        return templates.TemplateResponse("dashboard/index.html", {
            "request": request,
            "session": request.session,
            "user_message": "User dashboard - usage statistics and configuration management coming soon",
            "providers_count": 0,
            "rotations_count": 0,
            "autoselect_count": 0,
            "server_config": {}
        })

@app.get("/dashboard/providers", response_class=HTMLResponse)
async def dashboard_providers(request: Request):
    """Edit providers configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Load providers.json
    config_path = Path.home() / '.aisbf' / 'providers.json'
    if not config_path.exists():
        config_path = Path(__file__).parent / 'config' / 'providers.json'
    
    with open(config_path) as f:
        full_config = json.load(f)
    
    # Extract just the providers object (handle both nested and flat structures)
    if 'providers' in full_config and isinstance(full_config['providers'], dict):
        providers_data = full_config['providers']
    else:
        # Fallback for flat structure (backward compatibility)
        providers_data = {k: v for k, v in full_config.items() if k != 'condensation'}
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse("dashboard/providers.html", {
        "request": request,
        "session": request.session,
        "providers_json": json.dumps(providers_data),
        "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
    })

@app.post("/dashboard/providers")
async def dashboard_providers_save(request: Request, config: str = Form(...)):
    """Save providers configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Validate JSON
        providers_data = json.loads(config)
        
        # Apply defaults: if condense_method is set but condense_context is not, default to 80
        for provider_key, provider in providers_data.items():
            if 'models' in provider and isinstance(provider['models'], list):
                for model in provider['models']:
                    if 'condense_method' in model and model.get('condense_method'):
                        if 'condense_context' not in model or model.get('condense_context') is None:
                            model['condense_context'] = 80
        
        # Load existing config to preserve structure
        config_path = Path.home() / '.aisbf' / 'providers.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'providers.json'
        
        # Read existing config to preserve condensation settings
        with open(config_path) as f:
            full_config = json.load(f)
        
        # Update providers section while preserving other keys
        full_config['providers'] = providers_data
        
        # Save to file with full structure
        save_path = Path.home() / '.aisbf' / 'providers.json'
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(full_config, f, indent=2)
        
        return templates.TemplateResponse("dashboard/providers.html", {
            "request": request,
            "session": request.session,
            "providers_json": json.dumps(providers_data),
            "success": "Configuration saved successfully! Restart server for changes to take effect."
        })
    except json.JSONDecodeError as e:
        # Reload current config on error
        config_path = Path.home() / '.aisbf' / 'providers.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'providers.json'
        with open(config_path) as f:
            full_config = json.load(f)
        
        # Extract providers
        if 'providers' in full_config and isinstance(full_config['providers'], dict):
            providers_data = full_config['providers']
        else:
            providers_data = {k: v for k, v in full_config.items() if k != 'condensation'}
        
        return templates.TemplateResponse("dashboard/providers.html", {
            "request": request,
            "session": request.session,
            "providers_json": json.dumps(providers_data),
            "error": f"Invalid JSON: {str(e)}"
        })

@app.get("/dashboard/rotations", response_class=HTMLResponse)
async def dashboard_rotations(request: Request):
    """Edit rotations configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    config_path = Path.home() / '.aisbf' / 'rotations.json'
    if not config_path.exists():
        config_path = Path(__file__).parent / 'config' / 'rotations.json'
    
    with open(config_path) as f:
        rotations_data = json.load(f)
    
    # Get available providers
    available_providers = list(config.providers.keys()) if config else []
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse("dashboard/rotations.html", {
        "request": request,
        "session": request.session,
        "rotations_json": json.dumps(rotations_data),
        "available_providers": json.dumps(available_providers),
        "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
    })

@app.post("/dashboard/rotations")
async def dashboard_rotations_save(request: Request, config: str = Form(...)):
    """Save rotations configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        rotations_data = json.loads(config)
        
        # Apply defaults: if condense_method is set but condense_context is not, default to 80
        if 'rotations' in rotations_data:
            for rotation_key, rotation in rotations_data['rotations'].items():
                if 'providers' in rotation and isinstance(rotation['providers'], list):
                    for provider in rotation['providers']:
                        if 'models' in provider and isinstance(provider['models'], list):
                            for model in provider['models']:
                                if 'condense_method' in model and model.get('condense_method'):
                                    if 'condense_context' not in model or model.get('condense_context') is None:
                                        model['condense_context'] = 80
        
        config_path = Path.home() / '.aisbf' / 'rotations.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(rotations_data, f, indent=2)
        
        available_providers = list(config.providers.keys()) if config else []
        
        return templates.TemplateResponse("dashboard/rotations.html", {
            "request": request,
            "session": request.session,
            "rotations_json": json.dumps(rotations_data),
            "available_providers": json.dumps(available_providers),
            "success": "Configuration saved successfully! Restart server for changes to take effect."
        })
    except json.JSONDecodeError as e:
        # Reload current config on error
        config_path = Path.home() / '.aisbf' / 'rotations.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'rotations.json'
        with open(config_path) as f:
            rotations_data = json.load(f)
        
        available_providers = list(config.providers.keys()) if config else []
        
        return templates.TemplateResponse("dashboard/rotations.html", {
            "request": request,
            "session": request.session,
            "rotations_json": json.dumps(rotations_data),
            "available_providers": json.dumps(available_providers),
            "error": f"Invalid JSON: {str(e)}"
        })

@app.get("/dashboard/autoselect", response_class=HTMLResponse)
async def dashboard_autoselect(request: Request):
    """Edit autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    config_path = Path.home() / '.aisbf' / 'autoselect.json'
    if not config_path.exists():
        config_path = Path(__file__).parent / 'config' / 'autoselect.json'
    
    with open(config_path) as f:
        autoselect_data = json.load(f)
    
    # Get available rotations
    available_rotations = list(config.rotations.keys()) if config else []
    
    # Get available provider models
    available_models = []
    
    # Add rotation IDs
    for rotation_id in available_rotations:
        available_models.append({
            'id': rotation_id,
            'name': f'{rotation_id} (rotation)',
            'type': 'rotation'
        })
    
    # Add provider models
    providers_path = Path.home() / '.aisbf' / 'providers.json'
    if not providers_path.exists():
        providers_path = Path(__file__).parent / 'config' / 'providers.json'
    
    if providers_path.exists():
        with open(providers_path) as f:
            providers_config = json.load(f)
            providers_data = providers_config.get('providers', {})
            
            for provider_id, provider in providers_data.items():
                if 'models' in provider and isinstance(provider['models'], list):
                    for model in provider['models']:
                        model_id = f"{provider_id}/{model['name']}"
                        available_models.append({
                            'id': model_id,
                            'name': f"{model_id} (provider model)",
                            'type': 'provider'
                        })
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse("dashboard/autoselect.html", {
        "request": request,
        "session": request.session,
        "autoselect_json": json.dumps(autoselect_data),
        "available_rotations": json.dumps(available_rotations),
        "available_models": json.dumps(available_models),
        "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
    })

@app.post("/dashboard/autoselect")
async def dashboard_autoselect_save(request: Request, config: str = Form(...)):
    """Save autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        autoselect_data = json.loads(config)
        config_path = Path.home() / '.aisbf' / 'autoselect.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(autoselect_data, f, indent=2)
        
        available_rotations = list(config.rotations.keys()) if config else []
        
        return templates.TemplateResponse("dashboard/autoselect.html", {
            "request": request,
            "session": request.session,
            "autoselect_json": json.dumps(autoselect_data),
            "available_rotations": json.dumps(available_rotations),
            "success": "Configuration saved successfully! Restart server for changes to take effect."
        })
    except json.JSONDecodeError as e:
        # Reload current config on error
        config_path = Path.home() / '.aisbf' / 'autoselect.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'autoselect.json'
        with open(config_path) as f:
            autoselect_data = json.load(f)
        
        available_rotations = list(config.rotations.keys()) if config else []
        
        return templates.TemplateResponse("dashboard/autoselect.html", {
            "request": request,
            "session": request.session,
            "autoselect_json": json.dumps(autoselect_data),
            "available_rotations": json.dumps(available_rotations),
            "error": f"Invalid JSON: {str(e)}"
        })

@app.get("/dashboard/prompts", response_class=HTMLResponse)
async def dashboard_prompts(request: Request):
    """Edit prompt templates"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Define available prompts
    prompt_files = [
        {'key': 'condensation_conversational', 'name': 'Condensation - Conversational', 'filename': 'condensation_conversational.md'},
        {'key': 'condensation_semantic', 'name': 'Condensation - Semantic', 'filename': 'condensation_semantic.md'},
        {'key': 'autoselect', 'name': 'Autoselect - Model Selection', 'filename': 'autoselect.md'},
    ]
    
    prompts_data = []
    for prompt_file in prompt_files:
        # Check user config first
        config_path = Path.home() / '.aisbf' / prompt_file['filename']
        
        if not config_path.exists():
            # Try installed locations
            installed_dirs = [
                Path.home() / '.local' / 'share' / 'aisbf',
                Path('/usr/share/aisbf'),
                Path(__file__).parent,  # For source tree
            ]
            
            source_path = None
            for installed_dir in installed_dirs:
                test_path = installed_dir / prompt_file['filename']
                if test_path.exists():
                    source_path = test_path
                    break
                # Also check config subdirectory
                test_path = installed_dir / 'config' / prompt_file['filename']
                if test_path.exists():
                    source_path = test_path
                    break
            
            if source_path:
                # Copy to user config directory
                config_path.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(source_path, config_path)
                logger.info(f"Copied prompt from {source_path} to {config_path}")
        
        if config_path.exists():
            with open(config_path) as f:
                content = f.read()
            prompts_data.append({
                'key': prompt_file['key'],
                'name': prompt_file['name'],
                'filename': prompt_file['filename'],
                'content': content
            })
        else:
            # Add empty prompt if file not found
            prompts_data.append({
                'key': prompt_file['key'],
                'name': prompt_file['name'],
                'filename': prompt_file['filename'],
                'content': f'# {prompt_file["name"]}\n\nPrompt template not found. Please add your prompt here.'
            })
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse("dashboard/prompts.html", {
        "request": request,
        "session": request.session,
        "prompts": prompt_files,
        "prompts_data": json.dumps(prompts_data),
        "success": "Prompt saved successfully!" if success else None
    })

@app.post("/dashboard/prompts")
async def dashboard_prompts_save(request: Request, prompt_key: str = Form(...), prompt_content: str = Form(...)):
    """Save prompt template"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Map prompt keys to filenames
    prompt_map = {
        'condensation_conversational': 'condensation_conversational.md',
        'condensation_semantic': 'condensation_semantic.md',
        'autoselect': 'autoselect.md',
    }
    
    if prompt_key not in prompt_map:
        return templates.TemplateResponse("dashboard/prompts.html", {
            "request": request,
            "session": request.session,
            "prompts": [],
            "prompts_data": "[]",
            "error": "Invalid prompt key"
        })
    
    filename = prompt_map[prompt_key]
    config_path = Path.home() / '.aisbf' / filename
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, 'w') as f:
        f.write(prompt_content)
    
    return RedirectResponse(url=url_for(request, "/dashboard/prompts?success=1"), status_code=303)

@app.get("/dashboard/condensation", response_class=HTMLResponse)
async def dashboard_condensation(request: Request):
    """Redirect to prompts page for backward compatibility"""
    return RedirectResponse(url=url_for(request, "/dashboard/prompts"), status_code=303)

@app.post("/dashboard/condensation")
async def dashboard_condensation_save(request: Request, config: str = Form(...)):
    """Save condensation prompts - backward compatibility"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    config_path = Path.home() / '.aisbf' / 'condensation_conversational.md'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        f.write(config)
    
    return RedirectResponse(url=url_for(request, "/dashboard/prompts?success=1"), status_code=303)

@app.get("/dashboard/settings", response_class=HTMLResponse)
async def dashboard_settings(request: Request):
    """Edit server settings"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    # Load aisbf.json - check user config first, then installed locations
    config_path = Path.home() / '.aisbf' / 'aisbf.json'
    
    if not config_path.exists():
        # Try installed locations
        installed_dirs = [
            Path.home() / '.local' / 'share' / 'aisbf',
            Path('/usr/share/aisbf'),
            Path(__file__).parent,  # For source tree
        ]
        
        source_path = None
        for installed_dir in installed_dirs:
            test_path = installed_dir / 'aisbf.json'
            if test_path.exists():
                source_path = test_path
                break
            # Also check config subdirectory
            test_path = installed_dir / 'config' / 'aisbf.json'
            if test_path.exists():
                source_path = test_path
                break
        
        if source_path:
            # Copy to user config directory
            config_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source_path, config_path)
            logger.info(f"Copied config from {source_path} to {config_path}")
        else:
            raise HTTPException(status_code=500, detail="Configuration file not found in any location")
    
    with open(config_path) as f:
        aisbf_config = json.load(f)
    
    # Ensure MCP config exists with defaults
    if 'mcp' not in aisbf_config:
        aisbf_config['mcp'] = {
            'enabled': False,
            'autoselect_tokens': [],
            'fullconfig_tokens': []
        }
    
    return templates.TemplateResponse("dashboard/settings.html", {
        "request": request,
        "session": request.session,
        "config": aisbf_config
    })

@app.post("/dashboard/settings")
async def dashboard_settings_save(
    request: Request,
    host: str = Form(...),
    port: int = Form(...),
    protocol: str = Form(...),
    auth_enabled: bool = Form(False),
    auth_tokens: str = Form(""),
    dashboard_username: str = Form(...),
    dashboard_password: str = Form(""),
    condensation_model_id: str = Form(...),
    autoselect_model_id: str = Form(...),
    mcp_enabled: bool = Form(False),
    autoselect_tokens: str = Form(""),
    fullconfig_tokens: str = Form(""),
    tor_enabled: bool = Form(False),
    tor_control_port: int = Form(9051),
    tor_control_host: str = Form("127.0.0.1"),
    tor_control_password: str = Form(""),
    tor_hidden_service_dir: str = Form(""),
    tor_hidden_service_port: int = Form(80),
    tor_socks_port: int = Form(9050),
    tor_socks_host: str = Form("127.0.0.1")
):
    """Save server settings"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Load current config
    config_path = Path.home() / '.aisbf' / 'aisbf.json'
    if not config_path.exists():
        config_path = Path(__file__).parent / 'config' / 'aisbf.json'
    
    with open(config_path) as f:
        aisbf_config = json.load(f)
    
    # Update config
    aisbf_config['server']['host'] = host
    aisbf_config['server']['port'] = port
    aisbf_config['server']['protocol'] = protocol
    aisbf_config['auth']['enabled'] = auth_enabled
    aisbf_config['auth']['tokens'] = [t.strip() for t in auth_tokens.split('\n') if t.strip()]
    aisbf_config['dashboard']['username'] = dashboard_username
    if dashboard_password:  # Only update if provided - hash the password
        password_hash = hashlib.sha256(dashboard_password.encode()).hexdigest()
        aisbf_config['dashboard']['password'] = password_hash
    aisbf_config['internal_model']['condensation_model_id'] = condensation_model_id
    aisbf_config['internal_model']['autoselect_model_id'] = autoselect_model_id
    
    # Update MCP config
    if 'mcp' not in aisbf_config:
        aisbf_config['mcp'] = {}
    aisbf_config['mcp']['enabled'] = mcp_enabled
    aisbf_config['mcp']['autoselect_tokens'] = [t.strip() for t in autoselect_tokens.split('\n') if t.strip()]
    aisbf_config['mcp']['fullconfig_tokens'] = [t.strip() for t in fullconfig_tokens.split('\n') if t.strip()]
    
    # Update TOR config
    if 'tor' not in aisbf_config:
        aisbf_config['tor'] = {}
    aisbf_config['tor']['enabled'] = tor_enabled
    aisbf_config['tor']['control_port'] = tor_control_port
    aisbf_config['tor']['control_host'] = tor_control_host
    aisbf_config['tor']['control_password'] = tor_control_password if tor_control_password else None
    aisbf_config['tor']['hidden_service_dir'] = tor_hidden_service_dir if tor_hidden_service_dir else None
    aisbf_config['tor']['hidden_service_port'] = tor_hidden_service_port
    aisbf_config['tor']['socks_port'] = tor_socks_port
    aisbf_config['tor']['socks_host'] = tor_socks_host
    
    # Save config
    config_path = Path.home() / '.aisbf' / 'aisbf.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(aisbf_config, f, indent=2)
    
    return templates.TemplateResponse("dashboard/settings.html", {
        "request": request,
        "session": request.session,
        "config": aisbf_config,
        "success": "Settings saved successfully! Restart server for changes to take effect."
    })

@app.post("/dashboard/restart")
async def dashboard_restart(request: Request):
    """Restart the server"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    import os
    import signal
    
    logger.info("Server restart requested from dashboard")
    
    # Schedule restart after response is sent
    def restart_server():
        import time
        time.sleep(1)  # Give time for response to be sent
        logger.info("Restarting server...")
        os.execv(sys.executable, [sys.executable] + _original_argv)
    
    import threading
    threading.Thread(target=restart_server, daemon=True).start()
    
    return JSONResponse({"message": "Server is restarting..."})

@app.get("/dashboard/tor/status")
async def dashboard_tor_status(request: Request):
    """Get TOR hidden service status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    global tor_service
    
    if tor_service:
        status = tor_service.get_status()
    else:
        status = {
            'enabled': False,
            'connected': False,
            'onion_address': None,
            'service_id': None,
            'control_host': None,
            'control_port': None,
            'hidden_service_port': None
        }
    
    return JSONResponse(status)

@app.get("/dashboard/docs", response_class=HTMLResponse)
async def dashboard_docs(request: Request):
    """Display documentation"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Try to find DOCUMENTATION.md in multiple locations
    search_paths = [
        Path.home() / '.aisbf' / 'DOCUMENTATION.md',
        Path.home() / '.local' / 'share' / 'aisbf' / 'DOCUMENTATION.md',
        Path('/usr/share/aisbf') / 'DOCUMENTATION.md',
        Path(__file__).parent / 'DOCUMENTATION.md',
    ]
    
    doc_path = None
    for path in search_paths:
        if path.exists():
            doc_path = path
            break
    
    if doc_path and doc_path.exists():
        with open(doc_path, encoding='utf-8') as f:
            markdown_content = f.read()
            # Convert markdown to HTML with extensions for better formatting
            html_content = markdown.markdown(
                markdown_content,
                extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists']
            )
    else:
        html_content = "<p>Documentation file not found.</p>"
    
    return templates.TemplateResponse("dashboard/docs.html", {
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "Documentation"
    })

@app.get("/dashboard/about", response_class=HTMLResponse)
async def dashboard_about(request: Request):
    """Display README/About"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Try to find README.md in multiple locations
    search_paths = [
        Path.home() / '.aisbf' / 'README.md',
        Path.home() / '.local' / 'share' / 'aisbf' / 'README.md',
        Path('/usr/share/aisbf') / 'README.md',
        Path(__file__).parent / 'README.md',
    ]
    
    readme_path = None
    for path in search_paths:
        if path.exists():
            readme_path = path
            break
    
    if readme_path and readme_path.exists():
        with open(readme_path, encoding='utf-8') as f:
            markdown_content = f.read()
            # Convert markdown to HTML with extensions for better formatting
            html_content = markdown.markdown(
                markdown_content,
                extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists']
            )
    else:
        html_content = "<p>README file not found.</p>"
    
    return templates.TemplateResponse("dashboard/docs.html", {
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "About"
    })

@app.get("/dashboard/license", response_class=HTMLResponse)
async def dashboard_license(request: Request):
    """Display License"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Try to find LICENSE.txt in multiple locations
    search_paths = [
        Path.home() / '.aisbf' / 'LICENSE.txt',
        Path.home() / '.local' / 'share' / 'aisbf' / 'LICENSE.txt',
        Path('/usr/share/aisbf') / 'LICENSE.txt',
        Path(__file__).parent / 'LICENSE.txt',
    ]
    
    license_path = None
    for path in search_paths:
        if path.exists():
            license_path = path
            break
    
    if license_path and license_path.exists():
        with open(license_path, encoding='utf-8') as f:
            content = f.read()
            # Convert to HTML with pre tags to preserve formatting
            html_content = f"<pre style='white-space: pre-wrap; word-wrap: break-word; background: #0f3460; padding: 20px; border-radius: 6px; color: #e0e0e0; font-family: inherit;'>{content}</pre>"
    else:
        html_content = "<p>License file not found.</p>"
    
    return templates.TemplateResponse("dashboard/docs.html", {
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "License"
    })

def parse_provider_from_model(model: str) -> tuple[str, str]:
    """
    Parse provider and model from model field.
    
    Supports formats:
    - "provider/model" -> ("provider", "model")
    - "provider/namespace/model" -> ("provider", "namespace/model")
    - "model" -> (None, "model")
    
    Returns:
        tuple: (provider_id, actual_model_name)
    """
    if '/' in model:
        parts = model.split('/', 1)
        return parts[0], parts[1]
    return None, model

@app.get("/")
async def root():
    return {
        "message": "AI Proxy Server is running",
        "providers": list(config.providers.keys()),
        "rotations": list(config.rotations.keys()),
        "autoselect": list(config.autoselect.keys())
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/models/{model_id}")
async def v1_get_model(model_id: str, request: Request):
    """Get a specific model by ID (OpenAI-compatible endpoint)"""
    # First try to find in all models
    all_models_response = await v1_list_all_models(request)
    all_models = all_models_response.get("data", [])
    
    for model in all_models:
        if model.get("id") == model_id:
            return model
    
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")


@app.post("/api/v1/completions")
async def v1_completions(request: Request):
    """
    Legacy text completions endpoint (OpenAI-compatible)
    Maps to chat/completions for compatibility
    """
    # Get the request body
    body = await request.body()
    import json
    data = json.loads(body) if body else {}
    
    # Convert completion request to chat completion
    prompt = data.get("prompt", "")
    model = data.get("model", "")
    max_tokens = data.get("max_tokens", 2048)
    temperature = data.get("temperature", 1.0)
    
    # Build chat messages from prompt
    messages = [{"role": "user", "content": prompt}]
    
    # Create a new request for chat/completions
    chat_request = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    # Call chat completions handler
    return await v1_chat_completions(chat_request, request)

# Standard OpenAI-compatible v1 endpoints
@app.post("/api/v1/chat/completions")
async def v1_chat_completions(request: Request, body: ChatCompletionRequest):
    """Standard OpenAI-compatible chat completions endpoint"""
    logger.info(f"=== V1 CHAT COMPLETION REQUEST ===")
    logger.info(f"Model: {body.model}")
    
    # Parse provider from model field
    provider_id, actual_model = parse_provider_from_model(body.model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    logger.info(f"Parsed provider: {provider_id}, model: {actual_model}")
    
    # Update body with actual model name
    body_dict = body.model_dump()
    
    # PATH 3: Check if it's an autoselect (format: autoselect/{name})
    if provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        body_dict['model'] = actual_model
        if body.stream:
            return await autoselect_handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await autoselect_handler.handle_autoselect_request(actual_model, body_dict)
    
    # PATH 2: Check if it's a rotation (format: rotation/{name})
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        body_dict['model'] = actual_model
        return await rotation_handler.handle_rotation_request(actual_model, body_dict)
    
    # PATH 1: Direct provider model (format: {provider}/{model})
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available providers: {list(config.providers.keys())}, or use 'rotation/name' or 'autoselect/name'"
        )
    
    # Validate kiro credentials before processing request
    provider_config = config.get_provider(provider_id)
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )
    
    # Handle as direct provider request
    body_dict['model'] = actual_model
    if body.stream:
        return await request_handler.handle_streaming_chat_completion(request, provider_id, body_dict)
    else:
        return await request_handler.handle_chat_completion(request, provider_id, body_dict)

@app.get("/api/models")
async def list_all_models(request: Request):
    """List all available models from all providers (public endpoint)"""
    logger.info("=== LIST ALL MODELS REQUEST ===")
    
    all_models = []
    
    # PATH 1: Add provider models (from local config or cached API results)
    for provider_id, provider_config in config.providers.items():
        try:
            provider_models = await get_provider_models(provider_id, provider_config)
            all_models.extend(provider_models)
        except Exception as e:
            logger.warning(f"Error listing models for provider {provider_id}: {e}")
    
    # PATH 2: Add rotations as rotation/{rotation_name}
    for rotation_id, rotation_config in config.rotations.items():
        try:
            all_models.append({
                'id': f"rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-rotation',
                'type': 'rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.model_name,
                'capabilities': getattr(rotation_config, 'capabilities', [])
            })
        except Exception as e:
            logger.warning(f"Error listing rotation {rotation_id}: {e}")
    
    # PATH 3: Add autoselect as autoselect/{autoselect_name}
    for autoselect_id, autoselect_config in config.autoselect.items():
        try:
            all_models.append({
                'id': f"autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-autoselect',
                'type': 'autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.model_name,
                'description': autoselect_config.description,
                'capabilities': getattr(autoselect_config, 'capabilities', [])
            })
        except Exception as e:
            logger.warning(f"Error listing autoselect {autoselect_id}: {e}")
    
    logger.info(f"Returning {len(all_models)} total models")
    return {"object": "list", "data": all_models}

@app.get("/api/v1/models")
async def v1_list_all_models(request: Request):
    """List all available models from all providers (OpenAI-compatible endpoint)"""
    logger.info("=== V1 LIST ALL MODELS REQUEST ===")
    
    all_models = []
    
    # PATH 1: Add provider models (from local config or cached API results)
    for provider_id, provider_config in config.providers.items():
        try:
            provider_models = await get_provider_models(provider_id, provider_config)
            all_models.extend(provider_models)
        except Exception as e:
            logger.warning(f"Error listing models for provider {provider_id}: {e}")
    
    # PATH 2: Add rotations as rotation/{rotation_name}
    for rotation_id, rotation_config in config.rotations.items():
        try:
            all_models.append({
                'id': f"rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-rotation',
                'type': 'rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.model_name,
                'capabilities': getattr(rotation_config, 'capabilities', [])
            })
        except Exception as e:
            logger.warning(f"Error listing rotation {rotation_id}: {e}")
    
    # PATH 3: Add autoselect as autoselect/{autoselect_name}
    for autoselect_id, autoselect_config in config.autoselect.items():
        try:
            all_models.append({
                'id': f"autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-autoselect',
                'type': 'autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.model_name,
                'description': autoselect_config.description,
                'capabilities': getattr(autoselect_config, 'capabilities', [])
            })
        except Exception as e:
            logger.warning(f"Error listing autoselect {autoselect_id}: {e}")
    
    logger.info(f"Returning {len(all_models)} total models")
    return {"object": "list", "data": all_models}

@app.post("/api/v1/audio/transcriptions")
async def v1_audio_transcriptions(request: Request):
    """Standard audio transcription endpoint (supports all three proxy paths)"""
    logger.info("=== V1 AUDIO TRANSCRIPTION REQUEST ===")
    
    form = await request.form()
    model = form.get('model', '')
    
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    # Validate kiro credentials before processing request
    provider_config = config.get_provider(provider_id)
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )
    
    # Create new form data with updated model
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        if key == 'model':
            updated_form[key] = actual_model
        else:
            updated_form[key] = value
    
    return await request_handler.handle_audio_transcription(request, provider_id, updated_form)

@app.post("/api/v1/audio/speech")
async def v1_audio_speech(request: Request, body: dict):
    """Standard text-to-speech endpoint (supports all three proxy paths)"""
    logger.info("=== V1 TEXT-TO-SPEECH REQUEST ===")
    
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    # Validate kiro credentials before processing request
    provider_config = config.get_provider(provider_id)
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )
    
    body['model'] = actual_model
    return await request_handler.handle_text_to_speech(request, provider_id, body)

@app.post("/api/v1/images/generations")
async def v1_image_generations(request: Request, body: dict):
    """Standard image generation endpoint (supports all three proxy paths)"""
    logger.info("=== V1 IMAGE GENERATION REQUEST ===")
    
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    # Validate kiro credentials before processing request
    provider_config = config.get_provider(provider_id)
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )
    
    body['model'] = actual_model
    return await request_handler.handle_image_generation(request, provider_id, body)

@app.post("/api/v1/embeddings")
async def v1_embeddings(request: Request, body: dict):
    """Standard embeddings endpoint (supports all three proxy paths)"""
    logger.info("=== V1 EMBEDDINGS REQUEST ===")
    
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    # Validate kiro credentials before processing request
    provider_config = config.get_provider(provider_id)
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )
    
    body['model'] = actual_model
    return await request_handler.handle_embeddings(request, provider_id, body)

@app.get("/api/rotations")
async def list_rotations():
    """List all available rotations"""
    logger.info("=== LIST ROTATIONS REQUEST ===")
    rotations_info = {}
    for rotation_id, rotation_config in config.rotations.items():
        models = []
        for provider in rotation_config.providers:
            for model in provider['models']:
                models.append({
                    "name": model['name'],
                    "provider_id": provider['provider_id'],
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                })
        rotations_info[rotation_id] = {
            "model_name": rotation_config.model_name,
            "models": models
        }
    logger.info(f"Available rotations: {list(rotations_info.keys())}")
    return rotations_info

@app.post("/api/rotations/chat/completions")
async def rotation_chat_completions(request: Request, body: ChatCompletionRequest):
    """
    Handle chat completions for rotations using model name to select rotation.
    
    The RotationHandler handles streaming internally based on the selected
    provider's type (google vs others), so we just pass through the response.
    """
    logger.info(f"=== ROTATION CHAT COMPLETION REQUEST START ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Model requested: {body.model}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request body: {body}")
    logger.info(f"Available rotations: {list(config.rotations.keys())}")

    body_dict = body.model_dump()

    # Check if the model name corresponds to a rotation
    if body.model not in config.rotations:
        logger.error(f"Model '{body.model}' not found in rotations")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        raise HTTPException(
            status_code=400,
            detail=f"Model '{body.model}' not found. Available rotations: {list(config.rotations.keys())}"
        )

    logger.info(f"Model '{body.model}' found in rotations")
    logger.debug("Handling rotation request")

    try:
        # The rotation handler handles streaming internally and returns
        # a StreamingResponse for streaming requests or a dict for non-streaming
        result = await rotation_handler.handle_rotation_request(body.model, body_dict)
        logger.debug(f"Rotation response result type: {type(result)}")
        return result
    except Exception as e:
        logger.error(f"Error handling rotation chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/rotations/models")
async def list_rotation_models():
    """List all models across all rotations"""
    logger.info("=== LIST ROTATION MODELS REQUEST ===")
    all_models = []
    for rotation_id, rotation_config in config.rotations.items():
        for provider in rotation_config.providers:
            for model in provider['models']:
                all_models.append({
                    "id": f"{rotation_id}/{model['name']}",
                    "name": rotation_id,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider['provider_id'],
                    "rotation_id": rotation_id,
                    "actual_model": model['name'],
                    "provider_id": provider['provider_id'],
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                })
    logger.info(f"Total rotation models available: {len(all_models)}")
    return {"data": all_models}

@app.get("/api/autoselect")
async def list_autoselect():
    """List all available autoselect configurations"""
    logger.info("=== LIST AUTOSELECT REQUEST ===")
    autoselect_info = {}
    for autoselect_id, autoselect_config in config.autoselect.items():
        autoselect_info[autoselect_id] = {
            "model_name": autoselect_config.model_name,
            "description": autoselect_config.description,
            "fallback": autoselect_config.fallback,
            "available_models": [
                {
                    "model_id": m.model_id,
                    "description": m.description
                }
                for m in autoselect_config.available_models
            ]
        }
    logger.info(f"Available autoselect: {list(autoselect_info.keys())}")
    return autoselect_info

@app.post("/api/autoselect/chat/completions")
async def autoselect_chat_completions(request: Request, body: ChatCompletionRequest):
    """Handle chat completions for autoselect using model name to select autoselect configuration"""
    logger.info(f"=== AUTOSELECT CHAT COMPLETION REQUEST START ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    # Log raw request body for debugging
    try:
        raw_body = await request.body()
        logger.info(f"Raw request body: {raw_body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"Error reading raw body: {str(e)}")
    
    logger.info(f"Model requested: {body.model}")
    logger.info(f"Request body: {body}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys())}")

    body_dict = body.model_dump()

    # Check if the model name corresponds to an autoselect configuration
    if body.model not in config.autoselect:
        logger.error(f"Model '{body.model}' not found in autoselect")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(
            status_code=400,
            detail=f"Model '{body.model}' not found. Available autoselect: {list(config.autoselect.keys())}"
        )

    logger.info(f"Model '{body.model}' found in autoselect")
    logger.debug("Handling autoselect request")

    try:
        if body.stream:
            logger.debug("Handling streaming autoselect request")
            return await autoselect_handler.handle_autoselect_streaming_request(body.model, body_dict)
        else:
            logger.debug("Handling non-streaming autoselect request")
            result = await autoselect_handler.handle_autoselect_request(body.model, body_dict)
            logger.debug(f"Autoselect response result: {result}")
            return result
    except Exception as e:
        logger.error(f"Error handling autoselect chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/autoselect/models")
async def list_autoselect_models():
    """List all models across all autoselect configurations"""
    logger.info("=== LIST AUTOSELECT MODELS REQUEST ===")
    all_models = []
    for autoselect_id, autoselect_config in config.autoselect.items():
        for model_info in autoselect_config.available_models:
            all_models.append({
                "id": model_info.model_id,
                "name": autoselect_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "autoselect",
                "autoselect_id": autoselect_id,
                "description": model_info.description,
                "fallback": autoselect_config.fallback
            })
    logger.info(f"Total autoselect models available: {len(all_models)}")
    return {"data": all_models}

@app.post("/api/{provider_id}/chat/completions")
async def chat_completions(provider_id: str, request: Request, body: ChatCompletionRequest):
    logger.info(f"=== CHAT COMPLETION REQUEST START ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request body: {body}")
    logger.info(f"Available providers: {list(config.providers.keys())}")
    logger.info(f"Available rotations: {list(config.rotations.keys())}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys())}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Request body: {body}")

    body_dict = body.model_dump()

    # Check if it's an autoselect
    if provider_id in config.autoselect:
        logger.debug("Handling autoselect request")
        try:
            if body.stream:
                logger.debug("Handling streaming autoselect request")
                return await autoselect_handler.handle_autoselect_streaming_request(provider_id, body_dict)
            else:
                logger.debug("Handling non-streaming autoselect request")
                result = await autoselect_handler.handle_autoselect_request(provider_id, body_dict)
                logger.debug(f"Autoselect response result: {result}")
                return result
        except Exception as e:
            logger.error(f"Error handling autoselect: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations:
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation request")
        return await rotation_handler.handle_rotation_request(provider_id, body_dict)

    # Check if it's a provider
    if provider_id not in config.providers:
        logger.error(f"Provider ID '{provider_id}' not found in providers")
        logger.error(f"Available providers: {list(config.providers.keys())}")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")

    logger.info(f"Provider ID '{provider_id}' found in providers")

    provider_config = config.get_provider(provider_id)
    logger.debug(f"Provider config: {provider_config}")
    
    # Validate kiro credentials before processing request
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )

    try:
        if body.stream:
            logger.debug("Handling streaming chat completion")
            return await request_handler.handle_streaming_chat_completion(request, provider_id, body_dict)
        else:
            logger.debug("Handling non-streaming chat completion")
            result = await request_handler.handle_chat_completion(request, provider_id, body_dict)
            logger.debug(f"Response result: {result}")
            return result
    except Exception as e:
        logger.error(f"Error handling chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/{provider_id}/models")
async def list_models(request: Request, provider_id: str):
    logger.debug(f"Received list_models request for provider: {provider_id}")

    # Check if it's an autoselect
    if provider_id in config.autoselect:
        logger.debug("Handling autoselect model list request")
        try:
            result = await autoselect_handler.handle_autoselect_model_list(provider_id)
            logger.debug(f"Autoselect models result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error handling autoselect model list: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations:
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation model list request")
        return await rotation_handler.handle_rotation_model_list(provider_id)

    # Check if it's a provider
    if provider_id not in config.providers:
        logger.error(f"Provider ID '{provider_id}' not found in providers")
        logger.error(f"Available providers: {list(config.providers.keys())}")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")

    logger.info(f"Provider ID '{provider_id}' found in providers")

    provider_config = config.get_provider(provider_id)

    try:
        logger.debug("Handling model list request")
        result = await request_handler.handle_model_list(request, provider_id)
        logger.debug(f"Models result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error handling list_models: {str(e)}", exc_info=True)
        raise

# Audio endpoints (model specified in request as provider/model, rotation/name, or autoselect/name)
@app.post("/api/audio/transcriptions")
async def audio_transcriptions(request: Request):
    """Handle audio transcription requests (supports all three proxy paths)"""
    logger.info("=== AUDIO TRANSCRIPTION REQUEST ===")
    
    form = await request.form()
    model = form.get('model', '')
    
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        # Select a provider from the rotation using weighted random selection
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        # Use the fallback model from autoselect config
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        # Parse the fallback to get provider and model
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            # Fallback is a rotation, select from it
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    # Validate provider exists
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    # Create new form data with updated model
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        if key == 'model':
            updated_form[key] = actual_model
        else:
            updated_form[key] = value
    
    return await request_handler.handle_audio_transcription(request, provider_id, updated_form)

@app.post("/api/audio/speech")
async def audio_speech(request: Request, body: dict):
    """Handle text-to-speech requests (supports all three proxy paths)"""
    logger.info("=== TEXT-TO-SPEECH REQUEST ===")
    
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    body['model'] = actual_model
    return await request_handler.handle_text_to_speech(request, provider_id, body)

# Image endpoints (supports all three proxy paths)
@app.post("/api/images/generations")
async def image_generations(request: Request, body: dict):
    """Handle image generation requests (supports all three proxy paths)"""
    logger.info("=== IMAGE GENERATION REQUEST ===")
    
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    body['model'] = actual_model
    return await request_handler.handle_image_generation(request, provider_id, body)

# Embeddings endpoint (supports all three proxy paths)
@app.post("/api/embeddings")
async def embeddings(request: Request, body: dict):
    """Handle embeddings requests (supports all three proxy paths)"""
    logger.info("=== EMBEDDINGS REQUEST ===")
    
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'"
        )
    
    # Handle rotation
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        selected_provider, selected_model = rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    
    # Handle autoselect
    elif provider_id == "autoselect":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        autoselect_config = config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in config.rotations:
                selected_provider, selected_model = rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fallback configuration for autoselect '{actual_model}'"
                )
    
    if provider_id not in config.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' not found. Available: {list(config.providers.keys())}"
        )
    
    # Validate kiro credentials before processing request
    provider_config = config.get_provider(provider_id)
    if not validate_kiro_credentials(provider_id, provider_config):
        raise HTTPException(
            status_code=403,
            detail=f"Provider '{provider_id}' credentials not available. Please configure credentials for this provider."
        )
    
    body['model'] = actual_model
    return await request_handler.handle_embeddings(request, provider_id, body)

# Content proxy endpoint
@app.get("/api/proxy/{content_id}")
async def proxy_content(content_id: str):
    """Proxy generated content (images, audio, etc.)"""
    logger.info(f"=== PROXY CONTENT REQUEST ===")
    logger.info(f"Content ID: {content_id}")
    
    try:
        result = await request_handler.handle_content_proxy(content_id)
        return result
    except Exception as e:
        logger.error(f"Error proxying content: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/{provider_id}")
async def catch_all_post(provider_id: str, request: Request):
    """Catch-all for POST requests to help debug routing issues"""
    logger.info(f"=== CATCH-ALL POST REQUEST ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Available providers: {list(config.providers.keys())}")
    logger.info(f"Available rotations: {list(config.rotations.keys())}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys())}")

    error_msg = f"""
    Invalid endpoint: {request.url.path}

    The correct endpoint format is: /api/{{provider_id}}/chat/completions

    Available providers: {list(config.providers.keys())}
    Available rotations: {list(config.rotations.keys())}
    Available autoselect: {list(config.autoselect.keys())}

    Example: POST /api/ollama/chat/completions
    """
    logger.error(error_msg)
    raise HTTPException(status_code=404, detail=error_msg.strip())

def main():
    """Main entry point for the AISBF server"""
    import uvicorn
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='AISBF - AI Service Broker Framework',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aisbf                                    # Start with default settings
  aisbf --host 127.0.0.1 --port 8080      # Custom host and port
  aisbf --config /path/to/config          # Use custom config directory
  aisbf --https --ssl-cert cert.pem       # Enable HTTPS with custom cert
        """
    )
    
    parser.add_argument('--config', type=str, help='Custom config directory path')
    parser.add_argument('--host', type=str, help='Server host (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, help='Server port (default: 17765)')
    parser.add_argument('--https', action='store_true', help='Enable HTTPS')
    parser.add_argument('--ssl-cert', type=str, help='SSL certificate file path')
    parser.add_argument('--ssl-key', type=str, help='SSL private key file path')
    parser.add_argument('--no-auth', action='store_true', help='Disable authentication (override config)')
    
    args = parser.parse_args()
    
    # Store original command line arguments for restart functionality
    global _original_argv
    _original_argv = sys.argv.copy()
    
    # Initialize app (this sets config, handlers, server_config)
    initialize_app(args.config)
    
    # Get the now-initialized server_config
    global server_config
    
    # CLI arguments take precedence over config file
    host = args.host if args.host else server_config['host']
    port = args.port if args.port else server_config['port']
    
    # Protocol handling
    if args.https:
        protocol = 'https'
        ssl_certfile = args.ssl_cert if args.ssl_cert else server_config.get('ssl_certfile')
        ssl_keyfile = args.ssl_key if args.ssl_key else server_config.get('ssl_keyfile')
        
        # Auto-generate if not provided
        if not ssl_certfile or not ssl_keyfile:
            ssl_dir = Path.home() / '.aisbf' / 'ssl'
            ssl_certfile = str(ssl_dir / 'cert.pem')
            ssl_keyfile = str(ssl_dir / 'key.pem')
        
        cert_path = Path(ssl_certfile).expanduser()
        key_path = Path(ssl_keyfile).expanduser()
        
        if not cert_path.exists() or not key_path.exists():
            generate_self_signed_cert(cert_path, key_path)
    else:
        protocol = server_config.get('protocol', 'http')
        ssl_certfile = server_config.get('ssl_certfile')
        ssl_keyfile = server_config.get('ssl_keyfile')
        
        # Handle HTTPS from config
        if protocol == 'https':
            if not ssl_certfile or not ssl_keyfile:
                ssl_dir = Path.home() / '.aisbf' / 'ssl'
                ssl_certfile = str(ssl_dir / 'cert.pem')
                ssl_keyfile = str(ssl_dir / 'key.pem')
            
            cert_path = Path(ssl_certfile).expanduser()
            key_path = Path(ssl_keyfile).expanduser()
            
            if not cert_path.exists() or not key_path.exists():
                generate_self_signed_cert(cert_path, key_path)
    
    # Authentication handling
    auth_enabled = not args.no_auth and server_config.get('auth_enabled', False)
    
    # Update global server_config with final values
    server_config['host'] = host
    server_config['port'] = port
    server_config['protocol'] = protocol
    server_config['ssl_certfile'] = ssl_certfile if protocol == 'https' else None
    server_config['ssl_keyfile'] = ssl_keyfile if protocol == 'https' else None
    server_config['auth_enabled'] = auth_enabled
    
    # Log server configuration
    logger.info(f"=== AISBF Server Configuration ===")
    logger.info(f"Protocol: {protocol}")
    logger.info(f"Host: {host}")
    logger.info(f"Port: {port}")
    logger.info(f"Authentication: {'Enabled' if auth_enabled else 'Disabled'}")
    if args.config:
        logger.info(f"Config Directory: {args.config}")
    
    if protocol == 'https':
        logger.info(f"SSL Certificate: {ssl_certfile}")
        logger.info(f"SSL Key: {ssl_keyfile}")
        logger.info(f"Starting AI Proxy Server on https://{host}:{port}")
        uvicorn.run(
            app,
            host=host,
            port=port,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile
        )
    else:
        logger.info(f"Starting AI Proxy Server on http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)

# MCP (Model Context Protocol) endpoints
# These endpoints allow remote agents to configure the system and make model requests

def get_mcp_auth_level(request: Request) -> int:
    """Get MCP authentication level from request header"""
    mcp_config = load_mcp_config()
    
    if not mcp_config.get('enabled', False):
        # If MCP is not explicitly enabled, check for legacy auth tokens
        if server_config and server_config.get('auth_enabled', False):
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header.replace('Bearer ', '')
                if token in server_config.get('auth_tokens', []):
                    return MCPAuthLevel.FULLCONFIG
        # Default to no access if MCP is not enabled
        return MCPAuthLevel.NONE
    
    fullconfig_tokens = mcp_config.get('fullconfig_tokens', [])
    autoselect_tokens = mcp_config.get('autoselect_tokens', [])
    
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return MCPAuthLevel.NONE
    
    token = auth_header.replace('Bearer ', '')
    
    if token in fullconfig_tokens:
        return MCPAuthLevel.FULLCONFIG
    
    if token in autoselect_tokens:
        return MCPAuthLevel.AUTOSELECT
    
    return MCPAuthLevel.NONE


@app.get("/mcp")
async def mcp_sse(request: Request):
    """
    MCP SSE (Server-Sent Events) endpoint.
    
    This endpoint provides MCP protocol support via Server-Sent Events.
    It supports both tool calls and streaming responses.
    
    Authentication:
    - Use 'Authorization: Bearer <token>' header
    - Tokens in 'mcp.fullconfig_tokens' have full configuration access
    - Tokens in 'mcp.autoselect_tokens' have autoselection/autorotation access only
    """
    # Check authentication
    auth_level = get_mcp_auth_level(request)
    
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(
            status_code=401,
            content={"error": "Invalid or missing MCP authentication token"}
        )
    
    async def event_generator():
        """Generate SSE events for MCP responses"""
        import json
        
        # Send initial connection event
        yield f"data: {json.dumps({'event': 'connected', 'auth_level': auth_level})}\n\n".encode('utf-8')
        
        # Read request from query parameter (for GET) or stream body (for POST)
        request_text = ""
        
        # For SSE, we need to read the request body
        try:
            body = await request._receive()
            if body and isinstance(body, bytes):
                request_text = body.decode('utf-8')
            elif body and isinstance(body, dict):
                request_text = json.dumps(body)
        except Exception as e:
            logger.warning(f"Error reading MCP request body: {e}")
        
        # If no body, check query params
        if not request_text:
            request_text = request.query_params.get('request', '{}')
        
        try:
            mcp_request = json.loads(request_text) if request_text else {}
        except json.JSONDecodeError:
            yield f"data: {json.dumps({'error': 'Invalid JSON request'})}\n\n".encode('utf-8')
            return
        
        method = mcp_request.get('method', '')
        request_id = mcp_request.get('id')
        params = mcp_request.get('params', {})
        
        # Handle different MCP methods
        if method == 'initialize':
            # Return server capabilities
            capabilities = {
                "tools": {
                    "listChanged": True
                },
                "resources": {
                    "subscribe": True,
                    "listChanged": True
                }
            }
            
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": capabilities,
                    "serverInfo": {
                        "name": "AISBF MCP Server",
                        "version": "1.0.0"
                    }
                }
            }
            yield f"data: {json.dumps(response)}\n\n".encode('utf-8')
            
        elif method == 'tools/list':
            # Return available tools
            tools = mcp_server.get_available_tools(auth_level)
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": tools
                }
            }
            yield f"data: {json.dumps(response)}\n\n".encode('utf-8')
            
        elif method == 'tools/call':
            # Call a tool
            tool_name = params.get('name')
            arguments = params.get('arguments', {})
            
            if not tool_name:
                yield f"data: {json.dumps({'error': 'Tool name is required'})}\n\n".encode('utf-8')
                return
            
            try:
                result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level)
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
                yield f"data: {json.dumps(response)}\n\n".encode('utf-8')
            except HTTPException as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": e.status_code,
                        "message": e.detail
                    }
                }
                yield f"data: {json.dumps(error_response)}\n\n".encode('utf-8')
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                yield f"data: {json.dumps(error_response)}\n\n".encode('utf-8')
        
        # Send done event
        yield f"data: {json.dumps({'event': 'done'})}\n\n".encode('utf-8')
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/mcp")
async def mcp_post(request: Request):
    """
    MCP HTTP POST endpoint.
    
    This endpoint provides MCP protocol support via regular HTTP POST requests.
    
    Authentication:
    - Use 'Authorization: Bearer <token>' header
    - Tokens in 'mcp.fullconfig_tokens' have full configuration access
    - Tokens in 'mcp.autoselect_tokens' have autoselection/autorotation access only
    """
    # Check authentication
    auth_level = get_mcp_auth_level(request)
    
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(
            status_code=401,
            content={"error": "Invalid or missing MCP authentication token"}
        )
    
    # Parse request body
    try:
        body = await request.body()
        mcp_request = json.loads(body.decode('utf-8')) if body else {}
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON request body"}
        )
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid request body"}
        )
    
    method = mcp_request.get('method', '')
    request_id = mcp_request.get('id')
    params = mcp_request.get('params', {})
    
    # Handle different MCP methods
    if method == 'initialize':
        # Return server capabilities
        capabilities = {
            "tools": {
                "listChanged": True
            },
            "resources": {
                "subscribe": True,
                "listChanged": True
            }
        }
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": capabilities,
                "serverInfo": {
                    "name": "AISBF MCP Server",
                    "version": "1.0.0"
                }
            }
        }
        
    elif method == 'tools/list':
        # Return available tools
        tools = mcp_server.get_available_tools(auth_level)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools
            }
        }
        
    elif method == 'tools/call':
        # Call a tool
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        
        if not tool_name:
            return JSONResponse(
                status_code=400,
                content={"error": "Tool name is required"}
            )
        
        try:
            result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        except HTTPException as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": e.status_code,
                    "message": e.detail
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
    
    return JSONResponse(
        status_code=400,
        content={"error": "Unknown MCP method"}
    )


@app.get("/mcp/tools")
async def mcp_list_tools(request: Request):
    """
    List available MCP tools for the authenticated client.
    """
    auth_level = get_mcp_auth_level(request)
    
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(
            status_code=401,
            content={"error": "Invalid or missing MCP authentication token"}
        )
    
    tools = mcp_server.get_available_tools(auth_level)
    return {"tools": tools}


@app.post("/mcp/tools/call")
async def mcp_call_tool(request: Request):
    """
    Call an MCP tool directly via HTTP POST.
    """
    auth_level = get_mcp_auth_level(request)
    
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(
            status_code=401,
            content={"error": "Invalid or missing MCP authentication token"}
        )
    
    # Parse request body
    try:
        body = await request.body()
        body_data = json.loads(body.decode('utf-8')) if body else {}
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON request body"}
        )
    
    tool_name = body_data.get('name')
    arguments = body_data.get('arguments', {})
    
    if not tool_name:
        return JSONResponse(
            status_code=400,
            content={"error": "Tool name is required"}
        )
    
    try:
        result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level)
        return {"result": result}
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": e.detail}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


if __name__ == "__main__":
    main()
