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
    
    def __init__(self, credentials_file: Optional[str] = None, api_base: Optional[str] = None):
        """
        Initialize Kilo OAuth2 client.
        
        Args:
            credentials_file: Path to credentials JSON file (default: ~/.kilo_credentials.json)
            api_base: Base URL for Kilo API (default: https://api.kilo.ai)
        """
        self.credentials_file = credentials_file or os.path.expanduser("~/.kilo_credentials.json")
        self.api_base = api_base or os.environ.get("KILO_API_URL", "https://api.kilo.ai")
        self.credentials = None
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
        Save credentials to file with secure permissions.
        
        Args:
            credentials: Credentials dict to save
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.credentials_file), exist_ok=True)
            
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
        Initiate device authorization flow.
        
        Returns:
            Dict with 'code', 'verificationUrl', and 'expiresIn'
            
        Raises:
            Exception: If initiation fails
        """
        url = f"{self.api_base}/api/device-auth/codes"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0
                )
                
                if response.status_code == 429:
                    raise Exception("Too many pending authorization requests. Please try again later.")
                
                response.raise_for_status()
                data = response.json()
                
                logger.info(f"KiloOAuth2: Device auth initiated - code: {data.get('code')}")
                return data
                
            except httpx.HTTPError as e:
                logger.error(f"KiloOAuth2: Failed to initiate device auth: {e}")
                raise Exception(f"Failed to initiate device authorization: {e}")
    
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
    
    async def authenticate_with_device_flow(self) -> Dict[str, Any]:
        """
        Complete device authorization flow.
        
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
            return None
        
        # Check if token is expired
        expires = self.credentials.get("expires", 0)
        if expires < time.time():
            logger.warning("KiloOAuth2: Token expired")
            return None
        
        return self.credentials.get("access")
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated with valid token."""
        return self.get_valid_token() is not None
    
    def get_user_email(self) -> Optional[str]:
        """Get authenticated user's email."""
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
