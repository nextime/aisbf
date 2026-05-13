"""
App startup/shutdown, initialization, signal handling, and server config loading.
Extracted from main.py.
"""
from decimal import Decimal
from typing import Optional
import time
import logging
import sys
import os
import signal
import atexit
import secrets
import asyncio
import multiprocessing
import threading
import json
from pathlib import Path
from logging.handlers import RotatingFileHandler
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# Globals (shared with main.py via import)
# ---------------------------------------------------------------------------
_custom_config_dir = None
_original_argv = None
payment_service = None
_initialized = False
_server_ip_blocked: bool = False
_claude_cli_mode = False
_user_handlers_cache = {}
tor_service = None
_cache_refresh_task = None
_background_tasks: set = set()
_config_reload_lock = threading.Lock()


def set_config_dir(config_dir: str):
    global _custom_config_dir
    _custom_config_dir = config_dir
    os.environ['AISBF_CONFIG_DIR'] = config_dir


def get_config_dir():
    return _custom_config_dir or os.environ.get('AISBF_CONFIG_DIR')


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
class BrokenPipeFilter(logging.Filter):
    def filter(self, record):
        if record.getMessage().startswith('--- Logging error ---'):
            return False
        if 'BrokenPipeError' in record.getMessage():
            return False
        return True


class SafeStderr:
    def __init__(self, original_stderr, log_file_path):
        self.original_stderr = original_stderr
        self.log_file = None
        try:
            self.log_file = open(log_file_path, 'a')
        except Exception:
            pass

    def write(self, data):
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
    if os.geteuid() == 0:
        log_dir = Path('/var/log/aisbf')
    else:
        log_dir = Path.home() / '.local' / 'var' / 'log' / 'aisbf'
    log_dir.mkdir(parents=True, exist_ok=True)

    AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')

    log_file = log_dir / 'aisbf.log'
    file_handler = RotatingFileHandler(log_file, maxBytes=50*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(fmt)

    error_handler = RotatingFileHandler(log_dir / 'aisbf_error.log', maxBytes=50*1024*1024, backupCount=5, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    if AISBF_DEBUG:
        console_handler.setLevel(logging.DEBUG)
        if not getattr(setup_logging, '_debug_banner_shown', False):
            print("=== AISBF DEBUG MODE ENABLED ===")
            setup_logging._debug_banner_shown = True
    else:
        console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    for noisy_logger in (
        'websockets.client',
        'websockets.server',
        'websockets.protocol',
        'uvicorn.protocols.websockets.websockets_impl',
    ):
        logging.getLogger(noisy_logger).setLevel(logging.INFO if AISBF_DEBUG else logging.WARNING)

    bpf = BrokenPipeFilter()
    for h in (file_handler, error_handler, console_handler):
        h.addFilter(bpf)

    try:
        sys.stderr = SafeStderr(sys.stderr, log_dir / 'aisbf_stderr.log')
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not redirect stderr: {e}")

    return logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def generate_self_signed_cert(cert_file: Path, key_file: Path):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from datetime import datetime, timedelta

    logger = logging.getLogger(__name__)
    logger.info("Generating self-signed SSL certificate...")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AISBF"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(private_key, hashes.SHA256()))

    key_file.parent.mkdir(parents=True, exist_ok=True)
    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    logger.info(f"Generated self-signed certificate: {cert_file}")


def get_aisbf_config_path(custom_config_dir=None) -> Path:
    candidates = []
    if custom_config_dir:
        candidates.append(Path(custom_config_dir) / 'aisbf.json')
    candidates += [
        Path.home() / '.aisbf' / 'aisbf.json',
        Path.home() / '.local' / 'share' / 'aisbf' / 'aisbf.json',
        Path('/usr/local/share/aisbf/aisbf.json'),
        Path('/usr/share/aisbf/aisbf.json'),
        Path(__file__).parent.parent.parent / 'config' / 'aisbf.json',
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]


def load_server_config(custom_config_dir=None):
    config_path = None
    if custom_config_dir:
        p = Path(custom_config_dir) / 'aisbf.json'
        if p.exists():
            config_path = p

    if not config_path:
        config_path = Path.home() / '.aisbf' / 'aisbf.json'

    if not config_path.exists():
        for d in [Path('/usr/share/aisbf'), Path.home() / '.local' / 'share' / 'aisbf']:
            t = d / 'aisbf.json'
            if t.exists():
                config_path = t
                break
        else:
            t = Path(__file__).parent.parent.parent / 'config' / 'aisbf.json'
            if t.exists():
                config_path = t

    if config_path and config_path.exists():
        try:
            with open(config_path) as f:
                data = json.load(f)
            srv = data.get('server', {})
            auth = data.get('auth', {})
            protocol = srv.get('protocol', 'http')
            ssl_certfile = srv.get('ssl_certfile')
            ssl_keyfile = srv.get('ssl_keyfile')
            if protocol == 'https':
                if not ssl_certfile or not ssl_keyfile:
                    ssl_dir = Path.home() / '.aisbf' / 'ssl'
                    ssl_certfile = str(ssl_dir / 'cert.pem')
                    ssl_keyfile = str(ssl_dir / 'key.pem')
                cert_path = Path(ssl_certfile).expanduser()
                key_path = Path(ssl_keyfile).expanduser()
                if not cert_path.exists() or not key_path.exists():
                    generate_self_signed_cert(cert_path, key_path)
            return {
                'host': srv.get('host', '0.0.0.0'),
                'port': srv.get('port', 17765),
                'protocol': protocol,
                'ssl_certfile': ssl_certfile if protocol == 'https' else None,
                'ssl_keyfile': ssl_keyfile if protocol == 'https' else None,
                'auth_enabled': auth.get('enabled', False),
                'auth_tokens': auth.get('tokens', [])
            }
        except Exception as e:
            logging.getLogger(__name__).warning(f"Error loading aisbf.json: {e}, using defaults")

    return {'host': '0.0.0.0', 'port': 17765, 'protocol': 'http',
            'ssl_certfile': None, 'ssl_keyfile': None,
            'auth_enabled': False, 'auth_tokens': []}


def _get_or_create_session_secret():
    secret_file = Path.home() / '.aisbf' / 'session_secret.key'
    if secret_file.exists():
        try:
            with open(secret_file) as f:
                return f.read().strip()
        except Exception:
            pass
    secret = secrets.token_urlsafe(32)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        with open(secret_file, 'w') as f:
            f.write(secret)
        os.chmod(secret_file, 0o600)
    except Exception:
        pass
    return secret


# ---------------------------------------------------------------------------
# Config reload helpers
# ---------------------------------------------------------------------------
def _reload_global_config():
    logger = logging.getLogger(__name__)
    with _config_reload_lock:
        try:
            from aisbf.config import config as _global_cfg
            if _global_cfg is not None:
                _global_cfg.reload()
                logger.info("Global config hot-reloaded after dashboard change")
        except Exception as e:
            logger.error(f"Error reloading global config: {e}", exc_info=True)


def _apply_condense_defaults_provider(provider: dict):
    for model in provider.get('models', []):
        if isinstance(model, dict) and model.get('condense_method') and not model.get('condense_context'):
            model['condense_context'] = 80


def _apply_condense_defaults_rotation(rotation: dict):
    for prov in rotation.get('providers', []):
        for model in prov.get('models', []):
            if isinstance(model, dict) and model.get('condense_method') and not model.get('condense_context'):
                model['condense_context'] = 80


def _providers_json_path():
    p = Path.home() / '.aisbf' / 'providers.json'
    if not p.exists():
        p = Path(__file__).parent.parent.parent / 'config' / 'providers.json'
    return p


def _rotations_json_path():
    p = Path.home() / '.aisbf' / 'rotations.json'
    if not p.exists():
        p = Path(__file__).parent.parent.parent / 'config' / 'rotations.json'
    return p


def _autoselect_json_path():
    p = Path.home() / '.aisbf' / 'autoselect.json'
    if not p.exists():
        p = Path(__file__).parent.parent.parent / 'config' / 'autoselect.json'
    return p


# ---------------------------------------------------------------------------
# Admin notifications
# ---------------------------------------------------------------------------
def _get_admin_notifications_config(config) -> dict:
    defaults = {
        'new_user_signup': False, 'payment_received': False,
        'tier_upgrade': False, 'tier_downgrade': False,
        'subscription_expired': False, 'subscription_renewed': False,
        'wallet_topup': False, 'user_deleted_account': False,
    }
    try:
        if config and config.aisbf and hasattr(config.aisbf, 'dashboard') and config.aisbf.dashboard:
            notif = getattr(config.aisbf.dashboard, 'notifications', None)
            if notif:
                nd = notif if isinstance(notif, dict) else vars(notif)
                defaults.update({k: bool(v) for k, v in nd.items() if k in defaults})
    except Exception:
        pass
    return defaults


def _get_admin_email(config) -> str:
    try:
        if config and config.aisbf and hasattr(config.aisbf, 'dashboard') and config.aisbf.dashboard:
            return getattr(config.aisbf.dashboard, 'email', '') or ''
    except Exception:
        pass
    return ''


def _send_admin_notification_email(config, event_key: str, subject: str, body_html: str):
    try:
        if not _get_admin_notifications_config(config).get(event_key, False):
            return
        admin_email = _get_admin_email(config)
        if not admin_email:
            return
        smtp_cfg = None
        if config and config.aisbf and hasattr(config.aisbf, 'smtp'):
            smtp_cfg = config.aisbf.smtp
        if not smtp_cfg or not getattr(smtp_cfg, 'enabled', False):
            return
        from aisbf.email_utils import send_simple_email
        send_simple_email(admin_email, subject, body_html, smtp_cfg)
    except Exception as e:
        logging.getLogger(__name__).warning(f"_send_admin_notification_email({event_key}): {e}")


# ---------------------------------------------------------------------------
# Login rate limiter
# ---------------------------------------------------------------------------
_login_failures: dict = {}
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECS = 300
_LOGIN_LOCKOUT_SECS = 600


def _login_rate_limit_check(ip: str, username: str) -> bool:
    key = f"{ip}:{username.lower()}"
    now = time.time()
    attempts = [t for t in _login_failures.get(key, []) if now - t < _LOGIN_WINDOW_SECS]
    _login_failures[key] = attempts
    return len(attempts) >= _LOGIN_MAX_ATTEMPTS


def _login_record_failure(ip: str, username: str) -> None:
    _login_failures.setdefault(f"{ip}:{username.lower()}", []).append(time.time())


def _login_clear_failures(ip: str, username: str) -> None:
    _login_failures.pop(f"{ip}:{username.lower()}", None)


# ---------------------------------------------------------------------------
# Handler cache
# ---------------------------------------------------------------------------
def get_user_handler(handler_type: str, request_handler, rotation_handler, autoselect_handler, user_id=None):
    from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler

    if user_id is None:
        if handler_type == 'request':
            return request_handler
        elif handler_type == 'rotation':
            return rotation_handler
        elif handler_type == 'autoselect':
            return autoselect_handler
        raise ValueError(f"Unknown handler type: {handler_type}")

    cache_key = f"{handler_type}_{user_id}"
    if cache_key in _user_handlers_cache:
        return _user_handlers_cache[cache_key]

    if handler_type == 'request':
        handler = RequestHandler(user_id)
    elif handler_type == 'rotation':
        handler = RotationHandler(user_id)
    elif handler_type == 'autoselect':
        handler = AutoselectHandler(user_id)
    else:
        raise ValueError(f"Unknown handler type: {handler_type}")

    _user_handlers_cache[cache_key] = handler
    return handler


# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------
def initialize_app(app_state: dict, custom_config_dir=None):
    """Initialize app globals. app_state is a dict that holds config, handlers, etc."""
    logger = logging.getLogger(__name__)

    if app_state.get('_initialized'):
        return

    if custom_config_dir:
        set_config_dir(custom_config_dir)
        logger.info(f"Using custom config directory: {custom_config_dir}")

    import shutil as _shutil
    from aisbf.providers.claude_cli import detect_claude_cli
    if detect_claude_cli():
        app_state['_claude_cli_mode'] = True
        import aisbf.providers.claude_cli as _cli_mode_mod
        logger.info(f"Claude CLI detected at {_cli_mode_mod.CLAUDE_CLI_PATH} – CLI proxy mode enabled")
    else:
        logger.info("Claude CLI not found in PATH – using HTTP API mode")

    from aisbf.config import config as cfg
    from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler

    app_state['config'] = cfg
    app_state['request_handler'] = RequestHandler()
    app_state['rotation_handler'] = RotationHandler()
    app_state['autoselect_handler'] = AutoselectHandler()
    app_state['server_config'] = load_server_config(custom_config_dir)

    aisbf_config_path = get_aisbf_config_path(custom_config_dir)
    if aisbf_config_path.exists():
        with open(aisbf_config_path) as f:
            aisbf_config = json.load(f)
        app_state['server_config']['dashboard_config'] = aisbf_config.get('dashboard', {})
    else:
        app_state['server_config']['dashboard_config'] = {
            'username': 'admin',
            'password': '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'
        }

    app_state['_initialized'] = True
    logger.info("App initialization complete")


# ---------------------------------------------------------------------------
# Multiprocessing / signal cleanup
# ---------------------------------------------------------------------------
def _cleanup_multiprocessing_children():
    logger = logging.getLogger(__name__)
    try:
        active = multiprocessing.active_children()
        if active:
            logger.info(f"Terminating {len(active)} multiprocessing child process(es)...")
            for child in active:
                child.terminate()
            for child in active:
                child.join(timeout=2)
            for child in multiprocessing.active_children():
                child.kill()
    except Exception as e:
        logger.warning(f"Error cleaning up multiprocessing children: {e}")


def _signal_handler(signum, frame):
    logger = logging.getLogger(__name__)
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, shutting down...")
    _cleanup_multiprocessing_children()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def register_signal_handlers():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(_cleanup_multiprocessing_children)
