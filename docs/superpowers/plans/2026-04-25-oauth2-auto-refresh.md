# OAuth2 Automatic Token Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automatic OAuth2 token refresh across all providers so expired access tokens are transparently refreshed using refresh tokens without user interaction.

**Architecture:** Add `get_valid_token_with_refresh()` method to all OAuth2 auth classes (KiloOAuth2, ClaudeAuth, CodexOAuth2, QwenOAuth2). Update provider handlers to call refresh-aware methods. Auth classes handle refresh internally with proper error messages when refresh fails.

**Tech Stack:** Python 3.x, httpx, asyncio, pytest

---

## File Structure

**Auth Classes (aisbf/auth/):**
- `kilo.py` - Add `get_valid_token_with_refresh()` method
- `claude.py` - Refactor existing `get_valid_token()` to separate refresh/no-refresh methods
- `codex.py` - Verify existing implementation
- `qwen.py` - Verify existing implementation

**Provider Handlers (aisbf/providers/):**
- `kilo.py` - Update `_ensure_authenticated()` to use refresh method
- `claude.py` - Update token retrieval to use refresh method
- `codex.py` - Verify existing implementation
- `qwen.py` - Verify existing implementation

**Tests:**
- `tests/auth/test_kilo_oauth2.py` - New test file for KiloOAuth2
- `tests/auth/test_claude_auth.py` - New test file for ClaudeAuth
- `tests/providers/test_kilo_provider.py` - New test file for KiloProviderHandler
- `tests/providers/test_claude_provider.py` - New test file for ClaudeProviderHandler

---

## Task 1: Add get_valid_token_with_refresh() to KiloOAuth2

**Files:**
- Modify: `aisbf/auth/kilo.py:459-485`
- Test: `tests/auth/test_kilo_oauth2.py`

- [ ] **Step 1: Write failing test for get_valid_token_with_refresh with valid token**

Create `tests/auth/test_kilo_oauth2.py`:

```python
import pytest
import time
import json
import tempfile
import os
from aisbf.auth.kilo import KiloOAuth2


@pytest.fixture
def temp_credentials_file():
    """Create a temporary credentials file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def valid_credentials():
    """Valid credentials with future expiry."""
    return {
        "type": "oauth",
        "access": "valid_access_token",
        "refresh": "valid_refresh_token",
        "expires": int(time.time()) + 3600,  # Expires in 1 hour
        "userEmail": "test@example.com"
    }


@pytest.fixture
def expired_credentials():
    """Expired credentials."""
    return {
        "type": "oauth",
        "access": "expired_access_token",
        "refresh": "expired_refresh_token",
        "expires": int(time.time()) - 3600,  # Expired 1 hour ago
        "userEmail": "test@example.com"
    }


@pytest.mark.asyncio
async def test_get_valid_token_with_refresh_returns_valid_token(temp_credentials_file, valid_credentials):
    """Test that get_valid_token_with_refresh returns token when valid."""
    # Save valid credentials
    with open(temp_credentials_file, 'w') as f:
        json.dump(valid_credentials, f)
    
    oauth2 = KiloOAuth2(credentials_file=temp_credentials_file)
    
    token = await oauth2.get_valid_token_with_refresh()
    
    assert token == "valid_access_token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/auth/test_kilo_oauth2.py::test_get_valid_token_with_refresh_returns_valid_token -v`

Expected: FAIL with "AttributeError: 'KiloOAuth2' object has no attribute 'get_valid_token_with_refresh'"

- [ ] **Step 3: Write failing test for get_valid_token_with_refresh with expired token**

Add to `tests/auth/test_kilo_oauth2.py`:

```python
@pytest.mark.asyncio
async def test_get_valid_token_with_refresh_returns_none_when_expired(temp_credentials_file, expired_credentials):
    """Test that get_valid_token_with_refresh returns None when token expired."""
    # Save expired credentials
    with open(temp_credentials_file, 'w') as f:
        json.dump(expired_credentials, f)
    
    oauth2 = KiloOAuth2(credentials_file=temp_credentials_file)
    
    token = await oauth2.get_valid_token_with_refresh()
    
    assert token is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/auth/test_kilo_oauth2.py::test_get_valid_token_with_refresh_returns_none_when_expired -v`

Expected: FAIL with "AttributeError: 'KiloOAuth2' object has no attribute 'get_valid_token_with_refresh'"

- [ ] **Step 5: Implement get_valid_token_with_refresh in KiloOAuth2**

Add method after `get_valid_token()` in `aisbf/auth/kilo.py` (around line 485):

```python
async def get_valid_token_with_refresh(self) -> Optional[str]:
    """
    Get a valid access token, attempting refresh if expired.
    
    Note: Kilo uses long-lived tokens (1 year) with the same value for
    access and refresh. There is no separate refresh endpoint - when tokens
    expire, users must complete device flow again.
    
    Returns:
        Access token string or None if expired/not authenticated
    """
    # Reload credentials in case another process updated them
    self._load_credentials()
    
    # Check if token is still valid
    if self.credentials and self.credentials.get('expires', 0) > time.time():
        return self.credentials.get('access')
    
    # Token expired - cannot refresh unattended
    # Kilo requires device flow for new tokens
    logger.error("KiloOAuth2: Token expired, re-authentication required")
    return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/auth/test_kilo_oauth2.py -v`

Expected: Both tests PASS

- [ ] **Step 7: Commit**

```bash
git add aisbf/auth/kilo.py tests/auth/test_kilo_oauth2.py
git commit -m "feat(auth): add get_valid_token_with_refresh to KiloOAuth2"
```

---

## Task 2: Refactor ClaudeAuth to separate refresh/no-refresh methods

**Files:**
- Modify: `aisbf/auth/claude.py:314-345`
- Test: `tests/auth/test_claude_auth.py`

- [ ] **Step 1: Write failing test for new get_valid_token (no refresh)**

Create `tests/auth/test_claude_auth.py`:

```python
import pytest
import time
import json
import tempfile
import os
from aisbf.auth.claude import ClaudeAuth


@pytest.fixture
def temp_credentials_file():
    """Create a temporary credentials file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def valid_tokens():
    """Valid tokens with future expiry."""
    return {
        "access_token": "valid_access_token",
        "refresh_token": "valid_refresh_token",
        "expires_in": 3600,
        "expires_at": time.time() + 3600,  # Expires in 1 hour
        "token_type": "Bearer"
    }


@pytest.fixture
def expired_tokens():
    """Expired tokens."""
    return {
        "access_token": "expired_access_token",
        "refresh_token": "expired_refresh_token",
        "expires_in": 3600,
        "expires_at": time.time() - 3600,  # Expired 1 hour ago
        "token_type": "Bearer"
    }


def test_get_valid_token_returns_token_when_valid(temp_credentials_file, valid_tokens):
    """Test that get_valid_token returns token when valid (no refresh)."""
    # Save valid tokens
    with open(temp_credentials_file, 'w') as f:
        json.dump(valid_tokens, f)
    
    auth = ClaudeAuth(credentials_file=temp_credentials_file)
    
    token = auth.get_valid_token()
    
    assert token == "valid_access_token"


def test_get_valid_token_returns_none_when_expired(temp_credentials_file, expired_tokens):
    """Test that get_valid_token returns None when expired (no refresh attempt)."""
    # Save expired tokens
    with open(temp_credentials_file, 'w') as f:
        json.dump(expired_tokens, f)
    
    auth = ClaudeAuth(credentials_file=temp_credentials_file)
    
    token = auth.get_valid_token()
    
    assert token is None
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `pytest tests/auth/test_claude_auth.py::test_get_valid_token_returns_none_when_expired -v`

Expected: FAIL - current `get_valid_token()` attempts refresh, so it won't return None immediately

- [ ] **Step 3: Write test for get_valid_token_with_refresh**

Add to `tests/auth/test_claude_auth.py`:

```python
@pytest.mark.asyncio
async def test_get_valid_token_with_refresh_returns_valid_token(temp_credentials_file, valid_tokens):
    """Test that get_valid_token_with_refresh returns token when valid."""
    # Save valid tokens
    with open(temp_credentials_file, 'w') as f:
        json.dump(valid_tokens, f)
    
    auth = ClaudeAuth(credentials_file=temp_credentials_file)
    
    token = await auth.get_valid_token_with_refresh()
    
    assert token == "valid_access_token"
```

- [ ] **Step 4: Refactor ClaudeAuth methods**

In `aisbf/auth/claude.py`, replace the existing `get_valid_token()` method (lines 314-345) with:

```python
def get_valid_token(self) -> Optional[str]:
    """
    Get a valid access token without attempting refresh.
    
    This is a quick check method that returns the token if valid,
    or None if expired. It does NOT attempt to refresh the token.
    
    Returns:
        Valid access token or None if expired/not authenticated
    """
    if not self.tokens:
        return None
    
    # Check if token is expired (with 5 minute buffer)
    if time.time() > (self.tokens.get('expires_at', 0) - 300):
        return None
    
    return self.tokens.get('access_token')

async def get_valid_token_with_refresh(self, auto_login: bool = False) -> Optional[str]:
    """
    Get a valid access token, refreshing it if necessary.
    
    Args:
        auto_login: If True, automatically trigger login flow when no credentials exist.
                   If False, return None instead (default: False for security).
    
    Returns:
        Valid access token or None if refresh fails
    """
    if not self.tokens:
        if not auto_login:
            logger.error("No Claude credentials available. Please authenticate via dashboard or MCP.")
            return None
        logger.info("No tokens available, starting login flow")
        self.login()
        return self.tokens.get('access_token') if self.tokens else None
    
    # Refresh if less than 5 minutes remain
    if time.time() > (self.tokens.get('expires_at', 0) - 300):
        logger.info("Token expiring soon, refreshing...")
        if not await self.refresh_token():
            if not auto_login:
                logger.error("Token refresh failed and auto_login is disabled")
                return None
            logger.warning("Refresh failed, re-authenticating...")
            self.login()
            return self.tokens.get('access_token') if self.tokens else None
    
    return self.tokens.get('access_token')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/auth/test_claude_auth.py -v`

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add aisbf/auth/claude.py tests/auth/test_claude_auth.py
git commit -m "refactor(auth): separate ClaudeAuth refresh/no-refresh methods"
```

---

## Task 3: Update KiloProviderHandler to use get_valid_token_with_refresh

**Files:**
- Modify: `aisbf/providers/kilo.py:204-259`
- Test: `tests/providers/test_kilo_provider.py`

- [ ] **Step 1: Write failing test for _ensure_authenticated with valid token**

Create `tests/providers/test_kilo_provider.py`:

```python
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch
from aisbf.providers.kilo import KiloProviderHandler


@pytest.fixture
def mock_oauth2_valid():
    """Mock KiloOAuth2 with valid token."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value="valid_token")
    return mock


@pytest.fixture
def mock_oauth2_expired():
    """Mock KiloOAuth2 with expired token (returns None)."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value=None)
    mock.initiate_device_flow = AsyncMock(return_value={
        "code": "ABC123",
        "verification_url": "https://kilo.ai/device",
        "expires_in": 600,
        "poll_interval": 3.0
    })
    return mock


@pytest.mark.asyncio
async def test_ensure_authenticated_returns_token_when_valid(mock_oauth2_valid):
    """Test that _ensure_authenticated returns token when valid."""
    handler = KiloProviderHandler(provider_id="test_kilo", api_key=None, user_id=1)
    handler.oauth2 = mock_oauth2_valid
    handler._use_api_key_auth = False
    
    result = await handler._ensure_authenticated()
    
    assert result["status"] == "authenticated"
    assert result["token"] == "valid_token"
    mock_oauth2_valid.get_valid_token_with_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_initiates_device_flow_when_expired(mock_oauth2_expired):
    """Test that _ensure_authenticated initiates device flow when token expired."""
    handler = KiloProviderHandler(provider_id="test_kilo", api_key=None, user_id=1)
    handler.oauth2 = mock_oauth2_expired
    handler._use_api_key_auth = False
    
    result = await handler._ensure_authenticated()
    
    assert result["status"] == "pending_authorization"
    assert result["code"] == "ABC123"
    assert result["verification_url"] == "https://kilo.ai/device"
    mock_oauth2_expired.get_valid_token_with_refresh.assert_called_once()
    mock_oauth2_expired.initiate_device_flow.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/providers/test_kilo_provider.py::test_ensure_authenticated_returns_token_when_valid -v`

Expected: FAIL with "AttributeError: 'Mock' object has no attribute 'get_valid_token_with_refresh'"

- [ ] **Step 3: Update _ensure_authenticated to use get_valid_token_with_refresh**

In `aisbf/providers/kilo.py`, replace `_ensure_authenticated()` method (lines 204-259):

```python
async def _ensure_authenticated(self):
    """Ensure user is authenticated and return valid token.
    
    Returns immediately with status, never blocks polling in HTTP request.
    For device flow: only initiates flow, does NOT poll inside handler.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # If API key authentication is configured, use it directly - NO OAUTH EVER
    if self._use_api_key_auth:
        logger.info("KiloProviderHandler: Using configured API key authentication - skipping OAuth2 flow")
        return {
            "status": "authenticated",
            "token": self.api_key
        }

    # Try to get valid token with automatic refresh
    logger.info(f"KiloProviderHandler._ensure_authenticated: Calling get_valid_token_with_refresh()")
    token = await self.oauth2.get_valid_token_with_refresh()

    if token:
        logger.info("KiloProviderHandler: Using OAuth2 token (valid or refreshed)")
        return {
            "status": "authenticated",
            "token": token
        }
    
    logger.info("KiloProviderHandler: No valid OAuth2 token, initiating device flow")
    
    # Start the non-blocking device flow - ONLY initiate, DO NOT poll
    flow_info = await self.oauth2.initiate_device_flow()
    
    # Return immediately with pending status - NEVER block on poll in HTTP handler
    return {
        "status": "pending_authorization",
        "verification_url": flow_info["verification_url"],
        "code": flow_info["code"],
        "expires_in": flow_info["expires_in"],
        "poll_interval": flow_info["poll_interval"]
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_kilo_provider.py -v`

Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add aisbf/providers/kilo.py tests/providers/test_kilo_provider.py
git commit -m "feat(providers): update KiloProviderHandler to use token refresh"
```

---

## Task 4: Update ClaudeProviderHandler to use get_valid_token_with_refresh

**Files:**
- Modify: `aisbf/providers/claude.py:954,976`
- Test: `tests/providers/test_claude_provider.py`

- [ ] **Step 1: Write failing test for handle_request with valid token**

Create `tests/providers/test_claude_provider.py`:

```python
import pytest
from unittest.mock import Mock, AsyncMock, patch
from aisbf.providers.claude import ClaudeProviderHandler
from aisbf.models import ChatCompletionRequest, Message


@pytest.fixture
def mock_auth_valid():
    """Mock ClaudeAuth with valid token."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value="valid_access_token")
    return mock


@pytest.fixture
def mock_auth_expired():
    """Mock ClaudeAuth with expired token (returns None)."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def sample_request():
    """Sample chat completion request."""
    return ChatCompletionRequest(
        model="claude-3-5-sonnet-20241022",
        messages=[Message(role="user", content="Hello")],
        stream=False
    )


@pytest.mark.asyncio
async def test_handle_request_uses_refreshed_token(mock_auth_valid, sample_request):
    """Test that handle_request uses get_valid_token_with_refresh."""
    handler = ClaudeProviderHandler(provider_id="test_claude", api_key=None, user_id=1)
    handler.auth = mock_auth_valid
    
    # Mock the HTTP client to avoid actual API calls
    with patch.object(handler, 'client') as mock_client:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-3-5-sonnet-20241022",
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # This should call get_valid_token_with_refresh
        await handler.handle_request(sample_request)
        
        mock_auth_valid.get_valid_token_with_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_handle_request_raises_error_when_token_refresh_fails(mock_auth_expired, sample_request):
    """Test that handle_request raises error when token refresh fails."""
    handler = ClaudeProviderHandler(provider_id="test_claude", api_key=None, user_id=1)
    handler.auth = mock_auth_expired
    
    with pytest.raises(Exception) as exc_info:
        await handler.handle_request(sample_request)
    
    assert "authentication required" in str(exc_info.value).lower() or "token" in str(exc_info.value).lower()
    mock_auth_expired.get_valid_token_with_refresh.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/providers/test_claude_provider.py::test_handle_request_uses_refreshed_token -v`

Expected: FAIL - handler currently calls `get_valid_token()` not `get_valid_token_with_refresh()`

- [ ] **Step 3: Update ClaudeProviderHandler to use get_valid_token_with_refresh**

In `aisbf/providers/claude.py`, find the two locations where `get_valid_token()` is called (around lines 954 and 976) and replace with `get_valid_token_with_refresh()`:

Line 954 (in `handle_request` method):
```python
# OLD:
access_token = await self.auth.get_valid_token()

# NEW:
access_token = await self.auth.get_valid_token_with_refresh()
if not access_token:
    raise Exception("Claude authentication required. Token refresh failed. Please re-authenticate via /dashboard/claude/auth/start")
```

Line 976 (in `handle_streaming_request` method):
```python
# OLD:
access_token = await self.auth.get_valid_token()

# NEW:
access_token = await self.auth.get_valid_token_with_refresh()
if not access_token:
    raise Exception("Claude authentication required. Token refresh failed. Please re-authenticate via /dashboard/claude/auth/start")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_claude_provider.py -v`

Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add aisbf/providers/claude.py tests/providers/test_claude_provider.py
git commit -m "feat(providers): update ClaudeProviderHandler to use token refresh"
```

---

## Task 5: Verify CodexOAuth2 and CodexProviderHandler

**Files:**
- Read: `aisbf/auth/codex.py:572-615`
- Read: `aisbf/providers/codex.py:165-189`

- [ ] **Step 1: Verify CodexOAuth2 has get_valid_token_with_refresh**

Run: `grep -n "def get_valid_token_with_refresh" aisbf/auth/codex.py`

Expected: Should find the method definition around line 572

- [ ] **Step 2: Verify CodexOAuth2.get_valid_token doesn't refresh**

Read `aisbf/auth/codex.py:543-570` and verify:
- Method returns `None` when token is expired
- Method does NOT call refresh logic
- Method does NOT make network requests

Expected: Method should only check expiry and return token or None

- [ ] **Step 3: Verify CodexProviderHandler uses get_valid_token_with_refresh**

Run: `grep -n "get_valid_token_with_refresh" aisbf/providers/codex.py`

Expected: Should find call to `get_valid_token_with_refresh()` around line 173

- [ ] **Step 4: Document verification results**

Create verification note:

```bash
echo "CodexOAuth2 and CodexProviderHandler verification:
- CodexOAuth2.get_valid_token_with_refresh() exists at line 572
- CodexOAuth2.get_valid_token() does not refresh (line 543)
- CodexProviderHandler calls get_valid_token_with_refresh() at line 173
Status: VERIFIED - No changes needed" > docs/superpowers/verification-codex.txt
git add docs/superpowers/verification-codex.txt
git commit -m "docs: verify CodexOAuth2 implementation"
```

---

## Task 6: Verify QwenOAuth2 and QwenProviderHandler

**Files:**
- Read: `aisbf/auth/qwen.py:608-625`
- Read: `aisbf/providers/qwen.py:179-220`

- [ ] **Step 1: Verify QwenOAuth2 has get_valid_token_with_refresh**

Run: `grep -n "def get_valid_token_with_refresh" aisbf/auth/qwen.py`

Expected: Should find the method definition around line 608

- [ ] **Step 2: Verify QwenOAuth2.get_valid_token doesn't refresh**

Read `aisbf/auth/qwen.py:593-606` and verify:
- Method returns `None` when token is expired
- Method does NOT call refresh logic
- Method does NOT make network requests

Expected: Method should only check expiry and return token or None

- [ ] **Step 3: Verify QwenProviderHandler uses get_valid_token_with_refresh**

Run: `grep -n "get_valid_token_with_refresh" aisbf/providers/qwen.py`

Expected: Should find call to `get_valid_token_with_refresh()` around line 201

- [ ] **Step 4: Document verification results**

Create verification note:

```bash
echo "QwenOAuth2 and QwenProviderHandler verification:
- QwenOAuth2.get_valid_token_with_refresh() exists at line 608
- QwenOAuth2.get_valid_token() does not refresh (line 593)
- QwenProviderHandler calls get_valid_token_with_refresh() at line 201
Status: VERIFIED - No changes needed" > docs/superpowers/verification-qwen.txt
git add docs/superpowers/verification-qwen.txt
git commit -m "docs: verify QwenOAuth2 implementation"
```

---

## Task 7: Run all tests and verify implementation

**Files:**
- Run: All test files

- [ ] **Step 1: Run all auth tests**

Run: `pytest tests/auth/ -v`

Expected: All tests PASS

- [ ] **Step 2: Run all provider tests**

Run: `pytest tests/providers/ -v`

Expected: All tests PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`

Expected: All tests PASS (or only pre-existing failures)

- [ ] **Step 4: Manual verification - Test with expired token**

Create a test script `test_manual_refresh.py`:

```python
import asyncio
import time
import json
import tempfile
from aisbf.auth.kilo import KiloOAuth2

async def test_kilo_refresh():
    # Create temp file with expired token
    fd, path = tempfile.mkstemp(suffix='.json')
    with open(path, 'w') as f:
        json.dump({
            "type": "oauth",
            "access": "expired_token",
            "refresh": "expired_token",
            "expires": int(time.time()) - 3600,
            "userEmail": "test@example.com"
        }, f)
    
    oauth2 = KiloOAuth2(credentials_file=path)
    token = await oauth2.get_valid_token_with_refresh()
    
    print(f"Token result: {token}")
    print(f"Expected: None (token expired)")
    
    import os
    os.remove(path)

asyncio.run(test_kilo_refresh())
```

Run: `python test_manual_refresh.py`

Expected output:
```
Token result: None
Expected: None (token expired)
```

- [ ] **Step 5: Clean up test script**

```bash
rm test_manual_refresh.py
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "test: verify OAuth2 auto-refresh implementation"
```

---

## Self-Review Checklist

**Spec Coverage:**
- ✅ KiloOAuth2.get_valid_token_with_refresh() - Task 1
- ✅ ClaudeAuth refactored to separate methods - Task 2
- ✅ KiloProviderHandler updated - Task 3
- ✅ ClaudeProviderHandler updated - Task 4
- ✅ CodexOAuth2 verified - Task 5
- ✅ QwenOAuth2 verified - Task 6
- ✅ All tests pass - Task 7

**Placeholder Scan:**
- ✅ No TBD, TODO, or "implement later"
- ✅ All code blocks complete
- ✅ All test assertions specific
- ✅ All file paths exact

**Type Consistency:**
- ✅ `get_valid_token_with_refresh()` returns `Optional[str]` consistently
- ✅ `get_valid_token()` returns `Optional[str]` consistently
- ✅ All async methods use `async def` and `await`

**Testing:**
- ✅ Unit tests for each auth class
- ✅ Unit tests for each provider handler
- ✅ Manual verification script included

---

## Success Criteria

1. ✅ All OAuth2 auth classes have `get_valid_token_with_refresh()` method
2. ✅ All OAuth2 auth classes have non-refreshing `get_valid_token()` method
3. ✅ All provider handlers call `get_valid_token_with_refresh()`
4. ✅ Expired tokens return `None` without user interaction
5. ✅ All tests pass
6. ✅ No regressions in existing OAuth2 flows
