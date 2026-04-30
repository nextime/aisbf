from fastapi import APIRouter, Request, Form, Query, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from typing import Optional
import logging, json, os, threading, time
from pathlib import Path
from aisbf.database import DatabaseRegistry
from aisbf.app.templates import url_for, get_base_url
from aisbf.routes.auth import require_dashboard_auth, require_api_auth, require_admin

router = APIRouter()
_config = None
_templates = None

def init(config, templates):
    global _config, _templates
    _config = config
    _templates = templates

logger = logging.getLogger(__name__)

import secrets

# Global storage for pending OAuth2 callbacks (for localhost flow)
_pending_oauth2_callbacks = {}
_oauth2_callback_server = None


@router.get("/dashboard/oauth2/callback")
@router.get("/dashboard/oauth2/callback/{user_id}/{provider}")
async def dashboard_oauth2_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    user_id: str = None,
    provider: str = None
):
    """Handle OAuth2 callback redirected from localhost or browser extension."""
    try:
        if error:
            logger.error(f"OAuth2 callback error: {error}")
            return HTMLResponse(content=f"<html><body><h1>Authentication Error</h1><p>Error: {error}</p><p><a href='/dashboard/providers'>Return to Dashboard</a></p></body></html>", status_code=400)

        if not code:
            return HTMLResponse(content="<html><body><h1>Authentication Error</h1><p>No authorization code received</p><p><a href='/dashboard/providers'>Return to Dashboard</a></p></body></html>", status_code=400)

        _pending_oauth2_callbacks[state] = {
            'code': code, 'state': state, 'error': error,
            'timestamp': time.time(), 'user_id': user_id, 'provider': provider
        }

        try:
            request.session['oauth2_code'] = code
            request.session['oauth2_state'] = state
            if user_id:
                request.session['oauth2_user_id'] = user_id
            if provider:
                request.session['oauth2_provider'] = provider
        except Exception:
            pass

        logger.info(f"OAuth2 callback received - User: {user_id}, Provider: {provider}, State: {state[:10] if state else 'None'}..., Code: {code[:10]}...")

        return HTMLResponse(content="""
            <html><head><title>Authentication Successful</title>
            <style>body{font-family:Arial,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;}.container{text-align:center;padding:40px;background:rgba(255,255,255,0.1);border-radius:10px;}</style>
            </head><body><div class="container"><h1>✓ Authentication Successful</h1><p>You can close this window and return to the dashboard.</p><p><a href="/dashboard/providers" style="color:#fff">Return to Dashboard</a></p></div>
            <script>setTimeout(()=>window.close(),3000);</script></body></html>
        """)

    except Exception as e:
        logger.error(f"Error handling OAuth2 callback: {e}")
        return HTMLResponse(content=f"<html><body><h1>Authentication Error</h1><p>Error: {str(e)}</p><p><a href='/dashboard/providers'>Return to Dashboard</a></p></body></html>", status_code=500)


def _start_localhost_callback_server():
    """Start a temporary HTTP server on port 54545 to catch OAuth2 callbacks."""
    global _oauth2_callback_server

    if _oauth2_callback_server is not None:
        logger.info("Localhost callback server already running")
        return

    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/callback':
                query_params = parse_qs(parsed.query)
                code = query_params.get('code', [None])[0]
                state = query_params.get('state', [None])[0]
                error = query_params.get('error', [None])[0]

                if state:
                    _pending_oauth2_callbacks[state] = {'code': code, 'state': state, 'error': error, 'timestamp': time.time()}
                _pending_oauth2_callbacks['latest'] = {'code': code, 'state': state, 'error': error, 'timestamp': time.time()}

                if error:
                    response_html = f"<html><body style='font-family:Arial;text-align:center;padding:50px;'><h1 style='color:#e74c3c;'>✗ Authentication Error</h1><p>Error: {error}</p><p>You can close this window.</p></body></html>"
                    self.send_response(400)
                else:
                    response_html = "<html><body style='font-family:Arial;text-align:center;padding:50px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;height:100vh;margin:0;display:flex;justify-content:center;align-items:center;'><div style='background:rgba(255,255,255,0.1);padding:40px;border-radius:10px;'><h1>✓ Authentication Successful</h1><p>You can close this window and return to the dashboard.</p></div><script>setTimeout(()=>window.close(),3000);</script></body></html>"
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

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(0.1)


def _stop_localhost_callback_server():
    """Stop the localhost callback server."""
    global _oauth2_callback_server
    if _oauth2_callback_server:
        _oauth2_callback_server.shutdown()
        _oauth2_callback_server = None
        logger.info("Stopped localhost OAuth2 callback server")


# Claude OAuth2 authentication endpoints

@router.post("/dashboard/claude/auth/start")
async def dashboard_claude_auth_start(request: Request):
    """Start Claude OAuth2 authentication flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.claude_credentials.json')

        if not provider_key:
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.claude import ClaudeAuth

        auth = ClaudeAuth(credentials_file=credentials_file, skip_initial_load=True)
        verifier, challenge = auth._generate_pkce()
        state = secrets.token_urlsafe(32)

        request.session['oauth2_verifier'] = verifier
        request.session['oauth2_state'] = state
        request.session['oauth2_provider'] = provider_key
        request.session['oauth2_credentials_file'] = credentials_file

        client_host = request.client.host if request.client else None
        is_local_access = client_host in ['127.0.0.1', '::1', 'localhost']
        request_host = request.headers.get('host', '').split(':')[0]
        is_localhost_request = request_host in ['127.0.0.1', 'localhost', '::1']
        has_proxy_headers = ('X-Forwarded-For' in request.headers or 'X-Forwarded-Host' in request.headers or 'X-Real-IP' in request.headers)
        use_extension = not (is_local_access or is_localhost_request) or has_proxy_headers

        if not use_extension:
            _start_localhost_callback_server()
            logger.info("Started localhost callback server for direct OAuth2 flow")

        auth_params = {
            "code": "true", "client_id": auth.CLIENT_ID, "response_type": "code",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "redirect_uri": auth.REDIRECT_URI,
            "scope": "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload",
            "state": state
        }
        auth_url = f"{auth.AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in auth_params.items())}"

        return JSONResponse({
            "success": True, "auth_url": auth_url, "use_extension": use_extension,
            "message": "Please complete authentication in the browser window" if use_extension else "Authentication will use direct localhost callback"
        })

    except Exception as e:
        logger.error(f"Error starting Claude auth: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/dashboard/claude/auth/complete")
async def dashboard_claude_auth_complete(request: Request):
    """Complete Claude OAuth2 authentication using the code from callback"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        state = request.session.get('oauth2_state')
        verifier = request.session.get('oauth2_verifier')
        credentials_file = request.session.get('oauth2_credentials_file', '~/.claude_credentials.json')
        code = request.session.get('oauth2_code')

        if not code and state and state in _pending_oauth2_callbacks:
            callback_data = _pending_oauth2_callbacks[state]
            if time.time() - callback_data.get('timestamp', 0) < 300:
                code = callback_data.get('code')
                if callback_data.get('error'):
                    return JSONResponse(status_code=400, content={"success": False, "error": f"OAuth2 error: {callback_data['error']}"})
                logger.info(f"Using code from global callback storage for state {state[:10]}...: {code[:10] if code else 'None'}...")

        if not code or not verifier:
            return JSONResponse(status_code=400, content={"success": False, "error": "No authorization code found. Please restart authentication."})

        from aisbf.auth.claude import ClaudeAuth

        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None

        save_callback = None
        if not is_config_admin:
            provider_key = request.session.get('oauth2_provider')

            def save_callback(creds):
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db and current_user_id and provider_key:
                        db.save_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='claude_oauth2', credentials=creds)
                        logger.info(f"ClaudeOAuth2: Saved credentials to database for user {current_user_id}")
                except Exception as e:
                    logger.error(f"ClaudeOAuth2: Failed to save credentials to database: {e}")
                    raise

        auth = ClaudeAuth(credentials_file=credentials_file, skip_initial_load=True, save_callback=save_callback)
        success = await auth.exchange_code_for_tokens(code, state, verifier)

        if success:
            if not is_config_admin:
                credentials_path = Path(credentials_file).expanduser()
                credentials_path.unlink(missing_ok=True)

            request.session.pop('oauth2_code', None)
            request.session.pop('oauth2_verifier', None)
            request.session.pop('oauth2_state', None)
            request.session.pop('oauth2_provider', None)
            request.session.pop('oauth2_credentials_file', None)
            if state:
                _pending_oauth2_callbacks.pop(state, None)

            return JSONResponse({"success": True, "message": "Authentication completed successfully"})
        else:
            return JSONResponse(status_code=400, content={"success": False, "error": "Token exchange failed. If you see rate_limit_error, please wait 1-2 minutes before trying again."})

    except Exception as e:
        logger.error(f"Error completing Claude auth: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/dashboard/claude/auth/callback-status")
async def dashboard_claude_auth_callback_status(request: Request):
    """Check if OAuth2 callback has been received (for localhost flow)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    expected_state = request.session.get('oauth2_state')

    if expected_state and expected_state in _pending_oauth2_callbacks:
        callback_data = _pending_oauth2_callbacks[expected_state]
        if time.time() - callback_data.get('timestamp', 0) < 300:
            if callback_data.get('error'):
                return JSONResponse({"received": True, "error": callback_data['error']})
            elif callback_data.get('code'):
                return JSONResponse({"received": True, "has_code": True})

    if request.session.get('oauth2_code'):
        return JSONResponse({"received": True, "has_code": True})

    now = time.time()
    stale_states = [k for k, v in _pending_oauth2_callbacks.items()
                    if k != 'latest' and now - v.get('timestamp', 0) > 600]
    for stale in stale_states:
        _pending_oauth2_callbacks.pop(stale, None)

    return JSONResponse({"received": False})


@router.post("/dashboard/claude/auth/status")
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
            return JSONResponse(status_code=400, content={"authenticated": False, "error": "Provider key is required"})

        from aisbf.auth.claude import ClaudeAuth

        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None

        if not is_config_admin:
            try:
                db = DatabaseRegistry.get_config_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='claude_oauth2')
                    if db_creds and db_creds.get('credentials'):
                        tokens = db_creds['credentials'].get('tokens', {})
                        if tokens.get('access_token'):
                            return JSONResponse({"authenticated": True, "email": db_creds['credentials'].get('email', 'unknown')})
            except Exception as e:
                logger.warning(f"ClaudeOAuth2: Failed to check database credentials: {e}")

        auth = ClaudeAuth(credentials_file=credentials_file)
        if auth.tokens:
            expires_at = auth.tokens.get('expires_at', 0)
            if time.time() < (expires_at - 300):
                return JSONResponse({"authenticated": True, "expires_in": expires_at - time.time()})
            else:
                if await auth.refresh_token():
                    return JSONResponse({"authenticated": True, "expires_in": auth.tokens.get('expires_at', 0) - time.time()})
                else:
                    return JSONResponse({"authenticated": False})
        else:
            return JSONResponse({"authenticated": False})

    except Exception as e:
        logger.error(f"Error checking Claude auth status: {e}")
        return JSONResponse(status_code=500, content={"authenticated": False, "error": str(e)})


# Kilo OAuth2 authentication endpoints

@router.post("/dashboard/kilo/auth/start")
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
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.kilo import KiloOAuth2

        auth = KiloOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        device_auth = await auth.initiate_device_auth()

        if not device_auth:
            return JSONResponse(status_code=500, content={"success": False, "error": "Failed to initiate device authorization"})

        request.session['kilo_device_code'] = device_auth['code']
        request.session['kilo_provider'] = provider_key
        request.session['kilo_credentials_file'] = credentials_file
        request.session['kilo_expires_at'] = time.time() + device_auth['expiresIn']

        return JSONResponse({
            "success": True, "user_code": device_auth['code'],
            "verification_uri": device_auth['verificationUrl'],
            "expires_in": device_auth['expiresIn'], "interval": 3,
            "message": f"Please visit {device_auth['verificationUrl']} and enter code: {device_auth['code']}"
        })

    except Exception as e:
        logger.error(f"Error starting Kilo auth: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/dashboard/kilo/auth/poll")
async def dashboard_kilo_auth_poll(request: Request):
    """Poll Kilo OAuth2 device authorization status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        device_code = request.session.get('kilo_device_code')
        credentials_file = request.session.get('kilo_credentials_file', '~/.kilo_credentials.json')
        expires_at = request.session.get('kilo_expires_at', 0)

        if not device_code:
            return JSONResponse(status_code=400, content={"success": False, "status": "error", "error": "No device authorization in progress"})

        if time.time() > expires_at:
            for k in ('kilo_device_code', 'kilo_provider', 'kilo_credentials_file', 'kilo_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": False, "status": "expired", "error": "Device authorization expired"})

        from aisbf.auth.kilo import KiloOAuth2

        auth = KiloOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        result = await auth.poll_device_auth(device_code)

        if result['status'] == 'approved':
            token = result.get('token')
            user_email = result.get('userEmail')
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None

            if token:
                credentials = {
                    "type": "oauth", "access": token, "refresh": token,
                    "expires": int(time.time()) + (365 * 24 * 60 * 60), "userEmail": user_email
                }
                if not is_config_admin:
                    try:
                        db = DatabaseRegistry.get_config_database()
                        provider_key = request.session.get('kilo_provider')
                        if db and current_user_id and provider_key:
                            db.save_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='kilo_oauth2', credentials=credentials)
                            logger.info(f"KiloOAuth2: Saved credentials to database for user {current_user_id}")
                    except Exception as e:
                        logger.error(f"KiloOAuth2: Failed to save credentials to database: {e}")
                else:
                    auth._save_credentials(credentials)
                    logger.info(f"KiloOAuth2: Saved credentials to file for {user_email}")

            for k in ('kilo_device_code', 'kilo_provider', 'kilo_credentials_file', 'kilo_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": True, "status": "completed", "message": "Authentication completed successfully"})

        elif result['status'] == 'pending':
            return JSONResponse({"success": True, "status": "pending", "message": "Waiting for user authorization"})
        elif result['status'] in ('denied', 'expired'):
            for k in ('kilo_device_code', 'kilo_provider', 'kilo_credentials_file', 'kilo_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": False, "status": result['status'], "error": f"User {result['status']} authorization"})
        elif result['status'] == 'slow_down':
            return JSONResponse({"success": True, "status": "slow_down", "message": "Polling too frequently, slowing down"})
        else:
            return JSONResponse({"success": False, "status": "error", "error": result.get('error', 'Unknown error')})

    except Exception as e:
        logger.error(f"Error polling Kilo auth: {e}")
        return JSONResponse(status_code=500, content={"success": False, "status": "error", "error": str(e)})


@router.post("/dashboard/kilo/auth/status")
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
            return JSONResponse(status_code=400, content={"authenticated": False, "error": "Provider key is required"})

        from aisbf.auth.kilo import KiloOAuth2

        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None

        if not is_config_admin:
            try:
                db = DatabaseRegistry.get_config_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='kilo_oauth2')
                    if db_creds and db_creds.get('credentials'):
                        creds = db_creds['credentials']
                        expires_at = creds.get('expires', 0)
                        if time.time() < expires_at:
                            return JSONResponse({"authenticated": True, "expires_in": max(0, expires_at - time.time()), "email": creds.get('userEmail', 'unknown')})
            except Exception as e:
                logger.warning(f"KiloOAuth2: Failed to check database credentials: {e}")

        auth = KiloOAuth2(credentials_file=credentials_file)
        if auth.is_authenticated():
            token = await auth.get_valid_token()
            if token:
                expires_at = auth.credentials.get('expires', 0)
                return JSONResponse({"authenticated": True, "expires_in": max(0, expires_at - time.time()), "email": auth.credentials.get('userEmail')})

        return JSONResponse({"authenticated": False})

    except Exception as e:
        logger.error(f"Error checking Kilo auth status: {e}")
        return JSONResponse(status_code=500, content={"authenticated": False, "error": str(e)})


@router.post("/dashboard/kilo/auth/logout")
async def dashboard_kilo_auth_logout(request: Request):
    """Logout from Kilo OAuth2"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.kilo_credentials.json')

        if not provider_key:
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.kilo import KiloOAuth2

        auth = KiloOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        auth.logout()
        return JSONResponse({"success": True, "message": "Logged out successfully"})

    except Exception as e:
        logger.error(f"Error logging out from Kilo: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# Codex OAuth2 authentication endpoints

@router.post("/dashboard/codex/auth/start")
async def dashboard_codex_auth_start(request: Request):
    """Start Codex OAuth2 Device Authorization Grant flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/codex_credentials.json')
        issuer = data.get('issuer', 'https://auth.openai.com')

        if not provider_key:
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.codex import CodexOAuth2

        auth = CodexOAuth2(credentials_file=credentials_file, issuer=issuer, skip_initial_load=True)
        device_info = await auth.request_device_code_flow()

        request.session['codex_device_auth_id'] = device_info.get('device_auth_id')
        request.session['codex_user_code'] = device_info.get('user_code')
        request.session['codex_provider'] = provider_key
        request.session['codex_credentials_file'] = credentials_file
        request.session['codex_issuer'] = issuer
        request.session['codex_expires_at'] = time.time() + device_info.get('expires_in', 900)

        return JSONResponse({
            "success": True, "user_code": device_info.get('user_code'),
            "verification_uri": device_info.get('verification_uri'),
            "expires_in": device_info.get('expires_in', 900),
            "interval": device_info.get('interval', 5),
            "message": f"Please visit {device_info.get('verification_uri')} and enter code: {device_info.get('user_code')}"
        })

    except Exception as e:
        logger.error(f"Error starting Codex auth: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/dashboard/codex/auth/poll")
async def dashboard_codex_auth_poll(request: Request):
    """Poll Codex OAuth2 device authorization status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        device_auth_id = request.session.get('codex_device_auth_id')
        user_code = request.session.get('codex_user_code')

        if not device_auth_id or not user_code:
            return JSONResponse({"success": False, "status": "error", "error": "No device authorization in progress. Please start authentication again."})

        expires_at = request.session.get('codex_expires_at', 0)
        if time.time() > expires_at:
            for k in ('codex_device_auth_id', 'codex_user_code', 'codex_provider', 'codex_credentials_file', 'codex_issuer', 'codex_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": False, "status": "expired", "error": "Device authorization expired"})

        credentials_file = request.session.get('codex_credentials_file', '~/.aisbf/codex_credentials.json')
        issuer = request.session.get('codex_issuer', 'https://auth.openai.com')

        from aisbf.auth.codex import CodexOAuth2

        auth = CodexOAuth2(credentials_file=credentials_file, issuer=issuer, skip_initial_load=True)
        auth._device_auth_id = device_auth_id
        auth._device_user_code = user_code

        result = await auth.poll_device_code_completion()

        if result['status'] == 'approved':
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None

            if not is_config_admin:
                try:
                    db = DatabaseRegistry.get_config_database()
                    provider_key = request.session.get('codex_provider')
                    if db and current_user_id and provider_key:
                        credentials_path = Path(credentials_file).expanduser()
                        if credentials_path.exists():
                            with open(credentials_path, 'r') as f:
                                db_credentials = json.load(f)
                            db.save_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='codex_oauth2', credentials=db_credentials)
                            logger.info(f"CodexOAuth2: Saved credentials to database for user {current_user_id}")
                            credentials_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"CodexOAuth2: Failed to save credentials to database: {e}")

            for k in ('codex_device_auth_id', 'codex_user_code', 'codex_provider', 'codex_credentials_file', 'codex_issuer', 'codex_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": True, "status": "approved", "message": "Authentication completed successfully", "new_endpoint": "https://chatgpt.com/backend-api/codex"})

        elif result['status'] == 'pending':
            return JSONResponse({"success": True, "status": "pending", "message": "Waiting for user authorization"})
        elif result['status'] in ('denied', 'expired'):
            for k in ('codex_device_auth_id', 'codex_user_code', 'codex_provider', 'codex_credentials_file', 'codex_issuer', 'codex_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": False, "status": result['status'], "error": f"User {result['status']} authorization"})
        else:
            return JSONResponse({"success": False, "status": "error", "error": result.get('error', 'Unknown error')})

    except Exception as e:
        logger.error(f"Error polling Codex auth: {e}")
        return JSONResponse(status_code=500, content={"success": False, "status": "error", "error": str(e)})


@router.post("/dashboard/codex/auth/status")
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
            return JSONResponse(status_code=400, content={"authenticated": False, "error": "Provider key is required"})

        from aisbf.auth.codex import CodexOAuth2

        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None

        if not is_config_admin:
            try:
                db = DatabaseRegistry.get_config_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='codex_oauth2')
                    if db_creds and db_creds.get('credentials'):
                        tokens = db_creds['credentials'].get('tokens', {})
                        if tokens.get('access_token'):
                            return JSONResponse({"authenticated": True, "email": db_creds['credentials'].get('email', 'unknown')})
            except Exception as e:
                logger.warning(f"CodexOAuth2: Failed to check database credentials: {e}")

        auth = CodexOAuth2(credentials_file=credentials_file)
        if auth.is_authenticated():
            token = await auth.get_valid_token_with_refresh()
            if token:
                return JSONResponse({"authenticated": True, "email": auth.get_user_email()})

        return JSONResponse({"authenticated": False})

    except Exception as e:
        logger.error(f"Error checking Codex auth status: {e}")
        return JSONResponse(status_code=500, content={"authenticated": False, "error": str(e)})


@router.post("/dashboard/codex/auth/logout")
async def dashboard_codex_auth_logout(request: Request):
    """Logout from Codex OAuth2"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/codex_credentials.json')

        if not provider_key:
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.codex import CodexOAuth2

        auth = CodexOAuth2(credentials_file=credentials_file)
        auth.logout()
        return JSONResponse({"success": True, "message": "Logged out successfully"})

    except Exception as e:
        logger.error(f"Error logging out from Codex: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# Qwen OAuth2 authentication endpoints

def _save_qwen_credentials(credentials_file: str, token_response: dict) -> None:
    """Save Qwen OAuth2 credentials to file"""
    from datetime import datetime as _dt
    try:
        expires_in = token_response.get("expires_in", 7200)
        expires_in_ms = max(expires_in * 1000, 3600000)

        credentials = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response.get("refresh_token"),
            "token_type": token_response.get("token_type", "Bearer"),
            "resource_url": token_response.get("resource_url"),
            "expiry_date": int(time.time() * 1000) + expires_in_ms,
            "last_refresh": _dt.utcnow().isoformat() + "Z",
        }

        cred_path = Path(credentials_file).expanduser()
        cred_path.parent.mkdir(parents=True, exist_ok=True)

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', dir=cred_path.parent, delete=False) as f:
            json.dump(credentials, f, indent=2)
            temp_path = f.name

        os.rename(temp_path, cred_path)
        os.chmod(cred_path, 0o600)
        logger.info(f"QwenOAuth2: Saved credentials to {credentials_file}")
    except Exception as e:
        logger.error(f"QwenOAuth2: Failed to save credentials: {e}")
        raise


@router.post("/dashboard/qwen/auth/start")
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
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.qwen import QwenOAuth2

        auth = QwenOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        logger.info(f"QwenOAuth2: Requesting device code for provider: {provider_key}")
        device_info = await auth.request_device_code()

        if not device_info:
            return JSONResponse(status_code=500, content={"success": False, "error": "Failed to initiate device authorization"})

        logger.info(f"QwenOAuth2: Device code obtained: {device_info.get('user_code')}")

        request.session['qwen_device_code'] = device_info['device_code']
        request.session['qwen_code_verifier'] = device_info['code_verifier']
        request.session['qwen_provider'] = provider_key
        request.session['qwen_credentials_file'] = credentials_file
        request.session['qwen_expires_at'] = time.time() + device_info['expires_in']

        return JSONResponse({
            "success": True, "user_code": device_info['user_code'],
            "verification_uri": device_info['verification_uri_complete'],
            "expires_in": device_info['expires_in'], "interval": device_info['interval'],
            "message": f"Please visit {device_info['verification_uri_complete']} and enter code: {device_info['user_code']}"
        })

    except Exception as e:
        logger.error(f"Error starting Qwen auth: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/dashboard/qwen/auth/poll")
async def dashboard_qwen_auth_poll(request: Request):
    """Poll Qwen OAuth2 device authorization status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        device_code = request.session.get('qwen_device_code')
        code_verifier = request.session.get('qwen_code_verifier')
        credentials_file = request.session.get('qwen_credentials_file', '~/.aisbf/qwen_credentials.json')
        expires_at = request.session.get('qwen_expires_at', 0)

        if not device_code:
            return JSONResponse(status_code=400, content={"success": False, "status": "error", "error": "No device authorization in progress"})

        if time.time() > expires_at:
            for k in ('qwen_device_code', 'qwen_code_verifier', 'qwen_provider', 'qwen_credentials_file', 'qwen_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": False, "status": "expired", "error": "Device authorization expired"})

        from aisbf.auth.qwen import QwenOAuth2

        auth = QwenOAuth2(credentials_file=credentials_file, skip_initial_load=True)
        result = await auth.poll_device_token(device_code, code_verifier)

        if result and result.get("access_token"):
            current_user_id = request.session.get('user_id')
            is_config_admin = current_user_id is None

            _save_qwen_credentials(credentials_file, result)

            if not is_config_admin:
                try:
                    db = DatabaseRegistry.get_config_database()
                    provider_key = request.session.get('qwen_provider')
                    if db and current_user_id and provider_key:
                        credentials_path = Path(credentials_file).expanduser()
                        if credentials_path.exists():
                            with open(credentials_path, 'r') as f:
                                db_credentials = json.load(f)
                            db.save_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='qwen_oauth2', credentials=db_credentials)
                            logger.info(f"QwenOAuth2: Saved credentials to database for user {current_user_id}")
                            credentials_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"QwenOAuth2: Failed to save credentials to database: {e}")

            for k in ('qwen_device_code', 'qwen_code_verifier', 'qwen_provider', 'qwen_credentials_file', 'qwen_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": True, "status": "completed", "message": "Authentication completed successfully"})

        elif result is None:
            return JSONResponse({"success": True, "status": "pending", "message": "Waiting for user authorization. Please approve the device on your Qwen account."})
        else:
            return JSONResponse({"success": True, "status": "pending", "message": "Waiting for user authorization"})

    except Exception as e:
        error_msg = str(e).lower()
        if "authorization_pending" in error_msg or "pending" in error_msg:
            return JSONResponse({"success": True, "status": "pending", "message": "Waiting for user authorization. Please approve the device on your Qwen account."})
        elif "slow_down" in error_msg or "429" in error_msg:
            return JSONResponse({"success": True, "status": "slow_down", "message": "Polling too frequently, slowing down"})
        elif "expired" in error_msg:
            for k in ('qwen_device_code', 'qwen_code_verifier', 'qwen_provider', 'qwen_credentials_file', 'qwen_expires_at'):
                request.session.pop(k, None)
            return JSONResponse({"success": False, "status": "expired", "error": "Device authorization expired"})
        else:
            logger.error(f"Error polling Qwen auth: {e}", exc_info=True)
            return JSONResponse(status_code=500, content={"success": False, "status": "error", "error": str(e)})


@router.post("/dashboard/qwen/auth/status")
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
            return JSONResponse(status_code=400, content={"authenticated": False, "error": "Provider key is required"})

        from aisbf.auth.qwen import QwenOAuth2

        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None

        if not is_config_admin:
            try:
                db = DatabaseRegistry.get_config_database()
                if db and current_user_id:
                    db_creds = db.get_user_oauth2_credentials(user_id=current_user_id, provider_id=provider_key, auth_type='qwen_oauth2')
                    if db_creds and db_creds.get('credentials'):
                        creds = db_creds['credentials']
                        access_token = creds.get('access_token')
                        expiry_date = creds.get('expiry_date', 0)
                        if access_token and time.time() * 1000 < expiry_date:
                            return JSONResponse({"authenticated": True, "expires_in": max(0, (expiry_date - int(time.time() * 1000)) / 1000)})
            except Exception as e:
                logger.warning(f"QwenOAuth2: Failed to check database credentials: {e}")

        auth = QwenOAuth2(credentials_file=credentials_file)
        if auth.is_authenticated():
            token = await auth.get_valid_token_with_refresh()
            if token:
                expiry_date = auth.credentials.get('expiry_date', 0)
                return JSONResponse({"authenticated": True, "expires_in": max(0, (expiry_date - int(time.time() * 1000)) / 1000)})

        return JSONResponse({"authenticated": False})

    except Exception as e:
        logger.error(f"Error checking Qwen auth status: {e}")
        return JSONResponse(status_code=500, content={"authenticated": False, "error": str(e)})


@router.post("/dashboard/qwen/auth/logout")
async def dashboard_qwen_auth_logout(request: Request):
    """Logout from Qwen OAuth2"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        data = await request.json()
        provider_key = data.get('provider_key')
        credentials_file = data.get('credentials_file', '~/.aisbf/qwen_credentials.json')

        if not provider_key:
            return JSONResponse(status_code=400, content={"success": False, "error": "Provider key is required"})

        from aisbf.auth.qwen import QwenOAuth2

        auth = QwenOAuth2(credentials_file=credentials_file)
        auth.clear_credentials()

        current_user_id = request.session.get('user_id')
        if current_user_id:
            try:
                db = DatabaseRegistry.get_config_database()
                if db:
                    db.delete_user_oauth2_credentials(current_user_id, provider_key, 'qwen_oauth2')
            except Exception as e:
                logger.warning(f"QwenOAuth2: Failed to clear database credentials: {e}")

        for k in ('qwen_device_code', 'qwen_code_verifier', 'qwen_provider', 'qwen_credentials_file', 'qwen_expires_at'):
            request.session.pop(k, None)

        return JSONResponse({"success": True, "message": "Logged out successfully"})

    except Exception as e:
        logger.error(f"Error logging out from Qwen: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/dashboard/extension/download")
async def dashboard_extension_download(request: Request):
    """Download the OAuth2 redirect extension as a ZIP file"""
    from fastapi.responses import FileResponse, Response
    import zipfile, io
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    try:
        extension_zip = Path(__file__).parent.parent.parent.parent / 'static' / 'aisbf-oauth2-extension.zip'
        if not extension_zip.exists():
            extension_dir = Path(__file__).parent.parent.parent.parent / 'static' / 'extension'
            if not extension_dir.exists():
                return JSONResponse(status_code=404, content={"error": "Extension files not found"})
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fp in extension_dir.rglob('*'):
                    if fp.is_file() and not fp.name.endswith('.sh'):
                        zf.write(fp, fp.relative_to(extension_dir))
            zip_buffer.seek(0)
            return Response(content=zip_buffer.getvalue(), media_type="application/zip",
                            headers={"Content-Disposition": "attachment; filename=aisbf-oauth2-extension.zip"})
        return FileResponse(path=extension_zip, media_type="application/zip",
                            filename="aisbf-oauth2-extension.zip")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/dashboard/welcome-shown")
async def dashboard_welcome_shown(request: Request):
    """Mark welcome modal as shown for this session"""
    if 'session' in request.scope:
        request.session['welcome_shown'] = True
    return JSONResponse({'success': True})


@router.get("/dashboard/tor/status")
async def dashboard_tor_status(request: Request):
    """Get Tor hidden service status"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    if request.session.get('role') != 'admin':
        return JSONResponse({'success': False, 'error': 'Admin access required'}, status_code=403)
    try:
        from aisbf.app.startup import get_aisbf_config_path
        config_path = get_aisbf_config_path()
        with open(config_path) as f:
            aisbf_config = json.load(f)
        tor_cfg = aisbf_config.get('tor', {})
        # tor_service lives in main.py app state
        from fastapi import Request as _Req
        tor_service = None
        try:
            import main as _main
            tor_service = _main._app_state.get('tor_service')
        except Exception:
            pass
        return JSONResponse({
            'enabled': bool(tor_cfg.get('enabled', False)),
            'running': tor_service is not None and tor_service.is_connected() if tor_service else False,
            'onion_address': tor_service.onion_address if tor_service and hasattr(tor_service, 'onion_address') else None
        })
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.post("/dashboard/contact")
async def dashboard_contact(request: Request):
    """Handle contact form submissions"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    is_authenticated = not require_dashboard_auth(request)
    try:
        data = await request.json()
        message_type = data.get('type')
        title = data.get('title')
        message = data.get('message')
        if not all([message_type, title, message]):
            return JSONResponse({'success': False, 'error': 'All fields are required'}, status_code=400)
        user_id = request.session.get('user_id')
        username = request.session.get('username', 'Unknown')
        email = request.session.get('email')
        if not is_authenticated:
            email = data.get('email', '').strip()
            if not email:
                return JSONResponse({'success': False, 'error': 'Email is required'}, status_code=400)
            username = 'Guest'
            user_id = None
        smtp_config = _config.aisbf.smtp if _config and _config.aisbf and hasattr(_config.aisbf, 'smtp') else None
        if not smtp_config or not smtp_config.enabled:
            return JSONResponse({'success': False, 'error': 'Email service is not configured'}, status_code=500)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[AISBF Contact] {message_type.upper()}: {title}"
        msg['From'] = f"{smtp_config.from_name} <{smtp_config.from_email}>"
        msg['To'] = "stefy@aisbf.cloud"
        if email:
            msg['Reply-To'] = email
        html = f"<h3>Contact Form</h3><p><b>Type:</b> {message_type}</p><p><b>Title:</b> {title}</p><p><b>User:</b> {username} ({user_id or 'guest'})</p><p><b>Email:</b> {email or 'N/A'}</p><pre>{message}</pre>"
        msg.attach(MIMEText(html, 'html'))
        if smtp_config.use_ssl:
            with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port) as s:
                if smtp_config.username:
                    s.login(smtp_config.username, smtp_config.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(smtp_config.host, smtp_config.port) as s:
                s.ehlo()
                if smtp_config.use_tls:
                    s.starttls(); s.ehlo()
                if smtp_config.username:
                    s.login(smtp_config.username, smtp_config.password)
                s.send_message(msg)
        return JSONResponse({'success': True})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)
