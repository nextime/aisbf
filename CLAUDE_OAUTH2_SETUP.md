# Claude OAuth2 Provider Setup Guide

## Overview

AISBF now supports Claude Code (claude.ai) as a provider using OAuth2 authentication. This implementation mimics the official Claude CLI authentication flow and includes a Chrome extension to handle OAuth2 callbacks when AISBF runs on a remote server.

## Architecture

### Components

1. **ClaudeAuth Class** (`aisbf/claude_auth.py`)
   - Handles OAuth2 PKCE flow
   - Manages token storage and refresh
   - Stores credentials in `~/.claude_credentials.json` by default

2. **ClaudeProviderHandler** (`aisbf/providers.py`)
   - Implements the provider interface for Claude API
   - Handles authentication header injection
   - Supports automatic token refresh

3. **Chrome Extension** (`static/extension/`)
   - Intercepts localhost OAuth2 callbacks (port 54545)
   - Redirects callbacks to remote AISBF server
   - Auto-configures with server URL

4. **Dashboard Integration** (`templates/dashboard/providers.html`)
   - Extension detection and installation prompt
   - OAuth2 flow initiation
   - Authentication status checking

5. **Backend Endpoints** (`main.py`)
   - `/dashboard/extension/download` - Download extension ZIP
   - `/dashboard/oauth2/callback` - Receive OAuth2 callbacks
   - `/dashboard/claude/auth/start` - Start OAuth2 flow
   - `/dashboard/claude/auth/complete` - Complete token exchange
   - `/dashboard/claude/auth/status` - Check authentication status

## Setup Instructions

### 1. Add Claude Provider to Configuration

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

### 2. Install Chrome Extension (For Remote Servers)

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

### 3. Authenticate with Claude

1. Go to AISBF Dashboard → Providers
2. Expand the Claude provider
3. Click "🔐 Authenticate with Claude"
4. A browser window will open to claude.ai
5. Log in with your Claude account
6. Authorize the application
7. The window will close automatically
8. Dashboard will show "✓ Authentication successful!"

### 4. Use Claude Provider

Once authenticated, you can use Claude models via the API:

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

## How It Works

### OAuth2 Flow

1. **Initiation**:
   - User clicks "Authenticate" in dashboard
   - Dashboard calls `/dashboard/claude/auth/start`
   - Server generates PKCE challenge and returns OAuth2 URL
   - Dashboard opens URL in new window

2. **Authorization**:
   - User logs in to claude.ai
   - Claude redirects to `http://localhost:54545/callback?code=...`

3. **Callback Interception** (Remote Server):
   - Chrome extension intercepts localhost callback
   - Extension redirects to `https://your-server/dashboard/oauth2/callback?code=...`
   - Server stores code in session

4. **Token Exchange**:
   - Dashboard detects window closed
   - Calls `/dashboard/claude/auth/complete`
   - Server exchanges code for access/refresh tokens
   - Tokens saved to credentials file

5. **API Usage**:
   - ClaudeProviderHandler loads tokens from file
   - Automatically refreshes expired tokens
   - Injects Bearer token in API requests

### Extension Configuration

The extension automatically configures itself with your AISBF server URL. It intercepts requests to:
- `http://localhost:54545/*`
- `http://127.0.0.1:54545/*`

And redirects them to:
- `https://your-server/dashboard/oauth2/callback?...`

## Troubleshooting

### Extension Not Detected

**Problem**: Dashboard shows "OAuth2 Redirect Extension Required"

**Solution**:
1. Verify extension is installed in Chrome
2. Check extension is enabled in `chrome://extensions/`
3. Refresh the dashboard page
4. Try clicking "Check Status" button

### Authentication Timeout

**Problem**: "Authentication timeout. Please try again."

**Solution**:
1. Ensure extension is installed and enabled
2. Check browser console for errors
3. Verify server is accessible from browser
4. Try authentication again

### Token Expired

**Problem**: API requests fail with 401 Unauthorized

**Solution**:
1. Click "Check Status" in dashboard
2. If expired, click "Authenticate with Claude" again
3. Tokens are automatically refreshed on API calls

### Credentials File Not Found

**Problem**: "Provider 'claude' credentials not available"

**Solution**:
1. Check credentials file path in provider config
2. Ensure file exists: `ls -la ~/.claude_credentials.json`
3. Re-authenticate if file is missing or corrupted

## Security Considerations

1. **Credentials Storage**:
   - Tokens stored in `~/.claude_credentials.json`
   - File should have restricted permissions (600)
   - Contains access_token, refresh_token, and expiry

2. **Extension Permissions**:
   - Extension only intercepts localhost:54545
   - Does not access or store any data
   - Only redirects OAuth2 callbacks

3. **Token Refresh**:
   - Access tokens expire after ~1 hour
   - Automatically refreshed using refresh_token
   - Refresh tokens are long-lived

## API Compatibility

The Claude provider supports:
- ✅ Chat completions (`/v1/chat/completions`)
- ✅ Streaming responses
- ✅ System messages
- ✅ Multi-turn conversations
- ✅ Tool/function calling
- ✅ Vision (image inputs)
- ❌ Audio transcription (not supported by Claude API)
- ❌ Text-to-speech (not supported by Claude API)
- ❌ Image generation (not supported by Claude API)

## Required Headers

When using Claude provider, the following headers are automatically added:

```
Authorization: Bearer <access_token>
anthropic-version: 2023-06-01
anthropic-beta: claude-code-20250219
Content-Type: application/json
```

## Example Configuration

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

## Files Modified/Created

### New Files
- `aisbf/claude_auth.py` - OAuth2 authentication handler
- `static/extension/manifest.json` - Extension manifest
- `static/extension/background.js` - Extension service worker
- `static/extension/popup.html` - Extension popup UI
- `static/extension/popup.js` - Popup logic
- `static/extension/options.html` - Extension options page
- `static/extension/options.js` - Options logic
- `static/extension/icons/*.svg` - Extension icons
- `static/extension/README.md` - Extension documentation
- `CLAUDE_OAUTH2_SETUP.md` - This guide

### Modified Files
- `aisbf/providers.py` - Added ClaudeProviderHandler
- `aisbf/config.py` - Added claude provider type support
- `main.py` - Added OAuth2 endpoints
- `templates/dashboard/providers.html` - Added OAuth2 UI
- `templates/dashboard/user_providers.html` - Added OAuth2 UI
- `config/providers.json` - Added example configuration
- `AI.PROMPT` - Added Claude provider documentation

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review extension console logs
3. Check AISBF server logs
4. Verify OAuth2 flow in browser network tab

## References

- Claude API Documentation: https://docs.anthropic.com/
- OAuth2 PKCE Flow: https://oauth.net/2/pkce/
- Chrome Extension Development: https://developer.chrome.com/docs/extensions/
