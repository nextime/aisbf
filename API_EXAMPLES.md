# AISBF API Examples

This document provides practical examples for using the AISBF API endpoints.

## Table of Contents
- [Three Proxy Paths](#three-proxy-paths)
- [Chat Completions](#chat-completions)
- [Audio Endpoints](#audio-endpoints)
- [Image Generation](#image-generation)
- [Embeddings](#embeddings)
- [Model Listing](#model-listing)
- [Advanced Features](#advanced-features)

## Three Proxy Paths

AISBF provides three ways to proxy AI models:

### PATH 1: Direct Provider Models
Format: `{provider_id}/{model_name}`
```bash
# Examples:
"openai/gpt-4"
"gemini/gemini-2.0-flash"
"anthropic/claude-3-5-sonnet-20241022"
"kilotest/kilo/free"
```

### PATH 2: Rotations
Format: `rotation/{rotation_name}`
```bash
# Examples:
"rotation/coding"
"rotation/general"
```

### PATH 3: Autoselect
Format: `autoselect/{autoselect_name}`
```bash
# Examples:
"autoselect/autoselect"
```

## OpenAI-Compatible v1 Endpoints

The v1 endpoints follow the standard OpenAI API format and support all three proxy paths.

### Chat Completions

#### PATH 1: Direct Provider Models

Using cURL:
```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"  # Not required if auth is disabled
)

response = client.chat.completions.create(
    model="openai/gpt-4",
    messages=[
        {"role": "user", "content": "Hello, how are you?"}
    ]
)

print(response.choices[0].message.content)
```

Different providers:
```bash
# Google Gemini
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini/gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Anthropic Claude
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-3-5-sonnet-20241022",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Custom provider with nested model path
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kilotest/kilo/free",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Ollama (local)
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ollama/llama2",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

#### PATH 2: Rotations (Load Balancing)

Using cURL:
```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rotation/coding",
    "messages": [
      {"role": "user", "content": "Write a Python function to sort a list"}
    ]
  }'
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.chat.completions.create(
    model="rotation/coding",
    messages=[
        {"role": "user", "content": "Write a Python function to sort a list"}
    ]
)

print(response.choices[0].message.content)
```

#### PATH 3: Autoselect (AI-Powered Selection)

Using cURL:
```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autoselect/autoselect",
    "messages": [
      {"role": "user", "content": "Debug this Python code: def add(a,b): return a-b"}
    ]
  }'
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.chat.completions.create(
    model="autoselect/autoselect",
    messages=[
        {"role": "user", "content": "Debug this Python code: def add(a,b): return a-b"}
    ]
)

print(response.choices[0].message.content)
```

#### Streaming Response

Works with all three proxy paths:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

# PATH 1: Direct provider
stream = client.chat.completions.create(
    model="gemini/gemini-2.0-flash",
    messages=[{"role": "user", "content": "Write a short poem"}],
    stream=True
)

# PATH 2: Rotation
stream = client.chat.completions.create(
    model="rotation/coding",
    messages=[{"role": "user", "content": "Write a short poem"}],
    stream=True
)

# PATH 3: Autoselect
stream = client.chat.completions.create(
    model="autoselect/autoselect",
    messages=[{"role": "user", "content": "Write a short poem"}],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## Audio Endpoints

**Note:** Audio endpoints support all three proxy paths (direct providers, rotations, and autoselect).

### Audio Transcription

Using `/api/audio/transcriptions`:
```bash
curl -X POST http://localhost:17765/api/audio/transcriptions \
  -F "file=@audio.mp3" \
  -F "model=openai/whisper-1"
```

Using `/api/v1/audio/transcriptions` (OpenAI-compatible):
```bash
curl -X POST http://localhost:17765/api/v1/audio/transcriptions \
  -F "file=@audio.mp3" \
  -F "model=openai/whisper-1"
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

with open("audio.mp3", "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="openai/whisper-1",
        file=audio_file
    )

print(transcript.text)
```

### Text-to-Speech

Using `/api/audio/speech`:
```bash
curl -X POST http://localhost:17765/api/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/tts-1",
    "input": "Hello, this is a test.",
    "voice": "alloy"
  }' \
  --output speech.mp3
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.audio.speech.create(
    model="openai/tts-1",
    voice="alloy",
    input="Hello, this is a test."
)

response.stream_to_file("speech.mp3")
```

## Image Generation

**Note:** Image generation supports all three proxy paths (direct providers, rotations, and autoselect).

Using `/api/images/generations`:
```bash
curl -X POST http://localhost:17765/api/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/dall-e-3",
    "prompt": "A beautiful sunset over mountains",
    "n": 1,
    "size": "1024x1024"
  }'
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.images.generate(
    model="openai/dall-e-3",
    prompt="A beautiful sunset over mountains",
    n=1,
    size="1024x1024"
)

print(response.data[0].url)
```

## Embeddings

**Note:** Embeddings support all three proxy paths (direct providers, rotations, and autoselect).

Using `/api/embeddings`:
```bash
curl -X POST http://localhost:17765/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/text-embedding-ada-002",
    "input": "The quick brown fox jumps over the lazy dog"
  }'
```

Using Python with OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.embeddings.create(
    model="openai/text-embedding-ada-002",
    input="The quick brown fox jumps over the lazy dog"
)

print(response.data[0].embedding)
```

## Model Listing

### List All Models (All Three Proxy Paths)

The `/api/models` endpoint lists models from all three proxy paths:

Using cURL:
```bash
curl http://localhost:17765/api/models
```

Using Python:
```python
import requests

response = requests.get("http://localhost:17765/api/models")
models = response.json()["data"]

for model in models:
    print(f"{model['id']} - Type: {model.get('type', 'unknown')}")
```

Using OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

models = client.models.list()
for model in models.data:
    print(f"{model.id} - {model.owned_by}")
```

Example output:
```
openai/gpt-4 - Type: provider
gemini/gemini-2.0-flash - Type: provider
rotation/coding - Type: rotation
rotation/general - Type: rotation
autoselect/autoselect - Type: autoselect
```

## Legacy Endpoints

For backward compatibility, these endpoints are still available:

### Legacy Provider Endpoints
```bash
# Direct provider access (model without provider prefix)
curl -X POST http://localhost:17765/api/openai/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# List provider models
curl http://localhost:17765/api/openai/models
```

### Legacy Rotation Endpoints
```bash
# List rotations
curl http://localhost:17765/api/rotations

# Use rotation (model name = rotation name)
curl -X POST http://localhost:17765/api/rotations/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "coding",
    "messages": [{"role": "user", "content": "Write code"}]
  }'
```

### Legacy Autoselect Endpoints
```bash
# List autoselect configurations
curl http://localhost:17765/api/autoselect

# Use autoselect (model name = autoselect name)
curl -X POST http://localhost:17765/api/autoselect/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autoselect",
    "messages": [{"role": "user", "content": "Help me"}]
  }'
```

## Authentication

If authentication is enabled in your configuration:

```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="YOUR_TOKEN_HERE"
)

response = client.chat.completions.create(
    model="openai/gpt-4",
    messages=[{"role": "user", "content": "Hello"}]
)
```

## JavaScript/Node.js Examples

### Using fetch API

PATH 1: Direct Provider
```javascript
const response = await fetch('http://localhost:17765/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'openai/gpt-4',
    messages: [
      { role: 'user', content: 'Hello, how are you?' }
    ]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

PATH 2: Rotation
```javascript
const response = await fetch('http://localhost:17765/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'rotation/coding',
    messages: [
      { role: 'user', content: 'Write a sorting function' }
    ]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

PATH 3: Autoselect
```javascript
const response = await fetch('http://localhost:17765/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'autoselect/autoselect',
    messages: [
      { role: 'user', content: 'Help me with this task' }
    ]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

### Using OpenAI SDK

Works with all three proxy paths:
```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:17765/api/v1',
  apiKey: 'dummy'
});

// PATH 1: Direct provider
const response1 = await client.chat.completions.create({
  model: 'openai/gpt-4',
  messages: [{ role: 'user', content: 'Hello' }]
});

// PATH 2: Rotation
const response2 = await client.chat.completions.create({
  model: 'rotation/coding',
  messages: [{ role: 'user', content: 'Write code' }]
});

// PATH 3: Autoselect
const response3 = await client.chat.completions.create({
  model: 'autoselect/autoselect',
  messages: [{ role: 'user', content: 'Help me' }]
});

console.log(response1.choices[0].message.content);
```

### Streaming in JavaScript

Works with all three proxy paths:
```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:17765/api/v1',
  apiKey: 'dummy'
});

// Use any of the three proxy paths
const stream = await client.chat.completions.create({
  model: 'gemini/gemini-2.0-flash',  // or 'rotation/coding' or 'autoselect/autoselect'
  messages: [
    { role: 'user', content: 'Write a short poem' }
  ],
  stream: true
});

for await (const chunk of stream) {
  const content = chunk.choices[0]?.delta?.content || '';
  process.stdout.write(content);
}
```

## Error Handling

```python
from openai import OpenAI, OpenAIError

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

try:
    response = client.chat.completions.create(
        model="openai/gpt-4",
        messages=[
            {"role": "user", "content": "Hello"}
        ]
    )
    print(response.choices[0].message.content)
except OpenAIError as e:
    print(f"Error: {e}")
```

## Advanced Features

### Context Condensation

When using models with large context windows, AISBF automatically condenses context when approaching limits:

```python
# Large context will be automatically condensed
response = client.chat.completions.create(
    model="gemini/gemini-2.0-flash",
    messages=[
        {"role": "user", "content": "Very long prompt..."},
        # ... many messages
    ]
)
```

### Rate Limiting

AISBF automatically handles rate limits and rotates to available providers:

```python
# If rate limit is hit, AISBF will automatically use another provider
for i in range(100):
    response = client.chat.completions.create(
        model="coding",  # Rotation with multiple providers
        messages=[{"role": "user", "content": f"Request {i}"}]
    )
```

## MCP Server (Model Context Protocol)

AISBF includes an MCP server that allows remote agents to configure the system and make model requests. MCP is disabled by default and must be enabled in the configuration.

### Enabling MCP

Add to your `aisbf.json` config:
```json
{
  "mcp": {
    "enabled": true,
    "autoselect_tokens": ["your-autoselect-token"],
    "fullconfig_tokens": ["your-fullconfig-token"]
  }
}
```

Or use the dashboard settings page.

### Authentication Levels

- **Autoselect Tokens**: Access to autoselection/autorotation settings + standard APIs
- **Fullconfig Tokens**: Access to full system configuration + standard APIs

### MCP Endpoints

#### SSE Endpoint (Streaming)
```bash
# Initialize connection
curl -N http://localhost:17765/mcp \
  -H "Authorization: Bearer your-token"
```

#### HTTP POST Endpoint
```bash
# List available tools
curl -X POST http://localhost:17765/mcp \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'

# Call a tool
curl -X POST http://localhost:17765/mcp \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "list_models",
      "arguments": {}
    }
  }'
```

#### Direct Tool Calls
```bash
# List available tools
curl http://localhost:17765/mcp/tools \
  -H "Authorization: Bearer your-token"

# Call a tool directly
curl -X POST http://localhost:17765/mcp/tools/call \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "list_models",
    "arguments": {}
  }'
```

### Available Tools

**Common tools (all authenticated clients):**
- `list_models` - List all available models
- `list_rotations` - List all rotation configurations
- `list_autoselect` - List all autoselect configurations
- `chat_completion` - Make chat completion requests

**Autoselect-level tools:**
- `get_autoselect_config` - Get autoselect configuration
- `get_rotation_config` - Get rotation configuration
- `get_autoselect_settings` - Get autoselect settings
- `get_rotation_settings` - Get rotation settings

**Fullconfig-level tools:**
- `get_providers_config` - Get providers configuration
- `set_autoselect_config` - Set autoselect configuration
- `set_rotation_config` - Set rotation configuration
- `set_provider_config` - Set provider configuration
- `get_server_config` - Get server configuration
- `set_server_config` - Set server configuration
- `delete_autoselect_config` - Delete autoselect configuration
- `delete_rotation_config` - Delete rotation configuration
- `delete_provider_config` - Delete provider configuration

### Example: Using MCP with Claude Code

```bash
# Set the MCP server URL
global MCP_SERVER_URL "http://localhost:17765/mcp"
global MCP_AUTH_TOKEN "your-fullconfig-token"

# Or configure in your AI tool's MCP settings
```

## Dashboard Access

Access the web dashboard at:
```
http://localhost:17765/dashboard
```

Default credentials:
- Username: `admin`
- Password: `admin` (SHA256 hashed in config)

## User-Specific API Endpoints

AISBF provides user-specific API endpoints that allow authenticated users to access their own configurations. These endpoints are useful for users who want to manage their own providers, rotations, and autoselects separately from the global configuration.

### Authentication

All user-specific endpoints require authentication via Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_USER_TOKEN" http://localhost:17765/api/u/yourusername/models
```

Generate a user token from the dashboard: **Dashboard > My Account > API Tokens**

### User API Endpoints

#### List User Models

Returns all models from the user's own providers, rotations, and autoselects:

```bash
# Get all user models
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/models
```

Response includes:
- User provider models (`user-provider/provider_id/model_name`)
- User rotation models (`user-rotation/rotation_name`)
- User autoselect models (`user-autoselect/autoselect_name`)

#### List User Providers

Returns all user-configured providers:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/providers
```

#### List User Rotations

Returns all user-configured rotations:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/rotations
```

#### List User Autoselects

Returns all user-configured autoselects:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/autoselects
```

#### User Chat Completions

Send chat completion requests using user's own configurations:

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "user-rotation/myrotation",
    "messages": [{"role": "user", "content": "Hello"}]
  }' \
  http://localhost:17765/api/u/yourusername/chat/completions
```

**Model formats for user endpoints:**
- `user-provider/provider_id/model_name` - Use user's provider
- `user-rotation/rotation_name` - Use user's rotation  
- `user-autoselect/autoselect_name` - Use user's autoselect

**Admin users** can also access global configurations via these endpoints using the format:
- `provider/model_name` - Global provider
- `rotation/rotation_name` - Global rotation
- `autoselect/autoselect_name` - Global autoselect

#### List Models for Specific Config Type

Get models for a specific user configuration type:

```bash
# Get user provider models
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/providers/models

# Get user rotation models
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/rotations/models

# Get user autoselect models
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/autoselects/models
```

### Python Examples

```python
import requests

BASE_URL = "http://localhost:17765"
TOKEN = "YOUR_USER_TOKEN"

headers = {"Authorization": f"Bearer {TOKEN}"}

# List user models
response = requests.get(f"{BASE_URL}/api/u/yourusername/models", headers=headers)
print(response.json())

# List user providers
response = requests.get(f"{BASE_URL}/api/u/yourusername/providers", headers=headers)
print(response.json())

# Send chat completion using user rotation
response = requests.post(
    f"{BASE_URL}/api/u/yourusername/chat/completions",
    headers=headers,
    json={
        "model": "user-rotation/myrotation",
        "messages": [{"role": "user", "content": "Hello"}]
    }
)
print(response.json())
```

### Using with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="YOUR_USER_TOKEN"  # Use user token as API key
)

# Use user's rotation
response = client.chat.completions.create(
    model="user-rotation/myrotation",
    messages=[{"role": "user", "content": "Hello"}]
)

print(response.choices[0].message.content)
```

## MCP User Tools

The MCP server includes user-specific tools that allow authenticated users to configure their own models, providers, rotations, and autoselects. These tools are available when a user_id is associated with the authenticated token.

### Available User Tools

**User Models:**
- `list_user_models` - List all models from user's own configurations

**User Providers:**
- `list_user_providers` - List all user-configured providers
- `get_user_provider` - Get a specific user provider
- `set_user_provider` - Save a user provider configuration
- `delete_user_provider` - Delete a user provider

**User Rotations:**
- `list_user_rotations` - List all user-configured rotations
- `get_user_rotation` - Get a specific user rotation
- `set_user_rotation` - Save a user rotation configuration
- `delete_user_rotation` - Delete a user rotation

**User Autoselects:**
- `list_user_autoselects` - List all user-configured autoselects
- `get_user_autoselect` - Get a specific user autoselect
- `set_user_autoselect` - Save a user autoselect configuration
- `delete_user_autoselect` - Delete a user autoselect

**User Chat:**
- `user_chat_completion` - Send chat completion using user's configurations

### MCP User Tool Examples

```bash
# List user models
curl -X POST http://localhost:17765/mcp \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "list_user_models",
      "arguments": {}
    }
  }'

# Set a user provider
curl -X POST http://localhost:17765/mcp \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "set_user_provider",
      "arguments": {
        "provider_id": "myprovider",
        "provider_data": {
          "name": "My Provider",
          "type": "openai",
          "endpoint": "https://api.openai.com/v1",
          "api_key": "sk-...",
          "models": [
            {"name": "gpt-4"}
          ]
        }
      }
    }
  }'

# Send chat using user's rotation
curl -X POST http://localhost:17765/mcp \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "user_chat_completion",
      "arguments": {
        "model": "user-rotation/myrotation",
        "messages": [{"role": "user", "content": "Hello"}]
      }
    }
  }'
```

### Direct Tool Call Examples

```bash
# List user providers
curl -X POST http://localhost:17765/mcp/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "list_user_providers",
    "arguments": {}
  }'

# Get user rotation
curl -X POST http://localhost:17765/mcp/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_user_rotation",
    "arguments": {
      "rotation_id": "myrotation"
    }
  }'
```

## License

Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
