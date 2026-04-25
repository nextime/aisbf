"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

OAuth2 Device Authorization Grant implementation for Kilo Gateway.

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
import json
import logging
import os
import time
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)


class KiloOAuth2:
    """
    OAuth2 Device Authorization Grant implementation for Kilo Gateway.
    
    Implements RFC 8628 device authorization flow for CLI/desktop applications.
    Supports authentication with Kilo Gateway at https://api.kilo.ai.
    """
    
    def __init__(self, credentials_file: Optional[str] = None, api_base: Optional[str] = None, skip_initial_load: bool = False, save_callback: Optional[callable] = None):
        """
        Initialize Kilo OAuth2 client.
        
        Args:
            credentials_file: Path to credentials JSON file (default: ~/.kilo_credentials.json)
            api_base: Base URL for Kilo API (default: https://api.kilo.ai)
            skip_initial_load: If True, do not load credentials from file on initialization
        """
        self.credentials_file = os.path.expanduser(credentials_file) if credentials_file else os.path.expanduser("~/.kilo_credentials.json")
        self.api_base = api_base or os.environ.get("KILO_API_URL", "https://api.kilo.ai")
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
                logger.info(f"KiloOAuth2: Loaded credentials from {self.credentials_file}")
            except Exception as e:
                logger.warning(f"KiloOAuth2: Failed to load credentials: {e}")
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
                logger.info(f"KiloOAuth2: Saved credentials via callback")
                return
            except Exception as e:
                logger.error(f"KiloOAuth2: Failed to save credentials to database: {e}")
                # DO NOT FALLBACK TO FILE SAVE FOR REGULAR USERS
                raise
        
        # Admin/global provider ONLY: save to file
        try:
            # Ensure directory exists
            cred_dir = os.path.dirname(self.credentials_file)
            if cred_dir:  # Only create if there's a directory component
                os.makedirs(cred_dir, exist_ok=True)

            # Write credentials
            with open(self.credentials_file, 'w') as f:
                json.dump(credentials, f, indent=2)
            
            # Set file permissions to 0o600 (user read/write only)
            os.chmod(self.credentials_file, 0o600)
            
            self.credentials = credentials
            logger.info(f"KiloOAuth2: Saved credentials to {self.credentials_file}")
        except Exception as e:
            logger.error(f"KiloOAuth2: Failed to save credentials: {e}")
            raise
    
    async def initiate_device_auth(self) -> Dict[str, Any]:
        """
        Initiate device authorization flow with retry logic.
        
        Implements retry with exponential backoff to handle transient Vercel edge node failures.
        
        Returns:
            Dict with 'code', 'verificationUrl', and 'expiresIn'
            
        Raises:
            Exception: If initiation fails after all retries
        """
        url = f"{self.api_base}/api/device-auth/codes"
        max_retries = 3
        base_delay = 1.0
        
        async with httpx.AsyncClient() as client:
            for attempt in range(max_retries):
                try:
                    headers = {
                        'Content-Type': 'application/json',
                        'User-Agent': 'Kilocode/1.0 (Firefox/130.0)'
                    }
                    
                    if attempt > 0:
                        logger.info(f"KiloOAuth2: Retry attempt {attempt + 1}/{max_retries}")
                    
                    # Log the exact request details
                    logger.info(f"KiloOAuth2: Initiating device auth request")
                    logger.info(f"KiloOAuth2: URL: {url}")
                    logger.info(f"KiloOAuth2: Headers: {headers}")
                    logger.info(f"KiloOAuth2: Body: b''")
                    logger.info(f"KiloOAuth2: httpx version: {httpx.__version__}")
                    
                    response = await client.post(
                        url,
                        content=b'',
                        headers=headers,
                        timeout=30.0
                    )
                    
                    # Log the exact response details
                    logger.info(f"KiloOAuth2: Response status: {response.status_code}")
                    logger.info(f"KiloOAuth2: Response headers: {dict(response.headers)}")
                    logger.info(f"KiloOAuth2: Response body: {response.text}")
                    
                    # Check for Vercel edge node in response
                    vercel_id = response.headers.get('x-vercel-id', 'unknown')
                    logger.info(f"KiloOAuth2: Vercel edge node: {vercel_id}")
                    
                    if response.status_code == 429:
                        raise Exception("Too many pending authorization requests. Please try again later.")
                    
                    # If we get a 500 error and have retries left, retry with exponential backoff
                    if response.status_code == 500 and attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"KiloOAuth2: Got 500 error from Vercel edge node {vercel_id}, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    logger.info(f"KiloOAuth2: Device auth initiated - code: {data.get('code')}")
                    return data
                    
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"KiloOAuth2: Request failed: {e}, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"KiloOAuth2: Failed to initiate device auth after {max_retries} attempts: {e}")
                        raise Exception(f"Failed to initiate device authorization: {e}")
            
            raise Exception(f"Failed to initiate device authorization after {max_retries} attempts")
    
    async def poll_device_auth(self, code: str) -> Dict[str, Any]:
        """
        Poll device authorization status.
        
        Args:
            code: Device authorization code
            
        Returns:
            Dict with 'status' and optionally 'token' and 'userEmail'
            Status can be: 'pending', 'approved', 'denied', 'expired'
        """
        url = f"{self.api_base}/api/device-auth/codes/{code}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=30.0)
                
                if response.status_code == 202:
                    return {"status": "pending"}
                elif response.status_code == 200:
                    data = response.json()
                    return {
                        "status": "approved",
                        "token": data.get("token"),
                        "userEmail": data.get("userEmail")
                    }
                elif response.status_code == 403:
                    return {"status": "denied"}
                elif response.status_code == 410:
                    return {"status": "expired"}
                else:
                    raise Exception(f"Unexpected status code: {response.status_code}")
                    
            except httpx.HTTPError as e:
                logger.error(f"KiloOAuth2: Failed to poll device auth: {e}")
                raise
    
    async def initiate_device_flow(self) -> Dict[str, Any]:
        """
        Start device authorization flow - returns immediately with verification info.
        
        This is the non-blocking version that allows external handling of
        the verification URL and code display.
        
        Returns:
            Dict with verification_url, code, expires_in, and poll_interval
        """
        auth_data = await self.initiate_device_auth()
        code = auth_data.get("code")
        verification_url = auth_data.get("verificationUrl")
        expires_in = auth_data.get("expiresIn", 600)
        
        # Store for polling with auto-renewal
        self._device_code = code
        self._device_expires_at = time.time() + expires_in
        self._device_verification_url = verification_url
        self._device_poll_interval = 3.0
        self._device_flow_started_at = time.time()
        self._device_code_renewals = 0
        
        logger.info(f"KiloOAuth2: Please visit {verification_url} and enter code: {code}")
        logger.info(f"KiloOAuth2: Code expires in {expires_in} seconds")
        
        # Try to open browser
        try:
            import webbrowser
            webbrowser.open(verification_url)
            logger.info("KiloOAuth2: Opened browser for authorization")
        except Exception as e:
            logger.debug(f"KiloOAuth2: Could not open browser: {e}")
        
        return {
            "code": code,
            "verification_url": verification_url,
            "expires_in": expires_in,
            "poll_interval": 3.0
        }
    
    async def _renew_device_code(self) -> Dict[str, Any]:
        """
        Auto-renew the device authorization code when it expires.
        
        This allows the device flow to continue indefinitely until the user
        completes authorization, similar to how KiloCode handles it.
        
        Returns:
            Dict with new code info, or error dict if renewal fails
        """
        try:
            auth_data = await self.initiate_device_auth()
            code = auth_data.get("code")
            verification_url = auth_data.get("verificationUrl")
            expires_in = auth_data.get("expiresIn", 600)
            
            self._device_code = code
            self._device_expires_at = time.time() + expires_in
            self._device_verification_url = verification_url
            self._device_code_renewals += 1
            
            logger.info(f"KiloOAuth2: Device code auto-renewed - new code: {code}")
            logger.info(f"KiloOAuth2: Please visit {verification_url} and enter code: {code}")
            logger.info(f"KiloOAuth2: New code expires in {expires_in} seconds")
            
            # Try to open browser with renewed code
            try:
                import webbrowser
                webbrowser.open(verification_url)
            except Exception:
                pass
            
            return {
                "code": code,
                "verification_url": verification_url,
                "expires_in": expires_in
            }
        except Exception as e:
            logger.error(f"KiloOAuth2: Failed to renew device code: {e}")
            return {"status": "error", "error": f"Failed to renew device code: {e}"}
    
    async def poll_device_flow_completion(self) -> Dict[str, Any]:
        """
        Poll for device authorization completion (non-blocking, single poll).
        
        Automatically renews the device code when it expires, allowing the
        flow to continue until the user completes authorization.
        
        Call this repeatedly until status is not 'pending'.
        
        Returns:
            Dict with status: 'pending', 'approved', 'denied', 'expired', or 'error'
        """
        if not hasattr(self, '_device_code') or not self._device_code:
            return {"status": "error", "error": "No device authorization in progress. Call initiate_device_flow() first."}
        
        # Check if device code has expired - auto-renew if needed
        if hasattr(self, '_device_expires_at') and time.time() > self._device_expires_at:
            logger.info("KiloOAuth2: Device code expired, auto-renewing...")
            renew_result = await self._renew_device_code()
            if "status" in renew_result and renew_result["status"] == "error":
                return renew_result
            # Continue polling with new code
            return {"status": "pending", "code_renewed": True, "new_code": renew_result.get("code")}
        
        try:
            result = await self.poll_device_auth(self._device_code)
            status = result.get("status")
            
            if status == "approved":
                token = result.get("token")
                user_email = result.get("userEmail")
                
                if not token:
                    return {"status": "error", "error": "Authorization approved but no token received"}
                
                # Save credentials
                credentials = {
                    "type": "oauth",
                    "access": token,
                    "refresh": token,
                    "expires": int(time.time()) + (365 * 24 * 60 * 60),  # 1 year
                    "userEmail": user_email
                }
                
                self._save_credentials(credentials)
                
                logger.info(f"KiloOAuth2: Authentication successful for {user_email}")
                
                # Clear device code
                self._device_code = None
                
                return {
                    "status": "approved",
                    "token": token,
                    "userEmail": user_email
                }
            
            elif status == "denied":
                self._device_code = None
                return {"status": "denied", "error": "Authorization denied by user"}
            
            elif status == "expired":
                # This shouldn't happen with auto-renewal, but handle it anyway
                logger.info("KiloOAuth2: Device code expired (from server), auto-renewing...")
                renew_result = await self._renew_device_code()
                if "status" in renew_result and renew_result["status"] == "error":
                    return renew_result
                return {"status": "pending", "code_renewed": True, "new_code": renew_result.get("code")}
            
            # status == "pending"
            return {"status": "pending"}
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def authenticate_with_device_flow(self) -> Dict[str, Any]:
        """
        Complete device authorization flow (blocking - waits for completion).
        
        Returns:
            Dict with authentication result
            
        Raises:
            Exception: If authentication fails
        """
        # Initiate device auth
        auth_data = await self.initiate_device_auth()
        code = auth_data.get("code")
        verification_url = auth_data.get("verificationUrl")
        expires_in = auth_data.get("expiresIn", 600)
        
        logger.info(f"KiloOAuth2: Please visit {verification_url} and enter code: {code}")
        logger.info(f"KiloOAuth2: Code expires in {expires_in} seconds")
        
        # Try to open browser
        try:
            import webbrowser
            webbrowser.open(verification_url)
            logger.info("KiloOAuth2: Opened browser for authorization")
        except Exception as e:
            logger.debug(f"KiloOAuth2: Could not open browser: {e}")
        
        # Poll for authorization
        poll_interval = 3.0  # 3 seconds
        max_attempts = int(expires_in / poll_interval)
        
        for attempt in range(max_attempts):
            if attempt > 0:
                await asyncio.sleep(poll_interval)
            
            result = await self.poll_device_auth(code)
            status = result.get("status")
            
            if status == "approved":
                token = result.get("token")
                user_email = result.get("userEmail")
                
                if not token:
                    raise Exception("Authorization approved but no token received")
                
                # Save credentials
                credentials = {
                    "type": "oauth",
                    "access": token,
                    "refresh": token,  # Same token for both
                    "expires": int(time.time()) + (365 * 24 * 60 * 60),  # 1 year
                    "userEmail": user_email
                }
                
                self._save_credentials(credentials)
                
                logger.info(f"KiloOAuth2: Authentication successful for {user_email}")
                return {
                    "type": "success",
                    "provider": "kilo",
                    "token": token,
                    "userEmail": user_email
                }
            
            elif status == "denied":
                raise Exception("Authorization denied by user")
            
            elif status == "expired":
                raise Exception("Authorization code expired")
            
            # status == "pending", continue polling
            logger.debug(f"KiloOAuth2: Waiting for authorization... (attempt {attempt + 1}/{max_attempts})")
        
        raise Exception("Authorization timeout: Maximum attempts reached")
    
    def get_valid_token(self) -> Optional[str]:
        """
        Get a valid access token.
        
        Returns:
            Access token string or None if not authenticated
        """
        if not self.credentials:
            # Try to load credentials from file if not already loaded
            # This handles the case where credentials were saved by a previous
            # handler instance but this instance was created before the file existed
            self._load_credentials()
            if not self.credentials:
                return None
        
        # Check if token is expired
        expires = self.credentials.get("expires", 0)
        if expires < time.time():
            logger.warning("KiloOAuth2: Token expired")
            return None
        
        return self.credentials.get("access")
    
    async def get_valid_token_with_refresh(self) -> Optional[str]:
        """
        Get a valid access token, attempting refresh if expired.
        
        Note: Kilo uses long-lived tokens (1 year) with the same value for
        access and refresh. There is no separate refresh endpoint - when tokens
        expire, users must complete device flow again.
        
        Returns:
            Access token string or None if expired/not authenticated
        """
        self._load_credentials()
        
        if self.credentials and self.credentials.get('expires', 0) > time.time():
            return self.credentials.get('access')
        
        logger.error("KiloOAuth2: Token expired, re-authentication required")
        return None
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated with valid token."""
        # get_valid_token() already handles credential reloading
        return self.get_valid_token() is not None
    
    def get_user_email(self) -> Optional[str]:
        """Get authenticated user's email."""
        # Try to load credentials if not present
        if not self.credentials:
            self._load_credentials()
        if self.credentials:
            return self.credentials.get("userEmail")
        return None
    
    def logout(self) -> None:
        """Clear stored credentials."""
        if os.path.exists(self.credentials_file):
            try:
                os.remove(self.credentials_file)
                logger.info("KiloOAuth2: Credentials removed")
            except Exception as e:
                logger.error(f"KiloOAuth2: Failed to remove credentials: {e}")
        
        self.credentials = None
    
    async def get_profile(self, token: str) -> Dict[str, Any]:
        """
        Fetch user profile from Kilo API.
        
        Args:
            token: Access token
            
        Returns:
            Profile data dict
        """
        url = f"{self.api_base}/api/profile"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0
                )
                
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPError as e:
                logger.error(f"KiloOAuth2: Failed to fetch profile: {e}")
                raise
