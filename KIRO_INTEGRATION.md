# Kiro Integration for AISBF

## Overview

AISBF now includes **direct integration** with Kiro (Amazon Q Developer), allowing you to use Claude models through your Kiro IDE or kiro-cli credentials without running a separate kiro-gateway server.

This integration was built by analyzing and incorporating the core functionality from the [kiro-gateway](https://github.com/jwadow/kiro-gateway) project directly into AISBF.

## Features

- **Direct API Integration**: Makes API calls directly to Amazon Q Developer's API
- **Multiple Credential Sources**: Supports Kiro IDE, kiro-cli, and environment variables
- **Automatic Token Refresh**: Handles token expiration and refresh automatically
- **No External Dependencies**: No need to run kiro-gateway as a separate service
- **Multiple Authentication Types**: Supports both Kiro Desktop Auth and AWS SSO OIDC

## Architecture

The integration consists of three main components:

1. **`aisbf/kiro_auth.py`**: Authentication manager that handles:
   - Loading credentials from multiple sources
   - Token refresh for both Kiro Desktop Auth and AWS SSO OIDC
   - Automatic token lifecycle management

2. **`aisbf/kiro_utils.py`**: Utility functions for:
   - Machine fingerprint generation
   - Model name normalization
   - Request/response format conversion

3. **`aisbf/providers.py`**: KiroProviderHandler that:
   - Uses KiroAuthManager for authentication
   - Makes direct HTTP requests to Kiro's API
   - Converts between OpenAI format and Kiro format

## Configuration

### Method 1: Using Kiro IDE Credentials (JSON File)

If you have Kiro IDE (VS Code extension) installed, AISBF can use its credentials directly.

**Location**: `~/.config/Code/User/globalStorage/amazon.q/credentials.json`

**Configuration in `~/.aisbf/providers.json`**:

```json
{
  "providers": {
    "kiro": {
      "id": "kiro",
      "name": "Kiro (Amazon Q Developer)",
      "endpoint": "https://q.us-east-1.amazonaws.com",
      "type": "kiro",
      "api_key_required": false,
      "rate_limit": 0,
      "kiro_config": {
        "creds_file": "~/.config/Code/User/globalStorage/amazon.q/credentials.json",
        "region": "us-east-1"
      }
    }
  }
}
```

### Method 2: Using kiro-cli Credentials (SQLite Database)

If you have kiro-cli installed, AISBF can use its credentials from the SQLite database.

**Location**: `~/.local/share/kiro-cli/data.sqlite3`

**Configuration in `~/.aisbf/providers.json`**:

```json
{
  "providers": {
    "kiro-cli": {
      "id": "kiro-cli",
      "name": "Kiro CLI (Amazon Q Developer)",
      "endpoint": "https://q.us-east-1.amazonaws.com",
      "type": "kiro",
      "api_key_required": false,
      "rate_limit": 0,
      "kiro_config": {
        "sqlite_db": "~/.local/share/kiro-cli/data.sqlite3",
        "region": "us-east-1"
      }
    }
  }
}
```

### Method 3: Using Environment Variables

You can also provide credentials directly via environment variables or configuration.

**Configuration in `~/.aisbf/providers.json`**:

```json
{
  "providers": {
    "kiro": {
      "id": "kiro",
      "name": "Kiro (Amazon Q Developer)",
      "endpoint": "https://q.us-east-1.amazonaws.com",
      "type": "kiro",
      "api_key_required": false,
      "rate_limit": 0,
      "kiro_config": {
        "refresh_token": "your-refresh-token-here",
        "profile_arn": "arn:aws:codewhisperer:us-east-1:...",
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
        "region": "us-east-1"
      }
    }
  }
}
```

## Available Models

The following Claude models are available through Kiro:

- `anthropic.claude-3-5-sonnet-20241022-v2:0` - Claude 3.5 Sonnet v2 (latest)
- `anthropic.claude-3-5-haiku-20241022-v1:0` - Claude 3.5 Haiku
- `anthropic.claude-3-5-sonnet-20240620-v1:0` - Claude 3.5 Sonnet v1
- `anthropic.claude-sonnet-3-5-v2` - Claude 3.5 Sonnet v2 (alias)

## Usage Examples

### Using Kiro Provider Directly

```bash
# Using Kiro provider with a specific model
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "kiro",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

### Using Kiro in a Rotation

Add Kiro to your rotation configuration in `~/.aisbf/rotations.json`:

```json
{
  "rotations": {
    "kiro-claude": {
      "providers": [
        {
          "provider_id": "kiro",
          "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
          "weight": 1
        },
        {
          "provider_id": "kiro-cli",
          "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
          "weight": 1
        }
      ],
      "notifyerrors": true
    }
  }
}
```

Then use the rotation:

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "rotation_id": "kiro-claude",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

## Authentication Types

### Kiro Desktop Auth

Used by Kiro IDE (VS Code extension). Credentials are stored in JSON format.

- **Token URL**: `https://prod.{region}.auth.desktop.kiro.dev/refreshToken`
- **Method**: POST with JSON body containing refresh token
- **Response**: Access token with expiration time

### AWS SSO OIDC

Used by kiro-cli. Credentials are stored in SQLite database.

- **Token URL**: `https://oidc.{region}.amazonaws.com/token`
- **Method**: POST with form data (grant_type, client_id, client_secret, refresh_token)
- **Response**: Access token with expiration time

## Regions

Kiro supports multiple AWS regions:

- `us-east-1` (default)
- `eu-central-1`
- `ap-southeast-1`
- `us-west-2`

The API endpoint is always `https://q.{region}.amazonaws.com`, regardless of the region.

## Troubleshooting

### "Kiro authentication not configured"

**Cause**: No valid credentials found in any of the configured sources.

**Solution**: 
1. Verify that Kiro IDE or kiro-cli is installed and authenticated
2. Check that the credential file/database path is correct
3. Ensure the credentials haven't expired

### "Profile ARN not available"

**Cause**: The profile ARN couldn't be loaded from credentials.

**Solution**:
1. Re-authenticate with Kiro IDE or kiro-cli
2. Verify that your AWS account has access to Amazon Q Developer
3. Check that the credentials file contains a valid profile ARN

### Token Refresh Failures

**Cause**: Refresh token has expired or is invalid.

**Solution**:
1. Re-authenticate with Kiro IDE or kiro-cli
2. Check that your AWS credentials are still valid
3. Verify network connectivity to AWS endpoints

### "Improperly formed request"

**Cause**: The request format doesn't match Kiro API requirements.

**Solution**:
1. Check that you're using a valid model ID
2. Ensure messages are properly formatted
3. Review the logs for specific error details

## Logging

Enable debug logging to see detailed information about Kiro API calls:

```bash
export AISBF_DEBUG=true
python -m aisbf.main
```

This will show:
- Authentication attempts and token refresh
- API request/response details
- Credential loading process
- Error details

## Comparison with kiro-gateway

### Before (External kiro-gateway)

```
Client → AISBF → kiro-gateway (separate process) → Kiro API
```

**Drawbacks**:
- Need to run kiro-gateway as a separate service
- Additional network hop
- More complex deployment

### After (Direct Integration)

```
Client → AISBF → Kiro API
```

**Benefits**:
- No external dependencies
- Simpler deployment
- Lower latency
- Unified configuration

## Credits

This integration was built by analyzing and incorporating functionality from:
- [kiro-gateway](https://github.com/jwadow/kiro-gateway) by Jwadow

The core authentication and API interaction logic was adapted from kiro-gateway's implementation.

## License

The Kiro integration code in AISBF is licensed under the GNU General Public License v3.0, consistent with AISBF's license.

The original kiro-gateway project is licensed under the GNU Affero General Public License v3.0.
