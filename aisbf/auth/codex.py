"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

OAuth2 Device Authorization Grant implementation for Codex (OpenAI).

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

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

# Codex OAuth2 Constants (from codex-oauth-implementation-guide.md)
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_ISSUER = "https://auth.openai.com"
DEFAULT_PORT = 1455
# IMPORTANT: Scopes must match the codex-cli implementation guide
SCOPES = "openid profile email offline_access api.connectors.read api.connectors.invoke"


class CodexOAuth2:
    """
    OAuth2 Device Authorization Grant implementation for Codex (OpenAI).
    
    Implements RFC 8628 device authorization flow for CLI/desktop applications.
    Supports authentication with OpenAI's Codex OAuth2 endpoints.
    """
    
    def __init__(self, credentials_file: Optional[str] = None, issuer: Optional[str] = None, skip_initial_load: bool = False, save_callback: Optional[callable] = None):
        """
        Initialize Codex OAuth2 client.

        Args:
            credentials_file: Path to credentials JSON file (default: ~/.aisbf/codex_credentials.json)
            issuer: OAuth2 issuer URL (default: https://auth.openai.com)
            skip_initial_load: If True, do not load credentials from file on initialization
            save_callback: Optional callback to save credentials instead of writing to file
        """
        # Expand and resolve path immediately to absolute path
        default_path = os.path.expanduser("~/.aisbf/codex_credentials.json")
        if credentials_file:
            # Expand user directory and convert to absolute path
            expanded = os.path.expanduser(credentials_file)
            # If still relative, make it absolute
            self.credentials_file = os.path.abspath(expanded)
        else:
            self.credentials_file = default_path

        self.issuer = (issuer or DEFAULT_ISSUER).rstrip("/")
        self.credentials = None
        self._save_callback = save_callback
        if not skip_initial_load:
            self._load_credentials()
    
    def _load_credentials(self) -> None:
        """Load credentials from file if it exists."""
        if os.path.exists(self.credentials_file):
            try:
                with open(self.credentials_file, 'r') as f:
                    self.credentials = json.load(f)
                logger.info(f"CodexOAuth2: Loaded credentials from {self.credentials_file}")
            except Exception as e:
                logger.warning(f"CodexOAuth2: Failed to load credentials: {e}")
                self.credentials = None
    
    def _save_credentials(self, credentials: Dict[str, Any]) -> None:
        """
        Save credentials:
        - If save_callback is provided, use it (database save for user providers)
        - Otherwise, save to file with secure permissions (admin/global providers)

        Args:
            credentials: Credentials dict to save
        """
        self.credentials = credentials
        
        if self._save_callback:
            # User provider: ONLY use callback, NO file fallback EVER
            try:
                self._save_callback(credentials)
                logger.info(f"CodexOAuth2: Saved credentials via callback")
                return
            except Exception as e:
                logger.error(f"CodexOAuth2: Failed to save credentials to database: {e}")
                # DO NOT FALLBACK TO FILE SAVE FOR REGULAR USERS
                raise
        
        # Admin/global provider ONLY: save to file
        try:
            # Path is already expanded and absolute from __init__
            resolved_path = self.credentials_file
            
            logger.debug(f"CodexOAuth2: Saving credentials to resolved path: {resolved_path}")
            
            # Ensure parent directory exists
            parent_dir = os.path.dirname(resolved_path)
            if parent_dir:
                logger.debug(f"CodexOAuth2: Creating parent directory: {parent_dir}")
                os.makedirs(parent_dir, exist_ok=True)
                # Secure directory permissions
                try:
                    os.chmod(parent_dir, 0o700)
                    logger.debug(f"CodexOAuth2: Set directory permissions to 0o700")
                except Exception as e:
                    logger.debug(f"CodexOAuth2: Could not set directory permissions: {e}")

            # Write credentials safely
            logger.debug(f"CodexOAuth2: Writing credentials to file")
            with open(resolved_path, 'w') as f:
                json.dump(credentials, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            logger.debug(f"CodexOAuth2: File written successfully")

            # Set file permissions to 0o600 (user read/write only)
            try:
                os.chmod(resolved_path, 0o600)
                logger.debug(f"CodexOAuth2: Set file permissions to 0o600")
            except Exception as e:
                logger.debug(f"CodexOAuth2: Could not set file permissions: {e}")

            # Verify file was created
            if os.path.exists(resolved_path):
                file_size = os.path.getsize(resolved_path)
                logger.info(f"CodexOAuth2: Saved credentials to {resolved_path} ({file_size} bytes)")
            else:
                logger.error(f"CodexOAuth2: File was not created at {resolved_path}")
                raise IOError(f"Failed to create credentials file at {resolved_path}")

            self.credentials = credentials
        except Exception as e:
            logger.error(f"CodexOAuth2: Failed to save credentials to {self.credentials_file}: {e}", exc_info=True)
            raise
    
    @staticmethod
    def generate_pkce() -> tuple:
        """Generate PKCE code verifier and challenge."""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b'=').decode()
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode()
        return code_verifier, code_challenge
    
    @staticmethod
    def generate_state() -> str:
        """Generate CSRF state parameter."""
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    
    def build_authorization_url(
        self,
        redirect_uri: str,
        code_challenge: str,
        state: str,
        workspace_id: Optional[str] = None,
    ) -> str:
        """Build the OAuth authorization URL."""
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": "codex_cli",
        }
        if workspace_id:
            params["allowed_workspace_id"] = workspace_id
        
        query = urllib.parse.urlencode(params)
        return f"{self.issuer}/oauth/authorize?{query}"
    
    async def exchange_code_for_tokens(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict:
        """Exchange authorization code for tokens."""
        token_url = f"{self.issuer}/oauth/token"
        
        body = (
            f"grant_type=authorization_code"
            f"&code={urllib.parse.quote(code)}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&client_id={urllib.parse.quote(CLIENT_ID)}"
            f"&code_verifier={urllib.parse.quote(code_verifier)}"
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=body,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def refresh_tokens(self, refresh_token: str) -> dict:
        """Refresh tokens using the refresh token."""
        token_url = f"{self.issuer}/oauth/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                headers={"Content-Type": "application/json"},
                json={
                    "client_id": CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30.0
            )
            
            if response.status_code == 401:
                body = response.json()
                error = body.get("error", {})
                error_code = error.get("code", "unknown") if isinstance(error, dict) else str(error)
                
                messages = {
                    "refresh_token_expired": "Your refresh token has expired. Please log out and sign in again.",
                    "refresh_token_reused": "Your refresh token was already used. Please log out and sign in again.",
                    "refresh_token_invalidated": "Your refresh token was revoked. Please log out and sign in again.",
                }
                raise Exception(messages.get(error_code, "Your access token could not be refreshed. Please log out and sign in again."))
            
            response.raise_for_status()
            return response.json()
    
    async def obtain_api_key(self, id_token: str) -> str:
        """Exchange ID token for an OpenAI API key."""
        token_url = f"{self.issuer}/oauth/token"
        
        body = (
            f"grant_type={urllib.parse.quote('urn:ietf:params:oauth:grant-type:token-exchange')}"
            f"&client_id={urllib.parse.quote(CLIENT_ID)}"
            f"&requested_token={urllib.parse.quote('openai-api-key')}"
            f"&subject_token={urllib.parse.quote(id_token)}"
            f"&subject_token_type={urllib.parse.quote('urn:ietf:params:oauth:token-type:id_token')}"
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=body,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()["access_token"]
    
    async def request_device_code(self) -> dict:
        """Request a device code for headless login."""
        url = f"{self.issuer}/api/accounts/deviceauth/usercode"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={"client_id": CLIENT_ID},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def poll_device_code_token(
        self,
        device_auth_id: str,
        user_code: str,
        interval: int = 5,
    ) -> dict:
        """
        Poll for device code token once (non-blocking).
        
        Returns:
            Dict with token response on success
            
        Raises:
            Exception on non-403/404 errors
        """
        url = f"{self.issuer}/api/accounts/deviceauth/token"
        
        # Include client_id to properly identify the application
        payload = {
            "client_id": CLIENT_ID,
            "device_auth_id": device_auth_id,
            "user_code": user_code,
        }
        
        logger.debug(f"CodexOAuth2: Polling token endpoint - URL: {url}, Payload: {payload}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30.0
            )
            
            logger.debug(f"CodexOAuth2: Poll response - Status: {response.status_code}, Body: {response.text[:500]}")
            
            if response.status_code == 200:
                return response.json()
            
            # 403/404 means still pending - re-raise for caller to handle
            if response.status_code in (403, 404):
                raise Exception(f"Authorization pending (status {response.status_code})")
            
            raise Exception(f"Device auth failed with status {response.status_code}: {response.text}")
    
    async def request_device_code_flow(self) -> Dict[str, Any]:
        """
        Start device authorization flow - returns immediately with verification info.
        
        Returns:
            Dict with verification_uri, user_code, expires_in, interval
        """
        # Step 1: Request device code
        device_resp = await self.request_device_code()
        device_auth_id = device_resp["device_auth_id"]
        user_code = device_resp["user_code"]
        interval = int(device_resp.get("interval", 5))
        expires_in = 900  # 15 minutes
        
        # Store device auth info in instance for polling
        self._device_auth_id = device_auth_id
        self._device_user_code = user_code
        self._device_interval = interval
        
        logger.info(f"CodexOAuth2: Device code initiated - user_code: {user_code}")
        
        return {
            "device_auth_id": device_auth_id,
            "user_code": user_code,
            "verification_uri": f"{self.issuer}/codex/device",
            "expires_in": expires_in,
            "interval": interval,
        }
    
    async def poll_device_code_completion(self) -> Dict[str, Any]:
        """
        Poll for device authorization completion.
        
        Returns:
            Dict with status: 'pending', 'approved', 'denied', 'expired'
        """
        if not hasattr(self, '_device_auth_id') or not self._device_auth_id:
            return {"status": "error", "error": "No device authorization in progress"}
        
        logger.debug(f"CodexOAuth2: Polling for completion - device_auth_id: {self._device_auth_id}, user_code: {self._device_user_code}")
        
        try:
            token_resp = await self.poll_device_code_token(
                device_auth_id=self._device_auth_id,
                user_code=self._device_user_code,
                interval=1,  # We control polling interval from outside
            )
            
            logger.info(f"CodexOAuth2: Token response received - keys: {list(token_resp.keys())}")
            
            # Step 3: Exchange for tokens
            redirect_uri = f"{self.issuer}/deviceauth/callback"
            tokens = await self.exchange_code_for_tokens(
                code=token_resp["authorization_code"],
                redirect_uri=redirect_uri,
                code_verifier=token_resp["code_verifier"],
            )
            
            logger.info(f"CodexOAuth2: Tokens exchanged successfully")
            
            # Step 4: Optionally obtain API key
            api_key = None
            try:
                api_key = await self.obtain_api_key(tokens["id_token"])
                logger.info(f"CodexOAuth2: API key obtained")
            except Exception as e:
                logger.warning(f"CodexOAuth2: Failed to obtain API key: {e}")
            
            # Step 5: Save credentials
            credentials = {
                "auth_mode": "codex",
                "tokens": {
                    "id_token": tokens["id_token"],
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "account_id": tokens.get("account_id"),
                },
                "openai_api_key": api_key,
                "last_refresh": datetime.utcnow().isoformat() + "Z",
            }
            
            self._save_credentials(credentials)
            
            # Clear device auth info
            self._device_auth_id = None
            self._device_user_code = None
            
            return {"status": "approved"}
            
        except Exception as e:
            error_msg = str(e)
            logger.debug(f"CodexOAuth2: Poll exception - {type(e).__name__}: {error_msg}")
            # 403/404 means still pending
            if "403" in error_msg or "404" in error_msg or "pending" in error_msg.lower():
                return {"status": "pending"}
            elif "denied" in error_msg.lower():
                return {"status": "denied", "error": "User denied authorization"}
            elif "timed out" in error_msg.lower() or "expired" in error_msg.lower():
                return {"status": "expired", "error": "Device authorization expired"}
            else:
                return {"status": "error", "error": error_msg}
    
    async def authenticate_with_device_flow(self) -> Dict[str, Any]:
        """
        Complete device authorization flow (blocking - waits for completion).
        
        Returns:
            Dict with authentication result
        """
        # Start the flow
        device_info = await self.request_device_code_flow()
        
        # Poll until completion
        max_polls = int(device_info["expires_in"] / device_info["interval"])
        for _ in range(max_polls):
            await asyncio.sleep(device_info["interval"])
            result = await self.poll_device_code_completion()
            if result["status"] != "pending":
                return result
        
        return {"status": "expired", "error": "Device authorization expired"}
    
    async def authenticate_with_browser_flow(self, port: int = DEFAULT_PORT) -> Dict[str, Any]:
        """
        Complete browser-based OAuth2 flow with PKCE.
        
        Returns:
            Dict with auth_url, state, code_verifier for external handling
        """
        code_verifier, code_challenge = self.generate_pkce()
        state = self.generate_state()
        redirect_uri = f"http://localhost:{port}/auth/callback"
        
        auth_url = self.build_authorization_url(
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            state=state,
        )
        
        return {
            "auth_url": auth_url,
            "state": state,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "port": port,
        }
    
    async def complete_browser_flow(
        self,
        code: str,
        state: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """
        Complete browser OAuth2 flow after receiving callback.
        
        Args:
            code: Authorization code from callback
            state: State parameter (for CSRF verification)
            code_verifier: PKCE code verifier
            redirect_uri: Redirect URI used in authorization
            
        Returns:
            Dict with authentication result
        """
        # Exchange code for tokens
        tokens = await self.exchange_code_for_tokens(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        
        # Optionally obtain API key
        api_key = None
        try:
            api_key = await self.obtain_api_key(tokens["id_token"])
        except Exception as e:
            logger.warning(f"CodexOAuth2: Failed to obtain API key: {e}")
        
        # Save credentials
        credentials = {
            "auth_mode": "codex",
            "tokens": {
                "id_token": tokens["id_token"],
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "account_id": tokens.get("account_id"),
            },
            "openai_api_key": api_key,
            "last_refresh": datetime.utcnow().isoformat() + "Z",
        }
        
        self._save_credentials(credentials)
        
        return {
            "type": "success",
            "provider": "codex",
        }
    
    def get_valid_token(self) -> Optional[str]:
        """
        Get a valid access token, refreshing if needed.
        
        Returns:
            Access token string or None if not authenticated
        """
        if not self.credentials or not self.credentials.get("tokens"):
            return None
        
        tokens = self.credentials.get("tokens", {})
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        
        if not access_token or not refresh_token:
            return None
        
        # Check if access token is expired (with 5 minute buffer)
        try:
            claims = self._parse_jwt_claims(access_token)
            exp = claims.get("exp", 0)
            if exp < time.time() + 300:
                # Token expired or about to expire - refresh
                return None
        except Exception:
            return None
        
        return access_token
    
    async def get_valid_token_with_refresh(self) -> Optional[str]:
        """
        Get a valid access token, automatically refreshing if needed.
        
        Returns:
            Access token string or None if refresh fails
        """
        token = self.get_valid_token()
        if token:
            return token
        
        # Try to refresh
        if not self.credentials or not self.credentials.get("tokens"):
            return None
        
        refresh_token = self.credentials["tokens"].get("refresh_token")
        if not refresh_token:
            return None
        
        try:
            new_tokens = await self.refresh_tokens(refresh_token)
            
            # Optionally obtain new API key
            api_key = None
            try:
                api_key = await self.obtain_api_key(new_tokens["id_token"])
            except Exception:
                api_key = self.credentials.get("openai_api_key")
            
            # Update credentials
            self.credentials["tokens"] = {
                "id_token": new_tokens["id_token"],
                "access_token": new_tokens["access_token"],
                "refresh_token": new_tokens["refresh_token"],
                "account_id": new_tokens.get("account_id"),
            }
            self.credentials["openai_api_key"] = api_key
            self.credentials["last_refresh"] = datetime.utcnow().isoformat() + "Z"
            self._save_credentials(self.credentials)
            
            return new_tokens["access_token"]
        except Exception as e:
            logger.error(f"CodexOAuth2: Token refresh failed: {e}")
            return None
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated with valid token."""
        return self.get_valid_token() is not None
    
    def get_user_email(self) -> Optional[str]:
        """Get authenticated user's email from ID token."""
        if not self.credentials or not self.credentials.get("tokens"):
            return None
        
        id_token = self.credentials["tokens"].get("id_token")
        if not id_token:
            return None
        
        try:
            claims = self._parse_jwt_claims(id_token)
            email = claims.get("email")
            profile = claims.get("https://api.openai.com/profile", {})
            if not email and profile:
                email = profile.get("email")
            return email
        except Exception:
            return None
    
    def logout(self) -> None:
        """Clear stored credentials."""
        if os.path.exists(self.credentials_file):
            try:
                os.remove(self.credentials_file)
                logger.info("CodexOAuth2: Credentials removed")
            except Exception as e:
                logger.error(f"CodexOAuth2: Failed to remove credentials: {e}")
        
        self.credentials = None
    
    @staticmethod
    def _parse_jwt_claims(jwt_token: str) -> dict:
        """Parse the payload from a JWT token."""
        parts = jwt_token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        
        # Add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
