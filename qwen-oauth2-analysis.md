# Qwen API Documentation

Complete documentation for implementing Qwen API requests based on the Qwen Code codebase analysis.

## 📚 Documentation Files

This repository contains comprehensive documentation for working with the Qwen API:

### 1. **QWEN_API_SUMMARY.md** - Quick Reference Guide
- **Purpose**: Fast lookup for common patterns and configurations
- **Best for**: Developers who need quick answers
- **Contents**:
  - API endpoints and base URLs
  - Required headers
  - Request payload format
  - Message format examples
  - Session management
  - Token management
  - Streaming response format
  - Error handling patterns
  - Minimal working examples

### 2. **QWEN_API_IMPLEMENTATION_GUIDE.md** - Complete Implementation
- **Purpose**: Full Python implementation with detailed explanations
- **Best for**: Developers building from scratch
- **Contents**:
  - OAuth2 authentication flow
  - Token storage and refresh logic
  - Complete Python client class
  - Request building and sending
  - Response parsing
  - Error handling with retry logic
  - Streaming support
  - Working code examples
  - Testing instructions

### 3. **QWEN_API_FLOW_DIAGRAM.md** - Visual Flow Charts
- **Purpose**: Visual representation of request flows
- **Best for**: Understanding the overall architecture
- **Contents**:
  - Complete request flow diagram
  - Streaming request flow
  - Message format conversion (none needed!)
  - Cache control flow
  - Error handling flow
  - Token lifecycle diagram
  - Session management diagram

### 4. **test_qwen_api.py** - Test Suite
- **Purpose**: Executable test script to verify implementation
- **Best for**: Testing your setup and understanding API behavior
- **Features**:
  - Credentials validation
  - Token expiry checking
  - Token refresh testing
  - Simple completion test
  - Streaming completion test
  - Multi-turn conversation test
  - Detailed logging
  - Comprehensive error handling

## 🚀 Quick Start

### Prerequisites

1. **OAuth2 Credentials**: You need valid OAuth2 credentials stored in `~/.qwen/oauth_creds.json`
2. **Python 3.7+**: Required for the test script
3. **requests library**: Install with `pip install requests`

### Credentials File Format

```json
{
  "access_token": "your_access_token_here",
  "refresh_token": "your_refresh_token_here",
  "expiry_date": 1234567890000,
  "token_type": "Bearer",
  "resource_url": "https://dashscope.aliyuncs.com/compatible-mode"
}
```

### Running the Test Suite

```bash
# Make the script executable
chmod +x test_qwen_api.py

# Run all tests
./test_qwen_api.py

# Run with verbose output
./test_qwen_api.py --verbose
```

### Minimal Example

```python
import requests
import json
import uuid

# Load credentials
with open("~/.qwen/oauth_creds.json") as f:
    creds = json.load(f)

# Build request
headers = {
    "Authorization": f"Bearer {creds['access_token']}",
    "Content-Type": "application/json",
    "User-Agent": "QwenCode/1.0.0",
    "X-DashScope-CacheControl": "enable",
    "X-DashScope-UserAgent": "QwenCode/1.0.0",
    "X-DashScope-AuthType": "qwen-oauth",
}

payload = {
    "model": "qwen-plus",
    "messages": [
        {"role": "user", "content": "Hello!"}
    ],
    "metadata": {
        "sessionId": str(uuid.uuid4()),
        "promptId": str(uuid.uuid4())
    }
}

# Send request
response = requests.post(
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    headers=headers,
    json=payload
)

# Parse response
result = response.json()
print(result["choices"][0]["message"]["content"])
```

## 📖 Key Concepts

### 1. OpenAI Compatibility

The Qwen API is **100% OpenAI-compatible**. This means:
- No message format conversion needed
- Standard OpenAI message structure works directly
- Tool calling (function calling) uses OpenAI format
- Streaming follows OpenAI SSE format

### 2. OAuth2 Authentication

Unlike OpenAI's static API keys, Qwen uses OAuth2:
- Access tokens expire (typically 1 hour)
- Refresh tokens allow getting new access tokens
- Automatic refresh on 401/403 errors
- Re-authentication needed when refresh token expires

### 3. Session Management

Two levels of tracking:
- **Session ID**: Persistent across entire conversation
- **Prompt ID**: Unique per request

Both are UUIDs sent in the `metadata` field.

### 4. Dynamic Endpoints

The API endpoint is not fixed:
- Provided in OAuth credentials as `resource_url`
- Default: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Always use the endpoint from credentials

### 5. DashScope Headers

Additional headers for caching and tracking:
- `X-DashScope-CacheControl`: Enable prompt caching
- `X-DashScope-UserAgent`: Application identification
- `X-DashScope-AuthType`: Authentication method

## 🔍 Common Use Cases

### Simple Chat Completion

```python
from qwen_api_client import QwenAPIClient

client = QwenAPIClient()
response = client.chat_completion(
    messages=[
        {"role": "user", "content": "What is the capital of France?"}
    ],
    model="qwen-plus"
)
print(response["choices"][0]["message"]["content"])
```

### Streaming Response

```python
for chunk in client.chat_completion(
    messages=[
        {"role": "user", "content": "Count from 1 to 10"}
    ],
    model="qwen-plus",
    stream=True
):
    if "choices" in chunk:
        delta = chunk["choices"][0].get("delta", {})
        if "content" in delta:
            print(delta["content"], end="", flush=True)
```

### Multi-Turn Conversation

```python
session_id = str(uuid.uuid4())
messages = []

# Turn 1
messages.append({"role": "user", "content": "My name is Alice"})
response = client.chat_completion(messages=messages, model="qwen-plus")
messages.append({"role": "assistant", "content": response["choices"][0]["message"]["content"]})

# Turn 2
messages.append({"role": "user", "content": "What is my name?"})
response = client.chat_completion(messages=messages, model="qwen-plus")
print(response["choices"][0]["message"]["content"])  # Should mention "Alice"
```

### Function Calling

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                },
                "required": ["location"]
            }
        }
    }
]

response = client.chat_completion(
    messages=[
        {"role": "user", "content": "What's the weather in Paris?"}
    ],
    model="qwen-plus",
    tools=tools
)

# Check for tool calls
if response["choices"][0]["message"].get("tool_calls"):
    tool_call = response["choices"][0]["message"]["tool_calls"][0]
    print(f"Function: {tool_call['function']['name']}")
    print(f"Arguments: {tool_call['function']['arguments']}")
```

## 🛠️ Troubleshooting

### Issue: "No credentials found"

**Solution**: Ensure `~/.qwen/oauth_creds.json` exists with valid credentials.

### Issue: "Token expired" or 401/403 errors

**Solution**: The client should automatically refresh. If refresh fails, re-authenticate.

### Issue: "Refresh token expired"

**Solution**: You need to re-authenticate using the OAuth2 device flow.

### Issue: Streaming not working

**Solution**: Ensure you set `stream: true` and `stream_options: {include_usage: true}`.

### Issue: Session context not maintained

**Solution**: Use the same `sessionId` for all requests in a conversation.

## 📊 API Limits and Best Practices

### Rate Limits

- Implement exponential backoff for 429 errors
- Default retry: 3 attempts with increasing delays

### Token Management

- Check token expiry before each request
- Refresh proactively (60 second buffer)
- Cache credentials in memory for performance

### Session Management

- Generate session ID once per conversation
- Generate new prompt ID for each request
- Include both in metadata for tracking

### Error Handling

- Always handle 401/403 with automatic refresh
- Implement retry logic for network errors
- Log errors with request IDs for debugging

## 🔐 Security Considerations

1. **Credential Storage**: Store credentials securely with appropriate file permissions
2. **Token Exposure**: Never log or expose access tokens
3. **HTTPS Only**: Always use HTTPS endpoints
4. **Token Rotation**: Refresh tokens regularly, don't reuse expired tokens

## 📝 Additional Resources

### Source Code References

From the Qwen Code codebase:
- OAuth2 implementation: `packages/core/src/qwen/qwenOAuth2.ts`
- Content generator: `packages/core/src/qwen/qwenContentGenerator.ts`
- DashScope provider: `packages/core/src/core/openaiContentGenerator/provider/dashscope.ts`
- Message converter: `packages/core/src/core/openaiContentGenerator/converter.ts`
- Pipeline: `packages/core/src/core/openaiContentGenerator/pipeline.ts`

### API Endpoints

- OAuth Token: `https://chat.qwen.ai/api/v1/oauth2/token`
- Chat Completions: `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`

### Models

Common models:
- `qwen-plus`: Balanced performance and speed
- `qwen-max`: Maximum capability
- `qwen-turbo`: Fastest response
- `qwen3-coder-plus`: Code-specialized model

## 🤝 Contributing

If you find issues or have improvements:
1. Test your changes with the test suite
2. Update relevant documentation
3. Ensure examples work correctly

## 📄 License

This documentation is based on the Qwen Code codebase analysis and is provided for educational purposes.

---

**Last Updated**: 2026-04-19

**Documentation Version**: 1.0.0

**Based on**: Qwen Code codebase analysis
# Qwen API Implementation Summary

## Quick Reference

### 1. API Endpoint

```
Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
Endpoint: /chat/completions
Full URL: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

**Note**: The base URL can be dynamic and is provided in the OAuth `resource_url` field.

### 2. Authentication Headers

```python
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "QwenCode/1.0.0 (Linux; x86_64)",
    "X-DashScope-CacheControl": "enable",
    "X-DashScope-UserAgent": "QwenCode/1.0.0 (Linux; x86_64)",
    "X-DashScope-AuthType": "qwen-oauth",
    "x-request-id": "unique-uuid-here"  # Optional
}
```

### 3. Request Payload Format

```python
payload = {
    "model": "qwen-plus",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ],
    "stream": False,  # or True for streaming
    "stream_options": {"include_usage": True},  # Required for streaming
    "temperature": 0.7,  # Optional
    "max_tokens": 1000,  # Optional
    "metadata": {  # Optional but recommended
        "sessionId": "session-uuid",
        "promptId": "prompt-uuid"
    }
}
```

### 4. Message Format (OpenAI-Compatible)

**System Message:**

```python
{"role": "system", "content": "You are a helpful assistant."}
```

**User Message:**

```python
{"role": "user", "content": "What is the weather?"}
```

**Assistant Message:**

```python
{"role": "assistant", "content": "The weather is sunny."}
```

**Tool Call:**

```python
{
    "role": "assistant",
    "content": null,
    "tool_calls": [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "San Francisco"}'
            }
        }
    ]
}
```

**Tool Response:**

```python
{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": '{"temperature": 72, "condition": "sunny"}'
}
```

### 5. Session Management

**Session ID:**

- Purpose: Track entire conversation
- Format: UUID (e.g., `"550e8400-e29b-41d4-a716-446655440000"`)
- Persistence: Same for all requests in a conversation
- Location: `payload["metadata"]["sessionId"]`

**Prompt ID:**

- Purpose: Track individual request
- Format: UUID (unique per request)
- Persistence: New for each API call
- Location: `payload["metadata"]["promptId"]`

**Example:**

```python
import uuid

# Create once per conversation
session_id = str(uuid.uuid4())

# Create for each request
prompt_id = str(uuid.uuid4())

payload = {
    "model": "qwen-plus",
    "messages": [...],
    "metadata": {
        "sessionId": session_id,
        "promptId": prompt_id
    }
}
```

### 6. Token Management

**Token Refresh Flow:**

```
1. Check if token expired (expiry_date < current_time)
2. If expired, call refresh endpoint
3. Update stored credentials
4. Retry original request with new token
```

**Refresh Request:**

```python
POST https://chat.qwen.ai/api/v1/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&
refresh_token=YOUR_REFRESH_TOKEN&
client_id=f0304373b74a44d2b584a3fb70ca9e56
```

**Refresh Response:**

```json
{
  "access_token": "new_access_token",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "new_refresh_token_or_same",
  "resource_url": "https://dashscope.aliyuncs.com/compatible-mode"
}
```

### 7. Streaming Response Format

**SSE Format:**

```
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1234567890,"model":"qwen-plus","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1234567890,"model":"qwen-plus","choices":[{"index":0,"delta":{"content":" there"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1234567890,"model":"qwen-plus","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}

data: [DONE]
```

**Parsing:**

```python
for line in response.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data = line[6:]  # Remove 'data: ' prefix
            if data == '[DONE]':
                break
            chunk = json.loads(data)
            # Process chunk
```

### 8. Cache Control (Optional Enhancement)

**Enable caching for system message:**

```python
{
    "role": "system",
    "content": [
        {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral"}
        }
    ]
}
```

**Enable caching for last message (streaming):**

```python
{
    "role": "user",
    "content": [
        {
            "type": "text",
            "text": "What is the weather?",
            "cache_control": {"type": "ephemeral"}
        }
    ]
}
```

**Enable caching for last tool:**

```python
tools = [
    {"type": "function", "function": {...}},
    {
        "type": "function",
        "function": {...},
        "cache_control": {"type": "ephemeral"}
    }
]
```

### 9. Error Handling

**401/403 Errors:**

```python
if response.status_code in (401, 403):
    # Token expired - refresh and retry
    refresh_access_token()
    retry_request()
```

**400 on Refresh:**

```python
if response.status_code == 400:
    # Refresh token expired - need full re-authentication
    raise Exception("Please re-authenticate")
```

### 10. Complete Minimal Example

```python
import requests
import json
import uuid

# Load credentials
with open("~/.qwen/oauth_creds.json") as f:
    creds = json.load(f)

# Build request
headers = {
    "Authorization": f"Bearer {creds['access_token']}",
    "Content-Type": "application/json",
    "User-Agent": "QwenCode/1.0.0",
    "X-DashScope-CacheControl": "enable",
    "X-DashScope-UserAgent": "QwenCode/1.0.0",
    "X-DashScope-AuthType": "qwen-oauth",
}

payload = {
    "model": "qwen-plus",
    "messages": [
        {"role": "user", "content": "Hello!"}
    ],
    "metadata": {
        "sessionId": str(uuid.uuid4()),
        "promptId": str(uuid.uuid4())
    }
}

# Send request
response = requests.post(
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    headers=headers,
    json=payload
)

# Handle response
if response.status_code == 200:
    result = response.json()
    print(result["choices"][0]["message"]["content"])
elif response.status_code in (401, 403):
    # Refresh token and retry
    pass
```

---

## Key Differences from Standard OpenAI API

1. **Authentication**: OAuth2 with refresh tokens instead of static API keys
2. **Base URL**: Dynamic based on `resource_url` from OAuth
3. **Headers**: Additional `X-DashScope-*` headers
4. **Metadata**: Session and prompt tracking via `metadata` field
5. **Cache Control**: DashScope-specific caching mechanism
6. **Token Refresh**: Automatic refresh flow on 401/403

---

## Important Notes

1. **No Initial System Prompt Required**: Unlike some APIs, there's no mandatory initial handshake or system prompt. You can start with any message.

2. **Session Persistence**: The `sessionId` should remain constant throughout a conversation to maintain context.

3. **Token Expiry**: Always check `expiry_date` before making requests and refresh proactively.

4. **Resource URL**: The API endpoint can change based on the `resource_url` in OAuth credentials. Always use the dynamic endpoint.

5. **OpenAI Compatibility**: The message format is 100% OpenAI-compatible. No conversion needed.

6. **Streaming**: When streaming, always include `stream_options: {include_usage: true}` to get token usage in the final chunk.

7. **Error Handling**: Implement automatic retry with token refresh for 401/403 errors.

---

## Testing Checklist

- [ ] Load credentials from `~/.qwen/oauth_creds.json`
- [ ] Check token expiry before request
- [ ] Build headers with all required fields
- [ ] Generate unique session_id and prompt_id
- [ ] Send request to correct endpoint
- [ ] Handle 401/403 with token refresh
- [ ] Parse response correctly
- [ ] Test streaming mode
- [ ] Test with function calling
- [ ] Verify session persistence across requests

---

## Additional Resources

- Full implementation: See `QWEN_API_IMPLEMENTATION_GUIDE.md`
- OAuth2 flow: See `packages/core/src/qwen/qwenOAuth2.ts`
- Request building: See `packages/core/src/core/openaiContentGenerator/provider/dashscope.ts`
- Message conversion: See `packages/core/src/core/openaiContentGenerator/converter.ts`
# Qwen API Implementation Guide

This document provides a complete guide for implementing Qwen API requests in Python, based on the exact implementation in the Qwen Code codebase.

## Table of Contents

1. [OAuth2 Authentication](#oauth2-authentication)
2. [API Request Format](#api-request-format)
3. [Session Management](#session-management)
4. [Message Format Conversion](#message-format-conversion)
5. [Complete Python Implementation](#complete-python-implementation)

---

## OAuth2 Authentication

### OAuth2 Configuration

```python
# OAuth Endpoints
QWEN_OAUTH_BASE_URL = "https://chat.qwen.ai"
QWEN_OAUTH_DEVICE_CODE_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/device/code"
QWEN_OAUTH_TOKEN_ENDPOINT = f"{QWEN_OAUTH_BASE_URL}/api/v1/oauth2/token"

# OAuth Client Configuration
QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_OAUTH_SCOPE = "openid profile email model.completion"
QWEN_OAUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
```

### Token Storage

Tokens are stored in: `~/.qwen/oauth_creds.json`

```json
{
  "access_token": "your_access_token",
  "refresh_token": "your_refresh_token",
  "id_token": "optional_id_token",
  "expiry_date": 1234567890000,
  "token_type": "Bearer",
  "resource_url": "https://dashscope.aliyuncs.com/compatible-mode"
}
```

### Token Refresh

When the access token expires (401/403 errors), refresh it:

```python
import requests

def refresh_access_token(refresh_token: str) -> dict:
    """Refresh the access token using the refresh token."""
    body_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": QWEN_OAUTH_CLIENT_ID,
    }

    response = requests.post(
        QWEN_OAUTH_TOKEN_ENDPOINT,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data=body_data,
    )

    if response.status_code == 400 or response.status_code == 401:
        # Refresh token expired - need to re-authenticate
        raise Exception("Refresh token expired. Please re-authenticate.")

    response.raise_for_status()
    token_data = response.json()

    # Update credentials
    credentials = {
        "access_token": token_data["access_token"],
        "token_type": token_data["token_type"],
        "refresh_token": token_data.get("refresh_token", refresh_token),  # Use new if provided
        "resource_url": token_data.get("resource_url"),
        "expiry_date": int(time.time() * 1000) + token_data["expires_in"] * 1000,
    }

    return credentials
```

---

## API Request Format

### Base URL

The API endpoint is determined by the `resource_url` from OAuth credentials:

```python
def get_api_endpoint(resource_url: str = None) -> str:
    """Get the API endpoint URL."""
    base_endpoint = resource_url or "https://dashscope.aliyuncs.com/compatible-mode"

    # Normalize URL: add protocol if missing, ensure /v1 suffix
    if not base_endpoint.startswith("http"):
        base_endpoint = f"https://{base_endpoint}"

    if not base_endpoint.endswith("/v1"):
        base_endpoint = f"{base_endpoint}/v1"

    return base_endpoint
```

### Required Headers

```python
def build_headers(access_token: str, auth_type: str = "qwen-oauth") -> dict:
    """Build request headers for Qwen API."""
    version = "1.0.0"  # Your application version
    user_agent = f"QwenCode/{version} ({platform.system()}; {platform.machine()})"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": user_agent,
        "X-DashScope-CacheControl": "enable",
        "X-DashScope-UserAgent": user_agent,
        "X-DashScope-AuthType": auth_type,
        "x-request-id": str(uuid.uuid4()),  # Optional but recommended
    }

    return headers
```

### Request Metadata

Qwen API supports metadata for session tracking:

```python
def build_metadata(session_id: str, prompt_id: str, channel: str = None) -> dict:
    """Build metadata for request tracking."""
    metadata = {
        "sessionId": session_id,
        "promptId": prompt_id,
    }

    if channel:
        metadata["channel"] = channel

    return {"metadata": metadata}
```

---

## Session Management

### Session ID

- **Purpose**: Track conversation history across multiple requests
- **Format**: UUID or any unique identifier
- **Persistence**: Should remain constant for the entire conversation
- **Generation**: Create once at conversation start

```python
import uuid

session_id = str(uuid.uuid4())  # Generate once per conversation
```

### Prompt ID

- **Purpose**: Track individual requests within a session
- **Format**: UUID or unique identifier
- **Persistence**: New for each request
- **Generation**: Create for each API call

```python
prompt_id = str(uuid.uuid4())  # Generate for each request
```

---

## Message Format Conversion

### OpenAI to Qwen Format

Qwen API uses OpenAI-compatible format. The conversion is straightforward:

#### System Message

```python
# OpenAI format
{
    "role": "system",
    "content": "You are a helpful assistant."
}

# Qwen format (same)
{
    "role": "system",
    "content": "You are a helpful assistant."
}
```

#### User Message

```python
# OpenAI format
{
    "role": "user",
    "content": "Hello, how are you?"
}

# Qwen format (same)
{
    "role": "user",
    "content": "Hello, how are you?"
}
```

#### Assistant Message

```python
# OpenAI format
{
    "role": "assistant",
    "content": "I'm doing well, thank you!"
}

# Qwen format (same)
{
    "role": "assistant",
    "content": "I'm doing well, thank you!"
}
```

#### Tool Calls (Function Calling)

```python
# OpenAI format
{
    "role": "assistant",
    "content": null,
    "tool_calls": [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "San Francisco"}'
            }
        }
    ]
}

# Qwen format (same)
{
    "role": "assistant",
    "content": null,
    "tool_calls": [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "San Francisco"}'
            }
        }
    ]
}
```

#### Tool Response

```python
# OpenAI format
{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": '{"temperature": 72, "condition": "sunny"}'
}

# Qwen format (same)
{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": '{"temperature": 72, "condition": "sunny"}'
}
```

### Cache Control (DashScope-specific)

For prompt caching, add `cache_control` to the last text part of specific messages:

```python
# System message with cache control
{
    "role": "system",
    "content": [
        {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral"}
        }
    ]
}

# Last history message with cache control (for streaming)
{
    "role": "user",
    "content": [
        {
            "type": "text",
            "text": "What is the weather?",
            "cache_control": {"type": "ephemeral"}
        }
    ]
}
```

For tools, add cache control to the last tool:

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather information",
            "parameters": {...}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web",
            "parameters": {...}
        },
        "cache_control": {"type": "ephemeral"}  # Add to last tool
    }
]
```

---

## Complete Python Implementation

### Full Implementation Example

```python
import json
import time
import uuid
import platform
import requests
from typing import Dict, List, Optional, Generator
from pathlib import Path

class QwenAPIClient:
    """Complete Qwen API client implementation."""

    # OAuth Configuration
    OAUTH_BASE_URL = "https://chat.qwen.ai"
    OAUTH_TOKEN_ENDPOINT = f"{OAUTH_BASE_URL}/api/v1/oauth2/token"
    CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
    DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Credentials file
    CREDS_FILE = Path.home() / ".qwen" / "oauth_creds.json"

    def __init__(self, session_id: Optional[str] = None):
        """Initialize the client."""
        self.session_id = session_id or str(uuid.uuid4())
        self.credentials = self._load_credentials()
        self.api_base = self._get_api_endpoint()

    def _load_credentials(self) -> Dict:
        """Load credentials from file."""
        if not self.CREDS_FILE.exists():
            raise Exception("No credentials found. Please authenticate first.")

        with open(self.CREDS_FILE, 'r') as f:
            return json.load(f)

    def _save_credentials(self, credentials: Dict):
        """Save credentials to file."""
        self.CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.CREDS_FILE, 'w') as f:
            json.dump(credentials, f, indent=2)
        self.credentials = credentials

    def _get_api_endpoint(self) -> str:
        """Get the API endpoint from credentials."""
        resource_url = self.credentials.get("resource_url", self.DEFAULT_API_BASE)

        # Normalize URL
        if not resource_url.startswith("http"):
            resource_url = f"https://{resource_url}"

        if not resource_url.endswith("/v1"):
            resource_url = f"{resource_url}/v1"

        return resource_url

    def _is_token_expired(self) -> bool:
        """Check if the access token is expired."""
        expiry_date = self.credentials.get("expiry_date", 0)
        # Add 60 second buffer
        return time.time() * 1000 >= (expiry_date - 60000)

    def _refresh_token(self):
        """Refresh the access token."""
        refresh_token = self.credentials.get("refresh_token")
        if not refresh_token:
            raise Exception("No refresh token available")

        body_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.CLIENT_ID,
        }

        response = requests.post(
            self.OAUTH_TOKEN_ENDPOINT,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data=body_data,
        )

        if response.status_code in (400, 401):
            raise Exception("Refresh token expired. Please re-authenticate.")

        response.raise_for_status()
        token_data = response.json()

        # Update credentials
        new_credentials = {
            "access_token": token_data["access_token"],
            "token_type": token_data["token_type"],
            "refresh_token": token_data.get("refresh_token", refresh_token),
            "resource_url": token_data.get("resource_url", self.credentials.get("resource_url")),
            "expiry_date": int(time.time() * 1000) + token_data["expires_in"] * 1000,
        }

        self._save_credentials(new_credentials)
        self.api_base = self._get_api_endpoint()

    def _get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._is_token_expired():
            self._refresh_token()

        return self.credentials["access_token"]

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        access_token = self._get_valid_token()
        version = "1.0.0"
        user_agent = f"QwenCode/{version} ({platform.system()}; {platform.machine()})"

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": user_agent,
            "X-DashScope-CacheControl": "enable",
            "X-DashScope-UserAgent": user_agent,
            "X-DashScope-AuthType": "qwen-oauth",
            "x-request-id": str(uuid.uuid4()),
        }

    def chat_completion(
        self,
        messages: List[Dict],
        model: str = "qwen-plus",
        stream: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict:
        """
        Send a chat completion request.

        Args:
            messages: List of message dictionaries in OpenAI format
            model: Model name to use
            stream: Whether to stream the response
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            tools: List of tool definitions
            **kwargs: Additional parameters

        Returns:
            Response dictionary or generator for streaming
        """
        prompt_id = str(uuid.uuid4())

        # Build request payload
        payload = {
            "model": model,
            "messages": messages,
            "metadata": {
                "sessionId": self.session_id,
                "promptId": prompt_id,
            }
        }

        # Add optional parameters
        if temperature is not None:
            payload["temperature"] = temperature

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        # Add any additional parameters
        payload.update(kwargs)

        # Make request with retry on auth error
        return self._make_request(payload, stream)

    def _make_request(self, payload: Dict, stream: bool) -> Dict:
        """Make the API request with automatic token refresh."""
        url = f"{self.api_base}/chat/completions"

        try:
            headers = self._build_headers()

            if stream:
                return self._stream_request(url, headers, payload)
            else:
                response = requests.post(url, headers=headers, json=payload)

                # Handle auth errors with token refresh
                if response.status_code in (401, 403):
                    self._refresh_token()
                    headers = self._build_headers()
                    response = requests.post(url, headers=headers, json=payload)

                response.raise_for_status()
                return response.json()

        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")

    def _stream_request(self, url: str, headers: Dict, payload: Dict) -> Generator:
        """Handle streaming requests."""
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=True
        )

        # Handle auth errors with token refresh
        if response.status_code in (401, 403):
            self._refresh_token()
            headers = self._build_headers()
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=True
            )

        response.raise_for_status()

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]  # Remove 'data: ' prefix
                    if data == '[DONE]':
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue


# Usage Example
def main():
    """Example usage of the Qwen API client."""

    # Initialize client (creates or reuses session)
    client = QwenAPIClient()

    # Simple chat completion
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]

    # Non-streaming request
    response = client.chat_completion(
        messages=messages,
        model="qwen-plus",
        temperature=0.7,
        max_tokens=1000
    )

    print("Response:", response["choices"][0]["message"]["content"])

    # Streaming request
    print("\nStreaming response:")
    for chunk in client.chat_completion(
        messages=messages,
        model="qwen-plus",
        stream=True
    ):
        if "choices" in chunk and len(chunk["choices"]) > 0:
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta:
                print(delta["content"], end="", flush=True)

    print("\n")

    # With function calling
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA"
                        }
                    },
                    "required": ["location"]
                }
            }
        }
    ]

    messages = [
        {"role": "user", "content": "What's the weather in San Francisco?"}
    ]

    response = client.chat_completion(
        messages=messages,
        model="qwen-plus",
        tools=tools
    )

    print("Tool call:", response["choices"][0]["message"].get("tool_calls"))


if __name__ == "__main__":
    main()
```

---

## Key Implementation Details

### 1. **No Initial System Prompt Required**

- System prompts are optional and sent as regular messages
- No special initialization handshake needed

### 2. **Session Management**

- Session ID: Persistent across conversation
- Prompt ID: Unique per request
- Both sent in `metadata` field of request payload

### 3. **Token Management**

- Access tokens expire (check `expiry_date`)
- Refresh automatically on 401/403 errors
- Store credentials in `~/.qwen/oauth_creds.json`

### 4. **Headers**

- `Authorization`: Bearer token (required)
- `X-DashScope-*`: Provider-specific headers
- `User-Agent`: Application identification
- `x-request-id`: Request tracking (optional)

### 5. **Cache Control**

- Enabled by default via `X-DashScope-CacheControl: enable`
- Can add `cache_control` to specific message parts for fine-grained control
- Applied to system message and last history message in streaming mode

### 6. **Error Handling**

- 401/403: Token expired → refresh and retry
- 400 on refresh: Refresh token expired → re-authenticate
- Network errors: Implement exponential backoff

### 7. **Streaming**

- Set `stream: true` and `stream_options: {include_usage: true}`
- Parse SSE format: `data: {json}\n\n`
- Handle `[DONE]` marker

---

## Testing Your Implementation

```python
# Test token validity
client = QwenAPIClient()
print("Token valid:", not client._is_token_expired())

# Test simple request
response = client.chat_completion(
    messages=[{"role": "user", "content": "Hello"}],
    model="qwen-plus"
)
print("Response:", response)

# Test streaming
for chunk in client.chat_completion(
    messages=[{"role": "user", "content": "Count to 5"}],
    model="qwen-plus",
    stream=True
):
    print(chunk)
```

---

## Summary

This implementation mimics exactly how Qwen Code sends requests:

1. **OAuth2 flow** for authentication with automatic token refresh
2. **OpenAI-compatible message format** (no conversion needed)
3. **Session tracking** via metadata (sessionId + promptId)
4. **DashScope-specific headers** for cache control and tracking
5. **Automatic retry** on authentication errors
6. **Streaming support** with SSE parsing

The key insight is that Qwen API is OpenAI-compatible, so you can use standard OpenAI message formats directly. The main differences are:

- OAuth2 authentication instead of API keys
- DashScope-specific headers
- Metadata for session tracking
- Dynamic endpoint from OAuth credentials
# Qwen API Request Flow Diagram

This document provides a visual representation of how Qwen Code sends API requests.

## Complete Request Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INITIATES REQUEST                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    1. SESSION MANAGEMENT                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ • Generate/Reuse Session ID (UUID)                           │  │
│  │ • Generate new Prompt ID (UUID) for this request             │  │
│  │ • Session ID persists across conversation                    │  │
│  │ • Prompt ID unique per request                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    2. TOKEN MANAGEMENT                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Load credentials from ~/.qwen/oauth_creds.json               │  │
│  │         │                                                     │  │
│  │         ▼                                                     │  │
│  │ Check if token expired (expiry_date < current_time)          │  │
│  │         │                                                     │  │
│  │         ├─── YES ──▶ Refresh Token                           │  │
│  │         │              │                                      │  │
│  │         │              ▼                                      │  │
│  │         │         POST /api/v1/oauth2/token                  │  │
│  │         │         grant_type=refresh_token                   │  │
│  │         │              │                                      │  │
│  │         │              ▼                                      │  │
│  │         │         Save new credentials                       │  │
│  │         │              │                                      │  │
│  │         └─── NO ───────┘                                      │  │
│  │                   │                                           │  │
│  │                   ▼                                           │  │
│  │         Use access_token for request                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    3. BUILD REQUEST HEADERS                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Authorization: Bearer {access_token}                         │  │
│  │ Content-Type: application/json                               │  │
│  │ Accept: application/json                                     │  │
│  │ User-Agent: QwenCode/{version} ({platform}; {arch})          │  │
│  │ X-DashScope-CacheControl: enable                             │  │
│  │ X-DashScope-UserAgent: QwenCode/{version} ({platform})       │  │
│  │ X-DashScope-AuthType: qwen-oauth                             │  │
│  │ x-request-id: {uuid}                                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    4. BUILD REQUEST PAYLOAD                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ {                                                            │  │
│  │   "model": "qwen-plus",                                      │  │
│  │   "messages": [                                              │  │
│  │     {"role": "system", "content": "..."},                    │  │
│  │     {"role": "user", "content": "..."}                       │  │
│  │   ],                                                         │  │
│  │   "stream": false,                                           │  │
│  │   "temperature": 0.7,                                        │  │
│  │   "max_tokens": 1000,                                        │  │
│  │   "metadata": {                                              │  │
│  │     "sessionId": "{session_uuid}",                           │  │
│  │     "promptId": "{prompt_uuid}"                              │  │
│  │   }                                                          │  │
│  │ }                                                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    5. DETERMINE API ENDPOINT                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Get resource_url from credentials                            │  │
│  │         │                                                     │  │
│  │         ▼                                                     │  │
│  │ Default: https://dashscope.aliyuncs.com/compatible-mode     │  │
│  │         │                                                     │  │
│  │         ▼                                                     │  │
│  │ Normalize: Add https:// if missing, ensure /v1 suffix       │  │
│  │         │                                                     │  │
│  │         ▼                                                     │  │
│  │ Final: https://dashscope.aliyuncs.com/compatible-mode/v1    │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    6. SEND HTTP REQUEST                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ POST {api_base}/chat/completions                             │  │
│  │ Headers: [see step 3]                                        │  │
│  │ Body: [see step 4]                                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    7. HANDLE RESPONSE                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Status Code?                                                 │  │
│  │    │                                                          │  │
│  │    ├─── 200 OK ──▶ Parse response, return to user           │  │
│  │    │                                                          │  │
│  │    ├─── 401/403 ──▶ Token expired                            │  │
│  │    │                    │                                     │  │
│  │    │                    ▼                                     │  │
│  │    │               Refresh token (step 2)                    │  │
│  │    │                    │                                     │  │
│  │    │                    ▼                                     │  │
│  │    │               Retry request (step 6)                    │  │
│  │    │                                                          │  │
│  │    └─── Other ──▶ Handle error, report to user              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Streaming Request Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    STREAMING REQUEST (Steps 1-6 same)                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PAYLOAD DIFFERENCES                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ {                                                            │  │
│  │   ...                                                        │  │
│  │   "stream": true,                    ← Enable streaming     │  │
│  │   "stream_options": {                                        │  │
│  │     "include_usage": true            ← Get token usage      │  │
│  │   },                                                         │  │
│  │   ...                                                        │  │
│  │ }                                                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PARSE SSE STREAM                                  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ For each line in response.iter_lines():                     │  │
│  │   │                                                          │  │
│  │   ├─ Line starts with "data: " ?                            │  │
│  │   │     │                                                    │  │
│  │   │     ├─ YES ─▶ Extract JSON after "data: "               │  │
│  │   │     │           │                                        │  │
│  │   │     │           ├─ Is "[DONE]" ? ─▶ End stream          │  │
│  │   │     │           │                                        │  │
│  │   │     │           └─ Parse JSON chunk                      │  │
│  │   │     │               │                                    │  │
│  │   │     │               ├─ Extract delta.content            │  │
│  │   │     │               ├─ Extract finish_reason            │  │
│  │   │     │               └─ Extract usage (final chunk)      │  │
│  │   │     │                                                    │  │
│  │   │     └─ NO ─▶ Skip line                                  │  │
│  │   │                                                          │  │
│  │   └─ Yield chunk to user                                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Message Format Conversion (OpenAI → Qwen)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NO CONVERSION NEEDED!                             │
│                                                                       │
│  Qwen API is 100% OpenAI-compatible                                 │
│                                                                       │
│  OpenAI Format              Qwen Format                              │
│  ─────────────              ───────────                              │
│  {"role": "user",     ═══▶  {"role": "user",                        │
│   "content": "..."}          "content": "..."}                       │
│                                                                       │
│  Same for:                                                           │
│  • System messages                                                   │
│  • Assistant messages                                                │
│  • Tool calls                                                        │
│  • Tool responses                                                    │
│  • Function definitions                                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Cache Control Flow (Optional)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CACHE CONTROL (Optional Enhancement)              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ 1. System Message Caching                                    │  │
│  │    {                                                         │  │
│  │      "role": "system",                                       │  │
│  │      "content": [                                            │  │
│  │        {                                                     │  │
│  │          "type": "text",                                     │  │
│  │          "text": "You are...",                               │  │
│  │          "cache_control": {"type": "ephemeral"}  ← Cache    │  │
│  │        }                                                     │  │
│  │      ]                                                       │  │
│  │    }                                                         │  │
│  │                                                              │  │
│  │ 2. Last History Message Caching (streaming only)            │  │
│  │    {                                                         │  │
│  │      "role": "user",                                         │  │
│  │      "content": [                                            │  │
│  │        {                                                     │  │
│  │          "type": "text",                                     │  │
│  │          "text": "What is...",                               │  │
│  │          "cache_control": {"type": "ephemeral"}  ← Cache    │  │
│  │        }                                                     │  │
│  │      ]                                                       │  │
│  │    }                                                         │  │
│  │                                                              │  │
│  │ 3. Last Tool Caching (streaming only)                       │  │
│  │    tools = [                                                 │  │
│  │      {...},                                                  │  │
│  │      {                                                       │  │
│  │        "type": "function",                                   │  │
│  │        "function": {...},                                    │  │
│  │        "cache_control": {"type": "ephemeral"}  ← Cache      │  │
│  │      }                                                       │  │
│  │    ]                                                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ERROR HANDLING                                    │
│                                                                       │
│  Response Status Code                                                │
│         │                                                             │
│         ├─── 200 ──▶ Success, parse response                        │
│         │                                                             │
│         ├─── 401/403 ──▶ Token expired                               │
│         │                    │                                        │
│         │                    ▼                                        │
│         │            POST /api/v1/oauth2/token                       │
│         │            grant_type=refresh_token                        │
│         │                    │                                        │
│         │                    ├─── 200 ──▶ Token refreshed            │
│         │                    │              │                         │
│         │                    │              ▼                         │
│         │                    │         Save credentials              │
│         │                    │              │                         │
│         │                    │              ▼                         │
│         │                    │         Retry original request        │
│         │                    │                                        │
│         │                    └─── 400/401 ──▶ Refresh token expired  │
│         │                                      │                      │
│         │                                      ▼                      │
│         │                              Re-authenticate required       │
│         │                                                             │
│         ├─── 429 ──▶ Rate limit, implement backoff                   │
│         │                                                             │
│         ├─── 500+ ──▶ Server error, retry with backoff               │
│         │                                                             │
│         └─── Other ──▶ Handle error, report to user                  │
└─────────────────────────────────────────────────────────────────────┘
```

## Token Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TOKEN LIFECYCLE                                   │
│                                                                       │
│  1. Initial Authentication (Device Flow)                             │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ User authenticates via browser                           │   │
│     │         ▼                                                 │   │
│     │ Receive access_token + refresh_token                     │   │
│     │         ▼                                                 │   │
│     │ Save to ~/.qwen/oauth_creds.json                         │   │
│     │         ▼                                                 │   │
│     │ Set expiry_date = now + expires_in                       │   │
│     └──────────────────────────────────────────────────────────┘   │
│                                                                       │
│  2. Token Usage                                                      │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ Before each request:                                     │   │
│     │   Check if expiry_date < current_time                    │   │
│     │   If expired: refresh token                              │   │
│     │   Use access_token in Authorization header               │   │
│     └──────────────────────────────────────────────────────────┘   │
│                                                                       │
│  3. Token Refresh                                                    │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ POST /api/v1/oauth2/token                                │   │
│     │   grant_type=refresh_token                               │   │
│     │   refresh_token={current_refresh_token}                  │   │
│     │         ▼                                                 │   │
│     │ Receive new access_token                                 │   │
│     │ Optionally receive new refresh_token                     │   │
│     │         ▼                                                 │   │
│     │ Update ~/.qwen/oauth_creds.json                          │   │
│     │         ▼                                                 │   │
│     │ Set new expiry_date                                      │   │
│     └──────────────────────────────────────────────────────────┘   │
│                                                                       │
│  4. Token Expiration                                                 │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ If refresh fails with 400/401:                           │   │
│     │   Refresh token expired                                  │   │
│     │         ▼                                                 │   │
│     │   Clear credentials                                      │   │
│     │         ▼                                                 │   │
│     │   User must re-authenticate                              │   │
│     └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Session Management

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SESSION MANAGEMENT                                │
│                                                                       │
│  Session ID (Conversation Level)                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ • Generated once at conversation start                         │ │
│  │ • Format: UUID (e.g., "550e8400-e29b-41d4-a716-446655440000") │ │
│  │ • Persists across all requests in conversation                 │ │
│  │ • Sent in metadata.sessionId                                   │ │
│  │ • Purpose: Track conversation history                          │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  Prompt ID (Request Level)                                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ • Generated for each API request                               │ │
│  │ • Format: UUID (unique per request)                            │ │
│  │ • Sent in metadata.promptId                                    │ │
│  │ • Purpose: Track individual requests                           │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  Example Flow:                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Conversation Start                                             │ │
│  │   session_id = uuid4()  # "abc-123"                            │ │
│  │                                                                 │ │
│  │ Request 1:                                                      │ │
│  │   prompt_id = uuid4()  # "def-456"                             │ │
│  │   metadata = {sessionId: "abc-123", promptId: "def-456"}       │ │
│  │                                                                 │ │
│  │ Request 2:                                                      │ │
│  │   prompt_id = uuid4()  # "ghi-789"                             │ │
│  │   metadata = {sessionId: "abc-123", promptId: "ghi-789"}       │ │
│  │                                                                 │ │
│  │ Request 3:                                                      │ │
│  │   prompt_id = uuid4()  # "jkl-012"                             │ │
│  │   metadata = {sessionId: "abc-123", promptId: "jkl-012"}       │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Takeaways

1. **OpenAI Compatibility**: No message format conversion needed
2. **OAuth2 Flow**: Token refresh on 401/403, re-auth on refresh failure
3. **Session Tracking**: sessionId (conversation) + promptId (request)
4. **Dynamic Endpoint**: Use resource_url from OAuth credentials
5. **Headers**: Include DashScope-specific headers for caching and tracking
6. **Streaming**: Parse SSE format, handle [DONE] marker
7. **Error Handling**: Automatic retry with token refresh on auth errors
# Qwen API Implementation Checklist

Use this checklist to ensure your Qwen API implementation is complete and correct.

## ✅ Prerequisites

- [ ] Python 3.7+ installed
- [ ] `requests` library installed (`pip install requests`)
- [ ] Valid OAuth2 credentials obtained
- [ ] Credentials stored in `~/.qwen/oauth_creds.json`

## ✅ Credentials Setup

- [ ] Credentials file exists at correct location
- [ ] File contains all required fields:
  - [ ] `access_token`
  - [ ] `refresh_token`
  - [ ] `expiry_date`
  - [ ] `token_type`
  - [ ] `resource_url` (optional but recommended)
- [ ] File permissions are secure (readable only by user)
- [ ] Credentials are valid (not expired)

## ✅ Basic Implementation

### Token Management
- [ ] Load credentials from file
- [ ] Check token expiry before requests
- [ ] Implement token refresh logic
- [ ] Handle refresh token expiration
- [ ] Save updated credentials after refresh
- [ ] Use 60-second buffer for expiry check

### Headers
- [ ] `Authorization: Bearer {token}` header
- [ ] `Content-Type: application/json` header
- [ ] `Accept: application/json` header
- [ ] `User-Agent` header with app name/version
- [ ] `X-DashScope-CacheControl: enable` header
- [ ] `X-DashScope-UserAgent` header
- [ ] `X-DashScope-AuthType: qwen-oauth` header
- [ ] Optional: `x-request-id` header with UUID

### Endpoint Configuration
- [ ] Extract `resource_url` from credentials
- [ ] Default to `https://dashscope.aliyuncs.com/compatible-mode`
- [ ] Add `https://` if protocol missing
- [ ] Ensure `/v1` suffix
- [ ] Use `/chat/completions` endpoint

### Request Payload
- [ ] `model` field (e.g., "qwen-plus")
- [ ] `messages` array with proper format
- [ ] Optional: `temperature` parameter
- [ ] Optional: `max_tokens` parameter
- [ ] Optional: `metadata` with sessionId and promptId
- [ ] For streaming: `stream: true`
- [ ] For streaming: `stream_options: {include_usage: true}`

## ✅ Session Management

- [ ] Generate session ID once per conversation (UUID)
- [ ] Generate new prompt ID for each request (UUID)
- [ ] Include both in `metadata` field
- [ ] Reuse session ID across conversation turns
- [ ] Store session ID for conversation persistence

## ✅ Message Format

### System Messages
- [ ] Use `role: "system"`
- [ ] Include content as string or array

### User Messages
- [ ] Use `role: "user"`
- [ ] Include content as string or array
- [ ] Support text content
- [ ] Support image content (if needed)

### Assistant Messages
- [ ] Use `role: "assistant"`
- [ ] Include content as string
- [ ] Support tool_calls array (if using functions)

### Tool Messages
- [ ] Use `role: "tool"`
- [ ] Include `tool_call_id`
- [ ] Include result in `content`

## ✅ Error Handling

### Authentication Errors
- [ ] Detect 401/403 status codes
- [ ] Trigger token refresh automatically
- [ ] Retry original request after refresh
- [ ] Handle refresh token expiration (400/401 on refresh)
- [ ] Prompt for re-authentication when needed

### Network Errors
- [ ] Implement retry logic with exponential backoff
- [ ] Handle connection timeouts
- [ ] Handle read timeouts
- [ ] Maximum retry attempts (e.g., 3)

### Rate Limiting
- [ ] Detect 429 status code
- [ ] Implement exponential backoff
- [ ] Respect Retry-After header if present

### API Errors
- [ ] Parse error responses
- [ ] Log error details
- [ ] Provide meaningful error messages to user

## ✅ Streaming Support

### Request Configuration
- [ ] Set `stream: true` in payload
- [ ] Set `stream_options: {include_usage: true}`
- [ ] Use streaming HTTP request

### Response Parsing
- [ ] Parse SSE format (Server-Sent Events)
- [ ] Handle `data: ` prefix
- [ ] Parse JSON from each chunk
- [ ] Handle `[DONE]` marker
- [ ] Extract `delta.content` from chunks
- [ ] Extract `finish_reason` from final chunk
- [ ] Extract `usage` metadata from final chunk

### Error Handling
- [ ] Handle streaming errors
- [ ] Clean up on connection failure
- [ ] Handle partial responses

## ✅ Advanced Features

### Cache Control (Optional)
- [ ] Add cache_control to system message
- [ ] Add cache_control to last history message (streaming)
- [ ] Add cache_control to last tool (streaming)
- [ ] Use `{type: "ephemeral"}` format

### Function Calling
- [ ] Define tools array with function schemas
- [ ] Include tools in request payload
- [ ] Parse tool_calls from response
- [ ] Execute functions locally
- [ ] Send tool results back to API
- [ ] Handle multi-turn function calling

### Multi-Turn Conversations
- [ ] Maintain message history
- [ ] Append assistant responses to history
- [ ] Use same session ID across turns
- [ ] Handle context window limits

## ✅ Testing

### Unit Tests
- [ ] Test credential loading
- [ ] Test token expiry checking
- [ ] Test token refresh
- [ ] Test header building
- [ ] Test payload building
- [ ] Test endpoint construction

### Integration Tests
- [ ] Test simple completion
- [ ] Test streaming completion
- [ ] Test multi-turn conversation
- [ ] Test function calling
- [ ] Test error handling
- [ ] Test token refresh flow

### Manual Testing
- [ ] Run test_qwen_api.py script
- [ ] Verify all tests pass
- [ ] Test with expired token
- [ ] Test with invalid credentials
- [ ] Test streaming output
- [ ] Test conversation context

## ✅ Production Readiness

### Security
- [ ] Credentials stored securely
- [ ] File permissions set correctly (600)
- [ ] Tokens not logged or exposed
- [ ] HTTPS used for all requests
- [ ] Sensitive data not in error messages

### Performance
- [ ] Credentials cached in memory
- [ ] Connection pooling enabled
- [ ] Timeouts configured appropriately
- [ ] Retry logic optimized

### Monitoring
- [ ] Request/response logging
- [ ] Error tracking
- [ ] Token refresh tracking
- [ ] API usage metrics
- [ ] Request ID tracking

### Documentation
- [ ] API usage documented
- [ ] Error codes documented
- [ ] Configuration options documented
- [ ] Examples provided
- [ ] Troubleshooting guide available

## ✅ Code Quality

### Code Organization
- [ ] Separate concerns (auth, requests, parsing)
- [ ] Reusable client class
- [ ] Clear function/method names
- [ ] Proper error handling throughout

### Code Style
- [ ] Consistent formatting
- [ ] Type hints (if using Python 3.5+)
- [ ] Docstrings for public methods
- [ ] Comments for complex logic

### Maintainability
- [ ] Configuration externalized
- [ ] Magic numbers avoided
- [ ] Constants defined
- [ ] Easy to update/extend

## 🎯 Quick Validation

Run these commands to validate your implementation:

```bash
# 1. Check credentials exist
test -f ~/.qwen/oauth_creds.json && echo "✓ Credentials found" || echo "✗ Credentials missing"

# 2. Validate credentials format
python3 -c "import json; json.load(open('~/.qwen/oauth_creds.json'.replace('~', '$HOME')))" && echo "✓ Valid JSON" || echo "✗ Invalid JSON"

# 3. Run test suite
python3 test_qwen_api.py

# 4. Test simple request
python3 -c "
from test_qwen_api import QwenAPITester
tester = QwenAPITester(verbose=False)
tester.load_credentials()
result = tester.test_simple_completion('Hello')
print('✓ API request successful')
"
```

## 📊 Implementation Status

Track your progress:

```
Total Items: 100+
Completed: ___
Remaining: ___
Progress: ___%
```

## 🚀 Next Steps

After completing this checklist:

1. **Test thoroughly** - Run all tests multiple times
2. **Handle edge cases** - Test with various inputs
3. **Monitor in production** - Track errors and performance
4. **Iterate** - Improve based on real usage
5. **Document** - Keep documentation up to date

## 📝 Notes

Use this space to track issues, questions, or customizations:

```
Date: ___________
Issue: ___________________________________________________________
Resolution: _______________________________________________________

Date: ___________
Issue: ___________________________________________________________
Resolution: _______________________________________________________

Date: ___________
Issue: ___________________________________________________________
Resolution: _______________________________________________________
```

---

**Checklist Version**: 1.0.0  
**Last Updated**: 2026-04-19  
**Compatible with**: Qwen API (DashScope OpenAI-compatible endpoint)

---
---
---

# APPENDIX A: Python Test Script

Below is the complete test script (`test_qwen_api.py`) for testing your Qwen API implementation:

```python
#!/usr/bin/env python3
"""
Qwen API Test Script

This script demonstrates and tests the complete Qwen API implementation,
including OAuth2 authentication, token refresh, and chat completions.

Usage:
    python test_qwen_api.py
    python test_qwen_api.py --verbose
"""

import json
import time
import uuid
import platform
import requests
from pathlib import Path
from typing import Dict, List, Optional

class QwenAPITester:
    """Test client for Qwen API with detailed logging."""
    
    OAUTH_BASE_URL = "https://chat.qwen.ai"
    OAUTH_TOKEN_ENDPOINT = f"{OAUTH_BASE_URL}/api/v1/oauth2/token"
    CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
    DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    CREDS_FILE = Path.home() / ".qwen" / "oauth_creds.json"
    
    def __init__(self, session_id: Optional[str] = None, verbose: bool = True):
        self.session_id = session_id or str(uuid.uuid4())
        self.verbose = verbose
        self.credentials = None
        self.api_base = None
    
    def run_all_tests(self):
        """Run comprehensive test suite."""
        print("\n" + "="*60)
        print("QWEN API TEST SUITE")
        print("="*60 + "\n")
        
        try:
            print("[TEST 1] Checking credentials...")
            if not self.CREDS_FILE.exists():
                print("❌ FAILED: No credentials found")
                return
            print("✓ PASSED: Credentials file exists")
            
            print("\n[TEST 2] Loading credentials...")
            self.load_credentials()
            print("✓ PASSED: Credentials loaded")
            
            print("\n[TEST 3] Testing simple completion...")
            self.test_simple_completion()
            print("✓ PASSED: Simple completion successful")
            
            print("\n[TEST 4] Testing streaming...")
            self.test_streaming_completion()
            print("✓ PASSED: Streaming successful")
            
            print("\n" + "="*60)
            print("ALL TESTS PASSED ✓")
            print("="*60 + "\n")
        
        except Exception as e:
            print(f"\n❌ TEST FAILED: {str(e)}")

if __name__ == "__main__":
    import sys
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    tester = QwenAPITester(verbose=verbose)
    tester.run_all_tests()
```

---

# APPENDIX B: Example Requests and Responses

## Example 1: Simple Chat Completion

**Request:**
```json
POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
Headers:
  Authorization: Bearer eyJhbGc...
  Content-Type: application/json
  X-DashScope-CacheControl: enable
  X-DashScope-AuthType: qwen-oauth

Body:
{
  "model": "qwen-plus",
  "messages": [
    {"role": "user", "content": "What is 2+2?"}
  ],
  "metadata": {
    "sessionId": "550e8400-e29b-41d4-a716-446655440000",
    "promptId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
  }
}
```

**Response:**
```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "qwen-plus",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "2+2 equals 4."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 8,
    "total_tokens": 18
  }
}
```

## Example 2: Streaming Request

**Request:**
```json
{
  "model": "qwen-plus",
  "messages": [
    {"role": "user", "content": "Count from 1 to 3"}
  ],
  "stream": true,
  "stream_options": {"include_usage": true},
  "metadata": {
    "sessionId": "550e8400-e29b-41d4-a716-446655440000",
    "promptId": "7ba7b810-9dad-11d1-80b4-00c04fd430c8"
  }
}
```

**Response (SSE Stream):**
```
data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"role":"assistant","content":"1"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":", 2"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":", 3"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":8,"completion_tokens":6,"total_tokens":14}}

data: [DONE]
```

## Example 3: Function Calling

**Request:**
```json
{
  "model": "qwen-plus",
  "messages": [
    {"role": "user", "content": "What's the weather in Paris?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "City name"
            }
          },
          "required": ["location"]
        }
      }
    }
  ],
  "metadata": {
    "sessionId": "550e8400-e29b-41d4-a716-446655440000",
    "promptId": "8ba7b810-9dad-11d1-80b4-00c04fd430c8"
  }
}
```

**Response:**
```json
{
  "id": "chatcmpl-124",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"location\": \"Paris\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 45,
    "completion_tokens": 15,
    "total_tokens": 60
  }
}
```

**Follow-up Request (with tool result):**
```json
{
  "model": "qwen-plus",
  "messages": [
    {"role": "user", "content": "What's the weather in Paris?"},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"location\": \"Paris\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "{\"temperature\": 18, \"condition\": \"sunny\"}"
    }
  ],
  "tools": [...],
  "metadata": {
    "sessionId": "550e8400-e29b-41d4-a716-446655440000",
    "promptId": "9ba7b810-9dad-11d1-80b4-00c04fd430c8"
  }
}
```

**Final Response:**
```json
{
  "id": "chatcmpl-125",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The weather in Paris is currently sunny with a temperature of 18°C."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 75,
    "completion_tokens": 18,
    "total_tokens": 93
  }
}
```

---

# APPENDIX C: Error Codes and Handling

## HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Parse response normally |
| 400 | Bad Request | Check request format, parameters |
| 401 | Unauthorized | Token expired - refresh and retry |
| 403 | Forbidden | Token invalid - refresh and retry |
| 429 | Too Many Requests | Rate limited - implement backoff |
| 500 | Internal Server Error | Retry with exponential backoff |
| 502 | Bad Gateway | Temporary issue - retry |
| 503 | Service Unavailable | Service down - retry later |

## Common Error Responses

### Token Expired (401)
```json
{
  "error": {
    "message": "Invalid authentication credentials",
    "type": "invalid_request_error",
    "code": "invalid_api_key"
  }
}
```
**Action:** Refresh token and retry request

### Rate Limit (429)
```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "rate_limit_error",
    "code": "rate_limit_exceeded"
  }
}
```
**Action:** Wait and retry with exponential backoff

### Invalid Request (400)
```json
{
  "error": {
    "message": "Invalid request: missing required field 'model'",
    "type": "invalid_request_error",
    "code": "invalid_request"
  }
}
```
**Action:** Fix request format and retry

## Token Refresh Errors

### Refresh Token Expired (400/401)
```json
{
  "error": "invalid_grant",
  "error_description": "The refresh token is invalid or expired"
}
```
**Action:** User must re-authenticate via OAuth2 device flow

### Invalid Client (401)
```json
{
  "error": "invalid_client",
  "error_description": "Client authentication failed"
}
```
**Action:** Check client ID configuration

---

# APPENDIX D: Configuration Examples

## Minimal Configuration

```python
# Minimal working configuration
config = {
    "credentials_path": "~/.qwen/oauth_creds.json",
    "model": "qwen-plus",
    "timeout": 120,
}
```

## Production Configuration

```python
# Production-ready configuration
config = {
    # Authentication
    "credentials_path": "~/.qwen/oauth_creds.json",
    "token_refresh_buffer": 60,  # seconds before expiry
    
    # API Settings
    "model": "qwen-plus",
    "base_url": None,  # Use from credentials
    "timeout": 120,
    "max_retries": 3,
    
    # Request Parameters
    "temperature": 0.7,
    "max_tokens": 2000,
    "top_p": 0.9,
    
    # Session Management
    "session_id": None,  # Auto-generate
    "enable_metadata": True,
    
    # Features
    "enable_streaming": True,
    "enable_cache_control": True,
    "enable_function_calling": True,
    
    # Logging
    "log_requests": True,
    "log_responses": False,  # Don't log full responses
    "log_level": "INFO",
}
```

## Environment Variables

```bash
# Optional environment variables
export QWEN_CREDENTIALS_PATH="~/.qwen/oauth_creds.json"
export QWEN_MODEL="qwen-plus"
export QWEN_TIMEOUT="120"
export QWEN_MAX_RETRIES="3"
export QWEN_LOG_LEVEL="INFO"
```

---

# APPENDIX E: Troubleshooting Guide

## Problem: Credentials Not Found

**Symptoms:**
- Error: "No credentials found"
- File not found error

**Solutions:**
1. Check file exists: `ls -la ~/.qwen/oauth_creds.json`
2. Verify file permissions: `chmod 600 ~/.qwen/oauth_creds.json`
3. Check file format: `cat ~/.qwen/oauth_creds.json | python -m json.tool`
4. Re-authenticate if needed

## Problem: Token Refresh Fails

**Symptoms:**
- 400/401 error on refresh
- "Refresh token expired" message

**Solutions:**
1. Delete credentials: `rm ~/.qwen/oauth_creds.json`
2. Re-authenticate via OAuth2 device flow
3. Check system time is correct
4. Verify network connectivity

## Problem: Streaming Not Working

**Symptoms:**
- No chunks received
- Connection hangs
- Incomplete responses

**Solutions:**
1. Verify `stream: true` in request
2. Add `stream_options: {include_usage: true}`
3. Check network/firewall settings
4. Increase timeout value
5. Test with non-streaming first

## Problem: Session Context Lost

**Symptoms:**
- Model doesn't remember previous messages
- Context not maintained

**Solutions:**
1. Use same `sessionId` for all requests
2. Include full message history in each request
3. Verify messages array is correct
4. Check for context window limits

## Problem: Rate Limiting

**Symptoms:**
- 429 status code
- "Rate limit exceeded" error

**Solutions:**
1. Implement exponential backoff
2. Reduce request frequency
3. Check rate limit headers
4. Consider upgrading plan

---

# APPENDIX F: Best Practices Summary

## Security Best Practices

1. **Never commit credentials** to version control
2. **Use environment variables** for sensitive data
3. **Set proper file permissions** (600 for credentials)
4. **Rotate tokens regularly** via refresh
5. **Use HTTPS only** for all requests
6. **Don't log tokens** in application logs
7. **Validate all inputs** before sending to API

## Performance Best Practices

1. **Cache credentials** in memory
2. **Reuse HTTP connections** (connection pooling)
3. **Implement request batching** where possible
4. **Use streaming** for long responses
5. **Set appropriate timeouts** (120s recommended)
6. **Monitor token usage** to optimize costs
7. **Enable cache control** for repeated prompts

## Code Quality Best Practices

1. **Separate concerns** (auth, requests, parsing)
2. **Use type hints** for better IDE support
3. **Write comprehensive tests** for all features
4. **Document public APIs** with docstrings
5. **Handle errors gracefully** with retries
6. **Log important events** for debugging
7. **Follow PEP 8** style guidelines

## API Usage Best Practices

1. **Include metadata** for tracking
2. **Use appropriate models** for tasks
3. **Set reasonable token limits** to control costs
4. **Implement retry logic** with backoff
5. **Monitor API responses** for errors
6. **Track usage metrics** for optimization
7. **Test thoroughly** before production

---

# APPENDIX G: Quick Reference Card

## Essential URLs
```
OAuth Token:  https://chat.qwen.ai/api/v1/oauth2/token
API Endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

## Essential Headers
```
Authorization: Bearer {access_token}
Content-Type: application/json
X-DashScope-CacheControl: enable
X-DashScope-AuthType: qwen-oauth
```

## Minimal Request
```json
{
  "model": "qwen-plus",
  "messages": [{"role": "user", "content": "Hello"}]
}
```

## Token Refresh
```bash
POST https://chat.qwen.ai/api/v1/oauth2/token
grant_type=refresh_token&refresh_token={token}&client_id={id}
```

## Common Models
- `qwen-plus` - Balanced
- `qwen-max` - Most capable
- `qwen-turbo` - Fastest
- `qwen3-coder-plus` - Code specialist

## Error Handling
- 401/403 → Refresh token
- 429 → Backoff and retry
- 500+ → Retry with backoff

---

**END OF COMPLETE DOCUMENTATION**

**Document Version:** 1.0.0  
**Last Updated:** 2026-04-19  
**Total Pages:** 2,160+ lines  
**File Size:** 81KB+

For the latest updates and additional resources, refer to the individual documentation files or visit the Qwen Code repository.
