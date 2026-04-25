# OAuth2 Automatic Token Refresh Design

**Date:** 2026-04-25  
**Status:** Approved  
**Approach:** Centralized Auth Layer (Approach A)

## Problem Statement

OAuth2 providers in AISBF currently have inconsistent token refresh behavior:
- `ClaudeAuth` proactively refreshes in `get_valid_token()` 
- `CodexOAuth2` and `QwenOAuth2` have separate `get_valid_token_with_refresh()` methods
- `KiloOAuth2` returns `None` on expiry without attempting refresh
- Provider handlers inconsistently call refresh-aware vs non-refresh methods

When a token expires, API requests fail and require manual re-authentication, even when a valid refresh token exists. This creates unnecessary friction for users.

## Requirements

1. **Automatic Refresh**: When an OAuth2 access token expires, automatically use the refresh token to obtain a new access token without user interaction
2. **Unattended Operation**: Refresh must happen transparently during API requests
3. **Graceful Degradation**: When refresh fails (revoked/expired refresh token), return clear error messages asking user to re-authenticate
4. **No Interactive Fallback**: Do NOT automatically trigger interactive flows (device auth, browser login) - only refresh using existing refresh tokens
5. **Consistency**: All OAuth2 providers must behave the same way
6. **Database Persistence**: Refreshed tokens must be saved back to database for user providers

## Design Overview

### Architecture

Implement a consistent auth layer pattern across all OAuth2 providers:

```
API Request → Provider Handler → Auth.get_valid_token_with_refresh()
                                        ↓
                                  Check expiry
                                        ↓
                                  Valid? → Return token
                                        ↓
                                  Expired? → Refresh token
                                        ↓
                                  Success? → Save & return new token
                                        ↓
                                  Failed? → Raise clear error
```

### Components

#### 1. Auth Classes (aisbf/auth/)

Each OAuth2 auth class must implement:

**`get_valid_token_with_refresh() -> Optional[str]`** (async)
- Check if current token is valid (not expired)
- If valid: return access token
- If expired: attempt refresh using refresh token
- If refresh succeeds: save new tokens and return access token
- If refresh fails: return `None`

**`get_valid_token() -> Optional[str]`** (sync, no refresh)
- Check if current token is valid
- Return token if valid, `None` if expired
- Does NOT attempt refresh (for quick checks)

**Error Handling:**
- Refresh token expired/revoked: Log clear message, return `None`
- Network errors: Retry with exponential backoff (existing behavior)
- Rate limits: Retry with backoff (existing behavior)

#### 2. Provider Handlers (aisbf/providers/)

Provider handlers must:
- Always call `get_valid_token_with_refresh()` before making API requests
- Handle `None` return by raising user-friendly exception
- Never call non-refresh methods for authentication

**Error Messages:**
- Dashboard: "Authentication expired. Please re-authenticate via [link]"
- API: HTTP 401 with JSON: `{"error": "authentication_required", "message": "OAuth2 token expired. Please re-authenticate.", "provider": "provider_id"}`

#### 3. Token Expiry Detection

**Proactive (Preferred):**
- Check `expires_at` timestamp before making requests
- Refresh if token expires within 5 minutes (300 seconds buffer)

**Reactive (Fallback):**
- If API returns 401/403, attempt refresh once
- Retry request with new token
- If still fails, return auth error to user

### Implementation Scope

#### Auth Classes to Update

1. **KiloOAuth2** (`aisbf/auth/kilo.py`)
   - Add `get_valid_token_with_refresh()` method
   - Implement refresh logic (Kilo uses same token for access/refresh, check expiry)
   - Note: Kilo tokens are long-lived (1 year), refresh may just validate existing token

2. **ClaudeAuth** (`aisbf/auth/claude.py`)
   - Rename existing `get_valid_token()` to `get_valid_token_with_refresh()`
   - Add new `get_valid_token()` that doesn't refresh (for quick checks)
   - Existing refresh logic is already correct

3. **CodexOAuth2** (`aisbf/auth/codex.py`)
   - Already has `get_valid_token_with_refresh()` - verify it's correct
   - Ensure `get_valid_token()` doesn't refresh

4. **QwenOAuth2** (`aisbf/auth/qwen.py`)
   - Already has `get_valid_token_with_refresh()` - verify it's correct
   - Ensure `get_valid_token()` doesn't refresh

#### Provider Handlers to Update

1. **ClaudeProviderHandler** (`aisbf/providers/claude.py`)
   - Update calls to use `get_valid_token_with_refresh()`
   - Add proper error handling for `None` return

2. **KiloProviderHandler** (`aisbf/providers/kilo.py`)
   - Update `_ensure_authenticated()` to call `get_valid_token_with_refresh()`
   - Add proper error handling for `None` return
   - Remove device flow initiation from this path (only for initial auth)

3. **CodexProviderHandler** (`aisbf/providers/codex.py`)
   - Verify it already calls `get_valid_token_with_refresh()`
   - Ensure error handling is correct

4. **QwenProviderHandler** (`aisbf/providers/qwen.py`)
   - Verify it already calls `get_valid_token_with_refresh()`
   - Ensure error handling is correct

### Token Refresh Logic

#### For Providers with Standard OAuth2 Refresh

**ClaudeAuth, CodexOAuth2, QwenOAuth2:**

```python
async def get_valid_token_with_refresh(self) -> Optional[str]:
    # Check if file/db was updated by another process
    self._load_or_reload_credentials()
    
    # Check expiry with 5-minute buffer
    if self._is_token_valid(buffer_seconds=300):
        return self.credentials['access_token']
    
    # Token expired - attempt refresh
    if not self.credentials or 'refresh_token' not in self.credentials:
        logger.error(f"{self.__class__.__name__}: No refresh token available")
        return None
    
    try:
        # Call provider's token endpoint with refresh_token grant
        new_tokens = await self._refresh_token_request()
        
        # Save new tokens (file or database via callback)
        self._save_credentials(new_tokens)
        
        logger.info(f"{self.__class__.__name__}: Successfully refreshed access token")
        return new_tokens['access_token']
        
    except RefreshTokenExpired:
        logger.error(f"{self.__class__.__name__}: Refresh token expired or revoked")
        return None
    except Exception as e:
        logger.error(f"{self.__class__.__name__}: Token refresh failed: {e}")
        return None
```

#### For Kilo (Long-lived Tokens)

**KiloOAuth2:**

Kilo uses the same token for both access and refresh, with 1-year expiry. The "refresh" operation is essentially validating the existing token is still valid:

```python
async def get_valid_token_with_refresh(self) -> Optional[str]:
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

Note: Kilo doesn't have a separate refresh endpoint. When tokens expire, users must complete device flow again.

### Database Integration

For user providers (user_id is not None), refreshed tokens must be saved to database:

```python
def _save_credentials(self, credentials: Dict):
    self.credentials = credentials
    
    if self._save_callback:
        # User provider: save to database
        try:
            self._save_callback(credentials)
            logger.info(f"{self.__class__.__name__}: Saved credentials via callback")
            return
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Failed to save to database: {e}")
            raise
    
    # Admin provider: save to file
    # ... existing file save logic ...
```

### Error Messages

#### Dashboard Error Display

When `get_valid_token_with_refresh()` returns `None`:

```html
<div class="alert alert-warning">
    <strong>Authentication Required</strong>
    <p>Your OAuth2 session for {provider_name} has expired.</p>
    <a href="/dashboard/{provider_id}/auth/start" class="btn btn-primary">
        Re-authenticate
    </a>
</div>
```

#### API Error Response

When `get_valid_token_with_refresh()` returns `None`:

```json
{
    "error": {
        "type": "authentication_required",
        "message": "OAuth2 authentication expired for provider '{provider_id}'. Please re-authenticate via the dashboard.",
        "provider": "{provider_id}",
        "auth_url": "/dashboard/{provider_id}/auth/start"
    }
}
```

HTTP Status: 401 Unauthorized

### Testing Strategy

#### Unit Tests

1. **Auth Class Tests** (`tests/auth/test_*_oauth2.py`)
   - Test `get_valid_token_with_refresh()` with valid token (no refresh)
   - Test `get_valid_token_with_refresh()` with expired token (triggers refresh)
   - Test refresh success (new token returned and saved)
   - Test refresh failure - expired refresh token (returns None)
   - Test refresh failure - network error (retries then returns None)
   - Test `get_valid_token()` doesn't trigger refresh

2. **Provider Handler Tests** (`tests/providers/test_*_provider.py`)
   - Test API request with valid token (succeeds)
   - Test API request with expired token (auto-refreshes, succeeds)
   - Test API request with expired refresh token (returns 401 error)
   - Test error message format (dashboard and API)

#### Integration Tests

1. **End-to-End Flow** (`tests/integration/test_oauth2_refresh.py`)
   - Authenticate user with OAuth2
   - Make API request (succeeds)
   - Manually expire access token
   - Make API request (auto-refreshes, succeeds)
   - Manually expire refresh token
   - Make API request (returns 401 with clear message)

### Migration Notes

#### Backward Compatibility

- Existing `get_valid_token()` behavior changes for ClaudeAuth (no longer refreshes)
- Code calling `get_valid_token()` expecting refresh must be updated to call `get_valid_token_with_refresh()`
- Database schema unchanged (no migration needed)

#### Deployment

1. Deploy auth class changes first
2. Deploy provider handler changes second
3. No downtime required (graceful degradation)

### Security Considerations

1. **Token Storage**: Refresh tokens remain stored with same security (file permissions 0600, database encryption)
2. **Refresh Token Rotation**: If provider rotates refresh tokens, save new refresh token from response
3. **Logging**: Never log token values, only success/failure and error types
4. **Rate Limiting**: Respect provider rate limits on token refresh endpoint (existing retry logic)

### Performance Impact

- **Proactive Refresh**: Adds ~100-200ms latency to first request after token expires (one-time per expiry)
- **Token Validation**: Adds <1ms per request (timestamp comparison)
- **Database Saves**: Adds ~10-50ms per refresh (async, non-blocking)

Overall impact: Negligible for normal usage, significant improvement in user experience.

## Implementation Plan

See separate implementation plan document for detailed task breakdown and execution order.

## Success Criteria

1. All OAuth2 providers automatically refresh expired tokens
2. No manual re-authentication required when refresh token is valid
3. Clear error messages when refresh token is expired
4. All tests pass
5. No regressions in existing OAuth2 flows
6. Consistent behavior across all providers

## Future Enhancements

1. **Proactive Refresh**: Refresh tokens before they expire (e.g., when 80% of lifetime elapsed)
2. **Background Refresh**: Periodic background task to refresh tokens before expiry
3. **Token Revocation Detection**: Detect and handle token revocation events
4. **Multi-Provider Refresh**: Batch refresh multiple providers in parallel
