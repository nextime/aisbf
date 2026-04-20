"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Qwen OAuth2 Device Authorization Grant implementation.

⚠️  WARNING: QWEN OAUTH2 SERVICE DISCONTINUED ⚠️

As of April 2026, Qwen has completely disabled OAuth2 subscriptions for Qwen Code.
The OAuth2 tokens obtained from chat.qwen.ai are no longer valid for the DashScope API.

This implementation is maintained in the hope that Qwen will re-enable OAuth2 support
in the future. If the service remains discontinued, this code will eventually be removed.

For now, please use API key authentication instead of OAuth2 for Qwen/DashScope services.

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
import platform
import secrets
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

# Qwen CLI-style headers
def _get_qwen_headers() -> Dict[str, str]:
    """Get headers that mimic the Qwen CLI."""
    # Detect platform for user-agent
    system = platform.system()  # 'Linux', 'Darwin', 'Windows'
    machine = platform.machine()  # 'x86_64', 'aarch64', etc.
    user_agent = f"QwenCode/1.0.0 ({system.lower()}; {machine})"
    
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "x-request-id": str(uuid.uuid4()),
    }

# Qwen OAuth2 Constants (from qwen-oauth2-analysis.md)
QWEN_OAUTH_BASE_URL = "https://chat.qwen.ai"
QWEN_OAUTH_DEVICE_CODE_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/device/code"
QWEN_OAUTH_TOKEN_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/token"
QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_OAUTH_SCOPE = "openid profile email model.completion"
QWEN_OAUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Token management constants
TOKEN_REFRESH_BUFFER_MS = 30_000  # 30 seconds
LOCK_TIMEOUT_MS = 10_000          # 10 seconds
CACHE_CHECK_INTERVAL_MS = 5_000   # 5 seconds


class QwenOAuth2:
    """
    OAuth2 Device Authorization Grant implementation for Qwen.
    
    ⚠️  WARNING: QWEN OAUTH2 SERVICE DISCONTINUED ⚠️
    
    As of April 2026, Qwen has completely disabled OAuth2 subscriptions for Qwen Code.
    OAuth2 tokens from chat.qwen.ai are no longer accepted by the DashScope API.
    
    This implementation is maintained for potential future re-enablement by Qwen.
    Please use API key authentication instead.
    
    Implements RFC 8628 device authorization flow with PKCE for CLI/desktop applications.
    Supports authentication with Qwen's OAuth2 endpoints and automatic token refresh.
    """
    
    def __init__(self, credentials_file: Optional[str] = None):
        """
        Initialize Qwen OAuth2 client.
        
        ⚠️  WARNING: OAuth2 authentication for Qwen has been discontinued.
        This client will not work with DashScope API. Use API key authentication instead.
        
        Args:
            credentials_file: Path to credentials JSON file (default: ~/.aisbf/qwen_credentials.json)
        """
        logger.warning(
            "⚠️  Qwen OAuth2 service has been discontinued by Qwen. "
            "OAuth2 tokens are no longer accepted by DashScope API. "
            "Please use API key authentication instead."
        )
        self.credentials_file = os.path.expanduser(credentials_file) if credentials_file else os.path.expanduser("~/.aisbf/qwen_credentials.json")
        self.lock_file = os.path.expanduser("~/.aisbf/qwen_credentials.lock")
        self.credentials = None
        self._file_mod_time = 0
        self._last_check = 0
        self._load_credentials()
    
    def _load_credentials(self) -> None:
        """Load credentials from file if it exists."""
        if os.path.exists(self.credentials_file):
            try:
                with open(self.credentials_file, 'r') as f:
                    self.credentials = json.load(f)
                
                # Update file modification time
                stat = os.stat(self.credentials_file)
                self._file_mod_time = stat.st_mtime
                
                logger.info(f"QwenOAuth2: Loaded credentials from {self.credentials_file}")
            except Exception as e:
                logger.warning(f"QwenOAuth2: Failed to load credentials: {e}")
                self.credentials = None
    
    def _save_credentials(self, credentials: Dict[str, Any]) -> None:
        """
        Save credentials to file with secure permissions and file locking.
        
        Args:
            credentials: Credentials dict to save
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.credentials_file), exist_ok=True)
            
            # Write credentials atomically (temp file + rename)
            temp_file = f"{self.credentials_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(credentials, f, indent=2)
            
            # Atomic rename
            os.rename(temp_file, self.credentials_file)
            
            # Set file permissions to 0o600 (user read/write only)
            os.chmod(self.credentials_file, 0o600)
            
            # Update internal state
            self.credentials = credentials
            stat = os.stat(self.credentials_file)
            self._file_mod_time = stat.st_mtime
            
            logger.info(f"QwenOAuth2: Saved credentials to {self.credentials_file}")
        except Exception as e:
            logger.error(f"QwenOAuth2: Failed to save credentials: {e}")
            raise
    
    @staticmethod
    def generate_pkce() -> tuple:
        """Generate PKCE code verifier and challenge (S256)."""
        # Generate 32 random bytes = 256 bits, base64url encoded = 43 characters
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode('ascii')
        
        # Generate SHA-256 hash of verifier
        sha256_hash = hashlib.sha256(code_verifier.encode('ascii')).digest()
        code_challenge = base64.urlsafe_b64encode(sha256_hash).rstrip(b'=').decode('ascii')
        
        return code_verifier, code_challenge
    
    async def _acquire_lock(self, max_attempts: int = 20) -> bool:
        """
        Acquire a file lock to prevent concurrent token refreshes.

        Returns:
            True if lock acquired, False otherwise.
        """
        import asyncio
        lock_id = str(uuid.uuid4())
        interval = 0.1

        for _ in range(max_attempts):
            try:
                # Try to create lock file atomically (exclusive mode)
                with open(self.lock_file, 'x') as f:
                    f.write(lock_id)
                return True
            except FileExistsError:
                # Lock file exists, check if stale
                try:
                    stat = os.stat(self.lock_file)
                    lock_age = time.time() - stat.st_mtime

                    if lock_age > LOCK_TIMEOUT_MS / 1000:
                        # Remove stale lock
                        os.unlink(self.lock_file)
                        continue
                except (OSError, FileNotFoundError):
                    # Lock might have been removed by another process
                    continue

                await asyncio.sleep(interval)
                interval = min(interval * 1.5, 2.0)  # Exponential backoff

        return False
    
    def _release_lock(self) -> None:
        """Release the file lock."""
        try:
            os.unlink(self.lock_file)
        except FileNotFoundError:
            pass  # Lock already removed
    
    def check_and_reload(self) -> None:
        """Check if the credentials file was updated by another process and reload."""
        now = time.time()
        
        # Limit check frequency
        if now - self._last_check < CACHE_CHECK_INTERVAL_MS / 1000:
            return
        
        self._last_check = now
        
        try:
            stat = os.stat(self.credentials_file)
            file_mod_time = stat.st_mtime
            
            if file_mod_time > self._file_mod_time:
                # File has been modified, reload
                self._load_credentials()
                logger.debug("QwenOAuth2: Reloaded credentials from disk (modified by another process)")
        except FileNotFoundError:
            self._file_mod_time = 0
    
    def _is_token_valid(self) -> bool:
        """Check if the token is valid and not expired (with buffer)."""
        if not self.credentials or not self.credentials.get('access_token'):
            return False
        
        expiry_date = self.credentials.get('expiry_date')
        if not expiry_date:
            return False
        
        now_ms = int(time.time() * 1000)
        return now_ms < expiry_date - TOKEN_REFRESH_BUFFER_MS
    
    async def request_device_code(self) -> Dict[str, Any]:
        """
        Request a device code for headless login.
        
        Returns:
            Dict with device_code, user_code, verification_uri, expires_in, interval
        """
        code_verifier, code_challenge = self.generate_pkce()
        
        body_data = {
            "client_id": QWEN_OAUTH_CLIENT_ID,
            "scope": QWEN_OAUTH_SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        
        # Build headers mimicking Qwen CLI
        headers = _get_qwen_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-DashScope-CacheControl"] = "enable"
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                QWEN_OAUTH_DEVICE_CODE_ENDPOINT,
                headers=headers,
                data=body_data,
                timeout=30.0
            )
            
            logger.debug(f"QwenOAuth2: Device code request response status: {response.status_code}")
            logger.debug(f"QwenOAuth2: Device code request response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                error_body = response.text
                raise Exception(
                    f"Device authorization failed: {response.status_code} {response.reason_phrase}. Response: {error_body}"
                )
            
            # Try to parse JSON, handle empty or non-JSON responses
            response_text = response.text
            logger.debug(f"QwenOAuth2: Device code request response body: {response_text[:500] if response_text else 'empty'}")
            
            if not response_text or not response_text.strip():
                raise Exception(
                    f"Device authorization failed: Empty response from server. Status: {response.status_code}"
                )
            
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                raise Exception(
                    f"Device authorization failed: Invalid JSON response. Status: {response.status_code}, Response: {response_text[:500]}"
                )
            
            if "device_code" not in result:
                error = result.get("error", "Unknown error")
                description = result.get("error_description", "No details provided")
                raise Exception(f"Device authorization failed: {error} - {description}")
            
            # Store code_verifier for later use
            self._code_verifier = code_verifier
            
            logger.info(f"QwenOAuth2: Device code obtained - user_code: {result['user_code']}")
            
            return {
                "device_code": result["device_code"],
                "user_code": result["user_code"],
                "verification_uri": result["verification_uri"],
                "verification_uri_complete": result["verification_uri_complete"],
                "expires_in": result["expires_in"],
                "interval": result.get("interval", 5),
                "code_verifier": code_verifier,
            }
    
    async def poll_device_token(
        self,
        device_code: str,
        code_verifier: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Poll for device code token once (non-blocking).
        
        Returns:
            Dict with token response on success, None if still pending
            
        Raises:
            Exception on non-pending errors
        """
        body_data = {
            "grant_type": QWEN_OAUTH_GRANT_TYPE,
            "client_id": QWEN_OAUTH_CLIENT_ID,
            "device_code": device_code,
            "code_verifier": code_verifier,
        }
        
        # Build headers mimicking Qwen CLI
        headers = _get_qwen_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-DashScope-CacheControl"] = "enable"
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                QWEN_OAUTH_TOKEN_ENDPOINT,
                headers=headers,
                data=body_data,
                timeout=30.0
            )
            
            # Check Content-Type to determine response type
            content_type = response.headers.get("content-type", "")
            
            # If not JSON, it's likely a pending/authorization page
            if "application/json" not in content_type:
                response_text = response.text.lower()
                # Check if this is an authorization pending page
                if ("pending" in response_text or 
                    "authorize" in response_text or
                    "waiting" in response_text or
                    response.status_code == 200):
                    # Still pending - user hasn't approved yet
                    logger.debug("QwenOAuth2: Authorization still pending (HTML response)")
                    return None
                # Otherwise it's an error
                raise Exception(
                    f"Device token poll failed: HTTP {response.status_code}, Content-Type: {content_type}"
                )
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("access_token"):
                    return result
                else:
                    raise Exception(f"Unexpected token response: {result}")
            
            # Parse error response
            try:
                error_data = response.json()
            except Exception:
                raise Exception(
                    f"Device token poll failed: {response.status_code} {response.reason_phrase}"
                )
            
            # authorization_pending: continue polling
            if response.status_code == 400 and error_data.get("error") == "authorization_pending":
                return None
            
            # slow_down: increase polling interval (handled by caller)
            if response.status_code == 429 and error_data.get("error") == "slow_down":
                return None
            
            # Other errors
            error = error_data.get("error", "Unknown error")
            description = error_data.get("error_description", "No details provided")
            raise Exception(f"Device token poll failed: {error} - {description}")
    
    async def authenticate_with_device_flow(self) -> Dict[str, Any]:
        """
        Complete device authorization flow (blocking - waits for completion).
        
        Returns:
            Dict with authentication result
        """
        # Step 1: Request device code
        device_info = await self.request_device_code()
        
        device_code = device_info["device_code"]
        code_verifier = device_info["code_verifier"]
        poll_interval = float(device_info["interval"])
        max_polls = int(device_info["expires_in"] / poll_interval)
        
        logger.info(f"QwenOAuth2: Please visit: {device_info['verification_uri_complete']}")
        logger.info(f"QwenOAuth2: User code: {device_info['user_code']}")
        
        # Step 2: Poll until completion
        for attempt in range(max_polls):
            await asyncio.sleep(poll_interval)
            
            try:
                token_data = await self.poll_device_token(device_code, code_verifier)
                
                if token_data:
                    # Success - save credentials
                    # OAuth2: expires_in is in seconds
                    expires_in = token_data.get("expires_in", 7200)
                    expires_in_ms = expires_in * 1000  # Convert seconds to milliseconds
                    
                    # Minimum 1 hour
                    if expires_in_ms < 3600000:
                        expires_in_ms = 3600000
                    
                    # WORKAROUND: OAuth2 server returns incorrect resource_url ("portal.qwen.ai")
                    # Always use the correct DashScope API endpoint
                    resource_url = token_data.get("resource_url")
                    if resource_url and "portal.qwen.ai" in resource_url:
                        logger.warning(f"QwenOAuth2: OAuth2 server returned incorrect resource_url '{resource_url}', using correct endpoint")
                        resource_url = DEFAULT_DASHSCOPE_BASE_URL
                    elif not resource_url:
                        resource_url = DEFAULT_DASHSCOPE_BASE_URL
                    
                    credentials = {
                        "access_token": token_data["access_token"],
                        "refresh_token": token_data.get("refresh_token"),
                        "token_type": token_data.get("token_type", "Bearer"),
                        "resource_url": resource_url,
                        "expiry_date": int(time.time() * 1000) + expires_in_ms,
                        "last_refresh": datetime.utcnow().isoformat() + "Z",
                    }
                    
                    self._save_credentials(credentials)
                    logger.info("QwenOAuth2: Authentication successful")
                    
                    return {"status": "approved"}
                
                # Still pending, continue polling
                logger.debug(f"QwenOAuth2: Polling... (attempt {attempt + 1}/{max_polls})")
                
            except Exception as e:
                error_msg = str(e).lower()
                if "slow_down" in error_msg or "429" in error_msg:
                    # Increase polling interval
                    poll_interval = min(poll_interval * 1.5, 10.0)
                    logger.info(f"QwenOAuth2: Server requested slow down, increasing interval to {poll_interval:.1f}s")
                    continue
                else:
                    raise
        
        return {"status": "expired", "error": "Device authorization expired"}
    
    async def refresh_tokens(self) -> bool:
        """
        Use the refresh token to get a new access token.
        
        Returns:
            True if refresh was successful, False otherwise
        """
        if not self.credentials or not self.credentials.get("refresh_token"):
            logger.warning("QwenOAuth2: No refresh token available")
            return False
        
        logger.info("QwenOAuth2: Refreshing access token...")
        
        # Acquire lock to prevent concurrent refreshes
        if not await self._acquire_lock():
            logger.error("QwenOAuth2: Failed to acquire lock for token refresh")
            return False
        
        try:
            # Double-check after acquiring lock (another process might have refreshed)
            self.check_and_reload()
            if self._is_token_valid():
                logger.info("QwenOAuth2: Token already refreshed by another process")
                return True
            
            body_data = {
                "grant_type": "refresh_token",
                "refresh_token": self.credentials["refresh_token"],
                "client_id": QWEN_OAUTH_CLIENT_ID,
            }
            
            # Build headers mimicking Qwen CLI
            headers = _get_qwen_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["X-DashScope-CacheControl"] = "enable"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    QWEN_OAUTH_TOKEN_ENDPOINT,
                    headers=headers,
                    data=body_data,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # WORKAROUND: OAuth2 server returns incorrect resource_url ("portal.qwen.ai")
                    # Always use the correct DashScope API endpoint
                    resource_url = result.get("resource_url", self.credentials.get("resource_url"))
                    if resource_url and "portal.qwen.ai" in resource_url:
                        logger.warning(f"QwenOAuth2: OAuth2 server returned incorrect resource_url '{resource_url}', using correct endpoint")
                        resource_url = DEFAULT_DASHSCOPE_BASE_URL
                    elif not resource_url:
                        resource_url = DEFAULT_DASHSCOPE_BASE_URL
                    
                    # Update credentials
                    credentials = {
                        "access_token": result["access_token"],
                        "token_type": result.get("token_type", "Bearer"),
                        "refresh_token": result.get("refresh_token", self.credentials["refresh_token"]),
                        "resource_url": resource_url,
                        # OAuth2: expires_in is in seconds, convert to ms with minimum 1 hour
                        "expiry_date": int(time.time() * 1000) + max(3600000, result.get("expires_in", 7200) * 1000),
                        "last_refresh": datetime.utcnow().isoformat() + "Z",
                    }
                    
                    self._save_credentials(credentials)
                    logger.info("QwenOAuth2: Successfully refreshed access token")
                    return True
                
                elif response.status_code == 400:
                    # Refresh token expired/invalid - clear credentials
                    logger.error("QwenOAuth2: Refresh token expired or invalid")
                    self.clear_credentials()
                    return False
                
                else:
                    logger.error(f"QwenOAuth2: Token refresh failed: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"QwenOAuth2: Token refresh error: {e}")
            return False
        finally:
            self._release_lock()
    
    def get_valid_token(self) -> Optional[str]:
        """
        Get a valid access token (non-async, does not refresh).
        
        Returns:
            Access token string or None if not authenticated or expired
        """
        # Check if file was updated by another process
        self.check_and_reload()
        
        if not self._is_token_valid():
            return None
        
        return self.credentials.get("access_token")
    
    async def get_valid_token_with_refresh(self) -> Optional[str]:
        """
        Get a valid access token, automatically refreshing if needed.
        
        Returns:
            Access token string or None if refresh fails
        """
        # Check if file was updated by another process
        self.check_and_reload()
        
        if self._is_token_valid():
            return self.credentials.get("access_token")
        
        # Try to refresh
        if await self.refresh_tokens():
            return self.credentials.get("access_token")
        
        return None
    
    def get_resource_url(self) -> str:
        """
        Get the resource URL (API endpoint) from credentials.
        
        Returns:
            Resource URL or default DashScope URL
        """
        if self.credentials and self.credentials.get("resource_url"):
            return self.credentials["resource_url"]
        return DEFAULT_DASHSCOPE_BASE_URL
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated with valid token."""
        return self.get_valid_token() is not None
    
    def clear_credentials(self) -> None:
        """Clear stored credentials."""
        if os.path.exists(self.credentials_file):
            try:
                os.remove(self.credentials_file)
                logger.info("QwenOAuth2: Credentials removed")
            except Exception as e:
                logger.error(f"QwenOAuth2: Failed to remove credentials: {e}")
        
        self.credentials = None
        self._file_mod_time = 0
