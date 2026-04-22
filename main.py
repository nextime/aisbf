from decimal import Decimal
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
from aisbf import __version__
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from aisbf.models import ChatCompletionRequest, ChatCompletionResponse
from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
from aisbf.config import Config
from aisbf.mcp import mcp_server, MCPAuthLevel, load_mcp_config
from aisbf.database import DatabaseRegistry
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
from aisbf.database import _hash_password as _db_hash_password, _verify_password as _db_verify_password
import httpx
import multiprocessing
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import json
import re
import markdown
from urllib.parse import urljoin, urlencode
from cryptography.fernet import Fernet

# Global variable to store custom config directory
_custom_config_dir = None

# Global variable to store original command line arguments for restart
_original_argv = None

# Payment service global
payment_service = None

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
        
        # Debug logging for proxy headers
        if forwarded_proto or forwarded_host or forwarded_prefix:
            logger.debug(f"Proxy headers detected - Proto: {forwarded_proto}, Host: {forwarded_host}, Prefix: {forwarded_prefix}, Path: {request.url.path}")
        
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

    # Check if we're behind a proxy by looking for proxy headers
    # If X-Forwarded-Host is present, we're behind a proxy
    is_behind_proxy = "x-forwarded-host" in request.headers or "x-forwarded-proto" in request.headers
    
    if is_behind_proxy:
        # Behind proxy: return relative URL that browser resolves correctly
        # If root_path is "/" (no prefix), just return the path
        if root_path and root_path != "/":
            return root_path + path
        else:
            return path
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

# Note: ProxyHeadersMiddleware will be added LAST (after all other middleware)
# so it executes FIRST and processes proxy headers before other middleware

# Initialize Jinja2 templates with custom globals for proxy-aware URLs
templates = Jinja2Templates(directory="templates")
# Add root templates directory to search path for parent template resolution
templates.env.loader.searchpath.insert(0, "templates")

# Monkey patch TemplateResponse to automatically add dashboard context variables
original_template_response = templates.TemplateResponse
def patched_template_response(*args, **kwargs):
    if 'context' in kwargs and 'request' in kwargs['context']:
        request = kwargs['context']['request']
        if hasattr(request.state, 'is_aisbf_cloud'):
            kwargs['context']['is_aisbf_cloud'] = request.state.is_aisbf_cloud
        if hasattr(request.state, 'welcome_shown'):
            kwargs['context']['welcome_shown'] = request.state.welcome_shown
    return original_template_response(*args, **kwargs)

templates.TemplateResponse = patched_template_response

# Add MD5 filter for Gravatar
import hashlib
templates.env.filters['md5'] = lambda s: hashlib.md5(s.lower().encode('utf-8')).hexdigest() if s else ''

# Add custom template globals for proxy-aware URL generation
def setup_template_globals():
    """Setup Jinja2 template globals for proxy-aware URLs"""
    templates.env.globals['url_for'] = url_for
    templates.env.globals['get_base_url'] = get_base_url
    templates.env.globals['__version__'] = __version__
    # Add md5 filter for Gravatar email hashing (handles None/empty values gracefully)
    def md5_filter(s):
        if not s:
            # Fallback to empty string hash for users without email
            return hashlib.md5(b'').hexdigest().lower()
        return hashlib.md5(s.encode('utf-8')).hexdigest().lower()
    templates.env.filters['md5'] = md5_filter
    # Clear the template cache to avoid stale cache issues
    templates.env.cache.clear()

# Call setup after templates are initialized
setup_template_globals()

# Session secret key generation function
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
# Note: SessionMiddleware will be added AFTER the @app.middleware decorators
# to ensure proper middleware execution order

# SHA-256 of the factory-default "admin" password. If the stored hash still
# matches this value the admin hasn't changed their password yet.
_DEFAULT_ADMIN_SHA256 = '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'

# Dashboard paths the user may visit even when must_change_password is set
_MUST_CHANGE_PASSWORD_WHITELIST = (
    '/dashboard/settings',
    '/dashboard/logout',
    '/api/admin/settings/',
)

# --- Login rate limiter ---
# Keyed by (ip, username); value is list of failure timestamps.
_login_failures: dict = {}
_LOGIN_MAX_ATTEMPTS = 10   # failures before lockout
_LOGIN_WINDOW_SECS  = 300  # 5-minute sliding window
_LOGIN_LOCKOUT_SECS = 600  # 10-minute lockout after max failures

def _login_rate_limit_check(ip: str, username: str) -> bool:
    """Return True (blocked) when too many recent failures exist."""
    key = f"{ip}:{username.lower()}"
    now = time.time()
    attempts = [t for t in _login_failures.get(key, []) if now - t < _LOGIN_WINDOW_SECS]
    _login_failures[key] = attempts
    return len(attempts) >= _LOGIN_MAX_ATTEMPTS

def _login_record_failure(ip: str, username: str) -> None:
    key = f"{ip}:{username.lower()}"
    _login_failures.setdefault(key, []).append(time.time())

def _login_clear_failures(ip: str, username: str) -> None:
    _login_failures.pop(f"{ip}:{username.lower()}", None)

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
# Strong references to fire-and-forget tasks so the GC does not cancel them
_background_tasks: set = set()

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

    logger.debug(f"=== FETCH_PROVIDER_MODELS START: {provider_id} ===")
    try:
        logger.debug(f"Fetching models from provider: {provider_id} (user_id: {user_id})")

        # Create request handler with correct user context
        logger.debug(f"Creating RequestHandler for provider '{provider_id}' with user_id: {user_id}")
        request_handler = RequestHandler(user_id=user_id)
        logger.debug(f"RequestHandler created successfully for provider '{provider_id}'")

        # Create a dummy request object for the handler
        logger.debug(f"Creating dummy request object for provider '{provider_id}'")
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
        logger.debug(f"Dummy request created for path: {scope['path']}")

        # Fetch models from provider API (use user context if available)
        logger.debug(f"Calling handle_model_list for provider '{provider_id}'")
        models = await request_handler.handle_model_list(dummy_request, provider_id)
        logger.debug(f"handle_model_list returned {len(models) if models else 0} models for provider '{provider_id}'")

        # Cache the results - separate cache for users vs global
        cache_key = f"{provider_id}:{user_id}" if user_id else provider_id
        _model_cache[cache_key] = models
        _model_cache_timestamps[cache_key] = time.time()

        logger.info(f"Cached {len(models)} models from provider: {provider_id}")
        logger.debug(f"=== FETCH_PROVIDER_MODELS SUCCESS: {provider_id} ===")
        return models
    except Exception as e:
        logger.error(f"=== FETCH_PROVIDER_MODELS FAILED: {provider_id} ===")
        logger.error(f"Failed to fetch models from provider {provider_id}: {e}")
        logger.debug(f"Error type: {type(e).__name__}")
        logger.debug(f"Error details: {str(e)}", exc_info=True)
        logger.debug(f"=== FETCH_PROVIDER_MODELS END (FAILED): {provider_id} ===")
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
                    except Exception:
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
            if db_config:
                logger.info(f"Database config from aisbf.json: type={db_config.type if hasattr(db_config, 'type') else db_config.get('type')}, mysql_host={db_config.mysql_host if hasattr(db_config, 'mysql_host') else db_config.get('mysql_host')}, mysql_database={db_config.mysql_database if hasattr(db_config, 'mysql_database') else db_config.get('mysql_database')}")
                # Convert to dict if it's a Pydantic model
                if hasattr(db_config, 'model_dump'):
                    db_config = db_config.model_dump()
                elif hasattr(db_config, 'dict'):
                    db_config = db_config.dict()
            else:
                logger.warning("No database config found in aisbf.json, using defaults")
            DatabaseRegistry.get_config_database(db_config)
            
            # Initialize analytics after database is set up
            from aisbf.analytics import initialize_analytics
            db = DatabaseRegistry.get_config_database()
            initialize_analytics(db)
            logger.info("Analytics module initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
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
    logger.info("=== STARTUP MODEL PRE-FETCHING ===")
    logger.info("Pre-fetching models from providers with dynamic model lists...")
    prefetch_count = 0
    total_providers_checked = 0

    for provider_id, provider_config in config.providers.items():
        total_providers_checked += 1
        logger.debug(f"Checking provider '{provider_id}' for model pre-fetching...")

        if not (hasattr(provider_config, 'models') and provider_config.models):
            logger.debug(f"Provider '{provider_id}' has no local model config, attempting pre-fetch")

            # For Kilo providers, check if any authentication method is available
            provider_type = getattr(provider_config, 'type', '')
            if provider_type in ('kilo', 'kilocode'):
                logger.debug(f"Kilo provider '{provider_id}' detected, validating authentication...")
                has_valid_auth = False

                # Check 1: API key
                logger.debug(f"  Checking API key for provider '{provider_id}'...")
                api_key = getattr(provider_config, 'api_key', None)
                if api_key and not api_key.startswith('YOUR_'):
                    has_valid_auth = True
                    logger.info(f"  ✓ Kilo provider '{provider_id}' has API key configured, will fetch models")
                else:
                    logger.debug(f"  ✗ API key not configured or placeholder for provider '{provider_id}'")

                # Check 2: OAuth2 credentials file
                if not has_valid_auth:
                    logger.debug(f"  Checking OAuth2 credentials file for provider '{provider_id}'...")
                    try:
                        from aisbf.auth.kilo import KiloOAuth2
                        kilo_config = getattr(provider_config, 'kilo_config', None)
                        credentials_file = None
                        api_base = getattr(provider_config, 'endpoint', 'https://api.kilo.ai')

                        if kilo_config and isinstance(kilo_config, dict):
                            credentials_file = kilo_config.get('credentials_file')
                            logger.debug(f"    Credentials file from config: {credentials_file}")
                            # Override api_base from kilo_config if present
                            if 'api_base' in kilo_config and kilo_config['api_base']:
                                api_base = kilo_config['api_base']
                                logger.debug(f"    API base from config: {api_base}")

                        logger.debug(f"    Attempting OAuth2 authentication check...")
                        oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
                        if oauth2.is_authenticated():
                            has_valid_auth = True
                            logger.info(f"  ✓ Kilo provider '{provider_id}' has valid OAuth2 credentials file, will fetch models")
                        else:
                            logger.debug(f"  ✗ OAuth2 not authenticated for provider '{provider_id}'")
                    except Exception as e:
                        logger.warning(f"  ✗ Kilo provider '{provider_id}' OAuth2 file check failed: {e}")
                        logger.debug(f"    OAuth2 check error details: {type(e).__name__}: {str(e)}", exc_info=True)

                # Check 3: Database-stored credentials (uploaded via dashboard)
                if not has_valid_auth:
                    logger.debug(f"  Checking database credentials for provider '{provider_id}'...")
                    try:
                        db = DatabaseRegistry.get_config_database()
                        if db:
                            logger.debug(f"    Database available, checking for uploaded credentials...")
                            # Check for uploaded credentials files for this provider
                            auth_files = db.get_user_auth_files(0, provider_id)  # 0 for admin/global
                            if auth_files:
                                logger.debug(f"    Found {len(auth_files)} auth files for provider '{provider_id}'")
                                for auth_file in auth_files:
                                    file_type = auth_file.get('file_type', '')
                                    file_path = auth_file.get('file_path', '')
                                    logger.debug(f"      Checking auth file: type={file_type}, path={file_path}")
                                    if file_type in ('credentials', 'kilo_credentials', 'config') and file_path:
                                        if os.path.exists(file_path):
                                            has_valid_auth = True
                                            logger.info(f"  ✓ Kilo provider '{provider_id}' has uploaded credentials in database, will fetch models")
                                            logger.debug(f"    Using credentials file: {file_path}")
                                            break
                                        else:
                                            logger.debug(f"    Credentials file does not exist: {file_path}")
                            else:
                                logger.debug(f"    No auth files found in database for provider '{provider_id}'")
                        else:
                            logger.debug(f"    Database not available for credentials check")
                    except Exception as e:
                        logger.warning(f"  ✗ Kilo provider '{provider_id}' database credentials check failed: {e}")
                        logger.debug(f"    Database credentials check error details: {type(e).__name__}: {str(e)}", exc_info=True)

                if not has_valid_auth:
                    logger.info(f"Skipping model prefetch for Kilo provider '{provider_id}' (no valid authentication method found)")
                    logger.debug(f"  Authentication methods checked: API key, OAuth2 file, database credentials")
                    continue
            else:
                logger.debug(f"Provider '{provider_id}' is not Kilo type (type: {provider_type}), proceeding with fetch")

            logger.info(f"Attempting to pre-fetch models from provider '{provider_id}'...")
            try:
                models = await fetch_provider_models(provider_id)
                if models:
                    prefetch_count += 1
                    logger.info(f"✓ Successfully pre-fetched {len(models)} models from provider: {provider_id}")
                    logger.debug(f"  Models: {[m.get('id', m.get('name', 'unknown')) for m in models[:5]]}" + (f" ... and {len(models)-5} more" if len(models) > 5 else ""))
                else:
                    logger.warning(f"✗ Pre-fetch returned empty model list from provider '{provider_id}'")
            except Exception as e:
                logger.error(f"✗ Failed to pre-fetch models from provider '{provider_id}': {e}")
                logger.debug(f"  Pre-fetch error details for '{provider_id}': {type(e).__name__}: {str(e)}", exc_info=True)
        else:
            logger.debug(f"Provider '{provider_id}' has local model config ({len(provider_config.models)} models), skipping pre-fetch")

    logger.info(f"=== MODEL PRE-FETCHING COMPLETE ===")
    logger.info(f"Checked {total_providers_checked} providers, successfully pre-fetched from {prefetch_count} providers")
    
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

            # Check authentication configuration
            provider_type = getattr(provider_config, 'type', '')
            if provider_config.api_key_required:
                if provider_config.api_key:
                    logger.info(f"  API Key: Configured ✓")
                    logger.info(f"  Status: Ready to use")
                else:
                    logger.warning(f"  API Key: NOT CONFIGURED ✗")
                    logger.warning(f"  Status: WILL BE SKIPPED - API key required but not provided")
                    logger.warning(f"  Action: Add api_key to provider configuration in providers.json")
            elif provider_type in ('kilo', 'kilocode'):
                # Special handling for Kilo providers with multiple auth methods
                logger.info(f"  Authentication: Multiple methods supported")
                auth_methods = []

                # Check API key
                api_key = getattr(provider_config, 'api_key', None)
                if api_key and not api_key.startswith('YOUR_'):
                    auth_methods.append("API Key ✓")
                else:
                    auth_methods.append("API Key ✗")

                # Check OAuth2 file
                try:
                    from aisbf.auth.kilo import KiloOAuth2
                    kilo_config = getattr(provider_config, 'kilo_config', None)
                    credentials_file = None
                    if kilo_config and isinstance(kilo_config, dict):
                        credentials_file = kilo_config.get('credentials_file')
                    oauth2 = KiloOAuth2(credentials_file=credentials_file)
                    if oauth2.is_authenticated():
                        auth_methods.append("OAuth2 File ✓")
                    else:
                        auth_methods.append("OAuth2 File ✗")
                except Exception:
                    auth_methods.append("OAuth2 File ✗ (check failed)")

                # Check database credentials
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        auth_files = db.get_user_auth_files(0, provider_id)
                        if auth_files:
                            has_valid_file = False
                            for auth_file in auth_files:
                                file_type = auth_file.get('file_type', '')
                                file_path = auth_file.get('file_path', '')
                                if file_type in ('credentials', 'kilo_credentials', 'config') and file_path and os.path.exists(file_path):
                                    has_valid_file = True
                                    break
                            if has_valid_file:
                                auth_methods.append("Database Credentials ✓")
                            else:
                                auth_methods.append("Database Credentials ✗ (files exist but invalid)")
                        else:
                            auth_methods.append("Database Credentials ✗ (no files)")
                    else:
                        auth_methods.append("Database Credentials ✗ (no database)")
                except Exception:
                    auth_methods.append("Database Credentials ✗ (check failed)")

                logger.info(f"  Auth Methods: {', '.join(auth_methods)}")

                if any("✓" in method for method in auth_methods):
                    logger.info(f"  Status: Ready to use (at least one auth method available)")
                else:
                    logger.warning(f"  Status: WILL BE SKIPPED - No valid authentication methods found")
                    logger.warning(f"  Action: Configure API key, OAuth2 credentials file, or upload credentials via dashboard")
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
                logger.info(f"  Models Configured: None (will use provider's default models or dynamic fetching)")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("")
    
    # Initialize payment service
    global payment_service
    try:
        # Load encryption key from database, fallback to env var, then generate temporary
        db_manager = DatabaseRegistry.get_config_database()
        encryption_key = db_manager.get_encryption_key()
        encryption_key_source = 'database'
        
        if not encryption_key:
            encryption_key = os.getenv('ENCRYPTION_KEY')
            encryption_key_source = 'environment'
        
        if not encryption_key:
            encryption_key = Fernet.generate_key().decode()
            encryption_key_source = 'generated'
            db_manager.save_encryption_key(encryption_key)
            logger.warning("No ENCRYPTION_KEY set in database or environment, generated and saved new key to database")
        else:
            logger.info(f"Loaded ENCRYPTION_KEY from {encryption_key_source}")
        
        payment_config = {
            'encryption_key': encryption_key,
            'encryption_key_source': encryption_key_source,
            'base_url': os.getenv('BASE_URL', 'http://localhost:17765'),
            'currency_code': 'EUR',
            'btc_confirmations': 3,
            'eth_confirmations': 12
        }
        
        from aisbf.payments.service import PaymentService
        from aisbf.payments.migrations import PaymentMigrations
        
        db_manager = DatabaseRegistry.get_config_database()
        
        # Run payment system migrations before initializing service
        try:
            migrations = PaymentMigrations(db_manager)
            migrations.run_migrations()
            logger.info("Payment system migrations completed")
        except Exception as migration_error:
            logger.error(f"Failed to run payment migrations: {migration_error}")
            raise
        
        payment_service = PaymentService(db_manager, payment_config)
        await payment_service.initialize()
        app.state.payment_service = payment_service
        
        logger.info("Payment service started")
    except Exception as e:
        logger.error(f"Failed to initialize payment service: {e}")
        # Continue startup even if payment service fails
    
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

# API Token Authorization Middleware
@app.middleware("http")
async def api_token_authorization_middleware(request: Request, call_next):
    """Enforce proper token scope access:
    - Global tokens (aisbf.json): CAN access global endpoints, CANNOT access user endpoints
    - User tokens (database): CAN access ONLY their own user endpoints, CANNOT access global endpoints
    """
    
    path = request.url.path
    
    # Skip authorization for non-API paths
    if (path == "/" or
        path.startswith("/dashboard") or
        path.startswith("/auth/") or
        path.startswith("/api/admin") or
        path.startswith("/api/webhooks/") or  # Webhooks don't need auth
        path == "/favicon.ico" or
        path.startswith("/.well-known/")):
        return await call_next(request)
    
    # Skip for public models endpoints (GET only)
    if request.method == "GET" and path in ["/api/models", "/api/v1/models"]:
        return await call_next(request)
    
    is_global_token = getattr(request.state, 'is_global_token', False)
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    
    # Debug logging
    logger.info(f"API Token Auth: path={path}, is_global_token={is_global_token}, user_id={user_id}")
    
    # --- USER-SPECIFIC ENDPOINTS (/api/u/*) ---
    if (path.startswith("/api/u/") or 
        path.startswith("/mcp/u/") or
        path.startswith("/api/v1/u/") or
        path.startswith("/mcp/v1/u/")):
        
        # Global tokens CANNOT access user-specific endpoints
        if is_global_token:
            return JSONResponse(
                status_code=403,
                content={"error": "Global tokens cannot access user-specific endpoints. Use the user's own API token."}
            )
        
        # Verify user is accessing their own endpoints
        path_parts = path.split('/')
        if len(path_parts) >= 4 and path_parts[2] == 'u':
            target_username = path_parts[3]
            
            # User must be authenticated with a user token
            if not user_id:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Authentication required. Use a valid user API token."}
                )
            
            db = DatabaseRegistry.get_config_database()
            authenticated_user = db.get_user_by_id(user_id)
            
            if not authenticated_user:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Invalid user token."}
                )
            
            # Debug logging
            logger.info(f"Token auth check: user_id={user_id}, authenticated_username={authenticated_user.get('username')}, target_username={target_username}")
            
            if authenticated_user['username'] != target_username:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "You can only access your own user-specific endpoints.",
                        "authenticated_as": authenticated_user['username'],
                        "requested_user": target_username
                    }
                )
            
            # Enforce token scope
            token_scope = getattr(request.state, 'token_scope', 'both')
            is_mcp_path = path.startswith("/mcp/u/") or path.startswith("/mcp/v1/u/")
            if is_mcp_path and token_scope == 'api':
                return JSONResponse(
                    status_code=403,
                    content={"error": "This token does not have MCP access. Create a token with 'mcp' or 'both' scope."}
                )
            if not is_mcp_path and token_scope == 'mcp':
                return JSONResponse(
                    status_code=403,
                    content={"error": "This token does not have API access. Create a token with 'api' or 'both' scope."}
                )
    
    # --- GLOBAL ENDPOINTS (all other API paths) ---
    else:
        # Only GLOBAL tokens can access global endpoints
        if not is_global_token:
            return JSONResponse(
                status_code=403,
                content={"error": "User tokens cannot access global endpoints. Use your user-specific endpoints at /api/u/<your-username>"}
            )
    
    # All checks passed
    return await call_next(request)


# Authentication middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Check API token authentication if enabled"""
    if server_config and server_config.get('auth_enabled', False):
        # Skip token auth for paths that use session auth or are public
        if (request.url.path == "/" or
            request.url.path.startswith("/dashboard") or
            request.url.path.startswith("/auth/") or
            request.url.path.startswith("/api/webhooks/") or
            request.url.path == "/favicon.ico" or
            request.url.path.startswith("/.well-known/")):
            response = await call_next(request)
            return response

        # /api/admin/* uses session auth — allow through only when a valid admin session exists
        if request.url.path.startswith("/api/admin"):
            expires_at = request.session.get('expires_at')
            session_valid = (
                request.session.get('logged_in') and
                request.session.get('role') == 'admin' and
                not (expires_at and int(time.time()) > expires_at)
            )
            if session_valid:
                response = await call_next(request)
                return response
            # No valid admin session — fall through to Bearer-token check below

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
            request.state.token_scope = 'api'  # global tokens are API-scope by default
            request.state.is_admin = True  # Global tokens have admin access
        else:
            # Check user API tokens
            db = DatabaseRegistry.get_config_database()
            user_auth = db.authenticate_user_token(token)

            if user_auth:
                # Store user token info in request state
                request.state.user_id = user_auth['user_id']
                request.state.token_id = user_auth['token_id']
                request.state.is_global_token = False
                request.state.token_scope = user_auth.get('scope', 'api')
                # Store user role - admin users get full access
                request.state.is_admin = (user_auth.get('role') == 'admin')
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
        request.state.token_scope = 'both'

    # Check for unverified email for logged in dashboard users
    # Only enforce email verification if:
    # 1. User is logged in to dashboard
    # 2. User is not an admin (admins bypass email verification)
    # 3. User's email is not verified
    # 4. Email verification is enabled in config
    
    # Debug: Log session state for all dashboard requests
    if request.url.path.startswith("/dashboard"):
        logger.debug(f"Dashboard request to {request.url.path} - Session: logged_in={request.session.get('logged_in')}, email_verified={request.session.get('email_verified')}, role={request.session.get('role')}")
    
    if (request.url.path.startswith("/dashboard") and
        request.session.get('logged_in') and
        request.session.get('role') != 'admin'):

        # Check if email verification is enabled in config
        require_verification = False
        if config and hasattr(config, 'aisbf') and hasattr(config.aisbf, 'signup'):
            require_verification = getattr(config.aisbf.signup, 'require_email_verification', False)

        logger.debug(f"Email verification check - require_verification={require_verification}, email_verified={request.session.get('email_verified')}")

        # Check if user's email verification status has changed since login
        # This handles the case where email was verified in another browser/session
        user_id = request.session.get('user_id')
        if user_id and require_verification:
            try:
                db = DatabaseRegistry.get_config_database()
                current_user = db.get_user_by_id(user_id)
                if current_user and current_user.get('email_verified') != request.session.get('email_verified'):
                    # Email verification status changed, log user out
                    logger.info(f"Email verification status changed for user {user_id}, logging out session")
                    request.session.clear()
                    return RedirectResponse(url=url_for(request, "/dashboard/login") + "?error=Your email verification status has changed. Please log in again.", status_code=303)
            except Exception as e:
                logger.error(f"Error checking email verification status for user {user_id}: {e}")

        # Check if user still exists (handle case where user was deleted by admin)
        # This ensures deleted users are logged out on their next request
        user_id = request.session.get('user_id')
        if user_id:
            try:
                db = DatabaseRegistry.get_config_database()
                current_user = db.get_user_by_id(user_id)
                if not current_user:
                    # User has been deleted, log them out
                    logger.info(f"User {user_id} has been deleted, logging out session")
                    request.session.clear()
                    return RedirectResponse(url=url_for(request, "/dashboard/login") + "?error=Your account has been deleted. Please contact an administrator.", status_code=303)
            except Exception as e:
                logger.error(f"Error checking user existence for user {user_id}: {e}")

        # Only check email_verified if verification is required
        if require_verification and not request.session.get('email_verified'):
            # Allow only specific routes for unverified users
            # These are the ONLY pages an unverified user can access
            allowed_routes = [
                "/dashboard/verify",
                "/dashboard/resend-verification",
                "/dashboard/logout",
                "/dashboard/verify-email"
            ]
            
            # Check if current path matches any allowed route exactly or starts with it
            is_allowed = False
            for route in allowed_routes:
                if request.url.path == route or request.url.path == route + "/":
                    is_allowed = True
                    break
            
            if not is_allowed:
                # Block access and redirect to verify page
                redirect_url = url_for(request, "/dashboard/verify")
                logger.info(f"BLOCKING unverified user access to {request.url.path}, redirecting to: {redirect_url}")
                return RedirectResponse(url=redirect_url, status_code=303)

    response = await call_next(request)
    return response


# Global API Token Access Control Middleware
# Account Tier Limit Enforcement Middleware
@app.middleware("http")
async def tier_limit_middleware(request: Request, call_next):
    """Validate user account tier limits before processing API requests"""
    
    # Skip tier checks for non-API paths
    if (request.url.path == "/" or
        request.url.path.startswith("/dashboard") or
        request.url.path == "/favicon.ico" or
        request.url.path.startswith("/.well-known/") or
        request.url.path.startswith("/mcp") or
        request.url.path.startswith("/auth/")):
        return await call_next(request)
    
    # Skip tier checks for GET models endpoints
    if request.method == "GET" and (request.url.path.endswith("/models") or request.url.path.endswith("/models/")):
        return await call_next(request)
    
    # Only apply tier limits for authenticated users
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        return await call_next(request)
    
    db = DatabaseRegistry.get_config_database()
    
    # Get user tier and current usage
    tier = db.get_user_tier(user_id)
    if not tier:
        # Default free tier - allow all requests
        return await call_next(request)
    
    # Check if subscription is active and not expired
    subscription = db.get_user_subscription(user_id)
    if subscription:
        from datetime import datetime
        if subscription['expires_at'] and datetime.fromisoformat(subscription['expires_at']) < datetime.now():
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Subscription expired",
                    "message": "Your subscription has expired. Please renew to continue using the service.",
                    "code": "subscription_expired"
                }
            )
    
    # Get current usage statistics
    usage = db.get_user_usage(user_id)
    
    # Validate all tier limits with standard semantics:
    # -1 = unlimited, 0 = blocked, >0 = actual limit
    
    # 1. Max requests per day
    if tier['max_requests_per_day'] == 0:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Requests not permitted",
                "message": "Your account tier does not allow API requests. Please upgrade your plan.",
                "code": "requests_blocked"
            }
        )
    elif tier['max_requests_per_day'] > 0 and usage['requests_today'] >= tier['max_requests_per_day']:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Daily request limit exceeded",
                "message": f"You have reached your daily request limit of {tier['max_requests_per_day']} requests. Upgrade your plan for higher limits.",
                "limit": tier['max_requests_per_day'],
                "current": usage['requests_today'],
                "code": "daily_limit_exceeded"
            }
        )
    
    # 2. Max requests per month
    if tier['max_requests_per_month'] == 0:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Requests not permitted",
                "message": "Your account tier does not allow API requests. Please upgrade your plan.",
                "code": "requests_blocked"
            }
        )
    elif tier['max_requests_per_month'] > 0 and usage['requests_month'] >= tier['max_requests_per_month']:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Monthly request limit exceeded",
                "message": f"You have reached your monthly request limit of {tier['max_requests_per_month']} requests. Upgrade your plan for higher limits.",
                "limit": tier['max_requests_per_month'],
                "current": usage['requests_month'],
                "code": "monthly_limit_exceeded"
            }
        )
    
    # 3. Max providers check (only when creating providers)
    if request.url.path.endswith("/dashboard/user/providers") and request.method == "POST":
        if tier['max_providers'] == 0:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Provider creation not permitted",
                    "message": "Your account tier does not allow configuring providers. Please upgrade your plan.",
                    "code": "providers_blocked"
                }
            )
        elif tier['max_providers'] > 0 and usage['providers_count'] >= tier['max_providers']:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Maximum providers limit reached",
                    "message": f"You have reached your limit of {tier['max_providers']} providers. Upgrade your plan for higher limits.",
                    "limit": tier['max_providers'],
                    "current": usage['providers_count'],
                    "code": "providers_limit_exceeded"
                }
            )
    
    # 4. Max rotations check (only when creating rotations)
    if request.url.path.endswith("/dashboard/user/rotations") and request.method == "POST":
        if tier['max_rotations'] == 0:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Rotation creation not permitted",
                    "message": "Your account tier does not allow configuring rotations. Please upgrade your plan.",
                    "code": "rotations_blocked"
                }
            )
        elif tier['max_rotations'] > 0 and usage['rotations_count'] >= tier['max_rotations']:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Maximum rotations limit reached",
                    "message": f"You have reached your limit of {tier['max_rotations']} rotations. Upgrade your plan for higher limits.",
                    "limit": tier['max_rotations'],
                    "current": usage['rotations_count'],
                    "code": "rotations_limit_exceeded"
                }
            )
    
    # 5. Max autoselections check (only when creating autoselects)
    if request.url.path.endswith("/dashboard/user/autoselects") and request.method == "POST":
        if tier['max_autoselections'] == 0:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Autoselection creation not permitted",
                    "message": "Your account tier does not allow configuring autoselections. Please upgrade your plan.",
                    "code": "autoselections_blocked"
                }
            )
        elif tier['max_autoselections'] > 0 and usage['autoselects_count'] >= tier['max_autoselections']:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Maximum autoselections limit reached",
                    "message": f"You have reached your limit of {tier['max_autoselections']} autoselections. Upgrade your plan for higher limits.",
                    "limit": tier['max_autoselections'],
                    "current": usage['autoselects_count'],
                    "code": "autoselections_limit_exceeded"
                }
            )
    
    # All limits passed, process request
    response = await call_next(request)
    
    # Record request usage after successful processing
    if request.method == "POST" and (
        request.url.path.endswith("/chat/completions") or
        request.url.path.endswith("/completions") or
        request.url.path.endswith("/embeddings") or
        request.url.path.endswith("/audio/transcriptions") or
        request.url.path.endswith("/audio/speech") or
        request.url.path.endswith("/images/generations")
    ):
        # Increment request counters asynchronously; keep a strong reference so GC cannot cancel it
        import asyncio
        _t = asyncio.create_task(db.increment_user_request_count(user_id))
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)
    
    return response

async def record_token_usage_async(user_id: int, token_id: int):
    """Asynchronously record token usage"""
    try:
        db = DatabaseRegistry.get_config_database()
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

# CORS middleware — wildcard origins are incompatible with allow_credentials=True
# (browsers reject credentialed cross-origin requests to "*"). API clients
# (curl, SDK) never send cookies, so credentials are not needed here.
# Dashboard authentication relies on session cookies which are same-origin only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard context middleware - adds is_aisbf_cloud and welcome_shown to all template contexts
@app.middleware("http")
async def dashboard_context_middleware(request: Request, call_next):
    if request.url.path.startswith("/dashboard") and 'session' in request.scope:
        # ALWAYS set is_aisbf_cloud for ALL dashboard paths (to show footer links everywhere)
        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        request.state.is_aisbf_cloud = is_cloud or is_onion
        
        # Only handle welcome_shown logic when user is LOGGED IN
        if request.session.get('logged_in', False):
            # Check if welcome modal has been shown this session
            if not request.session.get('welcome_shown', False) and request.state.is_aisbf_cloud:
                request.state.welcome_shown = False
            else:
                request.state.welcome_shown = request.session.get('welcome_shown', False)
        else:
            # For unauthenticated users, never show welcome modal
            request.state.welcome_shown = True
    
    response = await call_next(request)
    return response


# Add session middleware AFTER the @app.middleware decorators
# This ensures SessionMiddleware runs before auth_middleware and tier_limit_middleware
# Middleware execution order: last added = first executed
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    max_age=30 * 24 * 60 * 60,  # 30 days
    same_site="lax",            # prevents cross-site request forgery
    https_only=os.environ.get("AISBF_HTTPS", "false").lower() == "true",
)

# Add proxy headers middleware LAST so it executes FIRST
# This ensures proxy headers are processed before any other middleware (including auth_middleware)
app.add_middleware(ProxyHeadersMiddleware)

# Helper function for API authentication
async def get_current_user(request: Request) -> dict:
    """Get current authenticated user from request state"""
    user_id = getattr(request.state, 'user_id', None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Get user from database
    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user

# Crypto payment API endpoints
@app.get("/api/crypto/addresses")
async def get_crypto_addresses(request: Request):
    """Get user's crypto addresses"""
    current_user = await get_current_user(request)
    addresses = await payment_service.get_user_crypto_addresses(current_user['id'])
    return {'addresses': addresses}


@app.get("/api/crypto/wallets")
async def get_crypto_wallets(request: Request):
    """Get user's crypto wallet balances"""
    current_user = await get_current_user(request)
    balances = await payment_service.get_user_wallet_balances(current_user['id'])
    return {'wallets': balances}


@app.post("/api/payment-methods/crypto")
async def add_crypto_payment_method(request: Request):
    """Add crypto payment method"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.add_crypto_payment_method(
        current_user['id'],
        body['crypto_type']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


# Fiat payment API endpoints
@app.post("/api/payment-methods/stripe")
async def add_stripe_payment_method(request: Request):
    """Add Stripe payment method"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.add_stripe_payment_method(
        current_user['id'],
        body['payment_method_token']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/payment-methods/paypal/initiate")
async def initiate_paypal_payment_method(request: Request):
    """Initiate PayPal billing agreement"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.initiate_paypal_billing_agreement(
        current_user['id'],
        body['return_url'],
        body['cancel_url']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/payment-methods/paypal/complete")
async def complete_paypal_payment_method(request: Request):
    """Complete PayPal billing agreement"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.complete_paypal_billing_agreement(
        current_user['id'],
        body['token']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.get("/api/payment-methods")
async def get_payment_methods(request: Request):
    """Get user's payment methods"""
    current_user = await get_current_user(request)
    methods = await payment_service.get_payment_methods(current_user['id'])
    return {'payment_methods': methods}


@app.delete("/api/payment-methods/{payment_method_id}")
async def delete_payment_method(payment_method_id: int, request: Request):
    """Delete payment method"""
    current_user = await get_current_user(request)
    
    result = await payment_service.delete_payment_method(
        current_user['id'],
        payment_method_id
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result

# Wallet API routes
try:
    from aisbf.payments.wallet.routes import router as wallet_router
    app.include_router(wallet_router)
except ImportError:
    logger.warning("Wallet routes not available - wallet functionality disabled")


@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    stripe_signature = request.headers.get("Stripe-Signature")
    payload = await request.body()
    
    result = await payment_service.stripe_handler.handle_webhook(
        payload,
        stripe_signature
    )
    
    return result


@app.post("/api/webhooks/paypal")
async def paypal_webhook(request: Request):
    """Handle PayPal webhooks"""
    payload = await request.json()
    headers = dict(request.headers)

    result = await payment_service.paypal_handler.handle_webhook(payload, headers)

    if result.get('status') == 'error':
        # Return 400 so PayPal retries rather than treating the error as success
        return JSONResponse(status_code=400, content=result)
    return result


# Subscription API endpoints
@app.post("/api/subscriptions")
async def create_subscription(request: Request):
    """Create new subscription"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.create_subscription(
        current_user['id'],
        body['tier_id'],
        body['payment_method_id'],
        body['billing_cycle']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/subscriptions/upgrade")
async def upgrade_subscription(request: Request):
    """Upgrade subscription"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.upgrade_subscription(
        current_user['id'],
        body['tier_id']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/subscriptions/downgrade")
async def downgrade_subscription(request: Request):
    """Downgrade subscription"""
    current_user = await get_current_user(request)
    body = await request.json()
    
    result = await payment_service.downgrade_subscription(
        current_user['id'],
        body['tier_id']
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.post("/api/subscriptions/cancel")
async def cancel_subscription(request: Request):
    """Cancel subscription"""
    current_user = await get_current_user(request)
    
    result = await payment_service.cancel_subscription(current_user['id'])
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


@app.get("/api/subscriptions/status")
async def get_subscription_status(request: Request):
    """Get subscription status"""
    current_user = await get_current_user(request)
    status = await payment_service.get_subscription_status(current_user['id'])
    return {'subscription': status}

# User search API endpoint for autocomplete
@app.get("/api/users/search")
async def search_users(request: Request, q: str = Query("", min_length=0)):
    """Search users by username for autocomplete (admin only)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Check if user is admin
    is_admin = request.session.get('role') == 'admin'
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    db = DatabaseRegistry.get_config_database()
    if not db:
        return {"users": []}
    
    # Get all users
    all_users = db.get_users()
    
    # Filter by query string (case-insensitive)
    if q:
        filtered_users = [
            {"id": user['id'], "username": user['username'], "role": user.get('role', 'user')}
            for user in all_users
            if q.lower() in user['username'].lower()
        ]
    else:
        filtered_users = [
            {"id": user['id'], "username": user['username'], "role": user.get('role', 'user')}
            for user in all_users
        ]
    
    # Limit to 50 results
    return {"users": filtered_users[:50]}

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
    user_filter: Optional[str] = Query(None),
    global_only: Optional[str] = Query(None)
):
    """Token usage analytics dashboard"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.analytics import get_analytics
    
    # Get analytics and database
    db = DatabaseRegistry.get_config_database()
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
    
    # Handle preset time ranges
    if time_range == 'yesterday':
        # Yesterday: from 00:00:00 to 23:59:59 of previous day
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        from_datetime = today - timedelta(days=1)
        to_datetime = today - timedelta(microseconds=1)
    elif time_range == 'custom':
        # If custom date range is provided, use it
        if not from_datetime or not to_datetime:
            # Default to last 24h if custom selected but no dates provided
            time_range = '24h'
    
    # If custom date range is provided, use custom mode
    if from_datetime and to_datetime and time_range not in ['yesterday']:
        time_range = 'custom'
    
    # Check user role and apply user restriction
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    # Parse user_filter from string to int, handling empty strings
    user_filter_int = None
    if user_filter:
        try:
            user_filter_int = int(user_filter)
        except (ValueError, TypeError):
            user_filter_int = None
    
    # Handle global_only filter - if checked, set user_filter to -1 (special value for global requests)
    if global_only == '1':
        user_filter_int = -1  # Special value to indicate "only global requests"
    
    # For non-admin users, force user filter to current user
    if not is_admin and current_user_id is not None:
        user_filter_int = current_user_id
    
    # Get all users for filter dropdown (only for admins)
    raw_users = db.get_users() if db and is_admin else []
    all_users = [
        {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in u.items()}
        for u in raw_users
    ]
    
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
        provider_stats = [analytics.get_provider_stats(provider_filter, from_datetime, to_datetime, user_filter=user_filter_int)]
    else:
        provider_stats = analytics.get_all_providers_stats(from_datetime, to_datetime, user_filter=user_filter_int)
    
    # Get token usage over time (with optional filters)
    token_over_time = analytics.get_token_usage_over_time(
        provider_id=provider_filter,
        time_range=time_range,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        user_filter=user_filter_int
    )
    
    # Get model performance (with optional filters)
    model_performance = analytics.get_model_performance(
        provider_filter=provider_filter,
        model_filter=model_filter,
        rotation_filter=rotation_filter,
        autoselect_filter=autoselect_filter,
        user_filter=user_filter_int,
        from_datetime=from_datetime,
        to_datetime=to_datetime
    )
    
    # Get cost overview
    cost_overview = analytics.get_cost_overview(from_datetime, to_datetime, user_filter=user_filter_int)
    
    # Placeholder for recommendations and optimization savings (not yet implemented)
    recommendations = []
    optimization_savings = 0
    
    # Get date range usage summary
    date_range_usage = None
    if from_datetime or to_datetime:
        start = from_datetime or (datetime.now() - timedelta(days=1))
        end = to_datetime or datetime.now()
        date_range_usage = analytics.get_token_usage_by_date_range(provider_filter, start, end, user_filter=user_filter_int)

    # Handle Decimal values from MySQL for JSON serialization
    def decimal_default(obj):
        if isinstance(obj, Decimal):
            return int(obj)
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    return templates.TemplateResponse(
        request=request,
        name="dashboard/analytics.html",
        context={
        "request": request,
        "session": request.session,
        "is_admin": is_admin,
        "provider_stats": provider_stats,
        "token_over_time": json.dumps(token_over_time, default=decimal_default),
        "model_performance": model_performance,
        "cost_overview": cost_overview,
        "recommendations": recommendations,
        "optimization_savings": optimization_savings,
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
        "selected_user": user_filter,
        "global_only": global_only,
        "currency_symbol": DatabaseRegistry.get_config_database().get_currency_settings().get('currency_symbol', '$')
    }
    )

@app.get("/dashboard/api/auth-check")
async def dashboard_auth_check(request: Request):
    """Return authentication status for OAuth popup polling."""
    from fastapi.responses import JSONResponse
    authenticated = bool(request.session.get('logged_in') and request.session.get('user_id'))
    return JSONResponse({"authenticated": authenticated})


@app.get("/dashboard/profile-pic")
async def dashboard_profile_pic(request: Request):
    """Serve the logged-in user's profile picture from the database."""
    from fastapi.responses import Response
    user_id = request.session.get('user_id')
    if not user_id:
        return Response(status_code=404)
    try:
        db = DatabaseRegistry.get_config_database()
        user = db.get_user_by_id(user_id)
        pic = user.get('profile_pic') if user else None
        if not pic:
            return Response(status_code=404)
        # pic is stored as a data URL: "data:<mime>;base64,<data>"
        if pic.startswith('data:'):
            header, b64data = pic.split(',', 1)
            mime = header.split(':')[1].split(';')[0]
            import base64
            img_bytes = base64.b64decode(b64data)
            return Response(content=img_bytes, media_type=mime,
                            headers={"Cache-Control": "private, max-age=3600"})
        # If it's a plain URL, redirect
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=pic)
    except Exception:
        return Response(status_code=404)


@app.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page(request: Request):
    """Show dashboard login page"""
    import logging

    logger = logging.getLogger(__name__)
    try:
        # Check if signup is enabled
        signup_enabled = False
        if config and hasattr(config, 'aisbf') and config.aisbf:
            signup_enabled = getattr(config.aisbf.signup, 'enabled', False) if config.aisbf.signup else False

        # Check if SMTP is enabled
        smtp_enabled = False
        if config and hasattr(config, 'aisbf') and config.aisbf and hasattr(config.aisbf, 'smtp') and config.aisbf.smtp:
            smtp_enabled = getattr(config.aisbf.smtp, 'enabled', False)

        # Check for signup success notification
        show_verify_email = request.query_params.get('signup') == 'success' and smtp_enabled

        # Check for error message in query params
        error_message = request.query_params.get('error')

        # Check for success message in query params
        success_message = request.query_params.get('success')

        # Check if running on AISBF Cloud domain (for footer links)
        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        # Get and render template using templates Jinja2Templates instance
        template = templates.get_template("dashboard/login.html")
        html_content = template.render(
            request=request, 
            signup_enabled=signup_enabled, 
            smtp_enabled=smtp_enabled, 
            show_verify_email=show_verify_email, 
            error=error_message, 
            success=success_message, 
            config=config.aisbf if config and config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True  # Never show welcome modal on login page
        )

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering login page: {e}", exc_info=True)
        raise

@app.get("/auth/logincheck")
async def auth_logincheck(request: Request):
    """Serve JavaScript that redirects to dashboard if user is logged in"""
    # Check if user is logged in
    is_logged_in = request.session.get('logged_in', False)
    
    # Check if session has expired
    if is_logged_in:
        expires_at = request.session.get('expires_at')
        if expires_at and int(time.time()) > expires_at:
            is_logged_in = False
    
    # Generate JavaScript response
    if is_logged_in:
        # Get the dashboard path (not full URL)
        root_path = request.scope.get("root_path", "")
        dashboard_path = f"{root_path}/dashboard"
        
        js_content = f"""
(function() {{
    // Redirect to dashboard if logged in
    if (window.location.pathname !== '{dashboard_path}') {{
        window.location.href = '{dashboard_path}';
    }}
}})();
"""
    else:
        js_content = """
(function() {
    // User not logged in, do nothing
})();
"""
    
    return Response(
        content=js_content,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.post("/dashboard/login")
async def dashboard_login(request: Request, username: str = Form(...), password: str = Form(...), remember_me: bool = Form(False)):
    """Handle dashboard login"""
    client_ip = request.client.host if request.client else "unknown"

    # Rate-limit check before touching credentials
    if _login_rate_limit_check(client_ip, username):
        return RedirectResponse(
            url=url_for(request, "/dashboard/login") + "?error=Too+many+failed+attempts.+Please+wait+and+try+again.",
            status_code=303
        )

    # Try database authentication first (plain password — database.py handles hashing/verification)
    db = DatabaseRegistry.get_config_database()
    user = db.authenticate_user(username, password)

    if user:
        # Database user authenticated
        logger.info(f"User authenticated: username={username}, email={user.get('email')}, user_id={user['id']}")
        request.session['logged_in'] = True
        _login_clear_failures(client_ip, username)
        request.session['username'] = username
        request.session['display_name'] = user.get('display_name') or ''
        request.session['email'] = user.get('email') or ''
        request.session['role'] = user['role']
        request.session['user_id'] = user['id']
        request.session['has_profile_pic'] = bool(user.get('profile_pic'))
        request.session['remember_me'] = remember_me
        request.session['email_verified'] = user['email_verified']
        if remember_me:
            # Set session to expire in 30 days for remember me
            request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
        else:
            # For non-remember-me sessions, set expiry to 2 weeks (default session length)
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

        # Update last login timestamp
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (user['id'],))
            conn.commit()

        # Check if email is verified
        if not user['email_verified']:
            # Check if account is expired (24 hours old and unverified)
            from datetime import datetime, timedelta
            if user['created_at']:
                if isinstance(user['created_at'], str):
                    created_at = datetime.fromisoformat(user['created_at'])
                else:
                    # Already a datetime object
                    created_at = user['created_at']
            else:
                created_at = datetime.now()
            if datetime.now() - created_at > timedelta(hours=24):
                # Delete expired unverified account
                db.delete_user(user['id'])
                return templates.TemplateResponse(
                    request=request,
                    name="dashboard/login.html",
                    context={
                        "request": request,
                        "error": "Your account verification has expired. Please sign up again.",
                        "config": config.aisbf if config and config.aisbf else {}
                    }
                )
            else:
                # Redirect to verification page
                return RedirectResponse(url=url_for(request, "/dashboard/verify"), status_code=303)

        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    # Fallback to config admin
    dashboard_config = server_config.get('dashboard_config', {}) if server_config else {}
    stored_username = dashboard_config.get('username', 'admin')
    stored_password_hash = dashboard_config.get('password', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918')

    if username == stored_username and _db_verify_password(password, stored_password_hash):
        _login_clear_failures(client_ip, username)
        request.session['logged_in'] = True
        request.session['username'] = username
        request.session['role'] = 'admin'
        request.session['user_id'] = None  # Config admin has no user_id
        request.session['remember_me'] = remember_me
        # Flag if still using the factory-default password so we can force a change
        request.session['must_change_password'] = (stored_password_hash == _DEFAULT_ADMIN_SHA256)
        if remember_me:
            request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
        else:
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
        if request.session['must_change_password']:
            return RedirectResponse(
                url=url_for(request, "/dashboard/settings") + "?warning=default_password",
                status_code=303
            )
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    # Authentication failed — record the failure for rate limiting
    _login_record_failure(client_ip, username)
    return RedirectResponse(url=url_for(request, "/dashboard/login") + "?error=Invalid username or password", status_code=303)


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

        # Check if running on AISBF Cloud domain (for footer links)
        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        # Get and render template using templates Jinja2Templates instance
        template = templates.get_template("dashboard/signup.html")
        html_content = template.render(
            request=request, 
            config=config.aisbf if config and config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True  # Never show welcome modal on signup page
        )

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering signup page: {e}", exc_info=True)
        raise


@app.post("/dashboard/signup")
async def dashboard_signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle user signup"""
    from aisbf.email_utils import hash_password, generate_verification_token, send_verification_email
    import logging

    logger = logging.getLogger(__name__)

    # Check if signup is enabled
    signup_enabled = False
    if config and hasattr(config, 'aisbf') and config.aisbf:
        signup_enabled = getattr(config.aisbf.signup, 'enabled', False) if config.aisbf.signup else False

    if not signup_enabled:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    # Validate username format
    import re
    if not re.match(r"^[a-zA-Z0-9_.-]+$", username):
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Username can only contain letters, numbers, underscores, hyphens, and dots", "config": config.aisbf if config and config.aisbf else {}}
        )

    # Validate username length
    if len(username) < 3 or len(username) > 50:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Username must be between 3 and 50 characters", "config": config.aisbf if config and config.aisbf else {}}
        )

    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Passwords do not match", "config": config.aisbf if config and config.aisbf else {}}
        )

    # Validate password strength (minimum 8 characters)
    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Password must be at least 8 characters long", "config": config.aisbf if config and config.aisbf else {}}
        )

    # Validate email format
    import re
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "Invalid email address", "config": config.aisbf if config and config.aisbf else {}}
        )

    # Check if username is already taken
    try:
        db = DatabaseRegistry.get_config_database()
        existing_user_by_username = db.get_user_by_username(username)
        if existing_user_by_username:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/signup.html",
                context={"request": request, "error": "This username is already taken. Please choose a different one.", "config": config.aisbf if config and config.aisbf else {}}
            )
    except Exception as e:
        logger.error(f"Error checking username uniqueness: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "An error occurred during signup. Please try again.", "config": config.aisbf if config and config.aisbf else {}}
        )

    try:
        db = DatabaseRegistry.get_config_database()

        # Check if user already exists
        existing_user = db.get_user_by_email(email)
        if existing_user:
            if existing_user['email_verified']:
                return templates.TemplateResponse(
                    request=request,
                    name="dashboard/signup.html",
                    context={"request": request, "error": "An account with this email already exists", "config": config.aisbf if config and config.aisbf else {}}
                )
            else:
                # Resend verification email for unverified user
                verification_token = generate_verification_token()
                expires_at = datetime.now() + timedelta(hours=24)
                db.set_verification_token(existing_user['id'], verification_token, expires_at)
                db.update_last_verification_email_sent(existing_user['id'], datetime.now())

                # Send verification email
                try:
                    base_url = get_base_url(request)
                    verification_url = f"{base_url}/dashboard/verify-email?token={verification_token}&email={email}"
                    send_verification_email(email, email, verification_token, base_url, config.aisbf.smtp if config.aisbf.smtp else None)

                    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
                except Exception as e:
                    logger.error(f"Failed to send verification email: {e}")
                    return templates.TemplateResponse(
                        request=request,
                        name="dashboard/signup.html",
                        context={"request": request, "message": "Account already exists but not verified. A new verification email has been sent.", "config": config.aisbf if config and config.aisbf else {}}
                    )

        # Hash password
        password_hash = hash_password(password)
        verification_token = generate_verification_token()

        # Create user
        user_id = db.create_user(username=username, password_hash=password_hash, role='user', email=email, email_verified=False)

        # Set verification token
        expires_at = datetime.now() + timedelta(hours=24)
        db.set_verification_token(user_id, verification_token, expires_at)
        db.update_last_verification_email_sent(user_id, datetime.now())

        # Send verification email
        try:
            base_url = get_base_url(request)
            verification_url = f"{base_url}/dashboard/verify-email?token={verification_token}&email={email}"
            send_verification_email(email, email, verification_token, base_url, config.aisbf.smtp if config.aisbf.smtp else None)

            return RedirectResponse(url=url_for(request, "/dashboard/login") + "?signup=success", status_code=303)
        except Exception as e:
            logger.error(f"Failed to send verification email: {e}")
            # Still create user but inform them about email issue
            return templates.TemplateResponse(
                request=request,
                name="dashboard/signup.html",
                context={"request": request, "message": "Account created successfully! However, there was an issue sending the verification email. Please contact an administrator.", "config": config.aisbf if config and config.aisbf else {}}
            )

    except Exception as e:
        logger.error(f"Error during signup: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/signup.html",
            context={"request": request, "error": "An error occurred during signup. Please try again.", "config": config.aisbf if config and config.aisbf else {}}
        )

@app.get("/dashboard/verify")
async def verify_email_page(request: Request):
    """Show email verification page"""
    import logging

    logger = logging.getLogger(__name__)

    # Check if user is logged in
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    if not user or user['email_verified']:
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    # Check if can resend (last sent > 10 min ago)
    can_resend = True
    if user.get('last_verification_email_sent'):
        from datetime import datetime, timedelta
        if isinstance(user['last_verification_email_sent'], str):
            last_sent = datetime.fromisoformat(user['last_verification_email_sent'])
        else:
            # Already a datetime object
            last_sent = user['last_verification_email_sent']
        if datetime.now() - last_sent < timedelta(minutes=10):
            can_resend = False

    # Render verify page
    return templates.TemplateResponse(
        request=request,
        name="dashboard/verify.html",
        context={
            "request": request,
            "user": user,
            "can_resend": can_resend,
            "config": config.aisbf if config and config.aisbf else {}
        }
    )

@app.post("/dashboard/resend-verification")
async def resend_verification(request: Request):
    """Resend verification email"""
    from aisbf.email_utils import send_verification_email, generate_verification_token
    import logging

    logger = logging.getLogger(__name__)

    # Check if user is logged in
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    if not user or user['email_verified']:
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    # Check if can resend
    if user.get('last_verification_email_sent'):
        from datetime import datetime, timedelta
        if isinstance(user['last_verification_email_sent'], str):
            last_sent = datetime.fromisoformat(user['last_verification_email_sent'])
        else:
            # Already a datetime object
            last_sent = user['last_verification_email_sent']
        if datetime.now() - last_sent < timedelta(minutes=10):
            return templates.TemplateResponse(
                request=request,
                name="dashboard/verify.html",
                context={
                    "request": request,
                    "user": user,
                    "can_resend": False,
                    "error": "Please wait 10 minutes before requesting another verification email.",
                    "config": config.aisbf if config and config.aisbf else {}
                }
            )

    # Generate new token and send
    verification_token = generate_verification_token()
    expires_at = datetime.now() + timedelta(hours=24)
    db.set_verification_token(user_id, verification_token, expires_at)
    db.update_last_verification_email_sent(user_id, datetime.now())

    try:
        base_url = get_base_url(request)
        send_verification_email(user['email'], user['username'], verification_token, base_url, config.aisbf.smtp if config.aisbf.smtp else None)
        message = "Verification email sent successfully!"
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        message = "Failed to send verification email. Please try again later."

    return templates.TemplateResponse(
        request=request,
        name="dashboard/verify.html",
        context={
            "request": request,
            "user": user,
            "can_resend": False,  # Just sent, can't resend immediately
            "message": message,
            "config": config.aisbf if config and config.aisbf else {}
        }
    )


@app.get("/dashboard/verify-email")
async def verify_email(request: Request, token: str, email: str):
    """Handle email verification"""
    import logging

    logger = logging.getLogger(__name__)

    try:
        db = DatabaseRegistry.get_config_database()

        # Verify the token
        if db.verify_email_token(email, token):
            # Token is valid, mark email as verified
            db.verify_email(email)

            # If user is already logged in, update their session
            if request.session.get('logged_in'):
                request.session['email_verified'] = True

            # Redirect to login page with success message
            return RedirectResponse(url=url_for(request, "/dashboard/login") + "?success=Email verified successfully! You can now log in.", status_code=303)
        else:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={
                    "request": request,
                    "error": "Invalid or expired verification token",
                    "config": config.aisbf if config and config.aisbf else {}
                }
            )

    except Exception as e:
        logger.error(f"Error during email verification: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={
                "request": request,
                "error": "An error occurred during email verification",
                "config": config.aisbf if config and config.aisbf else {}
            }
        )


@app.get("/dashboard/forgot-password", response_class=HTMLResponse)
async def dashboard_forgot_password_page(request: Request):
    """Show forgot password page"""
    import logging

    logger = logging.getLogger(__name__)
    try:
        # Check if SMTP is configured
        smtp_enabled = False
        if config and hasattr(config, 'aisbf') and config.aisbf and hasattr(config.aisbf, 'smtp'):
            smtp_enabled = getattr(config.aisbf.smtp, 'enabled', False)

        if not smtp_enabled:
            return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

        # Check if running on AISBF Cloud domain (for footer links)
        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        # Get and render template using templates Jinja2Templates instance
        template = templates.get_template("dashboard/forgot_password.html")
        html_content = template.render(
            request=request, 
            config=config.aisbf if config and config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True  # Never show welcome modal on forgot password page
        )

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering forgot password page: {e}", exc_info=True)
        raise


@app.post("/dashboard/forgot-password")
async def dashboard_forgot_password(request: Request, email: str = Form(...)):
    """Handle forgot password request"""
    from aisbf.email_utils import generate_password_reset_token, send_password_reset_email
    import logging
    from datetime import datetime, timedelta

    logger = logging.getLogger(__name__)

    # Check if SMTP is configured
    smtp_enabled = False
    if config and hasattr(config, 'aisbf') and config.aisbf and hasattr(config.aisbf, 'smtp'):
        smtp_enabled = getattr(config.aisbf.smtp, 'enabled', False)

    if not smtp_enabled:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        db = DatabaseRegistry.get_config_database()

        # Check if user exists
        user = db.get_user_by_email(email)
        if user and user['email_verified']:
            # Generate password reset token (1 hour expiry)
            reset_token = generate_password_reset_token()
            expires_at = datetime.now() + timedelta(hours=1)

            # Store token in database
            db.set_password_reset_token(user['id'], reset_token, expires_at)

            # Send reset email
            try:
                base_url = get_base_url(request)
                success = send_password_reset_email(
                    to_email=email,
                    username=user.get('username', email),
                    reset_token=reset_token,
                    base_url=base_url,
                    smtp_config=config.aisbf.smtp
                )
                if success:
                    logger.info(f"Password reset email sent to {email}")
                else:
                    logger.error(f"Failed to send password reset email to {email}")
            except Exception as e:
                logger.error(f"Failed to send password reset email: {e}")

        # Always return the same message regardless of whether user exists (security best practice)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/forgot_password.html",
            context={
                "request": request,
                "success": True,
                "message": "If an account exists with that email address, we have sent a password reset link.",
                "message_type": "success"
            }
        )

    except Exception as e:
        logger.error(f"Error processing forgot password request: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/forgot_password.html",
            context={
                "request": request,
                "error": "An error occurred processing your request. Please try again later.",
                "config": config.aisbf if config and config.aisbf else {}
            }
        )


@app.get("/dashboard/reset-password", response_class=HTMLResponse)
async def dashboard_reset_password_page(request: Request, token: str = Query(...), email: str = Query(...)):
    """Show password reset page"""
    import logging

    logger = logging.getLogger(__name())
    try:
        db = DatabaseRegistry.get_config_database()

        # Validate token
        token_valid = db.validate_password_reset_token(email, token)
        if not token_valid:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={
                    "request": request,
                    "error": "Invalid or expired password reset token. Please request a new one.",
                    "config": config.aisbf if config and config.aisbf else {}
                }
            )

        # Check if running on AISBF Cloud domain (for footer links)
        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        # Get and render template using templates Jinja2Templates instance
        template = templates.get_template("dashboard/reset_password.html")
        html_content = template.render(
            request=request, 
            email=email, 
            token=token, 
            config=config.aisbf if config and config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True  # Never show welcome modal on reset password page
        )

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering reset password page: {e}", exc_info=True)
        raise


@app.post("/dashboard/reset-password")
async def dashboard_reset_password(
    request: Request,
    email: str = Form(...),
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle password reset confirmation"""
    from aisbf.email_utils import hash_password
    import logging

    logger = logging.getLogger(__name__)

    try:
        db = DatabaseRegistry.get_config_database()

        # Validate token and retrieve user
        reset_user = db.get_user_by_reset_token(token)
        if not reset_user or reset_user.get('email', '').lower() != email.lower():
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={
                    "request": request,
                    "error": "Invalid or expired password reset token. Please request a new one.",
                    "config": config.aisbf if config and config.aisbf else {}
                }
            )

        # Validate passwords match
        if password != confirm_password:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/reset_password.html",
                context={
                    "request": request,
                    "email": email,
                    "token": token,
                    "error": "Passwords do not match",
                    "config": config.aisbf if config and config.aisbf else {}
                }
            )

        # Validate password strength (minimum 8 characters)
        if len(password) < 8:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/reset_password.html",
                context={
                    "request": request,
                    "email": email,
                    "token": token,
                    "error": "Password must be at least 8 characters long",
                    "config": config.aisbf if config and config.aisbf else {}
                }
            )

        # Hash new password and update; clear the token to prevent reuse
        password_hash = hash_password(password)
        user_id = reset_user['id']
        db.update_user_password(user_id, password_hash)
        db.clear_password_reset_token(user_id)

        logger.info(f"Password successfully reset for user {email}")

        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={
                "request": request,
                "message": "Password has been reset successfully. You can now login with your new password.",
                "config": config.aisbf if config and config.aisbf else {}
            }
        )

    except Exception as e:
        logger.error(f"Error processing password reset: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/reset_password.html",
            context={
                "request": request,
                "email": email,
                "token": token,
                "error": "An error occurred resetting your password. Please try again later.",
                "config": config.aisbf if config and config.aisbf else {}
            }
        )

@app.get("/dashboard/logout")
async def dashboard_logout(request: Request):
    """Handle dashboard logout"""
    request.session.clear()
    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)


@app.get("/dashboard/profile", response_class=HTMLResponse)
async def dashboard_profile(request: Request):
    """User profile page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    # Get user data for profile
    user = db.get_user_by_id(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/profile.html",
        context={
            "session": request.session,
            "user": user,
            "success": request.query_params.get('success'),
            "error": request.query_params.get('error')
        }
    )


@app.post("/dashboard/profile")
async def dashboard_profile_save(request: Request, username: str = Form(...), display_name: str = Form("")):
    """Save user profile changes (username and display_name). Profile pic is handled separately via /dashboard/profile/upload-pic/chunk."""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    try:
        db.update_user_profile(user_id, username, None, display_name if display_name else None, None)
        request.session['username'] = username
        request.session['display_name'] = display_name or ''

        return RedirectResponse(url=url_for(request, "/dashboard/profile?success=Profile updated successfully"), status_code=303)
    except Exception as e:
        return RedirectResponse(url=url_for(request, f"/dashboard/profile?error=Failed to update profile: {str(e)}"), status_code=303)


_PROFILE_PIC_MAX_BYTES = 5 * 1024 * 1024  # 5 MB assembled limit

@app.post("/dashboard/profile/upload-pic/chunk")
async def dashboard_profile_pic_chunk(
    request: Request,
    file_name: str = Form(...),
    chunk_number: int = Form(...),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
    file: UploadFile = File(...)
):
    """Chunked profile picture upload. Assembles chunks, validates, base64-encodes, stores in DB."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')

    if total_size > _PROFILE_PIC_MAX_BYTES:
        return JSONResponse({"success": False, "error": f"Image too large. Maximum size is 5 MB."}, status_code=400)

    content_type = file.content_type or ''
    if not content_type.startswith('image/'):
        # Fallback: infer from extension
        ext = Path(file_name).suffix.lower()
        ext_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                   '.gif': 'image/gif', '.webp': 'image/webp'}
        content_type = ext_map.get(ext, '')
        if not content_type:
            return JSONResponse({"success": False, "error": "Invalid file type. Upload JPG, PNG, GIF or WebP."}, status_code=400)

    import hashlib as _hl
    upload_id = _hl.sha256(f"{user_id}:{file_name}:{total_size}".encode()).hexdigest()[:16]
    temp_dir = Path.home() / '.aisbf' / 'temp_uploads' / 'profile_pics'
    temp_dir.mkdir(parents=True, exist_ok=True)

    chunk_data = await file.read()
    chunk_path = temp_dir / f"{upload_id}.part{chunk_number}"
    with open(chunk_path, 'wb') as f:
        f.write(chunk_data)

    received = list(temp_dir.glob(f"{upload_id}.part*"))
    if len(received) < total_chunks:
        return JSONResponse({"success": True, "complete": False, "chunk": chunk_number})

    # All chunks received — assemble
    try:
        assembled = bytearray()
        for i in range(1, total_chunks + 1):
            part = temp_dir / f"{upload_id}.part{i}"
            assembled.extend(part.read_bytes())
            part.unlink()

        if len(assembled) > _PROFILE_PIC_MAX_BYTES:
            return JSONResponse({"success": False, "error": "Assembled image exceeds 5 MB limit."}, status_code=400)

        import base64 as _b64
        data_url = f"data:{content_type};base64,{_b64.b64encode(bytes(assembled)).decode()}"

        db = DatabaseRegistry.get_config_database()
        db.update_user_profile(user_id, request.session.get('username', ''), None, None, data_url)
        request.session['has_profile_pic'] = True

        return JSONResponse({"success": True, "complete": True})

    except Exception as e:
        logger.error(f"Profile pic assembly error for user {user_id}: {e}")
        # Clean up any remaining parts
        for part in temp_dir.glob(f"{upload_id}.part*"):
            try:
                part.unlink()
            except Exception:
                pass
        return JSONResponse({"success": False, "error": "Upload failed. Please try again."}, status_code=500)


@app.get("/dashboard/change-password", response_class=HTMLResponse)
async def dashboard_change_password(request: Request):
    """Change user password page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check
    
    # User dashboard - load usage stats same as main dashboard user route
    db = DatabaseRegistry.get_config_database()
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
        name="dashboard/change_password.html",
        context={
            "session": request.session,
            "success": request.query_params.get('success'),
            "error": request.query_params.get('error')
        }
    )


@app.post("/dashboard/change-password")
async def dashboard_change_password_save(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    """Save password change"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check
    
    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()
    
    if new_password != confirm_password:
        return RedirectResponse(url=url_for(request, "/dashboard/change-password?error=New passwords do not match"), status_code=303)
    
    if len(new_password) < 6:
        return RedirectResponse(url=url_for(request, "/dashboard/change-password?error=New password must be at least 6 characters"), status_code=303)
    
    try:
        # Verify current password
        if not db.verify_user_password(user_id, current_password):
            return RedirectResponse(url=url_for(request, "/dashboard/change-password?error=Current password is incorrect"), status_code=303)
        
        # Update password
        db.update_user_password(user_id, new_password)
        
        return RedirectResponse(url=url_for(request, "/dashboard/change-password?success=Password changed successfully"), status_code=303)
    except Exception as e:
        return RedirectResponse(url=url_for(request, f"/dashboard/change-password?error=Failed to change password: {str(e)}"), status_code=303)
    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)


@app.get("/dashboard/change-email", response_class=HTMLResponse)
async def dashboard_change_email(request: Request):
    """Change email page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/change_email.html",
        context={
            "session": request.session,
            "success": request.query_params.get('success'),
            "error": request.query_params.get('error')
        }
    )


@app.post("/dashboard/change-email")
async def dashboard_change_email_save(request: Request, new_email: str = Form(...), password: str = Form(...)):
    """Process email change request"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check
    
    from aisbf.email_utils import send_email_verification, hash_password
    import secrets
    
    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()
    
    try:
        # Verify current password
        if not db.verify_user_password(user_id, password):
            return RedirectResponse(url=url_for(request, "/dashboard/change-email?error=Incorrect password"), status_code=303)
        
        # Check if new email is already in use
        existing_user = db.get_user_by_email(new_email)
        if existing_user and existing_user['id'] != user_id:
            return RedirectResponse(url=url_for(request, "/dashboard/change-email?error=Email address already in use"), status_code=303)
        
        # Generate verification token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=24)
        
        # Store pending email change in session (we'll update after verification)
        request.session['pending_email_change'] = {
            'new_email': new_email,
            'token': token,
            'expires_at': expires_at.isoformat()
        }
        
        # Send verification email to new address
        base_url = get_base_url(request)
        verification_url = f"{base_url}/dashboard/verify-email-change?token={token}&email={new_email}"
        
        if config and config.aisbf and config.aisbf.smtp and config.aisbf.smtp.enabled:
            send_email_verification(
                new_email,
                verification_url,
                config.aisbf.smtp
            )
            return RedirectResponse(
                url=url_for(request, "/dashboard/change-email?success=Verification email sent to new address. Please check your inbox."),
                status_code=303
            )
        else:
            return RedirectResponse(
                url=url_for(request, "/dashboard/change-email?error=Email service not configured. Please contact administrator."),
                status_code=303
            )
    except Exception as e:
        logger.error(f"Email change error: {e}")
        return RedirectResponse(url=url_for(request, f"/dashboard/change-email?error=Failed to process email change: {str(e)}"), status_code=303)


@app.get("/dashboard/verify-email-change")
async def verify_email_change(request: Request, token: str = Query(...), email: str = Query(...)):
    """Verify new email address"""
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    try:
        # Check pending email change in session
        pending = request.session.get('pending_email_change', {})
        
        if not pending or pending.get('token') != token or pending.get('new_email') != email:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/change_email.html",
                context={
                    "session": request.session,
                    "error": "Invalid or expired verification link"
                }
            )
        
        # Check expiration
        expires_at = datetime.fromisoformat(pending['expires_at'])
        if datetime.now() > expires_at:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/change_email.html",
                context={
                    "session": request.session,
                    "error": "Verification link has expired"
                }
            )
        
        # Update email
        db.update_user_email(user_id, email)
        request.session['email'] = email
        
        # Clear pending change
        request.session.pop('pending_email_change', None)
        
        return RedirectResponse(
            url=url_for(request, "/dashboard/profile?success=Email address updated successfully"),
            status_code=303
        )
    except Exception as e:
        logger.error(f"Email verification error: {e}")
        return templates.TemplateResponse(
            request=request,
            name="dashboard/change_email.html",
            context={
                "session": request.session,
                "error": f"Failed to verify email: {str(e)}"
            }
        )


@app.get("/dashboard/delete-account", response_class=HTMLResponse)
async def dashboard_delete_account(request: Request):
    """Delete account confirmation page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check
    
    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()
    
    # Check for active subscription
    subscription = db.get_user_subscription(user_id)
    has_subscription = subscription is not None and subscription.get('status') == 'active'
    subscription_tier = subscription.get('tier_name', '') if subscription else ''
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/delete_account.html",
        context={
            "session": request.session,
            "error": request.query_params.get('error'),
            "has_subscription": has_subscription,
            "subscription_tier": subscription_tier
        }
    )


@app.post("/dashboard/delete-account")
async def dashboard_delete_account_confirm(request: Request, password: str = Form(...), confirmation: str = Form(...)):
    """Process account deletion"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check
    
    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()
    
    try:
        # Verify confirmation text
        if confirmation != "DELETE":
            return RedirectResponse(url=url_for(request, "/dashboard/delete-account?error=Please type DELETE to confirm"), status_code=303)
        
        # Verify password
        if not db.verify_user_password(user_id, password):
            return RedirectResponse(url=url_for(request, "/dashboard/delete-account?error=Incorrect password"), status_code=303)
        
        # Delete user (this will cascade delete all related data)
        db.delete_user(user_id)
        
        # Clear session
        request.session.clear()
        
        return RedirectResponse(url=url_for(request, "/dashboard/login?message=Account deleted successfully"), status_code=303)
    except Exception as e:
        logger.error(f"Account deletion error: {e}")
        return RedirectResponse(url=url_for(request, f"/dashboard/delete-account?error=Failed to delete account: {str(e)}"), status_code=303)


# ==============================================
# OAuth2 Authentication Endpoints (Google + GitHub)
# ==============================================

# OAuth2 handler instances are stored in session during auth flow
_oauth2_instances = {}

@app.get("/auth/oauth2/google")
async def oauth2_google_initiate(request: Request):
    """Initiate Google OAuth2 authentication flow"""
    if not (config and config.aisbf and config.aisbf.oauth2 and 
            config.aisbf.oauth2.google and config.aisbf.oauth2.google.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    try:
        from aisbf.auth.google import GoogleOAuth2
        
        client_id = config.aisbf.oauth2.google.client_id
        client_secret = config.aisbf.oauth2.google.client_secret
        
        # Build proper redirect URI respecting proxy headers
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/google/callback"
        
        oauth = GoogleOAuth2(client_id, client_secret, redirect_uri)
        auth_url = oauth.get_authorization_url(config.aisbf.oauth2.google.scopes)
        
        # Store oauth instance and state in session for callback
        request.session['oauth2_google'] = {
            'state': oauth._state,
            'code_verifier': oauth._code_verifier
        }

        # Detect if this is a popup request (from Referer header or popup parameter)
        referer = request.headers.get('Referer', '')
        is_popup = 'popup=1' in referer or request.query_params.get('popup') == '1'
        if is_popup:
            request.session['oauth2_popup'] = True
            # Also store a more persistent flag
            request.session['oauth2_popup_mode'] = True
        
        return RedirectResponse(url=auth_url, status_code=303)
    except Exception as e:
        logger.error(f"Google OAuth2 initiation failed: {e}")
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={
                "request": request, 
                "error": "Google authentication service is temporarily unavailable"
            }
        )


@app.get("/auth/oauth2/google/callback")
async def oauth2_google_callback(request: Request, code: str = Query(...), state: str = Query(...)):
    """Handle Google OAuth2 callback"""
    if not (config and config.aisbf and config.aisbf.oauth2 and 
            config.aisbf.oauth2.google and config.aisbf.oauth2.google.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    try:
        from aisbf.auth.google import GoogleOAuth2
        
        client_id = config.aisbf.oauth2.google.client_id
        client_secret = config.aisbf.oauth2.google.client_secret
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/google/callback"
        
        # Verify state matches
        session_state = request.session.get('oauth2_google', {}).get('state')
        if state != session_state:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "config": config, "error": "Invalid authentication state"}
            )
        
        # Restore oauth instance
        oauth = GoogleOAuth2(client_id, client_secret, redirect_uri)
        oauth._state = session_state
        oauth._code_verifier = request.session.get('oauth2_google', {}).get('code_verifier')
        
        # Exchange code for tokens
        tokens = await oauth.exchange_code_for_tokens(code, state)
        if not tokens:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "config": config, "error": "Failed to authenticate with Google"}
            )
        
        # Get user profile
        user_info = await oauth.get_user_info(tokens.get('access_token'))
        if not user_info or not user_info.get('email'):
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "config": config, "error": "Could not retrieve your profile from Google"}
            )
        
        email = user_info.get('email')
        email_verified = user_info.get('email_verified', False)
        # Get display name from Google
        display_name = user_info.get('name', '')
        
        db = DatabaseRegistry.get_config_database()
        
        # Lookup existing user
        existing_user = db.get_user_by_email(email)
        
        if existing_user:
            # Existing user - login directly
            request.session['logged_in'] = True
            request.session['username'] = existing_user['username']
            request.session['email'] = existing_user.get('email', '')
            request.session['role'] = existing_user['role']
            request.session['user_id'] = existing_user['id']
            request.session['has_profile_pic'] = bool(existing_user.get('profile_pic'))
            request.session['email_verified'] = True  # OAuth2 users have verified emails
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

            # Update last login timestamp
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (existing_user['id'],))
                conn.commit()
        else:
            # New user - create account automatically (no password required)
            if not email_verified:
                return templates.TemplateResponse(
                    request=request,
                    name="dashboard/login.html",
                    context={"request": request, "config": config, "error": "Google email must be verified to create an account"}
                )

            # Generate secure random password for OAuth users (never used for login)
            random_password = secrets.token_urlsafe(32)
            password_hash = _db_hash_password(random_password)

            # Generate clean username from display_name with email fallback
            google_username = db.generate_username_from_display_name(display_name, email)
            final_username = db.find_unique_username(google_username)


            # Create user with verified email (no verification required)
            user_id = db.create_user(final_username, password_hash, 'user', None, email, True, display_name)

            # Login the new user
            request.session['logged_in'] = True
            request.session['username'] = final_username
            request.session['email'] = email
            request.session['role'] = 'user'
            request.session['user_id'] = user_id
            request.session['email_verified'] = True  # OAuth2 users have verified emails
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

            # Update last login timestamp for new user
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (user_id,))
                conn.commit()
        
        # Check if this is a popup window request BEFORE cleaning up session
        is_popup = request.session.pop('oauth2_popup', False) or request.session.pop('oauth2_popup_mode', False)
        
        # Cleanup session data
        request.session.pop('oauth2_google', None)
        if is_popup:
            # Return HTML with postMessage to opener
            return HTMLResponse(content=f'''
                <!DOCTYPE html>
                <html>
                <head><title>Authentication Complete</title></head>
                <body>
                    <script>
                        var msg = {{ type: 'oauth2_complete', redirect_url: '{url_for(request, "/dashboard")}' }};
                        try {{
                            var bc = new BroadcastChannel('oauth2_result');
                            bc.postMessage(msg);
                            bc.close();
                        }} catch(e) {{}}
                        try {{
                            if (window.opener) window.opener.postMessage(msg, '*');
                        }} catch(e) {{}}
                        window.close();
                    </script>
                </body>
                </html>
            ''')

        # Redirect to dashboard for regular requests
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    except Exception as e:
        logger.error(f"Error during email verification: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={"request": request, "config": config, "error": "An error occurred during email verification"}
        )


@app.get("/auth/oauth2/github")
async def oauth2_github_initiate(request: Request):
    """Initiate GitHub OAuth2 authentication flow"""
    if not (config and config.aisbf and config.aisbf.oauth2 and 
            config.aisbf.oauth2.github and config.aisbf.oauth2.github.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    try:
        from aisbf.auth.github import GitHubOAuth2
        
        client_id = config.aisbf.oauth2.github.client_id
        client_secret = config.aisbf.oauth2.github.client_secret
        
        # Build proper redirect URI respecting proxy headers
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/github/callback"
        
        oauth = GitHubOAuth2(client_id, client_secret, redirect_uri)
        auth_url = oauth.get_authorization_url(config.aisbf.oauth2.github.scopes)
        
        # Store state in session for callback
        request.session['oauth2_github'] = {
            'state': oauth._state
        }

        # Detect if this is a popup request (from Referer header or popup parameter)
        referer = request.headers.get('Referer', '')
        is_popup = 'popup=1' in referer or request.query_params.get('popup') == '1'
        if is_popup:
            request.session['oauth2_popup'] = True
            # Also store a more persistent flag
            request.session['oauth2_popup_mode'] = True
        
        return RedirectResponse(url=auth_url, status_code=303)
    except Exception as e:
        logger.error(f"GitHub OAuth2 initiation failed: {e}")
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={
                "request": request, 
                "error": "GitHub authentication service is temporarily unavailable"
            }
        )


@app.get("/auth/oauth2/github/callback")
async def oauth2_github_callback(request: Request, code: str = Query(...), state: str = Query(...)):
    """Handle GitHub OAuth2 callback"""
    if not (config and config.aisbf and config.aisbf.oauth2 and 
            config.aisbf.oauth2.github and config.aisbf.oauth2.github.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
    
    try:
        from aisbf.auth.github import GitHubOAuth2
        
        client_id = config.aisbf.oauth2.github.client_id
        client_secret = config.aisbf.oauth2.github.client_secret
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/github/callback"
        
        # Verify state matches
        session_state = request.session.get('oauth2_github', {}).get('state')
        if state != session_state:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "config": config, "error": "Invalid authentication state"}
            )
        
        # Restore oauth instance
        oauth = GitHubOAuth2(client_id, client_secret, redirect_uri)
        oauth._state = session_state
        
        # Exchange code for tokens
        tokens = await oauth.exchange_code_for_tokens(code, state)
        if not tokens:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "config": config, "error": "Failed to authenticate with GitHub"}
            )
        
        # Get user profile
        user_info = await oauth.get_user_info(tokens.get('access_token'))
        if not user_info or not user_info.get('email'):
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"request": request, "config": config, "error": "Could not retrieve your profile from GitHub. Please ensure your email is public."}
            )
        
        email = user_info.get('email')
        # Get display name from GitHub (name or login)
        display_name = user_info.get('name', '') or user_info.get('login', '')
        
        db = DatabaseRegistry.get_config_database()
        
        # Lookup existing user
        existing_user = db.get_user_by_email(email)
        
        if existing_user:
            # Existing user - login directly
            request.session['logged_in'] = True
            request.session['username'] = existing_user['username']
            request.session['email'] = existing_user.get('email', '')
            request.session['role'] = existing_user['role']
            request.session['user_id'] = existing_user['id']
            request.session['has_profile_pic'] = bool(existing_user.get('profile_pic'))
            request.session['email_verified'] = True  # OAuth2 users have verified emails
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

            # Update last login timestamp
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (existing_user['id'],))
                conn.commit()
        else:
            # New user - create account automatically (no password required)
            # Generate secure random password for OAuth users (never used for login)
            random_password = secrets.token_urlsafe(32)
            password_hash = _db_hash_password(random_password)
            
            # Generate clean username from display_name with email fallback
            github_username = db.generate_username_from_display_name(display_name, email)
            final_username = db.find_unique_username(github_username)
            
            # Create user with verified email (no verification required)
            user_id = db.create_user(final_username, password_hash, 'user', None, email, True, display_name)
            
            # Login the new user
            request.session['logged_in'] = True
            request.session['username'] = final_username
            request.session['email'] = email
            request.session['role'] = 'user'
            request.session['user_id'] = user_id
            request.session['email_verified'] = True  # OAuth2 users have verified emails
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

            # Update last login timestamp for new user
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (user_id,))
                conn.commit()

        # Check if this is a popup window request BEFORE cleaning up session
        is_popup = request.session.pop('oauth2_popup', False) or request.session.pop('oauth2_popup_mode', False)
        
        # Cleanup session data
        request.session.pop('oauth2_github', None)
        if is_popup:
            return HTMLResponse(content=f'''
                <!DOCTYPE html>
                <html>
                <head><title>Authentication Complete</title></head>
                <body>
                    <script>
                        var msg = {{ type: 'oauth2_complete', redirect_url: '{url_for(request, "/dashboard")}' }};
                        try {{
                            var bc = new BroadcastChannel('oauth2_result');
                            bc.postMessage(msg);
                            bc.close();
                        }} catch(e) {{}}
                        try {{
                            if (window.opener) window.opener.postMessage(msg, '*');
                        }} catch(e) {{}}
                        window.close();
                    </script>
                </body>
                </html>
            ''')

        # Redirect to dashboard for regular requests
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    except Exception as e:
        logger.error(f"GitHub OAuth2 callback failed: {e}", exc_info=True)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={"request": request, "config": config, "error": "Authentication failed. Please try again."}
        )

def require_dashboard_auth(request: Request):
    """Check if user is logged in to dashboard"""
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    # Check if session has expired
    expires_at = request.session.get('expires_at')
    if expires_at and int(time.time()) > expires_at:
        request.session.clear()
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    # Extend session expiry on each request (sliding expiration)
    if request.session.get('remember_me'):
        request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
    elif expires_at:
        request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

    # Force password change if still using factory default
    if request.session.get('must_change_password'):
        path = request.url.path
        if not any(path.startswith(p) for p in _MUST_CHANGE_PASSWORD_WHITELIST):
            return RedirectResponse(
                url=url_for(request, "/dashboard/settings") + "?warning=default_password",
                status_code=303
            )

    return None

def require_api_auth(request: Request):
    """Check if user is logged in to dashboard (API version - returns JSON)"""
    if not request.session.get('logged_in'):
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    # Check if session has expired
    expires_at = request.session.get('expires_at')
    if expires_at and int(time.time()) > expires_at:
        request.session.clear()
        return JSONResponse(status_code=401, content={"error": "Session expired"})

    # Extend session expiry on each request (sliding expiration)
    if request.session.get('remember_me'):
        request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
    elif expires_at:
        request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

    # Force password change if still using factory default
    if request.session.get('must_change_password'):
        path = request.url.path
        if not any(path.startswith(p) for p in _MUST_CHANGE_PASSWORD_WHITELIST):
            return JSONResponse(
                status_code=403,
                content={"error": "Default password must be changed before using the API",
                         "redirect": "/dashboard/settings?warning=default_password"}
            )

    return None

def require_api_admin(request: Request):
    """Check if user is admin (API version - returns JSON)"""
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    if request.session.get('role') != 'admin':
        return JSONResponse(
            status_code=403,
            content={"error": "Admin access required"}
        )
    return None

def require_admin(request: Request):
    """Check if user is admin (dashboard version - returns redirects)"""
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
    
    # Welcome modal and footer links are handled by dashboard_context_middleware
    # No need to override them here - request.state already has the correct values

    if request.session.get('role') == 'admin':
        # Admin dashboard
        db = DatabaseRegistry.get_config_database()
        users_count = len(db.get_users())
        return templates.TemplateResponse(
            request=request,
            name="dashboard/index.html",
            context={
                "request": request,
                "session": request.session,
                "__version__": __version__,
                "providers_count": len(config.providers) if config else 0,
                "rotations_count": len(config.rotations) if config else 0,
                "autoselect_count": len(config.autoselect) if config else 0,
                "server_config": server_config or {},
                "users_count": users_count,
            }
        )
    else:
        # User dashboard - show user stats
        db = DatabaseRegistry.get_config_database()
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
                if (datetime.fromisoformat(row['timestamp']) if isinstance(row['timestamp'], str) else row['timestamp']) >= today
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
        
        # Get subscription info
        subscription = db.get_user_subscription(user_id) if user_id else None
        current_tier = db.get_user_tier(user_id) if user_id else None
        payment_methods = db.get_user_payment_methods(user_id) if user_id else []
        all_tiers = db.get_visible_tiers() if user_id else []

        # Get currency settings
        currency_settings = db.get_currency_settings()
        currency_symbol = currency_settings.get('currency_symbol', '$')

        # Determine if there are higher tiers available to upgrade to
        upgrade_tiers = []
        if current_tier:
            for t in all_tiers:
                if not t.get('is_default') and t['price_monthly'] > current_tier.get('price_monthly', 0):
                    upgrade_tiers.append(t)
        elif all_tiers:
            upgrade_tiers = [t for t in all_tiers if not t.get('is_default')]

        return templates.TemplateResponse(
        request=request,
        name="dashboard/user_index.html",
        context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "usage_stats": usage_stats,
            "providers_count": providers_count,
            "rotations_count": rotations_count,
            "autoselects_count": autoselects_count,
            "recent_activity": recent_activity,
            "subscription": subscription,
            "current_tier": current_tier,
            "payment_methods": payment_methods,
            "currency_symbol": currency_symbol,
            "upgrade_tiers": upgrade_tiers,
            "display_name": (db.get_user_by_id(user_id) or {}).get('display_name') or request.session.get('username', '') if user_id else request.session.get('username', '')
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
        db = DatabaseRegistry.get_config_database()
        user_providers = db.get_user_providers(current_user_id)
        
        # Convert datetime objects to strings for JSON serialization
        for provider in user_providers:
            if 'created_at' in provider and provider['created_at']:
                provider['created_at'] = provider['created_at'].isoformat() if hasattr(provider['created_at'], 'isoformat') else str(provider['created_at'])
            if 'updated_at' in provider and provider['updated_at']:
                provider['updated_at'] = provider['updated_at'].isoformat() if hasattr(provider['updated_at'], 'isoformat') else str(provider['updated_at'])
        
        # Always pass raw user providers format to the template (array)
        providers_data = user_providers
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    if is_config_admin:
        # Config admin: use admin template
        return templates.TemplateResponse(
            request=request,
            name="dashboard/providers.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "providers_json": json.dumps(providers_data),
            "success": "Configuration saved successfully! Restart server for changes to take effect." if success else None
        }
        )
    else:
        # Database user: use user template with proper context
        return templates.TemplateResponse(
            request=request,
            name="dashboard/user_providers.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "user_providers_json": json.dumps(providers_data),
            "user_id": current_user_id,
            "success": "Configuration saved successfully!" if success else None
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
            token = await oauth2.get_valid_token()
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
            db = DatabaseRegistry.get_config_database()
            
            # Get existing providers to find which to delete
            existing_providers = db.get_user_providers(current_user_id)
            existing_provider_keys = {p['provider_id'] for p in existing_providers}
            new_provider_keys = set(providers_data.keys())
            
            # Delete providers that are no longer present
            providers_to_delete = existing_provider_keys - new_provider_keys
            for provider_key in providers_to_delete:
                db.delete_user_provider(current_user_id, provider_key)
            
            # Save each provider to database
            for provider_key, provider_config in providers_data.items():
                db.save_user_provider(current_user_id, provider_key, provider_config)
            
            logger.info(f"Saved {len(providers_data)} provider(s) to database for user {current_user_id}")
        
        if is_config_admin:
            success_msg = "Configuration saved successfully! Restart server for changes to take effect."
            return templates.TemplateResponse(
                request=request,
                name="dashboard/providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "providers_json": json.dumps(providers_data),
                    "success": success_msg
                }
            )
        else:
            success_msg = "Configuration saved successfully!"
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/user_providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_providers_json": json.dumps(providers_data),
                    "user_id": current_user_id,
                    "success": success_msg
                }
            )
    except json.JSONDecodeError as e:
        # Reload current config on error
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if is_config_admin:
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
                    "__version__": __version__,
                    "providers_json": json.dumps(providers_data),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/user_providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_providers_json": json.dumps(user_providers),
                    "user_id": current_user_id,
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
        
        # Get user ID from session
        current_user_id = request.session.get('user_id')
        
        # Get provider handler - pass user_id to automatically handle user-specific providers
        from aisbf.providers import get_provider_handler
        
        try:
            handler = get_provider_handler(provider_key, user_id=current_user_id)
        except ValueError as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=404)
        
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
        db = DatabaseRegistry.get_config_database()
        user_rotations = db.get_user_rotations(current_user_id)
        
        # Convert to the format expected by the frontend
        rotations_data = {"rotations": {}, "notifyerrors": False}
        for rotation in user_rotations:
            rotations_data["rotations"][rotation['rotation_id']] = rotation['config']
    
    # Get available providers - user-specific for database users
    if is_config_admin:
        # Admin: use global providers
        available_providers = list(config.providers.keys()) if config else []
    else:
        # Database user: use ONLY their own providers
        db = DatabaseRegistry.get_config_database()
        user_providers = db.get_user_providers(current_user_id)
        available_providers = [p['provider_id'] for p in user_providers]
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    if is_config_admin:
        # Config admin: use admin template
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
    else:
        # Database user: use user template
        return templates.TemplateResponse(
            request=request,
            name="dashboard/user_rotations.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "rotations_json": json.dumps(rotations_data),
            "available_providers": json.dumps(available_providers),
            "success": "Configuration saved successfully!" if success else None
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
            db = DatabaseRegistry.get_config_database()

            rotations = rotations_data.get('rotations', {})

            # Delete rotations that are no longer present
            existing_rotations = db.get_user_rotations(current_user_id)
            existing_rotation_keys = {r['rotation_id'] for r in existing_rotations}
            new_rotation_keys = set(rotations.keys())
            for rotation_key in existing_rotation_keys - new_rotation_keys:
                db.delete_user_rotation(current_user_id, rotation_key)

            # Save each rotation to database
            for rotation_key, rotation_config in rotations.items():
                db.save_user_rotation(current_user_id, rotation_key, rotation_config)

            logger.info(f"Saved {len(rotations)} rotation(s) to database for user {current_user_id}")
        
        if is_config_admin:
            # Get global config safely
            from aisbf.config import config as global_config
            available_providers = list(global_config.providers.keys()) if global_config else []
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "success": "Configuration saved successfully! Restart server for changes to take effect."
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_rotations = db.get_user_rotations(current_user_id)
            
            # For database users, get their own providers
            user_providers = db.get_user_providers(current_user_id)
            available_providers = [p['provider_id'] for p in user_providers]
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/user_rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "user_id": current_user_id,
                    "success": "Configuration saved successfully!"
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
            db = DatabaseRegistry.get_config_database()
            user_rotations = db.get_user_rotations(current_user_id)
            rotations_data = {"rotations": {}, "notifyerrors": False}
            for rotation in user_rotations:
                rotations_data["rotations"][rotation['rotation_id']] = rotation['config']
        
        if is_config_admin:
            available_providers = list(config.providers.keys()) if config else []
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            available_providers = [p['provider_id'] for p in user_providers]
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/user_rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "user_id": current_user_id,
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
        db = DatabaseRegistry.get_config_database()
        user_autoselects = db.get_user_autoselects(current_user_id)
        
        # Convert to the format expected by the frontend
        autoselect_data = {}
        for autoselect in user_autoselects:
            autoselect_data[autoselect['autoselect_id']] = autoselect['config']
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    if is_config_admin:
        # Admin: use global rotations and providers
        available_rotations = list(config.rotations.keys()) if config else []
        available_models = []
        
        # Add global rotation IDs
        for rotation_id in available_rotations:
            available_models.append({
                'id': rotation_id,
                'name': f'{rotation_id} (rotation)',
                'type': 'rotation'
            })
        
        # Add global provider models
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
        
        # Config admin: use admin template
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
    else:
        # Database user: use ONLY their own rotations and providers
        db = DatabaseRegistry.get_config_database()
        user_autoselects = db.get_user_autoselects(current_user_id)
        
        # Get only user's own rotations
        user_rotations = db.get_user_rotations(current_user_id)
        available_rotations = [rot['rotation_id'] for rot in user_rotations]
        
        # Get only user's own providers
        user_providers = db.get_user_providers(current_user_id)
        available_models = []
        
        # Add user rotation IDs
        for rotation_id in available_rotations:
            available_models.append({
                'id': rotation_id,
                'name': f'{rotation_id} (rotation)',
                'type': 'rotation'
            })
        
        # Add user provider models
        for provider in user_providers:
            provider_config = provider['config']
            if 'models' in provider_config and isinstance(provider_config['models'], list):
                for model in provider_config['models']:
                    model_id = f"{provider['provider_id']}/{model['name']}"
                    available_models.append({
                        'id': model_id,
                        'name': f"{model_id} (provider model)",
                        'type': 'provider'
                    })
    
        # Database user: use user template
        return templates.TemplateResponse(
            request=request,
            name="dashboard/user_autoselects.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "autoselect_json": json.dumps(autoselect_data),
            "available_rotations": json.dumps(available_rotations),
            "available_models": json.dumps(available_models),
            "user_id": current_user_id,
            "success": "Configuration saved successfully!" if success else None
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
            db = DatabaseRegistry.get_config_database()

            # Delete autoselects that are no longer present
            existing_autoselects = db.get_user_autoselects(current_user_id)
            existing_autoselect_keys = {a['autoselect_id'] for a in existing_autoselects}
            new_autoselect_keys = set(autoselect_data.keys())
            for autoselect_key in existing_autoselect_keys - new_autoselect_keys:
                db.delete_user_autoselect(current_user_id, autoselect_key)

            # Save each autoselect to database
            for autoselect_key, autoselect_config in autoselect_data.items():
                db.save_user_autoselect(current_user_id, autoselect_key, autoselect_config)

            logger.info(f"Saved {len(autoselect_data)} autoselect(s) to database for user {current_user_id}")
        
        if is_config_admin:
            # Get global config safely
            from aisbf.config import config as global_config
            available_rotations = list(global_config.rotations.keys()) if global_config else []
            
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
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/autoselect.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "autoselect_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "success": "Configuration saved successfully! Restart server for changes to take effect."
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_autoselects = db.get_user_autoselects(current_user_id)
            
            # For database users, get available user rotations
            user_rotations = db.get_user_rotations(current_user_id)
            available_rotations = [rot['rotation_id'] for rot in user_rotations]
            
            # For database users, get available user providers
            user_providers = db.get_user_providers(current_user_id)
            available_models = []
            
            # Add user rotation IDs
            for rotation_id in available_rotations:
                available_models.append({
                    'id': rotation_id,
                    'name': f'{rotation_id} (rotation)',
                    'type': 'rotation'
                })
            
            # Add user provider models
            for provider in user_providers:
                provider_config = provider['config']
                if 'models' in provider_config and isinstance(provider_config['models'], list):
                    for model in provider_config['models']:
                        model_id = f"{provider['provider_id']}/{model['name']}"
                        available_models.append({
                            'id': model_id,
                            'name': f"{model_id} (provider model)",
                            'type': 'provider'
                        })
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/user_autoselects.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_autoselects_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "user_id": current_user_id,
                    "success": "Configuration saved successfully!"
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
            db = DatabaseRegistry.get_config_database()
            user_autoselects = db.get_user_autoselects(current_user_id)
            autoselect_data = {}
            for autoselect in user_autoselects:
                autoselect_data[autoselect['autoselect_id']] = autoselect['config']
        
        if is_config_admin:
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
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/autoselect.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "autoselect_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            
            # For database users, get available user rotations
            user_rotations = db.get_user_rotations(current_user_id)
            available_rotations = [rot['rotation_id'] for rot in user_rotations]
            
            # For database users, get available user providers
            user_providers = db.get_user_providers(current_user_id)
            available_models = []
            
            # Add user rotation IDs
            for rotation_id in available_rotations:
                available_models.append({
                    'id': rotation_id,
                    'name': f'{rotation_id} (rotation)',
                    'type': 'rotation'
                })
            
            # Add user provider models
            for provider in user_providers:
                provider_config = provider['config']
                if 'models' in provider_config and isinstance(provider_config['models'], list):
                    for model in provider_config['models']:
                        model_id = f"{provider['provider_id']}/{model['name']}"
                        available_models.append({
                            'id': model_id,
                            'name': f"{model_id} (provider model)",
                            'type': 'provider'
                        })
            
            return templates.TemplateResponse(
                request=request,
                name="dashboard/user_autoselects.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_autoselects_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "user_id": current_user_id,
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
    db = DatabaseRegistry.get_config_database()
    
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
        db = DatabaseRegistry.get_config_database()
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
    
    db = DatabaseRegistry.get_config_database()
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
        "__version__": __version__,
        "config": aisbf_config,
        "os": os
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
   response_cache_enabled: bool = Form(False),
   response_cache_backend: str = Form("memory"),
   response_cache_ttl: int = Form(600),
   response_cache_max_memory: int = Form(1000),
   response_cache_redis_host: str = Form("localhost"),
   response_cache_redis_port: int = Form(6379),
   response_cache_redis_db: int = Form(0),
   response_cache_redis_password: str = Form(""),
   response_cache_redis_key_prefix: str = Form("aisbf:response:"),
   response_cache_sqlite_path: str = Form("~/.aisbf/response_cache.db"),
   response_cache_mysql_host: str = Form("localhost"),
   response_cache_mysql_port: int = Form(3306),
   response_cache_mysql_user: str = Form("aisbf"),
   response_cache_mysql_password: str = Form(""),
   response_cache_mysql_database: str = Form("aisbf_response_cache"),
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
   signup_require_verification: bool = Form(False),
   verification_token_expiry: int = Form(24),
   smtp_host: str = Form(""),
   smtp_port: int = Form(587),
   smtp_username: str = Form(""),
   smtp_password: str = Form(""),
   smtp_use_tls: bool = Form(True),
   smtp_use_ssl: bool = Form(False),
   smtp_from_email: str = Form(""),
   smtp_from_name: str = Form(""),
   oauth2_google_enabled: bool = Form(False),
   oauth2_google_client_id: str = Form(""),
   oauth2_google_client_secret: str = Form(""),
   oauth2_github_enabled: bool = Form(False),
   oauth2_github_client_id: str = Form(""),
   oauth2_github_client_secret: str = Form(""),
   smtp_enabled: bool = Form(False)
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
        aisbf_config['dashboard']['password'] = _db_hash_password(dashboard_password)
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

    # Update response cache config
    if 'response_cache' not in aisbf_config:
        aisbf_config['response_cache'] = {}
    aisbf_config['response_cache']['enabled'] = response_cache_enabled
    aisbf_config['response_cache']['backend'] = response_cache_backend
    aisbf_config['response_cache']['ttl'] = response_cache_ttl
    aisbf_config['response_cache']['max_memory_cache'] = response_cache_max_memory
    
    # Response cache Redis settings
    aisbf_config['response_cache']['redis_host'] = response_cache_redis_host
    aisbf_config['response_cache']['redis_port'] = response_cache_redis_port
    aisbf_config['response_cache']['redis_db'] = response_cache_redis_db
    if response_cache_redis_password:  # Only update if provided
        aisbf_config['response_cache']['redis_password'] = response_cache_redis_password
    aisbf_config['response_cache']['redis_key_prefix'] = response_cache_redis_key_prefix
    
    # Response cache SQLite settings
    aisbf_config['response_cache']['sqlite_path'] = response_cache_sqlite_path
    
    # Response cache MySQL settings
    aisbf_config['response_cache']['mysql_host'] = response_cache_mysql_host
    aisbf_config['response_cache']['mysql_port'] = response_cache_mysql_port
    aisbf_config['response_cache']['mysql_user'] = response_cache_mysql_user
    if response_cache_mysql_password:  # Only update if provided
        aisbf_config['response_cache']['mysql_password'] = response_cache_mysql_password
    aisbf_config['response_cache']['mysql_database'] = response_cache_mysql_database

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
    
    # Update Signup config
    if 'signup' not in aisbf_config:
        aisbf_config['signup'] = {}
    aisbf_config['signup']['enabled'] = signup_enabled
    aisbf_config['signup']['require_email_verification'] = signup_require_verification
    aisbf_config['signup']['verification_token_expiry_hours'] = verification_token_expiry
    
    # Update SMTP config
    if 'smtp' not in aisbf_config:
        aisbf_config['smtp'] = {}
    aisbf_config['smtp']['enabled'] = smtp_enabled
    aisbf_config['smtp']['host'] = smtp_host
    aisbf_config['smtp']['port'] = smtp_port
    aisbf_config['smtp']['username'] = smtp_username
    # Preserve existing password if submitted field is empty
    if smtp_password:
        aisbf_config['smtp']['password'] = smtp_password
    elif 'password' not in aisbf_config['smtp']:
        # Initialize as empty if not exists
        aisbf_config['smtp']['password'] = ""
    aisbf_config['smtp']['use_tls'] = smtp_use_tls
    aisbf_config['smtp']['use_ssl'] = smtp_use_ssl
    aisbf_config['smtp']['from_email'] = smtp_from_email
    aisbf_config['smtp']['from_name'] = smtp_from_name
    
    # Update OAuth2 config
    if 'oauth2' not in aisbf_config:
        aisbf_config['oauth2'] = {}
    
    # Google OAuth2
    if 'google' not in aisbf_config['oauth2']:
        aisbf_config['oauth2']['google'] = {}
    aisbf_config['oauth2']['google']['enabled'] = oauth2_google_enabled
    aisbf_config['oauth2']['google']['client_id'] = oauth2_google_client_id
    # Preserve existing client_secret if submitted field is empty
    if oauth2_google_client_secret:
        aisbf_config['oauth2']['google']['client_secret'] = oauth2_google_client_secret
    elif 'client_secret' not in aisbf_config['oauth2']['google']:
        aisbf_config['oauth2']['google']['client_secret'] = ""
    aisbf_config['oauth2']['google']['scopes'] = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ]
    
    # GitHub OAuth2
    if 'github' not in aisbf_config['oauth2']:
        aisbf_config['oauth2']['github'] = {}
    aisbf_config['oauth2']['github']['enabled'] = oauth2_github_enabled
    aisbf_config['oauth2']['github']['client_id'] = oauth2_github_client_id
    # Preserve existing client_secret if submitted field is empty
    if oauth2_github_client_secret:
        aisbf_config['oauth2']['github']['client_secret'] = oauth2_github_client_secret
    elif 'client_secret' not in aisbf_config['oauth2']['github']:
        aisbf_config['oauth2']['github']['client_secret'] = ""
    aisbf_config['oauth2']['github']['scopes'] = ["user:email", "read:user"]
    
    # Save config
    config_path = Path.home() / '.aisbf' / 'aisbf.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(aisbf_config, f, indent=2)

    # If a new dashboard password was submitted, clear the forced-change flag
    if dashboard_password:
        request.session.pop('must_change_password', None)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/settings.html",
        context={
        "request": request,
        "session": request.session,
        "config": aisbf_config,
        "os": os,
        "success": "Settings saved successfully! Restart server for changes to take effect."
    }
    )

@app.post("/dashboard/test-smtp")
async def dashboard_test_smtp(request: Request):
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        from aisbf.email_utils import send_test_email
        
        # Send test email to specified recipient
        test_recipient = body.get('test_recipient')
        
        if not test_recipient:
            return JSONResponse({"success": False, "error": "Test recipient email is required"})
        
        # Load the actual saved SMTP config from aisbf.json
        config_path = Path.home() / '.aisbf' / 'aisbf.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'aisbf.json'
        
        with open(config_path) as f:
            aisbf_config = json.load(f)
        
        smtp_config = aisbf_config.get('smtp', {})
        
        result = send_test_email(test_recipient, smtp_config)
        
        if result:
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"success": False, "error": "Failed to send test email"})
    except Exception as e:
        logger.error(f"Error testing SMTP: {e}")
        return JSONResponse({"success": False, "error": str(e)})

# Admin user management routes
@app.get("/dashboard/users", response_class=HTMLResponse)
async def dashboard_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    search: str = Query(None, max_length=100),
    order_by: str = Query('created_at', regex='^(username|last_login|created_at|tier_name)$'),
    direction: str = Query('desc', regex='^(asc|desc)$'),
    status_filter: str = Query(None, regex='^(active|inactive)$'),
    role_filter: str = Query(None, regex='^(admin|user)$')
):
    """Admin user management page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get paginated users
    result = db.get_users_paginated(
        page=page,
        limit=limit,
        search=search,
        order_by=order_by,
        direction=direction,
        status_filter=status_filter,
        role_filter=role_filter
    )
    
    users = result['users']
    total_users = result['total']
    
    # Calculate pagination metadata
    total_pages = (total_users + limit - 1) // limit  # Ceiling division
    current_page = min(page, total_pages) if total_pages > 0 else 1
    start_item = (current_page - 1) * limit + 1
    end_item = min(current_page * limit, total_users)
    
    # Get all tiers for assignment dropdown
    tiers = db.get_all_tiers()
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
            "request": request,
            "session": request.session,
            "users": users,
            "tiers": tiers,
            "pagination": {
                "current_page": current_page,
                "total_pages": total_pages,
                "total_users": total_users,
                "start_item": start_item,
                "end_item": end_item,
                "limit": limit,
                "has_prev": current_page > 1,
                "has_next": current_page < total_pages
            },
            "filters": {
                "search": search or "",
                "order_by": order_by,
                "direction": direction,
                "status_filter": status_filter,
                "role_filter": role_filter
            }
        }
    )

@app.post("/dashboard/users/add")
async def dashboard_users_add(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("user")):
    """Add a new user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    password_hash = _db_hash_password(password)

    try:
        # Get current admin username
        admin_username = request.session.get('username', 'admin')
        # Create user with display_name defaulting to username
        user_id = db.create_user(username, password_hash, role, admin_username, None, False, username)
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
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        # Update user (only if password is provided)
        if password:
            password_hash = _db_hash_password(password)
            db.update_user(user_id, username, password_hash, role, is_active, username)
        else:
            db.update_user(user_id, username, None, role, is_active, username)
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
    
    db = DatabaseRegistry.get_config_database()
    
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
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        db.delete_user(user_id)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/dashboard/users/{user_id}/tier")
async def dashboard_users_update_tier(request: Request, user_id: int):
    """Update user tier assignment"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        body = await request.json()
        tier_id = body.get('tier_id')
        
        if not tier_id:
            return JSONResponse({"success": False, "error": "tier_id is required"}, status_code=400)
        
        # Verify tier exists
        tier = db.get_tier_by_id(tier_id)
        if not tier:
            return JSONResponse({"success": False, "error": "Tier not found"}, status_code=404)
        
        # Update user tier
        success = db.set_user_tier(user_id, tier_id)
        
        if success:
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"success": False, "error": "Failed to update user tier"}, status_code=500)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/dashboard/users/bulk")
async def dashboard_users_bulk(request: Request):
    """Handle bulk user operations"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()

    try:
        body = await request.json()
        action = body.get('action')
        user_ids = body.get('user_ids', [])
        extra_data = body.get('extra_data')

        if not action or not user_ids:
            return JSONResponse({"success": False, "error": "Action and user_ids required"}, status_code=400)

        # Validate user_ids
        if not isinstance(user_ids, list) or not all(isinstance(uid, int) for uid in user_ids):
            return JSONResponse({"success": False, "error": "user_ids must be a list of integers"}, status_code=400)

        if action == 'enable':
            success_count = 0
            for user_id in user_ids:
                if db.update_user(user_id, None, None, None, True):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Enabled {success_count} of {len(user_ids)} users"})

        elif action == 'disable':
            success_count = 0
            for user_id in user_ids:
                if db.update_user(user_id, None, None, None, False):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Disabled {success_count} of {len(user_ids)} users"})

        elif action == 'delete':
            success_count = 0
            for user_id in user_ids:
                try:
                    db.delete_user(user_id)
                    success_count += 1
                except Exception:
                    pass  # Continue with other deletions
            return JSONResponse({"success": True, "message": f"Deleted {success_count} of {len(user_ids)} users"})

        elif action == 'tier':
            tier_id = extra_data
            if not tier_id:
                return JSONResponse({"success": False, "error": "tier_id required for tier action"}, status_code=400)

            # Verify tier exists
            tier = db.get_tier_by_id(tier_id)
            if not tier:
                return JSONResponse({"success": False, "error": "Tier not found"}, status_code=404)

            success_count = 0
            for user_id in user_ids:
                if db.set_user_tier(user_id, tier_id):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Changed tier for {success_count} of {len(user_ids)} users"})

        else:
            return JSONResponse({"success": False, "error": "Invalid action"}, status_code=400)

    except Exception as e:
        logger.error(f"Bulk operation error: {e}")
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)

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
            from aisbf.database import DatabaseRegistry
            DatabaseRegistry.get_config_database(db_config)

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
    db = DatabaseRegistry.get_config_database()

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
    is_config_admin = request.session.get('user_id') is None
    logger.info(f"🔍 UPLOAD HANDLER DEBUG: session.user_id = {request.session.get('user_id')}, is_config_admin = {is_config_admin}")

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
        logger.info(f"🔍 UPLOAD HANDLER: Received file {file.filename}, size: {len(content)} bytes")

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

            # Update providers.json with full path to the uploaded file
            try:
                config_path = Path.home() / '.aisbf' / 'providers.json'
                if not config_path.exists():
                    config_path = Path(__file__).parent / 'config' / 'providers.json'
                
                with open(config_path) as f:
                    full_config = json.load(f)
                
                # Navigate to the provider config
                if 'providers' in full_config and isinstance(full_config['providers'], dict):
                    providers = full_config['providers']
                else:
                    providers = full_config
                
                # Update the file path in provider config
                if provider_name in providers:
                    # Convert absolute path to ~/... format
                    relative_path = str(file_path).replace(str(Path.home()), '~')
                    
                    # Update the correct location based on provider type
                    provider_type = providers[provider_name].get('type', '')
                    
                    # For Kiro, update kiro_config.sqlite_db or kiro_config.creds_file
                    if provider_type == 'kiro' and file_type in ['sqlite_db', 'creds_file']:
                        if 'kiro_config' not in providers[provider_name]:
                            providers[provider_name]['kiro_config'] = {}
                        providers[provider_name]['kiro_config'][file_type] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.kiro_config.{file_type} = {relative_path}")
                    
                    # For Claude, update claude_config.credentials_file
                    elif provider_type == 'claude' and file_type in ['credentials_file', 'claude_credentials']:
                        if 'claude_config' not in providers[provider_name]:
                            providers[provider_name]['claude_config'] = {}
                        providers[provider_name]['claude_config']['credentials_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.claude_config.credentials_file = {relative_path}")
                    
                    # For Kilo, update kilo_config.creds_file
                    elif provider_type in ['kilo', 'kilocode'] and file_type in ['credentials_file', 'creds_file']:
                        if 'kilo_config' not in providers[provider_name]:
                            providers[provider_name]['kilo_config'] = {}
                        providers[provider_name]['kilo_config']['creds_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.kilo_config.creds_file = {relative_path}")
                    
                    # For Qwen, update qwen_config.credentials_file
                    elif provider_type == 'qwen' and file_type in ['credentials_file']:
                        if 'qwen_config' not in providers[provider_name]:
                            providers[provider_name]['qwen_config'] = {}
                        providers[provider_name]['qwen_config']['credentials_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.qwen_config.credentials_file = {relative_path}")
                    
                    # For Codex, update codex_config.credentials_file
                    elif provider_type == 'codex' and file_type in ['credentials_file', 'creds_file']:
                        if 'codex_config' not in providers[provider_name]:
                            providers[provider_name]['codex_config'] = {}
                        providers[provider_name]['codex_config']['credentials_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.codex_config.credentials_file = {relative_path}")
                    
                    # Fallback: update top-level field
                    else:
                        providers[provider_name][file_type] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.{file_type} = {relative_path}")
                    
                    # Save updated config
                    save_path = Path.home() / '.aisbf' / 'providers.json'
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, 'w') as f:
                        json.dump(full_config, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to update providers.json: {e}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
        else:
            # Database user: save to database
            db = DatabaseRegistry.get_config_database()

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
            db = DatabaseRegistry.get_config_database()

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

        # Create temporary upload directory in user's home
        if is_config_admin:
            # Config admin: use their home directory
            temp_dir = Path.home() / '.aisbf' / 'temp_uploads'
        else:
            # Database user: use their auth files directory
            temp_dir = get_user_auth_files_dir(current_user_id) / 'temp_uploads'
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
                db = DatabaseRegistry.get_config_database()
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
            else:
                # Config admin: update providers.json with full path
                try:
                    config_path = Path.home() / '.aisbf' / 'providers.json'
                    if not config_path.exists():
                        config_path = Path(__file__).parent / 'config' / 'providers.json'
                    
                    with open(config_path) as f:
                        full_config = json.load(f)
                    
                    # Navigate to the provider config
                    if 'providers' in full_config and isinstance(full_config['providers'], dict):
                        providers = full_config['providers']
                    else:
                        providers = full_config
                    
                    # Update the file path in provider config
                    if provider_key in providers:
                        # Convert absolute path to ~/... format
                        relative_path = str(file_path).replace(str(Path.home()), '~')
                        
                        # Update the correct location based on provider type
                        provider_type = providers[provider_key].get('type', '')
                        
                        # For Kiro, update kiro_config.sqlite_db or kiro_config.creds_file
                        if provider_type == 'kiro' and file_type in ['sqlite_db', 'creds_file']:
                            if 'kiro_config' not in providers[provider_key]:
                                providers[provider_key]['kiro_config'] = {}
                            providers[provider_key]['kiro_config'][file_type] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.kiro_config.{file_type} = {relative_path}")
                        
                        # For Claude, update claude_config.credentials_file
                        elif provider_type == 'claude' and file_type in ['credentials_file', 'claude_credentials']:
                            if 'claude_config' not in providers[provider_key]:
                                providers[provider_key]['claude_config'] = {}
                            providers[provider_key]['claude_config']['credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.claude_config.credentials_file = {relative_path}")
                        
                        # For Kilo, update kilo_config.creds_file
                        elif provider_type in ['kilo', 'kilocode'] and file_type in ['credentials_file', 'creds_file']:
                            if 'kilo_config' not in providers[provider_key]:
                                providers[provider_key]['kilo_config'] = {}
                            providers[provider_key]['kilo_config']['creds_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.kilo_config.creds_file = {relative_path}")
                        
                        # For Qwen, update qwen_config.credentials_file
                        elif provider_type == 'qwen' and file_type in ['credentials_file']:
                            if 'qwen_config' not in providers[provider_key]:
                                providers[provider_key]['qwen_config'] = {}
                            providers[provider_key]['qwen_config']['credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.qwen_config.credentials_file = {relative_path}")
                        
                        # For Codex, update codex_config.credentials_file
                        elif provider_type == 'codex' and file_type in ['credentials_file', 'creds_file']:
                            if 'codex_config' not in providers[provider_key]:
                                providers[provider_key]['codex_config'] = {}
                            providers[provider_key]['codex_config']['credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.codex_config.credentials_file = {relative_path}")
                        
                        # Fallback: update top-level field
                        else:
                            providers[provider_key][file_type] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.{file_type} = {relative_path}")
                        
                        # Save updated config
                        save_path = Path.home() / '.aisbf' / 'providers.json'
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(save_path, 'w') as f:
                            json.dump(full_config, f, indent=2)
                except Exception as e:
                    logger.error(f"Failed to update providers.json: {e}")

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
        except Exception:
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


# OAuth authentication check endpoints for providers
@app.get("/dashboard/providers/{provider_name}/auth/check")
async def dashboard_provider_auth_check(request: Request, provider_name: str):
    """Check OAuth authentication status for a provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        # Get user ID from session
        current_user_id = request.session.get('user_id')
        
        # Load provider configuration
        provider_config = None
        
        if current_user_id is None:
            # Admin: check global config
            global_config = Config()
            provider_config = global_config.providers.get(provider_name)
        else:
            # Regular user: get from user providers
            from aisbf.database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            user_provider = db.get_user_provider(current_user_id, provider_name)
            if user_provider:
                provider_config = user_provider['config']

        if not provider_config:
            return JSONResponse(
                status_code=404,
                content={"authenticated": False, "error": f"Provider '{provider_name}' not found"}
            )

        # Handle both dict (user providers) and object (global providers)
        if isinstance(provider_config, dict):
            provider_type = provider_config.get('type')
        else:
            provider_type = provider_config.type

        if provider_type == 'claude':
            from aisbf.auth.claude import ClaudeAuth
            # Handle dict vs object
            if isinstance(provider_config, dict):
                claude_config = provider_config.get('claude_config', {})
            else:
                claude_config = provider_config.claude_config or {}
            
            if current_user_id is None:
                # Admin user: load from file
                auth = ClaudeAuth(credentials_file=claude_config.get('credentials_file', '~/.claude_credentials.json'))
            else:
                # Regular user: load from database
                auth = ClaudeAuth(
                    credentials_file=claude_config.get('credentials_file', '~/.claude_credentials.json'),
                    skip_initial_load=True
                )
                # Load credentials from database
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='claude_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.tokens = db_creds['credentials'].get('tokens', {})
                            # Add expires_at if missing (for existing credentials saved before fix)
                            if auth.tokens and 'expires_at' not in auth.tokens and 'expires_in' in auth.tokens:
                                auth.tokens['expires_at'] = time.time() + auth.tokens.get('expires_in', 3600)
                except Exception as e:
                    logger.warning(f"Failed to load Claude credentials from database: {e}")
            
            is_auth = auth.is_authenticated()
            result = {"authenticated": is_auth}
            if is_auth and auth.tokens and 'expires_at' in auth.tokens:
                result["expires_at"] = auth.tokens['expires_at']
            return JSONResponse(result)

        elif provider_type == 'kilocode':
            from aisbf.auth.kilo import KiloOAuth2
            # Handle dict vs object
            if isinstance(provider_config, dict):
                kilo_config = provider_config.get('kilo_config', {})
            else:
                kilo_config = provider_config.kilo_config or {}
            
            if current_user_id is None:
                # Admin user: load from file
                auth = KiloOAuth2(credentials_file=kilo_config.get('credentials_file', '~/.kilo_credentials.json'))
            else:
                # Regular user: load from database
                auth = KiloOAuth2(
                    credentials_file=kilo_config.get('credentials_file', '~/.kilo_credentials.json'),
                    skip_initial_load=True
                )
                # Load credentials from database
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='kilo_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.credentials = db_creds['credentials']
                except Exception as e:
                    logger.warning(f"Failed to load Kilo credentials from database: {e}")
            
            is_auth = auth.is_authenticated()
            result = {"authenticated": is_auth}
            if is_auth and auth.credentials:
                expires = auth.credentials.get('expires', 0)
                if expires:
                    result["expires_at"] = expires
            return JSONResponse(result)

        elif provider_type == 'qwen':
            from aisbf.auth.qwen import QwenOAuth2
            # Handle dict vs object
            if isinstance(provider_config, dict):
                qwen_config = provider_config.get('qwen_config', {})
            else:
                qwen_config = provider_config.qwen_config or {}
            
            if current_user_id is None:
                # Admin user: load from file
                auth = QwenOAuth2(credentials_file=qwen_config.get('credentials_file', '~/.aisbf/qwen_credentials.json'))
            else:
                # Regular user: load from database
                auth = QwenOAuth2(
                    credentials_file=qwen_config.get('credentials_file', '~/.aisbf/qwen_credentials.json'),
                    skip_initial_load=True
                )
                # Load credentials from database
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='qwen_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.credentials = db_creds['credentials']
                except Exception as e:
                    logger.warning(f"Failed to load Qwen credentials from database: {e}")
            
            is_auth = auth.is_authenticated()
            result = {"authenticated": is_auth}
            if is_auth and auth.credentials:
                expiry_date = auth.credentials.get('expiry_date', 0)
                if expiry_date:
                    # Convert from milliseconds to seconds
                    result["expires_at"] = expiry_date / 1000
            return JSONResponse(result)

        elif provider_type == 'codex':
            from aisbf.auth.codex import CodexOAuth2
            # Handle dict vs object
            if isinstance(provider_config, dict):
                codex_config = provider_config.get('codex_config', {})
            else:
                codex_config = provider_config.codex_config or {}
            
            if current_user_id is None:
                # Admin user: load from file
                auth = CodexOAuth2(credentials_file=codex_config.get('credentials_file', '~/.aisbf/codex_credentials.json'))
            else:
                # Regular user: load from database
                auth = CodexOAuth2(
                    credentials_file=codex_config.get('credentials_file', '~/.aisbf/codex_credentials.json'),
                    skip_initial_load=True
                )
                # Load credentials from database
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='codex_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.credentials = db_creds['credentials']
                except Exception as e:
                    logger.warning(f"Failed to load Codex credentials from database: {e}")
            
            is_auth = auth.is_authenticated()
            result = {"authenticated": is_auth}
            if is_auth and auth.credentials:
                expires = auth.credentials.get('expires', 0)
                if expires:
                    result["expires_at"] = expires
            return JSONResponse(result)

        else:
            return JSONResponse(
                status_code=400,
                content={"authenticated": False, "error": f"Provider type '{provider_type}' does not support OAuth authentication checks"}
            )

    except Exception as e:
        logger.error(f"Error checking auth for provider {provider_name}: {e}")
        return JSONResponse(
            status_code=500,
            content={"authenticated": False, "error": str(e)}
        )


# User-specific rotation management routes
@app.get("/dashboard/user/rotations", response_class=HTMLResponse)
async def dashboard_user_rotations(request: Request):
    """Redirect to unified rotations endpoint"""
    return RedirectResponse(url=url_for(request, "/dashboard/rotations"), status_code=301)

@app.post("/dashboard/user/rotations")
async def dashboard_user_rotations_save(request: Request, config: str = Form(...)):
    """Redirect to unified rotations save endpoint"""
    return await dashboard_rotations_save(request, config)

@app.delete("/dashboard/user/rotations/{rotation_name}")
async def dashboard_user_rotations_delete(request: Request, rotation_name: str):
    """Delete user-specific rotation configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    db = DatabaseRegistry.get_config_database()

    try:
        db.delete_user_rotation(user_id, rotation_name)
        return JSONResponse({"message": "Rotation deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# User-specific autoselect management routes
@app.get("/dashboard/user/autoselects", response_class=HTMLResponse)
async def dashboard_user_autoselects(request: Request):
    """Redirect to unified autoselect endpoint"""
    return RedirectResponse(url=url_for(request, "/dashboard/autoselect"), status_code=301)

@app.post("/dashboard/user/autoselects")
async def dashboard_user_autoselects_save(request: Request, config: str = Form(...)):
    """Redirect to unified autoselect save endpoint"""
    return await dashboard_autoselect_save(request, config)

@app.delete("/dashboard/user/autoselects/{autoselect_name}")
async def dashboard_user_autoselects_delete(request: Request, autoselect_name: str):
    """Delete user-specific autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    db = DatabaseRegistry.get_config_database()

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

    db = DatabaseRegistry.get_config_database()

    # Get user API tokens
    user_tokens = db.get_user_api_tokens(user_id)
    
    # Convert datetime objects to strings for JSON serialization
    for token in user_tokens:
        if 'created_at' in token and token['created_at']:
            token['created_at'] = token['created_at'].isoformat() if hasattr(token['created_at'], 'isoformat') else str(token['created_at'])
        if 'last_used' in token and token['last_used']:
            token['last_used'] = token['last_used'].isoformat() if hasattr(token['last_used'], 'isoformat') else str(token['last_used'])

    return templates.TemplateResponse(
        request=request,
        name="dashboard/user_tokens.html",
        context={
        "request": request,
        "session": request.session,
        "__version__": __version__,
        "user_tokens": user_tokens,
        "user_id": user_id
    }
    )

@app.post("/dashboard/user/tokens")
async def dashboard_user_tokens_create(request: Request, description: str = Form(""), scope: str = Form("api")):
    """Create a new user API token"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if scope not in ('api', 'mcp', 'both'):
        scope = 'api'

    import secrets

    db = DatabaseRegistry.get_config_database()

    # Generate a secure token
    token = secrets.token_urlsafe(32)

    try:
        token_id = db.create_user_api_token(user_id, token, description.strip() or None, scope)
        return JSONResponse({
            "message": "Token created successfully",
            "token": token,
            "token_id": token_id,
            "scope": scope
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

    db = DatabaseRegistry.get_config_database()

    try:
        db.delete_user_api_token(user_id, token_id)
        return JSONResponse(content={"success": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/dashboard/cache-settings", response_class=HTMLResponse)
async def dashboard_user_cache_settings(request: Request):
    """User prompt cache settings page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()
    
    # Get all cache settings for user
    cache_settings = db.get_all_user_cache_settings(user_id)
    
    # Convert datetime objects to strings
    for setting in cache_settings:
        if 'created_at' in setting and setting['created_at']:
            setting['created_at'] = setting['created_at'].isoformat() if hasattr(setting['created_at'], 'isoformat') else str(setting['created_at'])
        if 'updated_at' in setting and setting['updated_at']:
            setting['updated_at'] = setting['updated_at'].isoformat() if hasattr(setting['updated_at'], 'isoformat') else str(setting['updated_at'])
    
    # Get user's providers for dropdown
    user_providers = db.get_user_providers(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/cache_settings.html",
        context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "cache_settings": cache_settings,
            "user_providers": user_providers,
            "user_id": user_id
        }
    )

@app.get("/dashboard/api/cache-settings")
async def dashboard_api_get_cache_settings(request: Request):
    """Get logged-in user's cache settings"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()
    
    provider_id = request.query_params.get('provider_id')
    model_name = request.query_params.get('model_name')
    
    if provider_id or model_name:
        # Get specific setting
        setting = db.get_user_cache_settings(user_id, provider_id, model_name)
        # Convert datetime to string if present
        if setting and 'updated_at' in setting and setting['updated_at']:
            setting['updated_at'] = setting['updated_at'].isoformat() if hasattr(setting['updated_at'], 'isoformat') else str(setting['updated_at'])
        return JSONResponse(setting)
    else:
        # Get all settings
        settings = db.get_all_user_cache_settings(user_id)
        # Convert datetime objects to strings
        for setting in settings:
            if 'updated_at' in setting and setting['updated_at']:
                setting['updated_at'] = setting['updated_at'].isoformat() if hasattr(setting['updated_at'], 'isoformat') else str(setting['updated_at'])
            if 'created_at' in setting and setting['created_at']:
                setting['created_at'] = setting['created_at'].isoformat() if hasattr(setting['created_at'], 'isoformat') else str(setting['created_at'])
        return JSONResponse({"settings": settings})

@app.post("/dashboard/api/cache-settings")
async def dashboard_api_set_cache_setting(request: Request):
    """Set logged-in user's cache setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')

    try:
        body = await request.json()
        provider_id = body.get('provider_id')
        model_name = body.get('model_name')
        cache_enabled = body.get('cache_enabled', True)
        
        db = DatabaseRegistry.get_config_database()
        success = db.set_user_cache_setting(user_id, cache_enabled, provider_id, model_name)
        
        if success:
            return JSONResponse({"success": True, "message": "Cache setting updated"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to update setting"})
    except Exception as e:
        logger.error(f"Error setting cache setting: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/dashboard/api/cache-settings")
async def dashboard_api_delete_cache_setting(request: Request):
    """Delete logged-in user's cache setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')

    try:
        provider_id = request.query_params.get('provider_id')
        model_name = request.query_params.get('model_name')
        
        db = DatabaseRegistry.get_config_database()
        success = db.delete_user_cache_setting(user_id, provider_id, model_name)
        
        if success:
            return JSONResponse({"success": True, "message": "Cache setting deleted"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to delete setting"})
    except Exception as e:
        logger.error(f"Error deleting cache setting: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/dashboard/response-cache/stats")
async def dashboard_response_cache_stats(request: Request):
    """Get response cache statistics"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    from aisbf.cache import get_response_cache
    
    try:
        cache = get_response_cache()
        
        if is_admin:
            # Admin sees global stats
            stats = cache.get_stats()
        else:
            # Regular users see their own personal cache impact
            stats = cache.get_user_stats(current_user_id)
            
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

@app.get("/dashboard/admin/tiers")
async def dashboard_admin_tiers(request: Request):
    """Admin account tiers management page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tiers = db.get_all_tiers()
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/admin_tiers.html",
        context={
        "request": request,
        "session": request.session,
        "tiers": tiers
    }
    )

# API endpoints for tiers CRUD operations
@app.get("/api/admin/tiers")
async def api_list_tiers(request: Request):
    """List all tiers - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tiers = db.get_all_tiers()
    return JSONResponse(tiers)

@app.get("/api/admin/tiers/{tier_id}")
async def api_get_tier(tier_id: int, request: Request):
    """Get specific tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tier = db.get_tier_by_id(tier_id)
    if not tier:
        return JSONResponse({"error": "Tier not found"}, status_code=404)
    
    return JSONResponse(tier)

@app.post("/api/admin/tiers")
async def api_create_tier(request: Request):
    """Create a new tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        body = await request.json()
        
        tier_id = db.create_tier(
            name=body.get('name'),
            description=body.get('description', ''),
            price_monthly=body.get('price_monthly', 0.0),
            price_yearly=body.get('price_yearly', 0.0),
            max_requests_per_day=body.get('max_requests_per_day', -1),
            max_requests_per_month=body.get('max_requests_per_month', -1),
            max_providers=body.get('max_providers', -1),
            max_rotations=body.get('max_rotations', -1),
            max_autoselections=body.get('max_autoselections', -1),
            max_rotation_models=body.get('max_rotation_models', -1),
            max_autoselection_models=body.get('max_autoselection_models', -1),
            is_active=body.get('is_active', True),
            is_visible=body.get('is_visible', True)
        )
        
        return JSONResponse({"success": True, "tier_id": tier_id})
    except Exception as e:
        logger.error(f"Error creating tier: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/api/admin/tiers/{tier_id}")
async def api_update_tier(request: Request, tier_id: int):
    """Update an existing tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        body = await request.json()
        
        # Build update kwargs
        update_kwargs = {}
        if 'name' in body:
            update_kwargs['name'] = body['name']
        if 'description' in body:
            update_kwargs['description'] = body['description']
        if 'price_monthly' in body:
            update_kwargs['price_monthly'] = body['price_monthly']
        if 'price_yearly' in body:
            update_kwargs['price_yearly'] = body['price_yearly']
        if 'max_requests_per_day' in body:
            update_kwargs['max_requests_per_day'] = body['max_requests_per_day']
        if 'max_requests_per_month' in body:
            update_kwargs['max_requests_per_month'] = body['max_requests_per_month']
        if 'max_providers' in body:
            update_kwargs['max_providers'] = body['max_providers']
        if 'max_rotations' in body:
            update_kwargs['max_rotations'] = body['max_rotations']
        if 'max_autoselections' in body:
            update_kwargs['max_autoselections'] = body['max_autoselections']
        if 'max_rotation_models' in body:
            update_kwargs['max_rotation_models'] = body['max_rotation_models']
        if 'max_autoselection_models' in body:
            update_kwargs['max_autoselection_models'] = body['max_autoselection_models']
        if 'is_active' in body:
            update_kwargs['is_active'] = body['is_active']
        if 'is_visible' in body:
            update_kwargs['is_visible'] = body['is_visible']
        
        success = db.update_tier(tier_id, **update_kwargs)
        
        if not success:
            return JSONResponse({"error": "Tier not found or no changes"}, status_code=404)
        
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error updating tier: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/admin/tiers/{tier_id}")
async def api_delete_tier(request: Request, tier_id: int):
    """Delete a tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        success = db.delete_tier(tier_id)
        
        if not success:
            return JSONResponse({"error": "Cannot delete default tier or tier not found"}, status_code=400)
        
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error deleting tier: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# Tier form pages
@app.get("/dashboard/admin/tiers/create")
async def dashboard_admin_tier_create(request: Request):
    """Create tier page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/admin_tier_form.html",
        context={
            "request": request,
            "session": request.session,
            "tier": None
        }
    )

@app.get("/dashboard/admin/tiers/edit/{tier_id}")
async def dashboard_admin_tier_edit(request: Request, tier_id: int):
    """Edit tier page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tier = db.get_tier_by_id(tier_id)
    if not tier:
        return RedirectResponse(url=url_for(request, "/dashboard/admin/tiers"), status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/admin_tier_form.html",
        context={
            "request": request,
            "session": request.session,
            "tier": tier
        }
    )

@app.post("/dashboard/admin/tiers/save")
async def dashboard_admin_tier_save(request: Request):
    """Save tier (create or update)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        form = await request.form()
        tier_id = form.get('tier_id')
        
        tier_data = {
            'name': form.get('name'),
            'description': form.get('description', ''),
            'price_monthly': float(form.get('price_monthly', 0)),
            'price_yearly': float(form.get('price_yearly', 0)),
            'max_requests_per_day': int(form.get('max_requests_per_day', -1)),
            'max_requests_per_month': int(form.get('max_requests_per_month', -1)),
            'max_providers': int(form.get('max_providers', -1)),
            'max_rotations': int(form.get('max_rotations', -1)),
            'max_autoselections': int(form.get('max_autoselections', -1)),
            'max_rotation_models': int(form.get('max_rotation_models', -1)),
            'max_autoselection_models': int(form.get('max_autoselection_models', -1)),
            'is_active': form.get('is_active') == '1',
            'is_visible': form.get('is_visible') == '1'
        }
        
        if tier_id:
            # Update existing tier
            db.update_tier(int(tier_id), **tier_data)
        else:
            # Create new tier
            db.create_tier(**tier_data)
        
        return RedirectResponse(url=url_for(request, "/dashboard/admin/tiers"), status_code=303)
    except Exception as e:
        logger.error(f"Error saving tier: {e}")
        return RedirectResponse(url=url_for(request, "/dashboard/admin/tiers"), status_code=303)

# Currency settings endpoints
@app.get("/api/admin/settings/currency")
async def api_get_currency_settings(request: Request):
    """Get currency settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get currency settings from database
    settings = db.get_currency_settings()
    
    return JSONResponse(settings)

@app.post("/api/admin/settings/currency")
async def api_save_currency_settings(request: Request):
    """Save currency settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        
        db = DatabaseRegistry.get_config_database()
        
        # Save currency settings to database
        db.save_currency_settings(body)
        
        return JSONResponse({"success": True, "message": "Currency settings saved"})
    except Exception as e:
        logger.error(f"Error saving currency settings: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# Payment gateway settings endpoints
@app.get("/api/admin/settings/payment-gateways")
async def api_get_payment_gateways(request: Request):
    """Get payment gateway settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get payment gateway settings from database
    gateways = db.get_payment_gateway_settings()
    
    return JSONResponse(gateways)

@app.post("/api/admin/settings/payment-gateways")
async def api_save_payment_gateways(request: Request):
    """Save payment gateway settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        
        db = DatabaseRegistry.get_config_database()
        
        # Save payment gateway settings to database
        db.save_payment_gateway_settings(body)
        
        return JSONResponse({"success": True, "message": "Payment gateway settings saved"})
    except Exception as e:
        logger.error(f"Error saving payment gateway settings: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/admin/settings/encryption-key")
async def api_get_encryption_key_status(request: Request):
    """Get encryption key status - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        encryption_key = db.get_encryption_key()
        
        # Check if key is set in database or environment
        env_key = os.getenv('ENCRYPTION_KEY')
        
        if encryption_key:
            source = 'database'
            is_set = True
        elif env_key:
            source = 'environment'
            is_set = True
        else:
            source = 'temporary'
            is_set = False
        
        return JSONResponse({
            "is_set": is_set,
            "source": source
        })
    except Exception as e:
        logger.error(f"Error getting encryption key status: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/admin/crypto/prices")
async def api_get_crypto_prices(request: Request):
    """Get crypto prices (BTC, ETH, USDT, USDC) from all enabled sources - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        
        # Get enabled price sources
        with db._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT name, is_enabled
                    FROM crypto_price_sources
                """)
                sources = {row[0].lower(): bool(row[1]) for row in cursor.fetchall()}
            except Exception:
                # Default if table doesn't exist yet
                sources = {'coinbase': True, 'binance': True, 'kraken': True}
        
        # Get currency settings
        currency_settings = db.get_currency_settings()
        currency_code = currency_settings.get('currency_code', 'EUR')
        
        result = {}
        
        # Cache for supported pairs
        supported_pairs_cache = getattr(asyncio, '__pair_cache', {})
        cache_expiry = getattr(asyncio, '__pair_cache_expiry', 0)
        
        if time.time() > cache_expiry:
            supported_pairs_cache = {}
            cache_expiry = time.time() + 86400  # 24 hour cache
            setattr(asyncio, '__pair_cache', supported_pairs_cache)
            setattr(asyncio, '__pair_cache_expiry', cache_expiry)
        
        # Fetch prices for each cryptocurrency
        for crypto_symbol, crypto_name in [('BTC', 'btc'), ('ETH', 'eth'), ('USDT', 'usdt'), ('USDC', 'usdc')]:
            prices = {}
            enabled_prices = []
            cache_key = f"{crypto_symbol}:{currency_code}"
            
            # Coinbase
            if sources.get('coinbase', False):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(f'https://api.coinbase.com/v2/prices/{crypto_symbol}-{currency_code}/spot')
                        if response.status_code == 200:
                            data = response.json()
                            price = float(data['data']['amount'])
                            prices['coinbase'] = price
                            enabled_prices.append(price)
                            supported_pairs_cache[f"coinbase:{cache_key}"] = True
                except Exception as e:
                    supported_pairs_cache[f"coinbase:{cache_key}"] = False
                    logger.debug(f"Coinbase does not support {crypto_symbol}/{currency_code} pair: {e}")
                    prices['coinbase'] = None
            else:
                prices['coinbase'] = None
            
            # Binance
            if sources.get('binance', False):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # Try direct pair first
                        symbol = f"{crypto_symbol}{currency_code}"
                        response = await client.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}')
                        
                        if response.status_code != 200:
                            # Fallback to USDT pair if direct pair not available
                            symbol = f"{crypto_symbol}USDT"
                            response = await client.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}')
                            
                            if response.status_code == 200:
                                # Get USD/EUR rate if needed
                                if currency_code != 'USD':
                                    usd_resp = await client.get('https://api.coinbase.com/v2/prices/USD-EUR/spot')
                                    if usd_resp.status_code == 200:
                                        usd_eur = float(usd_resp.json()['data']['amount'])
                                        data = response.json()
                                        price = float(data['price']) * usd_eur
                                        prices['binance'] = price
                                        enabled_prices.append(price)
                                        supported_pairs_cache[f"binance:{cache_key}"] = "usdt_fallback"
                        else:
                            data = response.json()
                            price = float(data['price'])
                            prices['binance'] = price
                            enabled_prices.append(price)
                            supported_pairs_cache[f"binance:{cache_key}"] = True
                            
                except Exception as e:
                    supported_pairs_cache[f"binance:{cache_key}"] = False
                    logger.debug(f"Binance does not support {crypto_symbol}/{currency_code} pair: {e}")
                    prices['binance'] = None
            else:
                prices['binance'] = None
            
            # Kraken
            if sources.get('kraken', False):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # Kraken symbols
                        kraken_prefix = {
                            'BTC': 'XXBT',
                            'ETH': 'XETH',
                            'USDT': 'USDT',
                            'USDC': 'USDC'
                        }.get(crypto_symbol, crypto_symbol)
                        
                        pair = f"{kraken_prefix}Z{currency_code}"
                        response = await client.get(f'https://api.kraken.com/0/public/Ticker?pair={pair}')
                        
                        if response.status_code == 200:
                            data = response.json()
                            if not data.get('error') and 'result' in data and data['result']:
                                result_key = list(data['result'].keys())[0]
                                price = float(data['result'][result_key]['c'][0])
                                prices['kraken'] = price
                                enabled_prices.append(price)
                                supported_pairs_cache[f"kraken:{cache_key}"] = True
                            else:
                                supported_pairs_cache[f"kraken:{cache_key}"] = False
                except Exception as e:
                    supported_pairs_cache[f"kraken:{cache_key}"] = False
                    logger.debug(f"Kraken does not support {crypto_symbol}/{currency_code} pair: {e}")
                    prices['kraken'] = None
            else:
                prices['kraken'] = None
            
            # Calculate average only if we have valid prices
            if enabled_prices:
                prices['average'] = sum(enabled_prices) / len(enabled_prices)
            else:
                prices['average'] = None
            
            result[crypto_name] = prices
        
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Error getting crypto prices: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/admin/crypto/btc-prices")
async def api_get_btc_prices(request: Request):
    """Get BTC prices from all enabled sources - API endpoint (legacy, redirects to /prices)"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        # Call the new endpoint and extract BTC data
        full_response = await api_get_crypto_prices(request)
        if isinstance(full_response, JSONResponse):
            import json
            data = json.loads(full_response.body.decode())
            if 'btc' in data:
                return JSONResponse(data['btc'])
        return full_response
    except Exception as e:
        logger.error(f"Error getting BTC prices: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/admin/settings/encryption-key")
async def api_save_encryption_key(request: Request):
    """Save encryption key - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        encryption_key = body.get('encryption_key', '').strip()
        
        if not encryption_key:
            return JSONResponse({"success": False, "error": "Encryption key is required"}, status_code=400)
        
        if len(encryption_key) != 44:
            return JSONResponse({"success": False, "error": "Encryption key must be 44 characters (base64 encoded)"}, status_code=400)
        
        db = DatabaseRegistry.get_config_database()
        success = db.save_encryption_key(encryption_key)
        
        if success:
            logger.info("Encryption key saved to database by admin")
            return JSONResponse({"success": True, "message": "Encryption key saved successfully. Restart server to apply."})
        else:
            return JSONResponse({"success": False, "error": "Failed to save encryption key"}, status_code=500)
    except Exception as e:
        logger.error(f"Error saving encryption key: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/admin/settings/crypto-seeds-reset")
async def api_reset_crypto_seeds(request: Request):
    """Delete all crypto master seeds so they are regenerated on next restart"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check

    try:
        db = DatabaseRegistry.get_config_database()
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM crypto_master_keys")
            deleted = cursor.rowcount
            conn.commit()
        logger.warning(f"Admin reset crypto master seeds: {deleted} rows deleted")
        return JSONResponse({"success": True, "deleted": deleted})
    except Exception as e:
        logger.error(f"Error resetting crypto seeds: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Admin configuration API endpoints
@app.get("/api/admin/config/price-sources")
async def get_price_sources(request: Request):
    """Get crypto price source configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT crypto_type, price_source, api_key, update_interval_seconds, is_enabled
            FROM crypto_price_sources
        """)
        rows = cursor.fetchall()
    
    sources = [
        {
            'crypto_type': row[0],
            'price_source': row[1],
            'api_key': row[2],
            'update_interval': row[3],
            'enabled': bool(row[4])
        }
        for row in rows
    ]
    
    return JSONResponse({'price_sources': sources})


@app.put("/api/admin/payment-system/config/price-sources")
async def update_payment_price_sources(request: Request):
    """Update crypto price source configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            for source in body.get('price_sources', []):
                cursor.execute(f"""
                    UPDATE crypto_price_sources
                    SET price_source = {placeholder},
                        api_key = {placeholder},
                        update_interval_seconds = {placeholder},
                        is_enabled = {placeholder}
                    WHERE crypto_type = {placeholder}
                """, (
                    source['price_source'],
                    source.get('api_key'),
                    source['update_interval'],
                    source['enabled'],
                    source['crypto_type']
                ))
            
            conn.commit()
        
        return JSONResponse({'success': True, 'message': 'Price sources updated'})
    except Exception as e:
        logger.error(f"Error updating price sources: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post("/api/admin/config/price-sources")
async def update_price_sources(request: Request):
    """Update crypto price source configuration (legacy endpoint)"""
    return await update_payment_price_sources(request)


@app.get("/api/admin/config/consolidation")
async def get_consolidation_config(request: Request):
    """Get wallet consolidation configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT crypto_type, threshold_amount, admin_address, is_enabled
            FROM crypto_consolidation_settings
        """)
        rows = cursor.fetchall()
    
    settings = [
        {
            'crypto_type': row[0],
            'threshold': float(row[1]),
            'admin_address': row[2],
            'enabled': bool(row[3])
        }
        for row in rows
    ]
    
    return JSONResponse({'consolidation_settings': settings})


@app.put("/api/admin/payment-system/config/consolidation")
async def update_payment_consolidation_config(request: Request):
    """Update wallet consolidation configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        logger.info(f"Received consolidation config update: {body}")
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            # Handle both old format (consolidation_settings array) and new format (btc/eth/usdt/usdc keys)
            if 'consolidation_settings' in body:
                # Old format
                for setting in body['consolidation_settings']:
                    cursor.execute(f"""
                        UPDATE crypto_consolidation_settings
                        SET threshold_amount = {placeholder},
                            admin_address = {placeholder},
                            is_enabled = {placeholder}
                        WHERE crypto_type = {placeholder}
                    """, (
                        setting['threshold'],
                        setting.get('admin_address', ''),
                        setting.get('enabled', True),
                        setting['crypto_type']
                    ))
                    logger.info(f"Updated {setting['crypto_type']} threshold to {setting['threshold']}")
            else:
                # New format - simple key-value pairs
                crypto_map = {
                    'btc': 'BTC',
                    'eth': 'ETH',
                    'usdt': 'USDT',
                    'usdc': 'USDC'
                }
                
                updated_count = 0
                for key, crypto_type in crypto_map.items():
                    if key in body:
                        threshold = float(body[key])
                        
                        # Use UPSERT to handle missing records
                        if db.db_type == 'sqlite':
                            cursor.execute(f"""
                                INSERT INTO crypto_consolidation_settings (crypto_type, threshold_amount, admin_address, is_enabled)
                                VALUES (?, ?, '', 0)
                                ON CONFLICT(crypto_type) DO UPDATE SET threshold_amount = ?
                            """, (crypto_type, threshold, threshold))
                        else:  # MySQL
                            cursor.execute(f"""
                                INSERT INTO crypto_consolidation_settings (crypto_type, threshold_amount, admin_address, is_enabled)
                                VALUES (%s, %s, '', 0)
                                ON DUPLICATE KEY UPDATE threshold_amount = %s
                            """, (crypto_type, threshold, threshold))
                        
                        rows_affected = cursor.rowcount
                        logger.info(f"Upserted {crypto_type} threshold to {threshold}, rows affected: {rows_affected}")
                        updated_count += rows_affected
                
                logger.info(f"Total rows affected: {updated_count}")
            
            conn.commit()
            logger.info("Consolidation settings committed to database")
        
        return JSONResponse({'success': True, 'message': 'Consolidation settings updated'})
    except Exception as e:
        logger.error(f"Error updating consolidation settings: {e}", exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@app.post("/api/admin/config/consolidation")
async def update_consolidation_config(request: Request):
    """Update wallet consolidation configuration (legacy endpoint)"""
    return await update_payment_consolidation_config(request)


@app.get("/api/admin/config/email")
async def get_email_config(request: Request):
    """Get email notification configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get SMTP config
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT smtp_host, smtp_port, smtp_username, from_email, from_name, use_tls
            FROM email_config
            LIMIT 1
        """)
        smtp_row = cursor.fetchone()
        
        # Get notification settings
        cursor.execute("""
            SELECT notification_type, is_enabled, subject_template
            FROM email_notification_settings
        """)
        notif_rows = cursor.fetchall()
    
    smtp_config = None
    if smtp_row:
        smtp_config = {
            'smtp_host': smtp_row[0],
            'smtp_port': smtp_row[1],
            'smtp_username': smtp_row[2],
            'from_email': smtp_row[3],
            'from_name': smtp_row[4],
            'use_tls': bool(smtp_row[5])
        }
    
    notifications = [
        {
            'type': row[0],
            'enabled': bool(row[1]),
            'subject': row[2]
        }
        for row in notif_rows
    ]
    
    return JSONResponse({
        'smtp_config': smtp_config,
        'notifications': notifications
    })


@app.put("/api/admin/payment-system/config/email")
async def update_payment_email_config(request: Request):
    """Update email notification configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            # Update SMTP config
            if 'smtp_config' in body:
                smtp = body['smtp_config']
                
                # Check if config exists
                cursor.execute("SELECT id FROM email_config LIMIT 1")
                exists = cursor.fetchone()
                
                if exists:
                    cursor.execute(f"""
                        UPDATE email_config
                        SET smtp_host = {placeholder},
                            smtp_port = {placeholder},
                            smtp_username = {placeholder},
                            smtp_password = {placeholder},
                            from_email = {placeholder},
                            from_name = {placeholder},
                            use_tls = {placeholder}
                    """, (
                        smtp['smtp_host'],
                        smtp['smtp_port'],
                        smtp.get('smtp_username'),
                        smtp.get('smtp_password'),
                        smtp['from_email'],
                        smtp.get('from_name'),
                        smtp.get('use_tls', True)
                    ))
                else:
                    cursor.execute(f"""
                        INSERT INTO email_config
                        (smtp_host, smtp_port, smtp_username, smtp_password, from_email, from_name, use_tls)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                    """, (
                        smtp['smtp_host'],
                        smtp['smtp_port'],
                        smtp.get('smtp_username'),
                        smtp.get('smtp_password'),
                        smtp['from_email'],
                        smtp.get('from_name'),
                        smtp.get('use_tls', True)
                    ))
            
            # Update notification settings
            if 'notifications' in body:
                for notif in body['notifications']:
                    cursor.execute(f"""
                        UPDATE email_notification_settings
                        SET is_enabled = {placeholder},
                            subject_template = {placeholder}
                        WHERE notification_type = {placeholder}
                    """, (
                        notif['enabled'],
                        notif['subject'],
                        notif['type']
                    ))
            
            conn.commit()
        
        return JSONResponse({'success': True, 'message': 'Email configuration updated'})
    except Exception as e:
        logger.error(f"Error updating email configuration: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post("/api/admin/config/email")
async def update_email_config(request: Request):
    """Update email notification configuration (legacy endpoint)"""
    return await update_payment_email_config(request)


@app.put("/api/admin/payment-system/config/blockchain")
async def update_payment_blockchain_config(request: Request):
    """Update blockchain monitoring configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            for config in body.get('blockchain_config', []):
                cursor.execute(f"""
                    UPDATE blockchain_monitoring_config
                    SET rpc_url = {placeholder},
                        confirmations_required = {placeholder},
                        scan_interval_seconds = {placeholder},
                        is_enabled = {placeholder}
                    WHERE crypto_type = {placeholder}
                """, (
                    config['rpc_url'],
                    config['confirmations'],
                    config['scan_interval'],
                    config['enabled'],
                    config['crypto_type']
                ))
            
            conn.commit()
        
        return JSONResponse({'success': True, 'message': 'Blockchain monitoring configuration updated'})
    except Exception as e:
        logger.error(f"Error updating blockchain monitoring configuration: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@app.get("/api/admin/scheduler/status")
async def get_scheduler_status(request: Request):
    """Get payment scheduler status"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    if not payment_service:
        return JSONResponse({'error': 'Payment service not initialized'}, status_code=503)
    
    try:
        from aisbf.payments.scheduler import PaymentScheduler
        # Get scheduler from payment service if available
        if hasattr(payment_service, 'scheduler'):
            status = payment_service.scheduler.get_job_status()
            return JSONResponse(status)
        else:
            return JSONResponse({'error': 'Scheduler not available'}, status_code=503)
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@app.post("/api/admin/scheduler/run-job")
async def run_scheduler_job(request: Request):
    """Manually trigger a scheduler job"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    if not payment_service:
        return JSONResponse({'error': 'Payment service not initialized'}, status_code=503)
    
    try:
        body = await request.json()
        job_name = body.get('job_name')
        
        if not job_name:
            return JSONResponse({'error': 'job_name required'}, status_code=400)
        
        if hasattr(payment_service, 'scheduler'):
            await payment_service.scheduler.run_job_now(job_name)
            return JSONResponse({'success': True, 'message': f'Job {job_name} triggered'})
        else:
            return JSONResponse({'error': 'Scheduler not available'}, status_code=503)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Error running scheduler job: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@app.get("/api/admin/payment-system/status")
async def get_payment_system_status(request: Request):
    """Get payment system status including master keys, balances, and payment counts"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check master keys status
            cursor.execute("SELECT COUNT(*) FROM crypto_master_keys")
            master_keys_count = cursor.fetchone()[0]
            
            # Get total crypto balances from user_crypto_wallets
            try:
                cursor.execute("""
                    SELECT crypto_type, SUM(balance_fiat) as total
                    FROM user_crypto_wallets
                    GROUP BY crypto_type
                """)
                balances = {row[0]: float(row[1]) for row in cursor.fetchall()}
                total_balance_usd = sum(balances.values())
            except Exception:
                balances = {}
                total_balance_usd = 0.0
            
            # Get pending payments count from payment_transactions
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM payment_transactions
                    WHERE status = 'pending'
                """)
                pending_count = cursor.fetchone()[0]
            except Exception:
                pending_count = 0
            
            # Get failed payments count from payment_transactions
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM payment_transactions
                    WHERE status = 'failed'
                """)
                failed_count = cursor.fetchone()[0]
            except Exception:
                failed_count = 0
        
        return JSONResponse({
            'master_keys_initialized': master_keys_count > 0,
            'master_keys_count': master_keys_count,
            'total_balance_usd': total_balance_usd,
            'pending_payments': pending_count,
            'failed_payments': failed_count
        })
    except Exception as e:
        logger.error(f"Error getting payment system status: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@app.get("/api/admin/payment-system/config")
async def get_payment_system_config(request: Request):
    """Get all payment system configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get price sources
            try:
                cursor.execute("""
                    SELECT name, api_type, endpoint_url, api_key, is_enabled
                    FROM crypto_price_sources
                """)
                price_sources = {
                    row[0].lower(): bool(row[4])
                    for row in cursor.fetchall()
                }
            except Exception:
                price_sources = {
                    'coinbase': True,
                    'binance': True,
                    'kraken': True
                }
            
            # Get blockchain monitoring config (default values)
            blockchain_config = {
                'mode': 'api',
                'polling_interval': 60
            }
            
            # Get email notification config (default values)
            email_config = {
                'payment_success': True,
                'payment_failed': True,
                'subscription_upgraded': True,
                'subscription_downgraded': True,
                'subscription_cancelled': True,
                'payment_retry': True
            }
            
            # Get consolidation settings
            try:
                cursor.execute("""
                    SELECT crypto_type, threshold_amount
                    FROM crypto_consolidation_settings
                """)
                consolidation = {
                    row[0].lower(): float(row[1])
                    for row in cursor.fetchall()
                }
            except Exception:
                consolidation = {
                    'btc': 0.01,
                    'eth': 0.1,
                    'usdt': 100,
                    'usdc': 100
                }
        
        return JSONResponse({
            'price_sources': price_sources,
            'blockchain': blockchain_config,
            'email_notifications': email_config,
            'consolidation': consolidation
        })
    except Exception as e:
        logger.error(f"Error getting payment system config: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)



@app.get("/dashboard/admin/payment-settings")
async def dashboard_admin_payment_settings(request: Request):
    """Admin payment system settings page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/admin_payment_settings.html",
        context={
            "request": request,
            "session": request.session,
            "currency_symbol": DatabaseRegistry.get_config_database().get_currency_settings().get('currency_symbol', '$')
        }
    )

@app.get("/dashboard/pricing")
async def dashboard_pricing(request: Request):
    """Pricing plans page for users"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    tiers = db.get_visible_tiers()
    current_tier = db.get_user_tier(user_id)

    # Mark the most expensive non-free tier as recommended if none marked
    paid_tiers = [t for t in tiers if not t.get('is_default')]
    if paid_tiers:
        most_expensive = max(paid_tiers, key=lambda t: t['price_monthly'])
        for t in tiers:
            t['is_recommended'] = (not t.get('is_default') and t['id'] == most_expensive['id'])

    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)

    # Get currency settings
    currency_settings = db.get_currency_settings()
    currency_symbol = currency_settings.get('currency_symbol', '$')

    # Get wallet balance for display
    wallet_balance = None
    has_stripe_card = False
    if user_id:
        try:
            from aisbf.payments.wallet.manager import WalletManager
            wallet_manager = WalletManager(db)
            wallet = await wallet_manager.get_wallet(user_id)
            wallet_balance = float(wallet.get('balance', 0))
        except Exception:
            wallet_balance = 0.0
        payment_methods = db.get_user_payment_methods(user_id)
        has_stripe_card = any(m.get('type') == 'stripe' and m.get('is_active') for m in payment_methods)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/pricing.html",
        context={
            "request": request,
            "session": request.session,
            "tiers": tiers,
            "current_tier": current_tier,
            "enabled_gateways": enabled_gateways,
            "currency_symbol": currency_symbol,
            "wallet_balance": wallet_balance,
            "has_stripe_card": has_stripe_card,
        }
    )


@app.post("/dashboard/subscribe/free")
async def dashboard_subscribe_free(request: Request):
    """Downgrade to the free tier"""
    from fastapi.responses import JSONResponse

    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    free_tiers = [t for t in db.get_visible_tiers() if t.get('is_default')]
    if not free_tiers:
        return JSONResponse({"error": "No free tier configured"}, status_code=404)
    free_tier = free_tiers[0]

    ph = db.placeholder
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE user_subscriptions SET status = 'cancelled' WHERE user_id = {ph} AND status = 'active'",
            (user_id,)
        )
        conn.commit()
    db.set_user_tier(user_id, free_tier['id'])
    return JSONResponse({"success": True, "message": "Downgraded to free plan. Changes are effective immediately."})


def _create_subscription_record(db, user_id: int, tier_id: int):
    """Cancel existing active subscriptions and create a new one for the given tier."""
    from datetime import datetime, timedelta
    ph = db.placeholder
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE user_subscriptions SET status = 'cancelled' WHERE user_id = {ph} AND status = 'active'",
            (user_id,)
        )
        start_date = datetime.now()
        end_date = start_date + timedelta(days=30)
        cursor.execute(f"""
            INSERT INTO user_subscriptions (user_id, tier_id, status, start_date, next_billing_date)
            VALUES ({ph}, {ph}, 'active', {ph}, {ph})
        """, (user_id, tier_id, start_date, end_date))
        conn.commit()

@app.post("/dashboard/subscribe/{tier_id}")
async def dashboard_subscribe_tier(request: Request, tier_id: int):
    """Subscribe/upgrade to a paid tier using wallet or saved Stripe card"""
    from fastapi.responses import JSONResponse
    from decimal import Decimal

    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    target_tier = db.get_tier_by_id(tier_id)
    if not target_tier or not target_tier.get('is_active'):
        return JSONResponse({"error": "Invalid or inactive plan"}, status_code=404)

    current_tier = db.get_user_tier(user_id)
    if current_tier and current_tier['id'] == tier_id:
        return JSONResponse({"error": "You are already on this plan"}, status_code=400)

    tier_price = float(target_tier['price_monthly'])

    # Get wallet balance
    from aisbf.payments.wallet.manager import WalletManager
    wallet_manager = WalletManager(db)
    try:
        wallet = await wallet_manager.get_wallet(user_id)
        wallet_balance = float(wallet.get('balance', 0))
    except Exception:
        wallet_balance = 0.0

    if wallet_balance >= tier_price:
        # Pay with wallet
        try:
            await wallet_manager.debit_wallet(user_id, Decimal(str(tier_price)), {
                "description": f"Plan upgrade to {target_tier['name']}",
                "payment_gateway": "wallet",
                "gateway_transaction_id": None,
                "payment_method_id": None,
            })
        except Exception as e:
            return JSONResponse({"error": f"Failed to debit wallet: {str(e)}"}, status_code=400)
        _create_subscription_record(db, user_id, tier_id)
        db.set_user_tier(user_id, tier_id)
        return JSONResponse({
            "success": True,
            "message": f"Upgraded to {target_tier['name']}. ${tier_price:.2f} deducted from your wallet."
        })

    # Wallet insufficient — check Stripe
    payment_methods = db.get_user_payment_methods(user_id)
    stripe_methods = [m for m in payment_methods if m.get('type') == 'stripe' and m.get('is_active')]

    if not stripe_methods:
        shortage = tier_price - wallet_balance
        return JSONResponse({
            "error": "insufficient_funds",
            "wallet_balance": wallet_balance,
            "required": tier_price,
            "shortage": round(shortage, 2),
            "message": (
                f"Your wallet balance (${wallet_balance:.2f}) is insufficient. "
                f"You need ${shortage:.2f} more. Top up your wallet or add a card."
            ),
        }, status_code=402)

    # Charge the default (or first) Stripe card for the exact plan amount
    default_method = next((m for m in stripe_methods if m.get('is_default')), stripe_methods[0])
    if payment_service is None:
        return JSONResponse({"error": "Payment service unavailable"}, status_code=503)

    result = await payment_service.stripe_handler.auto_charge(
        user_id,
        Decimal(str(tier_price)),
        default_method['identifier']
    )
    if not result.get('success'):
        return JSONResponse({"error": result.get('error', 'Card charge failed')}, status_code=402)

    _create_subscription_record(db, user_id, tier_id)
    db.set_user_tier(user_id, tier_id)
    return JSONResponse({
        "success": True,
        "message": f"Upgraded to {target_tier['name']}. ${tier_price:.2f} charged to your saved card."
    })


@app.get("/dashboard/usage", response_class=HTMLResponse)
async def dashboard_usage(request: Request):
    """Usage and quota page for users"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    from datetime import datetime, timedelta
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    current_tier = db.get_user_tier(user_id) if user_id else None
    all_tiers = db.get_visible_tiers()

    # Quota limits from tier
    max_requests_per_day = current_tier.get('max_requests_per_day', -1) if current_tier else -1
    max_requests_per_month = current_tier.get('max_requests_per_month', -1) if current_tier else -1
    max_providers = current_tier.get('max_providers', -1) if current_tier else -1
    max_rotations = current_tier.get('max_rotations', -1) if current_tier else -1
    max_autoselections = current_tier.get('max_autoselections', -1) if current_tier else -1

    # Actual usage
    requests_today = 0
    requests_month = 0
    tokens_24h = 0
    providers_count = 0
    rotations_count = 0
    autoselects_count = 0

    if user_id:
        token_usage = db.get_user_token_usage(user_id)
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_ago = now - timedelta(days=1)

        for row in token_usage:
            ts = row['timestamp']
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    continue
            if ts >= today_start:
                requests_today += 1
            if ts >= month_start:
                requests_month += 1
            if ts >= day_ago:
                tokens_24h += int(row.get('token_count', 0) or 0)

        providers_count = len(db.get_user_providers(user_id))
        rotations_count = len(db.get_user_rotations(user_id))
        autoselects_count = len(db.get_user_autoselects(user_id))

    upgrade_tiers = [
        t for t in all_tiers
        if not t.get('is_default') and (
            current_tier is None or t['price_monthly'] > current_tier.get('price_monthly', 0)
        )
    ]

    currency_settings = db.get_currency_settings()
    currency_symbol = currency_settings.get('currency_symbol', '$')

    return templates.TemplateResponse(
        request=request,
        name="dashboard/usage.html",
        context={
            "request": request,
            "session": request.session,
            "current_tier": current_tier,
            "max_requests_per_day": max_requests_per_day,
            "max_requests_per_month": max_requests_per_month,
            "max_providers": max_providers,
            "max_rotations": max_rotations,
            "max_autoselections": max_autoselections,
            "requests_today": requests_today,
            "requests_month": requests_month,
            "tokens_24h": tokens_24h,
            "providers_count": providers_count,
            "rotations_count": rotations_count,
            "autoselects_count": autoselects_count,
            "upgrade_tiers": upgrade_tiers,
            "currency_symbol": currency_symbol,
        }
    )


@app.get("/dashboard/subscription")
async def dashboard_subscription(request: Request):
    """User subscription status and payment methods management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    # Get user subscription info
    subscription = db.get_user_subscription(user_id)
    current_tier = db.get_user_tier(user_id)
    payment_methods = db.get_user_payment_methods(user_id)
    
    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)
    
    # Get currency settings
    currency_settings = db.get_currency_settings()
    currency_symbol = currency_settings.get('currency_symbol', '$')
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/subscription.html",
        context={
        "request": request,
        "session": request.session,
        "subscription": subscription,
        "current_tier": current_tier,
        "payment_methods": payment_methods,
        "enabled_gateways": enabled_gateways,
        "currency_symbol": currency_symbol
    }
    )

@app.get("/dashboard/wallet", response_class=HTMLResponse)
async def dashboard_wallet(request: Request):
    """User wallet dashboard page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        db = DatabaseRegistry.get_config_database()
        user_id = request.session.get('user_id')

        from aisbf.payments.wallet.manager import WalletManager
        wallet_manager = WalletManager(db)
        wallet = await wallet_manager.get_wallet(user_id)

        all_gateways = db.get_payment_gateway_settings()
        enabled_gateways = {k: v for k, v in all_gateways.items() if v.get('enabled', False)}

        # Get user's saved Stripe credit cards for auto top-up
        stripe_cards = [m for m in db.get_user_payment_methods(user_id)
                        if m.get('type') == 'stripe' or m.get('gateway') == 'stripe']

        # Determine if there are upgrade plans available
        current_tier = db.get_user_tier(user_id)
        all_tiers = db.get_visible_tiers()
        upgrade_tiers = [
            t for t in all_tiers
            if not t.get('is_default') and (
                current_tier is None or t['price_monthly'] > current_tier.get('price_monthly', 0)
            )
        ]

        return templates.TemplateResponse(
            request=request,
            name="dashboard/wallet.html",
            context={
                "request": request,
                "wallet": wallet,
                "enabled_gateways": enabled_gateways,
                "currency_symbol": db.get_currency_settings().get('currency_symbol', '$'),
                "stripe_cards": stripe_cards,
                "upgrade_tiers": upgrade_tiers,
            }
        )
    except ImportError:
        return HTMLResponse("Wallet functionality not available", status_code=503)
    except Exception as e:
        logger.error(f"Failed to load wallet page: {e}")
        return templates.TemplateResponse("dashboard/error.html", {
            "request": request,
            "error": "Failed to load wallet. Please try again later."
        }, status_code=500)

@app.post("/dashboard/wallet/topup")
async def dashboard_wallet_topup(request: Request):
    """Session-authenticated wallet top-up — supports all admin-enabled gateways."""
    from fastapi.responses import JSONResponse
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    method = (body.get('payment_method') or '').lower()
    amount = body.get('amount')

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid amount"}, status_code=400)

    if amount < 5 or amount > 500:
        return JSONResponse({"error": "Amount must be between $5 and $500"}, status_code=400)

    db = DatabaseRegistry.get_config_database()
    gateways = db.get_payment_gateway_settings()
    gw = gateways.get(method, {})
    if not gw.get('enabled', False):
        return JSONResponse({"error": f"Payment method '{method}' is not enabled"}, status_code=400)

    # Crypto: generate per-user HD wallet address
    crypto_methods = {'bitcoin': 'btc', 'ethereum': 'eth', 'usdt': 'usdt', 'usdc': 'usdc'}
    if method in crypto_methods:
        crypto_type = crypto_methods[method]
        ps = getattr(request.app.state, 'payment_service', None)
        if ps is None:
            return JSONResponse({"error": "Payment service unavailable"}, status_code=503)
        try:
            address = await ps.wallet_manager.get_or_create_user_address(user_id, crypto_type)
        except Exception as e:
            import traceback as _tb
            logger.error(f"Crypto address generation error: {e!r}\n{_tb.format_exc()}")
            return JSONResponse({"error": "Could not generate deposit address"}, status_code=503)
        return JSONResponse({
            "type": "crypto",
            "method": method,
            "address": address,
            "amount": amount,
            "network": gw.get('network', ''),
            "confirmations": gw.get('confirmations', 3),
        })

    # Stripe: create checkout session (hosted redirect flow)
    if method == 'stripe':
        try:
            payment_service = getattr(request.app.state, 'payment_service', None)
            if not payment_service or not hasattr(payment_service, 'stripe_handler'):
                return JSONResponse({"error": "Stripe payment service unavailable"}, status_code=503)
            from decimal import Decimal
            base = str(request.base_url).rstrip('/')
            result = await payment_service.stripe_handler.create_topup_checkout_session(
                user_id,
                Decimal(str(amount)),
                success_url=f"{base}/dashboard/wallet?topup=success",
                cancel_url=f"{base}/dashboard/wallet?topup=cancelled",
            )
            if not result.get('success'):
                return JSONResponse({"error": result.get('error', 'Stripe error')}, status_code=502)
            return JSONResponse({"type": "stripe", "checkout_url": result['checkout_url']})
        except Exception as e:
            logger.error(f"Stripe top-up error: {e}")
            return JSONResponse({"error": "Stripe checkout failed. Please try again."}, status_code=502)

    # PayPal: create order
    if method == 'paypal':
        try:
            payment_service = getattr(request.app.state, 'payment_service', None)
            if not payment_service or not hasattr(payment_service, 'paypal_handler'):
                return JSONResponse({"error": "PayPal payment service unavailable"}, status_code=503)
            from decimal import Decimal
            result = await payment_service.paypal_handler.create_topup_order(user_id, Decimal(str(amount)))
            if not result.get('success'):
                logger.error(f"PayPal top-up error: {result.get('error')}")
                return JSONResponse({"error": "PayPal checkout failed. Please try again."}, status_code=502)
            return JSONResponse({"type": "paypal", "approval_url": result['approval_url']})
        except Exception as e:
            logger.error(f"PayPal top-up error: {e}")
            return JSONResponse({"error": "PayPal checkout failed. Please try again."}, status_code=502)

    return JSONResponse({"error": f"Unsupported payment method: {method}"}, status_code=400)


@app.get("/dashboard/wallet/transactions")
async def dashboard_wallet_transactions(request: Request, limit: int = 50, offset: int = 0):
    """Session-authenticated wallet transaction history (used by the wallet dashboard page)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    try:
        from aisbf.payments.wallet.manager import WalletManager
        db = DatabaseRegistry.get_config_database()
        wallet_manager = WalletManager(db)
        transactions = await wallet_manager.get_transactions(user_id, limit=limit, offset=offset)
        return transactions
    except Exception as e:
        logger.error(f"Failed to load wallet transactions: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Failed to load transactions"}, status_code=500)


@app.put("/dashboard/wallet/auto-topup")
async def dashboard_wallet_auto_topup(request: Request):
    """Session-authenticated auto-topup configuration (used by the wallet dashboard page)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    try:
        body = await request.json()
        from aisbf.payments.wallet.manager import WalletManager
        db = DatabaseRegistry.get_config_database()
        wallet_manager = WalletManager(db)
        result = await wallet_manager.configure_auto_topup(user_id, body)
        from fastapi.responses import JSONResponse
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Failed to configure auto-topup: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Failed to save settings"}, status_code=500)


@app.get("/dashboard/billing")
async def dashboard_billing(request: Request):
    """User payment transaction history page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    # Get user payment methods
    payment_methods = db.get_user_payment_methods(user_id)

    # Get payment transactions
    transactions = db.get_user_payment_transactions(user_id)

    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)

    # Get user wallet
    currency_settings = db.get_currency_settings()
    currency_code = currency_settings.get('currency_code', 'EUR')
    try:
        from aisbf.payments.wallet.manager import WalletManager
        wallet_manager = WalletManager(db)
        wallet = await wallet_manager.get_wallet(user_id)
    except Exception:
        wallet = {'balance': '0.00', 'currency_code': currency_code, 'auto_topup_enabled': False}

    # Get Stripe publishable key
    stripe_publishable_key = ""
    if 'stripe' in gateways and gateways['stripe'].get('enabled'):
        stripe_publishable_key = gateways['stripe'].get('publishable_key', '')

    return templates.TemplateResponse(
        request=request,
        name="dashboard/billing.html",
        context={
        "request": request,
        "session": request.session,
        "payment_methods": payment_methods,
        "transactions": transactions,
        "enabled_gateways": enabled_gateways,
        "wallet": wallet,
        "currency_symbol": currency_settings.get('currency_symbol', '$'),
        "stripe_publishable_key": stripe_publishable_key,
    }
    )

@app.get("/dashboard/billing/add-method")
async def dashboard_add_payment_method(request: Request):
    """Add payment method page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)
    
    # Get Stripe publishable key
    stripe_publishable_key = ""
    if 'stripe' in gateways and gateways['stripe'].get('enabled'):
        stripe_publishable_key = gateways['stripe'].get('publishable_key', '')
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/add_payment_method.html",
        context={
            "request": request,
            "session": request.session,
            "enabled_gateways": enabled_gateways,
            "stripe_publishable_key": stripe_publishable_key
        }
    )

@app.post("/dashboard/billing/add-method")
async def dashboard_add_payment_method_post(request: Request):
    """Handle crypto default setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    data = await request.json()
    user_id = request.session.get('user_id')
    payment_type = data.get('type')
    
    if payment_type in ['bitcoin', 'eth', 'usdt', 'usdc']:
        db = DatabaseRegistry.get_config_database()
        
        # Set as default payment method
        db.set_user_default_payment_method(user_id, payment_type)
        
        return JSONResponse({"success": True, "message": f"{payment_type.upper()} set as default payment method"})
    
    return JSONResponse({"success": False, "error": "Invalid payment type"}, status_code=400)

@app.post("/dashboard/billing/add-method/stripe")
async def dashboard_add_payment_method_stripe(request: Request):
    """Handle Stripe payment method addition"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    data = await request.json()
    user_id = request.session.get('user_id')
    payment_method_id = data.get('payment_method_id')
    
    if not payment_method_id:
        return JSONResponse({"success": False, "error": "Payment method ID required"}, status_code=400)
    
    db = DatabaseRegistry.get_config_database()
    
    # Store payment method in database
    try:
        method_id = db.add_payment_method(user_id, 'stripe', payment_method_id, is_default=True, metadata={'stripe_payment_method_id': payment_method_id})
        return JSONResponse({"success": True, "message": "Credit card added successfully"})
    except Exception as e:
        logger.error(f"Error adding Stripe payment method: {e}")
        return JSONResponse({"success": False, "error": "Failed to add payment method"}, status_code=500)

@app.delete("/dashboard/billing/payment-methods/{method_id}")
async def dashboard_delete_payment_method(request: Request, method_id: int):
    """Delete a payment method"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    try:
        # Delete the payment method
        success = db.delete_payment_method(user_id, method_id)
        
        if success:
            logger.info(f"Payment method {method_id} deleted for user {user_id}")
            return JSONResponse({"success": True, "message": "Payment method deleted successfully"})
        else:
            return JSONResponse({"success": False, "error": "Payment method not found or already deleted"}, status_code=404)
    except Exception as e:
        logger.error(f"Error deleting payment method: {e}")
        return JSONResponse({"success": False, "error": "Failed to delete payment method"}, status_code=500)

@app.post("/dashboard/billing/payment-methods/{method_id}/set-default")
async def dashboard_set_default_payment_method(request: Request, method_id: int):
    """Set a payment method as default"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    try:
        # Get the payment method to verify it belongs to the user
        payment_methods = db.get_user_payment_methods(user_id)
        method_exists = any(m['id'] == method_id for m in payment_methods)
        
        if not method_exists:
            return JSONResponse({"success": False, "error": "Payment method not found"}, status_code=404)
        
        # Set as default by updating all methods for this user
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            # Unset all defaults for this user
            cursor.execute(f'''
                UPDATE payment_methods SET is_default = 0
                WHERE user_id = {placeholder}
            ''', (user_id,))
            
            # Set the selected method as default
            cursor.execute(f'''
                UPDATE payment_methods SET is_default = 1
                WHERE id = {placeholder} AND user_id = {placeholder}
            ''', (method_id, user_id))
            
            conn.commit()
        
        logger.info(f"Payment method {method_id} set as default for user {user_id}")
        return JSONResponse({"success": True, "message": "Payment method set as default"})
    except Exception as e:
        logger.error(f"Error setting default payment method: {e}")
        return JSONResponse({"success": False, "error": "Failed to set default payment method"}, status_code=500)

@app.get("/dashboard/billing/add-method/paypal/oauth")
async def dashboard_add_payment_method_paypal_oauth(request: Request):
    """Initiate PayPal Vault setup flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    # Get PayPal settings
    gateways = db.get_payment_gateway_settings()
    paypal_settings = gateways.get('paypal', {})
    
    # Validate PayPal is enabled
    if not paypal_settings.get('enabled'):
        logger.warning(f"PayPal OAuth attempted but PayPal is not enabled (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not enabled",
            status_code=302
        )
    
    # Check if user already has PayPal as payment method
    existing_methods = db.get_user_payment_methods(user_id)
    for method in existing_methods:
        if method.get('type') == 'paypal':
            logger.info(f"User {user_id} already has PayPal payment method")
            return RedirectResponse(
                url="/dashboard/billing?error=PayPal is already added as a payment method",
                status_code=302
            )
    
    # Construct callback URLs
    base_url = str(request.base_url).rstrip('/')
    return_url = f"{base_url}/dashboard/billing/add-method/paypal/callback"
    cancel_url = f"{base_url}/dashboard/billing?error=PayPal connection cancelled"
    
    # Create vault setup token using payment service
    result = await payment_service.initiate_paypal_vault_setup(user_id, return_url, cancel_url)
    
    if not result['success']:
        logger.error(f"Failed to create PayPal vault setup: {result.get('error')}")
        return RedirectResponse(
            url="/dashboard/billing?error=Failed to initialize PayPal connection",
            status_code=302
        )
    
    logger.info(f"Initiating PayPal vault setup for user {user_id}")
    
    return RedirectResponse(url=result['approval_url'], status_code=302)

@app.get("/dashboard/billing/add-method/paypal/callback")
async def dashboard_add_payment_method_paypal_callback(request: Request):
    """Handle PayPal vault setup callback"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    user_id = request.session.get('user_id')
    
    # Get query parameters
    token = request.query_params.get('token')
    error = request.query_params.get('error')
    
    # Handle user cancellation
    if error:
        logger.info(f"PayPal vault setup cancelled by user {user_id}: {error}")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal connection cancelled",
            status_code=302
        )
    
    # Validate setup token
    if not token:
        logger.error(f"PayPal callback missing setup token (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid PayPal response",
            status_code=302
        )
    
    try:
        # Complete vault setup using payment service
        result = await payment_service.complete_paypal_vault_setup(user_id, token)
        
        if not result['success']:
            logger.error(f"Failed to complete PayPal vault setup: {result.get('error')}")
            return RedirectResponse(
                url="/dashboard/billing?error=Failed to connect PayPal account",
                status_code=302
            )
        
        logger.info(f"PayPal payment method added for user {user_id} (payment_token={result['payment_token_id']})")
        
        return RedirectResponse(
            url="/dashboard/billing?success=PayPal account connected successfully",
            status_code=302
        )
            
    except Exception as e:
        logger.error(f"PayPal callback error (user_id={user_id}): {str(e)}")
        return RedirectResponse(
            url="/dashboard/billing?error=Failed to connect PayPal account",
            status_code=302
        )
            
    except Exception as e:
        logger.error(f"PayPal callback error (user_id={user_id}): {str(e)}")
        return RedirectResponse(
            url="/dashboard/billing?error=Failed to connect PayPal account",
            status_code=302
        )
    
    # Validate state token (CSRF protection)
    session_state = request.session.get('paypal_oauth_state')
    if not session_state:
        logger.warning(f"PayPal OAuth callback with no session state (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Session expired, please try again",
            status_code=302
        )
    
    if state != session_state:
        logger.warning(f"PayPal OAuth state mismatch (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid request (security check failed)",
            status_code=302
        )
    
    # Clear state token from session
    request.session.pop('paypal_oauth_state', None)
    
    # Validate authorization code
    if not code:
        logger.error(f"PayPal OAuth callback missing authorization code (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid PayPal response",
            status_code=302
        )
    
    # Get PayPal settings
    gateways = db.get_payment_gateway_settings()
    paypal_settings = gateways.get('paypal', {})
    
    client_id = paypal_settings.get('client_id', '').strip()
    client_secret = paypal_settings.get('client_secret', '').strip()
    is_sandbox = paypal_settings.get('sandbox', True)
    
    if not client_id or not client_secret:
        logger.error(f"PayPal OAuth callback but credentials not configured (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not properly configured",
            status_code=302
        )
    
    # Determine PayPal API URLs
    if is_sandbox:
        token_url = "https://api.sandbox.paypal.com/v1/oauth2/token"
        userinfo_url = "https://api.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=openid"
    else:
        token_url = "https://api.paypal.com/v1/oauth2/token"
        userinfo_url = "https://api.paypal.com/v1/identity/oauth2/userinfo?schema=openid"
    
    # Construct callback URL (must match what was sent to PayPal)
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/dashboard/billing/add-method/paypal/callback"
    
    try:
        # Exchange authorization code for access token
        import base64
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
        
        async with httpx.AsyncClient() as client:
            # Token exchange request
            token_response = await client.post(
                token_url,
                headers={
                    'Authorization': f'Basic {auth_b64}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri
                },
                timeout=30.0
            )
            
            if token_response.status_code != 200:
                logger.error(f"PayPal token exchange failed (user_id={user_id}): {token_response.status_code} {token_response.text}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to connect PayPal account",
                    status_code=302
                )
            
            token_data = token_response.json()
            access_token = token_data.get('access_token')
            
            if not access_token:
                logger.error(f"PayPal token response missing access_token (user_id={user_id})")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to connect PayPal account",
                    status_code=302
                )
            
            logger.info(f"PayPal access token obtained for user {user_id}")
            
            # Fetch user profile
            userinfo_response = await client.get(
                userinfo_url,
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                timeout=30.0
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"PayPal userinfo fetch failed (user_id={user_id}): {userinfo_response.status_code}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to retrieve PayPal account information",
                    status_code=302
                )
            
            userinfo = userinfo_response.json()
            paypal_user_id = userinfo.get('user_id')
            paypal_email = userinfo.get('email')
            paypal_name = userinfo.get('name', '')
            
            if not paypal_user_id or not paypal_email:
                logger.error(f"PayPal userinfo missing required fields (user_id={user_id})")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to retrieve PayPal account information",
                    status_code=302
                )
            
            logger.info(f"PayPal user profile retrieved for user {user_id}: {paypal_email}")
            
            # Check for duplicate PayPal account
            existing_methods = db.get_user_payment_methods(user_id)
            for method in existing_methods:
                if method.get('type') == 'paypal':
                    metadata = method.get('metadata', {})
                    if isinstance(metadata, str):
                        import json
                        metadata = json.loads(metadata)
                    
                    existing_email = metadata.get('paypal_email')
                    existing_user_id = metadata.get('paypal_user_id')
                    
                    if existing_email == paypal_email or existing_user_id == paypal_user_id:
                        logger.info(f"Duplicate PayPal account detected for user {user_id}")
                        return RedirectResponse(
                            url="/dashboard/billing?error=This PayPal account is already connected",
                            status_code=302
                        )
            
            # Store payment method
            is_default = len(existing_methods) == 0
            metadata = {
                'paypal_user_id': paypal_user_id,
                'paypal_email': paypal_email,
                'paypal_name': paypal_name,
                'access_token': access_token,
                'sandbox': is_sandbox
            }
            
            method_id = db.add_payment_method(
                user_id=user_id,
                method_type='paypal',
                identifier=paypal_email,
                is_default=is_default,
                metadata=metadata
            )
            
            if method_id:
                logger.info(f"PayPal payment method added for user {user_id} (method_id={method_id})")
                return RedirectResponse(
                    url="/dashboard/billing?success=PayPal account connected successfully",
                    status_code=302
                )
            else:
                logger.error(f"Failed to store PayPal payment method for user {user_id}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to save payment method",
                    status_code=302
                )
    
    except httpx.TimeoutException as e:
        logger.error(f"PayPal OAuth timeout (user_id={user_id}): {e}")
        return RedirectResponse(
            url="/dashboard/billing?error=Connection timeout, please try again",
            status_code=302
        )
    except httpx.HTTPError as e:
        logger.error(f"PayPal OAuth HTTP error (user_id={user_id}): {e}")
        return RedirectResponse(
            url="/dashboard/billing?error=Connection error, please try again",
            status_code=302
        )
    except Exception as e:
        logger.error(f"PayPal OAuth unexpected error (user_id={user_id}): {e}", exc_info=True)
        return RedirectResponse(
            url="/dashboard/billing?error=An error occurred while connecting PayPal",
            status_code=302
        )

@app.get("/dashboard/response-cache")
async def dashboard_response_cache(request: Request):
    """Response cache dashboard page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    from aisbf.cache import get_response_cache
    
    try:
        cache = get_response_cache()
        
        if is_admin:
            # Admin sees global stats
            stats = cache.get_stats()
        else:
            # Regular users see their own personal cache impact
            stats = cache.get_user_stats(current_user_id)
            
    except Exception as e:
        logger.error(f"Error getting response cache stats: {e}")
        stats = {
            'enabled': False,
            'hits': 0,
            'misses': 0,
            'hit_rate': 0.0,
            'size': 0,
            'evictions': 0,
            'backend': 'unknown',
            'error': str(e)
        }
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/response_cache.html",
        context={
        "request": request,
        "session": request.session,
        "stats": stats,
        "is_admin": is_admin
    }
    )

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
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    try:
        if is_admin:
            # Admin sees all limiters
            limiters = get_all_adaptive_rate_limiters()
        else:
            # Regular user sees ONLY their own configured providers
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            user_provider_ids = [p['provider_id'] for p in user_providers]
            
            # Get all limiters for this user
            all_limiters = get_all_adaptive_rate_limiters(current_user_id)
            
            # Filter to only show providers the user has actually configured
            limiters = {}
            for provider_id, limiter in all_limiters.items():
                if provider_id in user_provider_ids:
                    limiters[provider_id] = limiter
            
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
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    from aisbf.providers import get_all_adaptive_rate_limiters, get_adaptive_rate_limiter
    
    try:
        if is_admin:
            # Admin can reset any limiter
            limiters = get_all_adaptive_rate_limiters()
            if provider_id in limiters:
                limiters[provider_id].reset()
                return JSONResponse({'success': True, 'message': f'Rate limiter for {provider_id} reset successfully'})
            else:
                return JSONResponse({'success': False, 'error': f'Provider {provider_id} not found'}, status_code=404)
        else:
            # Regular user can only reset limiters for providers THEY have configured
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            user_provider_ids = [p['provider_id'] for p in user_providers]
            
            if provider_id not in user_provider_ids:
                return JSONResponse({'success': False, 'error': f'You do not have permission to reset rate limiters for {provider_id}'}, status_code=403)
            
            # Reset their user-specific limiter
            user_limiter_key = f"user:{current_user_id}:{provider_id}"
            limiters = get_all_adaptive_rate_limiters()
            if user_limiter_key in limiters:
                limiters[user_limiter_key].reset()
                return JSONResponse({'success': True, 'message': f'Rate limiter for {provider_id} reset successfully'})
            else:
                return JSONResponse({'success': False, 'error': f'Rate limiter for {provider_id} not found'}, status_code=404)
    except Exception as e:
        logger.error(f"Error resetting rate limiter: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@app.post("/dashboard/response-cache/clear")
async def dashboard_response_cache_clear(request: Request):
    """Clear response cache"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    
    if not is_admin:
        return JSONResponse({'success': False, 'error': 'Clearing cache is only available to administrators'}, status_code=403)
    
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
                extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'toc']
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
            # Rewrite DOCUMENTATION.md links (relative or absolute) to /dashboard/docs
            html_content = re.sub(
                r'href="(?:https?://[^"]*?/)?DOCUMENTATION\.md#([^"]*)"',
                r'href="/dashboard/docs#\1"',
                html_content
            )
            html_content = re.sub(
                r'href="(?:https?://[^"]*?/)?DOCUMENTATION\.md"',
                'href="/dashboard/docs"',
                html_content
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
        token_id = getattr(request.state, 'token_id', None)
        handler = get_user_handler('autoselect', user_id)

        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)
    
    # PATH 2: Check if it's a rotation (format: rotation/{name} or rotations/{name})
    if provider_id == "rotation" or provider_id == "rotations":
        if actual_model not in config.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
            )
        body_dict['model'] = actual_model
        # Get user-specific handler
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = get_user_handler('rotation', user_id)
        return await handler.handle_rotation_request(actual_model, body_dict, user_id, token_id)
    
    # PATH 2a: Check if it's an autoselect (format: autoselect/{name} or autoselections/{name})
    if provider_id == "autoselect" or provider_id == "autoselections":
        if actual_model not in config.autoselect:
            raise HTTPException(
                status_code=400,
                detail=f"Autoselect '{actual_model}' not found. Available: {list(config.autoselect.keys())}"
            )
        body_dict['model'] = actual_model
        # Get user-specific handler
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = get_user_handler('autoselect', user_id)
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)
    
    # PATH 1: Direct provider model (format: {provider}/{model})
    if provider_id not in config.providers:
            raise HTTPException(
                status_code=404,
                detail=f"User autoselect '{actual_model}' not found. Available: {list(handler.user_autoselects.keys())}"
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
            db = DatabaseRegistry.get_config_database()
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
            db = DatabaseRegistry.get_config_database()
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
            status_code=404,
            detail=f"Rotation '{body.model}' not found. Available: {list(config.rotations.keys())}"
        )

    logger.info(f"Model '{body.model}' found in rotations")
    logger.debug("Handling rotation request")

    try:
        # Get user-specific handler
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = get_user_handler('rotation', user_id)

        # The rotation handler handles streaming internally and returns
        # a StreamingResponse for streaming requests or a dict for non-streaming
        result = await handler.handle_rotation_request(body.model, body_dict, user_id, token_id)
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
    token_id = getattr(request.state, 'token_id', None)
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
            result = await handler.handle_autoselect_request(body.model, body_dict, user_id, token_id)
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


@app.get("/api/autoselections/models")
async def list_autoselection_models():
    """List all models across all autoselect configurations (alias for /api/autoselect/models)"""
    return await list_autoselect_models()

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
        token_id = getattr(request.state, 'token_id', None)
        handler = get_user_handler('autoselect', user_id)
        try:
            if body.stream:
                logger.debug("Handling streaming autoselect request")
                return await handler.handle_autoselect_streaming_request(provider_id, body_dict)
            else:
                logger.debug("Handling non-streaming autoselect request")
                result = await handler.handle_autoselect_request(provider_id, body_dict, user_id, token_id)
                logger.debug(f"Autoselect response result: {result}")
                return result
        except Exception as e:
            logger.error(f"Error handling autoselect: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations or (user_id and provider_id in get_user_handler('rotation', user_id).rotations):
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation request")
        token_id = getattr(request.state, 'token_id', None)
        handler = get_user_handler('rotation', user_id)
        return await handler.handle_rotation_request(provider_id, body_dict, user_id, token_id)

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
    if provider_id in config.rotations or (user_id and provider_id in get_user_handler('rotation', user_id).rotations):
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


@app.get("/mcp/u/{username}/tools")
async def mcp_user_list_tools(request: Request, username: str):
    """
    List available MCP tools for the authenticated user.
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required"}
        )
    
    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
            )
    
    # User-specific MCP tools
    tools = mcp_server.get_available_tools(MCPAuthLevel.USER, user_id)
    return {"tools": tools}


@app.post("/mcp/u/{username}/tools/call")
async def mcp_user_call_tool(request: Request, username: str):
    """
    Call an MCP tool for the authenticated user via HTTP POST.
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required"}
        )
    
    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
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
        result = await mcp_server.handle_tool_call(tool_name, arguments, MCPAuthLevel.USER, user_id)
        return {"result": result}
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": e.detail}
        )
    except Exception as e:
        logger.error(f"Error calling MCP tool: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
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
    db = DatabaseRegistry.get_config_database()
    
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
        for rotation_id, rotation_config in rotation_handler.rotations.items():
            try:
                all_models.append({
                    'id': f"rotation/{rotation_id}",
                    'object': 'model',
                    'created': int(time.time()),
                    'owned_by': 'aisbf-rotation',
                    'type': 'rotation',
                    'rotation_id': rotation_id,
                    'source': 'user_config'
                })
            except Exception as e:
                logger.warning(f"Error listing user rotation {rotation_id}: {e}")
        
        autoselect_handler = get_user_handler('autoselect', target_user_id)
        for autoselect_id, autoselect_config in autoselect_handler.autoselects.items():
            try:
                all_models.append({
                    'id': f"autoselect/{autoselect_id}",
                    'object': 'model',
                    'created': int(time.time()),
                    'owned_by': 'aisbf-autoselect',
                    'type': 'autoselect',
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
    
    # Add user providers - fetch live models from each provider API
    from aisbf.providers import get_provider_handler
    for provider_id, provider_config in handler.user_providers.items():
        try:
            # Get provider handler for this user provider
            provider_handler = get_provider_handler(provider_id, user_id=target_user_id)
            
            # Fetch live models from provider
            provider_models = await provider_handler.get_models()
            
            # Add all models from this provider
            for model in provider_models:
                model_id = f"{provider_id}/{model.id}"
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
    for rotation_id, rotation_config in rotation_handler.rotations.items():
        try:
            all_models.append({
                'id': f"rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-rotation',
                'type': 'rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.get('model_name', rotation_id),
                'capabilities': rotation_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    # Add user autoselects
    autoselect_handler = get_user_handler('autoselect', target_user_id)
    for autoselect_id, autoselect_config in autoselect_handler.autoselects.items():
        try:
            all_models.append({
                'id': f"autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-autoselect',
                'type': 'autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.get('model_name', autoselect_id),
                'description': autoselect_config.get('description'),
                'capabilities': autoselect_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    return {"object": "list", "data": all_models}


@app.get("/api/u/{username}/models")
async def user_list_models(request: Request, username: str):
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
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/username/models
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)

    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
            )
    
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
            for rotation_id, rotation_config in rotation_handler.rotations.items():
                try:
                    all_models.append({
                        'id': f"rotation/{rotation_id}",
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': 'aisbf-rotation',
                        'type': 'rotation',
                        'rotation_id': rotation_id,
                        'source': 'user_config'
                    })
                except Exception as e:
                    logger.warning(f"Error listing user rotation {rotation_id}: {e}")
            
            autoselect_handler = get_user_handler('autoselect', user_id)
            for autoselect_id, autoselect_config in autoselect_handler.autoselects.items():
                try:
                    all_models.append({
                        'id': f"autoselect/{autoselect_id}",
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': 'aisbf-autoselect',
                        'type': 'autoselect',
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
    for rotation_id, rotation_config in rotation_handler.rotations.items():
        try:
            all_models.append({
                'id': f"rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-rotation',
                'type': 'rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.get('model_name', rotation_id),
                'capabilities': rotation_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    # Add user autoselects
    autoselect_handler = get_user_handler('autoselect', user_id)
    for autoselect_id, autoselect_config in autoselect_handler.autoselects.items():
        try:
            all_models.append({
                'id': f"autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-autoselect',
                'type': 'autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.get('model_name', autoselect_id),
                'description': autoselect_config.get('description'),
                'capabilities': autoselect_config.get('capabilities', []),
                'source': 'user_config'
            })
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    
    return {"object": "list", "data": all_models}


@app.get("/api/u/{username}/providers")
async def user_list_providers(request: Request, username: str):
    """
    List all provider configurations for the authenticated user.

    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.

    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/username/providers
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)

    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
            )
    
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


@app.get("/api/u/{username}/rotations")
async def user_list_rotations(request: Request, username: str):
    """
    List all rotation configurations for the authenticated user.

    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.

    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/username/rotations
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)

    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
            )
    
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
            for rotation_id, rotation_config in handler.rotations.items():
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
    for rotation_id, rotation_config in handler.rotations.items():
        try:
            rotations_info[rotation_id] = {
                "model_name": rotation_config.get('model_name', rotation_id),
                "providers": rotation_config.get('providers', [])
            }
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    
    return {"rotations": rotations_info}


@app.get("/api/u/{username}/autoselects")
async def user_list_autoselects(request: Request, username: str):
    """
    List all autoselect configurations for the authenticated user.

    Admin users and global tokens can access all configurations.
    Authentication is done via Bearer token in the Authorization header.

    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/username/autoselects
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)

    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
            )
    
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
            for autoselect_id, autoselect_config in handler.autoselects.items():
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
    for autoselect_id, autoselect_config in handler.autoselects.items():
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
    db = DatabaseRegistry.get_config_database()
    
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
    db = DatabaseRegistry.get_config_database()
    
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
            for rotation_id, rotation_config in handler.rotations.items():
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
    for rotation_id, rotation_config in handler.rotations.items():
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
    db = DatabaseRegistry.get_config_database()
    
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
            for autoselect_id, autoselect_config in handler.autoselects.items():
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
    for autoselect_id, autoselect_config in handler.autoselects.items():
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
    - 'rotation/name' - user's rotation
    - 'user-autoselect/name' - user's autoselect
    
    Example:
        curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
             -H "Content-Type: application/json" \
             -d '{"model": "rotation/myrotation", "messages": [{"role": "user", "content": "Hello"}]}' \
             http://localhost:17765/api/u/{username}/chat/completions
    """
    db = DatabaseRegistry.get_config_database()
    
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
             detail="Model must be in format 'provider/model', 'rotation/name', 'autoselect/name', 'rotations/name', 'autoselections/name', or 'user-provider/model'"
        )
    
    body_dict = body.model_dump()
    
    # Handle new formats: rotations/{rotation_name} and autoselections/{autoselection_name}
    if provider_id == "rotations" or provider_id == "rotation":
        # Normalize to user-rotation handler
        rotation_name = actual_model
        handler = get_user_handler('rotation', target_user_id)
        if rotation_name not in handler.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"User rotation '{rotation_name}' not found. Available: {list(handler.rotations.keys())}"
            )
        body_dict['model'] = rotation_name
        token_id = getattr(request.state, 'token_id', None)
        return await handler.handle_rotation_request(rotation_name, body_dict, authenticated_user_id, token_id)
    
    if provider_id == "autoselections" or provider_id == "autoselect":
        # Normalize to user-autoselect handler
        autoselect_name = actual_model
        handler = get_user_handler('autoselect', target_user_id)
        if autoselect_name not in handler.user_autoselects:
            raise HTTPException(
                status_code=400,
                detail=f"User autoselect '{autoselect_name}' not found. Available: {list(handler.user_autoselects.keys())}"
            )
        body_dict['model'] = autoselect_name

        if body.stream:
            return await handler.handle_autoselect_streaming_request(autoselect_name, body_dict)
        else:
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_autoselect_request(autoselect_name, body_dict, authenticated_user_id, token_id)
    
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
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_autoselect_request(actual_model, body_dict, authenticated_user_id, token_id)
    
    if provider_id == "user-rotation":
        handler = get_user_handler('rotation', target_user_id)
        if actual_model not in handler.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"User rotation '{actual_model}' not found. Available: {list(handler.rotations.keys())}"
            )
        body_dict['model'] = actual_model
        token_id = getattr(request.state, 'token_id', None)
        return await handler.handle_rotation_request(actual_model, body_dict, authenticated_user_id, token_id)
    
    if provider_id == "user-provider" or provider_id in (get_user_handler('request', target_user_id).user_providers.keys() if target_user_id else []):
        # Check if this is a user provider
        handler = get_user_handler('request', target_user_id)
        provider_name = actual_model if provider_id == "user-provider" else provider_id
        
        if provider_name not in handler.user_providers:
            raise HTTPException(
                status_code=404,
                detail=f"User provider '{provider_name}' not found. Available: {list(handler.user_providers.keys())}"
            )
        
        provider_config = handler.user_providers[provider_name]
        
        if not validate_kiro_credentials(provider_name, provider_config):
            raise HTTPException(
                status_code=403,
                detail=f"Provider '{provider_name}' credentials not available."
            )
        
        # Extract actual model name: if format is "provider/model", keep only "model" part
        if actual_model.startswith(f"{provider_name}/"):
            actual_model_name = actual_model[len(provider_name)+1:]
            body_dict['model'] = actual_model_name
        else:
            # Keep original model name if no slash
            body_dict['model'] = actual_model
        
        # If no model specified, return error
        if not body_dict.get('model'):
            raise HTTPException(
                status_code=400,
                detail="Model name is required in format 'provider/model' or 'model'"
            )
        
        if body.stream:
            return await handler.handle_streaming_chat_completion(request, provider_name, body_dict)
        else:
            return await handler.handle_chat_completion(request, provider_name, body_dict)
    
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
                token_id = getattr(request.state, 'token_id', None)
                return await handler.handle_autoselect_request(actual_model, body_dict, authenticated_user_id, token_id)

        if provider_id == "rotation":
            if actual_model not in config.rotations:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
                )
            handler = get_user_handler('rotation', None)
            body_dict['model'] = actual_model
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_rotation_request(actual_model, body_dict, authenticated_user_id, token_id)
        
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
         detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'. Global configurations are only available to admin users."
    )


@app.get("/api/u/{username}/rotations/models")
async def user_list_rotation_models_by_username(request: Request, username: str):
    """
    List all models for user rotations.
    """
    return await user_list_config_models_by_username(request, username, "rotations")


@app.get("/api/u/{username}/autoselections/models")
async def user_list_autoselection_models_by_username(request: Request, username: str):
    """
    List all models for user autoselections.
    """
    return await user_list_config_models_by_username(request, username, "autoselects")


@app.get("/api/u/{username}/{user_provider_id}/models")
async def user_list_provider_models_by_username(request: Request, username: str, user_provider_id: str):
    """
    List models for a specific user provider.
    """
    db = DatabaseRegistry.get_config_database()
    
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
    
    handler = get_user_handler('request', target_user_id)
    if user_provider_id not in handler.user_providers:
        return JSONResponse(
            status_code=404,
            content={"error": f"User provider '{user_provider_id}' not found"}
        )
    
    provider_config = handler.user_providers[user_provider_id]
    all_models = []
    
    try:
        if hasattr(provider_config, 'models') and provider_config.models:
            for model in provider_config.models:
                all_models.append({
                    "id": f"{user_provider_id}/{model.name}",
                    "name": model.name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": user_provider_id,
                    "provider_id": user_provider_id,
                    "type": "user_provider"
                })
        else:
            # Try to fetch models from provider API
            models = await fetch_provider_models(user_provider_id, user_id=target_user_id)
            for model in models:
                all_models.append({
                    "id": f"{user_provider_id}/{model.get('id', model.get('name', ''))}",
                    "name": model.get('name', ''),
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": user_provider_id,
                    "provider_id": user_provider_id,
                    "type": "user_provider"
                })
    except Exception as e:
        logger.warning(f"Error listing models for user provider {user_provider_id}: {e}")
    
    return {"data": all_models}


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
    db = DatabaseRegistry.get_config_database()
    
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
        for rotation_id, rotation_config in handler.rotations.items():
            try:
                providers = rotation_config.get('providers', [])
                for provider in providers:
                    for model in provider.get('models', []):
                        all_models.append({
                            "id": f"rotation/{rotation_id}/{model.get('name', '')}",
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
        for autoselect_id, autoselect_config in handler.autoselects.items():
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

@app.post("/api/u/{username}/chat/completions")
async def user_chat_completions(request: Request, username: str, body: ChatCompletionRequest):
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
    - 'rotation/name' - user's rotation
    - 'user-autoselect/name' - user's autoselect
    
    Example:
        curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
             -H "Content-Type: application/json" \
             -d '{"model": "rotation/myrotation", "messages": [{"role": "user", "content": "Hello"}]}' \
             http://localhost:17765/api/user/chat/completions
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)

    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            raise HTTPException(
                status_code=403,
                detail="Access denied. Username in URL must match authenticated user."
            )

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
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)
    
    # Handle user rotation (format: user-rotation/{name})
    if provider_id == "user-rotation":
        handler = get_user_handler('rotation', user_id)
        if actual_model not in handler.rotations:
            raise HTTPException(
                status_code=400,
                detail=f"User rotation '{actual_model}' not found. Available: {list(handler.rotations.keys())}"
            )
        body_dict['model'] = actual_model
        token_id = getattr(request.state, 'token_id', None)
        return await handler.handle_rotation_request(actual_model, body_dict, user_id, token_id)
    
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
                token_id = getattr(request.state, 'token_id', None)
                return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)
        
        # Handle global rotation
        if provider_id == "rotation":
            if actual_model not in config.rotations:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rotation '{actual_model}' not found. Available: {list(config.rotations.keys())}"
                )
            handler = get_user_handler('rotation', None)
            body_dict['model'] = actual_model
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_rotation_request(actual_model, body_dict, user_id, token_id)
        
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
         detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'. Global configurations are only available to admin users."
    )


# User-specific model listing endpoint
@app.get("/api/u/{username}/{config_type}/models")
async def user_list_config_models(request: Request, username: str, config_type: str):
    """
    List models for a specific user configuration type.

    Args:
        username: Username of the user
        config_type: One of 'providers', 'rotations', or 'autoselects'

    Authentication is done via Bearer token in the Authorization header.

    Example:
        curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/username/rotations/models
    """
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)

    # Validate username matches authenticated user (unless admin/global token)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied. Username in URL must match authenticated user."}
            )
    
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
        for rotation_id, rotation_config in handler.rotations.items():
            try:
                providers = rotation_config.get('providers', [])
                for provider in providers:
                    for model in provider.get('models', []):
                        all_models.append({
                            "id": f"rotation/{rotation_id}/{model.get('name', '')}",
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
        for autoselect_id, autoselect_config in handler.autoselects.items():
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
                
                # Store the callback data using state as key AND also store latest for backward compatibility
                if state:
                    _pending_oauth2_callbacks[state] = {
                        'code': code,
                        'state': state,
                        'error': error,
                        'timestamp': time.time()
                    }
                # Also store latest for backward compatibility
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
@app.get("/dashboard/oauth2/callback/{user_id}/{provider}")
async def dashboard_oauth2_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    user_id: str = None,
    provider: str = None
):
    """
    Handle OAuth2 callback redirected from localhost.
    
    This endpoint handles two scenarios:
    1. Direct localhost callback (when browser is on same machine as AISBF)
    2. Redirected callback from browser extension (when browser is remote)
    
    When using /dashboard/oauth2/callback/{user_id}/{provider} format, we know
    exactly which user and provider this callback belongs to, making state matching
    unnecessary and guaranteeing 100% compatibility with claude-code's implementation.
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
        
        # Store callback in global storage using STATE as unique key
        # This works across domains even when session cookie is not available
        _pending_oauth2_callbacks[state] = {
            'code': code,
            'state': state,
            'error': error,
            'timestamp': time.time(),
            'user_id': user_id,
            'provider': provider
        }
        
        # Also try to store in session if cookie is available (same domain)
        try:
            request.session['oauth2_code'] = code
            request.session['oauth2_state'] = state
            if user_id:
                request.session['oauth2_user_id'] = user_id
            if provider:
                request.session['oauth2_provider'] = provider
        except Exception:
            pass
        
        # Detect if this is a direct localhost callback (no extension involved)
        referer = request.headers.get('referer', '')
        is_direct_callback = 'localhost:54545' in referer or '127.0.0.1:54545' in referer
        
        logger.info(f"OAuth2 callback received - Direct: {is_direct_callback}, User: {user_id}, Provider: {provider}, State: {state[:10]}..., Code: {code[:10]}...")
        
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
        auth = ClaudeAuth(credentials_file=credentials_file, skip_initial_load=True)
        
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
        # Get state from user's session (always available since user was the one who started auth)
        state = request.session.get('oauth2_state')
        verifier = request.session.get('oauth2_verifier')
        credentials_file = request.session.get('oauth2_credentials_file', '~/.claude_credentials.json')
        
        # Get code from session OR from global storage using state
        code = request.session.get('oauth2_code')
        
        # Check global storage for THIS user's state
        if not code and state and state in _pending_oauth2_callbacks:
            callback_data = _pending_oauth2_callbacks[state]
            # Only use if received within the last 5 minutes
            if time.time() - callback_data.get('timestamp', 0) < 300:
                code = callback_data.get('code')
                if callback_data.get('error'):
                    return JSONResponse(
                        status_code=400,
                        content={"success": False, "error": f"OAuth2 error: {callback_data['error']}"}
                    )
                logger.info(f"Using code from global callback storage for state {state[:10]}...: {code[:10] if code else 'None'}...")
        
        if not code or not verifier:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "No authorization code found. Please restart authentication."}
            )
        
        # Import ClaudeAuth
        from aisbf.auth.claude import ClaudeAuth
        
        # Only the ONE config admin (user_id=None from aisbf.json) saves to file
        # All other users (including database admins) save to database
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        save_callback = None
        if not is_config_admin:
            # For non-admin users, set up save_callback to save directly to database
            provider_key = request.session.get('oauth2_provider')
            
            def save_callback(creds):
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db and current_user_id and provider_key:
                        db.save_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_key,
                            auth_type='claude_oauth2',
                            credentials=creds
                        )
                        logger.info(f"ClaudeOAuth2: Saved credentials to database for user {current_user_id}")
                except Exception as e:
                    logger.error(f"ClaudeOAuth2: Failed to save credentials to database: {e}")
                    raise
        
        # Create auth instance with proper save_callback
        auth = ClaudeAuth(
            credentials_file=credentials_file,
            skip_initial_load=True,
            save_callback=save_callback
        )
        
        # Use the new exchange_code_for_tokens method with retry logic
        # Pass state as the second parameter (required), verifier as third (optional)
        success = await auth.exchange_code_for_tokens(code, state, verifier)
        
        if success:
            # Clear temporary file for non-admin users (it was never written when using save_callback)
            if not is_config_admin:
                credentials_path = Path(credentials_file).expanduser()
                credentials_path.unlink(missing_ok=True)
            
            # Clear session data
            request.session.pop('oauth2_code', None)
            request.session.pop('oauth2_verifier', None)
            request.session.pop('oauth2_state', None)
            request.session.pop('oauth2_provider', None)
            request.session.pop('oauth2_credentials_file', None)
            
            # Clear pending callback data for THIS user's state
            if state:
                _pending_oauth2_callbacks.pop(state, None)
            
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
    
    # Get expected state from user's session (this is what we generated when auth started)
    expected_state = request.session.get('oauth2_state')
    
    # Check if we have callback data matching THIS user's state
    if expected_state and expected_state in _pending_oauth2_callbacks:
        callback_data = _pending_oauth2_callbacks[expected_state]
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
    
    # Also check session (for same domain flow)
    if request.session.get('oauth2_code'):
        return JSONResponse({
            "received": True,
            "has_code": True
        })
    
    # Garbage collect stale entries older than 10 minutes
    now = time.time()
    stale_states = [k for k, v in _pending_oauth2_callbacks.items() 
                    if k != 'latest' and now - v.get('timestamp', 0) > 600]
    for stale in stale_states:
        _pending_oauth2_callbacks.pop(stale, None)
    
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
                db = DatabaseRegistry.get_config_database()
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
        auth = KiloOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        
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
        auth = KiloOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        
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
                        db = DatabaseRegistry.get_config_database()
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
                "status": "completed",
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
                db = DatabaseRegistry.get_config_database()
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
            token = await auth.get_valid_token()
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
        auth = KiloOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        
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
        auth = CodexOAuth2(credentials_file=credentials_file, issuer=issuer, skip_initial_load=True)

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
        auth = CodexOAuth2(credentials_file=credentials_file, issuer=issuer, skip_initial_load=True)
        
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
                    db = DatabaseRegistry.get_config_database()
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
                db = DatabaseRegistry.get_config_database()
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
            token = await auth.get_valid_token_with_refresh()
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
        auth = QwenOAuth2(credentials_file=credentials_file, skip_initial_load=True)

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
        auth = QwenOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        
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
                    db = DatabaseRegistry.get_config_database()
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
                "status": "completed",
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
                db = DatabaseRegistry.get_config_database()
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
                db = DatabaseRegistry.get_config_database()
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


@app.post("/dashboard/contact")
async def dashboard_contact(request: Request):
    """Handle contact form submissions"""
    is_authenticated = not require_dashboard_auth(request)

    try:
        data = await request.json()
        message_type = data.get('type')
        title = data.get('title')
        message = data.get('message')

        if not all([message_type, title, message]):
            return JSONResponse({'success': False, 'error': 'All fields are required'}, status_code=400)

        # Get user info — for unauthenticated users, require a reply-to email
        user_id = request.session.get('user_id')
        username = request.session.get('username', 'Unknown')
        email = request.session.get('email')

        if not is_authenticated:
            provided_email = data.get('email', '').strip()
            if not provided_email:
                return JSONResponse({'success': False, 'error': 'Email is required'}, status_code=400)
            email = provided_email
            username = 'Guest'
            user_id = None
        
        # Get SMTP config
        from aisbf.config import get_config
        config = get_config()
        smtp_config = config.aisbf.smtp if config and hasattr(config, 'aisbf') and config.aisbf and hasattr(config.aisbf, 'smtp') else None
        
        if not smtp_config or not smtp_config.enabled:
            return JSONResponse({'success': False, 'error': 'Email service is not configured'}, status_code=500)
        
        # Import email utilities
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[AISBF Contact] {message_type.upper()}: {title}"
        msg['From'] = f"{smtp_config.from_name} <{smtp_config.from_email}>"
        msg['To'] = "stefy@aisbf.cloud"
        if email:
            msg['Reply-To'] = email
        
        email_display = email or 'No email provided'

        # Create email content
        text = f"""
Contact Form Submission:

Type: {message_type}
Title: {title}

User ID: {user_id or 'Guest (not logged in)'}
Username: {username}
Email: {email_display}

Message:
{message}
        """
        
        html = f"""
<html>
  <body>
    <h3>Contact Form Submission</h3>
    <p><strong>Type:</strong> {message_type}</p>
    <p><strong>Title:</strong> {title}</p>
    <br>
    <p><strong>User ID:</strong> {user_id or 'Guest (not logged in)'}</p>
    <p><strong>Username:</strong> {username}</p>
    <p><strong>Email:</strong> {email_display}</p>
    <br>
    <p><strong>Message:</strong></p>
    <pre>{message}</pre>
  </body>
</html>
        """
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        if smtp_config.use_ssl:
            with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port) as server:
                if smtp_config.username and smtp_config.password:
                    server.ehlo()
                    server.login(smtp_config.username, smtp_config.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_config.host, smtp_config.port) as server:
                server.ehlo()
                if smtp_config.use_tls:
                    server.starttls()
                    server.ehlo()
                if smtp_config.username and smtp_config.password:
                    server.login(smtp_config.username, smtp_config.password)
                server.send_message(msg)
        
        return JSONResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Contact form error: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.post("/dashboard/welcome-shown")
async def dashboard_welcome_shown(request: Request):
    """Mark welcome modal as shown for this session"""
    if 'session' in request.scope:
        request.session['welcome_shown'] = True
    return JSONResponse({'success': True})


@app.get("/dashboard/tor/status")
async def dashboard_tor_status(request: Request):
    """Get Tor hidden service status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Only admin can access Tor status
    if request.session.get('role') != 'admin':
        return JSONResponse({'success': False, 'error': 'Admin access required'}, status_code=403)
    
    try:
        from aisbf.config import get_config
        config = get_config()
        
        tor_enabled = config and hasattr(config, 'tor') and config.tor and config.tor.enabled
        tor_running = tor_service is not None and tor_service.is_connected() if tor_service else False
        
        response = {
            'enabled': tor_enabled,
            'running': tor_running,
            'onion_address': tor_service.onion_address if tor_service and tor_service.onion_address else None
        }
        
        return JSONResponse(response)
        
    except Exception as e:
        logger.error(f"Tor status error: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


if __name__ == "__main__":
    main()
