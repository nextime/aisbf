from contextlib import asynccontextmanager
from decimal import Decimal
"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""
import os
import sys
import time
import asyncio
import argparse
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from cryptography.fernet import Fernet

from aisbf import __version__
from aisbf.database import DatabaseRegistry
from aisbf.cache import initialize_cache
from aisbf.tor import setup_tor_hidden_service

# ---------------------------------------------------------------------------
# App-level modules
# ---------------------------------------------------------------------------
from aisbf.app.startup import (
    setup_logging, set_config_dir, get_config_dir,
    get_aisbf_config_path, load_server_config, _get_or_create_session_secret,
    initialize_app, register_signal_handlers, _cleanup_multiprocessing_children,
    generate_self_signed_cert,
)
from aisbf.app.templates import (
    ProxyHeadersMiddleware, get_base_url, url_for,
    create_templates, setup_template_globals, patch_template_response,
)
from aisbf.app.middleware import (
    GenocidalBlockingMiddleware,
    make_api_token_authorization_middleware,
    make_auth_middleware,
    make_tier_limit_middleware,
    make_dashboard_context_middleware,
    make_client_rate_limiting_middleware,
)
from aisbf import geolocation

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = setup_logging()

# ---------------------------------------------------------------------------
# App state (mutable globals shared across modules)
# ---------------------------------------------------------------------------
_app_state: dict = {
    'config': None,
    'server_config': None,
    'request_handler': None,
    'rotation_handler': None,
    'autoselect_handler': None,
    '_initialized': False,
    '_claude_cli_mode': False,
    'payment_service': None,
    'tor_service': None,
    '_cache_refresh_task': None,
}
_background_tasks: set = set()
_server_ip_blocked: bool = False


def _get_config():
    return _app_state.get('config')


def _get_server_config():
    return _app_state.get('server_config')


def _get_db():
    return DatabaseRegistry.get_config_database()


def _get_user_handler(handler_type: str, user_id=None):
    from aisbf.app.startup import get_user_handler
    return get_user_handler(
        handler_type,
        _app_state['request_handler'],
        _app_state['rotation_handler'],
        _app_state['autoselect_handler'],
        user_id,
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _run_startup()
    try:
        yield
    finally:
        await _run_shutdown()


app = FastAPI(
    title="AI Proxy Server",
    max_request_size=100 * 1024 * 1024,
    lifespan=lifespan,
)

_static_dir = Path(__file__).parent / 'static'
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/dashboard/static", StaticFiles(directory=str(_static_dir)), name="static")

_template_dir = str(Path(__file__).parent / 'templates')
templates = create_templates(_template_dir)
setup_template_globals(templates, __version__)
patch_template_response(templates)

_session_secret = _get_or_create_session_secret()

_DEFAULT_ADMIN_SHA256 = '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error on {request.url.path}: {exc.errors()}")
    body_data = None
    if hasattr(exc, 'body'):
        if isinstance(exc.body, dict):
            body_data = exc.body
        elif hasattr(exc.body, 'items'):
            body_data = dict(exc.body.items())
        else:
            body_data = str(exc.body)
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": body_data})


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        from fastapi.responses import HTMLResponse
        p = Path(__file__).parent / "aisbf" / "templates" / "404.html"
        if p.exists():
            return HTMLResponse(content=p.read_text(), status_code=404)
    return JSONResponse(status_code=404, content={"detail": "Not found"})


# ---------------------------------------------------------------------------
# Middleware (registration order: last added = first executed)
# ---------------------------------------------------------------------------
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

app.middleware("http")(make_dashboard_context_middleware())
app.middleware("http")(make_client_rate_limiting_middleware(_get_config))
app.middleware("http")(make_tier_limit_middleware(_get_db, _background_tasks))
app.middleware("http")(make_api_token_authorization_middleware(_get_server_config, _get_db))
app.middleware("http")(make_auth_middleware(_get_server_config, _get_config, _get_db, url_for))

app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    max_age=30 * 24 * 60 * 60,
    same_site="lax",
    https_only=os.environ.get("AISBF_HTTPS", "false").lower() == "true",
)
app.add_middleware(GenocidalBlockingMiddleware, server_ip_blocked_ref=lambda: _server_ip_blocked)
app.add_middleware(ProxyHeadersMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
import aisbf.routes.auth as _auth_routes
import aisbf.routes.api as _api_routes
import aisbf.routes.coderai_broker as _coderai_broker_routes
import aisbf.routes.mcp as _mcp_routes
import aisbf.routes.user_api as _user_api_routes
import aisbf.routes.dashboard.providers as _dash_providers
import aisbf.routes.dashboard.settings as _dash_settings
import aisbf.routes.dashboard.admin as _dash_admin
import aisbf.routes.dashboard.payments as _dash_payments
import aisbf.routes.dashboard.provider_auth as _dash_provider_auth

app.include_router(_auth_routes.router)
app.include_router(_api_routes.router)
app.include_router(_coderai_broker_routes.router)
app.include_router(_mcp_routes.router)
app.include_router(_user_api_routes.router)
app.include_router(_dash_providers.router)
app.include_router(_dash_settings.router)
app.include_router(_dash_admin.router)
app.include_router(_dash_payments.router)
app.include_router(_dash_provider_auth.router)

# Wallet routes
try:
    from aisbf.payments.wallet.routes import router as wallet_router
    app.include_router(wallet_router)
except ImportError:
    logger.warning("Wallet routes not available")


def _init_all_routers():
    """Inject config/templates into all route modules after app init."""
    config = _app_state['config']
    server_config = _app_state['server_config']

    _auth_routes.init(config, templates, server_config)
    _api_routes.init(config, _get_user_handler, _app_state['rotation_handler'])
    _mcp_routes.init(server_config, _get_user_handler)
    _user_api_routes.init(config, _get_user_handler)
    _dash_providers.init(config, templates, server_config)
    _dash_settings.init(config, templates)
    _dash_admin.init(config, templates)
    _dash_payments.init(config, templates)
    _dash_provider_auth.init(config, templates)


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------
async def _check_server_ip_country() -> None:
    global _server_ip_blocked
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://api.ipify.org")
            if resp.status_code == 200:
                server_ip = resp.text.strip()
                country = await geolocation.get_ip_country(server_ip)
                if country == 'IL':
                    _server_ip_blocked = True
                    logger.warning(f"Server public IP {server_ip} is Israeli — all access will be blocked")
                else:
                    logger.info(f"Server public IP {server_ip} country: {country}")
    except Exception as e:
        logger.warning(f"Could not determine server public IP country: {e}")


async def _run_startup() -> None:
    global _server_ip_blocked

    await _check_server_ip_country()

    if not _app_state['_initialized']:
        custom_config_dir = get_config_dir()
        initialize_app(_app_state, custom_config_dir)

    config = _app_state['config']
    server_config = _app_state['server_config']

    # Initialize database
    try:
        db_config = config.aisbf.database if config.aisbf and config.aisbf.database else None
        if db_config and hasattr(db_config, 'model_dump'):
            db_config = db_config.model_dump()
        elif db_config and hasattr(db_config, 'dict'):
            db_config = db_config.dict()
        DatabaseRegistry.get_config_database(db_config)
        from aisbf.analytics import initialize_analytics
        initialize_analytics(DatabaseRegistry.get_config_database())
        logger.info("Analytics module initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Initialize cache
    try:
        cache_config = config.aisbf.cache if config.aisbf and config.aisbf.cache else None
        initialize_cache(cache_config)
    except Exception as e:
        logger.error(f"Failed to initialize cache: {e}")

    # Initialize response cache
    try:
        from aisbf.cache import initialize_response_cache
        rc_config = config.aisbf.response_cache if config.aisbf and config.aisbf.response_cache else None
        if rc_config:
            initialize_response_cache(rc_config.model_dump() if hasattr(rc_config, 'model_dump') else rc_config)
    except Exception as e:
        logger.error(f"Failed to initialize response cache: {e}")

    # Initialize request batcher
    try:
        from aisbf.batching import initialize_request_batcher
        bc = config.aisbf.batching if config.aisbf and config.aisbf.batching else None
        if bc:
            bd = bc.model_dump() if hasattr(bc, 'model_dump') else dict(bc)
            initialize_request_batcher(bd)
    except Exception as e:
        logger.error(f"Failed to initialize request batcher: {e}")

    # Log loaded config files
    if config and hasattr(config, '_loaded_files'):
        logger.info("=" * 60)
        for k, v in config._loaded_files.items():
            logger.info(f"  {k.capitalize()}: {v}")
        logger.info("=" * 60)

    # TOR
    if config and hasattr(config, 'tor') and config.tor and config.tor.enabled:
        local_port = server_config.get('port', 17765) if server_config else 17765
        tor_service = setup_tor_hidden_service(config.tor, local_port)
        _app_state['tor_service'] = tor_service
        if tor_service:
            logger.info("TOR hidden service initialized")

    # Payment service
    try:
        db_manager = DatabaseRegistry.get_config_database()
        encryption_key = db_manager.get_encryption_key()
        if not encryption_key:
            encryption_key = os.getenv('ENCRYPTION_KEY')
        if not encryption_key:
            encryption_key = Fernet.generate_key().decode()
            db_manager.save_encryption_key(encryption_key)

        from aisbf.payments.service import PaymentService
        from aisbf.payments.migrations import PaymentMigrations
        PaymentMigrations(db_manager).run_migrations()
        payment_service = PaymentService(db_manager, {
            'encryption_key': encryption_key,
            'base_url': os.getenv('BASE_URL', 'http://localhost:17765'),
            'currency_code': 'EUR',
            'btc_confirmations': 3,
            'eth_confirmations': 12,
        })
        await payment_service.initialize()
        app.state.payment_service = payment_service
        _app_state['payment_service'] = payment_service
        logger.info("Payment service started")
    except Exception as e:
        logger.error(f"Failed to initialize payment service: {e}")

    # Initialize routers with config/templates
    _init_all_routers()

    # Background tasks
    from aisbf.app.model_cache import prefetch_global_provider_models, refresh_model_cache
    asyncio.create_task(prefetch_global_provider_models(config))
    if _app_state['_cache_refresh_task'] is None:
        _app_state['_cache_refresh_task'] = asyncio.create_task(refresh_model_cache(config))

    logger.info(f"=== AISBF {__version__} Started ===")
    logger.info(f"Providers: {list(config.providers.keys()) if config else []}")


async def _run_shutdown() -> None:
    tor_service = _app_state.get('tor_service')
    if tor_service:
        tor_service.disconnect()
    _cleanup_multiprocessing_children()


# Register OS signal handlers
register_signal_handlers()

# ---------------------------------------------------------------------------
# Payment API endpoints (thin wrappers — payment_service from app.state)
# ---------------------------------------------------------------------------
async def _get_current_user(request: Request) -> dict:
    from fastapi import HTTPException
    user_id = getattr(request.state, 'user_id', None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@app.get("/api/crypto/addresses")
async def get_crypto_addresses(request: Request):
    u = await _get_current_user(request)
    return {'addresses': await request.app.state.payment_service.get_user_crypto_addresses(u['id'])}


@app.get("/api/crypto/wallets")
async def get_crypto_wallets(request: Request):
    u = await _get_current_user(request)
    return {'wallets': await request.app.state.payment_service.get_user_wallet_balances(u['id'])}


@app.post("/api/payment-methods/crypto")
async def add_crypto_payment_method(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.add_crypto_payment_method(u['id'], body['crypto_type'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/payment-methods/stripe")
async def add_stripe_payment_method(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.add_stripe_payment_method(u['id'], body['payment_method_token'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/payment-methods/paypal/initiate")
async def initiate_paypal_payment_method(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.initiate_paypal_billing_agreement(u['id'], body['return_url'], body['cancel_url'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/payment-methods/paypal/complete")
async def complete_paypal_payment_method(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.complete_paypal_billing_agreement(u['id'], body['token'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.get("/api/payment-methods")
async def get_payment_methods(request: Request):
    u = await _get_current_user(request)
    return {'payment_methods': await request.app.state.payment_service.get_payment_methods(u['id'])}


@app.delete("/api/payment-methods/{payment_method_id}")
async def delete_payment_method(payment_method_id: int, request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    result = await request.app.state.payment_service.delete_payment_method(u['id'], payment_method_id)
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    return await request.app.state.payment_service.stripe_handler.handle_webhook(
        payload, request.headers.get("Stripe-Signature"))


@app.post("/api/webhooks/paypal")
async def paypal_webhook(request: Request):
    result = await request.app.state.payment_service.paypal_handler.handle_webhook(
        await request.json(), dict(request.headers))
    if result.get('status') == 'error':
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/subscriptions")
async def create_subscription(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.create_subscription(u['id'], body['tier_id'], body['payment_method_id'], body['billing_cycle'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/subscriptions/upgrade")
async def upgrade_subscription(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.upgrade_subscription(u['id'], body['tier_id'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/subscriptions/downgrade")
async def downgrade_subscription(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    body = await request.json()
    result = await request.app.state.payment_service.downgrade_subscription(u['id'], body['tier_id'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.post("/api/subscriptions/cancel")
async def cancel_subscription(request: Request):
    from fastapi import HTTPException
    u = await _get_current_user(request)
    result = await request.app.state.payment_service.cancel_subscription(u['id'])
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.get("/api/subscriptions/status")
async def get_subscription_status(request: Request):
    u = await _get_current_user(request)
    return {'subscription': await request.app.state.payment_service.get_subscription_status(u['id'])}


@app.get("/api/users/search")
async def search_users(request: Request, q: str = ""):
    from fastapi import HTTPException
    from aisbf.routes.auth import require_dashboard_auth
    if require_dashboard_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.session.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    db = DatabaseRegistry.get_config_database()
    if not db:
        return {"users": []}
    all_users = db.get_users()
    filtered = [{"id": u['id'], "username": u['username'], "role": u.get('role', 'user')}
                for u in all_users if not q or q.lower() in u['username'].lower()]
    return {"users": filtered[:50]}


@app.get("/dashboard/api/auth-check")
async def dashboard_auth_check(request: Request):
    authenticated = bool(request.session.get('logged_in') and request.session.get('user_id'))
    return JSONResponse({"authenticated": authenticated})


@app.post("/api/admin/analytics/delete-global")
async def analytics_delete_global(request: Request):
    from aisbf.routes.auth import require_dashboard_auth
    if require_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if request.session.get('role') != 'admin' or request.session.get('user_id') is not None:
        return JSONResponse({"error": "Config admin only"}, status_code=403)
    db = DatabaseRegistry.get_config_database()
    return JSONResponse({"deleted": db.delete_analytics_global()})


@app.post("/api/admin/analytics/delete-all")
async def analytics_delete_all(request: Request):
    from aisbf.routes.auth import require_dashboard_auth
    if require_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if request.session.get('role') != 'admin' or request.session.get('user_id') is not None:
        return JSONResponse({"error": "Config admin only"}, status_code=403)
    db = DatabaseRegistry.get_config_database()
    return JSONResponse({"deleted": db.delete_analytics_all()})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    import uvicorn

    parser = argparse.ArgumentParser(description='AISBF - AI Service Broker Framework')
    parser.add_argument('--config', type=str)
    parser.add_argument('--host', type=str)
    parser.add_argument('--port', type=int)
    parser.add_argument('--https', action='store_true')
    parser.add_argument('--ssl-cert', type=str)
    parser.add_argument('--ssl-key', type=str)
    parser.add_argument('--no-auth', action='store_true')
    args = parser.parse_args()

    global _app_state
    _app_state['_original_argv'] = sys.argv.copy()

    initialize_app(_app_state, args.config)
    server_config = _app_state['server_config']

    host = args.host or server_config['host']
    port = args.port or server_config['port']

    if args.https:
        protocol = 'https'
        ssl_certfile = args.ssl_cert or server_config.get('ssl_certfile')
        ssl_keyfile = args.ssl_key or server_config.get('ssl_keyfile')
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
        if protocol == 'https':
            if not ssl_certfile or not ssl_keyfile:
                ssl_dir = Path.home() / '.aisbf' / 'ssl'
                ssl_certfile = str(ssl_dir / 'cert.pem')
                ssl_keyfile = str(ssl_dir / 'key.pem')
            cert_path = Path(ssl_certfile).expanduser()
            key_path = Path(ssl_keyfile).expanduser()
            if not cert_path.exists() or not key_path.exists():
                generate_self_signed_cert(cert_path, key_path)

    auth_enabled = not args.no_auth and server_config.get('auth_enabled', False)
    server_config.update({'host': host, 'port': port, 'protocol': protocol,
                          'ssl_certfile': ssl_certfile if protocol == 'https' else None,
                          'ssl_keyfile': ssl_keyfile if protocol == 'https' else None,
                          'auth_enabled': auth_enabled})

    logger.info(f"Starting AISBF {__version__} on {protocol}://{host}:{port}")

    uvicorn_kwargs = dict(host=host, port=port, timeout_keep_alive=300, timeout_graceful_shutdown=30)
    if protocol == 'https':
        uvicorn_kwargs['ssl_certfile'] = ssl_certfile
        uvicorn_kwargs['ssl_keyfile'] = ssl_keyfile

    uvicorn.run(app, **uvicorn_kwargs)


if __name__ == "__main__":
    main()
