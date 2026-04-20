# Complete ChatGPT/OpenAI API Request Flow Documentation

This document provides a comprehensive analysis of how Codex sends requests to the ChatGPT/OpenAI API, including authentication, headers, request format, session management, and endpoints.

## Table of Contents

1. [Authentication & OAuth2 Flow](#1-authentication--oauth2-flow)
2. [API Endpoints](#2-api-endpoints)
3. [Request Headers](#3-request-headers)
4. [Request Body Format](#4-request-body-format)
5. [Session Management](#5-session-management)
6. [Transport Mechanisms](#6-transport-mechanisms)
7. [System Prompt (Instructions)](#7-system-prompt-instructions)
8. [Message Format Conversion](#8-message-format-conversion-openai-compatible--chatgpt)
9. [Complete Request Flow](#9-complete-request-flow)
10. [Python Implementation Example](#10-python-implementation-example)

---

## 1. Authentication & OAuth2 Flow

### OAuth2 Token Management

**Location**: `codex-rs/login/src/auth/manager.rs`

Codex uses OAuth2 device code flow for ChatGPT authentication:

#### 1.1 Device Code Request

- **Endpoint**: `https://auth0.openai.com/oauth/device/code`
- **Client ID**: Retrieved from configuration
- **Scope**: `openid profile email offline_access`

#### 1.2 Token Exchange

- **Endpoint**: `https://auth0.openai.com/oauth/token`
- **Grant type**: `urn:ietf:params:oauth:grant-type:device_code`
- **Returns**: `access_token`, `refresh_token`, `id_token`

#### 1.3 Token Storage

- Tokens stored in `~/.codex/auth.json` or system keyring
- ID token contains `chatgpt_account_id` claim
- Access token used for API authentication

#### 1.4 Token Refresh

- Automatic refresh on 401 responses
- Uses refresh token to get new access token
- Implements retry logic with exponential backoff

### Token Data Structure

```rust
pub struct TokenData {
    pub access_token: String,
    pub refresh_token: Option<String>,
    pub account_id: Option<String>,  // From chatgpt_account_id claim
    pub id_token: IdTokenClaims,
}
```

---

## 2. API Endpoints

### Base URL

- **Default**: `https://chatgpt.com/backend-api/`
- **Configurable**: via `chatgpt_base_url` in config

### Primary Endpoints

#### 2.1 Responses API (Main chat endpoint)

- **Path**: `/v1/responses`
- **Method**: `POST`
- **Transport**: HTTP (SSE) or WebSocket
- **Purpose**: Streaming chat completions

#### 2.2 Compact API (History compression)

- **Path**: `/v1/responses/compact`
- **Method**: `POST`
- **Purpose**: Compress conversation history

#### 2.3 Memories API (Memory summarization)

- **Path**: `/v1/memories/trace_summarize`
- **Method**: `POST`
- **Purpose**: Summarize conversation memories

#### 2.4 Models List

- **Path**: `/models`
- **Method**: `GET`
- **Purpose**: Retrieve available models

#### 2.5 Plugins

- **Path**: `/plugins/list`
- **Path**: `/plugins/featured`
- **Path**: `/plugins/export/curated`

#### 2.6 Files (OpenAI file uploads)

- **Path**: `/files`
- **Method**: `POST`
- **Path**: `/files/{file_id}/uploaded`
- **Method**: `POST`

#### 2.7 Realtime (Voice/WebRTC)

- **Path**: `/v1/realtime/calls`
- **Method**: `POST`
- **Purpose**: Create WebRTC voice sessions

---

## 3. Request Headers

### 3.1 Authentication Headers

**Location**: `codex-rs/model-provider/src/bearer_auth_provider.rs`

```http
Authorization: Bearer {access_token}
ChatGPT-Account-ID: {account_id}
```

For FedRAMP accounts:

```http
X-OpenAI-Fedramp: true
```

### 3.2 Standard Headers

**Location**: `codex-rs/login/src/auth/default_client.rs`

```http
User-Agent: {originator}/{version} ({os} {os_version}; {arch}) {terminal_info} ({suffix})
originator: codex_cli_rs
Content-Type: application/json
```

Example User-Agent:

```
codex_cli_rs/0.1.0 (Linux 5.15.0; x86_64) iTerm2/3.4.0
```

### 3.3 Codex-Specific Headers

**Location**: `codex-rs/core/src/client.rs`

#### Session Identification

```http
session_id: {conversation_id}
x-client-request-id: {conversation_id}
```

#### Installation Tracking

```http
x-codex-installation-id: {installation_id}
```

#### Window/Turn Tracking

```http
x-codex-window-id: {conversation_id}:{window_generation}
x-codex-turn-state: {sticky_routing_token}
x-codex-turn-metadata: {base64_encoded_metadata}
```

#### Subagent Identification

```http
x-openai-subagent: review|compact|memory_consolidation|collab_spawn
x-codex-parent-thread-id: {parent_thread_id}
```

#### Feature Flags

```http
x-codex-beta-features: {comma_separated_features}
OpenAI-Beta: responses_websockets=2026-02-06
```

#### Telemetry

```http
x-responsesapi-include-timing-metrics: true
```

#### Residency (Enterprise)

```http
x-openai-internal-codex-residency: us
```

---

## 4. Request Body Format

### 4.1 Main Request Structure

**Location**: `codex-rs/codex-api/src/common.rs`

```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful coding assistant...",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Hello, how are you?"
        }
      ]
    }
  ],
  "tools": [],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "reasoning": {
    "effort": "medium",
    "summary": "auto"
  },
  "store": false,
  "stream": true,
  "include": ["reasoning.encrypted_content"],
  "service_tier": "default",
  "prompt_cache_key": "{conversation_id}",
  "text": {
    "verbosity": "medium",
    "format": {
      "type": "json_schema",
      "strict": true,
      "schema": {},
      "name": "codex_output_schema"
    }
  },
  "client_metadata": {
    "x-codex-installation-id": "...",
    "ws_request_header_traceparent": "...",
    "ws_request_header_tracestate": "..."
  }
}
```

### 4.2 Input Items (ResponseItem)

**Location**: `codex-rs/protocol/src/models.rs`

The `input` array contains conversation history as `ResponseItem` objects:

```rust
pub enum ResponseItem {
    Message {
        role: String,  // "user", "assistant", "developer"
        content: Vec<ContentItem>,
    },
    FunctionCall {
        call_id: String,
        name: String,
        arguments: String,
    },
    FunctionCallOutput {
        call_id: String,
        output: FunctionCallOutputPayload,
    },
    CustomToolCall {
        call_id: String,
        name: String,
        input: Value,
    },
    CustomToolCallOutput {
        call_id: String,
        output: FunctionCallOutputPayload,
    },
    Reasoning {
        content: Vec<ReasoningContent>,
        summary: Vec<String>,
    },
    // ... other types
}
```

### 4.3 Content Items

```rust
pub enum ContentItem {
    InputText { text: String },
    InputImage {
        source: ImageSource,
        detail: Option<String>,
    },
    OutputText { text: String },
    // ... other types
}
```

---

## 5. Session Management

### 5.1 Conversation ID (ThreadId)

**Location**: `codex-rs/protocol/src/protocol.rs`

- **Format**: UUID v4
- **Persistence**: Across entire conversation
- **Used for**:
  - Session identification (`session_id` header)
  - Prompt caching (`prompt_cache_key`)
  - Window tracking (`x-codex-window-id`)

### 5.2 Window Generation

**Location**: `codex-rs/core/src/client.rs`

- Increments when conversation context is reset
- **Format**: `{conversation_id}:{window_generation}`
- **Sent in**: `x-codex-window-id` header

### 5.3 Turn State (Sticky Routing)

**Location**: `codex-rs/core/src/client.rs`

```http
# Server sends in response header:
x-codex-turn-state: {opaque_token}

# Client echoes back in subsequent requests within same turn:
x-codex-turn-state: {same_token}
```

**Purpose**: Ensures requests within a turn hit the same backend instance

---

## 6. Transport Mechanisms

### 6.1 HTTP (SSE - Server-Sent Events)

**Location**: `codex-rs/core/src/client.rs:1132`

1. POST to `/v1/responses`
2. Response: `Content-Type: text/event-stream`
3. **Events**:
   - `response.created`
   - `response.output_item.added`
   - `response.output_item.done`
   - `response.completed`
   - `response.failed`

### 6.2 WebSocket

**Location**: `codex-rs/core/src/client.rs:1229`

#### Connection

- Upgrade HTTP to WebSocket
- **Path**: `/v1/responses`
- **Protocol**: `responses_websockets=2026-02-06`

#### Request Format

```json
{
  "type": "response.create",
  "model": "gpt-4",
  "instructions": "...",
  "input": [],
  "previous_response_id": "resp_123",
  "generate": false,
  ...
}
```

#### Incremental Requests

- Reuses WebSocket connection
- Sends only delta of new input items
- References `previous_response_id`

#### Fallback

- Falls back to HTTP on connection failure
- Session-scoped: once activated, stays on HTTP

---

## 7. System Prompt (Instructions)

### 7.1 Base Instructions

**Location**: `codex-rs/protocol/src/models.rs`

```rust
pub struct BaseInstructions {
    pub text: String,
    pub personality: Option<Personality>,
}
```

### 7.2 Instruction Sources (Priority Order)

1. **User Override**: `config.base_instructions`
2. **Model Default**: `model_info.base_instructions`
3. **Personality Template**: Applied if no override

### 7.3 Instruction Composition

**Location**: `codex-rs/core/src/session/session.rs`

```rust
// Final instructions sent to API:
instructions = base_instructions + tool_instructions + context_tags
```

Context tags include:

- Sandbox mode information
- Collaboration mode
- Realtime conversation state
- Approval settings

---

## 8. Message Format Conversion (OpenAI Compatible → ChatGPT)

### 8.1 Key Differences

1. **No Direct OpenAI Format**:
   - Codex doesn't use OpenAI's `messages` array format
   - Uses custom `ResponseItem` enum instead

2. **Input Array**:
   - **OpenAI**: `messages: [{role, content}]`
   - **Codex**: `input: [ResponseItem]`

3. **Instructions vs System Message**:
   - **OpenAI**: System message in `messages` array
   - **Codex**: Separate `instructions` field

4. **Tool Calls**:
   - **OpenAI**: Embedded in message content
   - **Codex**: Separate `ResponseItem` types (`FunctionCall`, `FunctionCallOutput`)

### 8.2 Conversion Example

**OpenAI Format**:

```json
{
  "model": "gpt-4",
  "messages": [
    { "role": "system", "content": "You are helpful" },
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi there!" }
  ]
}
```

**Codex Format**:

```json
{
  "model": "gpt-4",
  "instructions": "You are helpful",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [{ "type": "input_text", "text": "Hello" }]
    },
    {
      "type": "message",
      "role": "assistant",
      "content": [{ "type": "output_text", "text": "Hi there!" }]
    }
  ]
}
```

---

## 9. Complete Request Flow

### Step-by-Step Process

#### Step 1: Authentication

```python
# Load tokens from storage
tokens = load_from_auth_json()
access_token = tokens['access_token']
account_id = tokens['id_token']['chatgpt_account_id']
```

#### Step 2: Build Headers

```python
headers = {
    'Authorization': f'Bearer {access_token}',
    'ChatGPT-Account-ID': account_id,
    'User-Agent': 'codex_cli_rs/0.1.0 (Linux 5.15.0; x86_64) iTerm2',
    'originator': 'codex_cli_rs',
    'Content-Type': 'application/json',
    'session_id': conversation_id,
    'x-codex-installation-id': installation_id,
    'x-codex-window-id': f'{conversation_id}:0',
    'OpenAI-Beta': 'responses_websockets=2026-02-06',
}
```

#### Step 3: Build Request Body

```python
body = {
    'model': 'gpt-4',
    'instructions': base_instructions,
    'input': conversation_history,  # List of ResponseItem
    'tools': tool_definitions,
    'tool_choice': 'auto',
    'parallel_tool_calls': True,
    'stream': True,
    'store': False,
    'prompt_cache_key': conversation_id,
}
```

#### Step 4: Send Request

```python
# HTTP/SSE
response = requests.post(
    'https://chatgpt.com/backend-api/v1/responses',
    headers=headers,
    json=body,
    stream=True
)

# Or WebSocket
ws = websocket.create_connection(
    'wss://chatgpt.com/backend-api/v1/responses',
    header=headers
)
ws.send(json.dumps({'type': 'response.create', **body}))
```

#### Step 5: Handle Response

```python
# SSE
for line in response.iter_lines():
    if line.startswith(b'data: '):
        event = json.loads(line[6:])
        handle_event(event)

# WebSocket
while True:
    message = json.loads(ws.recv())
    handle_event(message)
```

#### Step 6: Handle 401 (Token Refresh)

```python
if response.status_code == 401:
    # Refresh token
    new_tokens = refresh_access_token(refresh_token)
    # Retry request with new token
```

#### Step 7: Update Turn State

```python
# Extract from response headers
turn_state = response.headers.get('x-codex-turn-state')
# Include in next request within same turn
headers['x-codex-turn-state'] = turn_state
```

---

## 10. Python Implementation Example

```python
import requests
import json
import uuid
from typing import List, Dict, Any

class CodexChatGPTClient:
    def __init__(self, access_token: str, account_id: str):
        self.base_url = "https://chatgpt.com/backend-api"
        self.access_token = access_token
        self.account_id = account_id
        self.conversation_id = str(uuid.uuid4())
        self.installation_id = str(uuid.uuid4())
        self.window_generation = 0
        self.turn_state = None

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'ChatGPT-Account-ID': self.account_id,
            'User-Agent': 'custom_client/1.0.0 (Linux; x86_64)',
            'originator': 'custom_client',
            'Content-Type': 'application/json',
            'session_id': self.conversation_id,
            'x-client-request-id': self.conversation_id,
            'x-codex-installation-id': self.installation_id,
            'x-codex-window-id': f'{self.conversation_id}:{self.window_generation}',
        }

        if self.turn_state:
            headers['x-codex-turn-state'] = self.turn_state

        return headers

    def send_message(self,
                     user_message: str,
                     conversation_history: List[Dict],
                     instructions: str = "You are a helpful assistant.") -> None:

        # Build input array
        input_items = []
        for item in conversation_history:
            input_items.append({
                'type': 'message',
                'role': item['role'],
                'content': [{'type': 'input_text', 'text': item['content']}]
            })

        # Add current message
        input_items.append({
            'type': 'message',
            'role': 'user',
            'content': [{'type': 'input_text', 'text': user_message}]
        })

        # Build request body
        body = {
            'model': 'gpt-4',
            'instructions': instructions,
            'input': input_items,
            'tools': [],
            'tool_choice': 'auto',
            'parallel_tool_calls': True,
            'stream': True,
            'store': False,
            'prompt_cache_key': self.conversation_id,
        }

        # Send request
        response = requests.post(
            f'{self.base_url}/v1/responses',
            headers=self._build_headers(),
            json=body,
            stream=True
        )

        # Update turn state from response
        if 'x-codex-turn-state' in response.headers:
            self.turn_state = response.headers['x-codex-turn-state']

        # Process SSE stream
        for line in response.iter_lines():
            if line.startswith(b'data: '):
                try:
                    event = json.loads(line[6:])
                    self._handle_event(event)
                except json.JSONDecodeError:
                    continue

    def _handle_event(self, event: Dict[str, Any]):
        event_type = event.get('type')

        if event_type == 'response.output_item.done':
            item = event.get('item', {})
            if item.get('type') == 'message':
                content = item.get('content', [])
                for c in content:
                    if c.get('type') == 'output_text':
                        print(c.get('text', ''), end='', flush=True)

        elif event_type == 'response.completed':
            print()  # New line after completion


# Usage example
if __name__ == "__main__":
    # Assuming you have valid tokens from OAuth2 flow
    client = CodexChatGPTClient(
        access_token="your_access_token_here",
        account_id="your_account_id_here"
    )

    # Send a message
    client.send_message(
        user_message="Hello, how are you?",
        conversation_history=[],
        instructions="You are a helpful coding assistant."
    )
```

---

## Summary

This documentation provides a complete reference for implementing a standalone client that mimics Codex's request behavior to ChatGPT's backend API. Key takeaways:

1. **Authentication**: Uses OAuth2 device code flow with token refresh
2. **Headers**: Requires `Authorization`, `ChatGPT-Account-ID`, and various Codex-specific headers
3. **Format**: Uses custom `ResponseItem` format instead of OpenAI's `messages` array
4. **Transport**: Supports both HTTP/SSE and WebSocket with automatic fallback
5. **Session Management**: Uses conversation IDs, window generations, and turn state for routing
6. **Instructions**: Separate `instructions` field instead of system messages

All code locations reference the Codex Rust codebase for verification and deeper exploration.

---

## 11. Detailed Request Examples with Tool Usage

### 11.1 Simple Text Request (No Tools)

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful coding assistant.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "What is Python?"
        }
      ]
    }
  ],
  "tools": [],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "reasoning": null,
  "store": false,
  "stream": true,
  "include": [],
  "service_tier": null,
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000",
  "text": null,
  "client_metadata": {
    "x-codex-installation-id": "123e4567-e89b-12d3-a456-426614174000"
  }
}
```

### 11.2 Request with Function Tools

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful coding assistant with access to shell commands.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "List files in the current directory"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "shell",
      "description": "Execute a shell command and return the output",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string",
            "description": "The shell command to execute"
          },
          "workdir": {
            "type": "string",
            "description": "Working directory for command execution"
          }
        },
        "required": ["command"],
        "additionalProperties": false
      }
    }
  ],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "reasoning": null,
  "store": false,
  "stream": true,
  "include": [],
  "service_tier": null,
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000",
  "text": null,
  "client_metadata": {
    "x-codex-installation-id": "123e4567-e89b-12d3-a456-426614174000"
  }
}
```

### 11.3 Request with Tool Call and Output in History

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful coding assistant.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "List files in the current directory"
        }
      ]
    },
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "I'll list the files for you."
        }
      ]
    },
    {
      "type": "function_call",
      "call_id": "call_abc123",
      "name": "shell",
      "arguments": "{\"command\":\"ls -la\"}"
    },
    {
      "type": "function_call_output",
      "call_id": "call_abc123",
      "output": {
        "type": "text",
        "text": "total 48\ndrwxr-xr-x  12 user  staff   384 Apr 19 10:30 .\ndrwxr-xr-x   6 user  staff   192 Apr 18 15:20 ..\n-rw-r--r--   1 user  staff  1234 Apr 19 10:25 README.md\n-rw-r--r--   1 user  staff   567 Apr 19 10:30 main.py"
      }
    },
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "What's in main.py?"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "shell",
      "description": "Execute a shell command",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string"
          }
        },
        "required": ["command"]
      }
    }
  ],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "store": false,
  "stream": true,
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 11.4 Request with Built-in Tools

**Request with local_shell, web_search, and image_generation:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful assistant with access to shell, web search, and image generation.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Search for Python tutorials and create a diagram"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "local_shell"
    },
    {
      "type": "web_search",
      "external_web_access": true,
      "search_context_size": "medium",
      "search_content_types": ["text", "image"]
    },
    {
      "type": "image_generation",
      "output_format": "url"
    }
  ],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "store": false,
  "stream": true,
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 11.5 Request with Reasoning Controls

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful coding assistant.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Explain how quicksort works"
        }
      ]
    }
  ],
  "tools": [],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "reasoning": {
    "effort": "high",
    "summary": "auto"
  },
  "store": false,
  "stream": true,
  "include": ["reasoning.encrypted_content"],
  "service_tier": null,
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Reasoning effort options:**
- `"low"` - Minimal reasoning
- `"medium"` - Balanced reasoning (default)
- `"high"` - Extended reasoning

**Reasoning summary options:**
- `"auto"` - Automatic summary generation
- `"none"` - No summary
- `"concise"` - Brief summary
- `"detailed"` - Detailed summary

### 11.6 Request with Verbosity Control

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful coding assistant.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Explain Python decorators"
        }
      ]
    }
  ],
  "tools": [],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "store": false,
  "stream": true,
  "text": {
    "verbosity": "high"
  },
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Verbosity options:**
- `"low"` - Concise responses
- `"medium"` - Balanced responses (default)
- `"high"` - Detailed responses

### 11.7 Request with JSON Schema Output

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful assistant that returns structured data.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "List 3 programming languages with their use cases"
        }
      ]
    }
  ],
  "tools": [],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "store": false,
  "stream": true,
  "text": {
    "format": {
      "type": "json_schema",
      "strict": true,
      "name": "programming_languages",
      "schema": {
        "type": "object",
        "properties": {
          "languages": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": {
                  "type": "string"
                },
                "use_case": {
                  "type": "string"
                }
              },
              "required": ["name", "use_case"],
              "additionalProperties": false
            }
          }
        },
        "required": ["languages"],
        "additionalProperties": false
      }
    }
  },
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 11.8 Request with Image Input

**Request:**
```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful assistant that can analyze images.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "What's in this image?"
        },
        {
          "type": "input_image",
          "source": {
            "type": "url",
            "url": "https://example.com/image.jpg"
          },
          "detail": "high"
        }
      ]
    }
  ],
  "tools": [],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "store": false,
  "stream": true,
  "prompt_cache_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Image detail options:**
- `"low"` - Low resolution analysis
- `"high"` - High resolution analysis
- `"auto"` - Automatic selection

---

## 12. Key Differences from Standard OpenAI API

### 12.1 Missing Fields in Codex/ChatGPT Format

The following OpenAI API fields are **NOT supported** in Codex's ChatGPT backend format:

#### Not Supported:
- `temperature` - Not configurable per request
- `top_p` - Not configurable per request
- `max_tokens` - Not configurable per request (handled internally)
- `max_completion_tokens` - Not configurable per request
- `presence_penalty` - Not supported
- `frequency_penalty` - Not supported
- `logit_bias` - Not supported
- `logprobs` - Not supported
- `top_logprobs` - Not supported
- `n` - Always 1 (single response)
- `stop` - Not configurable
- `seed` - Not supported
- `user` - Not used (account ID in header instead)

### 12.2 Codex-Specific Fields

Fields that exist in Codex but not in standard OpenAI API:

#### Codex-Only Fields:
- `instructions` - Replaces system message
- `input` - Replaces `messages` array
- `prompt_cache_key` - For prompt caching
- `client_metadata` - For telemetry and tracking
- `include` - For including reasoning content
- `text.verbosity` - Response verbosity control
- `reasoning.effort` - Reasoning effort level
- `reasoning.summary` - Reasoning summary type

### 12.3 Tool Definition Differences

**OpenAI Standard:**
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get weather information",
    "parameters": {
      "type": "object",
      "properties": {
        "location": {"type": "string"}
      },
      "required": ["location"]
    }
  }
}
```

**Codex/ChatGPT Format:**
```json
{
  "type": "function",
  "name": "get_weather",
  "description": "Get weather information",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {"type": "string"}
    },
    "required": ["location"],
    "additionalProperties": false
  }
}
```

**Key differences:**
- No nested `function` object
- `additionalProperties: false` is typically included
- Tool definition is flatter

### 12.4 Built-in Tool Types

Codex supports special built-in tool types not in standard OpenAI:

```json
{
  "type": "local_shell"
}
```

```json
{
  "type": "web_search",
  "external_web_access": true,
  "search_context_size": "medium"
}
```

```json
{
  "type": "image_generation",
  "output_format": "url"
}
```

```json
{
  "type": "tool_search",
  "execution": "client",
  "description": "Search for available tools",
  "parameters": {...}
}
```

```json
{
  "type": "namespace",
  "name": "mcp_server_name",
  "description": "Tools from MCP server",
  "tools": [...]
}
```

### 12.5 Response Format Differences

**OpenAI Standard Response:**
```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion.chunk",
  "created": 1677652288,
  "model": "gpt-4",
  "choices": [{
    "index": 0,
    "delta": {
      "content": "Hello"
    },
    "finish_reason": null
  }]
}
```

**Codex/ChatGPT SSE Events:**
```
data: {"type":"response.created","response_id":"resp_123"}

data: {"type":"response.output_item.added","item":{"type":"message","role":"assistant","content":[]}}

data: {"type":"response.output_text.delta","delta":"Hello"}

data: {"type":"response.output_item.done","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello"}]}}

data: {"type":"response.completed","response_id":"resp_123","token_usage":{"input_tokens":10,"output_tokens":5}}
```

### 12.6 Service Tier

Codex uses `service_tier` field for priority routing:

```json
{
  "service_tier": "default"
}
```

**Options:**
- `"default"` - Standard priority
- `"priority"` - High priority (maps to "fast" internally)
- `null` - No specific tier

This is different from OpenAI's standard API which doesn't have this field.

---

## 13. Complete Conversion Guide: OpenAI → Codex Format

### 13.1 Basic Conversion Function

```python
def convert_openai_to_codex(openai_request: dict) -> dict:
    """
    Convert OpenAI API format to Codex/ChatGPT format
    """
    codex_request = {
        "model": openai_request.get("model", "gpt-4"),
        "instructions": "",
        "input": [],
        "tools": [],
        "tool_choice": openai_request.get("tool_choice", "auto"),
        "parallel_tool_calls": openai_request.get("parallel_tool_calls", True),
        "store": False,
        "stream": openai_request.get("stream", True),
        "include": [],
        "service_tier": None,
        "prompt_cache_key": str(uuid.uuid4()),
    }
    
    # Extract system message as instructions
    messages = openai_request.get("messages", [])
    for msg in messages:
        if msg.get("role") == "system":
            codex_request["instructions"] = msg.get("content", "")
            break
    
    # Convert messages to input items
    for msg in messages:
        if msg.get("role") == "system":
            continue  # Already handled
            
        role = msg.get("role")
        content = msg.get("content", "")
        
        # Handle string content
        if isinstance(content, str):
            codex_request["input"].append({
                "type": "message",
                "role": role,
                "content": [{
                    "type": "input_text" if role == "user" else "output_text",
                    "text": content
                }]
            })
        # Handle array content (multimodal)
        elif isinstance(content, list):
            content_items = []
            for item in content:
                if item.get("type") == "text":
                    content_items.append({
                        "type": "input_text" if role == "user" else "output_text",
                        "text": item.get("text", "")
                    })
                elif item.get("type") == "image_url":
                    content_items.append({
                        "type": "input_image",
                        "source": {
                            "type": "url",
                            "url": item.get("image_url", {}).get("url", "")
                        },
                        "detail": item.get("image_url", {}).get("detail", "auto")
                    })
            
            codex_request["input"].append({
                "type": "message",
                "role": role,
                "content": content_items
            })
        
        # Handle tool calls in assistant messages
        if msg.get("tool_calls"):
            for tool_call in msg["tool_calls"]:
                codex_request["input"].append({
                    "type": "function_call",
                    "call_id": tool_call.get("id", ""),
                    "name": tool_call.get("function", {}).get("name", ""),
                    "arguments": tool_call.get("function", {}).get("arguments", "{}")
                })
        
        # Handle tool responses
        if msg.get("role") == "tool":
            codex_request["input"].append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id", ""),
                "output": {
                    "type": "text",
                    "text": msg.get("content", "")
                }
            })
    
    # Convert tools
    if "tools" in openai_request:
        for tool in openai_request["tools"]:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                codex_request["tools"].append({
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {})
                })
    
    return codex_request
```

### 13.2 Usage Example

```python
# OpenAI format request
openai_request = {
    "model": "gpt-4",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"}
    ],
    "temperature": 0.7,  # Will be ignored
    "max_tokens": 100,   # Will be ignored
    "stream": True
}

# Convert to Codex format
codex_request = convert_openai_to_codex(openai_request)

# Send to ChatGPT backend
response = requests.post(
    "https://chatgpt.com/backend-api/v1/responses",
    headers=headers,
    json=codex_request,
    stream=True
)
```

---

## 14. Summary of Request Fields

### 14.1 Required Fields

- `model` - Model identifier (e.g., "gpt-4")
- `input` - Array of ResponseItem objects
- `tools` - Array of tool definitions (can be empty)
- `tool_choice` - Tool selection mode ("auto", "none", or specific tool)
- `parallel_tool_calls` - Boolean for parallel execution
- `store` - Boolean for storing conversation
- `stream` - Boolean for streaming responses

### 14.2 Optional Fields

- `instructions` - System prompt (empty string if not provided)
- `reasoning` - Reasoning controls (effort and summary)
- `include` - Array of fields to include (e.g., reasoning content)
- `service_tier` - Priority routing ("default", "priority", or null)
- `prompt_cache_key` - Cache key for prompt caching
- `text` - Text controls (verbosity and format)
- `client_metadata` - Metadata for telemetry

### 14.3 Field Value Constraints

**model:**
- Must be a valid model identifier
- Examples: "gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"

**tool_choice:**
- `"auto"` - Model decides when to use tools
- `"none"` - Never use tools
- `{"type": "function", "name": "tool_name"}` - Force specific tool

**parallel_tool_calls:**
- `true` - Allow multiple tool calls in parallel
- `false` - Execute tools sequentially

**store:**
- `false` - Don't store (typical for Codex)
- `true` - Store conversation

**stream:**
- `true` - Stream responses via SSE
- `false` - Return complete response

This completes the comprehensive documentation of the ChatGPT/Codex API request format with detailed examples and conversion guidance.
