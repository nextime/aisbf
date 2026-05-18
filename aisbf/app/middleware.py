"""
All ASGI middleware functions extracted from main.py.
"""
import time
import logging
import threading
import hmac as _hmac
import ipaddress
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


def _is_coderai_registration_route(path: str) -> bool:
    return (
        path == "/api/coderai/register"
        or path == "/api/coderai/wss"
        or path.startswith("/api/u/") and (path.endswith("/coderai/register") or path.endswith("/coderai/wss"))
    )


async def _record_dashboard_visit_event(request: Request, response) -> None:
    try:
        if not request.url.path.startswith("/dashboard"):
            return
        from aisbf.database import DatabaseRegistry
        from aisbf import geolocation
        db = DatabaseRegistry.get_config_database()
        ip_address = _get_real_client_ip(request)
        country_code = None
        if ip_address and ip_address != 'unknown' and not _is_private_or_local_ip(ip_address):
            try:
                country_code = await geolocation.get_ip_country(ip_address)
            except Exception:
                country_code = None
        session_token = None
        if hasattr(request, 'session'):
            session_token = request.session.get('username') or request.session.get('user_id') or request.session.get('role')
        db.record_dashboard_event(
            event_type='dashboard_visit',
            path=request.url.path,
            user_id=request.session.get('user_id') if hasattr(request, 'session') else None,
            username=request.session.get('username') if hasattr(request, 'session') else None,
            session_id=str(session_token) if session_token is not None else None,
            ip_address=ip_address if ip_address != 'unknown' else None,
            country_code=country_code,
            method=request.method,
            status_code=getattr(response, 'status_code', None),
            metadata={
                'query': dict(request.query_params),
                'is_admin': request.session.get('role') == 'admin' if hasattr(request, 'session') else False,
            },
        )
    except Exception:
        logger.debug("Failed to record dashboard visit event", exc_info=True)

# ---------------------------------------------------------------------------
# Client rate limiter state
# ---------------------------------------------------------------------------
_client_rl_state: dict = {}
_client_rl_lock = threading.Lock()


def _get_real_client_ip(request: Request) -> str:
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        # Use rightmost IP (appended by the trusted upstream proxy) to prevent spoofing
        return xff.split(',')[-1].strip()
    client = request.scope.get('client')
    return client[0] if client else 'unknown'


def _client_rl_key(request: Request, category: str) -> str:
    if category == 'api':
        auth_hdr = request.headers.get('Authorization', '')
        if auth_hdr.startswith('Bearer '):
            token = auth_hdr[7:].strip()
            if token:
                return f"token:{token}"
    return f"ip:{_get_real_client_ip(request)}"


def _client_rl_check(bucket: str, window_seconds: int, max_requests: int) -> tuple:
    if max_requests <= 0:
        return True, 0
    now = time.time()
    cutoff = now - window_seconds
    with _client_rl_lock:
        ts = [t for t in _client_rl_state.get(bucket, []) if t > cutoff]
        if len(ts) >= max_requests:
            retry_after = int(ts[0] + window_seconds - now) + 1
            _client_rl_state[bucket] = ts
            return False, retry_after
        ts.append(now)
        _client_rl_state[bucket] = ts
        return True, 0


# ---------------------------------------------------------------------------
# Geo-blocking helpers
# ---------------------------------------------------------------------------
_LOCAL_IPS = {"127.0.0.1", "::1", "localhost"}
_BLOCK_MESSAGE = "We do not support the Israeli genocide of Palestinian people."


def _get_client_ip(request: Request) -> Optional[str]:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # Use rightmost IP (appended by the trusted upstream proxy) to prevent spoofing
        return xff.split(",")[-1].strip()
    client = request.scope.get("client")
    return client[0] if client else None


def _is_local_client(request: Request) -> bool:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip() in _LOCAL_IPS
    forwarded_host = request.headers.get("X-Forwarded-Host") or request.headers.get("X-Real-IP")
    if forwarded_host:
        host = forwarded_host.split(":")[0].strip()
        if host not in _LOCAL_IPS:
            return False
    ip = _get_client_ip(request)
    return ip in _LOCAL_IPS if ip else False


def _is_private_or_local_ip(ip: Optional[str]) -> bool:
    if not ip:
        return False
    if ip in _LOCAL_IPS:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any((
        addr.is_private,
        addr.is_loopback,
        addr.is_link_local,
        addr.is_reserved,
    ))


class GenocidalBlockingMiddleware(BaseHTTPMiddleware):
    """Block Israeli IPs/domains."""

    def __init__(self, app, server_ip_blocked_ref):
        super().__init__(app)
        self._server_ip_blocked_ref = server_ip_blocked_ref

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/dashboard/blocked":
            return await call_next(request)
        if await self._should_block(request):
            return self._block_response(request)
        return await call_next(request)

    async def _should_block(self, request: Request) -> bool:
        if self._server_ip_blocked_ref():
            return True
        host = request.headers.get("host", "").lower().split(":")[0]
        if host.endswith(".il"):
            return True
        from aisbf import geolocation
        client_ip = _get_client_ip(request)
        if client_ip and not _is_private_or_local_ip(client_ip):
            country = await geolocation.get_ip_country(client_ip)
            if country == 'IL':
                return True
        return False

    def _block_response(self, request: Request):
        from aisbf.app.templates import get_base_url
        path = request.url.path
        if path.startswith("/api") or path.startswith("/mcp"):
            return JSONResponse(status_code=403, content={"error": _BLOCK_MESSAGE})
        return RedirectResponse(url=f"{get_base_url(request)}/dashboard/blocked", status_code=302)


# ---------------------------------------------------------------------------
# Middleware factory functions (to be registered on the FastAPI app)
# ---------------------------------------------------------------------------
def make_api_token_authorization_middleware(get_server_config, get_db):
    async def api_token_authorization_middleware(request: Request, call_next):
        path = request.url.path
        server_config = get_server_config()

        if (path == "/" or path.startswith("/dashboard") or path.startswith("/auth/") or
                path.startswith("/api/admin") or path.startswith("/api/webhooks/") or
                path == "/favicon.ico" or path.startswith("/.well-known/")):
            return await call_next(request)

        if request.method == "GET" and path in ["/api/models", "/api/v1/models"]:
            return await call_next(request)

        if _is_coderai_registration_route(path):
            return await call_next(request)

        if not (server_config and server_config.get('auth_enabled', False)):
            return await call_next(request)

        is_global_token = getattr(request.state, 'is_global_token', False)
        user_id = getattr(request.state, 'user_id', None)

        if (path.startswith("/api/u/") or path.startswith("/mcp/u/") or
                path.startswith("/api/v1/u/") or path.startswith("/mcp/v1/u/")):
            if is_global_token:
                return JSONResponse(status_code=403, content={"error": "Global tokens cannot access user-specific endpoints."})
            path_parts = path.split('/')
            if len(path_parts) >= 4 and path_parts[2] == 'u':
                target_username = path_parts[3]
                if not user_id:
                    return JSONResponse(status_code=401, content={"error": "Authentication required."})
                db = get_db()
                authenticated_user = db.get_user_by_id(user_id)
                if not authenticated_user:
                    return JSONResponse(status_code=403, content={"error": "Invalid user token."})
                if authenticated_user['username'] != target_username:
                    return JSONResponse(status_code=403, content={"error": "You can only access your own user-specific endpoints."})
                token_scope = getattr(request.state, 'token_scope', 'both')
                is_mcp_path = path.startswith("/mcp/u/") or path.startswith("/mcp/v1/u/")
                if is_mcp_path and token_scope == 'api':
                    return JSONResponse(status_code=403, content={"error": "This token does not have MCP access."})
                if not is_mcp_path and token_scope == 'mcp':
                    return JSONResponse(status_code=403, content={"error": "This token does not have API access."})
        else:
            if not is_global_token:
                return JSONResponse(status_code=403, content={"error": "User tokens cannot access global endpoints."})

        return await call_next(request)
    return api_token_authorization_middleware


def make_auth_middleware(get_server_config, get_config, get_db, url_for_fn):
    async def auth_middleware(request: Request, call_next):
        server_config = get_server_config()
        config = get_config()

        if server_config and server_config.get('auth_enabled', False):
            if (request.url.path == "/" or request.url.path.startswith("/dashboard") or
                    request.url.path.startswith("/auth/") or
                    request.url.path.startswith("/api/webhooks/") or
                    request.url.path == "/favicon.ico" or
                    request.url.path.startswith("/.well-known/")):
                return await call_next(request)

            if request.url.path.startswith("/api/admin"):
                expires_at = request.session.get('expires_at')
                if (request.session.get('logged_in') and request.session.get('role') == 'admin' and
                        not (expires_at and int(time.time()) > expires_at)):
                    return await call_next(request)

            if request.url.path.startswith("/api/market"):
                expires_at = request.session.get('expires_at')
                if (request.session.get('logged_in') and
                        not (expires_at and int(time.time()) > expires_at)):
                    return await call_next(request)

            if request.method == "GET" and request.url.path in ["/api/models", "/api/v1/models"]:
                return await call_next(request)

            if _is_coderai_registration_route(request.url.path):
                return await call_next(request)

            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return JSONResponse(status_code=401, content={"error": "Missing or invalid Authorization header."})

            token = auth_header.replace('Bearer ', '')
            allowed_tokens = server_config.get('auth_tokens', [])
            _token_valid = False
            for _t in allowed_tokens:
                _token_valid |= _hmac.compare_digest(token, _t)
            if _token_valid:
                request.state.user_id = None
                request.state.token_id = None
                request.state.is_global_token = True
                request.state.token_scope = 'api'
                request.state.is_admin = True
            else:
                db = get_db()
                user_auth = db.authenticate_user_token(token)
                if user_auth:
                    request.state.user_id = user_auth['user_id']
                    request.state.token_id = user_auth['token_id']
                    request.state.is_global_token = False
                    request.state.token_scope = user_auth.get('scope', 'api')
                    request.state.is_admin = (user_auth.get('role') == 'admin')
                else:
                    return JSONResponse(status_code=403, content={"error": "Invalid authentication token"})
        else:
            request.state.user_id = None
            request.state.token_id = None
            request.state.is_global_token = False
            request.state.token_scope = 'both'

        if (request.url.path.startswith("/dashboard") and
                request.session.get('logged_in') and
                request.session.get('role') != 'admin'):

            require_verification = False
            if config and hasattr(config, 'aisbf') and hasattr(config.aisbf, 'signup'):
                require_verification = getattr(config.aisbf.signup, 'require_email_verification', False)

            user_id = request.session.get('user_id')
            if user_id and require_verification:
                try:
                    db = get_db()
                    current_user = db.get_user_by_id(user_id)
                    if current_user and current_user.get('email_verified') != request.session.get('email_verified'):
                        request.session.clear()
                        return RedirectResponse(url=url_for_fn(request, "/dashboard/login") + "?error=Session+expired", status_code=303)
                except Exception:
                    pass

            if user_id:
                try:
                    db = get_db()
                    if not db.get_user_by_id(user_id):
                        request.session.clear()
                        return RedirectResponse(url=url_for_fn(request, "/dashboard/login") + "?error=Account+deleted", status_code=303)
                except Exception:
                    pass

            if require_verification and not request.session.get('email_verified'):
                allowed_routes = ["/dashboard/verify", "/dashboard/resend-verification",
                                  "/dashboard/logout", "/dashboard/verify-email"]
                if not any(request.url.path == r or request.url.path == r + "/" for r in allowed_routes):
                    return RedirectResponse(url=url_for_fn(request, "/dashboard/verify"), status_code=303)

        return await call_next(request)
    return auth_middleware


def make_tier_limit_middleware(get_db, background_tasks_ref):
    async def tier_limit_middleware(request: Request, call_next):
        import asyncio as _asyncio
        if (request.url.path == "/" or request.url.path.startswith("/dashboard") or
                request.url.path == "/favicon.ico" or
                request.url.path.startswith("/.well-known/") or
                request.url.path.startswith("/mcp") or
                request.url.path.startswith("/auth/")):
            return await call_next(request)

        if request.method == "GET" and (request.url.path.endswith("/models") or request.url.path.endswith("/models/")):
            return await call_next(request)

        user_id = getattr(request.state, 'user_id', None)
        if not user_id:
            return await call_next(request)

        db = get_db()
        tier = db.get_user_tier(user_id)
        if not tier:
            return await call_next(request)

        subscription = db.get_user_subscription(user_id)
        if subscription:
            from datetime import datetime
            if subscription['expires_at'] and datetime.fromisoformat(subscription['expires_at']) < datetime.now():
                return JSONResponse(status_code=402, content={"error": "Subscription expired", "code": "subscription_expired"})

        usage = db.get_user_usage(user_id)

        def _check_limit(limit_val, current_val, label, code):
            if limit_val == 0:
                return JSONResponse(status_code=402, content={"error": f"{label} not permitted", "code": f"{code}_blocked"})
            if limit_val > 0 and current_val >= limit_val:
                return JSONResponse(status_code=429, content={"error": f"{label} limit exceeded", "limit": limit_val, "current": current_val, "code": f"{code}_exceeded"})
            return None

        r = _check_limit(tier['max_requests_per_day'], usage['requests_today'], "Daily request", "daily_limit")
        if r:
            return r
        r = _check_limit(tier['max_requests_per_month'], usage['requests_month'], "Monthly request", "monthly_limit")
        if r:
            return r

        response = await call_next(request)

        if request.method == "POST" and any(request.url.path.endswith(ep) for ep in (
            "/chat/completions", "/completions", "/embeddings",
            "/audio/transcriptions", "/audio/speech", "/images/generations"
        )):
            _t = _asyncio.create_task(db.increment_user_request_count(user_id))
            background_tasks_ref.add(_t)
            _t.add_done_callback(background_tasks_ref.discard)

        return response
    return tier_limit_middleware


def make_dashboard_context_middleware():
    async def dashboard_context_middleware(request: Request, call_next):
        if request.url.path.startswith("/dashboard") and 'session' in request.scope:
            is_cloud = (request.url.hostname == 'aisbf.cloud' or
                        request.url.hostname.endswith('.aisbf.cloud'))
            is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
            request.state.is_aisbf_cloud = is_cloud or is_onion
            try:
                from aisbf.database import DatabaseRegistry
                market_settings = DatabaseRegistry.get_config_database().get_market_settings()
                request.state.market_enabled = bool(market_settings.get('enabled'))
            except Exception:
                request.state.market_enabled = True
            if request.session.get('logged_in', False):
                request.state.welcome_shown = request.session.get('welcome_shown', False)
            else:
                request.state.welcome_shown = True
        response = await call_next(request)
        await _record_dashboard_visit_event(request, response)
        return response
    return dashboard_context_middleware


def make_client_rate_limiting_middleware(get_config):
    async def client_rate_limiting_middleware(request: Request, call_next):
        path = request.url.path
        if path in ('/health', '/favicon.ico') or path.startswith('/static/'):
            return await call_next(request)

        config = get_config()
        aisbf_conf = config.get_aisbf_config() if config else None
        rl_cfg = getattr(aisbf_conf, 'client_rate_limiting', None) if aisbf_conf else None
        if not rl_cfg or not rl_cfg.enabled:
            return await call_next(request)

        is_api_mcp = (path.startswith('/api/') or path.startswith('/mcp/') or
                      path in ('/v1/chat/completions', '/v1/models', '/api/models', '/api/v1/models'))
        category = 'api' if is_api_mcp else 'general'
        limit_cfg = rl_cfg.api if is_api_mcp else rl_cfg.general
        client_key = _client_rl_key(request, category)

        allowed, retry_after = _client_rl_check(f"{client_key}:{category}:min", 60, limit_cfg.requests_per_minute)
        if not allowed:
            return JSONResponse(status_code=429, content={"error": "Too many requests", "retry_after": retry_after},
                                headers={"Retry-After": str(retry_after)})

        allowed, retry_after = _client_rl_check(f"{client_key}:{category}:hour", 3600, limit_cfg.requests_per_hour)
        if not allowed:
            return JSONResponse(status_code=429, content={"error": "Too many requests", "retry_after": retry_after},
                                headers={"Retry-After": str(retry_after)})

        return await call_next(request)
    return client_rate_limiting_middleware
