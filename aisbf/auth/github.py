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
from typing import Dict, Optional
import httpx

logger = logging.getLogger(__name__)

GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"
GITHUB_API_EMAILS_URL = "https://api.github.com/user/emails"


class GitHubOAuth2:
    """GitHub OAuth2 Authentication Handler"""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._state = None
    
    def get_authorization_url(self, scopes: list = None) -> str:
        """Generate GitHub authorization URL"""
        if scopes is None:
            scopes = ["user:email", "read:user"]
        
        state = secrets.token_urlsafe(16)
        self._state = state
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "allow_signup": "true"
        }
        
        query = urllib.parse.urlencode(params)
        return f"{GITHUB_OAUTH_AUTH_URL}?{query}"
    
    async def exchange_code_for_tokens(self, code: str, state: str) -> Optional[Dict]:
        """Exchange authorization code for access token"""
        if state != self._state:
            logger.warning("GitHub OAuth2: State parameter mismatch")
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GITHUB_OAUTH_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri
                    },
                    headers={"Accept": "application/json"}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"GitHub OAuth2 token exchange failed: {e}")
            return None
    
    async def get_user_info(self, access_token: str) -> Optional[Dict]:
        """Get user information from GitHub including primary email"""
        try:
            async with httpx.AsyncClient() as client:
                # Get user profile
                user_response = await client.get(
                    GITHUB_API_USER_URL,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                user_response.raise_for_status()
                user_data = user_response.json()
                
                # Get emails if needed
                if not user_data.get("email"):
                    emails_response = await client.get(
                        GITHUB_API_EMAILS_URL,
                        headers={"Authorization": f"Bearer {access_token}"}
                    )
                    emails_response.raise_for_status()
                    emails = emails_response.json()
                    
                    # Find primary verified email
                    for email in emails:
                        if email.get("primary") and email.get("verified"):
                            user_data["email"] = email.get("email")
                            break
                
                return user_data
        except Exception as e:
            logger.error(f"GitHub OAuth2 user info request failed: {e}")
            return None
