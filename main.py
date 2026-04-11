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
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, status, Form, Query, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates
from aisbf.models import ChatCompletionRequest, ChatCompletionResponse
from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
from aisbf.mcp import mcp_server, MCPAuthLevel, load_mcp_config
from aisbf.database import initialize_database
from aisbf.cache import initialize_cache
from aisbf.tor import setup_tor_hidden_service, TorHiddenService
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers
from itsdangerous import URLSafeTimedSerializer
import time
import logging
import sys
import os
import signal
import atexit
import argparse
import secrets
import hashlib
import asyncio
import httpx
import multiprocessing
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
        URL respecting proxy configuration - relative if behind proxy, full otherwise
    """
    root_path = request.scope.get("root_path", "")

    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path

    if root_path:
        # Behind proxy: return relative URL that browser resolves correctly
        return root_path + path
    else:
        # Not behind proxy: return full URL
        base_url = get_base_url(request)
        return f"{base_url}{path}"

# Note: config will be imported after parsing CLI args if --config is provided
# For now, we'll delay the import and initialization
app = FastAPI(
    title="AI Proxy Server",
    max_request_size=100 * 1024 * 1024  # 100MB max request size
)

# Add proxy headers middleware (must be added before other middleware)
app.add_middleware(ProxyHeadersMiddleware)

# Initialize Jinja2 templates with custom globals for proxy-aware URLs
templates = Jinja2Templates(directory="templates")

# Add custom template globals for proxy-aware URL generation
def setup_template_globals():
    """Setup Jinja2 template globals for proxy-aware URLs"""
    templates.env.globals['url_for'] = url_for
    templates.env.globals['get_base_url'] = get_base_url
    # Clear the template cache to avoid stale cache issues
    templates.env.cache.clear()

# Call setup after templates are initialized
setup_template_globals()

# Add session middleware at module level with a persistent secret key
# This is needed for uvicorn import (when main() doesn't run)
# Use a persistent secret key so sessions survive server restarts
def _get_or_create_session_secret():
    """Get or create a persistent session secret key"""
    secret_file = Path.home() / '.aisbf' / 'session_secret.key'
    
    if secret_file.exists():
        try:
            with open(secret_file, 'r') as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"Failed to read session secret, generating new one: {e}")
    
    # Generate new secret
    secret = secrets.token_urlsafe(32)
    
    # Save it for future use
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        with open(secret_file, 'w') as f:
            f.write(secret)
        # Set restrictive permissions
        import os
        os.chmod(secret_file, 0o600)
    except Exception as e:
        logger.warning(f"Failed to save session secret: {e}")
    
    return secret

_session_secret = _get_or_create_session_secret()
# Configure session middleware: 30 days max age (cookie expiration)
# Note: Session data is stored in signed cookies, so it persists across restarts
app.add_middleware(SessionMiddleware, secret_key=_session_secret, max_age=30 * 24 * 60 * 60)  # 30 days max age

# These will be initialized in startup event or main() after config is loaded
request_handler = None
rotation_handler = None
autoselect_handler = None
server_config = None
config = None
_initialized = False

# Cache for user-specific handlers to avoid recreating them
_user_handlers_cache = {}

def get_user_handler(handler_type: str, user_id=None):
    """Get the appropriate handler for a user, with caching"""
    global request_handler, rotation_handler, autoselect_handler, _user_handlers_cache

    if user_id is None:
        # Return global handlers for non-authenticated requests
        if handler_type == 'request':
            return request_handler
        elif handler_type == 'rotation':
            return rotation_handler
        elif handler_type == 'autoselect':
            return autoselect_handler
        else:
            raise ValueError(f"Unknown handler type: {handler_type}")

    # Check cache first
    cache_key = f"{handler_type}_{user_id}"
    if cache_key in _user_handlers_cache:
        return _user_handlers_cache[cache_key]

    # Create new handler instance for this user
    if handler_type == 'request':
        handler = RequestHandler(user_id)
    elif handler_type == 'rotation':
        handler = RotationHandler(user_id)
    elif handler_type == 'autoselect':
        handler = AutoselectHandler(user_id)
    else:
        raise ValueError(f"Unknown handler type: {handler_type}")

    # Cache it
    _user_handlers_cache[cache_key] = handler
    return handler
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

async def fetch_provider_models(provider_id: str, user_id: Optional[int] = None) -> list:
    """Fetch models from provider API and cache them"""
    global _model_cache, _model_cache_timestamps
    
    try:
        logger.debug(f"Fetching models from provider: {provider_id} (user_id: {user_id})")
        # Create request handler with correct user context
        request_handler = RequestHandler(user_id=user_id)
        
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
        
        # Fetch models from provider API (use user context if available)
        models = await request_handler.handle_model_list(dummy_request, provider_id)

        # Cache the results - separate cache for users vs global
        cache_key = f"{provider_id}:{user_id}" if user_id else provider_id
        _model_cache[cache_key] = models
        _model_cache_timestamps[cache_key] = time.time()
        
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

async def get_provider_models(provider_id: str, provider_config, user_id: Optional[int] = None) -> list:
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
    
    # Validate provider authentication status
    provider_type = getattr(provider_config, 'type', '')
    
    # Validate kiro/kiro-cli credentials
    if provider_type in ('kiro', 'kiro-cli'):
        if not validate_kiro_credentials(provider_id, provider_config):
            logger.debug(f"Skipping provider {provider_id}: Kiro credentials not available or invalid")
            return []
    
    # Validate Codex OAuth2 credentials
    if provider_type == 'codex':
        try:
            from aisbf.auth.codex import CodexOAuth2
            codex_config = getattr(provider_config, 'codex_config', {})
            credentials_file = codex_config.get('credentials_file', '~/.aisbf/codex_credentials.json')
            auth = CodexOAuth2(credentials_file=credentials_file)
            if not auth.is_authenticated():
                logger.debug(f"Skipping provider {provider_id}: Codex OAuth2 not authenticated")
                return []
        except Exception as e:
            logger.debug(f"Codex auth check failed for {provider_id}: {e}")
    
    # Validate Qwen OAuth2 credentials
    if provider_type == 'qwen':
        try:
            from aisbf.auth.qwen import QwenOAuth2
            qwen_config = getattr(provider_config, 'qwen_config', {})
            credentials_file = qwen_config.get('credentials_file', '~/.aisbf/qwen_credentials.json')
            auth = QwenOAuth2(credentials_file=credentials_file)
            if not auth.is_authenticated():
                logger.debug(f"Skipping provider {provider_id}: Qwen OAuth2 not authenticated")
                return []
        except Exception as e:
            logger.debug(f"Qwen auth check failed for {provider_id}: {e}")
    
    # Validate Claude OAuth2 credentials
    if provider_type == 'claude':
        try:
            from aisbf.auth.claude import ClaudeAuth
            claude_config = getattr(provider_config, 'claude_config', {})
            credentials_file = claude_config.get('credentials_file', '~/.claude_credentials.json')
            auth = ClaudeAuth(credentials_file=credentials_file)
            if not auth.is_authenticated():
                logger.debug(f"Skipping provider {provider_id}: Claude OAuth2 not authenticated")
                return []
        except Exception as e:
            logger.debug(f"Claude auth check failed for {provider_id}: {e}")
    
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
    cache_key = f"{provider_id}:{user_id}" if user_id else provider_id
    if cache_key in _model_cache:
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
            fetched_models = await fetch_provider_models(provider_id, user_id=user_id)
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
            db_config = config.aisbf.database if config.aisbf and config.aisbf.database else None
            initialize_database(db_config)
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            # Continue startup even if database fails

        # Initialize cache
        try:
            cache_config = config.aisbf.cache if config.aisbf and config.aisbf.cache else None
            initialize_cache(cache_config)
        except Exception as e:
            logger.error(f"Failed to initialize cache: {e}")
            # Continue startup even if cache fails

        # Initialize response cache
        try:
            from aisbf.cache import initialize_response_cache
            response_cache_config = config.aisbf.response_cache if config.aisbf and config.aisbf.response_cache else None
            if response_cache_config:
                initialize_response_cache(response_cache_config.model_dump() if hasattr(response_cache_config, 'model_dump') else response_cache_config)
                logger.info("Response cache initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize response cache: {e}")
            # Continue startup even if response cache fails

        # Initialize request batcher
        try:
            from aisbf.batching import initialize_request_batcher
            batching_config = config.aisbf.batching if config.aisbf and config.aisbf.batching else None
            if batching_config:
                # Convert to dict for the batcher
                batching_dict = batching_config.model_dump() if hasattr(batching_config, 'model_dump') else dict(batching_config) if batching_config else None
                initialize_request_batcher(batching_dict)
                logger.info(f"Request batcher initialized: enabled={batching_dict.get('enabled', False)}")
        except Exception as e:
            logger.error(f"Failed to initialize request batcher: {e}")
            # Continue startup even if batching fails
    
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
    
    # Pre-fetch models at startup for providers without local model config
    # For Kilo providers, check API key, OAuth2 file credentials, and database-stored credentials
    logger.info("Pre-fetching models from providers with dynamic model lists...")
    prefetch_count = 0
    for provider_id, provider_config in config.providers.items():
        if not (hasattr(provider_config, 'models') and provider_config.models):
            # For Kilo providers, check if any authentication method is available
            provider_type = getattr(provider_config, 'type', '')
            if provider_type in ('kilo', 'kilocode'):
                has_valid_auth = False
                
                # Check 1: API key
                api_key = getattr(provider_config, 'api_key', None)
                if api_key and not api_key.startswith('YOUR_'):
                    has_valid_auth = True
                    logger.info(f"Kilo provider '{provider_id}' has API key configured, fetching models...")
                
                # Check 2: OAuth2 credentials file
                if not has_valid_auth:
                    try:
                        from aisbf.auth.kilo import KiloOAuth2
                        kilo_config = getattr(provider_config, 'kilo_config', None)
                        credentials_file = None
                        api_base = getattr(provider_config, 'endpoint', 'https://api.kilo.ai')
                        
                        if kilo_config and isinstance(kilo_config, dict):
                            credentials_file = kilo_config.get('credentials_file')
                            # Override api_base from kilo_config if present
                            if 'api_base' in kilo_config and kilo_config['api_base']:
                                api_base = kilo_config['api_base']
                        
                        oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
                        if oauth2.is_authenticated():
                            has_valid_auth = True
                            logger.info(f"Kilo provider '{provider_id}' has valid OAuth2 credentials file, fetching models...")
                    except Exception as e:
                        logger.debug(f"Kilo provider '{provider_id}' OAuth2 file check failed: {e}")
                
                # Check 3: Database-stored credentials (uploaded via dashboard)
                if not has_valid_auth:
                    try:
                        from aisbf.database import get_database
                        db = get_database()
                        if db:
                            # Check for uploaded credentials files for this provider
                            auth_files = db.get_user_auth_files(0, provider_id)  # 0 for admin/global
                            if auth_files:
                                for auth_file in auth_files:
                                    file_type = auth_file.get('file_type', '')
                                    file_path = auth_file.get('file_path', '')
                                    if file_type in ('credentials', 'kilo_credentials', 'config') and file_path:
                                        if os.path.exists(file_path):
                                            has_valid_auth = True
                                            logger.info(f"Kilo provider '{provider_id}' has uploaded credentials in database, fetching models...")
                                            break
                    except Exception as e:
                        logger.debug(f"Kilo provider '{provider_id}' database credentials check failed: {e}")
                
                if not has_valid_auth:
                    logger.info(f"Skipping model prefetch for Kilo provider '{provider_id}' (no API key, OAuth2 file, or uploaded credentials)")
                    continue
            
            try:
                models = await fetch_provider_models(provider_id)
                if models:
                    prefetch_count += 1
                    logger.info(f"Pre-fetched {len(models)} models from provider: {provider_id}")
            except Exception as e:
                logger.warning(f"Failed to pre-fetch models from provider {provider_id}: {e}")
    
    if prefetch_count > 0:
        logger.info(f"Pre-fetched models from {prefetch_count} provider(s) at startup")
    else:
        logger.info("No providers with dynamic model lists found for pre-fetching")
    
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

def _cleanup_multiprocessing_children():
    """Terminate any lingering multiprocessing child processes."""
    try:
        active_children = multiprocessing.active_children()
        if active_children:
            logger.info(f"Terminating {len(active_children)} multiprocessing child process(es)...")
            for child in active_children:
                logger.debug(f"  Terminating child process: {child.name} (PID {child.pid})")
                child.terminate()
            # Give them a moment to terminate gracefully
            for child in active_children:
                child.join(timeout=2)
            # Force kill any still alive
            for child in multiprocessing.active_children():
                logger.warning(f"  Force killing child process: {child.name} (PID {child.pid})")
                child.kill()
    except Exception as e:
        logger.warning(f"Error cleaning up multiprocessing children: {e}")


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for clean shutdown including multiprocessing children."""
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, shutting down...")
    _cleanup_multiprocessing_children()
    # Re-raise the signal so uvicorn can handle its own shutdown
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


# Register signal handlers for clean shutdown
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# Also register atexit handler as a safety net
atexit.register(_cleanup_multiprocessing_children)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global tor_service
    
    # Cleanup TOR hidden service
    if tor_service:
        logger.info("Shutting down TOR hidden service...")
        tor_service.disconnect()
        logger.info("TOR hidden service shutdown complete")
    
    # Cleanup multiprocessing children (sentence-transformers, torch, etc.)
    _cleanup_multiprocessing_children()

# Authentication middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Check API token authentication if enabled"""
    if server_config and server_config.get('auth_enabled', False):
        # Skip auth for root endpoint, dashboard routes, favicon, and browser metadata
        if (request.url.path == "/" or
            request.url.path.startswith("/dashboard") or
            request.url.path == "/favicon.ico" or
            request.url.path.startswith("/.well-known/")):
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

        # First check global tokens (for backward compatibility)
        allowed_tokens = server_config.get('auth_tokens', [])
        if token in allowed_tokens:
            # Store global token info in request state
            request.state.user_id = None
            request.state.token_id = None
            request.state.is_global_token = True
            request.state.is_admin = True  # Global tokens have admin access
        else:
            # Check user API tokens
            from aisbf.database import get_database
            db = get_database()
            user_auth = db.authenticate_user_token(token)

            if user_auth:
                # Store user token info in request state
                request.state.user_id = user_auth['user_id']
                request.state.token_id = user_auth['token_id']
                request.state.is_global_token = False
                # Store user role - admin users get full access
                request.state.is_admin = (user_auth.get('role') == 'admin')

                # Record token usage for analytics
                # We'll do this asynchronously to avoid blocking the request
                import asyncio
                asyncio.create_task(record_token_usage_async(user_auth['user_id'], user_auth['token_id']))
            else:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Invalid authentication token"}
                )
    else:
        # Auth not enabled, set default state
        request.state.user_id = None
        request.state.token_id = None
        request.state.is_global_token = False

    response = await call_next(request)
    return response

async def record_token_usage_async(user_id: int, token_id: int):
    """Asynchronously record token usage"""
    try:
        from aisbf.database import get_database
        db = get_database()
        # Record with dummy values for now - will be updated when we know the actual usage
        db.record_user_token_usage(user_id, token_id, '', '', 0)
    except Exception as e:
        logger.warning(f"Failed to record token usage: {e}")

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
    
    # Convert FormData to plain dict for JSON serialization
    body_data = None
    if hasattr(exc, 'body'):
        if isinstance(exc.body, dict):
            body_data = exc.body
        elif hasattr(exc.body, '_dict'):
            body_data = exc.body._dict
        elif hasattr(exc.body, 'items'):
            body_data = dict(exc.body.items())
        else:
            body_data = str(exc.body)
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": body_data}
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
@app.get("/dashboard/analytics", response_class=HTMLResponse)
async def dashboard_analytics(
    request: Request,
    time_range: str = Query("24h"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    provider_filter: Optional[str] = Query(None),
    model_filter: Optional[str] = Query(None),
    rotation_filter: Optional[str] = Query(None),
    autoselect_filter: Optional[str] = Query(None),
    user_filter: Optional[int] = Query(None)
):
    """Token usage analytics dashboard"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.analytics import get_analytics
    from aisbf.database import get_database
    
    # Get analytics and database
    db = get_database()
    analytics = get_analytics(db)
    
    # Parse date range
    from_datetime = None
    to_datetime = None
    
    if from_date:
        try:
            from_datetime = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    if to_date:
        try:
            to_datetime = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    # If custom date range is provided, use custom mode
    if from_datetime and to_datetime:
        time_range = 'custom'
    
    # Get all users for filter dropdown
    all_users = db.get_users() if db else []
    
    # Get available providers, models, rotations, and autoselects for filter dropdowns
    available_providers = list(config.providers.keys()) if config else []
    available_rotations = list(config.rotations.keys()) if config else []
    available_autoselects = list(config.autoselect.keys()) if config else []
    
    # Get models from providers
    available_models = []
    if config and hasattr(config, 'providers'):
        for provider_id, provider_config in config.providers.items():
            if hasattr(provider_config, 'models') and provider_config.models:
                for model in provider_config.models:
                    available_models.append(f"{provider_id}/{model.name}")
    
    # Get provider statistics (with optional filter)
    if provider_filter:
        provider_stats = [analytics.get_provider_stats(provider_filter, from_datetime, to_datetime)]
    else:
        provider_stats = analytics.get_all_providers_stats(from_datetime, to_datetime)
    
    # Get token usage over time (with optional filters)
    token_over_time = analytics.get_token_usage_over_time(
        provider_id=provider_filter,
        time_range=time_range,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        user_filter=user_filter
    )
    
    # Get model performance (with optional filters)
    model_performance = analytics.get_model_performance(
        provider_filter=provider_filter,
        model_filter=model_filter,
        rotation_filter=rotation_filter,
        autoselect_filter=autoselect_filter,
        user_filter=user_filter
    )
    
    # Get cost overview
    cost_overview = analytics.get_cost_overview(from_datetime, to_datetime)
    
    # Get optimization recommendations
    recommendations = analytics.get_optimization_recommendations()
    
    # Get date range usage summary
    date_range_usage = None
    if from_datetime or to_datetime:
        start = from_datetime or (datetime.now() - timedelta(days=1))
        end = to_datetime or datetime.now()
        date_range_usage = analytics.get_token_usage_by_date_range(provider_filter, start, end)
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/analytics.html",
        context={
        "request": request,
        "session": request.session,
        "provider_stats": provider_stats,
        "token_over_time": json.dumps(token_over_time),
        "model_performance": model_performance,
        "cost_overview": cost_overview,
        "recommendations": recommendations,
        "selected_time_range": time_range,
        "from_date": from_date,
        "to_date": to_date,
        "date_range_usage": date_range_usage,
        "available_providers": available_providers,
        "available_models": available_models,
        "available_rotations": available_rotations,
        "available_autoselects": available_autoselects,
        "available_users": all_users,
        "selected_provider": provider_filter,
        "selected_model": model_filter,
        "selected_rotation": rotation_filter,
        "selected_autoselect": autoselect_filter,
        "selected_user": user_filter
    }
    )

@app.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page(request: Request):
    """Show dashboard login page"""
    import logging
    from jinja2 import Environment, FileSystemLoader, DictLoader

    logger = logging.getLogger(__name__)
    try:
        # Create a completely fresh Jinja2 environment to avoid any caching issues
        env = Environment(loader=FileSystemLoader("templates"), auto_reload=False)

        # Add the required globals
        env.globals['url_for'] = url_for
        env.globals['get_base_url'] = get_base_url

        # Check if signup is enabled
        signup_enabled = False
        if config and hasattr(config, 'aisbf') and config.aisbf:
            signup_enabled = getattr(config.aisbf.signup, 'enabled', False) if config.aisbf.signup else False

        # Get and render template
        template = env.get_template("dashboard/login.html")
        html_content = template.render(request=request, signup_enabled=signup_enabled)

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering login page: {e}", exc_info=True)
        raise

@app.post("/dashboard/login")
async def dashboard_login(request: Request, username: str = Form(...), password: str = Form(...), remember_me: bool = Form(False)):
    """Handle dashboard login"""
    from aisbf.database import get_database

    # Hash the submitted password
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    # Try database authentication first
    db = get_database()
    user = db.authenticate_user(username, password_hash)

    if user:
        # Database user authenticated - check if email is verified
        if not user['email_verified']:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "error": "Please verify your email address before logging in"}
            )

        request.session['logged_in'] = True
        request.session['username'] = username
        request.session['role'] = user['role']
        request.session['user_id'] = user['id']
        request.session['remember_me'] = remember_me
        if remember_me:
            # Set session to expire in 30 days for remember me
            request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
        else:
            # For non-remember-me sessions, set expiry to 2 weeks (default session length)
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    # Fallback to config admin
    dashboard_config = server_config.get('dashboard_config', {}) if server_config else {}
    stored_username = dashboard_config.get('username', 'admin')
    stored_password_hash = dashboard_config.get('password', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918')

    if username == stored_username and password_hash == stored_password_hash:
        request.session['logged_in'] = True
        request.session['username'] = username
        request.session['role'] = 'admin'
        request.session['user_id'] = None  # Config admin has no user_id
        request.session['remember_me'] = remember_me
        if remember_me:
            # Set session to expire in 30 days for remember me
            request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
        else:
            # For non-remember-me sessions, set expiry to 2 weeks (default session length)
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    # Check if signup is enabled
    signup_enabled = False
    if config and hasattr(config, 'aisbf') and config.aisbf:
        signup_enabled = getattr(config.aisbf.signup, 'enabled', False) if config.aisbf.signup else False

    return templates.TemplateResponse(
        request=request,
        name="dashboard/login.html",
        context={"request": request, "error": "Invalid credentials", "signup_enabled": signup_enabled}
    )


@app.get("/dashboard/signup", response_class=HTMLResponse)
async def dashboard_signup_page(request: Request):
    """Show dashboard signup page"""
    import logging

    logger = logging.getLogger(__name__)
    try:
        # Check if signup is enabled
        signup_enabled = False
        if config and hasattr(config, 'aisbf') and config.aisbf:
            signup_enabled = getattr(config.aisbf.signup, 'enabled', False) if config.aisbf.signup else False

        if not signup_enabled:
            return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

        # Create a completely fresh Jinja2 environment to avoid any caching issues
        env = Environment(loader=FileSystemLoader("templates"), auto_reload=False)

        # Add the required globals
        env.globals['url_for'] = url_for
        env.globals['get_base_url'] = get_base_url

        # Get and render template
        template = env.get_template("dashboard/signup.html")
        html_content = template.render(request=request)

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering signup page: {e}", exc_info=True)
        raise


@app.post("/dashboard/signup")
async def dashboard_signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle user signup"""
    from aisbf.database import get_database
    from aisbf.email_utils import hash_password, generate_verification_token, send_verification_email
    import logging

    logger = logging.getLogger(__name__)

    # Check if signup is enabled
    signup_enabled = False
    if config and hasattr(config, 'aisbf') and config.aisbf:
        signup_enabled = getattr(config.aisbf.signup, 'enabled', False) if config.aisbf.signup else False

    if not signup_enabled:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Passwords do not match"}
        )

    # Validate password strength (minimum 8 characters)
    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Password must be at least 8 characters long"}
        )

    # Validate email format
    import re
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Invalid email address"}
        )

    try:
        db = get_database()

        # Check if user already exists
        existing_user = db.get_user_by_email(email)
        if existing_user:
            if existing_user['email_verified']:
                return templates.TemplateResponse(
                    request=request,
                    name="dashboard/signup.html",
                    context={"request": request, "error": "An account with this email already exists"}
                )
            else:
                # Resend verification email for unverified user
                verification_token = generate_verification_token()
                db.set_verification_token(email, verification_token)

                # Send verification email
                try:
                    base_url = get_base_url(request)
                    verification_url = f"{base_url}/dashboard/verify-email?token={verification_token}&email={email}"
                    send_verification_email(email, verification_url, config.aisbf.smtp if config.aisbf.smtp else None)
                except Exception as e:
                    logger.error(f"Failed to send verification email: {e}")

                return templates.TemplateResponse(
                    request=request,
                    name="dashboard/signup.html",
                    context={"request": request, "message": "Account already exists but not verified. A new verification email has been sent."}
                )

        # Create new user
        password_hash = hash_password(password)
        verification_token = generate_verification_token()

        user_id = db.create_user(email, password_hash, verification_token)

        # Send verification email
        try:
            base_url = get_base_url(request)
            verification_url = f"{base_url}/dashboard/verify-email?token={verification_token}&email={email}"
            send_verification_email(email, verification_url, config.aisbf.smtp if config.aisbf.smtp else None)

            return templates.TemplateResponse(
                request=request,
                name="dashboard/signup.html",
                context={"request": request, "message": "Account created successfully! Please check your email to verify your account."}
            )
        except Exception as e:
            logger.error(f"Failed to send verification email: {e}")
            # Still create user but inform them about email issue
            return templates.TemplateResponse(
                request=request,
                name="dashboard/signup.html",
                context={"request": request, "message": "Account created successfully! However, there was an issue sending the verification email. Please contact an administrator."}
            )

    except Exception as e:
        logger.error(f"Error during signup: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "An error occurred during signup. Please try again."}
        )


@app.get("/dashboard/verify-email")
async def verify_email(request: Request, token: str, email: str):
    """Handle email verification"""
    from aisbf.database import get_database
    import logging

    logger = logging.getLogger(__name__)

    try:
        db = get_database()

        # Verify the token
        if db.verify_email_token(email, token):
            # Token is valid, mark email as verified
            db.verify_email(email)

            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "message": "Email verified successfully! You can now log in."}
            )
        else:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "error": "Invalid or expired verification token"}
            )

    except Exception as e:
        logger.error(f"Error during email verification: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={"request": request, "error": "An error occurred during email verification"}
        )

@app.get("/dashboard/logout")
async def dashboard_logout(request: Request):
    """Handle dashboard logout"""
    request.session.clear()
    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

def require_dashboard_auth(request: Request):
    """Check if user is logged in to dashboard"""
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    # Check if session has expired
    expires_at = request.session.get('expires_at')
    if expires_at and int(time.time()) > expires_at:
        # Session expired
        request.session.clear()
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    # Extend session expiry for remember me users on each request (sliding expiration)
    if request.session.get('remember_me'):
        # Refresh expiry to 30 days from now for remember me
        request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
    elif expires_at:
        # For non-remember-me sessions, refresh to 2 weeks from now (sliding expiration)
        request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
    
    return None

def require_admin(request: Request):
    """Check if user is admin"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    if request.session.get('role') != 'admin':
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)
    return None

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    """Dashboard overview page"""
    # Clear template cache to prevent unhashable dict errors
    templates.env.cache.clear()
    
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    if request.session.get('role') == 'admin':
        # Admin dashboard
        return templates.TemplateResponse(
            request=request,
            name="dashboard/index.html",
            context={
                "request": request,
                "session": request.session,
                "providers_count": len(config.providers) if config else 0,
                "rotations_count": len(config.rotations) if config else 0,
                "autoselect_count": len(config.autoselect) if config else 0,
                "server_config": server_config or {}
            }
        )
    else:
        # User dashboard - show user stats
        from aisbf.database import get_database
        db = get_database()
        user_id = request.session.get('user_id')
        
        # Get user statistics
        usage_stats = {
            'total_tokens': 0,
            'requests_today': 0
        }
        
        if user_id:
            # Get token usage for this user
            token_usage = db.get_user_token_usage(user_id)
            usage_stats['total_tokens'] = sum(row['token_count'] for row in token_usage)
            
            # Count requests today
            from datetime import datetime, timedelta
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            usage_stats['requests_today'] = len([
                row for row in token_usage
                if datetime.fromisoformat(row['timestamp']) >= today
            ])
            
            # Get user config counts
            providers_count = len(db.get_user_providers(user_id))
            rotations_count = len(db.get_user_rotations(user_id))
            autoselects_count = len(db.get_user_autoselects(user_id))
            
            # Get recent activity (last 10)
            recent_activity = token_usage[-10:] if token_usage else []
        else:
            providers_count = 0
            rotations_count = 0
            autoselects_count = 0
            recent_activity = []
        
        return templates.TemplateResponse(
        request=request,
        name="dashboard/user_index.html",
        context={
            "request": request,
            "session": request.session,
            "usage_stats": usage_stats,
            "providers_count": providers_count,
            "rotations_count": rotations_count,
            "autoselects_count": autoselects_count,
            "recent_activity": recent_activity
        }
    )

@app.get("/dashboard/providers", response_class=HTMLResponse)
async def dashboard_providers(request: Request):
    """Edit providers configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    if is_config_admin:
        # Config admin: load from JSON files
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
    else:
        # Database user: load from database
        from aisbf.database import get_database
        db = get_database()
        user_providers = db.get_user_providers(current_user_id)
        
        # Convert to the format expected by the frontend
        providers_data = {}
        for provider in user_providers:
            providers_data[provider['provider_id']] = provider['config']
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/providers.html",
        context={
        "request": request,
        "session": request.session,
        "providers_json": json.dumps(providers_data),
        "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
    }
    )

async def _auto_detect_provider_models(provider_key: str, provider: dict) -> list:
    """
    Auto-detect models from a provider's API endpoint.
    
    Tries to fetch models from the provider's /v1/models or /models endpoint.
    For Kilo providers, uses OAuth2 authentication if available.
    
    Args:
        provider_key: Provider identifier (e.g., 'kilo', 'my-openai-provider')
        provider: Provider configuration dict
        
    Returns:
        List of model dicts, or empty list if detection fails
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        endpoint = provider.get('endpoint', '')
        if not endpoint:
            logger.debug(f"No endpoint for provider '{provider_key}', skipping auto-detection")
            return []
        
        provider_type = provider.get('type', 'openai')
        api_key = provider.get('api_key', '')
        
        # Skip if API key is a placeholder
        if api_key and api_key.startswith('YOUR_'):
            api_key = ''
        
        # Check if this is a Kilo provider (by type or by endpoint URL)
        is_kilo_provider = provider_type in ('kilo', 'kilocode')
        if not is_kilo_provider:
            # Also check endpoint URL for Kilo domains
            kilo_domains = ['kilocode.ai', 'api.kilo.ai', 'kilo.ai']
            for domain in kilo_domains:
                if domain in endpoint:
                    is_kilo_provider = True
                    break
        
        # For Kilo providers, try to get OAuth2 token
        if is_kilo_provider:
            from aisbf.auth.kilo import KiloOAuth2
            kilo_config = provider.get('kilo_config', {})
            credentials_file = kilo_config.get('credentials_file', '~/.kilo_credentials.json')
            oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=endpoint)
            token = oauth2.get_valid_token()
            if token:
                api_key = token
                logger.info(f"Using OAuth2 token for Kilo provider '{provider_key}'")
            else:
                logger.warning(f"No OAuth2 token available for Kilo provider '{provider_key}', please authenticate first")
                return []
        
        # Skip if no authentication available
        if not api_key:
            logger.debug(f"No API key or token for provider '{provider_key}', skipping auto-detection")
            return []
        
        # Build models URL - try multiple paths
        models_url = None
        response_data = None
        
        for path in ['/v1/models', '/models']:
            test_url = endpoint.rstrip('/') + path
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    headers = {'Authorization': f'Bearer {api_key}'}
                    response = await client.get(test_url, headers=headers)
                    
                    if response.status_code == 200:
                        models_url = test_url
                        response_data = response.json()
                        break
                    elif response.status_code == 401:
                        logger.debug(f"Authentication failed for {test_url}")
                    else:
                        logger.debug(f"Got status {response.status_code} from {test_url}")
            except Exception as e:
                logger.debug(f"Error fetching {test_url}: {e}")
                continue
        
        if not models_url or not response_data:
            logger.debug(f"Could not reach models endpoint for provider '{provider_key}'")
            return []
        
        # Parse response - handle both OpenAI format {data: [...]} and array format
        models_list = response_data.get('data', response_data) if isinstance(response_data, dict) else response_data
        if not isinstance(models_list, list):
            logger.debug(f"Unexpected models response format for provider '{provider_key}'")
            return []
        
        # Convert to our model format
        detected_models = []
        for model_data in models_list:
            if isinstance(model_data, str):
                # Simple string model ID
                detected_models.append({
                    'name': model_data,
                    'rate_limit': 0,
                    'max_request_tokens': 100000,
                    'context_size': 100000
                })
            elif isinstance(model_data, dict):
                # Dict with id/name
                model_id = model_data.get('id', model_data.get('model', ''))
                if not model_id:
                    continue
                
                # Extract context size
                context_size = (
                    model_data.get('context_window') or
                    model_data.get('context_length') or
                    model_data.get('max_input_tokens')
                )
                
                detected_models.append({
                    'name': model_id,
                    'rate_limit': 0,
                    'max_request_tokens': int(context_size) if context_size else 100000,
                    'context_size': int(context_size) if context_size else 100000
                })
        
        logger.info(f"Auto-detected {len(detected_models)} models for provider '{provider_key}' from {models_url}")
        return detected_models
        
    except Exception as e:
        logger.warning(f"Failed to auto-detect models for provider '{provider_key}': {e}")
        return []


@app.post("/dashboard/providers")
async def dashboard_providers_save(request: Request, config: str = Form(...)):
    """Save providers configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
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
        
        if is_config_admin:
            # Config admin: save to JSON files
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
        else:
            # Database user: save to database
            from aisbf.database import get_database
            db = get_database()
            
            # Save each provider to database
            for provider_key, provider_config in providers_data.items():
                db.save_user_provider(current_user_id, provider_key, provider_config)
            
            logger.info(f"Saved {len(providers_data)} provider(s) to database for user {current_user_id}")
        
        success_msg = "Configuration saved successfully! Restart server for changes to take effect."
        
        return templates.TemplateResponse(
        request=request,
        name="dashboard/providers.html",
        context={
            "request": request,
            "session": request.session,
            "providers_json": json.dumps(providers_data),
            "success": success_msg
        }
    )
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
        
        return templates.TemplateResponse(
        request=request,
        name="dashboard/providers.html",
        context={
            "request": request,
            "session": request.session,
            "providers_json": json.dumps(providers_data),
            "error": f"Invalid JSON: {str(e)}"
        }
    )

@app.post("/dashboard/providers/get-models")
async def dashboard_providers_get_models(request: Request):
    """Fetch models from provider API"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Parse request body
        body = await request.json()
        provider_key = body.get('provider_key')
        
        if not provider_key:
            return JSONResponse({
                "success": False,
                "error": "provider_key is required"
            }, status_code=400)
        
        # Check if provider exists in config
        if not config or provider_key not in config.providers:
            return JSONResponse({
                "success": False,
                "error": f"Provider '{provider_key}' not found in configuration"
            }, status_code=404)
        
        # Get provider handler
        from aisbf.providers import get_provider_handler
        
        provider_config = config.providers[provider_key]
        api_key = provider_config.api_key if hasattr(provider_config, 'api_key') else None
        
        handler = get_provider_handler(provider_key, api_key)
        
        # Fetch models from provider
        models_result = await handler.get_models()
        
        # Handle pending authorization status
        if isinstance(models_result, dict) and models_result.get("status") == "pending_authorization":
            return JSONResponse({
                "success": False,
                "authorization_required": True,
                "authorization_url": models_result.get("verification_url"),
                "device_code": models_result.get("code"),
                "expires_in": models_result.get("expires_in"),
                "poll_interval": models_result.get("poll_interval"),
                "message": f"Please visit {models_result.get('verification_url')} and enter code: {models_result.get('code')}"
            }, status_code=401)
        
        models = models_result
        
        # Convert Model objects to dicts with all available fields
        models_data = []
        for model in models:
            model_dict = {
                "id": model.id,
                "name": model.name,
                "provider_id": model.provider_id
            }
            
            # Add all optional fields if present
            optional_fields = [
                'weight', 'rate_limit', 'max_request_tokens',
                'rate_limit_TPM', 'rate_limit_TPH', 'rate_limit_TPD',
                'context_size', 'context_length', 'condense_context', 'condense_method',
                'error_cooldown', 'description', 'architecture', 'pricing',
                'top_provider', 'supported_parameters', 'default_parameters'
            ]
            
            for field in optional_fields:
                if hasattr(model, field):
                    value = getattr(model, field)
                    if value is not None:
                        model_dict[field] = value
            
            models_data.append(model_dict)
        
        return JSONResponse({
            "success": True,
            "models": models_data
        })
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching models for provider: {str(e)}", exc_info=True)
        
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

@app.get("/dashboard/rotations", response_class=HTMLResponse)
async def dashboard_rotations(request: Request):
    """Edit rotations configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    if is_config_admin:
        # Config admin: load from JSON files
        config_path = Path.home() / '.aisbf' / 'rotations.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'rotations.json'
        
        with open(config_path) as f:
            rotations_data = json.load(f)
    else:
        # Database user: load from database
        from aisbf.database import get_database
        db = get_database()
        user_rotations = db.get_user_rotations(current_user_id)
        
        # Convert to the format expected by the frontend
        rotations_data = {"rotations": {}, "notifyerrors": False}
        for rotation in user_rotations:
            rotations_data["rotations"][rotation['rotation_id']] = rotation['config']
    
    # Get available providers
    available_providers = list(config.providers.keys()) if config else []
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/rotations.html",
        context={
        "request": request,
        "session": request.session,
        "rotations_json": json.dumps(rotations_data),
        "available_providers": json.dumps(available_providers),
        "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
    }
    )

@app.post("/dashboard/rotations")
async def dashboard_rotations_save(request: Request, config: str = Form(...)):
    """Save rotations configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
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
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'rotations.json'
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(rotations_data, f, indent=2)
        else:
            # Database user: save to database
            from aisbf.database import get_database
            db = get_database()
            
            # Save each rotation to database
            rotations = rotations_data.get('rotations', {})
            for rotation_key, rotation_config in rotations.items():
                db.save_user_rotation(current_user_id, rotation_key, rotation_config)
            
            logger.info(f"Saved {len(rotations)} rotation(s) to database for user {current_user_id}")
        
        # Get global config safely
        from aisbf.config import config as global_config
        available_providers = list(global_config.providers.keys()) if global_config else []
        
        return templates.TemplateResponse(
            request=request,
            name="dashboard/rotations.html",
            context={
                "request": request,
                "session": request.session,
                "rotations_json": json.dumps(rotations_data),
                "available_providers": json.dumps(available_providers),
                "success": "Configuration saved successfully! Restart server for changes to take effect."
            }
        )
    except json.JSONDecodeError as e:
        # Reload current config on error
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if is_config_admin:
            config_path = Path.home() / '.aisbf' / 'rotations.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'rotations.json'
            with open(config_path) as f:
                rotations_data = json.load(f)
        else:
            from aisbf.database import get_database
            db = get_database()
            user_rotations = db.get_user_rotations(current_user_id)
            rotations_data = {"rotations": {}, "notifyerrors": False}
            for rotation in user_rotations:
                rotations_data["rotations"][rotation['rotation_id']] = rotation['config']
        
        available_providers = list(config.providers.keys()) if config else []
        
        return templates.TemplateResponse(
        request=request,
        name="dashboard/rotations.html",
        context={
            "request": request,
            "session": request.session,
            "rotations_json": json.dumps(rotations_data),
            "available_providers": json.dumps(available_providers),
            "error": f"Invalid JSON: {str(e)}"
        }
    )

@app.get("/dashboard/autoselect", response_class=HTMLResponse)
async def dashboard_autoselect(request: Request):
    """Edit autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    if is_config_admin:
        # Config admin: load from JSON files
        config_path = Path.home() / '.aisbf' / 'autoselect.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'autoselect.json'
        
        with open(config_path) as f:
            autoselect_data = json.load(f)
    else:
        # Database user: load from database
        from aisbf.database import get_database
        db = get_database()
        user_autoselects = db.get_user_autoselects(current_user_id)
        
        # Convert to the format expected by the frontend
        autoselect_data = {}
        for autoselect in user_autoselects:
            autoselect_data[autoselect['autoselect_id']] = autoselect['config']
    
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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/autoselect.html",
        context={
        "request": request,
        "session": request.session,
        "autoselect_json": json.dumps(autoselect_data),
        "available_rotations": json.dumps(available_rotations),
        "available_models": json.dumps(available_models),
        "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
    }
    )

@app.post("/dashboard/autoselect")
async def dashboard_autoselect_save(request: Request, config: str = Form(...)):
    """Save autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    try:
        autoselect_data = json.loads(config)
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'autoselect.json'
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(autoselect_data, f, indent=2)
        else:
            # Database user: save to database
            from aisbf.database import get_database
            db = get_database()
            
            # Save each autoselect to database
            for autoselect_key, autoselect_config in autoselect_data.items():
                db.save_user_autoselect(current_user_id, autoselect_key, autoselect_config)
            
            logger.info(f"Saved {len(autoselect_data)} autoselect(s) to database for user {current_user_id}")
        
        # Get global config safely
        from aisbf.config import config as global_config
        available_rotations = list(global_config.rotations.keys()) if global_config else []
        
        return templates.TemplateResponse(
            request=request,
            name="dashboard/autoselect.html",
            context={
                "request": request,
                "session": request.session,
                "autoselect_json": json.dumps(autoselect_data),
                "available_rotations": json.dumps(available_rotations),
                "success": "Configuration saved successfully! Restart server for changes to take effect."
            }
        )
    except json.JSONDecodeError as e:
        # Reload current config on error
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if is_config_admin:
            config_path = Path.home() / '.aisbf' / 'autoselect.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'autoselect.json'
            with open(config_path) as f:
                autoselect_data = json.load(f)
        else:
            from aisbf.database import get_database
            db = get_database()
            user_autoselects = db.get_user_autoselects(current_user_id)
            autoselect_data = {}
            for autoselect in user_autoselects:
                autoselect_data[autoselect['autoselect_id']] = autoselect['config']
        
        available_rotations = list(config.rotations.keys()) if config else []
        
        return templates.TemplateResponse(
        request=request,
        name="dashboard/autoselect.html",
        context={
            "request": request,
            "session": request.session,
            "autoselect_json": json.dumps(autoselect_data),
            "available_rotations": json.dumps(available_rotations),
            "error": f"Invalid JSON: {str(e)}"
        }
    )

@app.get("/dashboard/prompts", response_class=HTMLResponse)
async def dashboard_prompts(request: Request):
    """Edit prompt templates"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    user_id = request.session.get('user_id')
    
    # Define available prompts
    prompt_files = [
        {'key': 'condensation_conversational', 'name': 'Condensation - Conversational', 'filename': 'condensation_conversational.md'},
        {'key': 'condensation_semantic', 'name': 'Condensation - Semantic', 'filename': 'condensation_semantic.md'},
        {'key': 'autoselect', 'name': 'Autoselect - Model Selection', 'filename': 'autoselect.md'},
    ]
    
    prompts_data = []
    from aisbf.database import get_database
    db = get_database()
    
    for prompt_file in prompt_files:
        content = None
        
        # Check if regular user has saved override
        if user_id:
            content = db.get_user_prompt(user_id, prompt_file['key'])
        
        # If no user override or admin, load default from filesystem
        if content is None:
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
            else:
                # Add empty prompt if file not found
                content = f'# {prompt_file["name"]}\n\nPrompt template not found. Please add your prompt here.'
        
        prompts_data.append({
            'key': prompt_file['key'],
            'name': prompt_file['name'],
            'filename': prompt_file['filename'],
            'content': content
        })
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/prompts.html",
        context={
        "request": request,
        "session": request.session,
        "prompts": prompt_files,
        "prompts_data": json.dumps(prompts_data),
        "is_admin": is_admin,
        "success": "Prompt saved successfully!" if success else None
    }
    )

@app.post("/dashboard/prompts")
async def dashboard_prompts_save(request: Request, prompt_key: str = Form(...), prompt_content: str = Form(...)):
    """Save prompt template"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    user_id = request.session.get('user_id')
    
    # Map prompt keys to filenames
    prompt_map = {
        'condensation_conversational': 'condensation_conversational.md',
        'condensation_semantic': 'condensation_semantic.md',
        'autoselect': 'autoselect.md',
    }
    
    if prompt_key not in prompt_map:
        return templates.TemplateResponse(
        request=request,
        name="dashboard/prompts.html",
        context={
            "request": request,
            "session": request.session,
            "prompts": [],
            "prompts_data": "[]",
            "error": "Invalid prompt key"
        }
    )
    
    if is_admin:
        # Admin saves to filesystem
        filename = prompt_map[prompt_key]
        config_path = Path.home() / '.aisbf' / filename
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w') as f:
            f.write(prompt_content)
    else:
        # Regular user saves to database
        from aisbf.database import get_database
        db = get_database()
        db.save_user_prompt(user_id, prompt_key, prompt_content)
    
    return RedirectResponse(url=url_for(request, "/dashboard/prompts?success=1"), status_code=303)

@app.post("/dashboard/prompts/reset/{prompt_key}")
async def dashboard_prompts_reset(request: Request, prompt_key: str):
    """Reset prompt to default for user"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)
    
    from aisbf.database import get_database
    db = get_database()
    db.delete_user_prompt(user_id, prompt_key)
    
    return JSONResponse({"success": True})


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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/settings.html",
        context={
        "request": request,
        "session": request.session,
        "config": aisbf_config
    }
    )

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
     database_type: str = Form("sqlite"),
     sqlite_path: str = Form("~/.aisbf/aisbf.db"),
     mysql_host: str = Form("localhost"),
     mysql_port: int = Form(3306),
     mysql_user: str = Form("aisbf"),
     mysql_password: str = Form(""),
     mysql_database: str = Form("aisbf"),
     cache_type: str = Form("file"),
     redis_host: str = Form("localhost"),
     redis_port: int = Form(6379),
     redis_db: int = Form(0),
     redis_password: str = Form(""),
     redis_key_prefix: str = Form("aisbf:"),
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
     tor_socks_host: str = Form("127.0.0.1"),
     signup_enabled: bool = Form(False),
     smtp_server: str = Form(""),
     smtp_port: int = Form(587),
     smtp_username: str = Form(""),
     smtp_password: str = Form(""),
     smtp_use_tls: bool = Form(True),
     smtp_from_address: str = Form("")
 ):
    """Save server settings"""
    auth_check = require_admin(request)
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

    # Update database config
    if 'database' not in aisbf_config:
        aisbf_config['database'] = {}
    aisbf_config['database']['type'] = database_type
    aisbf_config['database']['sqlite_path'] = sqlite_path
    aisbf_config['database']['mysql_host'] = mysql_host
    aisbf_config['database']['mysql_port'] = mysql_port
    aisbf_config['database']['mysql_user'] = mysql_user
    if mysql_password:  # Only update if provided
        aisbf_config['database']['mysql_password'] = mysql_password
    aisbf_config['database']['mysql_database'] = mysql_database

    # Update cache config
    if 'cache' not in aisbf_config:
        aisbf_config['cache'] = {}
    aisbf_config['cache']['type'] = cache_type
    aisbf_config['cache']['redis_host'] = redis_host
    aisbf_config['cache']['redis_port'] = redis_port
    aisbf_config['cache']['redis_db'] = redis_db
    if redis_password:  # Only update if provided
        aisbf_config['cache']['redis_password'] = redis_password
    aisbf_config['cache']['redis_key_prefix'] = redis_key_prefix

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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/settings.html",
        context={
        "request": request,
        "session": request.session,
        "config": aisbf_config,
        "success": "Settings saved successfully! Restart server for changes to take effect."
    }
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard/settings.html",
        context={
        "request": request,
        "session": request.session,
        "config": aisbf_config,
        "success": "Settings saved successfully! Restart server for changes to take effect."
    }
    )

# Admin user management routes
@app.get("/dashboard/users", response_class=HTMLResponse)
async def dashboard_users(request: Request):
    """Admin user management page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = get_database()
    
    # Get all users
    users = db.get_users()
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
        "request": request,
        "session": request.session,
        "users": users
    }
    )

@app.post("/dashboard/users/add")
async def dashboard_users_add(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("user")):
    """Add a new user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = get_database()
    
    # Hash the password
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        # Get current admin username
        admin_username = request.session.get('username', 'admin')
        user_id = db.create_user(username, password_hash, role, admin_username)
        return RedirectResponse(url=url_for(request, "/dashboard/users"), status_code=303)
    except Exception as e:
        users = db.get_users()
        return templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
            "request": request,
            "session": request.session,
            "users": users,
            "error": f"Failed to create user: {str(e)}"
        }
    )

@app.post("/dashboard/users/{user_id}/edit")
async def dashboard_users_edit(request: Request, user_id: int, username: str = Form(...), password: str = Form(""), role: str = Form("user"), is_active: bool = Form(True)):
    """Edit an existing user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = get_database()
    
    try:
        # Update user (only if password is provided)
        if password:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            db.update_user(user_id, username, password_hash, role, is_active)
        else:
            db.update_user(user_id, username, None, role, is_active)
        return RedirectResponse(url=url_for(request, "/dashboard/users"), status_code=303)
    except Exception as e:
        users = db.get_users()
        return templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
            "request": request,
            "session": request.session,
            "users": users,
            "error": f"Failed to update user: {str(e)}"
        }
    )

@app.post("/dashboard/users/{user_id}/toggle")
async def dashboard_users_toggle(request: Request, user_id: int):
    """Toggle user active status"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = get_database()
    
    try:
        users = db.get_users()
        for user in users:
            if user['id'] == user_id:
                new_status = not user['is_active']
                db.update_user(user_id, user['username'], None, user['role'], new_status)
                return JSONResponse({"success": True})
        return JSONResponse({"success": False, "error": "User not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/dashboard/users/{user_id}/delete")
async def dashboard_users_delete(request: Request, user_id: int):
    """Delete a user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = get_database()
    
    try:
        db.delete_user(user_id)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/dashboard/restart")
async def dashboard_restart(request: Request):
    """Reload configuration from disk"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    logger.info("Configuration reload requested from dashboard")

    try:
        # Reload configuration
        from aisbf.config import config
        config.reload()

        # Re-initialize database if config changed
        db_config = config.aisbf.database if config.aisbf and config.aisbf.database else None
        if db_config:
            from aisbf.database import initialize_database
            initialize_database(db_config)

        # Re-initialize cache if config changed
        cache_config = config.aisbf.cache if config.aisbf and config.aisbf.cache else None
        if cache_config:
            from aisbf.cache import initialize_cache
            initialize_cache(cache_config)

        # Re-initialize response cache if config changed
        response_cache_config = config.aisbf.response_cache if config.aisbf and config.aisbf.response_cache else None
        if response_cache_config:
            from aisbf.cache import initialize_response_cache
            initialize_response_cache(response_cache_config.model_dump() if hasattr(response_cache_config, 'model_dump') else response_cache_config)

        logger.info("Configuration reloaded successfully")

        return JSONResponse({"message": "Configuration reloaded successfully. All changes have been applied."})

    except Exception as e:
        logger.error(f"Error reloading configuration: {e}")
        return JSONResponse({"error": f"Failed to reload configuration: {str(e)}"}, status_code=500)

# User-specific configuration management routes
@app.get("/dashboard/user/providers", response_class=HTMLResponse)
async def dashboard_user_providers(request: Request):
    """User provider management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    # Get user-specific providers
    user_providers = db.get_user_providers(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/user_providers.html",
        context={
        "request": request,
        "session": request.session,
        "user_providers_json": json.dumps(user_providers),
        "user_id": user_id
    }
    )

@app.post("/dashboard/user/providers")
async def dashboard_user_providers_save(request: Request, provider_name: str = Form(...), provider_config: str = Form(...)):
    """Save user-specific provider configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    try:
        # Validate JSON
        provider_data = json.loads(provider_config)

        # Save to database
        db.save_user_provider(user_id, provider_name, provider_data)

        return RedirectResponse(url=url_for(request, "/dashboard/user/providers"), status_code=303)
    except json.JSONDecodeError as e:
        # Reload current providers on error
        user_providers = db.get_user_providers(user_id)
        return templates.TemplateResponse(
        request=request,
        name="dashboard/user_providers.html",
        context={
            "request": request,
            "session": request.session,
            "user_providers_json": json.dumps(user_providers),
            "user_id": user_id,
            "error": f"Invalid JSON: {str(e)}"
        }
    )

@app.delete("/dashboard/user/providers/{provider_name}")
async def dashboard_user_providers_delete(request: Request, provider_name: str):
    """Delete user-specific provider configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        db.delete_user_provider(user_id, provider_name)
        return JSONResponse({"message": "Provider deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# User authentication file management routes
def get_user_auth_files_dir(user_id: int) -> Path:
    """Get the directory for user authentication files"""
    auth_files_dir = Path.home() / '.aisbf' / 'user_auth_files' / str(user_id)
    auth_files_dir.mkdir(parents=True, exist_ok=True)
    return auth_files_dir


@app.post("/dashboard/user/providers/{provider_name}/upload")
async def dashboard_user_provider_upload(
    request: Request,
    provider_name: str,
    file_type: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload authentication file for a provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        # Get user auth files directory
        auth_files_dir = get_user_auth_files_dir(user_id)
        
        # Generate unique filename
        import uuid
        file_ext = Path(file.filename).suffix if file.filename else '.json'
        stored_filename = f"{provider_name}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
        file_path = auth_files_dir / stored_filename

        # Save file
        content = await file.read()
        with open(file_path, 'wb') as f:
            f.write(content)

        # Save metadata to database
        file_id = db.save_user_auth_file(
            user_id=user_id,
            provider_id=provider_name,
            file_type=file_type,
            original_filename=file.filename or stored_filename,
            stored_filename=stored_filename,
            file_path=str(file_path),
            file_size=len(content),
            mime_type=file.content_type
        )

        return JSONResponse({
            "message": "File uploaded successfully",
            "file_id": file_id,
            "file_path": str(file_path),
            "stored_filename": stored_filename
        })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/dashboard/user/providers/{provider_name}/files")
async def dashboard_user_provider_files(request: Request, provider_name: str):
    """Get all authentication files for a provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        files = db.get_user_auth_files(user_id, provider_name)
        return JSONResponse({"files": files})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/dashboard/user/providers/{provider_name}/files/{file_type}/download")
async def dashboard_user_provider_file_download(
    request: Request,
    provider_name: str,
    file_type: str
):
    """Download an authentication file"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    from fastapi.responses import FileResponse
    db = get_database()

    try:
        file_info = db.get_user_auth_file(user_id, provider_name, file_type)
        if not file_info:
            return JSONResponse(status_code=404, content={"error": "File not found"})

        file_path = Path(file_info['file_path'])
        if not file_path.exists():
            return JSONResponse(status_code=404, content={"error": "File not found on disk"})

        return FileResponse(
            path=str(file_path),
            filename=file_info['original_filename'],
            media_type=file_info['mime_type'] or 'application/octet-stream'
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/dashboard/user/providers/{provider_name}/files/{file_type}")
async def dashboard_user_provider_file_delete(
    request: Request,
    provider_name: str,
    file_type: str
):
    """Delete an authentication file"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        file_info = db.get_user_auth_file(user_id, provider_name, file_type)
        if file_info:
            # Delete file from disk
            file_path = Path(file_info['file_path'])
            if file_path.exists():
                file_path.unlink()
            
            # Delete from database
            db.delete_user_auth_file(user_id, provider_name, file_type)
        
        return JSONResponse({"message": "File deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Admin authentication file management routes
def get_admin_auth_files_dir() -> Path:
    """Get the directory for admin authentication files"""
    auth_files_dir = Path.home() / '.aisbf' / 'admin_auth_files'
    auth_files_dir.mkdir(parents=True, exist_ok=True)
    return auth_files_dir


@app.post("/dashboard/providers/{provider_name}/upload")
async def dashboard_provider_upload(
    request: Request,
    provider_name: str,
    file_type: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload authentication file for a provider. Config admin saves to files, other users save to database."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        # Read file content
        content = await file.read()

        if is_config_admin:
            # Config admin: save to files
            auth_files_dir = get_admin_auth_files_dir()
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_name}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            logger.info(f"Config admin uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
        else:
            # Database user: save to database
            from aisbf.database import get_database
            db = get_database()

            # Get user auth files directory
            auth_files_dir = get_user_auth_files_dir(current_user_id)
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_name}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            # Save metadata to database
            file_id = db.save_user_auth_file(
                user_id=current_user_id,
                provider_id=provider_name,
                file_type=file_type,
                original_filename=file.filename or stored_filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=len(content),
                mime_type=file.content_type
            )

            logger.info(f"User {current_user_id} uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_id": file_id,
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/dashboard/providers/upload-auth-file")
async def dashboard_provider_upload_form(
    request: Request,
    provider_key: str = Form(...),
    file_type: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload authentication file for a provider (form variant used by frontend)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        # Read file content
        content = await file.read()

        if is_config_admin:
            # Config admin: save to files
            auth_files_dir = get_admin_auth_files_dir()
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_key}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            logger.info(f"Config admin uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
        else:
            # Database user: save to database
            from aisbf.database import get_database
            db = get_database()

            # Get user auth files directory
            auth_files_dir = get_user_auth_files_dir(current_user_id)
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_key}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            # Save metadata to database
            file_id = db.save_user_auth_file(
                user_id=current_user_id,
                provider_id=provider_key,
                file_type=file_type,
                original_filename=file.filename or stored_filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=len(content),
                mime_type=file.content_type
            )

            logger.info(f"User {current_user_id} uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_id": file_id,
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/dashboard/providers/upload-auth-file/chunk")
async def dashboard_provider_upload_chunk(
    request: Request,
    provider_key: str = Form(...),
    file_type: str = Form(...),
    file_name: str = Form(...),
    chunk_number: int = Form(...),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
    file: UploadFile = File(...)
):
    """Chunked file upload endpoint - handles very large files behind proxies."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        import uuid
        import hashlib

        # Generate unique upload ID
        upload_id = hashlib.sha256(f"{current_user_id}:{provider_key}:{file_name}:{total_size}".encode()).hexdigest()[:16]
        file_ext = Path(file_name).suffix if file_name else '.bin'

        # Create temporary upload directory
        temp_dir = Path('/tmp/aisbf_uploads')
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Save chunk
        chunk_path = temp_dir / f"{upload_id}.part{chunk_number}"
        content = await file.read()
        with open(chunk_path, 'wb') as f:
            f.write(content)

        # Check if all chunks are received
        received_chunks = list(temp_dir.glob(f"{upload_id}.part*"))
        if len(received_chunks) == total_chunks:
            # Assemble final file
            import uuid
            stored_filename = f"{provider_key}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"

            if is_config_admin:
                auth_files_dir = get_admin_auth_files_dir()
            else:
                auth_files_dir = get_user_auth_files_dir(current_user_id)

            file_path = auth_files_dir / stored_filename

            # Combine chunks
            with open(file_path, 'wb') as outfile:
                for i in range(1, total_chunks + 1):
                    chunk_path = temp_dir / f"{upload_id}.part{i}"
                    with open(chunk_path, 'rb') as infile:
                        outfile.write(infile.read())
                    chunk_path.unlink()

            # Save metadata to database if not admin
            if not is_config_admin:
                from aisbf.database import get_database
                db = get_database()
                db.save_user_auth_file(
                    user_id=current_user_id,
                    provider_id=provider_key,
                    file_type=file_type,
                    original_filename=file_name,
                    stored_filename=stored_filename,
                    file_path=str(file_path),
                    file_size=total_size,
                    mime_type=file.content_type
                )

            logger.info(f"Upload complete: {file_path} ({total_size} bytes, {total_chunks} chunks)")

            return JSONResponse({
                "success": True,
                "complete": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })

        return JSONResponse({
            "success": True,
            "complete": False,
            "received_chunks": len(received_chunks),
            "total_chunks": total_chunks
        })

    except Exception as e:
        logger.error(f"Chunk upload error: {e}")
        # Cleanup failed upload
        try:
            for chunk_path in temp_dir.glob(f"{upload_id}.part*"):
                chunk_path.unlink()
        except:
            pass
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/dashboard/providers/{provider_name}/files")
async def dashboard_provider_files(request: Request, provider_name: str):
    """Get all authentication files for a global provider (admin only)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    try:
        auth_files_dir = get_admin_auth_files_dir()
        files = []
        
        for file_path in auth_files_dir.glob(f"{provider_name}_*"):
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "filename": file_path.name,
                    "file_path": str(file_path),
                    "file_size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return JSONResponse({"files": files})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/dashboard/providers/{provider_name}/files/{filename}/download")
async def dashboard_provider_file_download(
    request: Request,
    provider_name: str,
    filename: str
):
    """Download an authentication file for a global provider (admin only)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    try:
        auth_files_dir = get_admin_auth_files_dir()
        file_path = auth_files_dir / filename
        
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse(status_code=404, content={"error": "File not found"})
        
        # Security check: ensure file belongs to this provider
        if not filename.startswith(f"{provider_name}_"):
            return JSONResponse(status_code=403, content={"error": "Access denied"})
        
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type='application/octet-stream'
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/dashboard/providers/{provider_name}/files/{filename}")
async def dashboard_provider_file_delete(
    request: Request,
    provider_name: str,
    filename: str
):
    """Delete an authentication file for a global provider (admin only)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    try:
        auth_files_dir = get_admin_auth_files_dir()
        file_path = auth_files_dir / filename
        
        if not file_path.exists():
            return JSONResponse(status_code=404, content={"error": "File not found"})
        
        # Security check: ensure file belongs to this provider
        if not filename.startswith(f"{provider_name}_"):
            return JSONResponse(status_code=403, content={"error": "Access denied"})
        
        file_path.unlink()
        
        return JSONResponse({"message": "File deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# User-specific rotation management routes
@app.get("/dashboard/user/rotations", response_class=HTMLResponse)
async def dashboard_user_rotations(request: Request):
    """User rotation management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    # Get user-specific rotations
    user_rotations = db.get_user_rotations(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/user_rotations.html",
        context={
        "request": request,
        "session": request.session,
        "user_rotations_json": json.dumps(user_rotations),
        "user_id": user_id
    }
    )

@app.post("/dashboard/user/rotations")
async def dashboard_user_rotations_save(request: Request, rotation_name: str = Form(...), rotation_config: str = Form(...)):
    """Save user-specific rotation configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    try:
        # Validate JSON
        rotation_data = json.loads(rotation_config)

        # Save to database
        db.save_user_rotation(user_id, rotation_name, rotation_data)

        return RedirectResponse(url=url_for(request, "/dashboard/user/rotations"), status_code=303)
    except json.JSONDecodeError as e:
        # Reload current rotations on error
        user_rotations = db.get_user_rotations(user_id)
        return templates.TemplateResponse(
        request=request,
        name="dashboard/user_rotations.html",
        context={
            "request": request,
            "session": request.session,
            "user_rotations_json": json.dumps(user_rotations),
            "user_id": user_id,
            "error": f"Invalid JSON: {str(e)}"
        }
    )

@app.delete("/dashboard/user/rotations/{rotation_name}")
async def dashboard_user_rotations_delete(request: Request, rotation_name: str):
    """Delete user-specific rotation configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        db.delete_user_rotation(user_id, rotation_name)
        return JSONResponse({"message": "Rotation deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# User-specific autoselect management routes
@app.get("/dashboard/user/autoselects", response_class=HTMLResponse)
async def dashboard_user_autoselects(request: Request):
    """User autoselect management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    # Get user-specific autoselects
    user_autoselects = db.get_user_autoselects(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/user_autoselects.html",
        context={
        "request": request,
        "session": request.session,
        "user_autoselects_json": json.dumps(user_autoselects),
        "user_id": user_id
    }
    )

@app.post("/dashboard/user/autoselects")
async def dashboard_user_autoselects_save(request: Request, autoselect_name: str = Form(...), autoselect_config: str = Form(...)):
    """Save user-specific autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    try:
        # Validate JSON
        autoselect_data = json.loads(autoselect_config)

        # Save to database
        db.save_user_autoselect(user_id, autoselect_name, autoselect_data)

        return RedirectResponse(url=url_for(request, "/dashboard/user/autoselects"), status_code=303)
    except json.JSONDecodeError as e:
        # Reload current autoselects on error
        user_autoselects = db.get_user_autoselects(user_id)
        return templates.TemplateResponse(
        request=request,
        name="dashboard/user_autoselects.html",
        context={
            "request": request,
            "session": request.session,
            "user_autoselects_json": json.dumps(user_autoselects),
            "user_id": user_id,
            "error": f"Invalid JSON: {str(e)}"
        }
    )

@app.delete("/dashboard/user/autoselects/{autoselect_name}")
async def dashboard_user_autoselects_delete(request: Request, autoselect_name: str):
    """Delete user-specific autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        db.delete_user_autoselect(user_id, autoselect_name)
        return JSONResponse({"message": "Autoselect deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/dashboard/user/reload-config")
async def dashboard_user_reload_config(request: Request):
    """Reload user configuration from database"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    try:
        global _user_handlers_cache
        
        # Clear all cached handler instances for this user
        cache_keys_to_remove = [
            key for key in _user_handlers_cache.keys()
            if key.endswith(f"_{user_id}")
        ]
        
        for key in cache_keys_to_remove:
            del _user_handlers_cache[key]
        
        logger.info(f"Cleared {len(cache_keys_to_remove)} cached handler(s) for user {user_id}")
        
        # Force create new handler instances to verify reload works
        get_user_handler('request', user_id)
        get_user_handler('rotation', user_id)
        get_user_handler('autoselect', user_id)
        
        logger.info(f"User {user_id} configuration reloaded successfully from database")
        
        return JSONResponse({
            "message": "Configuration reloaded successfully. All changes have been applied immediately.",
            "handlers_cleared": len(cache_keys_to_remove)
        })

    except Exception as e:
        logger.error(f"Error reloading user configuration: {e}")
        return JSONResponse({"error": f"Failed to reload configuration: {str(e)}"}, status_code=500)

# User API token management routes
@app.get("/dashboard/user/tokens", response_class=HTMLResponse)
async def dashboard_user_tokens(request: Request):
    """User API token management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    from aisbf.database import get_database
    db = get_database()

    # Get user API tokens
    user_tokens = db.get_user_api_tokens(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/user_tokens.html",
        context={
        "request": request,
        "session": request.session,
        "user_tokens": user_tokens,
        "user_id": user_id
    }
    )

@app.post("/dashboard/user/tokens")
async def dashboard_user_tokens_create(request: Request, description: str = Form("")):
    """Create a new user API token"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    import secrets

    db = get_database()

    # Generate a secure token
    token = secrets.token_urlsafe(32)

    try:
        token_id = db.create_user_api_token(user_id, token, description.strip() or None)
        return JSONResponse({
            "message": "Token created successfully",
            "token": token,
            "token_id": token_id
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/dashboard/user/tokens/{token_id}")
async def dashboard_user_tokens_delete(request: Request, token_id: int):
    """Delete a user API token"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    from aisbf.database import get_database
    db = get_database()

    try:
        db.delete_user_api_token(user_id, token_id)
        return JSONResponse({"message": "Token deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

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

@app.get("/dashboard/response-cache/stats")
async def dashboard_response_cache_stats(request: Request):
    """Get response cache statistics"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.cache import get_response_cache
    
    try:
        cache = get_response_cache()
        stats = cache.get_stats()
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Error getting response cache stats: {e}")
        return JSONResponse({
            'enabled': False,
            'hits': 0,
            'misses': 0,
            'hit_rate': 0.0,
            'size': 0,
            'evictions': 0,
            'backend': 'unknown',
            'error': str(e)
        })

@app.get("/dashboard/rate-limits")
async def dashboard_rate_limits(request: Request):
    """Rate limits dashboard page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/rate_limits.html",
        context={
        "request": request,
        "session": request.session
    }
    )

@app.get("/dashboard/rate-limits/data")
async def dashboard_rate_limits_data(request: Request):
    """Get adaptive rate limit statistics"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.providers import get_all_adaptive_rate_limiters
    
    try:
        limiters = get_all_adaptive_rate_limiters()
        stats = {}
        for provider_id, limiter in limiters.items():
            stats[provider_id] = limiter.get_stats()
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Error getting rate limit stats: {e}")
        return JSONResponse({
            'error': str(e),
            'providers': {}
        })

@app.post("/dashboard/rate-limits/{provider_id}/reset")
async def dashboard_rate_limits_reset(request: Request, provider_id: str):
    """Reset adaptive rate limiter for a specific provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.providers import get_all_adaptive_rate_limiters
    
    try:
        limiters = get_all_adaptive_rate_limiters()
        if provider_id in limiters:
            limiters[provider_id].reset()
            return JSONResponse({'success': True, 'message': f'Rate limiter for {provider_id} reset successfully'})
        else:
            return JSONResponse({'success': False, 'error': f'Provider {provider_id} not found'}, status_code=404)
    except Exception as e:
        logger.error(f"Error resetting rate limiter: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@app.post("/dashboard/response-cache/clear")
async def dashboard_response_cache_clear(request: Request):
    """Clear response cache"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.cache import get_response_cache
    
    try:
        cache = get_response_cache()
        cache.clear()
        return JSONResponse({'success': True, 'message': 'Response cache cleared'})
    except Exception as e:
        logger.error(f"Error clearing response cache: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/docs.html",
        context={
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "Documentation"
    }
    )

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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/docs.html",
        context={
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "About"
    }
    )

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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/docs.html",
        context={
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "License"
    }
    )

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


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    from fastapi.responses import FileResponse
    
    # Try to find favicon in multiple locations
    search_paths = [
        Path(__file__).parent / 'static' / 'extension' / 'icons' / 'icon16.png',
        Path(__file__).parent / 'static' / 'favicon.ico',
        Path.home() / '.local' / 'share' / 'aisbf' / 'static' / 'extension' / 'icons' / 'icon16.png',
    ]
    
    for favicon_path in search_paths:
        if favicon_path.exists():
            return FileResponse(
                path=favicon_path,
                media_type="image/png" if favicon_path.suffix == '.png' else "image/x-icon"
            )
    
    # Return 204 No Content if favicon not found (better than 404)
    from fastapi.responses import Response
    return Response(status_code=204)


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
        # Get user-specific handler
        user_id = getattr(request.state, 'user_id', None)
        handler = get_user_handler('autoselect', user_id)
    
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict)
    
    # PATH 2: Check if it's a rotation (format: rotation/{name})
    if provider_id == "rotation":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        body_dict['model'] = actual_model
        # Get user-specific handler
        user_id = getattr(request.state, 'user_id', None)
        handler = get_user_handler('rotation', user_id)
        return await handler.handle_rotation_request(actual_model, body_dict)
    
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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)

    if body.stream:
        return await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
    else:
        return await handler.handle_chat_completion(request, provider_id, body_dict)

@app.get("/api/models")
async def list_all_models(request: Request):
    """List all available models from all providers (public endpoint)"""
    logger.info("=== LIST ALL MODELS REQUEST ===")

    all_models = []

    # Check authentication for user-specific models
    user_id = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        # Try to authenticate user
        try:
            from aisbf.database import get_database
            db = get_database()
            token = auth_header.split(" ")[1]
            user = db.get_user_by_token(token)
            if user:
                user_id = user.get("id")
                logger.info(f"Authenticated user {user_id} for models request")
        except Exception as e:
            logger.debug(f"Auth check failed for models request: {e}")

    # PATH 1: Add provider models (from local config or cached API results)
    for provider_id, provider_config in config.providers.items():
        try:
            provider_models = await get_provider_models(provider_id, provider_config, user_id=user_id)
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

    # Check authentication for user-specific models
    user_id = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        # Try to authenticate user
        try:
            from aisbf.database import get_database
            db = get_database()
            token = auth_header.split(" ")[1]
            user = db.get_user_by_token(token)
            if user:
                user_id = user.get("id")
                logger.info(f"Authenticated user {user_id} for models request")
        except Exception as e:
            logger.debug(f"Auth check failed for models request: {e}")
    
    # PATH 1: Add provider models (from local config or cached API results)
    for provider_id, provider_config in config.providers.items():
        try:
            provider_models = await get_provider_models(provider_id, provider_config, user_id=user_id)
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


@app.get("/v1/models")
async def v1_list_all_models_alias(request: Request):
    """Alias for /api/v1/models for client compatibility"""
    return await v1_list_all_models(request)


@app.get("/v1/chat/models")
async def v1_chat_models_alias(request: Request):
    """Alias for /api/v1/models for OpenAI client compatibility"""
    return await v1_list_all_models(request)


@app.get("/models")
async def models_root_alias(request: Request):
    """Alias for /api/v1/models for client compatibility"""
    return await v1_list_all_models(request)

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
    
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)

    # Create new form data with updated model
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        if key == 'model':
            updated_form[key] = actual_model
        else:
            updated_form[key] = value

    return await handler.handle_audio_transcription(request, provider_id, updated_form)

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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)
    return await handler.handle_text_to_speech(request, provider_id, body)

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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)
    return await handler.handle_image_generation(request, provider_id, body)

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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)
    return await handler.handle_embeddings(request, provider_id, body)

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
        # Get user-specific handler
        user_id = getattr(request.state, 'user_id', None)
        handler = get_user_handler('rotation', user_id)

        # The rotation handler handles streaming internally and returns
        # a StreamingResponse for streaming requests or a dict for non-streaming
        result = await handler.handle_rotation_request(body.model, body_dict)
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

    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('autoselect', user_id)

    # Check if the model name corresponds to an autoselect configuration
    if body.model not in config.autoselect and (not user_id or body.model not in handler.user_autoselects):
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
            return await handler.handle_autoselect_streaming_request(body.model, body_dict)
        else:
            logger.debug("Handling non-streaming autoselect request")
            result = await handler.handle_autoselect_request(body.model, body_dict)
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

    # Get user-specific handler based on the type
    user_id = getattr(request.state, 'user_id', None)

    # Check if it's an autoselect
    if provider_id in config.autoselect or (user_id and provider_id in get_user_handler('autoselect', user_id).user_autoselects):
        logger.debug("Handling autoselect request")
        handler = get_user_handler('autoselect', user_id)
        try:
            if body.stream:
                logger.debug("Handling streaming autoselect request")
                return await handler.handle_autoselect_streaming_request(provider_id, body_dict)
            else:
                logger.debug("Handling non-streaming autoselect request")
                result = await handler.handle_autoselect_request(provider_id, body_dict)
                logger.debug(f"Autoselect response result: {result}")
                return result
        except Exception as e:
            logger.error(f"Error handling autoselect: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations or (user_id and provider_id in get_user_handler('rotation', user_id).user_rotations):
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation request")
        handler = get_user_handler('rotation', user_id)
        return await handler.handle_rotation_request(provider_id, body_dict)

    # Check if it's a provider
    handler = get_user_handler('request', user_id)
    if provider_id not in config.providers and (not user_id or provider_id not in handler.user_providers):
        logger.error(f"Provider ID '{provider_id}' not found in providers")
        logger.error(f"Available providers: {list(config.providers.keys())}")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")

    logger.info(f"Provider ID '{provider_id}' found in providers")

    provider_config = handler.user_providers.get(provider_id) if user_id and provider_id in handler.user_providers else config.get_provider(provider_id)
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
            return await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
        else:
            logger.debug("Handling non-streaming chat completion")
            result = await handler.handle_chat_completion(request, provider_id, body_dict)
            logger.debug(f"Response result: {result}")
            return result
    except Exception as e:
        logger.error(f"Error handling chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/{provider_id}/models")
async def list_models(request: Request, provider_id: str):
    logger.debug(f"Received list_models request for provider: {provider_id}")
    AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')

    # Get user-specific handler based on the type
    user_id = getattr(request.state, 'user_id', None)

    # Check if it's an autoselect
    if provider_id in config.autoselect or (user_id and provider_id in get_user_handler('autoselect', user_id).user_autoselects):
        logger.debug("Handling autoselect model list request")
        handler = get_user_handler('autoselect', user_id)
        try:
            result = await handler.handle_autoselect_model_list(provider_id)
            if AISBF_DEBUG:
                result_str = str(result)
                if len(result_str) > 1024:
                    result_str = result_str[:1024] + " ... [TRUNCATED, total length: " + str(len(result_str)) + " chars]"
                logger.debug(f"Autoselect models result: {result_str}")
            else:
                model_count = len(result)
                first_models = [m.get('id', m.get('name')) for m in result[:3]]
                preview = f"[{' | '.join(first_models)}" + (f" ... and {model_count - 3} more]" if model_count > 3 else ']')
                logger.debug(f"Autoselect models result: {model_count} models {preview}")
            return result
        except Exception as e:
            logger.error(f"Error handling autoselect model list: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations or (user_id and provider_id in get_user_handler('rotation', user_id).user_rotations):
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation model list request")
        handler = get_user_handler('rotation', user_id)
        return await handler.handle_rotation_model_list(provider_id)

    # Check if it's a provider
    handler = get_user_handler('request', user_id)
    if provider_id not in config.providers and (not user_id or provider_id not in handler.user_providers):
        logger.error(f"Provider ID '{provider_id}' not found in providers")
        logger.error(f"Available providers: {list(config.providers.keys())}")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")

    logger.info(f"Provider ID '{provider_id}' found in providers")

    try:
        logger.debug("Handling model list request")
        result = await handler.handle_model_list(request, provider_id)
        if AISBF_DEBUG:
            result_str = str(result)
            if len(result_str) > 1024:
                result_str = result_str[:1024] + " ... [TRUNCATED, total length: " + str(len(result_str)) + " chars]"
            logger.debug(f"Models result: {result_str}")
        else:
            model_count = len(result)
            first_models = [m.get('id', m.get('name')) for m in result[:3]]
            preview = f"[{' | '.join(first_models)}" + (f" ... and {model_count - 3} more]" if model_count > 3 else ']')
            logger.debug(f"Models result: {model_count} models {preview}")
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
    
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)

    # Create new form data with updated model
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        if key == 'model':
            updated_form[key] = actual_model
        else:
            updated_form[key] = value

    return await handler.handle_audio_transcription(request, provider_id, updated_form)

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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)
    return await handler.handle_text_to_speech(request, provider_id, body)

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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)
    return await handler.handle_image_generation(request, provider_id, body)

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
    # Get user-specific handler
    user_id = getattr(request.state, 'user_id', None)
    handler = get_user_handler('request', user_id)
    return await handler.handle_embeddings(request, provider_id, body)

# Content proxy endpoint
@app.get("/api/proxy/{content_id}")
async def proxy_content(content_id: str):
    """Proxy generated content (images, audio, etc.)"""
    logger.info(f"=== PROXY CONTENT REQUEST ===")
    logger.info(f"Content ID: {content_id}")
    
    try:
        # Get user-specific handler (use global for content proxy as it's shared)
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
            user_id = getattr(request.state, 'user_id', None)
            tools = mcp_server.get_available_tools(auth_level, user_id)
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
                # Get user_id from request state if available
                user_id = getattr(request.state, 'user_id', None)
                result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level, user_id)
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
        user_id = getattr(request.state, 'user_id', None)
        tools = mcp_server.get_available_tools(auth_level, user_id)
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
            # Get user_id from request state if available
            user_id = getattr(request.state, 'user_id', None)
            result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level, user_id)
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
    
    user_id = getattr(request.state, 'user_id', None)
    tools = mcp_server.get_available_tools(auth_level, user_id)
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
        # Get user_id from request state if available
        user_id = getattr(request.state, 'user_id', None)
        result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level, user_id)
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


# User-specific API endpoints
# These endpoints allow authenticated users to access their own configurations
# Admin users can also access other users' configurations

# New username-based endpoints
@app.get("/api/u/{username}/models")
async def user_list_models_by_username(request: Request, username: str):
    """
    List all available models for the specified user.
    
    This includes the user's own providers, rotations, and autoselects.
    Admin users can access any user's configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Returns models from:
    - User-configured providers
    - User-configured rotations  
    - User-configured autoselects
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/{username}/models
    """
    from aisbf.database import get_database
    db = get_database()
    
    # Get target user by username
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(
            status_code=404,
            content={"error": f"User '{username}' not found"}
        )
    
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    
    # Check permissions: only admin, global token, or the user themselves can access
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "You do not have permission to access this user's configurations"}
        )
    
    # For admin/global tokens, return both global and user configurations
    if is_global_token or is_admin:
        # Return global config models plus user-specific models
        all_models = []
        
        # Add global provider models
        for provider_id, provider_config in config.providers.items():
            try:
                provider_models = await get_provider_models(provider_id, provider_config)
                all_models.extend(provider_models)
            except Exception as e:
                logger.warning(f"Error listing models for provider {provider_id}: {e}")
        
        # Add global rotations
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
                    'source': 'global'
                })
            except Exception as e:
                logger.warning(f"Error listing rotation {rotation_id}: {e}")
        
        # Add global autoselects
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
                    'source': 'global'
                })
            except Exception as e:
                logger.warning(f"Error listing autoselect {autoselect_id}: {e}")
        
        # Add user-specific models
        handler = get_user_handler('request', target_user_id)
        for provider_id, provider_config in handler.user_providers.items():
            try:
                if hasattr(provider_config, 'models') and provider_config.models:
                    for model in provider_config.models:
                        model_id = f"{provider_id}/{model.name}"
                        all_models.append({
                            'id': model_id,
                            'object': 'model',
                            'created': int(time.time()),
                            'owned_by': provider_id,
                            'provider': provider_id,
                            'type': 'user_provider',
                            'model_name': model.name,
                            'source': 'user_config'
                        })
            except Exception as e:
                logger.warning(f"Error listing models for user provider {provider_id}: {e}")
        
        rotation_handler = get_user_handler('rotation', target_user_id)
        for rotation_id, rotation_config in rotation_handler.user_rotations.items():
            try:
                all_models.append({
                    'id': f"user-rotation/{rotation_id}",
                    'object': 'model',
                    'created': int(time.time()),
                    'owned_by': 'aisbf-user-rotation',
                    'type': 'user_rotation',
                    'rotation_id': rotation_id,
                    'source': 'user_config'
                })
            except Exception as e:
                logger.warning(f"Error listing user rotation {rotation_id}: {e}")
        
        autoselect_handler = get_user_handler('autoselect', target_user_id)
        for autoselect_id, autoselect_config in autoselect_handler.user_autoselects.items():
            try:
                all_models.append({
                    'id': f"user-autoselect/{autoselect_id}",
                    'object': 'model',
                    'created': int(time.time()),
                    'owned_by': 'aisbf-user-autoselect',
                    'type': 'user_autoselect',
                    'autoselect_id': autoselect_id,
                    'source': 'user_config'
                })
            except Exception as e:
                logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
        
        return {"object": "list", "data": all_models}
    
    # Regular user - only their own configurations
    all_models = []
    
    # Get user-specific handler for providers
    handler = get_user_handler('request', target_user_id)
    
    # Add user providers
    for provider_id, provider_config in handler.user_providers.items():
        try:
            if hasattr(provider_config, 'models') and provider_config.models:
                for model in provider_config.models:
                    model_id = f"{provider_id}/{model.name}"
                    all_models.append({
                        'id': model_id,
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': provider_id,
                        'provider': provider_id,
                        'type': 'user_provider',
                        'model_name': model.name,
                        'context_size': getattr(model, 'context_size', None),
                        'capabilities': getattr(model, 'capabilities', []),
                        'description': getattr(model, 'description', None),
                        'source': 'user_config'
                    })
        except Exception as e:
            logger.warning(f"Error listing models for user provider {provider_id}: {e}")
    
    # Add user rotations
    rotation_handler = get_user_handler('rotation', target_user_id)
    for rotation_id, rotation_config in rotation_handler.user_rotations.items():
        try:
            all_models.append({
                'id': f"user-rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-user-rotation',
                'type': 'user_rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.get('model_name', rotation_id),
                'capabilities': rotation_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    # Add user autoselects
    autoselect_handler = get_user_handler('autoselect', target_user_id)
    for autoselect_id, autoselect_config in autoselect_handler.user_autoselects.items():
        try:
            all_models.append({
                'id': f"user-autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-user-autoselect',
                'type': 'user_autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.get('model_name', autoselect_id),
                'description': autoselect_config.get('description'),
                'capabilities': autoselect_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    return {"object": "list", "data": all_models}


@app.get("/api/user/models")
async def user_list_models(request: Request):
    """
    List all available models for the authenticated user.
    
    This includes the user's own providers, rotations, and autoselects.
    Admin users can also access all users' configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Returns models from:
    - User-configured providers
    - User-configured rotations  
    - User-configured autoselects
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/user/models
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    # Global tokens and admin users can access all configurations
    if is_global_token or is_admin:
        # Return global config models plus user-specific models
        all_models = []
        
        # Add global provider models
        for provider_id, provider_config in config.providers.items():
            try:
                provider_models = await get_provider_models(provider_id, provider_config)
                all_models.extend(provider_models)
            except Exception as e:
                logger.warning(f"Error listing models for provider {provider_id}: {e}")
        
        # Add global rotations
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
                    'source': 'global'
                })
            except Exception as e:
                logger.warning(f"Error listing rotation {rotation_id}: {e}")
        
        # Add global autoselects
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
                    'source': 'global'
                })
            except Exception as e:
                logger.warning(f"Error listing autoselect {autoselect_id}: {e}")
        
        # If not global token, also add user-specific models
        if user_id and not is_global_token:
            handler = get_user_handler('request', user_id)
            for provider_id, provider_config in handler.user_providers.items():
                try:
                    if hasattr(provider_config, 'models') and provider_config.models:
                        for model in provider_config.models:
                            model_id = f"{provider_id}/{model.name}"
                            all_models.append({
                                'id': model_id,
                                'object': 'model',
                                'created': int(time.time()),
                                'owned_by': provider_id,
                                'provider': provider_id,
                                'type': 'user_provider',
                                'model_name': model.name,
                                'source': 'user_config'
                            })
                except Exception as e:
                    logger.warning(f"Error listing models for user provider {provider_id}: {e}")
            
            rotation_handler = get_user_handler('rotation', user_id)
            for rotation_id, rotation_config in rotation_handler.user_rotations.items():
                try:
                    all_models.append({
                        'id': f"user-rotation/{rotation_id}",
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': 'aisbf-user-rotation',
                        'type': 'user_rotation',
                        'rotation_id': rotation_id,
                        'source': 'user_config'
                    })
                except Exception as e:
                    logger.warning(f"Error listing user rotation {rotation_id}: {e}")
            
            autoselect_handler = get_user_handler('autoselect', user_id)
            for autoselect_id, autoselect_config in autoselect_handler.user_autoselects.items():
                try:
                    all_models.append({
                        'id': f"user-autoselect/{autoselect_id}",
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': 'aisbf-user-autoselect',
                        'type': 'user_autoselect',
                        'autoselect_id': autoselect_id,
                        'source': 'user_config'
                    })
                except Exception as e:
                    logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
        
        return {"object": "list", "data": all_models}
    
    # Regular user - only their own configurations
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    all_models = []
    
    # Get user-specific handler for providers
    handler = get_user_handler('request', user_id)
    
    # Add user providers
    for provider_id, provider_config in handler.user_providers.items():
        try:
            if hasattr(provider_config, 'models') and provider_config.models:
                for model in provider_config.models:
                    model_id = f"{provider_id}/{model.name}"
                    all_models.append({
                        'id': model_id,
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': provider_id,
                        'provider': provider_id,
                        'type': 'user_provider',
                        'model_name': model.name,
                        'context_size': getattr(model, 'context_size', None),
                        'capabilities': getattr(model, 'capabilities', []),
                        'description': getattr(model, 'description', None),
                        'source': 'user_config'
                    })
        except Exception as e:
            logger.warning(f"Error listing models for user provider {provider_id}: {e}")
    
    # Add user rotations
    rotation_handler = get_user_handler('rotation', user_id)
    for rotation_id, rotation_config in rotation_handler.user_rotations.items():
        try:
            all_models.append({
                'id': f"user-rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-user-rotation',
                'type': 'user_rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.get('model_name', rotation_id),
                'capabilities': rotation_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    # Add user autoselects
    autoselect_handler = get_user_handler('autoselect', user_id)
    for autoselect_id, autoselect_config in autoselect_handler.user_autoselects.items():
        try:
            all_models.append({
                'id': f"user-autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-user-autoselect',
                'type': 'user_autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.get('model_name', autoselect_id),
                'description': autoselect_config.get('description'),
                'capabilities': autoselect_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    return {"object": "list", "data": all_models}


@app.get("/api/user/providers")
async def user_list_providers(request: Request):
    """
    List all provider configurations for the authenticated user.
    
    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/user/providers
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    # Global tokens and admin users can access all configurations
    if is_global_token or is_admin:
        # Return global providers plus user-specific if user_id exists
        providers_info = {}
        
        # Add global providers
        for provider_id, provider_config in config.providers.items():
            try:
                if hasattr(provider_config, 'model_dump'):
                    config_dict = provider_config.model_dump()
                elif hasattr(provider_config, '__dict__'):
                    config_dict = vars(provider_config)
                else:
                    config_dict = {}
                
                safe_config = {k: v for k, v in config_dict.items() 
                              if k not in ['api_key', 'password', 'secret', 'token']}
                
                providers_info[provider_id] = {
                    'name': getattr(provider_config, 'name', provider_id),
                    'type': getattr(provider_config, 'type', 'unknown'),
                    'endpoint': getattr(provider_config, 'endpoint', None),
                    'models_count': len(getattr(provider_config, 'models', [])),
                    'config': safe_config,
                    'source': 'global'
                }
            except Exception as e:
                logger.warning(f"Error listing global provider {provider_id}: {e}")
        
        # If not global token, also add user-specific providers
        if user_id and not is_global_token:
            handler = get_user_handler('request', user_id)
            for provider_id, provider_config in handler.user_providers.items():
                try:
                    if hasattr(provider_config, 'model_dump'):
                        config_dict = provider_config.model_dump()
                    elif hasattr(provider_config, '__dict__'):
                        config_dict = vars(provider_config)
                    else:
                        config_dict = {}
                    
                    safe_config = {k: v for k, v in config_dict.items() 
                                  if k not in ['api_key', 'password', 'secret', 'token']}
                    
                    providers_info[provider_id] = {
                        'name': getattr(provider_config, 'name', provider_id),
                        'type': getattr(provider_config, 'type', 'unknown'),
                        'endpoint': getattr(provider_config, 'endpoint', None),
                        'models_count': len(getattr(provider_config, 'models', [])),
                        'config': safe_config,
                        'source': 'user_config'
                    }
                except Exception as e:
                    logger.warning(f"Error listing user provider {provider_id}: {e}")
        
        return {"providers": providers_info}
    
    # Regular user - only their own configurations
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    handler = get_user_handler('request', user_id)
    
    providers_info = {}
    for provider_id, provider_config in handler.user_providers.items():
        try:
            # Convert provider config to dict (excluding sensitive info)
            if hasattr(provider_config, 'model_dump'):
                config_dict = provider_config.model_dump()
            elif hasattr(provider_config, '__dict__'):
                config_dict = vars(provider_config)
            else:
                config_dict = {}
            
            # Remove sensitive fields for display
            safe_config = {k: v for k, v in config_dict.items() 
                          if k not in ['api_key', 'password', 'secret', 'token']}
            
            providers_info[provider_id] = {
                'name': getattr(provider_config, 'name', provider_id),
                'type': getattr(provider_config, 'type', 'unknown'),
                'endpoint': getattr(provider_config, 'endpoint', None),
                'models_count': len(getattr(provider_config, 'models', [])),
                'config': safe_config
            }
        except Exception as e:
            logger.warning(f"Error listing user provider {provider_id}: {e}")
    
    return {"providers": providers_info}


@app.get("/api/user/rotations")
async def user_list_rotations(request: Request):
    """
    List all rotation configurations for the authenticated user.
    
    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/user/rotations
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    # Global tokens and admin users can access all configurations
    if is_global_token or is_admin:
        rotations_info = {}
        
        # Add global rotations
        for rotation_id, rotation_config in config.rotations.items():
            try:
                rotations_info[rotation_id] = {
                    "model_name": rotation_config.model_name,
                    "providers": rotation_config.providers,
                    "source": "global"
                }
            except Exception as e:
                logger.warning(f"Error listing global rotation {rotation_id}: {e}")
        
        # If not global token, also add user-specific rotations
        if user_id and not is_global_token:
            handler = get_user_handler('rotation', user_id)
            for rotation_id, rotation_config in handler.user_rotations.items():
                try:
                    rotations_info[rotation_id] = {
                        "model_name": rotation_config.get('model_name', rotation_id),
                        "providers": rotation_config.get('providers', []),
                        "source": "user_config"
                    }
                except Exception as e:
                    logger.warning(f"Error listing user rotation {rotation_id}: {e}")
        
        return {"rotations": rotations_info}
    
    # Regular user - only their own configurations
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    handler = get_user_handler('rotation', user_id)
    
    rotations_info = {}
    for rotation_id, rotation_config in handler.user_rotations.items():
        try:
            rotations_info[rotation_id] = {
                "model_name": rotation_config.get('model_name', rotation_id),
                "providers": rotation_config.get('providers', [])
            }
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    return {"rotations": rotations_info}


@app.get("/api/user/autoselects")
async def user_list_autoselects(request: Request):
    """
    List all autoselect configurations for the authenticated user.
    
    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/user/autoselects
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    # Global tokens and admin users can access all configurations
    if is_global_token or is_admin:
        autoselects_info = {}
        
        # Add global autoselects
        for autoselect_id, autoselect_config in config.autoselect.items():
            try:
                autoselects_info[autoselect_id] = {
                    "model_name": autoselect_config.model_name,
                    "description": autoselect_config.description,
                    "fallback": autoselect_config.fallback,
                    "available_models": [
                        {"model_id": m.model_id, "description": m.description}
                        for m in autoselect_config.available_models
                    ],
                    "source": "global"
                }
            except Exception as e:
                logger.warning(f"Error listing global autoselect {autoselect_id}: {e}")
        
        # If not global token, also add user-specific autoselects
        if user_id and not is_global_token:
            handler = get_user_handler('autoselect', user_id)
            for autoselect_id, autoselect_config in handler.user_autoselects.items():
                try:
                    autoselects_info[autoselect_id] = {
                        "model_name": autoselect_config.get('model_name', autoselect_id),
                        "description": autoselect_config.get('description', ''),
                        "fallback": autoselect_config.get('fallback', ''),
                        "available_models": autoselect_config.get('available_models', []),
                        "source": "user_config"
                    }
                except Exception as e:
                    logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
        
        return {"autoselects": autoselects_info}
    
    # Regular user - only their own configurations
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    handler = get_user_handler('autoselect', user_id)
    
    autoselects_info = {}
    for autoselect_id, autoselect_config in handler.user_autoselects.items():
        try:
            autoselects_info[autoselect_id] = {
                "model_name": autoselect_config.get('model_name', autoselect_id),
                "description": autoselect_config.get('description', ''),
                "fallback": autoselect_config.get('fallback', ''),
                "available_models": autoselect_config.get('available_models', [])
            }
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    return {"autoselects": autoselects_info}


# Username-based user endpoints
@app.get("/api/u/{username}/providers")
async def user_list_providers_by_username(request: Request, username: str):
    """
    List all provider configurations for the specified user.
    
    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/{username}/providers
    """
    from aisbf.database import get_database
    db = get_database()
    
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(
            status_code=404,
            content={"error": f"User '{username}' not found"}
        )
    
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "You do not have permission to access this user's configurations"}
        )
    
    if is_global_token or is_admin:
        providers_info = {}
        
        for provider_id, provider_config in config.providers.items():
            try:
                if hasattr(provider_config, 'model_dump'):
                    config_dict = provider_config.model_dump()
                elif hasattr(provider_config, '__dict__'):
                    config_dict = vars(provider_config)
                else:
                    config_dict = {}
                
                safe_config = {k: v for k, v in config_dict.items()
                              if k not in ['api_key', 'password', 'secret', 'token']}
                
                providers_info[provider_id] = {
                    'name': getattr(provider_config, 'name', provider_id),
                    'type': getattr(provider_config, 'type', 'unknown'),
                    'endpoint': getattr(provider_config, 'endpoint', None),
                    'models_count': len(getattr(provider_config, 'models', [])),
                    'config': safe_config,
                    'source': 'global'
                }
            except Exception as e:
                logger.warning(f"Error listing global provider {provider_id}: {e}")
        
        if not is_global_token and target_user_id:
            handler = get_user_handler('request', target_user_id)
            for provider_id, provider_config in handler.user_providers.items():
                try:
                    if hasattr(provider_config, 'model_dump'):
                        config_dict = provider_config.model_dump()
                    elif hasattr(provider_config, '__dict__'):
                        config_dict = vars(provider_config)
                    else:
                        config_dict = {}
                    
                    safe_config = {k: v for k, v in config_dict.items()
                                  if k not in ['api_key', 'password', 'secret', 'token']}
                    
                    providers_info[provider_id] = {
                        'name': getattr(provider_config, 'name', provider_id),
                        'type': getattr(provider_config, 'type', 'unknown'),
                        'endpoint': getattr(provider_config, 'endpoint', None),
                        'models_count': len(getattr(provider_config, 'models', [])),
                        'config': safe_config,
                        'source': 'user_config'
                    }
                except Exception as e:
                    logger.warning(f"Error listing user provider {provider_id}: {e}")
        
        return {"providers": providers_info}
    
    if not target_user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    handler = get_user_handler('request', target_user_id)
    
    providers_info = {}
    for provider_id, provider_config in handler.user_providers.items():
        try:
            if hasattr(provider_config, 'model_dump'):
                config_dict = provider_config.model_dump()
            elif hasattr(provider_config, '__dict__'):
                config_dict = vars(provider_config)
            else:
                config_dict = {}
            
            safe_config = {k: v for k, v in config_dict.items()
                          if k not in ['api_key', 'password', 'secret', 'token']}
            
            providers_info[provider_id] = {
                'name': getattr(provider_config, 'name', provider_id),
                'type': getattr(provider_config, 'type', 'unknown'),
                'endpoint': getattr(provider_config, 'endpoint', None),
                'models_count': len(getattr(provider_config, 'models', [])),
                'config': safe_config
            }
        except Exception as e:
            logger.warning(f"Error listing user provider {provider_id}: {e}")
    
    return {"providers": providers_info}


@app.get("/api/u/{username}/rotations")
async def user_list_rotations_by_username(request: Request, username: str):
    """
    List all rotation configurations for the specified user.
    
    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/{username}/rotations
    """
    from aisbf.database import get_database
    db = get_database()
    
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(
            status_code=404,
            content={"error": f"User '{username}' not found"}
        )
    
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "You do not have permission to access this user's configurations"}
        )
    
    if is_global_token or is_admin:
        rotations_info = {}
        
        for rotation_id, rotation_config in config.rotations.items():
            try:
                rotations_info[rotation_id] = {
                    "model_name": rotation_config.model_name,
                    "providers": rotation_config.providers,
                    "source": "global"
                }
            except Exception as e:
                logger.warning(f"Error listing global rotation {rotation_id}: {e}")
        
        if not is_global_token and target_user_id:
            handler = get_user_handler('rotation', target_user_id)
            for rotation_id, rotation_config in handler.user_rotations.items():
                try:
                    rotations_info[rotation_id] = {
                        "model_name": rotation_config.get('model_name', rotation_id),
                        "providers": rotation_config.get('providers', []),
                        "source": "user_config"
                    }
                except Exception as e:
                    logger.warning(f"Error listing user rotation {rotation_id}: {e}")
        
        return {"rotations": rotations_info}
    
    if not target_user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    handler = get_user_handler('rotation', target_user_id)
    
    rotations_info = {}
    for rotation_id, rotation_config in handler.user_rotations.items():
        try:
            rotations_info[rotation_id] = {
                "model_name": rotation_config.get('model_name', rotation_id),
                "providers": rotation_config.get('providers', [])
            }
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    return {"rotations": rotations_info}


@app.get("/api/u/{username}/autoselects")
async def user_list_autoselects_by_username(request: Request, username: str):
    """
    List all autoselect configurations for the specified user.
    
    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/{username}/autoselects
    """
    from aisbf.database import get_database
    db = get_database()
    
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(
            status_code=404,
            content={"error": f"User '{username}' not found"}
        )
    
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "You do not have permission to access this user's configurations"}
        )
    
    if is_global_token or is_admin:
        autoselects_info = {}
        
        for autoselect_id, autoselect_config in config.autoselect.items():
            try:
                autoselects_info[autoselect_id] = {
                    "model_name": autoselect_config.model_name,
                    "description": autoselect_config.description,
                    "fallback": autoselect_config.fallback,
                    "available_models": [
                        {"model_id": m.model_id, "description": m.description}
                        for m in autoselect_config.available_models
                    ],
                    "source": "global"
                }
            except Exception as e:
                logger.warning(f"Error listing global autoselect {autoselect_id}: {e}")
        
        if not is_global_token and target_user_id:
            handler = get_user_handler('autoselect', target_user_id)
            for autoselect_id, autoselect_config in handler.user_autoselects.items():
                try:
                    autoselects_info[autoselect_id] = {
                        "model_name": autoselect_config.get('model_name', autoselect_id),
                        "description": autoselect_config.get('description', ''),
                        "fallback": autoselect_config.get('fallback', ''),
                        "available_models": autoselect_config.get('available_models', []),
                        "source": "user_config"
                    }
                except Exception as e:
                    logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
        
        return {"autoselects": autoselects_info}
    
    if not target_user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    handler = get_user_handler('autoselect', target_user_id)
    
    autoselects_info = {}
    for autoselect_id, autoselect_config in handler.user_autoselects.items():
        try:
            autoselects_info[autoselect_id] = {
                "model_name": autoselect_config.get('model_name', autoselect_id),
                "description": autoselect_config.get('description', ''),
                "fallback": autoselect_config.get('fallback', ''),
                "available_models": autoselect_config.get('available_models', [])
            }
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    return {"autoselects": autoselects_info}


@app.post("/api/u/{username}/chat/completions")
async def user_chat_completions_by_username(request: Request, username: str, body: ChatCompletionRequest):
    """
    Handle chat completions using the specified user's configurations.
    
    Admin users and global tokens can also use global configurations.
    Users can use their own providers, rotations, and autoselects.
    Authentication is done via Bearer token in the Authorization header.
    
    Model format:
    - 'provider/model' - global provider (admin only)
    - 'rotation/name' - global rotation (admin only)
    - 'autoselect/name' - global autoselect (admin only)
    - 'user-provider/model' - user's provider
    - 'user-rotation/name' - user's rotation
    - 'user-autoselect/name' - user's autoselect
    
    Example:
        curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
             -H "Content-Type: application/json" \
             -d '{"model": "user-rotation/myrotation", "messages": [{"role": "user", "content": "Hello"}]}' \
             http://localhost:17765/api/u/{username}/chat/completions
    """
    from aisbf.database import get_database
    db = get_database()
    
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(
            status_code=404,
            content={"error": f"User '{username}' not found"}
        )
    
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "You do not have permission to access this user's configurations"}
        )
    
    provider_id, actual_model = parse_provider_from_model(body.model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', 'autoselect/name', 'user-provider/model', 'user-rotation/name', or 'user-autoselect/name'"
        )
    
    body_dict = body.model_dump()
    
    if provider_id == "user-autoselect":
        handler = get_user_handler('autoselect', target_user_id)
        if actual_model not in handler.user_autoselects:
            raise HTTPException(
                status_code=400,
                detail=f"User autoselect '{actual_model}' not found. Available: {list(handler.user_autoselects.keys())}"
            )
        body_dict['model'] = actual_model
        
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict)
    
    if provider_id == "user-rotation":
        handler = get_user_handler('rotation', target_user_id)
        if actual_model not in handler.user_rotations:
            raise HTTPException(
                status_code=400,
                detail=f"User rotation '{actual_model}' not found. Available: {list(handler.user_rotations.keys())}"
            )
        body_dict['model'] = actual_model
        return await handler.handle_rotation_request(actual_model, body_dict)
    
    if provider_id == "user-provider":
        handler = get_user_handler('request', target_user_id)
        if actual_model not in handler.user_providers:
            raise HTTPException(
                status_code=400,
                detail=f"User provider '{actual_model}' not found. Available: {list(handler.user_providers.keys())}"
            )
        
        provider_config = handler.user_providers[actual_model]
        
        if not validate_kiro_credentials(actual_model, provider_config):
            raise HTTPException(
                status_code=403,
                detail=f"Provider '{actual_model}' credentials not available."
            )
        
        body_dict['model'] = actual_model
        
        if body.stream:
            return await handler.handle_streaming_chat_completion(request, actual_model, body_dict)
        else:
            return await handler.handle_chat_completion(request, actual_model, body_dict)
    
    if is_global_token or is_admin:
        if provider_id == "autoselect":
            if actual_model not in config.autoselect:
                raise HTTPException(
                    status_code=400,
                    detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
                )
            handler = get_user_handler('autoselect', None)
            body_dict['model'] = actual_model
            
            if body.stream:
                return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
            else:
                return await handler.handle_autoselect_request(actual_model, body_dict)
        
        if provider_id == "rotation":
            if actual_model not in config.rotations:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
                )
            handler = get_user_handler('rotation', None)
            body_dict['model'] = actual_model
            return await handler.handle_rotation_request(actual_model, body_dict)
        
        if provider_id in config.providers:
            provider_config = config.get_provider(provider_id)
            
            if not validate_kiro_credentials(provider_id, provider_config):
                raise HTTPException(
                    status_code=403,
                    detail=f"Provider '{provider_id}' credentials not available."
                )
            
            body_dict['model'] = actual_model
            handler = get_user_handler('request', None)
            
            if body.stream:
                return await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
            else:
                return await handler.handle_chat_completion(request, provider_id, body_dict)
    
    raise HTTPException(
        status_code=400,
        detail="Model must be in format 'user-provider/model', 'user-rotation/name', or 'user-autoselect/name'. Global configurations are only available to admin users."
    )


@app.get("/api/u/{username}/{config_type}/models")
async def user_list_config_models_by_username(request: Request, username: str, config_type: str):
    """
    List models for a specific user configuration type.
    
    Args:
        config_type: One of 'providers', 'rotations', or 'autoselects'
    
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/{username}/rotations/models
    """
    from aisbf.database import get_database
    db = get_database()
    
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(
            status_code=404,
            content={"error": f"User '{username}' not found"}
        )
    
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "You do not have permission to access this user's configurations"}
        )
    
    if not target_user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    all_models = []
    
    if config_type == "providers":
        handler = get_user_handler('request', target_user_id)
        for provider_id, provider_config in handler.user_providers.items():
            try:
                if hasattr(provider_config, 'models') and provider_config.models:
                    for model in provider_config.models:
                        all_models.append({
                            "id": f"user-provider/{provider_id}/{model.name}",
                            "name": model.name,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": provider_id,
                            "provider_id": provider_id,
                            "type": "user_provider"
                        })
            except Exception as e:
                logger.warning(f"Error listing models for user provider {provider_id}: {e}")
    
    elif config_type == "rotations":
        handler = get_user_handler('rotation', target_user_id)
        for rotation_id, rotation_config in handler.user_rotations.items():
            try:
                providers = rotation_config.get('providers', [])
                for provider in providers:
                    for model in provider.get('models', []):
                        all_models.append({
                            "id": f"user-rotation/{rotation_id}/{model.get('name', '')}",
                            "name": rotation_id,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": provider.get('provider_id', ''),
                            "rotation_id": rotation_id,
                            "actual_model": model.get('name', ''),
                            "provider_id": provider.get('provider_id', ''),
                            "weight": model.get('weight', 1),
                            "type": "user_rotation"
                        })
            except Exception as e:
                logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    elif config_type == "autoselects":
        handler = get_user_handler('autoselect', target_user_id)
        for autoselect_id, autoselect_config in handler.user_autoselects.items():
            try:
                for model_info in autoselect_config.get('available_models', []):
                    all_models.append({
                        "id": f"user-autoselect/{autoselect_id}/{model_info.get('model_id', '')}",
                        "name": autoselect_id,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "user-autoselect",
                        "autoselect_id": autoselect_id,
                        "description": model_info.get('description', ''),
                        "type": "user_autoselect"
                    })
            except Exception as e:
                logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config type. Use 'providers', 'rotations', or 'autoselects'"
        )
    
    return {"data": all_models}


# User-specific API chat completion endpoints
# These endpoints allow authenticated users to use their own configurations
# Admin users and global tokens can also access global configurations

@app.post("/api/user/chat/completions")
async def user_chat_completions(request: Request, body: ChatCompletionRequest):
    """
    Handle chat completions using the authenticated user's configurations.
    
    Admin users and global tokens can also use global configurations.
    Users can use their own providers, rotations, and autoselects.
    Authentication is done via Bearer token in the Authorization header.
    
    Model format: 
    - 'provider/model' - global provider (admin only)
    - 'rotation/name' - global rotation (admin only)
    - 'autoselect/name' - global autoselect (admin only)
    - 'user-provider/model' - user's provider
    - 'user-rotation/name' - user's rotation
    - 'user-autoselect/name' - user's autoselect
    
    Example:
        curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
             -H "Content-Type: application/json" \
             -d '{"model": "user-rotation/myrotation", "messages": [{"role": "user", "content": "Hello"}]}' \
             http://localhost:17765/api/user/chat/completions
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    # Parse provider from model field
    provider_id, actual_model = parse_provider_from_model(body.model)
    
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Model must be in format 'provider/model', 'rotation/name', 'autoselect/name', 'user-provider/model', 'user-rotation/name', or 'user-autoselect/name'"
        )
    
    body_dict = body.model_dump()
    
    # Handle user autoselect (format: user-autoselect/{name})
    if provider_id == "user-autoselect":
        handler = get_user_handler('autoselect', user_id)
        if actual_model not in handler.user_autoselects:
            raise HTTPException(
                status_code=400,
                detail=f"User autoselect '{actual_model}' not found. Available: {list(handler.user_autoselects.keys())}"
            )
        body_dict['model'] = actual_model
        
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict)
    
    # Handle user rotation (format: user-rotation/{name})
    if provider_id == "user-rotation":
        handler = get_user_handler('rotation', user_id)
        if actual_model not in handler.user_rotations:
            raise HTTPException(
                status_code=400,
                detail=f"User rotation '{actual_model}' not found. Available: {list(handler.user_rotations.keys())}"
            )
        body_dict['model'] = actual_model
        return await handler.handle_rotation_request(actual_model, body_dict)
    
    # Handle user provider (format: user-provider/{name})
    if provider_id == "user-provider":
        handler = get_user_handler('request', user_id)
        if actual_model not in handler.user_providers:
            raise HTTPException(
                status_code=400,
                detail=f"User provider '{actual_model}' not found. Available: {list(handler.user_providers.keys())}"
            )
        
        provider_config = handler.user_providers[actual_model]
        
        # Validate kiro credentials
        if not validate_kiro_credentials(actual_model, provider_config):
            raise HTTPException(
                status_code=403,
                detail=f"Provider '{actual_model}' credentials not available."
            )
        
        body_dict['model'] = actual_model
        
        if body.stream:
            return await handler.handle_streaming_chat_completion(request, actual_model, body_dict)
        else:
            return await handler.handle_chat_completion(request, actual_model, body_dict)
    
    # Check for global configurations (admin/global token only)
    if is_global_token or is_admin:
        # Handle global autoselect
        if provider_id == "autoselect":
            if actual_model not in config.autoselect:
                raise HTTPException(
                    status_code=400,
                    detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
                )
            handler = get_user_handler('autoselect', None)
            body_dict['model'] = actual_model
            
            if body.stream:
                return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
            else:
                return await handler.handle_autoselect_request(actual_model, body_dict)
        
        # Handle global rotation
        if provider_id == "rotation":
            if actual_model not in config.rotations:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
                )
            handler = get_user_handler('rotation', None)
            body_dict['model'] = actual_model
            return await handler.handle_rotation_request(actual_model, body_dict)
        
        # Handle global provider
        if provider_id in config.providers:
            provider_config = config.get_provider(provider_id)
            
            # Validate kiro credentials
            if not validate_kiro_credentials(provider_id, provider_config):
                raise HTTPException(
                    status_code=403,
                    detail=f"Provider '{provider_id}' credentials not available."
                )
            
            body_dict['model'] = actual_model
            handler = get_user_handler('request', None)
            
            if body.stream:
                return await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
            else:
                return await handler.handle_chat_completion(request, provider_id, body_dict)
    
    raise HTTPException(
        status_code=400,
        detail="Model must be in format 'user-provider/model', 'user-rotation/name', or 'user-autoselect/name'. Global configurations are only available to admin users."
    )


# User-specific model listing endpoint
@app.get("/api/user/{config_type}/models")
async def user_list_config_models(request: Request, config_type: str):
    """
    List models for a specific user configuration type.
    
    Args:
        config_type: One of 'providers', 'rotations', or 'autoselects'
    
    Authentication is done via Bearer token in the Authorization header.
    
    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/user/rotations/models
    """
    user_id = getattr(request.state, 'user_id', None)
    
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required. Use a valid API token."}
        )
    
    all_models = []
    
    if config_type == "providers":
        handler = get_user_handler('request', user_id)
        for provider_id, provider_config in handler.user_providers.items():
            try:
                if hasattr(provider_config, 'models') and provider_config.models:
                    for model in provider_config.models:
                        all_models.append({
                            "id": f"user-provider/{provider_id}/{model.name}",
                            "name": model.name,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": provider_id,
                            "provider_id": provider_id,
                            "type": "user_provider"
                        })
            except Exception as e:
                logger.warning(f"Error listing models for user provider {provider_id}: {e}")
    
    elif config_type == "rotations":
        handler = get_user_handler('rotation', user_id)
        for rotation_id, rotation_config in handler.user_rotations.items():
            try:
                providers = rotation_config.get('providers', [])
                for provider in providers:
                    for model in provider.get('models', []):
                        all_models.append({
                            "id": f"user-rotation/{rotation_id}/{model.get('name', '')}",
                            "name": rotation_id,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": provider.get('provider_id', ''),
                            "rotation_id": rotation_id,
                            "actual_model": model.get('name', ''),
                            "provider_id": provider.get('provider_id', ''),
                            "weight": model.get('weight', 1),
                            "type": "user_rotation"
                        })
            except Exception as e:
                logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    elif config_type == "autoselects":
        handler = get_user_handler('autoselect', user_id)
        for autoselect_id, autoselect_config in handler.user_autoselects.items():
            try:
                for model_info in autoselect_config.get('available_models', []):
                    all_models.append({
                        "id": f"user-autoselect/{autoselect_id}/{model_info.get('model_id', '')}",
                        "name": autoselect_id,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "user-autoselect",
                        "autoselect_id": autoselect_id,
                        "description": model_info.get('description', ''),
                        "type": "user_autoselect"
                    })
            except Exception as e:
                logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config type. Use 'providers', 'rotations', or 'autoselects'"
        )
    
    return {"data": all_models}


# Chrome extension download endpoint
@app.get("/dashboard/extension/download")
async def dashboard_extension_download(request: Request):
    """Download the OAuth2 redirect extension as a ZIP file"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        from fastapi.responses import FileResponse
        
        # Path to pre-packaged extension ZIP
        extension_zip = Path(__file__).parent / 'static' / 'aisbf-oauth2-extension.zip'
        
        if not extension_zip.exists():
            # Fallback: try to build it dynamically
            logger.warning("Pre-packaged extension not found, creating dynamically...")
            import zipfile
            import io
            from fastapi.responses import Response
            
            extension_dir = Path(__file__).parent / 'static' / 'extension'
            
            if not extension_dir.exists():
                return JSONResponse(
                    status_code=404,
                    content={"error": "Extension files not found"}
                )
            
            # Create ZIP file in memory
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_path in extension_dir.rglob('*'):
                    if file_path.is_file() and not file_path.name.endswith('.sh'):
                        arcname = file_path.relative_to(extension_dir)
                        zip_file.write(file_path, arcname)
            
            zip_buffer.seek(0)
            return Response(
                content=zip_buffer.getvalue(),
                media_type="application/zip",
                headers={
                    "Content-Disposition": "attachment; filename=aisbf-oauth2-extension.zip"
                }
            )
        
        # Serve pre-packaged ZIP file
        return FileResponse(
            path=extension_zip,
            media_type="application/zip",
            filename="aisbf-oauth2-extension.zip"
        )
        
    except Exception as e:
        logger.error(f"Error serving extension ZIP: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# Global storage for pending OAuth2 callbacks (for localhost flow)
_pending_oauth2_callbacks = {}
_oauth2_callback_server = None


def _start_localhost_callback_server():
    """Start a temporary HTTP server on port 54545 to catch OAuth2 callbacks."""
    global _oauth2_callback_server
    
    if _oauth2_callback_server is not None:
        logger.info("Localhost callback server already running")
        return
    
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    import threading
    
    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Suppress default logging
            pass
        
        def do_GET(self):
            """Handle GET request - OAuth2 callback"""
            parsed = urlparse(self.path)
            
            if parsed.path == '/callback':
                query_params = parse_qs(parsed.query)
                code = query_params.get('code', [None])[0]
                state = query_params.get('state', [None])[0]
                error = query_params.get('error', [None])[0]
                
                logger.info(f"Localhost callback server received - Code: {code[:10] if code else 'None'}...")
                
                # Store the callback data
                _pending_oauth2_callbacks['latest'] = {
                    'code': code,
                    'state': state,
                    'error': error,
                    'timestamp': time.time()
                }
                
                # Send success response
                if error:
                    response_html = f"""
                    <html>
                        <head><title>Authentication Error</title></head>
                        <body style="font-family: Arial; text-align: center; padding: 50px;">
                            <h1 style="color: #e74c3c;">✗ Authentication Error</h1>
                            <p>Error: {error}</p>
                            <p>You can close this window.</p>
                        </body>
                    </html>
                    """
                    self.send_response(400)
                else:
                    response_html = """
                    <html>
                        <head><title>Authentication Successful</title></head>
                        <body style="font-family: Arial; text-align: center; padding: 50px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; height: 100vh; margin: 0; display: flex; justify-content: center; align-items: center;">
                            <div style="background: rgba(255,255,255,0.1); padding: 40px; border-radius: 10px;">
                                <h1>✓ Authentication Successful</h1>
                                <p>You can close this window and return to the dashboard.</p>
                            </div>
                            <script>setTimeout(() => window.close(), 3000);</script>
                        </body>
                    </html>
                    """
                    self.send_response(200)
                
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(response_html.encode())
            else:
                self.send_response(404)
                self.end_headers()
    
    def run_server():
        global _oauth2_callback_server
        try:
            _oauth2_callback_server = HTTPServer(('127.0.0.1', 54545), CallbackHandler)
            logger.info("Started localhost OAuth2 callback server on port 54545")
            _oauth2_callback_server.serve_forever()
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning("Port 54545 already in use - another callback server may be running")
            else:
                logger.error(f"Failed to start callback server: {e}")
        except Exception as e:
            logger.error(f"Callback server error: {e}")
        finally:
            _oauth2_callback_server = None
    
    # Start server in a daemon thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Give it a moment to start
    time.sleep(0.1)


def _stop_localhost_callback_server():
    """Stop the localhost callback server."""
    global _oauth2_callback_server
    if _oauth2_callback_server:
        _oauth2_callback_server.shutdown()
        _oauth2_callback_server = None
        logger.info("Stopped localhost OAuth2 callback server")


# OAuth2 callback endpoint (receives callbacks from extension OR direct localhost)
@app.get("/dashboard/oauth2/callback")
async def dashboard_oauth2_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None)
):
    """
    Handle OAuth2 callback redirected from localhost.
    
    This endpoint handles two scenarios:
    1. Direct localhost callback (when browser is on same machine as AISBF)
    2. Redirected callback from browser extension (when browser is remote)
    """
    try:
        if error:
            logger.error(f"OAuth2 callback error: {error}")
            return HTMLResponse(
                content=f"""
                <html>
                    <head><title>Authentication Error</title></head>
                    <body>
                        <h1>Authentication Error</h1>
                        <p>Error: {error}</p>
                        <p><a href="/dashboard/providers">Return to Dashboard</a></p>
                    </body>
                </html>
                """,
                status_code=400
            )
        
        if not code:
            return HTMLResponse(
                content="""
                <html>
                    <head><title>Authentication Error</title></head>
                    <body>
                        <h1>Authentication Error</h1>
                        <p>No authorization code received</p>
                        <p><a href="/dashboard/providers">Return to Dashboard</a></p>
                    </body>
                </html>
                """,
                status_code=400
            )
        
        # Store the code in session for the auth completion
        request.session['oauth2_code'] = code
        request.session['oauth2_state'] = state
        
        # Detect if this is a direct localhost callback (no extension involved)
        referer = request.headers.get('referer', '')
        is_direct_callback = 'localhost:54545' in referer or '127.0.0.1:54545' in referer
        
        logger.info(f"OAuth2 callback received - Direct: {is_direct_callback}, Code: {code[:10]}...")
        
        # Return success page with auto-close script
        return HTMLResponse(
            content="""
            <html>
                <head>
                    <title>Authentication Successful</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            margin: 0;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: white;
                        }
                        .container {
                            text-align: center;
                            padding: 40px;
                            background: rgba(255, 255, 255, 0.1);
                            border-radius: 10px;
                            backdrop-filter: blur(10px);
                        }
                        h1 { margin-bottom: 20px; }
                        p { margin: 10px 0; }
                        a {
                            color: #fff;
                            text-decoration: underline;
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>✓ Authentication Successful</h1>
                        <p>You can close this window and return to the dashboard.</p>
                        <p><a href="/dashboard/providers">Return to Dashboard</a></p>
                    </div>
                    <script>
                        // Auto-close after 3 seconds
                        setTimeout(() => {
                            window.close();
                        }, 3000);
                    </script>
                </body>
            </html>
            """
        )
        
    except Exception as e:
        logger.error(f"Error handling OAuth2 callback: {e}")
        return HTMLResponse(
            content=f"""
            <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>Authentication Error</h1>
                    <p>Error: {str(e)}</p>
                    <p><a href="/dashboard/providers">Return to Dashboard</a></p>
                </body>
            </html>
            """,
            status_code=500
        )


# Claude OAuth2 authentication endpoints
@app.post("/dashboard/claude/auth/start")
async def dashboard_claude_auth_start(request: Request):
    """Start Claude OAuth2 authentication flow - returns URL for browser opening"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.claude_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import ClaudeAuth
        from aisbf.auth.claude import ClaudeAuth
        
        # Create auth instance
        auth = ClaudeAuth()
        # Override credentials file if specified
        auth.credentials_file = Path(credentials_file).expanduser()
        
        # Generate PKCE challenge
        verifier, challenge = auth._generate_pkce()
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Store verifier and state in session for later use
        request.session['oauth2_verifier'] = verifier
        request.session['oauth2_state'] = state
        request.session['oauth2_provider'] = provider_key
        request.session['oauth2_credentials_file'] = credentials_file
        
        # Detect if the browser is accessing from localhost/127.0.0.1
        # If so, we can use direct localhost callback without the extension
        client_host = request.client.host if request.client else None
        is_local_access = client_host in ['127.0.0.1', '::1', 'localhost']
        
        # Get the request host to determine the callback URL
        request_host = request.headers.get('host', '').split(':')[0]
        is_localhost_request = request_host in ['127.0.0.1', 'localhost', '::1']
        
        # Check if request is coming through a proxy
        has_proxy_headers = (
            'X-Forwarded-For' in request.headers or
            'X-Forwarded-Host' in request.headers or
            'X-Real-IP' in request.headers
        )
        
        # Use local callback only if truly accessing from localhost (not behind proxy)
        # If behind proxy, always serve extension even if request appears local
        use_extension = not (is_local_access or is_localhost_request) or has_proxy_headers
        
        # If using localhost, start the callback server
        if not use_extension:
            _start_localhost_callback_server()
            logger.info("Started localhost callback server for direct OAuth2 flow")
        
        # Build OAuth2 URL (Claude requires full scope set)
        auth_params = {
            "code": "true",
            "client_id": auth.CLIENT_ID,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": auth.REDIRECT_URI,
            "scope": "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload",
            "state": state
        }
        auth_url = f"{auth.AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in auth_params.items())}"
        
        return JSONResponse({
            "success": True,
            "auth_url": auth_url,
            "use_extension": use_extension,
            "message": "Please complete authentication in the browser window" if use_extension else "Authentication will use direct localhost callback"
        })
        
    except Exception as e:
        logger.error(f"Error starting Claude auth: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/dashboard/claude/auth/complete")
async def dashboard_claude_auth_complete(request: Request):
    """Complete Claude OAuth2 authentication using the code from callback"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Get code from session (stored by callback endpoint) or from localhost callback server
        code = request.session.get('oauth2_code')
        verifier = request.session.get('oauth2_verifier')
        state = request.session.get('oauth2_state')
        credentials_file = request.session.get('oauth2_credentials_file', '~/.claude_credentials.json')
        
        # Check for callback data from localhost server if not in session
        if not code and 'latest' in _pending_oauth2_callbacks:
            callback_data = _pending_oauth2_callbacks['latest']
            # Only use if received within the last 5 minutes
            if time.time() - callback_data.get('timestamp', 0) < 300:
                code = callback_data.get('code')
                state = callback_data.get('state') or state  # Use callback state if available
                if callback_data.get('error'):
                    return JSONResponse(
                        status_code=400,
                        content={"success": False, "error": f"OAuth2 error: {callback_data['error']}"}
                    )
                logger.info(f"Using code from localhost callback server: {code[:10] if code else 'None'}...")
        
        if not code or not verifier:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "No authorization code found. Please restart authentication."}
            )
        
        # Import ClaudeAuth
        from aisbf.auth.claude import ClaudeAuth
        
        # Create auth instance
        auth = ClaudeAuth()
        auth.credentials_file = Path(credentials_file).expanduser()
        
        # Use the new exchange_code_for_tokens method with retry logic
        # Pass state as the second parameter (required), verifier as third (optional)
        success = auth.exchange_code_for_tokens(code, state, verifier)
        
        if success:
            # Only the ONE config admin (user_id=None from aisbf.json) saves to file
            # All other users (including database admins) save to database
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None
            
            if not is_config_admin:
                # Non-config-admin user: save credentials to database
                try:
                    from aisbf.database import get_database
                    db = get_database()
                    provider_key = request.session.get('oauth2_provider')
                    if db and current_user_id and provider_key:
                        # Read the credentials that were just saved to file
                        credentials_path = Path(credentials_file).expanduser()
                        if credentials_path.exists():
                            with open(credentials_path, 'r') as f:
                                db_credentials = json.load(f)
                            
                            # Save to database
                            db.save_user_oauth2_credentials(
                                user_id=current_user_id,
                                provider_id=provider_key,
                                auth_type='claude_oauth2',
                                credentials=db_credentials
                            )
                            logger.info(f"ClaudeOAuth2: Saved credentials to database for user {current_user_id}")
                            
                            # Remove the file since we're using database storage for non-admin
                            credentials_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"ClaudeOAuth2: Failed to save credentials to database: {e}")
            
            # Clear session data
            request.session.pop('oauth2_code', None)
            request.session.pop('oauth2_verifier', None)
            request.session.pop('oauth2_state', None)
            request.session.pop('oauth2_provider', None)
            request.session.pop('oauth2_credentials_file', None)
            
            # Clear pending callback data
            _pending_oauth2_callbacks.pop('latest', None)
            
            return JSONResponse({
                "success": True,
                "message": "Authentication completed successfully"
            })
        else:
            # Check if it was a rate limit issue
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Token exchange failed. If you see rate_limit_error, please wait 1-2 minutes before trying again."}
            )
        
    except Exception as e:
        logger.error(f"Error completing Claude auth: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/dashboard/claude/auth/callback-status")
async def dashboard_claude_auth_callback_status(request: Request):
    """Check if OAuth2 callback has been received (for localhost flow)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if we have callback data from the localhost server
    if 'latest' in _pending_oauth2_callbacks:
        callback_data = _pending_oauth2_callbacks['latest']
        # Only valid if received within the last 5 minutes
        if time.time() - callback_data.get('timestamp', 0) < 300:
            if callback_data.get('error'):
                return JSONResponse({
                    "received": True,
                    "error": callback_data['error']
                })
            elif callback_data.get('code'):
                return JSONResponse({
                    "received": True,
                    "has_code": True
                })
    
    # Also check session (for extension flow)
    if request.session.get('oauth2_code'):
        return JSONResponse({
            "received": True,
            "has_code": True
        })
    
    return JSONResponse({
        "received": False
    })


@app.post("/dashboard/claude/auth/status")
async def dashboard_claude_auth_status(request: Request):
    """Check Claude authentication status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.claude_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"authenticated": False, "error": "Provider key is required"}
            )
        
        # Import ClaudeAuth
        from aisbf.auth.claude import ClaudeAuth
        
        # Check if current user is config admin
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if not is_config_admin:
            # Non-config-admin user: check database for credentials
            try:
                from aisbf.database import get_database
                db = get_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(
                        user_id=current_user_id,
                        provider_id=provider_key,
                        auth_type='claude_oauth2'
                    )
                    if db_creds and db_creds.get('credentials'):
                        # Check if tokens are still valid
                        tokens = db_creds['credentials'].get('tokens', {})
                        access_token = tokens.get('access_token')
                        if access_token:
                            return JSONResponse({
                                "authenticated": True,
                                "email": db_creds['credentials'].get('email', 'unknown')
                            })
            except Exception as e:
                logger.warning(f"ClaudeOAuth2: Failed to check database credentials: {e}")
        
        # Config admin or no database credentials: check file
        auth = ClaudeAuth(credentials_file=credentials_file)
        
        # Check if credentials exist and are valid
        if auth.tokens:
            # Check if token is expired (with 5 minute buffer)
            expires_at = auth.tokens.get('expires_at', 0)
            if time.time() < (expires_at - 300):
                # Token is valid
                return JSONResponse({
                    "authenticated": True,
                    "expires_in": expires_at - time.time()
                })
            else:
                # Token expired, try to refresh
                if auth.refresh_token():
                    return JSONResponse({
                        "authenticated": True,
                        "expires_in": auth.tokens.get('expires_at', 0) - time.time()
                    })
                else:
                    return JSONResponse({
                        "authenticated": False
                    })
        else:
            return JSONResponse({
                "authenticated": False
            })
        
    except Exception as e:
        logger.error(f"Error checking Claude auth status: {e}")
        return JSONResponse(
            status_code=500,
            content={"authenticated": False, "error": str(e)}
        )


# Kilo OAuth2 authentication endpoints
@app.post("/dashboard/kilo/auth/start")
async def dashboard_kilo_auth_start(request: Request):
    """Start Kilo OAuth2 Device Authorization Grant flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.kilo_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import KiloOAuth2
        from aisbf.auth.kilo import KiloOAuth2
        
        # Create auth instance
        auth = KiloOAuth2(credentials_file=credentials_file)
        
        # Initiate device authorization (async method)
        device_auth = await auth.initiate_device_auth()
        
        if not device_auth:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Failed to initiate device authorization"}
            )
        
        # Store device code in session for polling
        request.session['kilo_device_code'] = device_auth['code']
        request.session['kilo_provider'] = provider_key
        request.session['kilo_credentials_file'] = credentials_file
        request.session['kilo_expires_at'] = time.time() + device_auth['expiresIn']
        
        return JSONResponse({
            "success": True,
            "user_code": device_auth['code'],
            "verification_uri": device_auth['verificationUrl'],
            "expires_in": device_auth['expiresIn'],
            "interval": 3,
            "message": f"Please visit {device_auth['verificationUrl']} and enter code: {device_auth['code']}"
        })
        
    except Exception as e:
        logger.error(f"Error starting Kilo auth: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/dashboard/kilo/auth/poll")
async def dashboard_kilo_auth_poll(request: Request):
    """Poll Kilo OAuth2 device authorization status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Get device code from session
        device_code = request.session.get('kilo_device_code')
        credentials_file = request.session.get('kilo_credentials_file', '~/.kilo_credentials.json')
        expires_at = request.session.get('kilo_expires_at', 0)
        
        if not device_code:
            return JSONResponse(
                status_code=400,
                content={"success": False, "status": "error", "error": "No device authorization in progress"}
            )
        
        # Check if expired
        if time.time() > expires_at:
            # Clear session
            request.session.pop('kilo_device_code', None)
            request.session.pop('kilo_provider', None)
            request.session.pop('kilo_credentials_file', None)
            request.session.pop('kilo_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "expired",
                "error": "Device authorization expired"
            })
        
        # Import KiloOAuth2
        from aisbf.auth.kilo import KiloOAuth2
        
        # Create auth instance
        auth = KiloOAuth2(credentials_file=credentials_file)
        
        # Poll device authorization status (async method)
        result = await auth.poll_device_auth(device_code)
        
        if result['status'] == 'approved':
            # Save credentials
            token = result.get('token')
            user_email = result.get('userEmail')
            
            # Only the ONE config admin (user_id=None from aisbf.json) saves to file
            # All other users (including database admins) save to database
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None
            
            if token:
                credentials = {
                    "type": "oauth",
                    "access": token,
                    "refresh": token,  # Same token for both
                    "expires": int(time.time()) + (365 * 24 * 60 * 60),  # 1 year
                    "userEmail": user_email
                }
                
                if not is_config_admin:
                    # Non-config-admin user: save credentials to database
                    try:
                        from aisbf.database import get_database
                        db = get_database()
                        provider_key = request.session.get('kilo_provider')
                        if db and current_user_id and provider_key:
                            # Save to database
                            db.save_user_oauth2_credentials(
                                user_id=current_user_id,
                                provider_id=provider_key,
                                auth_type='kilo_oauth2',
                                credentials=credentials
                            )
                            logger.info(f"KiloOAuth2: Saved credentials to database for user {current_user_id}")
                    except Exception as e:
                        logger.error(f"KiloOAuth2: Failed to save credentials to database: {e}")
                else:
                    # Config admin: save to file
                    auth._save_credentials(credentials)
                    logger.info(f"KiloOAuth2: Saved credentials to file for {user_email}")
            
            # Clear session data
            request.session.pop('kilo_device_code', None)
            request.session.pop('kilo_provider', None)
            request.session.pop('kilo_credentials_file', None)
            request.session.pop('kilo_expires_at', None)
            
            return JSONResponse({
                "success": True,
                "status": "approved",
                "message": "Authentication completed successfully"
            })
        elif result['status'] == 'pending':
            return JSONResponse({
                "success": True,
                "status": "pending",
                "message": "Waiting for user authorization"
            })
        elif result['status'] == 'denied':
            # Clear session
            request.session.pop('kilo_device_code', None)
            request.session.pop('kilo_provider', None)
            request.session.pop('kilo_credentials_file', None)
            request.session.pop('kilo_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "denied",
                "error": "User denied authorization"
            })
        elif result['status'] == 'expired':
            # Clear session
            request.session.pop('kilo_device_code', None)
            request.session.pop('kilo_provider', None)
            request.session.pop('kilo_credentials_file', None)
            request.session.pop('kilo_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "expired",
                "error": "Device authorization expired"
            })
        elif result['status'] == 'slow_down':
            return JSONResponse({
                "success": True,
                "status": "slow_down",
                "message": "Polling too frequently, slowing down"
            })
        else:
            return JSONResponse({
                "success": False,
                "status": "error",
                "error": result.get('error', 'Unknown error')
            })
        
    except Exception as e:
        logger.error(f"Error polling Kilo auth: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "status": "error", "error": str(e)}
        )


@app.post("/dashboard/kilo/auth/status")
async def dashboard_kilo_auth_status(request: Request):
    """Check Kilo authentication status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.kilo_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"authenticated": False, "error": "Provider key is required"}
            )
        
        # Import KiloOAuth2
        from aisbf.auth.kilo import KiloOAuth2
        
        # Check if current user is config admin
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if not is_config_admin:
            # Non-config-admin user: check database for credentials
            try:
                from aisbf.database import get_database
                db = get_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(
                        user_id=current_user_id,
                        provider_id=provider_key,
                        auth_type='kilo_oauth2'
                    )
                    if db_creds and db_creds.get('credentials'):
                        # Check if tokens are still valid
                        creds = db_creds['credentials']
                        expires_at = creds.get('expires', 0)
                        if time.time() < expires_at:
                            return JSONResponse({
                                "authenticated": True,
                                "expires_in": max(0, expires_at - time.time()),
                                "email": creds.get('userEmail', 'unknown')
                            })
            except Exception as e:
                logger.warning(f"KiloOAuth2: Failed to check database credentials: {e}")
        
        # Config admin or no database credentials: check file
        auth = KiloOAuth2(credentials_file=credentials_file)
        
        # Check if authenticated
        if auth.is_authenticated():
            # Try to get a valid token (will refresh if needed)
            token = auth.get_valid_token()
            if token:
                # Get token expiration info
                expires_at = auth.credentials.get('expires', 0)
                
                return JSONResponse({
                    "authenticated": True,
                    "expires_in": max(0, expires_at - time.time()),
                    "email": auth.credentials.get('userEmail')
                })
        
        return JSONResponse({
            "authenticated": False
        })
        
    except Exception as e:
        logger.error(f"Error checking Kilo auth status: {e}")
        return JSONResponse(
            status_code=500,
            content={"authenticated": False, "error": str(e)}
        )


@app.post("/dashboard/kilo/auth/logout")
async def dashboard_kilo_auth_logout(request: Request):
    """Logout from Kilo OAuth2 (clear stored credentials)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.kilo_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import KiloOAuth2
        from aisbf.auth.kilo import KiloOAuth2
        
        # Create auth instance
        auth = KiloOAuth2(credentials_file=credentials_file)
        
        # Logout (clear credentials)
        auth.logout()
        
        return JSONResponse({
            "success": True,
            "message": "Logged out successfully"
        })
        
    except Exception as e:
        logger.error(f"Error logging out from Kilo: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


# Codex OAuth2 authentication endpoints
@app.post("/dashboard/codex/auth/start")
async def dashboard_codex_auth_start(request: Request):
    """Start Codex OAuth2 Device Authorization Grant flow - returns immediately with verification info"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/codex_credentials.json')
        issuer = data.get('issuer', 'https://auth.openai.com')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import CodexOAuth2
        from aisbf.auth.codex import CodexOAuth2
        
        # Create auth instance
        auth = CodexOAuth2(credentials_file=credentials_file, issuer=issuer)
        
        # Request device code (returns immediately)
        device_info = await auth.request_device_code_flow()
        
        # Store device info in session for polling
        request.session['codex_device_auth_id'] = device_info.get('device_auth_id')
        request.session['codex_user_code'] = device_info.get('user_code')
        request.session['codex_provider'] = provider_key
        request.session['codex_credentials_file'] = credentials_file
        request.session['codex_issuer'] = issuer
        request.session['codex_expires_at'] = time.time() + device_info.get('expires_in', 900)
        
        return JSONResponse({
            "success": True,
            "user_code": device_info.get('user_code'),
            "verification_uri": device_info.get('verification_uri'),
            "expires_in": device_info.get('expires_in', 900),
            "interval": device_info.get('interval', 5),
            "message": f"Please visit {device_info.get('verification_uri')} and enter code: {device_info.get('user_code')}"
        })
        
    except Exception as e:
        logger.error(f"Error starting Codex auth: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/dashboard/codex/auth/poll")
async def dashboard_codex_auth_poll(request: Request):
    """Poll Codex OAuth2 device authorization status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Get device auth info from session
        device_auth_id = request.session.get('codex_device_auth_id')
        user_code = request.session.get('codex_user_code')
        
        if not device_auth_id or not user_code:
            return JSONResponse({
                "success": False,
                "status": "error",
                "error": "No device authorization in progress. Please start authentication again."
            })
        
        # Check if expired
        expires_at = request.session.get('codex_expires_at', 0)
        if time.time() > expires_at:
            request.session.pop('codex_device_auth_id', None)
            request.session.pop('codex_user_code', None)
            request.session.pop('codex_provider', None)
            request.session.pop('codex_credentials_file', None)
            request.session.pop('codex_issuer', None)
            request.session.pop('codex_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "expired",
                "error": "Device authorization expired"
            })
        
        credentials_file = request.session.get('codex_credentials_file', '~/.aisbf/codex_credentials.json')
        issuer = request.session.get('codex_issuer', 'https://auth.openai.com')
        
        # Import CodexOAuth2
        from aisbf.auth.codex import CodexOAuth2
        
        # Create auth instance
        auth = CodexOAuth2(credentials_file=credentials_file, issuer=issuer)
        
        # Set device auth info on the instance (required for poll_device_code_completion)
        auth._device_auth_id = device_auth_id
        auth._device_user_code = user_code
        
        # Poll for completion
        result = await auth.poll_device_code_completion()
        
        if result['status'] == 'approved':
            # Only the ONE config admin (user_id=None from aisbf.json) saves to file
            # All other users (including database admins) save to database
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None
            
            if not is_config_admin:
                # Non-admin user: save credentials to database instead of file
                try:
                    from aisbf.database import get_database
                    db = get_database()
                    provider_key = request.session.get('codex_provider')
                    if db and current_user_id and provider_key:
                        # Read the credentials that were just saved to file
                        credentials_path = Path(credentials_file).expanduser()
                        if credentials_path.exists():
                            with open(credentials_path, 'r') as f:
                                db_credentials = json.load(f)
                            
                            # Save to database
                            db.save_user_oauth2_credentials(
                                user_id=current_user_id,
                                provider_id=provider_key,
                                auth_type='codex_oauth2',
                                credentials=db_credentials
                            )
                            logger.info(f"CodexOAuth2: Saved credentials to database for user {current_user_id}")
                            
                            # Remove the file since we're using database storage for non-admin
                            credentials_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"CodexOAuth2: Failed to save credentials to database: {e}")
            
            # Clear session
            request.session.pop('codex_device_auth_id', None)
            request.session.pop('codex_user_code', None)
            request.session.pop('codex_provider', None)
            request.session.pop('codex_credentials_file', None)
            request.session.pop('codex_issuer', None)
            request.session.pop('codex_expires_at', None)
            
            return JSONResponse({
                "success": True,
                "status": "approved",
                "message": "Authentication completed successfully",
                "new_endpoint": "https://chatgpt.com/backend-api/codex"
            })
        elif result['status'] == 'pending':
            return JSONResponse({
                "success": True,
                "status": "pending",
                "message": "Waiting for user authorization"
            })
        elif result['status'] == 'denied':
            request.session.pop('codex_device_auth_id', None)
            request.session.pop('codex_user_code', None)
            request.session.pop('codex_provider', None)
            request.session.pop('codex_credentials_file', None)
            request.session.pop('codex_issuer', None)
            request.session.pop('codex_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "denied",
                "error": "User denied authorization"
            })
        elif result['status'] == 'expired':
            request.session.pop('codex_device_auth_id', None)
            request.session.pop('codex_user_code', None)
            request.session.pop('codex_provider', None)
            request.session.pop('codex_credentials_file', None)
            request.session.pop('codex_issuer', None)
            request.session.pop('codex_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "expired",
                "error": "Device authorization expired"
            })
        else:
            return JSONResponse({
                "success": False,
                "status": "error",
                "error": result.get('error', 'Unknown error')
            })
        
    except Exception as e:
        logger.error(f"Error polling Codex auth: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "status": "error", "error": str(e)}
        )


@app.post("/dashboard/codex/auth/status")
async def dashboard_codex_auth_status(request: Request):
    """Check Codex authentication status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/codex_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"authenticated": False, "error": "Provider key is required"}
            )
        
        # Import CodexOAuth2
        from aisbf.auth.codex import CodexOAuth2
        
        # Check if current user is config admin
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if not is_config_admin:
            # Non-config-admin user: check database for credentials
            try:
                from aisbf.database import get_database
                db = get_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(
                        user_id=current_user_id,
                        provider_id=provider_key,
                        auth_type='codex_oauth2'
                    )
                    if db_creds and db_creds.get('credentials'):
                        # Check if tokens are still valid
                        tokens = db_creds['credentials'].get('tokens', {})
                        access_token = tokens.get('access_token')
                        if access_token:
                            return JSONResponse({
                                "authenticated": True,
                                "email": db_creds['credentials'].get('email', 'unknown')
                            })
            except Exception as e:
                logger.warning(f"CodexOAuth2: Failed to check database credentials: {e}")
        
        # Config admin or no database credentials: check file
        auth = CodexOAuth2(credentials_file=credentials_file)
        
        # Check if authenticated
        if auth.is_authenticated():
            # Try to get a valid token (will refresh if needed)
            token = auth.get_valid_token()
            if token:
                # Get user email from ID token
                email = auth.get_user_email()
                
                return JSONResponse({
                    "authenticated": True,
                    "email": email
                })
        
        return JSONResponse({
            "authenticated": False
        })
        
    except Exception as e:
        logger.error(f"Error checking Codex auth status: {e}")
        return JSONResponse(
            status_code=500,
            content={"authenticated": False, "error": str(e)}
        )


@app.post("/dashboard/codex/auth/logout")
async def dashboard_codex_auth_logout(request: Request):
    """Logout from Codex OAuth2 (clear stored credentials)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/codex_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import CodexOAuth2
        from aisbf.auth.codex import CodexOAuth2
        
        # Create auth instance
        auth = CodexOAuth2(credentials_file=credentials_file)
        
        # Logout (clear credentials)
        auth.logout()
        
        return JSONResponse({
            "success": True,
            "message": "Logged out successfully"
        })
        
    except Exception as e:
        logger.error(f"Error logging out from Codex: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


# Qwen OAuth2 authentication endpoints - Save credentials after successful poll
def _save_qwen_credentials(credentials_file: str, token_response: dict) -> None:
    """Save Qwen OAuth2 credentials to file"""
    from pathlib import Path
    import time
    
    try:
        # OAuth2 standard: expires_in is always in seconds
        # Convert to milliseconds for storage
        expires_in = token_response.get("expires_in", 7200)
        expires_in_ms = expires_in * 1000  # Convert seconds to milliseconds
        
        # Minimum expiry: 1 hour (3600 seconds = 3,600,000 ms)
        if expires_in_ms < 3600000:
            expires_in_ms = 3600000  # Default to 1 hour minimum
        
        credentials = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response.get("refresh_token"),
            "token_type": token_response.get("token_type", "Bearer"),
            "resource_url": token_response.get("resource_url"),
            "expiry_date": int(time.time() * 1000) + expires_in_ms,
            "last_refresh": datetime.utcnow().isoformat() + "Z",
        }
        
        # Ensure directory exists
        cred_path = Path(credentials_file).expanduser()
        cred_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write credentials atomically (temp file + rename)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', dir=cred_path.parent, delete=False) as f:
            json.dump(credentials, f, indent=2)
            temp_path = f.name
        
        # Atomic rename
        import os
        os.rename(temp_path, cred_path)
        
        # Set file permissions to 0o600
        os.chmod(cred_path, 0o600)
        
        logger.info(f"QwenOAuth2: Saved credentials to {credentials_file}")
    except Exception as e:
        logger.error(f"QwenOAuth2: Failed to save credentials: {e}")
        raise


@app.post("/dashboard/qwen/auth/start")
async def dashboard_qwen_auth_start(request: Request):
    """Start Qwen OAuth2 Device Authorization Grant flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/qwen_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import QwenOAuth2
        from aisbf.auth.qwen import QwenOAuth2
        
        # Create auth instance
        auth = QwenOAuth2(credentials_file=credentials_file)
        
        logger.info(f"QwenOAuth2: Requesting device code for provider: {provider_key}")
        
        # Request device code
        device_info = await auth.request_device_code()
        
        if not device_info:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Failed to initiate device authorization"}
            )
        
        logger.info(f"QwenOAuth2: Device code obtained: {device_info.get('user_code')}")
        
        # Store in session for polling
        request.session['qwen_device_code'] = device_info['device_code']
        request.session['qwen_code_verifier'] = device_info['code_verifier']
        request.session['qwen_provider'] = provider_key
        request.session['qwen_credentials_file'] = credentials_file
        request.session['qwen_expires_at'] = time.time() + device_info['expires_in']
        
        return JSONResponse({
            "success": True,
            "user_code": device_info['user_code'],
            "verification_uri": device_info['verification_uri_complete'],
            "expires_in": device_info['expires_in'],
            "interval": device_info['interval'],
            "message": f"Please visit {device_info['verification_uri_complete']} and enter code: {device_info['user_code']}"
        })
        
    except Exception as e:
        logger.error(f"Error starting Qwen auth: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/dashboard/qwen/auth/poll")
async def dashboard_qwen_auth_poll(request: Request):
    """Poll Qwen OAuth2 device authorization status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Get device code from session
        device_code = request.session.get('qwen_device_code')
        code_verifier = request.session.get('qwen_code_verifier')
        credentials_file = request.session.get('qwen_credentials_file', '~/.aisbf/qwen_credentials.json')
        expires_at = request.session.get('qwen_expires_at', 0)
        
        if not device_code:
            return JSONResponse(
                status_code=400,
                content={"success": False, "status": "error", "error": "No device authorization in progress"}
            )
        
        # Check if expired
        if time.time() > expires_at:
            request.session.pop('qwen_device_code', None)
            request.session.pop('qwen_code_verifier', None)
            request.session.pop('qwen_provider', None)
            request.session.pop('qwen_credentials_file', None)
            request.session.pop('qwen_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "expired",
                "error": "Device authorization expired"
            })
        
        # Import QwenOAuth2
        from aisbf.auth.qwen import QwenOAuth2
        
        # Create auth instance
        auth = QwenOAuth2(credentials_file=credentials_file)
        
        # Poll for token - returns token dict if approved, None if still pending
        result = await auth.poll_device_token(device_code, code_verifier)
        
        if result and result.get("access_token"):
            # Authentication successful - save the tokens
            # Only the ONE config admin (user_id=None from aisbf.json) saves to file
            # All other users (including database admins) save to database
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None
            
            # First save to file (for config admin), then copy to DB if needed
            _save_qwen_credentials(credentials_file, result)
            
            if not is_config_admin:
                # Non-config-admin user: also save credentials to database
                try:
                    from aisbf.database import get_database
                    db = get_database()
                    provider_key = request.session.get('qwen_provider')
                    if db and current_user_id and provider_key:
                        # Read the credentials that were just saved to file
                        credentials_path = Path(credentials_file).expanduser()
                        if credentials_path.exists():
                            with open(credentials_path, 'r') as f:
                                db_credentials = json.load(f)
                            
                            # Save to database
                            db.save_user_oauth2_credentials(
                                user_id=current_user_id,
                                provider_id=provider_key,
                                auth_type='qwen_oauth2',
                                credentials=db_credentials
                            )
                            logger.info(f"QwenOAuth2: Saved credentials to database for user {current_user_id}")
                            
                            # Remove the file since we're using database storage for non-admin
                            credentials_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"QwenOAuth2: Failed to save credentials to database: {e}")
            
            # Clear session
            request.session.pop('qwen_device_code', None)
            request.session.pop('qwen_code_verifier', None)
            request.session.pop('qwen_provider', None)
            request.session.pop('qwen_credentials_file', None)
            request.session.pop('qwen_expires_at', None)
            
            return JSONResponse({
                "success": True,
                "status": "approved",
                "message": "Authentication completed successfully"
            })
        elif result is None:
            # Still pending (None is returned when waiting for user approval)
            return JSONResponse({
                "success": True,
                "status": "pending",
                "message": "Waiting for user authorization. Please approve the device on your Qwen account."
            })
        else:
            # Unexpected result (not None, but no access_token) - treat as pending
            return JSONResponse({
                "success": True,
                "status": "pending",
                "message": "Waiting for user authorization"
            })
        
    except Exception as e:
        error_msg = str(e).lower()
        if "authorization_pending" in error_msg or "pending" in error_msg:
            return JSONResponse({
                "success": True,
                "status": "pending",
                "message": "Waiting for user authorization. Please approve the device on your Qwen account."
            })
        elif "slow_down" in error_msg or "429" in error_msg:
            return JSONResponse({
                "success": True,
                "status": "slow_down",
                "message": "Polling too frequently, slowing down"
            })
        elif "expired" in error_msg:
            request.session.pop('qwen_device_code', None)
            request.session.pop('qwen_code_verifier', None)
            request.session.pop('qwen_provider', None)
            request.session.pop('qwen_credentials_file', None)
            request.session.pop('qwen_expires_at', None)
            
            return JSONResponse({
                "success": False,
                "status": "expired",
                "error": "Device authorization expired"
            })
        else:
            logger.error(f"Error polling Qwen auth: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"success": False, "status": "error", "error": str(e)}
            )


@app.post("/dashboard/qwen/auth/status")
async def dashboard_qwen_auth_status(request: Request):
    """Check Qwen authentication status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/qwen_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"authenticated": False, "error": "Provider key is required"}
            )
        
        # Import QwenOAuth2
        from aisbf.auth.qwen import QwenOAuth2
        
        # Check if current user is config admin
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if not is_config_admin:
            # Non-config-admin user: check database for credentials
            try:
                from aisbf.database import get_database
                db = get_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(
                        user_id=current_user_id,
                        provider_id=provider_key,
                        auth_type='qwen_oauth2'
                    )
                    if db_creds and db_creds.get('credentials'):
                        # Check if tokens are still valid
                        creds = db_creds['credentials']
                        access_token = creds.get('access_token')
                        expiry_date = creds.get('expiry_date', 0)
                        if access_token and time.time() * 1000 < expiry_date:
                            return JSONResponse({
                                "authenticated": True,
                                "expires_in": max(0, (expiry_date - int(time.time() * 1000)) / 1000)
                        })
            except Exception as e:
                logger.warning(f"QwenOAuth2: Failed to check database credentials: {e}")
        
        # Config admin or no database credentials: check file
        auth = QwenOAuth2(credentials_file=credentials_file)
        
        # Check if authenticated
        if auth.is_authenticated():
            # Try to get a valid token (will refresh if needed)
            token = await auth.get_valid_token_with_refresh()
            if token:
                # Get token expiration info
                expiry_date = auth.credentials.get('expiry_date', 0)
                
                return JSONResponse({
                    "authenticated": True,
                    "expires_in": max(0, (expiry_date - int(time.time() * 1000)) / 1000)
                })
        
        return JSONResponse({
            "authenticated": False
        })
        
    except Exception as e:
        logger.error(f"Error checking Qwen auth status: {e}")
        return JSONResponse(
            status_code=500,
            content={"authenticated": False, "error": str(e)}
        )


@app.post("/dashboard/qwen/auth/logout")
async def dashboard_qwen_auth_logout(request: Request):
    """Logout from Qwen OAuth2 (clear stored credentials)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/qwen_credentials.json')
        
        if not provider_key:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Provider key is required"}
            )
        
        # Import QwenOAuth2
        from aisbf.auth.qwen import QwenOAuth2
        
        # Clear file credentials (for config admin)
        auth = QwenOAuth2(credentials_file=credentials_file)
        auth.clear_credentials()
        
        # Also clear database credentials (for database users)
        current_user_id = request.session.get('user_id')
        if current_user_id:
            try:
                from aisbf.database import get_database
                db = get_database()
                if db:
                    db.delete_user_oauth2_credentials(current_user_id, provider_key, 'qwen_oauth2')
            except Exception as e:
                logger.warning(f"QwenOAuth2: Failed to clear database credentials: {e}")
        
        # Clear session data
        request.session.pop('qwen_device_code', None)
        request.session.pop('qwen_code_verifier', None)
        request.session.pop('qwen_provider', None)
        request.session.pop('qwen_credentials_file', None)
        request.session.pop('qwen_expires_at', None)
        
        return JSONResponse({
            "success": True,
            "message": "Logged out successfully"
        })
        
    except Exception as e:
        logger.error(f"Error logging out from Qwen: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


if __name__ == "__main__":
    main()
