# Qwen Code OAuth2 Flow Analysis

> **Purpose**: This document provides a comprehensive analysis of the Qwen Code OAuth2 initialization flow, token management, and API request patterns. It includes Python reimplementation examples for building an independent OAuth2 client.

---

## Table of Contents

1. [Overview](#overview)
2. [OAuth2 Constants and Configuration](#oauth2-constants-and-configuration)
3. [PKCE (Proof Key for Code Exchange)](#pkce-proof-key-for-code-exchange)
4. [Device Authorization Flow](#device-authorization-flow)
5. [Token Polling](#token-polling)
6. [Token Refresh](#token-refresh)
7. [Credential Storage](#credential-storage)
8. [SharedTokenManager - Cross-Process Token Synchronization](#sharedtokenmanager---cross-process-token-synchronization)
9. [Making API Requests with OAuth Tokens](#making-api-requests-with-oauth-tokens)
10. [Complete Python Implementation](#complete-python-implementation)
11. [Error Handling and Edge Cases](#error-handling-and-edge-cases)

---

## Overview

Qwen Code uses the **OAuth 2.0 Device Authorization Grant** flow ([RFC 8628](https://datatracker.ietf.org/doc/html/rfc8628)) combined with **PKCE** ([RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636)) for secure authentication. This flow is designed for devices that cannot easily open a browser or handle redirects.

### Key Characteristics

- **Grant Type**: `urn:ietf:params:oauth:grant-type:device_code`
- **PKCE Method**: S256 (SHA-256 code challenge)
- **Token Endpoint**: `https://chat.qwen.ai/api/v1/oauth2/token`
- **Device Code Endpoint**: `https://chat.qwen.ai/api/v1/oauth2/device/code`
- **Client ID**: `f0304373b74a44d2b584a3fb70ca9e56`
- **Scopes**: `openid profile email model.completion`

### Flow Summary

1. Generate PKCE code verifier and challenge
2. Request a device code from the authorization server
3. Display the authorization URL to the user
4. Poll the token endpoint until the user approves
5. Store credentials to disk (`~/.qwen/oauth_creds.json`)
6. Use the access token for API requests
7. Refresh the token when it expires (30-second buffer before expiry)

---

## OAuth2 Constants and Configuration

These are the fixed constants used throughout the OAuth2 flow:

```typescript
// Source: packages/core/src/qwen/qwenOAuth2.ts
const QWEN_OAUTH_BASE_URL = 'https://chat.qwen.ai';
const QWEN_OAUTH_DEVICE_CODE_ENDPOINT = `${QWEN_OAUTH_BASE_URL}/api/v1/oauth2/device/code`;
const QWEN_OAUTH_TOKEN_ENDPOINT = `${QWEN_OAUTH_BASE_URL}/api/v1/oauth2/token`;
const QWEN_OAUTH_CLIENT_ID = 'f0304373b74a44d2b584a3fb70ca9e56';
const QWEN_OAUTH_SCOPE = 'openid profile email model.completion';
const QWEN_OAUTH_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:device_code';
```

### API Endpoints

| Endpoint | URL |
|----------|-----|
| Base URL | `https://chat.qwen.ai` |
| Device Code | `https://chat.qwen.ai/api/v1/oauth2/device/code` |
| Token | `https://chat.qwen.ai/api/v1/oauth2/token` |

### Default Model

- **Model ID**: `coder-model` (maps to `qwen3.6-plus` internally)
- **Default API Base URL**: `https://dashscope.aliyuncs.com/compatible-mode/v1`

---

## PKCE (Proof Key for Code Exchange)

PKCE adds an extra layer of security by generating a code verifier and its SHA-256 hash (code challenge).

### TypeScript Implementation

```typescript
// Source: packages/core/src/qwen/qwenOAuth2.ts (lines 47-77)

import crypto from 'crypto';

export function generateCodeVerifier(): string {
  return crypto.randomBytes(32).toString('base64url');
}

export function generateCodeChallenge(codeVerifier: string): string {
  const hash = crypto.createHash('sha256');
  hash.update(codeVerifier);
  return hash.digest('base64url');
}

export function generatePKCEPair(): {
  code_verifier: string;
  code_challenge: string;
} {
  const codeVerifier = generateCodeVerifier();
  const codeChallenge = generateCodeChallenge(codeVerifier);
  return { code_verifier: codeVerifier, code_challenge: codeChallenge };
}
```

### Python Implementation

```python
import base64
import hashlib
import secrets


def generate_code_verifier() -> str:
    """Generate a random code verifier for PKCE (43-128 characters)."""
    # 32 random bytes = 256 bits, base64url encoded = 43 characters
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def generate_code_challenge(code_verifier: str) -> str:
    """Generate a code challenge from a code verifier using SHA-256."""
    sha256_hash = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(sha256_hash).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge pair.
    
    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    return code_verifier, code_challenge
```

---

## Device Authorization Flow

The device authorization flow begins by requesting a device code from the server.

### Request

```http
POST /api/v1/oauth2/device/code HTTP/1.1
Host: chat.qwen.ai
Content-Type: application/x-www-form-urlencoded
Accept: application/json
x-request-id: <UUID>

client_id=f0304373b74a44d2b584a3fb70ca9e56&scope=openid+profile+email+model.completion&code_challenge=<CHALLENGE>&code_challenge_method=S256
```

### Response (Success)

```json
{
  "device_code": "abc123...",
  "user_code": "ABCD-1234",
  "verification_uri": "https://chat.qwen.ai/api/v1/oauth2/device/verify",
  "verification_uri_complete": "https://chat.qwen.ai/api/v1/oauth2/device/verify?user_code=ABCD-1234",
  "expires_in": 600,
  "interval": 5
}
```

### TypeScript Implementation

```typescript
// Source: packages/core/src/qwen/qwenOAuth2.ts (lines 291-332)

async requestDeviceAuthorization(options: {
  scope: string;
  code_challenge: string;
  code_challenge_method: string;
}): Promise<DeviceAuthorizationResponse> {
  const bodyData = {
    client_id: QWEN_OAUTH_CLIENT_ID,
    scope: options.scope,
    code_challenge: options.code_challenge,
    code_challenge_method: options.code_challenge_method,
  };

  const response = await fetch(QWEN_OAUTH_DEVICE_CODE_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
      'x-request-id': randomUUID(),
    },
    body: objectToUrlEncoded(bodyData),
  });

  if (!response.ok) {
    const errorData = await response.text();
    throw new Error(
      `Device authorization failed: ${response.status} ${response.statusText}. Response: ${errorData}`,
    );
  }

  const result = (await response.json()) as DeviceAuthorizationResponse;
  if (!isDeviceAuthorizationSuccess(result)) {
    const errorData = result as ErrorData;
    throw new Error(
      `Device authorization failed: ${errorData?.error || 'Unknown error'} - ${errorData?.error_description || 'No details provided'}`,
    );
  }

  return result;
}
```

### Python Implementation

```python
import uuid
import urllib.parse
import urllib.request
import json
from dataclasses import dataclass


@dataclass
class DeviceAuthorizationData:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int = 5


@dataclass
class ErrorData:
    error: str
    error_description: str


def url_encode(data: dict[str, str]) -> str:
    """Convert a dictionary to URL-encoded form data."""
    return urllib.parse.urlencode(data)


async def request_device_authorization(
    code_challenge: str,
    scope: str = "openid profile email model.completion",
    client_id: str = "f0304373b74a44d2b584a3fb70ca9e56",
    base_url: str = "https://chat.qwen.ai",
) -> DeviceAuthorizationData:
    """Request device authorization from the Qwen OAuth2 server.
    
    Args:
        code_challenge: PKCE code challenge (S256).
        scope: OAuth2 scopes to request.
        client_id: OAuth2 client ID.
        base_url: Base URL of the OAuth2 server.
    
    Returns:
        DeviceAuthorizationData on success.
    
    Raises:
        Exception: If the request fails.
    """
    endpoint = f"{base_url}/api/v1/oauth2/device/code"
    body_data = {
        "client_id": client_id,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    
    request = urllib.request.Request(
        endpoint,
        data=url_encode(body_data).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "x-request-id": str(uuid.uuid4()),
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise Exception(
            f"Device authorization failed: {e.code} {e.reason}. Response: {error_body}"
        ) from e
    
    if "device_code" not in result:
        error = result.get("error", "Unknown error")
        description = result.get("error_description", "No details provided")
        raise Exception(f"Device authorization failed: {error} - {description}")
    
    return DeviceAuthorizationData(
        device_code=result["device_code"],
        user_code=result["user_code"],
        verification_uri=result["verification_uri"],
        verification_uri_complete=result["verification_uri_complete"],
        expires_in=result["expires_in"],
        interval=result.get("interval", 5),
    )
```

---

## Token Polling

After obtaining the device code, the client polls the token endpoint until the user approves the authorization.

### Request

```http
POST /api/v1/oauth2/token HTTP/1.1
Host: chat.qwen.ai
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=f0304373b74a44d2b584a3fb70ca9e56&device_code=<DEVICE_CODE>&code_verifier=<CODE_VERIFIER>
```

### Response (Success)

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 7200,
  "scope": "openid profile email model.completion",
  "resource_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

### Response (Pending - User has not approved yet)

```json
{
  "error": "authorization_pending",
  "error_description": "The user has not yet approved the authorization request"
}
```

### Response (Slow Down - Polling too frequently)

```json
{
  "error": "slow_down",
  "error_description": "The client is polling too quickly"
}
```

### TypeScript Implementation

```typescript
// Source: packages/core/src/qwen/qwenOAuth2.ts (lines 334-399)

async pollDeviceToken(options: {
  device_code: string;
  code_verifier: string;
}): Promise<DeviceTokenResponse> {
  const bodyData = {
    grant_type: QWEN_OAUTH_GRANT_TYPE,
    client_id: QWEN_OAUTH_CLIENT_ID,
    device_code: options.device_code,
    code_verifier: options.code_verifier,
  };

  const response = await fetch(QWEN_OAUTH_TOKEN_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body: objectToUrlEncoded(bodyData),
  });

  if (!response.ok) {
    const responseText = await response.text();
    let errorData: ErrorData | null = null;
    try {
      errorData = JSON.parse(responseText) as ErrorData;
    } catch (_parseError) {
      const error = new Error(
        `Device token poll failed: ${response.status} ${response.statusText}. Response: ${responseText}`,
      );
      (error as Error & { status?: number }).status = response.status;
      throw error;
    }

    // OAuth RFC 8628: authorization_pending means continue polling
    if (response.status === 400 && errorData.error === 'authorization_pending') {
      return { status: 'pending' } as DeviceTokenPendingData;
    }

    // OAuth RFC 8628: slow_down means increase polling interval
    if (response.status === 429 && errorData.error === 'slow_down') {
      return { status: 'pending', slowDown: true } as DeviceTokenPendingData;
    }

    // Other 400 errors are real errors
    const error = new Error(
      `Device token poll failed: ${errorData.error || 'Unknown error'} - ${errorData.error_description}`,
    );
    (error as Error & { status?: number }).status = response.status;
    throw error;
  }

  return (await response.json()) as DeviceTokenResponse;
}
```

### Python Implementation

```python
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceTokenData:
    access_token: str
    refresh_token: Optional[str]
    token_type: str
    expires_in: int
    scope: Optional[str] = None
    resource_url: Optional[str] = None


@dataclass
class DeviceTokenPendingData:
    status: str = "pending"
    slow_down: bool = False


async def poll_device_token(
    device_code: str,
    code_verifier: str,
    client_id: str = "f0304373b74a44d2b584a3fb70ca9e56",
    base_url: str = "https://chat.qwen.ai",
    max_attempts: int = 300,
    initial_interval: float = 2.0,
    max_interval: float = 10.0,
) -> DeviceTokenData:
    """Poll the token endpoint until the user approves the authorization.
    
    Args:
        device_code: The device code from the authorization response.
        code_verifier: The PKCE code verifier.
        client_id: OAuth2 client ID.
        base_url: Base URL of the OAuth2 server.
        max_attempts: Maximum number of polling attempts.
        initial_interval: Initial polling interval in seconds.
        max_interval: Maximum polling interval in seconds.
    
    Returns:
        DeviceTokenData on success.
    
    Raises:
        Exception: If polling fails or times out.
    """
    endpoint = f"{base_url}/api/v1/oauth2/token"
    poll_interval = initial_interval
    
    for attempt in range(max_attempts):
        body_data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": device_code,
            "code_verifier": code_verifier,
        }
        
        request = urllib.request.Request(
            endpoint,
            data=url_encode(body_data).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(request) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            
            # Try to parse as JSON for standard OAuth errors
            try:
                error_data = json.loads(error_body)
            except json.JSONDecodeError:
                raise Exception(
                    f"Device token poll failed: {e.code} {e.reason}. Response: {error_body}"
                ) from e
            
            # authorization_pending: continue polling
            if e.code == 400 and error_data.get("error") == "authorization_pending":
                print(f"Polling... (attempt {attempt + 1}/{max_attempts})")
                time.sleep(poll_interval)
                continue
            
            # slow_down: increase polling interval
            if e.code == 429 and error_data.get("error") == "slow_down":
                poll_interval = min(poll_interval * 1.5, max_interval)
                print(f"Server requested slow down, increasing interval to {poll_interval:.1f}s")
                time.sleep(poll_interval)
                continue
            
            # Other errors
            error = error_data.get("error", "Unknown error")
            description = error_data.get("error_description", "No details provided")
            raise Exception(f"Device token poll failed: {error} - {description}")
        
        # Success - check if we got a token
        if "access_token" in result and result["access_token"]:
            return DeviceTokenData(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token"),
                token_type=result.get("token_type", "Bearer"),
                expires_in=result.get("expires_in", 7200),
                scope=result.get("scope"),
                resource_url=result.get("resource_url"),
            )
        
        # Unexpected response
        raise Exception(f"Unexpected token response: {result}")
    
    raise Exception("Authorization timeout: user did not approve the request in time")
```

---

## Token Refresh

When the access token expires, the client uses the refresh token to obtain a new one.

### Request

```http
POST /api/v1/oauth2/token HTTP/1.1
Host: chat.qwen.ai
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=refresh_token&refresh_token=<REFRESH_TOKEN>&client_id=f0304373b74a44d2b584a3fb70ca9e56
```

### Response (Success)

```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 7200,
  "refresh_token": "eyJ...",
  "resource_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

### Response (Error - Refresh Token Expired)

```json
{
  "error": "invalid_grant",
  "error_description": "The refresh token is invalid or expired"
}
```

### TypeScript Implementation

```typescript
// Source: packages/core/src/qwen/qwenOAuth2.ts (lines 401-463)

async refreshAccessToken(): Promise<TokenRefreshResponse> {
  if (!this.credentials.refresh_token) {
    throw new Error('No refresh token available');
  }

  const bodyData = {
    grant_type: 'refresh_token',
    refresh_token: this.credentials.refresh_token,
    client_id: QWEN_OAUTH_CLIENT_ID,
  };

  const response = await fetch(QWEN_OAUTH_TOKEN_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body: objectToUrlEncoded(bodyData),
  });

  if (!response.ok) {
    const errorData = await response.text();
    // Handle 400 errors which might indicate refresh token expiry
    if (response.status === 400) {
      await clearQwenCredentials();
      throw new CredentialsClearRequiredError(
        "Refresh token expired or invalid. Please use '/auth' to re-authenticate.",
        { status: response.status, response: errorData },
      );
    }
    throw new Error(
      `Token refresh failed: ${response.status} ${response.statusText}. Response: ${errorData}`,
    );
  }

  const responseData = (await response.json()) as TokenRefreshResponse;

  if (isErrorResponse(responseData)) {
    const errorData = responseData as ErrorData;
    throw new Error(
      `Token refresh failed: ${errorData?.error || 'Unknown error'} - ${errorData?.error_description || 'No details provided'}`,
    );
  }

  const tokenData = responseData as TokenRefreshData;
  const tokens: QwenCredentials = {
    access_token: tokenData.access_token,
    token_type: tokenData.token_type,
    refresh_token: tokenData.refresh_token || this.credentials.refresh_token,
    resource_url: tokenData.resource_url,
    expiry_date: Date.now() + tokenData.expires_in * 1000,
  };

  this.setCredentials(tokens);
  return responseData;
}
```

### Python Implementation

```python
@dataclass
class QwenCredentials:
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    expiry_date: Optional[int] = None  # Unix timestamp in milliseconds
    token_type: Optional[str] = None
    resource_url: Optional[str] = None


async def refresh_access_token(
    refresh_token: str,
    client_id: str = "f0304373b74a44d2b584a3fb70ca9e56",
    base_url: str = "https://chat.qwen.ai",
) -> QwenCredentials:
    """Refresh an access token using a refresh token.
    
    Args:
        refresh_token: The refresh token to use.
        client_id: OAuth2 client ID.
        base_url: Base URL of the OAuth2 server.
    
    Returns:
        QwenCredentials with the refreshed tokens.
    
    Raises:
        Exception: If the refresh fails.
    """
    endpoint = f"{base_url}/api/v1/oauth2/token"
    body_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    
    request = urllib.request.Request(
        endpoint,
        data=url_encode(body_data).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        
        # 400 error typically means refresh token is expired/invalid
        if e.code == 400:
            raise Exception(
                "Refresh token expired or invalid. Please re-authenticate."
            ) from e
        
        raise Exception(
            f"Token refresh failed: {e.code} {e.reason}. Response: {error_body}"
        ) from e
    
    if "error" in result:
        raise Exception(
            f"Token refresh failed: {result['error']} - {result.get('error_description', 'No details provided')}"
        )
    
    return QwenCredentials(
        access_token=result["access_token"],
        token_type=result.get("token_type", "Bearer"),
        refresh_token=result.get("refresh_token", refresh_token),
        resource_url=result.get("resource_url"),
        expiry_date=int(time.time() * 1000) + result.get("expires_in", 7200) * 1000,
    )
```

---

## Credential Storage

Credentials are stored in a JSON file at `~/.qwen/oauth_creds.json`.

### File Format

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expiry_date": 1712345678901,
  "resource_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

### Python Implementation

```python
import os
import json
from pathlib import Path


CREDENTIAL_FILENAME = "oauth_creds.json"
QWEN_DIR = ".qwen"


def get_credential_path() -> Path:
    """Get the path to the credentials file."""
    return Path.home() / QWEN_DIR / CREDENTIAL_FILENAME


def save_credentials(credentials: QwenCredentials) -> None:
    """Save credentials to the credentials file.
    
    Args:
        credentials: The credentials to save.
    """
    file_path = get_credential_path()
    file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    # Write to a temporary file first, then rename for atomicity
    temp_path = file_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
                "token_type": credentials.token_type,
                "expiry_date": credentials.expiry_date,
                "resource_url": credentials.resource_url,
            },
            f,
            indent=2,
        )
    
    # Atomic rename
    temp_path.rename(file_path)
    # Set restrictive permissions
    os.chmod(file_path, 0o600)


def load_credentials() -> Optional[QwenCredentials]:
    """Load credentials from the credentials file.
    
    Returns:
        QwenCredentials if valid credentials exist, None otherwise.
    """
    file_path = get_credential_path()
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Validate required fields
        required_fields = ["access_token", "refresh_token", "token_type", "expiry_date"]
        for field in required_fields:
            if field not in data or not data[field]:
                return None
        
        return QwenCredentials(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_type=data["token_type"],
            expiry_date=data["expiry_date"],
            resource_url=data.get("resource_url"),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def clear_credentials() -> None:
    """Delete the credentials file if it exists."""
    file_path = get_credential_path()
    if file_path.exists():
        file_path.unlink()
```

---

## SharedTokenManager - Cross-Process Token Synchronization

The `SharedTokenManager` is a critical component that ensures OAuth tokens are synchronized across multiple processes. This prevents race conditions when multiple instances of Qwen Code are running simultaneously.

### Key Features

1. **Singleton Pattern**: Single instance per process
2. **Memory Cache**: In-memory cache with file modification time tracking
3. **File-Based Locking**: Distributed lock using `oauth_creds.lock` file
4. **Automatic Reload**: Detects when another process has refreshed the token
5. **Token Validation**: Checks expiry with a 30-second buffer
6. **Atomic File Operations**: Uses temp file + rename for safe writes

### Constants

```typescript
// Source: packages/core/src/qwen/sharedTokenManager.ts
const TOKEN_REFRESH_BUFFER_MS = 30 * 1000;  // 30 seconds before expiry
const LOCK_TIMEOUT_MS = 10000;               // 10 seconds lock timeout
const CACHE_CHECK_INTERVAL_MS = 5000;        // 5 seconds between file checks
```

### Lock Acquisition

The lock file is created atomically using the `wx` flag (exclusive write). If the lock is older than 10 seconds, it's considered stale and removed.

### Python Implementation

```python
import fcntl
import time
import uuid
from pathlib import Path
from typing import Optional


LOCK_FILENAME = "oauth_creds.lock"
TOKEN_REFRESH_BUFFER_MS = 30_000  # 30 seconds
LOCK_TIMEOUT_MS = 10_000          # 10 seconds
CACHE_CHECK_INTERVAL_MS = 5_000   # 5 seconds


class SharedTokenManager:
    """Manages OAuth tokens across multiple processes using file-based caching and locking."""
    
    _instance: Optional["SharedTokenManager"] = None
    
    def __init__(self):
        self._credentials: Optional[QwenCredentials] = None
        self._file_mod_time: float = 0
        self._last_check: float = 0
        self._lock_path = Path.home() / QWEN_DIR / LOCK_FILENAME
    
    @classmethod
    def get_instance(cls) -> "SharedTokenManager":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _get_credential_path(self) -> Path:
        return Path.home() / QWEN_DIR / CREDENTIAL_FILENAME
    
    def _is_token_valid(self, credentials: QwenCredentials) -> bool:
        """Check if the token is valid and not expired (with buffer)."""
        if not credentials.expiry_date or not credentials.access_token:
            return False
        now_ms = int(time.time() * 1000)
        return now_ms < credentials.expiry_date - TOKEN_REFRESH_BUFFER_MS
    
    def _acquire_lock(self, max_attempts: int = 20, initial_interval: float = 0.1) -> bool:
        """Acquire a file lock to prevent concurrent token refreshes.
        
        Returns:
            True if lock acquired, False otherwise.
        """
        lock_id = str(uuid.uuid4())
        current_interval = initial_interval
        
        for _ in range(max_attempts):
            try:
                # Try to create lock file atomically (exclusive mode)
                with open(self._lock_path, "x") as f:
                    f.write(lock_id)
                return True
            except FileExistsError:
                # Lock file exists, check if stale
                try:
                    stat = self._lock_path.stat()
                    lock_age = time.time() - stat.st_mtime
                    
                    if lock_age > LOCK_TIMEOUT_MS / 1000:
                        # Remove stale lock
                        self._lock_path.unlink()
                        continue
                except (OSError, FileNotFoundError):
                    # Lock might have been removed by another process
                    continue
                
                time.sleep(current_interval)
                current_interval = min(current_interval * 1.5, 2.0)  # Exponential backoff
        
        return False
    
    def _release_lock(self) -> None:
        """Release the file lock."""
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass  # Lock already removed
    
    def check_and_reload(self) -> None:
        """Check if the credentials file was updated by another process and reload."""
        now = time.time()
        
        # Limit check frequency
        if now - self._last_check < CACHE_CHECK_INTERVAL_MS / 1000:
            return
        
        self._last_check = now
        file_path = self._get_credential_path()
        
        try:
            stat = file_path.stat()
            file_mod_time = stat.st_mtime
            
            if file_mod_time > self._file_mod_time:
                # File has been modified, reload
                creds = load_credentials()
                if creds:
                    self._credentials = creds
                    self._file_mod_time = file_mod_time
        except FileNotFoundError:
            self._file_mod_time = 0
    
    def get_valid_credentials(
        self,
        refresh_func: Optional[callable] = None,
        force_refresh: bool = False,
    ) -> QwenCredentials:
        """Get valid OAuth credentials, refreshing if necessary.
        
        Args:
            refresh_func: Function to call for refreshing tokens.
            force_refresh: If True, refresh even if token is still valid.
        
        Returns:
            Valid QwenCredentials.
        
        Raises:
            Exception: If unable to obtain valid credentials.
        """
        # Check if file was updated by another process
        self.check_and_reload()
        
        # Return cached credentials if valid
        if not force_refresh and self._credentials and self._is_token_valid(self._credentials):
            return self._credentials
        
        # Check if we have a refresh token
        if not self._credentials or not self._credentials.refresh_token:
            raise Exception("No refresh token available")
        
        # Acquire lock for refresh
        if not self._acquire_lock():
            raise Exception("Failed to acquire lock for token refresh")
        
        try:
            # Double-check after acquiring lock
            self.check_and_reload()
            if not force_refresh and self._credentials and self._is_token_valid(self._credentials):
                return self._credentials
            
            # Perform refresh
            if refresh_func:
                new_creds = refresh_func(self._credentials.refresh_token)
                self._credentials = new_creds
                save_credentials(new_creds)
                return new_creds
            
            raise Exception("No refresh function provided")
        finally:
            self._release_lock()
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._credentials = None
        self._file_mod_time = 0
        self._last_check = 0
```

---

## Making API Requests with OAuth Tokens

The `QwenContentGenerator` class handles API requests with automatic credential management and retry logic.

### Flow

1. Get valid credentials from `SharedTokenManager`
2. Set the access token as the `apiKey` on the OpenAI client
3. Set the `resource_url` as the `baseURL` (default: `https://dashscope.aliyuncs.com/compatible-mode/v1`)
4. Make the API request
5. If a 401/403 error occurs, force-refresh the token and retry

### TypeScript Implementation

```typescript
// Source: packages/core/src/qwen/qwenContentGenerator.ts (lines 87-150)

private async getValidToken(): Promise<{ token: string; endpoint: string }> {
  const credentials = await this.sharedManager.getValidCredentials(this.qwenClient);
  
  if (!credentials.access_token) {
    throw new Error('No access token available');
  }
  
  return {
    token: credentials.access_token,
    endpoint: this.getCurrentEndpoint(credentials.resource_url),
  };
}

private async executeWithCredentialManagement<T>(
  operation: () => Promise<T>,
): Promise<T> {
  const attemptOperation = async (): Promise<T> => {
    const { token, endpoint } = await this.getValidToken();
    
    // Apply dynamic configuration
    this.pipeline.client.apiKey = token;
    this.pipeline.client.baseURL = endpoint;
    
    return await operation();
  };
  
  try {
    return await attemptOperation();
  } catch (error) {
    if (this.isAuthError(error)) {
      // Force refresh and retry
      await this.sharedManager.getValidCredentials(this.qwenClient, true);
      return await attemptOperation();
    }
    throw error;
  }
}

override async generateContent(
  request: GenerateContentParameters,
  userPromptId: string,
): Promise<GenerateContentResponse> {
  return this.executeWithCredentialManagement(() =>
    super.generateContent(request, userPromptId),
  );
}
```

### DashScope Provider Headers

```typescript
// Source: packages/core/src/core/openaiContentGenerator/provider/dashscope.ts (lines 40-54)

override buildHeaders(): Record<string, string | undefined> {
  const version = this.cliConfig.getCliVersion() || 'unknown';
  const userAgent = `QwenCode/${version} (${process.platform}; ${process.arch})`;
  const { authType, customHeaders } = this.contentGeneratorConfig;
  
  return {
    'User-Agent': userAgent,
    'X-DashScope-CacheControl': 'enable',
    'X-DashScope-UserAgent': userAgent,
    'X-DashScope-AuthType': authType,  // 'qwen-oauth'
    ...customHeaders,
  };
}
```

### Python Implementation

```python
import urllib.request
import json
from typing import Optional


DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenAPIClient:
    """API client for making requests to the Qwen/DashScope API with OAuth tokens."""
    
    def __init__(
        self,
        token_manager: SharedTokenManager,
        refresh_func: callable,
        model: str = "coder-model",
        base_url: str = DEFAULT_DASHSCOPE_BASE_URL,
    ):
        self._token_manager = token_manager
        self._refresh_func = refresh_func
        self._model = model
        self._base_url = base_url
        self._token: Optional[str] = None
        self._endpoint: Optional[str] = None
    
    def _get_valid_token_and_endpoint(self) -> tuple[str, str]:
        """Get a valid token and endpoint, refreshing if necessary."""
        credentials = self._token_manager.get_valid_credentials(
            refresh_func=self._refresh_func
        )
        
        if not credentials.access_token:
            raise Exception("No access token available")
        
        # Normalize endpoint
        endpoint = credentials.resource_url or self._base_url
        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"
        if not endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/v1"
        
        return credentials.access_token, endpoint
    
    def _is_auth_error(self, error: Exception) -> bool:
        """Check if an error is related to authentication."""
        error_msg = str(error).lower()
        return any(
            keyword in error_msg
            for keyword in [
                "401",
                "403",
                "unauthorized",
                "forbidden",
                "invalid api key",
                "invalid access token",
                "token expired",
                "authentication",
                "access denied",
            ]
        )
    
    def _make_request(
        self,
        endpoint: str,
        token: str,
        payload: dict,
    ) -> dict:
        """Make an API request with the given token."""
        url = f"{endpoint}/chat/completions"
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "QwenCode/1.0.0 (linux; x86_64)",
                "X-DashScope-CacheControl": "enable",
                "X-DashScope-AuthType": "qwen-oauth",
            },
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(
                f"API request failed: {e.code} {e.reason}. Response: {error_body}"
            ) from e
    
    def generate_content(
        self,
        messages: list[dict],
        max_retries: int = 1,
    ) -> dict:
        """Generate content using the Qwen API.
        
        Args:
            messages: List of message objects in OpenAI format.
            max_retries: Number of retries on auth errors.
        
        Returns:
            API response as a dictionary.
        """
        payload = {
            "model": self._model,
            "messages": messages,
        }
        
        for attempt in range(max_retries + 1):
            try:
                token, endpoint = self._get_valid_token_and_endpoint()
                return self._make_request(endpoint, token, payload)
            except Exception as e:
                if self._is_auth_error(e) and attempt < max_retries:
                    # Force refresh and retry
                    self._token_manager.clear_cache()
                    self._token_manager.get_valid_credentials(
                        refresh_func=self._refresh_func,
                        force_refresh=True,
                    )
                else:
                    raise
    
    def generate_content_stream(
        self,
        messages: list[dict],
    ):
        """Generate content with streaming.
        
        Args:
            messages: List of message objects in OpenAI format.
        
        Yields:
            Streaming response chunks.
        """
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        
        token, endpoint = self._get_valid_token_and_endpoint()
        url = f"{endpoint}/chat/completions"
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "QwenCode/1.0.0 (linux; x86_64)",
                "X-DashScope-CacheControl": "enable",
                "X-DashScope-AuthType": "qwen-oauth",
            },
            method="POST",
        )
        
        with urllib.request.urlopen(request) as response:
            for line in response:
                line = line.decode("utf-8").strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    yield json.loads(data)
```

---

## Complete Python Implementation

Here is a complete, self-contained Python implementation of the Qwen OAuth2 flow:

```python
"""
Qwen OAuth2 Client - Complete Implementation

This module implements the full OAuth2 Device Authorization Grant flow
for Qwen Code, including PKCE, token management, and API requests.

Usage:
    from qwen_oauth import QwenOAuthClient
    
    client = QwenOAuthClient()
    client.authenticate()  # Interactive browser flow
    
    # Make API requests
    response = client.generate_content([
        {"role": "user", "content": "Hello, world!"}
    ])
    print(response)
"""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Generator


# ============================================================================
# Constants
# ============================================================================

QWEN_OAUTH_BASE_URL = "https://chat.qwen.ai"
QWEN_OAUTH_DEVICE_CODE_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/device/code"
QWEN_OAUTH_TOKEN_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/token"
QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_OAUTH_SCOPE = "openid profile email model.completion"
QWEN_OAUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

QWEN_DIR = ".qwen"
CREDENTIAL_FILENAME = "oauth_creds.json"
LOCK_FILENAME = "oauth_creds.lock"

TOKEN_REFRESH_BUFFER_MS = 30_000  # 30 seconds
LOCK_TIMEOUT_MS = 10_000          # 10 seconds
CACHE_CHECK_INTERVAL_MS = 5_000   # 5 seconds


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class QwenCredentials:
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    expiry_date: Optional[int] = None
    token_type: Optional[str] = None
    resource_url: Optional[str] = None


@dataclass
class DeviceAuthorizationData:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int = 5


@dataclass
class DeviceTokenData:
    access_token: str
    refresh_token: Optional[str]
    token_type: str
    expires_in: int
    scope: Optional[str] = None
    resource_url: Optional[str] = None


# ============================================================================
# PKCE
# ============================================================================

def generate_code_verifier() -> str:
    """Generate a random code verifier for PKCE."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def generate_code_challenge(code_verifier: str) -> str:
    """Generate a code challenge from a code verifier using SHA-256."""
    sha256_hash = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(sha256_hash).rstrip(b"=").decode("ascii")


# ============================================================================
# Utility Functions
# ============================================================================

def url_encode(data: dict[str, str]) -> str:
    """Convert a dictionary to URL-encoded form data."""
    return urllib.parse.urlencode(data)


def get_credential_path() -> Path:
    """Get the path to the credentials file."""
    return Path.home() / QWEN_DIR / CREDENTIAL_FILENAME


def get_lock_path() -> Path:
    """Get the path to the lock file."""
    return Path.home() / QWEN_DIR / LOCK_FILENAME


# ============================================================================
# Credential Storage
# ============================================================================

def save_credentials(credentials: QwenCredentials) -> None:
    """Save credentials to disk atomically."""
    file_path = get_credential_path()
    file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    temp_path = file_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(
            {k: v for k, v in asdict(credentials).items() if v is not None},
            f,
            indent=2,
        )
    
    temp_path.rename(file_path)
    os.chmod(file_path, 0o600)


def load_credentials() -> Optional[QwenCredentials]:
    """Load credentials from disk."""
    file_path = get_credential_path()
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        required = ["access_token", "refresh_token", "token_type", "expiry_date"]
        if not all(data.get(field) for field in required):
            return None
        
        return QwenCredentials(**{k: v for k, v in data.items() if k in QwenCredentials.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError):
        return None


def clear_credentials() -> None:
    """Delete the credentials file."""
    file_path = get_credential_path()
    if file_path.exists():
        file_path.unlink()


# ============================================================================
# SharedTokenManager
# ============================================================================

class SharedTokenManager:
    """Manages OAuth tokens across processes using file-based caching and locking."""
    
    _instance: Optional["SharedTokenManager"] = None
    
    def __init__(self):
        self._credentials: Optional[QwenCredentials] = None
        self._file_mod_time: float = 0
        self._last_check: float = 0
    
    @classmethod
    def get_instance(cls) -> "SharedTokenManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _is_token_valid(self, creds: QwenCredentials) -> bool:
        if not creds.expiry_date or not creds.access_token:
            return False
        return int(time.time() * 1000) < creds.expiry_date - TOKEN_REFRESH_BUFFER_MS
    
    def _acquire_lock(self, max_attempts: int = 20) -> bool:
        lock_id = str(uuid.uuid4())
        interval = 0.1
        
        for _ in range(max_attempts):
            try:
                with open(get_lock_path(), "x") as f:
                    f.write(lock_id)
                return True
            except FileExistsError:
                try:
                    stat = get_lock_path().stat()
                    if time.time() - stat.st_mtime > LOCK_TIMEOUT_MS / 1000:
                        get_lock_path().unlink()
                        continue
                except (OSError, FileNotFoundError):
                    continue
                
                time.sleep(interval)
                interval = min(interval * 1.5, 2.0)
        
        return False
    
    def _release_lock(self) -> None:
        try:
            get_lock_path().unlink()
        except FileNotFoundError:
            pass
    
    def check_and_reload(self) -> None:
        """Reload credentials if the file was modified by another process."""
        now = time.time()
        if now - self._last_check < CACHE_CHECK_INTERVAL_MS / 1000:
            return
        
        self._last_check = now
        file_path = get_credential_path()
        
        try:
            stat = file_path.stat()
            if stat.st_mtime > self._file_mod_time:
                creds = load_credentials()
                if creds:
                    self._credentials = creds
                    self._file_mod_time = stat.st_mtime
        except FileNotFoundError:
            self._file_mod_time = 0
    
    def get_valid_credentials(
        self,
        refresh_func: callable,
        force_refresh: bool = False,
    ) -> QwenCredentials:
        """Get valid credentials, refreshing if necessary."""
        self.check_and_reload()
        
        if not force_refresh and self._credentials and self._is_token_valid(self._credentials):
            return self._credentials
        
        if not self._credentials or not self._credentials.refresh_token:
            raise Exception("No refresh token available")
        
        if not self._acquire_lock():
            raise Exception("Failed to acquire lock for token refresh")
        
        try:
            self.check_and_reload()
            if not force_refresh and self._credentials and self._is_token_valid(self._credentials):
                return self._credentials
            
            new_creds = refresh_func(self._credentials.refresh_token)
            self._credentials = new_creds
            save_credentials(new_creds)
            return new_creds
        finally:
            self._release_lock()
    
    def clear_cache(self) -> None:
        self._credentials = None
        self._file_mod_time = 0
        self._last_check = 0


# ============================================================================
# OAuth2 Client
# ============================================================================

class QwenOAuthClient:
    """Complete Qwen OAuth2 client implementation."""
    
    def __init__(self):
        self._token_manager = SharedTokenManager.get_instance()
        self._credentials: Optional[QwenCredentials] = None
    
    def _refresh_token(self, refresh_token: str) -> QwenCredentials:
        """Refresh an access token."""
        body_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": QWEN_OAUTH_CLIENT_ID,
        }
        
        request = urllib.request.Request(
            QWEN_OAUTH_TOKEN_ENDPOINT,
            data=url_encode(body_data).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(request) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            if e.code == 400:
                clear_credentials()
                raise Exception("Refresh token expired. Please re-authenticate.") from e
            raise Exception(f"Token refresh failed: {e.code} {e.reason}") from e
        
        if "error" in result:
            raise Exception(f"Token refresh failed: {result['error']}")
        
        return QwenCredentials(
            access_token=result["access_token"],
            token_type=result.get("token_type", "Bearer"),
            refresh_token=result.get("refresh_token", refresh_token),
            resource_url=result.get("resource_url"),
            expiry_date=int(time.time() * 1000) + result.get("expires_in", 7200) * 1000,
        )
    
    def _request_device_authorization(self, code_challenge: str) -> DeviceAuthorizationData:
        """Request device authorization."""
        body_data = {
            "client_id": QWEN_OAUTH_CLIENT_ID,
            "scope": QWEN_OAUTH_SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        
        request = urllib.request.Request(
            QWEN_OAUTH_DEVICE_CODE_ENDPOINT,
            data=url_encode(body_data).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "x-request-id": str(uuid.uuid4()),
            },
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(request) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"Device authorization failed: {e.code} {e.reason}") from e
        
        if "device_code" not in result:
            raise Exception(f"Device authorization failed: {result.get('error', 'Unknown')}")
        
        return DeviceAuthorizationData(
            device_code=result["device_code"],
            user_code=result["user_code"],
            verification_uri=result["verification_uri"],
            verification_uri_complete=result["verification_uri_complete"],
            expires_in=result["expires_in"],
            interval=result.get("interval", 5),
        )
    
    def _poll_device_token(self, device_code: str, code_verifier: str) -> DeviceTokenData:
        """Poll for the device token until approved."""
        poll_interval = 2.0
        max_attempts = 300
        
        for attempt in range(max_attempts):
            body_data = {
                "grant_type": QWEN_OAUTH_GRANT_TYPE,
                "client_id": QWEN_OAUTH_CLIENT_ID,
                "device_code": device_code,
                "code_verifier": code_verifier,
            }
            
            request = urllib.request.Request(
                QWEN_OAUTH_TOKEN_ENDPOINT,
                data=url_encode(body_data).encode("utf-8"),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
            
            try:
                with urllib.request.urlopen(request) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8")
                try:
                    error_data = json.loads(error_body)
                except json.JSONDecodeError:
                    raise Exception(f"Token poll failed: {e.code} {e.reason}") from e
                
                if e.code == 400 and error_data.get("error") == "authorization_pending":
                    time.sleep(poll_interval)
                    continue
                
                if e.code == 429 and error_data.get("error") == "slow_down":
                    poll_interval = min(poll_interval * 1.5, 10.0)
                    time.sleep(poll_interval)
                    continue
                
                raise Exception(f"Token poll failed: {error_data.get('error', 'Unknown')}") from e
            
            if result.get("access_token"):
                return DeviceTokenData(
                    access_token=result["access_token"],
                    refresh_token=result.get("refresh_token"),
                    token_type=result.get("token_type", "Bearer"),
                    expires_in=result.get("expires_in", 7200),
                    resource_url=result.get("resource_url"),
                )
            
            time.sleep(poll_interval)
        
        raise Exception("Authorization timeout")
    
    def authenticate(self) -> QwenCredentials:
        """Perform the full OAuth2 device authorization flow."""
        # Try loading cached credentials first
        cached = load_credentials()
        if cached:
            self._credentials = cached
            self._token_manager._credentials = cached
            self._token_manager._file_mod_time = get_credential_path().stat().st_mtime if get_credential_path().exists() else 0
            
            if self._token_manager._is_token_valid(cached):
                return cached
        
        # PKCE
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        
        # Device authorization
        device_auth = self._request_device_authorization(code_challenge)
        
        # Display authorization URL
        print(f"\n{'=' * 60}")
        print(f"Qwen OAuth Device Authorization")
        print(f"{'=' * 60}")
        print(f"Please visit the following URL in your browser:")
        print(f"  {device_auth.verification_uri_complete}")
        print(f"Waiting for authorization to complete...")
        print(f"{'=' * 60}\n")
        
        # Try to open browser
        try:
            import webbrowser
            webbrowser.open(device_auth.verification_uri_complete)
        except Exception:
            pass
        
        # Poll for token
        token_data = self._poll_device_token(device_auth.device_code, code_verifier)
        
        # Store credentials
        self._credentials = QwenCredentials(
            access_token=token_data.access_token,
            refresh_token=token_data.refresh_token,
            token_type=token_data.token_type,
            resource_url=token_data.resource_url,
            expiry_date=int(time.time() * 1000) + token_data.expires_in * 1000,
        )
        
        save_credentials(self._credentials)
        self._token_manager.clear_cache()
        
        print("Authentication successful!")
        return self._credentials
    
    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        creds = self._token_manager.get_valid_credentials(
            refresh_func=self._refresh_token
        )
        return creds.access_token


# ============================================================================
# API Client
# ============================================================================

class QwenAPIClient:
    """API client for making requests to the Qwen/DashScope API."""
    
    def __init__(
        self,
        oauth_client: QwenOAuthClient,
        model: str = "coder-model",
    ):
        self._oauth_client = oauth_client
        self._model = model
    
    def _get_endpoint(self, resource_url: Optional[str] = None) -> str:
        endpoint = resource_url or DEFAULT_DASHSCOPE_BASE_URL
        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"
        if not endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/v1"
        return endpoint
    
    def _make_request(
        self,
        endpoint: str,
        token: str,
        payload: dict,
    ) -> dict:
        """Make an API request."""
        url = f"{endpoint}/chat/completions"
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "QwenCode/1.0.0 (linux; x86_64)",
                "X-DashScope-CacheControl": "enable",
                "X-DashScope-AuthType": "qwen-oauth",
            },
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"API request failed: {e.code} {e.reason}. Response: {error_body}") from e
    
    def _is_auth_error(self, error: Exception) -> bool:
        error_msg = str(error).lower()
        return any(
            kw in error_msg
            for kw in ["401", "403", "unauthorized", "forbidden", "invalid", "token expired"]
        )
    
    def generate_content(
        self,
        messages: list[dict],
        max_retries: int = 1,
    ) -> dict:
        """Generate content with automatic credential management and retry."""
        payload = {
            "model": self._model,
            "messages": messages,
        }
        
        for attempt in range(max_retries + 1):
            try:
                token = self._oauth_client.get_access_token()
                creds = SharedTokenManager.get_instance()._credentials
                endpoint = self._get_endpoint(creds.resource_url if creds else None)
                return self._make_request(endpoint, token, payload)
            except Exception as e:
                if self._is_auth_error(e) and attempt < max_retries:
                    SharedTokenManager.get_instance().clear_cache()
                    self._oauth_client.get_access_token()
                else:
                    raise
    
    def generate_content_stream(
        self,
        messages: list[dict],
    ) -> Generator[dict, None, None]:
        """Generate content with streaming."""
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        
        token = self._oauth_client.get_access_token()
        creds = SharedTokenManager.get_instance()._credentials
        endpoint = self._get_endpoint(creds.resource_url if creds else None)
        url = f"{endpoint}/chat/completions"
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "QwenCode/1.0.0 (linux; x86_64)",
                "X-DashScope-CacheControl": "enable",
                "X-DashScope-AuthType": "qwen-oauth",
            },
            method="POST",
        )
        
        with urllib.request.urlopen(request) as response:
            for line in response:
                line = line.decode("utf-8").strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    yield json.loads(data)


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Step 1: Authenticate
    oauth_client = QwenOAuthClient()
    credentials = oauth_client.authenticate()
    
    print(f"Access Token: {credentials.access_token[:20]}...")
    print(f"Token Type: {credentials.token_type}")
    print(f"Resource URL: {credentials.resource_url}")
    
    # Step 2: Make API requests
    api_client = QwenAPIClient(oauth_client, model="coder-model")
    
    response = api_client.generate_content([
        {"role": "user", "content": "Hello! What can you do?"}
    ])
    
    print("\nAPI Response:")
    for choice in response.get("choices", []):
        print(choice.get("message", {}).get("content", ""))
```

---

## Error Handling and Edge Cases

### 1. Credentials Clear Required Error

When a 400 error is returned during token refresh, it indicates the refresh token has expired. The client must clear all credentials and require re-authentication.

```python
class CredentialsClearRequiredError(Exception):
    """Thrown when a refresh token is expired or invalid."""
    pass

# In refresh flow:
if response.status == 400:
    clear_credentials()
    raise CredentialsClearRequiredError(
        "Refresh token expired or invalid. Please re-authenticate."
    )
```

### 2. Quota Exceeded Errors

Qwen OAuth has a free tier quota of 1,000 requests/day and 60 requests/minute. When exceeded, the API returns a specific error message.

```python
def is_quota_exceeded_error(error: Exception) -> bool:
    """Check if an error is a quota exceeded error."""
    error_msg = str(error).lower()
    return any(
        kw in error_msg
        for kw in ["insufficient_quota", "free allocated quota exceeded", "quota exceeded"]
    )
```

### 3. Rate Limiting (429)

The device token polling endpoint may return 429 with `slow_down` error. The client should increase the polling interval.

```python
if response.status == 429 and error_data.get("error") == "slow_down":
    poll_interval = min(poll_interval * 1.5, 10.0)  # Max 10 seconds
```

### 4. Cross-Process Token Synchronization

When multiple instances of the client run simultaneously, the `SharedTokenManager` ensures only one process refreshes the token at a time using file-based locking.

### 5. Token Expiry Buffer

Tokens are considered "expired" 30 seconds before their actual expiry time to prevent race conditions during API requests.

```python
TOKEN_REFRESH_BUFFER_MS = 30_000  # 30 seconds

def is_token_valid(credentials: QwenCredentials) -> bool:
    if not credentials.expiry_date:
        return False
    return time.time() * 1000 < credentials.expiry_date - TOKEN_REFRESH_BUFFER_MS
```

---

## Summary

The Qwen Code OAuth2 flow consists of:

1. **PKCE-based Device Authorization Grant** - Secure authentication without browser redirects
2. **File-based Credential Storage** - Tokens stored in `~/.qwen/oauth_creds.json`
3. **SharedTokenManager** - Cross-process token synchronization with file locking
4. **Dynamic Token Injection** - Access tokens are injected into API requests at request time
5. **Automatic Retry** - 401/403 errors trigger a token refresh and retry
6. **DashScope API** - OpenAI-compatible API endpoint with custom headers

The complete Python implementation above provides a drop-in replacement for the TypeScript OAuth2 client, suitable for use in any Python-based application.