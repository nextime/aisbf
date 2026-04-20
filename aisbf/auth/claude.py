"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Claude OAuth2 authentication handler for AISBF.

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
"""
import os
import json
import secrets
import hashlib
import base64
import webbrowser
import time
import asyncio
import httpx
from pathlib import Path
from typing import Optional, Dict
from flask import Flask, request
import threading
import logging

# Try to import curl_cffi for TLS fingerprinting (optional)
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# Configuration matching the official Claude CLI
# Try to load client_id from credentials file first, fallback to generated UUID
import json
import os
from pathlib import Path

def _load_client_id_from_credentials():
    """Attempt to load client_id from existing Claude credentials file"""
    try:
        creds_path = Path.home() / ".claude" / ".credentials.json"
        if creds_path.exists():
            with open(creds_path, 'r') as f:
                creds = json.load(f)
                # Try to extract client_id from various possible locations
                if 'client_id' in creds:
                    return creds['client_id']
                elif 'oauth' in creds and 'client_id' in creds['oauth']:
                    return creds['oauth']['client_id']
                elif 'claudeAiOauth' in creds and 'client_id' in creds['claudeAiOauth']:
                    return creds['claudeAiOauth']['client_id']
    except Exception:
        pass
    return None

def _generate_client_id():
    """Generate a stable client_id UUID based on machine characteristics"""
    # Use machine hostname and platform to generate a stable UUID
    import uuid
    import platform
    machine_id = f"{platform.node()}-{platform.machine()}-claude-code"
    # Generate UUID5 (name-based) from the machine ID
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, machine_id))

# Claude OAuth2 Configuration
# These values match the official claude-cli implementation
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # Official Claude Code client ID
AUTH_URL = "https://claude.com/cai/oauth/authorize"  # Authorization endpoint (note: /cai path is required)
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"  # Token exchange endpoint
DEFAULT_REDIRECT_URI = "http://localhost:54545/callback"  # Default local OAuth2 callback URI
CLI_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

logger = logging.getLogger(__name__)


class ClaudeAuth:
    """
    OAuth2 authentication handler for Claude Code.
    
    Implements the full OAuth2 PKCE flow used by the official claude-cli,
    including token refresh and automatic re-authentication.
    """
    
    # Class-level constants
    CLIENT_ID = CLIENT_ID
    AUTH_URL = AUTH_URL
    TOKEN_URL = TOKEN_URL
    REDIRECT_URI = DEFAULT_REDIRECT_URI
    CLI_USER_AGENT = CLI_USER_AGENT
    
    def __init__(self, credentials_file: Optional[str] = None, redirect_uri: Optional[str] = None, skip_initial_load: bool = False, save_callback: Optional[callable] = None):
        """
        Initialize Claude authentication.

        Args:
            credentials_file: Path to credentials file (default: ~/.aisbf/claude_credentials.json)
            skip_initial_load: If True, do not load credentials from file on initialization
            save_callback: Optional callback to save credentials instead of writing to file
        """
        if credentials_file:
            self.credentials_file = Path(credentials_file).expanduser()
        else:
            # Store credentials in ~/.aisbf/ directory (AISBF config directory)
            self.credentials_file = Path.home() / ".aisbf" / "claude_credentials.json"

        # Allow overriding redirect URI for reverse proxy deployments
        self.redirect_uri = redirect_uri if redirect_uri is not None else DEFAULT_REDIRECT_URI

        self.tokens = None
        self._save_callback = save_callback
        if not skip_initial_load:
            self.tokens = self._load_credentials()
        self._oauth_state = None  # Store state for OAuth flow
        self._code_verifier = None  # Store verifier for OAuth flow

        # Log TLS fingerprinting capability
        if HAS_CURL_CFFI:
            logger.info(f"ClaudeAuth initialized with TLS fingerprinting (curl_cffi) - credentials: {self.credentials_file}")
        else:
            logger.warning(f"ClaudeAuth initialized without TLS fingerprinting (curl_cffi not available) - credentials: {self.credentials_file}")
            logger.warning("Install curl_cffi for better Cloudflare bypass: pip install curl_cffi")
    
    def _load_credentials(self) -> Optional[Dict]:
        """Load credentials from file if they exist."""
        if self.credentials_file.exists():
            try:
                with open(self.credentials_file, 'r') as f:
                    tokens = json.load(f)
                logger.info("Loaded existing Claude credentials")
                return tokens
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")
                return None
        return None
    
    def _save_credentials(self, data: Dict):
        """
        Save credentials:
        - If save_callback is provided, use it (database save for user providers)
        - Otherwise, save to file with file locking to prevent race conditions
        """
        self.tokens = data
        
        if self._save_callback:
            # User provider: ONLY use callback, NO file fallback EVER
            try:
                self._save_callback({'tokens': data})
                logger.info("ClaudeAuth: Saved credentials via callback")
                return
            except Exception as e:
                logger.error(f"ClaudeAuth: Failed to save credentials to database: {e}")
                # DO NOT FALLBACK TO FILE SAVE FOR REGULAR USERS
                raise
        
        # Admin/global provider ONLY: save to file
        try:
            self.tokens = data
            # Store id_token if received (contains account info)
            if 'id_token' in data:
                self.tokens['id_token'] = data['id_token']
            # Add local expiry timestamp for easier checking
            self.tokens['expires_at'] = time.time() + data.get('expires_in', 3600)
            
            # Ensure directory exists
            self.credentials_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Use file locking to prevent race conditions with CLI
            import fcntl
            with open(self.credentials_file, 'w') as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    json.dump(self.tokens, f, indent=2)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except (IOError, OSError):
                    # If locking fails, write anyway (Windows compatibility)
                    json.dump(self.tokens, f, indent=2)
            
            # Set file permissions to 600 (owner read/write only)
            os.chmod(self.credentials_file, 0o600)
            
            logger.info(f"Saved Claude credentials to {self.credentials_file}")
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            raise
    
    def _generate_pkce(self):
        """Generate PKCE code verifier and challenge."""
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().replace('=', '')
        return verifier, challenge
    
    def _make_request(self, method: str, url: str, headers: Dict, json_data: Dict = None, timeout: float = 30.0):
        """
        Make HTTP request with TLS fingerprinting when available.
        
        Uses curl_cffi with Chrome impersonation to bypass Cloudflare's TLS fingerprinting,
        matching CLIProxyAPI's utls implementation. Falls back to httpx if curl_cffi is not available.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            headers: Request headers
            json_data: JSON body data
            timeout: Request timeout in seconds
            
        Returns:
            Response object with status_code, text, and json() method
        """
        if HAS_CURL_CFFI:
            # Use curl_cffi with Chrome impersonation (matches CLIProxyAPI's Chrome fingerprint)
            try:
                response = curl_requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=timeout,
                    impersonate="chrome120"  # Chrome 120 fingerprint
                )
                return response
            except Exception as e:
                logger.warning(f"curl_cffi request failed, falling back to httpx: {e}")
                # Fall through to httpx
        
        # Fallback to httpx (standard TLS)
        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            timeout=timeout
        )
        return response
    
    async def refresh_token(self, max_retries: int = 3) -> bool:
        """
        Use the refresh token to get a new access token without logging in.
        
        Args:
            max_retries: Maximum number of retry attempts for rate limits
            
        Returns:
            True if refresh was successful, False otherwise
        """
        import time
        
        if not self.tokens or 'refresh_token' not in self.tokens:
            logger.warning("No refresh token available")
            return False
        
        logger.info("Refreshing Claude access token...")
        
        for attempt in range(max_retries):
            try:
                # Claude's token endpoint expects JSON (not form-encoded like standard OAuth2)
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": CLI_USER_AGENT
                }
                
                response = self._make_request(
                    method="POST",
                    url=TOKEN_URL,
                    headers=headers,
                    json_data={
                        "grant_type": "refresh_token",
                        "client_id": CLIENT_ID,
                        "refresh_token": self.tokens['refresh_token']
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    self._save_credentials(response.json())
                    logger.info("Successfully refreshed access token")
                    return True
                elif response.status_code == 429:
                    # Rate limited - wait and retry with exponential backoff
                    wait_time = (2 ** attempt) * 5  # 5, 10, 20 seconds
                    logger.warning(f"Rate limited (429). Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                    return False
            except Exception as e:
                logger.error(f"Token refresh error: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                return False
        
        logger.error(f"Token refresh failed after {max_retries} attempts")
        return False
    
    async def get_valid_token(self, auto_login: bool = False) -> str:
        """
        Get a valid access token, refreshing it if necessary.
        
        Args:
            auto_login: If True, automatically trigger login flow when no credentials exist.
                       If False, raise an exception instead (default: False for security).
        
        Returns:
            Valid access token
            
        Raises:
            Exception: If no credentials exist and auto_login is False
        """
        if not self.tokens:
            if not auto_login:
                logger.error("No Claude credentials available. Please authenticate via dashboard or MCP.")
                raise Exception("Claude authentication required. Please authenticate via /dashboard/claude/auth/start or MCP tool.")
            logger.info("No tokens available, starting login flow")
            self.login()
        
        # Refresh if less than 5 minutes remain
        if time.time() > (self.tokens.get('expires_at', 0) - 300):
            logger.info("Token expiring soon, refreshing...")
            if not await self.refresh_token():
                if not auto_login:
                    logger.error("Token refresh failed and auto_login is disabled")
                    raise Exception("Claude token refresh failed. Please re-authenticate via /dashboard/claude/auth/start or MCP tool.")
                logger.warning("Refresh failed, re-authenticating...")
                self.login()
        
        return self.tokens['access_token']

    def get_account_id(self) -> Optional[str]:
        """
        Get account_id from OAuth2 credentials.
        
        Returns:
            Account ID if available, None otherwise
        """
        if not self.tokens:
            return None
        
        # First check for account.uuid in token response (Claude OAuth2 format)
        account = self.tokens.get('account')
        if account and isinstance(account, dict):
            account_uuid = account.get('uuid')
            if account_uuid:
                return account_uuid
        
        # Then try to get from id_token (JWT claim)
        id_token = self.tokens.get('id_token')
        if id_token:
            try:
                import base64
                import json
                # Decode JWT payload (second part of JWT)
                parts = id_token.split('.')
                if len(parts) >= 2:
                    # Add padding if needed
                    payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    claims = json.loads(decoded)
                    # Try sub claim first, then account_id
                    return claims.get('sub') or claims.get('account_id')
            except Exception:
                pass
        
        # Fall back to direct account_id field in token response
        return self.tokens.get('account_id') or self.tokens.get('account_uuid')
    
    def login(self, use_local_server=True):
        """
        Start a local server and open browser for the full OAuth2 flow.
        
        This implements the PKCE flow used by claude-cli:
        1. Generate PKCE verifier and challenge
        2. Generate state parameter for CSRF protection
        3. Start local callback server (if use_local_server=True)
        4. Open browser to authorization URL
        5. Wait for callback with authorization code
        6. Exchange code for tokens
        
        Args:
            use_local_server: If True, starts a local Flask server for callback.
                            If False, expects external handling of the callback.
        """
        logger.info("Starting Claude OAuth2 login flow...")
        
        verifier, challenge = self._generate_pkce()
        state = secrets.token_urlsafe(16)  # Generate random state for CSRF protection
        
        # Store state and verifier for later use
        self._oauth_state = state
        self._code_verifier = verifier
        
        if not use_local_server:
            # Return the auth URL and verifier for external handling
            auth_params = {
                "code": "true",
                "client_id": CLIENT_ID,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state
            }
            url = f"{AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in auth_params.items())}"
            return {
                'auth_url': url,
                'verifier': verifier,
                'challenge': challenge,
                'state': state
            }
        
        # Create Flask app for callback
        app = Flask(__name__)
        app.logger.disabled = True  # Disable Flask logging
        
        # Store the authorization code
        auth_code = {'code': None, 'error': None}
        
        @app.route('/callback')
        def callback():
            code = request.args.get('code')
            error = request.args.get('error')
            callback_state = request.args.get('state')
            
            if error:
                auth_code['error'] = error
                logger.error(f"OAuth error: {error}")
                return f"Authentication failed: {error}. You can close this window.", 400
            
            # Verify state parameter to prevent CSRF
            if callback_state != state:
                auth_code['error'] = 'state_mismatch'
                logger.error(f"State mismatch: expected {state}, got {callback_state}")
                return "Authentication failed: state mismatch. You can close this window.", 400
            
            if code:
                auth_code['code'] = code
                logger.info("Received authorization code")
                
                # Exchange code for tokens
                try:
                    # Parse code - it might have state appended with #
                    code_parts = code.split('#')
                    parsed_code = code_parts[0]
                    parsed_state = code_parts[1] if len(code_parts) > 1 else None
                    
                    # Claude's token endpoint expects JSON (not form-encoded like standard OAuth2)
                    headers = {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": CLI_USER_AGENT
                    }
                    
                    # Build token request matching CLIProxyAPI exactly:
                    # 1. Start with provided state
                    # 2. Override with parsed state if present
                    token_request = {
                        "code": parsed_code,
                        "state": state,
                        "grant_type": "authorization_code",
                        "client_id": CLIENT_ID,
                        "redirect_uri": self.redirect_uri,
                        "code_verifier": verifier
                    }
                    
                    # Override state if parsed from code (matching CLIProxyAPI lines 149-151)
                    if parsed_state:
                        token_request["state"] = parsed_state
                    
                    # Log the request (hide sensitive data)
                    safe_request = {k: v if k not in ['code', 'code_verifier'] else '***' for k, v in token_request.items()}
                    logger.info(f"Token exchange request: {safe_request}")
                    logger.debug(f"Token exchange full request: {token_request}")
                    
                    response = self._make_request(
                        method="POST",
                        url=TOKEN_URL,
                        headers=headers,
                        json_data=token_request,
                        timeout=30.0
                    )
                    
                    logger.info(f"Token exchange response status: {response.status_code}")
                    if response.status_code != 200:
                        logger.error(f"Token exchange response body: {response.text}")
                    
                    if response.status_code == 200:
                        self._save_credentials(response.json())
                        logger.info("Successfully obtained access token")
                        return "Authenticated! You can close this window."
                    else:
                        logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                        return f"Token exchange failed: {response.status_code}. You can close this window.", 400
                except Exception as e:
                    logger.error(f"Token exchange error: {e}")
                    return f"Token exchange error: {e}. You can close this window.", 500
            
            return "No authorization code received. You can close this window.", 400
        
        # Build authorization URL
        # Claude OAuth2 scopes for full access
        # Note: "code": "true" is required by Claude's OAuth implementation
        auth_params = {
            "code": "true",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state
        }
        url = f"{AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in auth_params.items())}"
        
        logger.info(f"Opening browser for authentication: {url}")
        print(f"\n{'='*80}")
        print(f"Claude Authentication Required")
        print(f"{'='*80}")
        print(f"\nPlease log in at: {url}")
        print(f"\nYour browser should open automatically.")
        print(f"If it doesn't, please copy and paste the URL above into your browser.")
        print(f"\n{'='*80}\n")
        
        # Open browser
        webbrowser.open(url)
        
        # Run Flask server in a separate thread with timeout
        def run_server():
            app.run(port=54545, debug=False, use_reloader=False)
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        
        # Wait for callback (with timeout)
        timeout = 300  # 5 minutes
        start_time = time.time()
        
        while auth_code['code'] is None and auth_code['error'] is None:
            if time.time() - start_time > timeout:
                logger.error("Authentication timeout")
                raise TimeoutError("Authentication timeout after 5 minutes")
            time.sleep(0.5)
        
        if auth_code['error']:
            raise Exception(f"Authentication failed: {auth_code['error']}")
        
        logger.info("OAuth2 login flow completed successfully")
    
    async def exchange_code_for_tokens(self, code: str, state: str, verifier: str = None, max_retries: int = 3) -> bool:
        """
        Exchange authorization code for access tokens.
        Matches CLIProxyAPI implementation exactly.
        
        Args:
            code: Authorization code from OAuth2 callback
            state: State parameter for CSRF protection (REQUIRED)
            verifier: PKCE code verifier (uses stored verifier if not provided)
            max_retries: Maximum number of retry attempts for rate limits
            
        Returns:
            True if successful, False otherwise
        """
        import time
        
        # Use stored verifier if not provided
        if verifier is None:
            verifier = self._code_verifier
        
        if not verifier:
            raise ValueError("No code verifier available")
        
        if not state:
            raise ValueError("State parameter is required for token exchange")
        
        for attempt in range(max_retries):
            try:
                # Claude's token endpoint expects JSON (not form-encoded like standard OAuth2)
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": CLI_USER_AGENT
                }
                
                # Parse code - it might have state appended with # (matching CLIProxyAPI parseCodeAndState)
                code_parts = code.split('#')
                parsed_code = code_parts[0]
                parsed_state = code_parts[1] if len(code_parts) > 1 else ""
                
                # Build token request matching CLIProxyAPI exactly:
                # 1. Start with provided state
                # 2. Override with parsed state if present
                token_request = {
                    "code": parsed_code,
                    "state": state,
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": verifier
                }
                
                # Override state if parsed from code (matching CLIProxyAPI lines 149-151)
                if parsed_state != "":
                    token_request["state"] = parsed_state
                
                # Log the request (hide sensitive data)
                safe_request = {k: v if k not in ['code', 'code_verifier'] else '***' for k, v in token_request.items()}
                logger.info(f"Token exchange request: {safe_request}")
                logger.debug(f"Token exchange full request: {token_request}")
                
                response = self._make_request(
                    method="POST",
                    url=TOKEN_URL,
                    headers=headers,
                    json_data=token_request,
                    timeout=30.0
                )
                
                logger.info(f"Token exchange response status: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Token exchange response body: {response.text}")
                
                if response.status_code == 200:
                    self._save_credentials(response.json())
                    logger.info("Successfully exchanged code for tokens")
                    return True
                elif response.status_code == 429:
                    # Rate limited - wait and retry with exponential backoff
                    wait_time = (2 ** attempt) * 5  # 5, 10, 20 seconds
                    logger.warning(f"Rate limited (429). Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                    return False
            except Exception as e:
                logger.error(f"Token exchange error: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                return False
        
        logger.error(f"Token exchange failed after {max_retries} attempts")
        return False
    
    def is_authenticated(self) -> bool:
        """Check if we have valid credentials."""
        return self.tokens is not None and 'access_token' in self.tokens
    
    def clear_credentials(self):
        """Clear stored credentials."""
        if self.credentials_file.exists():
            self.credentials_file.unlink()
            logger.info("Cleared Claude credentials")
        self.tokens = None


# Example usage
if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)

    async def main():
        auth = ClaudeAuth()
        token = auth.get_valid_token()

        # Use the token for an API call
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "claude-code-20250219",  # Required for subscription usage
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-3-7-sonnet-20250219",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": "How's the weather in the CLI today?"}]
                }
            )
            print(response.json())

    asyncio.run(main())
