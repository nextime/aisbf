"""
Kiro Authentication Module for AISBF
Adapted from kiro-gateway's auth.py
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
import hashlib
import uuid
import socket
import getpass
import logging

logger = logging.getLogger(__name__)

class AuthType(Enum):
    """Authentication type enum"""
    KIRO_DESKTOP = "kiro_desktop"
    AWS_SSO_OIDC = "aws_sso_oidc"

class KiroAuthManager:
    """
    Kiro Authentication Manager
    
    Handles authentication for Kiro API (Amazon Q Developer/CodeWhisperer)
    Supports both Kiro Desktop Auth and AWS SSO OIDC (kiro-cli)
    """
    
    def __init__(self, 
                 refresh_token: Optional[str] = None,
                 profile_arn: Optional[str] = None,
                 region: str = "us-east-1",
                 creds_file: Optional[str] = None,
                 sqlite_db: Optional[str] = None,
                 client_id: Optional[str] = None,
                 client_secret: Optional[str] = None):
        """
        Initialize Kiro Authentication Manager
        
        Args:
            refresh_token: Refresh token for Kiro Desktop Auth
            profile_arn: AWS CodeWhisperer profile ARN
            region: AWS region (default: us-east-1)
            creds_file: Path to JSON credentials file
            sqlite_db: Path to kiro-cli SQLite database
            client_id: OAuth client ID (for AWS SSO OIDC)
            client_secret: OAuth client secret (for AWS SSO OIDC)
        """
        self.refresh_token = refresh_token
        self.profile_arn = profile_arn
        self.region = region
        self.creds_file = creds_file
        self.sqlite_db = sqlite_db
        self.client_id = client_id
        self.client_secret = client_secret
        
        self._access_token = None
        self._refresh_token = refresh_token
        self._expires_at = None
        self._auth_type = AuthType.KIRO_DESKTOP
        self._lock = asyncio.Lock()
        
        # SQLite token keys to search for
        self.SQLITE_TOKEN_KEYS = [
            "kirocli:social:token",
            "kirocli:odic:token", 
            "codewhisperer:odic:token"
        ]
        
        self.SQLITE_REG_KEYS = [
            "kirocli:odic:device-registration",
            "codewhisperer:odic:device-registration"
        ]
        
        # Load credentials from file or SQLite if provided
        if sqlite_db:
            self._load_from_sqlite()
        elif creds_file:
            self._load_from_creds_file()
        
        # Determine auth type
        self._detect_auth_type()
    
    def _detect_auth_type(self):
        """Detect authentication type based on available credentials"""
        if self.client_id and self.client_secret:
            self._auth_type = AuthType.AWS_SSO_OIDC
            logger.info("Detected AWS SSO OIDC authentication")
        else:
            self._auth_type = AuthType.KIRO_DESKTOP
            logger.info("Detected Kiro Desktop authentication")
    
    def _load_from_sqlite(self):
        """Load credentials from SQLite database (kiro-cli)"""
        if not self.sqlite_db:
            return
        
        # Expand ~ in path
        db_path = Path(self.sqlite_db).expanduser()
        conn = None
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Try to find token in SQLite
            token_data = None
            token_key = None
            
            for key in self.SQLITE_TOKEN_KEYS:
                cursor.execute("SELECT value FROM auth_kv WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    token_data = json.loads(row[0])
                    token_key = key
                    break
            
            if token_data:
                self._access_token = token_data.get('access_token')
                self._refresh_token = token_data.get('refresh_token')
                self.refresh_token = token_data.get('refresh_token')  # Update public refresh_token too
                self._expires_at = datetime.fromisoformat(
                    token_data.get('expires_at', '1970-01-01T00:00:00Z')
                )
                # Also try to get profile_arn from token data
                if 'profile_arn' in token_data:
                    self.profile_arn = token_data['profile_arn']
                logger.info(f"Loaded credentials from SQLite key: {token_key}")
            
            # Try to get device registration for AWS SSO OIDC
            for reg_key in self.SQLITE_REG_KEYS:
                cursor.execute("SELECT value FROM auth_kv WHERE key = ?", (reg_key,))
                row = cursor.fetchone()
                if row:
                    reg_data = json.loads(row[0])
                    self.client_id = reg_data.get('clientId')
                    self.client_secret = reg_data.get('clientSecret')
                    # Also check for profile_arn in registration data
                    if 'profileArn' in reg_data:
                        self.profile_arn = reg_data['profileArn']
                    break
            
            # If profile_arn still not found, try to query it directly from the database
            if not self.profile_arn:
                # Try common profile ARN keys
                profile_keys = [
                    "kirocli:profile:arn",
                    "codewhisperer:profile:arn",
                    "kirocli:social:profile",
                    "codewhisperer:social:profile"
                ]
                for profile_key in profile_keys:
                    cursor.execute("SELECT value FROM auth_kv WHERE key = ?", (profile_key,))
                    row = cursor.fetchone()
                    if row:
                        try:
                            profile_data = json.loads(row[0])
                            if isinstance(profile_data, dict):
                                self.profile_arn = profile_data.get('arn') or profile_data.get('profileArn')
                            elif isinstance(profile_data, str):
                                self.profile_arn = profile_data
                            if self.profile_arn:
                                logger.info(f"Loaded profile ARN from SQLite key: {profile_key}")
                                break
                        except json.JSONDecodeError:
                            # Value might be a plain string
                            self.profile_arn = row[0]
                            logger.info(f"Loaded profile ARN (plain string) from SQLite key: {profile_key}")
                            break
                    
        except Exception as e:
            logger.error(f"Failed to load from SQLite: {e}")
        finally:
            if conn:
                conn.close()
    
    def _load_from_creds_file(self):
        """Load credentials from JSON file"""
        if not self.creds_file:
            return
        
        # Expand ~ in path
        creds_path = Path(self.creds_file).expanduser()
        
        try:
            with open(creds_path, 'r') as f:
                data = json.load(f)
                
            refresh_token_value = data.get('refreshToken', self.refresh_token)
            self.refresh_token = refresh_token_value
            self._refresh_token = refresh_token_value  # Keep private token in sync
            self._access_token = data.get('accessToken')
            self.profile_arn = data.get('profileArn', self.profile_arn)
            
            if 'expiresAt' in data:
                self._expires_at = datetime.fromisoformat(
                    data['expiresAt'].replace('Z', '+00:00')
                )
                
        except Exception as e:
            logger.error(f"Failed to load credentials file: {e}")
    
    def _get_machine_fingerprint(self):
        """Generate machine fingerprint for User-Agent"""
        try:
            hostname = socket.gethostname()
            username = getpass.getuser()
            unique_string = f"{hostname}-{username}-kiro-gateway"
            return hashlib.sha256(unique_string.encode()).hexdigest()
        except:
            return hashlib.sha256(b"default-machine-fingerprint").hexdigest()
    
    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary"""
        async with self._lock:
            if self._access_token and self._expires_at and self._expires_at > datetime.now(timezone.utc):
                return self._access_token
            
            # Need to refresh token
            if self._auth_type == AuthType.AWS_SSO_OIDC:
                await self._refresh_aws_sso_token()
            else:
                await self._refresh_kiro_desktop_token()
            
            return self._access_token
    
    async def _refresh_kiro_desktop_token(self):
        """Refresh token using Kiro Desktop Auth"""
        if not self.refresh_token:
            raise ValueError("No refresh token available")
        
        url = f"https://prod.{self.region}.auth.desktop.kiro.dev/refreshToken"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"KiroIDE-0.7.45-{self._get_machine_fingerprint()}"
        }
        payload = {"refreshToken": self.refresh_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data['accessToken']
            if 'refreshToken' in data:
                self.refresh_token = data['refreshToken']
                self._refresh_token = data['refreshToken']  # Keep private token in sync
            
            # Calculate expiration (1 hour default)
            self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=3600)
            
            # Save if we have a credentials file
            if self.creds_file:
                self._save_credentials()
    
    async def _refresh_aws_sso_token(self):
        """Refresh token using AWS SSO OIDC"""
        if not all([self.refresh_token, self.client_id, self.client_secret]):
            raise ValueError("Missing credentials for AWS SSO OIDC")
        
        url = f"https://oidc.{self.region}.amazonaws.com/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=payload)
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data['access_token']
            if 'refresh_token' in data:
                self.refresh_token = data['refresh_token']
                self._refresh_token = data['refresh_token']  # Keep private token in sync
            
            expires_in = data.get('expires_in', 3600)
            self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    
    def _save_credentials(self):
        """Save updated credentials to file"""
        if not self.creds_file:
            return
        
        # Expand ~ in path
        creds_path = Path(self.creds_file).expanduser()
        
        try:
            with open(creds_path, 'r') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        
        data.update({
            'accessToken': self._access_token,
            'refreshToken': self.refresh_token,
            'expiresAt': self._expires_at.isoformat() if self._expires_at else None,
            'profileArn': self.profile_arn,
            'region': self.region
        })
        
        with open(creds_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_auth_headers(self, token: str) -> dict:
        """Get headers for Kiro API requests"""
        fingerprint = self._get_machine_fingerprint()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"aws-sdk-js/1.0.27 KiroIDE-0.7.45-{fingerprint}",
            "x-amz-user-agent": f"aws-sdk-js/1.0.27 KiroIDE-0.7.45-{fingerprint}",
            "x-amz-codewhisperer-optout": "true",
            "x-amzn-kiro-agent-mode": "vibe",
            "amz-sdk-invocation-id": str(uuid.uuid4()),
            "amz-sdk-request": "attempt=1; max=3"
        }
    
    def _get_machine_fingerprint(self):
        """Get machine fingerprint for User-Agent"""
        try:
            import socket
            import getpass
            hostname = socket.gethostname()
            username = getpass.getuser()
            unique_string = f"{hostname}-{username}-kiro-gateway"
            return hashlib.sha256(unique_string.encode()).hexdigest()
        except:
            return hashlib.sha256(b"default-machine-fingerprint").hexdigest()