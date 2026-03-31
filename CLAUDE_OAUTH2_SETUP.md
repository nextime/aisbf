# Claude OAuth2 Provider Setup Guide

## ⚠️ IMPORTANT: Current Implementation Status

**The Claude provider implementation is currently NOT WORKING as documented.**

### The Problem

The Anthropic API at `api.anthropic.com/v1/messages` **does NOT support OAuth2 Bearer token authentication**. When attempting to use OAuth2 tokens, the API returns:

```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "OAuth authentication is currently not supported."
  }
}
```

### What Actually Works

The working implementation in `vendors/opencode-claude-max-proxy` uses a **completely different approach**:

1. **Uses Claude SDK** (`@anthropic-ai/claude-agent-sdk`) - NOT direct API calls
2. **Authenticates via Claude CLI** (`claude auth status`) - NOT OAuth2 Bearer tokens
3. **Session-based authentication** through Claude Code infrastructure
4. **Acts as a proxy** that translates OpenAI-format requests to Claude SDK calls

### Required Changes

The current implementation in [`aisbf/providers.py`](aisbf/providers.py:2300) needs to be completely rewritten to:
- Use the Claude SDK instead of direct HTTP calls
- Authenticate using Claude CLI credentials (stored in `~/.claude/.credentials.json`)
- Proxy requests through the Claude Code infrastructure
- NOT use OAuth2 Bearer tokens against the public API

## Overview (Original Documentation - OUTDATED)

AISBF **attempts** to support Claude Code (claude.ai) as a provider using OAuth2 authentication with automatic token refresh. This implementation matches the official Claude CLI authentication flow and includes a Chrome extension to handle OAuth2 callbacks when AISBF runs on a remote server.

**Intended Features (NOT CURRENTLY WORKING):**
- Full OAuth2 PKCE flow matching official claude-cli
- Automatic token refresh with refresh token rotation
- Chrome extension for remote server OAuth2 callback interception
- Dashboard integration with authentication UI
- Optional curl_cffi TLS fingerprinting for Cloudflare bypass
- Compatible with official claude-cli credentials

## Architecture (OUTDATED)

### Components

1. **ClaudeAuth Class** (`aisbf/claude_auth.py`)
   - Handles OAuth2 PKCE flow ✅ (Works)
   - Manages token storage and refresh ✅ (Works)
   - Stores credentials in `~/.claude_credentials.json` by default ✅ (Works)

2. **ClaudeProviderHandler** (`aisbf/providers.py`)
   - ❌ **BROKEN**: Attempts to use OAuth2 Bearer tokens against `api.anthropic.com`
   - ❌ **BROKEN**: API explicitly rejects OAuth authentication
   - ❌ **NEEDS REWRITE**: Should use Claude SDK like the working proxy implementation

3. **Chrome Extension** (`static/extension/`)
   - Intercepts localhost OAuth2 callbacks (port 54545) ✅ (Works)
   - Redirects callbacks to remote AISBF server ✅ (Works)
   - Auto-configures with server URL ✅ (Works)

4. **Dashboard Integration** (`templates/dashboard/providers.html`)
   - Extension detection and installation prompt ✅ (Works)
   - OAuth2 flow initiation ✅ (Works)
   - Authentication status checking ✅ (Works)

5. **Backend Endpoints** (`main.py`)
   - `/dashboard/extension/download` - Download extension ZIP ✅ (Works)
   - `/dashboard/oauth2/callback` - Receive OAuth2 callbacks ✅ (Works)
   - `/dashboard/claude/auth/start` - Start OAuth2 flow ✅ (Works)
   - `/dashboard/claude/auth/complete` - Complete token exchange ✅ (Works)
   - `/dashboard/claude/auth/status` - Check authentication status ✅ (Works)

**Summary**: OAuth2 authentication flow works perfectly. The problem is that the obtained tokens **cannot be used** to call the Anthropic API because the API doesn't support OAuth2 Bearer authentication.

## Why This Doesn't Work

The fundamental issue is an **architectural mismatch**:

### What We Implemented (WRONG)
```python
# aisbf/providers.py - ClaudeProviderHandler
headers = {
    'Authorization': f'Bearer {access_token}',  # ❌ API rejects this
    'anthropic-version': '2023-06-01',
    'anthropic-beta': 'claude-code-20250219',
    'Content-Type': 'application/json'
}

response = await self.client.post(
    'https://api.anthropic.com/v1/messages',  # ❌ This endpoint doesn't support OAuth2
    headers=headers,
    json=request_payload
)
```

### What Actually Works (vendors/opencode-claude-max-proxy)
```typescript
// Uses Claude SDK, NOT direct API calls
import { query } from "@anthropic-ai/claude-agent-sdk"

// Authenticates via Claude CLI credentials
const { stdout } = await exec("claude auth status", { timeout: 5000 })
const auth = JSON.parse(stdout)

// Makes SDK calls (session-based, NOT Bearer tokens)
for await (const event of query({
    prompt: makePrompt(),
    model,
    workingDirectory,
    // ... SDK-specific options
})) {
    // Process SDK events
}
```

## What Needs to Be Fixed

To make the Claude provider work, the implementation needs to:

1. **Install Claude SDK** as a dependency (Node.js package)
2. **Use Claude CLI credentials** from `~/.claude/.credentials.json`
3. **Call Claude SDK** instead of making direct HTTP requests
4. **Proxy SDK responses** back to OpenAI format
5. **Remove OAuth2 Bearer token usage** from API calls

This is a **major architectural change** that requires:
- Adding Node.js/TypeScript dependencies
- Rewriting ClaudeProviderHandler to use the SDK
- Potentially running a separate Node.js proxy process
- Or using the existing `opencode-claude-max-proxy` as a subprocess

## Setup Instructions (OUTDATED - DO NOT FOLLOW)

⚠️ **WARNING**: The following instructions will allow you to authenticate via OAuth2, but the resulting tokens **will not work** for API calls. The provider will fail with "OAuth authentication is currently not supported."

### 1. Add Claude Provider to Configuration (OUTDATED)

Edit `~/.aisbf/providers.json` or use the dashboard:

```json
{
  "providers": {
    "claude": {
      "id": "claude",
      "name": "Claude Code (OAuth2)",
      "endpoint": "https://api.anthropic.com/v1",
      "type": "claude",
      "api_key_required": false,
      "rate_limit": 0,
      "claude_config": {
        "credentials_file": "~/.claude_credentials.json"
      },
      "models": [
        {
          "name": "claude-3-7-sonnet-20250219",
          "context_size": 200000,
          "rate_limit": 0
        }
      ]
    }
  }
}
```

⚠️ **This configuration will NOT work** because the endpoint `https://api.anthropic.com/v1` does not support OAuth2 Bearer authentication.

### 2. Install Chrome Extension (For Remote Servers) (STILL WORKS)

If AISBF runs on a remote server (not localhost), you need the OAuth2 redirect extension:

1. **Download Extension**:
   - Go to AISBF Dashboard → Providers
   - Expand the Claude provider
   - Click "Authenticate with Claude"
   - If extension is not detected, click "Download Extension"

2. **Install in Chrome**:
   - Extract the downloaded ZIP file
   - Open Chrome and go to `chrome://extensions/`
   - Enable "Developer mode" (toggle in top-right)
   - Click "Load unpacked"
   - Select the extracted extension folder

3. **Verify Installation**:
   - Extension icon should appear in toolbar
   - Click "Check Status" in dashboard to verify

✅ **This part works correctly** - the extension successfully intercepts OAuth2 callbacks.

### 3. Authenticate with Claude (WORKS BUT TOKENS ARE UNUSABLE)

1. Go to AISBF Dashboard → Providers
2. Expand the Claude provider
3. Click "🔐 Authenticate with Claude"
4. A browser window will open to claude.ai
5. Log in with your Claude account
6. Authorize the application
7. The window will close automatically
8. Dashboard will show "✓ Authentication successful!"

✅ **OAuth2 flow works perfectly** - you will successfully obtain access and refresh tokens.

❌ **BUT**: These tokens cannot be used to call the Anthropic API because the API doesn't support OAuth2 Bearer authentication.

### 4. Use Claude Provider (DOES NOT WORK)

Once authenticated, attempting to use Claude models via the API will fail:

```bash
curl -X POST http://your-server:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "model": "claude/claude-3-7-sonnet-20250219",
    "messages": [
      {"role": "user", "content": "Hello, Claude!"}
    ]
  }'
```

**Result**: 401 Unauthorized with error message:
```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "OAuth authentication is currently not supported."
  }
}
```

## How It Works (OAuth2 Flow - This Part Works)

### OAuth2 Flow (FUNCTIONAL)

1. **Initiation**:
   - User clicks "Authenticate" in dashboard ✅
   - Dashboard calls `/dashboard/claude/auth/start` ✅
   - Server generates PKCE challenge and returns OAuth2 URL ✅
   - Dashboard opens URL in new window ✅

2. **Authorization**:
   - User logs in to claude.ai ✅
   - Claude redirects to `http://localhost:54545/callback?code=...` ✅

3. **Callback Interception** (Remote Server):
   - Chrome extension intercepts localhost callback ✅
   - Extension redirects to `https://your-server/dashboard/oauth2/callback?code=...` ✅
   - Server stores code in session ✅

4. **Token Exchange**:
   - Dashboard detects window closed ✅
   - Calls `/dashboard/claude/auth/complete` ✅
   - Server exchanges code for access/refresh tokens ✅
   - Tokens saved to credentials file ✅

5. **API Usage** (❌ THIS IS WHERE IT FAILS):
   - ClaudeProviderHandler loads tokens from file ✅
   - Automatically refreshes expired tokens ✅
   - Injects Bearer token in API requests ✅
   - **API rejects OAuth2 Bearer tokens** ❌
   - **Returns "OAuth authentication is currently not supported"** ❌

### Extension Configuration (WORKS CORRECTLY)

The extension automatically configures itself with your AISBF server URL. It intercepts requests to:
- `http://localhost:54545/*`
- `http://127.0.0.1:54545/*`

And redirects them to:
- `https://your-server/dashboard/oauth2/callback?...`

✅ **This works perfectly** - the extension successfully handles OAuth2 callback redirection.

## Troubleshooting

### The Real Problem: API Doesn't Support OAuth2

**Problem**: All API requests fail with 401 Unauthorized:
```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "OAuth authentication is currently not supported."
  }
}
```

**Root Cause**: The Anthropic API at `api.anthropic.com/v1/messages` does **NOT** support OAuth2 Bearer token authentication. This is a fundamental architectural issue, not a configuration problem.

**Solution**: The implementation needs to be completely rewritten to use the Claude SDK (like `vendors/opencode-claude-max-proxy`) instead of direct API calls.

### Extension Not Detected (STILL RELEVANT)

**Problem**: Dashboard shows "OAuth2 Redirect Extension Required"

**Solution**:
1. Verify extension is installed in Chrome ✅
2. Check extension is enabled in `chrome://extensions/` ✅
3. Refresh the dashboard page ✅
4. Try clicking "Check Status" button ✅

✅ **This troubleshooting is still valid** - extension detection works correctly.

### Authentication Timeout (STILL RELEVANT)

**Problem**: "Authentication timeout. Please try again."

**Solution**:
1. Ensure extension is installed and enabled ✅
2. Check browser console for errors ✅
3. Verify server is accessible from browser ✅
4. Try authentication again ✅

✅ **This troubleshooting is still valid** - OAuth2 flow works correctly.

### Token Expired (MISLEADING - TOKENS DON'T WORK AT ALL)

**Problem**: API requests fail with 401 Unauthorized

**Original Solution** (WRONG):
1. Click "Check Status" in dashboard
2. If expired, click "Authenticate with Claude" again
3. Tokens are automatically refreshed on API calls

**Actual Problem**: The API doesn't support OAuth2 Bearer tokens at all. Token expiration is irrelevant because even fresh tokens are rejected with "OAuth authentication is currently not supported."

### Credentials File Not Found (STILL RELEVANT)

**Problem**: "Provider 'claude' credentials not available"

**Solution**:
1. Check credentials file path in provider config ✅
2. Ensure file exists: `ls -la ~/.claude_credentials.json` ✅
3. Re-authenticate if file is missing or corrupted ✅

✅ **This troubleshooting is still valid** - credentials file management works correctly.

## Security Considerations (STILL VALID)

1. **Credentials Storage**:
   - Tokens stored in `~/.claude_credentials.json` ✅
   - File should have restricted permissions (600) ✅
   - Contains access_token, refresh_token, and expiry ✅

2. **Extension Permissions**:
   - Extension only intercepts localhost:54545 ✅
   - Does not access or store any data ✅
   - Only redirects OAuth2 callbacks ✅

3. **Token Refresh**:
   - Access tokens expire after ~1 hour ✅
   - Automatically refreshed using refresh_token ✅
   - Refresh tokens are long-lived ✅

✅ **All security considerations are still valid** - the OAuth2 implementation is secure.

## API Compatibility (INCORRECT - NOTHING WORKS)

The Claude provider **claims** to support:
- ❌ Chat completions (`/v1/chat/completions`) - **FAILS: OAuth not supported**
- ❌ Streaming responses - **FAILS: OAuth not supported**
- ❌ System messages - **FAILS: OAuth not supported**
- ❌ Multi-turn conversations - **FAILS: OAuth not supported**
- ❌ Tool/function calling - **FAILS: OAuth not supported**
- ❌ Vision (image inputs) - **FAILS: OAuth not supported**
- ❌ Audio transcription - **Not supported by Claude API**
- ❌ Text-to-speech - **Not supported by Claude API**
- ❌ Image generation - **Not supported by Claude API**

**Reality**: Nothing works because the API rejects OAuth2 Bearer tokens.

## Required Headers (CORRECT BUT INEFFECTIVE)

When using Claude provider, the following headers are automatically added:

```
Authorization: Bearer <access_token>  # ❌ API rejects this
anthropic-version: 2023-06-01
anthropic-beta: claude-code-20250219
Content-Type: application/json
```

✅ **Headers are correctly formatted** - the implementation properly constructs the headers.

❌ **But the API rejects them** - the `Authorization: Bearer` header causes the API to return "OAuth authentication is currently not supported."

## Example Configuration (WILL NOT WORK)

Complete provider configuration with multiple models:

```json
{
  "providers": {
    "claude": {
      "id": "claude",
      "name": "Claude Code",
      "endpoint": "https://api.anthropic.com/v1",
      "type": "claude",
      "api_key_required": false,
      "rate_limit": 0,
      "default_rate_limit_TPM": 40000,
      "default_rate_limit_TPH": 400000,
      "default_context_size": 200000,
      "claude_config": {
        "credentials_file": "~/.claude_credentials.json"
      },
      "models": [
        {
          "name": "claude-3-7-sonnet-20250219",
          "context_size": 200000,
          "rate_limit": 0,
          "rate_limit_TPM": 40000,
          "rate_limit_TPH": 400000
        },
        {
          "name": "claude-3-5-sonnet-20241022",
          "context_size": 200000,
          "rate_limit": 0,
          "rate_limit_TPM": 40000,
          "rate_limit_TPH": 400000
        }
      ]
    }
  }
}
```

⚠️ **This configuration is syntactically correct but functionally broken** - all API calls will fail with "OAuth authentication is currently not supported."

## Files Modified/Created (ACCURATE)

### New Files
- `aisbf/claude_auth.py` - OAuth2 authentication handler ✅ (Works correctly)
- `static/extension/manifest.json` - Extension manifest ✅ (Works correctly)
- `static/extension/background.js` - Extension service worker ✅ (Works correctly)
- `static/extension/popup.html` - Extension popup UI ✅ (Works correctly)
- `static/extension/popup.js` - Popup logic ✅ (Works correctly)
- `static/extension/options.html` - Extension options page ✅ (Works correctly)
- `static/extension/options.js` - Options logic ✅ (Works correctly)
- `static/extension/icons/*.svg` - Extension icons ✅ (Works correctly)
- `static/extension/README.md` - Extension documentation ✅ (Works correctly)
- `CLAUDE_OAUTH2_SETUP.md` - This guide ⚠️ (Now updated with reality)

### Modified Files
- `aisbf/providers.py` - Added ClaudeProviderHandler ❌ (Broken - uses wrong auth method)
- `aisbf/config.py` - Added claude provider type support ✅ (Works correctly)
- `main.py` - Added OAuth2 endpoints ✅ (Works correctly)
- `templates/dashboard/providers.html` - Added OAuth2 UI ✅ (Works correctly)
- `templates/dashboard/user_providers.html` - Added OAuth2 UI ✅ (Works correctly)
- `config/providers.json` - Added example configuration ⚠️ (Config is correct but won't work)
- `AI.PROMPT` - Added Claude provider documentation ⚠️ (Needs updating)

## Summary: What Works and What Doesn't

### ✅ What Works Perfectly

1. **OAuth2 Authentication Flow**
   - PKCE challenge generation
   - Authorization URL creation
   - Chrome extension callback interception
   - Token exchange
   - Token storage and refresh
   - Dashboard UI integration

2. **Infrastructure**
   - Chrome extension (fully functional)
   - Backend OAuth2 endpoints (fully functional)
   - Credentials file management (fully functional)
   - Token refresh mechanism (fully functional)

### ❌ What Doesn't Work At All

1. **API Calls**
   - All requests to `api.anthropic.com/v1/messages` fail
   - API explicitly rejects OAuth2 Bearer tokens
   - Error: "OAuth authentication is currently not supported"
   - No workaround available with current architecture

2. **ClaudeProviderHandler**
   - Correctly formats requests
   - Correctly adds headers
   - But uses wrong authentication method
   - Needs complete rewrite to use Claude SDK

### 🔧 What Needs to Be Fixed

To make the Claude provider actually work, the implementation needs to:

1. **Use Claude SDK** (`@anthropic-ai/claude-agent-sdk`)
   - Install as Node.js dependency
   - Call SDK methods instead of HTTP API
   - Handle SDK event stream format

2. **Use Claude CLI Credentials**
   - Read from `~/.claude/.credentials.json` (not `~/.claude_credentials.json`)
   - Use session-based authentication
   - Not OAuth2 Bearer tokens

3. **Implement Proxy Architecture**
   - Run Node.js subprocess with Claude SDK
   - Translate OpenAI format → Claude SDK format
   - Translate Claude SDK events → OpenAI format
   - Or use existing `opencode-claude-max-proxy` as subprocess

4. **Update Documentation**
   - Clarify this is a proxy to Claude Code, not direct API
   - Document Claude CLI requirement
   - Explain session-based authentication
   - Remove misleading OAuth2 Bearer token claims

## Support (UPDATED)

For issues or questions:
1. **OAuth2 Flow Issues**: Check the troubleshooting section above - OAuth2 works correctly
2. **API Call Failures**: This is expected - the API doesn't support OAuth2 Bearer tokens
3. **Extension Issues**: Review extension console logs - extension works correctly
4. **Server Issues**: Check AISBF server logs - backend endpoints work correctly
5. **Implementation Issues**: See "What Needs to Be Fixed" section above

**Known Issue**: The Claude provider implementation is fundamentally broken because it attempts to use OAuth2 Bearer tokens against an API that doesn't support them. This requires a complete architectural rewrite to use the Claude SDK instead of direct API calls.

## References

- Claude API Documentation: https://docs.anthropic.com/
- OAuth2 PKCE Flow: https://oauth.net/2/pkce/
- Chrome Extension Development: https://developer.chrome.com/docs/extensions/
- **Working Implementation**: See `vendors/opencode-claude-max-proxy` for a functional Claude Code proxy using the Claude SDK
- **Claude SDK**: `@anthropic-ai/claude-agent-sdk` (Node.js package required for working implementation)

## Conclusion

This documentation has been updated to reflect the **actual state** of the Claude provider implementation:

- ✅ **OAuth2 authentication works perfectly** - you can successfully obtain tokens
- ❌ **API calls don't work at all** - the API rejects OAuth2 Bearer tokens
- 🔧 **Major rewrite required** - needs to use Claude SDK instead of direct API calls

The implementation in [`aisbf/providers.py`](aisbf/providers.py:2300) (ClaudeProviderHandler) needs to be completely rewritten to match the working implementation in [`vendors/opencode-claude-max-proxy`](vendors/opencode-claude-max-proxy/src/proxy/server.ts:1), which uses the Claude SDK with session-based authentication instead of OAuth2 Bearer tokens against the public API.

**DO NOT attempt to use this provider** until the implementation is fixed. All API calls will fail with "OAuth authentication is currently not supported."
