# Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import logging
import urllib.parse
import secrets
import hashlib
import base64
from typing import Dict, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class GoogleOAuth2:
    """Google OAuth2 Authentication Handler"""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._state = None
        self._code_verifier = None
    
    def generate_pkce_pair(self) -> Tuple[str, str]:
        """Generate PKCE code verifier and challenge"""
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip('=')
        return code_verifier, code_challenge
    
    def get_authorization_url(self, scopes: list = None) -> str:
        """Generate authorization URL with PKCE"""
        if scopes is None:
            scopes = ["openid", "email", "profile"]
        
        state = secrets.token_urlsafe(16)
        code_verifier, code_challenge = self.generate_pkce_pair()
        
        self._state = state
        self._code_verifier = code_verifier
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "select_account consent"
        }
        
        query = urllib.parse.urlencode(params)
        return f"{GOOGLE_OAUTH_AUTH_URL}?{query}"
    
    async def exchange_code_for_tokens(self, code: str, state: str) -> Optional[Dict]:
        """Exchange authorization code for tokens"""
        if state != self._state:
            logger.warning("Google OAuth2: State parameter mismatch")
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GOOGLE_OAUTH_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": self._code_verifier
                    },
                    headers={"Accept": "application/json"}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Google OAuth2 token exchange failed: {e}")
            return None
    
    async def get_user_info(self, access_token: str) -> Optional[Dict]:
        """Get user information from Google"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    GOOGLE_OAUTH_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Google OAuth2 user info request failed: {e}")
            return None
