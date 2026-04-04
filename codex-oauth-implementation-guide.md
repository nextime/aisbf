# Codex OAuth 2.1 Implementation Guide

This document explains how the Codex CLI performs OAuth 2.1 authentication, how tokens are managed, and how they are used to make API requests. It includes Python examples so you can reimplement the flow in your own code.

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication Flows](#authentication-flows)
3. [Browser-Based Login (Authorization Code + PKCE)](#browser-based-login-authorization-code--pkce)
4. [Device Code Login](#device-code-login)
5. [Token Refresh](#token-refresh)
6. [Token Exchange for API Key](#token-exchange-for-api-key)
7. [How Tokens Are Used for API Requests](#how-tokens-are-used-for-api-requests)
8. [Credential Storage](#credential-storage)
9. [Complete Python Implementation](#complete-python-implementation)
10. [Key Constants and Endpoints](#key-constants-and-endpoints)

---

## Overview

Codex uses OAuth 2.1 with the following characteristics:

- **Public client**: No client secret is used (CLI apps cannot securely store secrets)
- **PKCE (Proof Key for Code Exchange)**: Required for the authorization code flow to prevent authorization code interception attacks
- **Two login methods**:
  1. **Browser-based login**: Standard OAuth 2.1 Authorization Code flow with PKCE
  2. **Device Code login**: For headless/remote environments where a browser is not available
- **Token types**: The OAuth flow returns three tokens:
  - `id_token`: JWT containing user identity claims
  - `access_token`: JWT used for API authentication (Bearer token)
  - `refresh_token`: Long-lived token used to obtain new access tokens
- **Token exchange**: The `id_token` can be exchanged for an OpenAI API key via a separate endpoint

### Key Endpoints

| Endpoint | URL |
|----------|-----|
| Authorization | `https://auth.openai.com/oauth/authorize` |
| Token | `https://auth.openai.com/oauth/token` |
| Device Code User Code | `https://auth.openai.com/api/accounts/deviceauth/usercode` |
| Device Code Token Poll | `https://auth.openai.com/api/accounts/deviceauth/token` |
| Token Refresh | `https://auth.openai.com/oauth/token` |

### Client ID

```
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
```

---

## Authentication Flows

### 1. Browser-Based Login (Authorization Code + PKCE)

This is the default flow when running `codex login` in a terminal with browser access.

#### Step 1: Generate PKCE Codes

PKCE requires two values:
- `code_verifier`: A cryptographically random string (43-128 characters)
- `code_challenge`: `BASE64URL(SHA256(code_verifier))`

```python
import secrets
import hashlib
import base64

def generate_pkce():
    # Generate a random 64-byte verifier
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b'=').decode()
    
    # Create the challenge: BASE64URL(SHA256(verifier))
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    
    return code_verifier, code_challenge
```

#### Step 2: Generate State Parameter

The `state` parameter prevents CSRF attacks. It should be a cryptographically random value.

```python
import secrets
import base64

def generate_state():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
```

#### Step 3: Build Authorization URL

```python
import urllib.parse

def build_authorization_url(
    issuer: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access api.connectors.read api.connectors.invoke",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "codex_cli",
    }
    
    query_string = urllib.parse.urlencode(params)
    return f"{issuer}/oauth/authorize?{query_string}"
```

#### Step 4: Start Local Callback Server

Codex starts a local HTTP server on `localhost:1455` to receive the OAuth callback. The redirect URI is `http://localhost:{port}/auth/callback`.

```python
import http.server
import threading
from urllib.parse import urlparse, parse_qs

class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == "/auth/callback":
            # Store the callback data
            self.server.auth_code = params.get("code", [None])[0]
            self.server.state = params.get("state", [None])[0]
            self.server.error = params.get("error", [None])[0]
            
            # Send response
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/success")
            self.end_headers()
        elif parsed.path == "/success":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Login successful! You can close this window.</h1>")
        elif parsed.path == "/cancel":
            self.send_response(200)
            self.wfile.write(b"Login cancelled")
    
    def log_message(self, format, *args):
        pass  # Suppress logging

def start_callback_server(port=1455):
    server = http.server.HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
    server.auth_code = None
    server.state = None
    server.error = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
```

#### Step 5: Open Browser and Wait for Callback

```python
import webbrowser

def run_browser_login(issuer, client_id, port=1455):
    code_verifier, code_challenge = generate_pkce()
    state = generate_state()
    redirect_uri = f"http://localhost:{port}/auth/callback"
    
    auth_url = build_authorization_url(
        issuer, client_id, redirect_uri, code_challenge, state
    )
    
    # Start callback server
    server = start_callback_server(port)
    
    # Open browser
    webbrowser.open(auth_url)
    
    # Wait for callback (with timeout)
    import time
    timeout = 300  # 5 minutes
    start = time.time()
    while server.auth_code is None and server.error is None:
        if time.time() - start > timeout:
            server.shutdown()
            raise TimeoutError("Login timed out")
        time.sleep(0.5)
    
    if server.error:
        server.shutdown()
        raise Exception(f"OAuth error: {server.error}")
    
    server.shutdown()
    return server.auth_code, state, code_verifier, redirect_uri
```

#### Step 6: Exchange Authorization Code for Tokens

```python
import requests
import urllib.parse

def exchange_code_for_tokens(
    issuer: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    code: str,
) -> dict:
    token_url = f"{issuer}/oauth/token"
    
    body = (
        f"grant_type=authorization_code"
        f"&code={urllib.parse.quote(code)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&code_verifier={urllib.parse.quote(code_verifier)}"
    )
    
    response = requests.post(
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    response.raise_for_status()
    
    return response.json()
    # Returns: {"id_token": "...", "access_token": "...", "refresh_token": "..."}
```

---

### 2. Device Code Login

Used for headless environments where a browser is not available.

#### Step 1: Request Device Code

```python
import requests

def request_device_code(issuer: str, client_id: str) -> dict:
    url = f"{issuer}/api/accounts/deviceauth/usercode"
    
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={"client_id": client_id},
    )
    response.raise_for_status()
    
    return response.json()
    # Returns: {"device_auth_id": "...", "user_code": "...", "interval": "5"}
```

#### Step 2: Display Instructions to User

```python
def display_device_instructions(issuer: str, device_code_resp: dict):
    verification_url = f"{issuer}/codex/device"
    user_code = device_code_resp["user_code"]
    
    print(f"\nFollow these steps to sign in with ChatGPT using device code authorization:\n")
    print(f"1. Open this link in your browser and sign in to your account")
    print(f"   {verification_url}")
    print(f"\n2. Enter this one-time code (expires in 15 minutes)")
    print(f"   {user_code}")
    print(f"\nDevice codes are a common phishing target. Never share this code.\n")
```

#### Step 3: Poll for Token

```python
import time
from datetime import datetime, timedelta

def poll_for_token(
    issuer: str,
    device_auth_id: str,
    user_code: str,
    interval: int = 5,
) -> dict:
    url = f"{issuer}/api/accounts/deviceauth/token"
    max_wait = timedelta(minutes=15)
    start = datetime.now()
    
    while True:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "device_auth_id": device_auth_id,
                "user_code": user_code,
            },
        )
        
        if response.status_code == 200:
            return response.json()
            # Returns: {"authorization_code": "...", "code_challenge": "...", "code_verifier": "..."}
        
        if response.status_code in (403, 404):
            if datetime.now() - start > max_wait:
                raise TimeoutError("Device auth timed out after 15 minutes")
            time.sleep(interval)
            continue
        
        raise Exception(f"Device auth failed with status {response.status_code}")
```

#### Step 4: Exchange for Tokens

The device code flow returns PKCE codes directly, so you use them to exchange for tokens:

```python
def complete_device_code_login(issuer: str, client_id: str, token_resp: dict) -> dict:
    redirect_uri = f"{issuer}/deviceauth/callback"
    
    return exchange_code_for_tokens(
        issuer=issuer,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_verifier=token_resp["code_verifier"],
        code=token_resp["authorization_code"],
    )
```

---

## Token Refresh

Access tokens expire. Use the refresh token to obtain new tokens without re-authenticating.

```python
def refresh_tokens(issuer: str, client_id: str, refresh_token: str) -> dict:
    token_url = f"{issuer}/oauth/token"
    
    response = requests.post(
        token_url,
        headers={"Content-Type": "application/json"},
        json={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    
    if response.status_code == 401:
        # Refresh token expired or invalid - user must re-authenticate
        body = response.json()
        error_code = body.get("error", {})
        if isinstance(error_code, dict):
            error_code = error_code.get("code", "unknown")
        
        if error_code == "refresh_token_expired":
            raise Exception("Your refresh token has expired. Please log out and sign in again.")
        elif error_code == "refresh_token_reused":
            raise Exception("Your refresh token was already used. Please log out and sign in again.")
        elif error_code == "refresh_token_invalidated":
            raise Exception("Your refresh token was revoked. Please log out and sign in again.")
        else:
            raise Exception("Your access token could not be refreshed. Please log out and sign in again.")
    
    response.raise_for_status()
    return response.json()
    # Returns: {"id_token": "...", "access_token": "...", "refresh_token": "..."}
```

**Important**: The refresh token may change with each refresh (token rotation). Always save the new refresh token if one is returned.

---

## Token Exchange for API Key

Codex can exchange the `id_token` for an OpenAI API key:

```python
def obtain_api_key(issuer: str, client_id: str, id_token: str) -> str:
    token_url = f"{issuer}/oauth/token"
    
    body = (
        f"grant_type={urllib.parse.quote('urn:ietf:params:oauth:grant-type:token-exchange')}"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&requested_token={urllib.parse.quote('openai-api-key')}"
        f"&subject_token={urllib.parse.quote(id_token)}"
        f"&subject_token_type={urllib.parse.quote('urn:ietf:params:oauth:token-type:id_token')}"
    )
    
    response = requests.post(
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    response.raise_for_status()
    
    return response.json()["access_token"]
```

---

## How Tokens Are Used for API Requests

### Bearer Token Authentication

The `access_token` is used as a Bearer token in the `Authorization` header:

```python
import requests

def make_api_request(access_token: str, url: str, method: str = "GET", **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {access_token}"
    
    response = requests.request(method, url, headers=headers, **kwargs)
    
    if response.status_code == 401:
        # Token may have expired - refresh and retry
        raise TokenExpiredError("Access token expired")
    
    return response
```

### Token Data Structure

Codex stores the following token data:

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class IdTokenInfo:
    email: Optional[str]
    chatgpt_plan_type: Optional[str]  # "free", "plus", "pro", "business", "enterprise", "edu"
    chatgpt_user_id: Optional[str]
    chatgpt_account_id: Optional[str]  # Workspace/organization ID
    raw_jwt: str

@dataclass
class TokenData:
    id_token: IdTokenInfo
    access_token: str
    refresh_token: str
    account_id: Optional[str]
```

### Parsing JWT Claims

```python
import base64
import json

def parse_jwt_claims(jwt_token: str) -> dict:
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

def parse_chatgpt_jwt_claims(jwt_token: str) -> IdTokenInfo:
    claims = parse_jwt_claims(jwt_token)
    
    # Extract email from top-level or profile claim
    email = claims.get("email")
    profile = claims.get("https://api.openai.com/profile", {})
    if not email and profile:
        email = profile.get("email")
    
    # Extract auth claims
    auth = claims.get("https://api.openai.com/auth", {})
    
    return IdTokenInfo(
        email=email,
        chatgpt_plan_type=auth.get("chatgpt_plan_type"),
        chatgpt_user_id=auth.get("chatgpt_user_id") or auth.get("user_id"),
        chatgpt_account_id=auth.get("chatgpt_account_id"),
        raw_jwt=jwt_token,
    )
```

---

## Credential Storage

Codex stores credentials in `~/.codex/auth.json`:

```json
{
  "auth_mode": "chatgpt",
  "tokens": {
    "id_token": "<JWT>",
    "access_token": "<JWT>",
    "refresh_token": "<string>",
    "account_id": "<string>"
  },
  "last_refresh": "2024-01-01T00:00:00Z"
}
```

Alternatively, credentials can be stored in the system keyring (macOS Keychain, Windows Credential Manager, etc.) when configured.

---

## Complete Python Implementation

Here's a complete, reusable Python class that implements the full OAuth flow:

```python
"""
Codex OAuth 2.1 Client Implementation

This module provides a complete implementation of the OAuth 2.1 flows used by Codex CLI,
including browser-based login with PKCE, device code login, token refresh, and API key exchange.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests


# Constants
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_ISSUER = "https://auth.openai.com"
DEFAULT_PORT = 1455
SCOPES = "openid profile email offline_access api.connectors.read api.connectors.invoke"


@dataclass
class IdTokenInfo:
    """Parsed ID token claims."""
    email: Optional[str] = None
    chatgpt_plan_type: Optional[str] = None
    chatgpt_user_id: Optional[str] = None
    chatgpt_account_id: Optional[str] = None
    raw_jwt: str = ""


@dataclass
class TokenData:
    """Complete token data stored after authentication."""
    id_token: IdTokenInfo
    access_token: str
    refresh_token: str
    account_id: Optional[str] = None


@dataclass
class AuthData:
    """Full authentication data stored to disk."""
    auth_mode: str = "chatgpt"
    tokens: Optional[TokenData] = None
    openai_api_key: Optional[str] = None
    last_refresh: Optional[str] = None


class CodexOAuthClient:
    """OAuth 2.1 client for Codex authentication."""
    
    def __init__(
        self,
        issuer: str = DEFAULT_ISSUER,
        client_id: str = CLIENT_ID,
        codex_home: Optional[Path] = None,
    ):
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.codex_home = codex_home or Path.home() / ".codex"
        self.session = requests.Session()
    
    # -------------------------------------------------------------------------
    # PKCE Helpers
    # -------------------------------------------------------------------------
    
    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        """Generate PKCE code verifier and challenge."""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        return code_verifier, code_challenge
    
    @staticmethod
    def generate_state() -> str:
        """Generate CSRF state parameter."""
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    
    # -------------------------------------------------------------------------
    # Authorization URL
    # -------------------------------------------------------------------------
    
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
            "client_id": self.client_id,
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
    
    # -------------------------------------------------------------------------
    # Token Exchange
    # -------------------------------------------------------------------------
    
    def exchange_code_for_tokens(
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
            f"&client_id={urllib.parse.quote(self.client_id)}"
            f"&code_verifier={urllib.parse.quote(code_verifier)}"
        )
        
        response = self.session.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body,
        )
        response.raise_for_status()
        return response.json()
    
    # -------------------------------------------------------------------------
    # Token Refresh
    # -------------------------------------------------------------------------
    
    def refresh_tokens(self, refresh_token: str) -> dict:
        """Refresh tokens using the refresh token."""
        token_url = f"{self.issuer}/oauth/token"
        
        response = self.session.post(
            token_url,
            headers={"Content-Type": "application/json"},
            json={
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
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
    
    # -------------------------------------------------------------------------
    # API Key Exchange
    # -------------------------------------------------------------------------
    
    def obtain_api_key(self, id_token: str) -> str:
        """Exchange ID token for an OpenAI API key."""
        token_url = f"{self.issuer}/oauth/token"
        
        body = (
            f"grant_type={urllib.parse.quote('urn:ietf:params:oauth:grant-type:token-exchange')}"
            f"&client_id={urllib.parse.quote(self.client_id)}"
            f"&requested_token={urllib.parse.quote('openai-api-key')}"
            f"&subject_token={urllib.parse.quote(id_token)}"
            f"&subject_token_type={urllib.parse.quote('urn:ietf:params:oauth:token-type:id_token')}"
        )
        
        response = self.session.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body,
        )
        response.raise_for_status()
        return response.json()["access_token"]
    
    # -------------------------------------------------------------------------
    # Device Code Flow
    # -------------------------------------------------------------------------
    
    def request_device_code(self) -> dict:
        """Request a device code for headless login."""
        url = f"{self.issuer}/api/accounts/deviceauth/usercode"
        
        response = self.session.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"client_id": self.client_id},
        )
        response.raise_for_status()
        return response.json()
    
    def poll_device_code_token(
        self,
        device_auth_id: str,
        user_code: str,
        interval: int = 5,
    ) -> dict:
        """Poll for device code token."""
        url = f"{self.issuer}/api/accounts/deviceauth/token"
        max_wait = timedelta(minutes=15)
        start = datetime.now()
        
        while True:
            response = self.session.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "device_auth_id": device_auth_id,
                    "user_code": user_code,
                },
            )
            
            if response.status_code == 200:
                return response.json()
            
            if response.status_code in (403, 404):
                if datetime.now() - start > max_wait:
                    raise TimeoutError("Device auth timed out after 15 minutes")
                time.sleep(interval)
                continue
            
            raise Exception(f"Device auth failed with status {response.status_code}")
    
    def run_device_code_login(self) -> TokenData:
        """Complete device code login flow."""
        # Step 1: Request device code
        device_resp = self.request_device_code()
        device_auth_id = device_resp["device_auth_id"]
        user_code = device_resp["user_code"]
        interval = int(device_resp.get("interval", 5))
        
        # Step 2: Display instructions
        verification_url = f"{self.issuer}/codex/device"
        print(f"\nFollow these steps to sign in:\n")
        print(f"1. Open this link and sign in:")
        print(f"   {verification_url}")
        print(f"\n2. Enter this code (expires in 15 minutes):")
        print(f"   {user_code}")
        print(f"\nNever share this code.\n")
        
        # Step 3: Poll for token
        token_resp = self.poll_device_code_token(device_auth_id, user_code, interval)
        
        # Step 4: Exchange for tokens
        redirect_uri = f"{self.issuer}/deviceauth/callback"
        tokens = self.exchange_code_for_tokens(
            code=token_resp["authorization_code"],
            redirect_uri=redirect_uri,
            code_verifier=token_resp["code_verifier"],
        )
        
        return self._build_token_data(tokens)
    
    # -------------------------------------------------------------------------
    # JWT Parsing
    # -------------------------------------------------------------------------
    
    @staticmethod
    def parse_jwt_claims(jwt_token: str) -> dict:
        """Parse JWT payload."""
        parts = jwt_token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    
    def parse_id_token(self, jwt_token: str) -> IdTokenInfo:
        """Parse ID token into structured claims."""
        claims = self.parse_jwt_claims(jwt_token)
        
        email = claims.get("email")
        profile = claims.get("https://api.openai.com/profile", {})
        if not email and profile:
            email = profile.get("email")
        
        auth = claims.get("https://api.openai.com/auth", {})
        
        return IdTokenInfo(
            email=email,
            chatgpt_plan_type=auth.get("chatgpt_plan_type"),
            chatgpt_user_id=auth.get("chatgpt_user_id") or auth.get("user_id"),
            chatgpt_account_id=auth.get("chatgpt_account_id"),
            raw_jwt=jwt_token,
        )
    
    # -------------------------------------------------------------------------
    # Token Data Building
    # -------------------------------------------------------------------------
    
    def _build_token_data(self, tokens: dict) -> TokenData:
        """Build TokenData from token response."""
        id_token_info = self.parse_id_token(tokens["id_token"])
        
        account_id = id_token_info.chatgpt_account_id
        return TokenData(
            id_token=id_token_info,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            account_id=account_id,
        )
    
    # -------------------------------------------------------------------------
    # Credential Storage
    # -------------------------------------------------------------------------
    
    def save_auth(self, auth_data: AuthData) -> None:
        """Save authentication data to auth.json."""
        self.codex_home.mkdir(parents=True, exist_ok=True)
        auth_path = self.codex_home / "auth.json"
        
        with open(auth_path, "w") as f:
            json.dump(
                {
                    "auth_mode": auth_data.auth_mode,
                    "openai_api_key": auth_data.openai_api_key,
                    "tokens": {
                        "id_token": auth_data.tokens.id_token.raw_jwt if auth_data.tokens else None,
                        "access_token": auth_data.tokens.access_token if auth_data.tokens else None,
                        "refresh_token": auth_data.tokens.refresh_token if auth_data.tokens else None,
                        "account_id": auth_data.tokens.account_id if auth_data.tokens else None,
                    } if auth_data.tokens else None,
                    "last_refresh": auth_data.last_refresh,
                },
                f,
                indent=2,
            )
        
        # Set restrictive permissions on Unix
        import os
        if os.name == "posix":
            os.chmod(auth_path, 0o600)
    
    def load_auth(self) -> Optional[AuthData]:
        """Load authentication data from auth.json."""
        auth_path = self.codex_home / "auth.json"
        if not auth_path.exists():
            return None
        
        with open(auth_path) as f:
            data = json.load(f)
        
        tokens = None
        if data.get("tokens"):
            t = data["tokens"]
            tokens = TokenData(
                id_token=self.parse_id_token(t["id_token"]),
                access_token=t["access_token"],
                refresh_token=t["refresh_token"],
                account_id=t.get("account_id"),
            )
        
        return AuthData(
            auth_mode=data.get("auth_mode", "chatgpt"),
            tokens=tokens,
            openai_api_key=data.get("openai_api_key"),
            last_refresh=data.get("last_refresh"),
        )
    
    # -------------------------------------------------------------------------
    # Making Authenticated API Requests
    # -------------------------------------------------------------------------
    
    def get_bearer_token(self) -> str:
        """Get the current access token, refreshing if needed."""
        auth = self.load_auth()
        if not auth or not auth.tokens:
            raise Exception("Not authenticated. Please run login first.")
        
        # Check if token is expired (with 5 minute buffer)
        claims = self.parse_jwt_claims(auth.tokens.access_token)
        exp = claims.get("exp", 0)
        if exp < time.time() + 300:
            # Token expired or about to expire - refresh
            new_tokens = self.refresh_tokens(auth.tokens.refresh_token)
            token_data = self._build_token_data(new_tokens)
            
            auth.tokens = token_data
            auth.last_refresh = datetime.utcnow().isoformat() + "Z"
            self.save_auth(auth)
            
            return token_data.access_token
        
        return auth.tokens.access_token
    
    def make_api_request(
        self,
        method: str,
        url: str,
        max_retries: int = 1,
        **kwargs,
    ) -> requests.Response:
        """Make an authenticated API request with automatic token refresh."""
        headers = kwargs.pop("headers", {})
        
        for attempt in range(max_retries + 1):
            token = self.get_bearer_token()
            headers["Authorization"] = f"Bearer {token}"
            
            response = self.session.request(method, url, headers=headers, **kwargs)
            
            if response.status_code == 401 and attempt < max_retries:
                # Force refresh and retry
                auth = self.load_auth()
                if auth and auth.tokens:
                    new_tokens = self.refresh_tokens(auth.tokens.refresh_token)
                    token_data = self._build_token_data(new_tokens)
                    auth.tokens = token_data
                    auth.last_refresh = datetime.utcnow().isoformat() + "Z"
                    self.save_auth(auth)
                continue
            
            return response
        
        response.raise_for_status()
        return response


# -------------------------------------------------------------------------
# Usage Examples
# -------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    
    client = CodexOAuthClient()
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python oauth_client.py login          # Browser login")
        print("  python oauth_client.py device-login   # Device code login")
        print("  python oauth_client.py status         # Check auth status")
        print("  python oauth_client.py refresh        # Refresh tokens")
        print("  python oauth_client.py api-key        # Get API key")
        print("  python oauth_client.py request <URL>  # Make API request")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "login":
        print("Browser login is best implemented with a local callback server.")
        print("Use 'device-login' for headless environments.")
    
    elif command == "device-login":
        token_data = client.run_device_code_login()
        
        # Optionally obtain an API key
        try:
            api_key = client.obtain_api_key(token_data.id_token.raw_jwt)
        except Exception:
            api_key = None
        
        auth_data = AuthData(
            auth_mode="chatgpt",
            tokens=token_data,
            openai_api_key=api_key,
            last_refresh=datetime.utcnow().isoformat() + "Z",
        )
        client.save_auth(auth_data)
        print("Successfully logged in!")
    
    elif command == "status":
        auth = client.load_auth()
        if auth and auth.tokens:
            print(f"Logged in as: {auth.tokens.id_token.email}")
            print(f"Plan: {auth.tokens.id_token.chatgpt_plan_type}")
            print(f"Account: {auth.tokens.id_token.chatgpt_account_id}")
            if auth.openai_api_key:
                key = auth.openai_api_key
                masked = f"{key[:8]}***{key[-5:]}" if len(key) > 13 else "***"
                print(f"API Key: {masked}")
        else:
            print("Not logged in.")
            sys.exit(1)
    
    elif command == "refresh":
        auth = client.load_auth()
        if not auth or not auth.tokens:
            print("Not logged in.")
            sys.exit(1)
        
        new_tokens = client.refresh_tokens(auth.tokens.refresh_token)
        token_data = client._build_token_data(new_tokens)
        auth.tokens = token_data
        auth.last_refresh = datetime.utcnow().isoformat() + "Z"
        client.save_auth(auth)
        print("Tokens refreshed successfully!")
    
    elif command == "api-key":
        auth = client.load_auth()
        if not auth or not auth.tokens:
            print("Not logged in.")
            sys.exit(1)
        
        api_key = client.obtain_api_key(auth.tokens.id_token.raw_jwt)
        print(f"API Key: {api_key}")
    
    elif command == "request":
        if len(sys.argv) < 3:
            print("Usage: python oauth_client.py request <URL>")
            sys.exit(1)
        
        url = sys.argv[2]
        response = client.make_api_request("GET", url)
        print(response.text)
```

---

## Key Constants and Endpoints

| Constant | Value |
|----------|-------|
| Client ID | `app_EMoamEEZ73f0CkXaXp7hrann` |
| Default Issuer | `https://auth.openai.com` |
| Default Callback Port | `1455` |
| Scopes | `openid profile email offline_access api.connectors.read api.connectors.invoke` |
| Originator | `codex_cli` |
| Refresh Token URL | `https://auth.openai.com/oauth/token` |
| Token Rotation | Yes - refresh token may change on each refresh |

### Auth JSON File Location

- **Default**: `~/.codex/auth.json`
- **Permissions**: `0600` (owner read/write only on Unix)

### Error Codes

| Error Code | Meaning |
|------------|---------|
| `refresh_token_expired` | Refresh token has expired |
| `refresh_token_reused` | Refresh token was already used (single-use) |
| `refresh_token_invalidated` | Refresh token was revoked |
| `access_denied` + `missing_codex_entitlement` | User doesn't have Codex access |

---

## Summary of the OAuth 2.1 Flow

1. **PKCE Generation**: Generate `code_verifier` and `code_challenge` (SHA256 hash, base64url encoded)
2. **Authorization Request**: Redirect user to `/oauth/authorize` with PKCE challenge
3. **User Authentication**: User signs in at the OpenAI auth provider
4. **Callback**: Auth server redirects to `localhost:1455/auth/callback` with `code` and `state`
5. **Token Exchange**: Exchange `code` + `code_verifier` for `id_token`, `access_token`, `refresh_token`
6. **API Key Exchange** (optional): Exchange `id_token` for an OpenAI API key
7. **Storage**: Save tokens to `~/.codex/auth.json`
8. **Usage**: Use `access_token` as Bearer token for API requests
9. **Refresh**: Use `refresh_token` to get new tokens when `access_token` expires
