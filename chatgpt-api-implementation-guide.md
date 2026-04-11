# ChatGPT API Implementation Guide for Codex-CLI

This document provides a comprehensive analysis of how codex-cli communicates with ChatGPT API endpoints, including exact endpoints, headers, authentication, request schemas, and implementation details.

## Table of Contents

1. [Overview](#overview)
2. [API Endpoints](#api-endpoints)
3. [Authentication](#authentication)
4. [Request Headers](#request-headers)
5. [Request/Response Schemas](#requestresponse-schemas)
6. [Model List Retrieval](#model-list-retrieval)
7. [Streaming Responses](#streaming-responses)
8. [WebSocket Support](#websocket-support)
9. [Message Conversion Between OpenAI and Codex Formats](#message-conversion-between-openai-and-codex-formats)
10. [Python Implementation Examples](#python-implementation-examples)
11. [Implementation Examples (Rust)](#implementation-examples-rust)
12. [Developer Role Messages](#developer-role-messages)
13. [Session Flow](#session-flow)

---

## Overview

Codex-CLI uses OpenAI's **Responses API** (not the Chat Completions API) to communicate with ChatGPT. The primary endpoints are:

- **Base URL (ChatGPT mode)**: `https://chatgpt.com/backend-api/codex`
- **Base URL (API Key mode)**: `https://api.openai.com/v1`

The client supports both HTTP/SSE and WebSocket transports for streaming responses.

---

## API Endpoints

### Primary Endpoints

#### 1. Responses Endpoint (Streaming)
- **Path**: `/v1/responses` (or `/responses` relative to base)
- **Method**: `POST`
- **Purpose**: Stream AI responses for a given prompt
- **Transport**: HTTP with Server-Sent Events (SSE) or WebSocket

#### 2. Models Endpoint
- **Path**: `/v1/models` (or `/models` relative to base)
- **Method**: `GET`
- **Purpose**: Retrieve available models and their capabilities
- **Query Parameters**: `client_version=<version>` (e.g., `0.99.0`)

#### 3. Compact Endpoint
- **Path**: `/v1/responses/compact` (or `/responses/compact` relative to base)
- **Method**: `POST`
- **Purpose**: Compact conversation history

#### 4. Memory Summarization Endpoint
- **Path**: `/v1/memories/trace_summarize` (or `/memories/trace_summarize` relative to base)
- **Method**: `POST`
- **Purpose**: Summarize memory traces

### ChatGPT-Specific Backend Endpoints (OAuth Mode)

When using ChatGPT authentication, additional endpoints are available:

#### 5. Config Requirements
- **Path**: `/backend-api/wham/config/requirements`
- **Method**: `GET`
- **Purpose**: Retrieve cloud configuration requirements

#### 6. Rate Limits
- **Path**: `/backend-api/api/codex/usage`
- **Method**: `GET`
- **Purpose**: Get account rate limits

#### 7. Plugin/App Management
- **Path**: `/backend-api/plugins/list`
- **Method**: `GET`
- **Purpose**: List installed plugins

- **Path**: `/backend-api/plugins/featured`
- **Method**: `GET`
- **Query Parameters**: `platform=codex`
- **Purpose**: Get featured plugins

- **Path**: `/backend-api/plugins/{plugin_id}/enable`
- **Method**: `POST`
- **Purpose**: Enable a plugin

- **Path**: `/backend-api/plugins/{plugin_id}/uninstall`
- **Method**: `POST`
- **Purpose**: Uninstall a plugin

#### 8. MCP Apps
- **Path**: `/backend-api/wham/apps`
- **Method**: WebSocket connection
- **Purpose**: MCP (Model Context Protocol) server communication

**Important Note**: When using ChatGPT OAuth authentication, the base instructions field in the request is **required** and should reference "Codex" specifically. The example from the blog post shows:

```json
{
  "instructions": "You are Codex, based on GPT-5. You are running as a coding agent ..."
}
```

This appears to be a requirement for the ChatGPT backend API to accept requests properly.

---

## Authentication

### Two Authentication Modes

#### 1. API Key Mode
- **Header**: `Authorization: Bearer <api_key>`
- **Source**: Environment variable (typically `OPENAI_API_KEY`)
- **Base URL**: `https://api.openai.com/v1`

#### 2. ChatGPT Mode (OAuth2)
- **Header**: `Authorization: Bearer <access_token>`
- **Additional Header**: `ChatGPT-Account-ID: <account_id>`
- **Base URL**: `https://chatgpt.com/backend-api/codex`
- **Token Management**: Automatic refresh on 401 responses

### Authentication Implementation

The authentication is handled through the `AuthProvider` trait:

```rust
pub trait AuthProvider: Send + Sync {
    fn bearer_token(&self) -> Option<String>;
    fn account_id(&self) -> Option<String> {
        None
    }
}
```

Headers are added via:

```rust
pub(crate) fn add_auth_headers_to_header_map<A: AuthProvider>(auth: &A, headers: &mut HeaderMap) {
    if let Some(token) = auth.bearer_token()
        && let Ok(header) = HeaderValue::from_str(&format!("Bearer {token}"))
    {
        let _ = headers.insert(http::header::AUTHORIZATION, header);
    }
    if let Some(account_id) = auth.account_id()
        && let Ok(header) = HeaderValue::from_str(&account_id)
    {
        let _ = headers.insert("ChatGPT-Account-ID", header);
    }
}
```

**Location**: `codex-rs/codex-api/src/auth.rs`

---

## Request Headers

### Standard Headers (All Requests)

1. **User-Agent**
   - Format: `{originator}/{version} ({os} {os_version}; {arch}) {terminal_type} ({suffix})`
   - Example: `codex_cli_rs/0.99.0 (Linux 6.12; x86_64) xterm-256color (vscode; 1.86.0)`
   - **Location**: `codex-rs/login/src/auth/default_client.rs:131-155`

2. **originator**
   - Value: `codex_cli_rs` (default) or custom via `CODEX_INTERNAL_ORIGINATOR_OVERRIDE`
   - Purpose: Identifies the client application

3. **Content-Type**
   - Value: `application/json` (for POST requests)

4. **Accept**
   - Value: `text/event-stream` (for SSE streaming)

### Responses API Specific Headers

5. **x-client-request-id**
   - Value: Thread/conversation ID
   - Purpose: Request correlation

6. **session_id**
   - Value: Thread/conversation ID
   - Purpose: Session tracking

7. **x-codex-turn-state**
   - Value: Sticky routing token from previous response
   - Purpose: Maintain routing to same backend instance within a turn

8. **x-codex-turn-metadata**
   - Value: Optional turn metadata (JSON)
   - Purpose: Observability and debugging

9. **x-codex-window-id**
   - Format: `{conversation_id}:{window_generation}`
   - Purpose: Window/context tracking

10. **x-openai-subagent**
    - Values: `review`, `compact`, `memory_consolidation`, `collab_spawn`
    - Purpose: Identify subagent requests

11. **x-codex-parent-thread-id**
    - Value: Parent thread ID (for spawned threads)
    - Purpose: Thread hierarchy tracking

12. **x-codex-beta-features**
    - Value: Comma-separated beta feature keys
    - Purpose: Enable experimental features

13. **x-responsesapi-include-timing-metrics**
    - Value: `true`
    - Purpose: Request timing metrics in response

### WebSocket Specific Headers

14. **OpenAI-Beta**
    - Value: `responses_websockets=2026-02-06`
    - Purpose: Enable WebSocket protocol version

### Developer Role Messages

When using the ChatGPT OAuth API, requests often include a `developer` role message in the input array. This is distinct from the `instructions` field:

- **`instructions` field**: Base system instructions (e.g., "You are Codex, based on GPT-5...")
- **`developer` role message**: Additional contextual instructions injected as a message in the conversation

Example from the blog post:
```json
{
  "input": [
    {
      "type": "message",
      "role": "developer",
      "content": [
        {
          "type": "input_text",
          "text": "You are a helpful assistant. Respond directly to the user request without running tools or shell commands."
        }
      ]
    },
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Generate an SVG of a pelican riding a bicycle"
        }
      ]
    }
  ]
}
```

The `developer` role is used for:
- Permission instructions (sandbox mode, approval policies)
- Capability instructions (available tools, restrictions)
- Context-specific guidance (collaboration mode, personality specs)
- Model switching notifications
- Realtime conversation boundaries

**Location**: `codex-rs/protocol/src/models.rs:755-767`

### Optional Headers

15. **OpenAI-Organization**
    - Source: `OPENAI_ORGANIZATION` environment variable
    - Purpose: Organization routing

16. **OpenAI-Project**
    - Source: `OPENAI_PROJECT` environment variable
    - Purpose: Project routing

17. **version**
    - Value: Package version (e.g., `0.99.0`)
    - Purpose: Client version tracking

### Request Compression

When using ChatGPT authentication with OpenAI provider:
- **Content-Encoding**: `zstd`
- Body is compressed using Zstandard algorithm

**Location**: `codex-rs/core/src/client.rs:1040-1049`

---

## Request/Response Schemas

### Responses API Request Schema

```json
{
  "model": "gpt-4",
  "instructions": "You are a helpful assistant...",
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
  "prompt_cache_key": "<conversation_id>",
  "text": {
    "type": "text",
    "verbosity": "normal"
  }
}
```

**Key Fields**:
- `model`: Model identifier (e.g., `gpt-4`, `o1-preview`)
- `instructions`: System instructions/base prompt
- `input`: Array of conversation items (messages, tool calls, tool results)
- `tools`: Available tools in JSON Schema format
- `reasoning`: Reasoning configuration (effort level, summary mode)
- `store`: Whether to store in Azure (provider-specific)
- `stream`: Always `true` for streaming
- `include`: Additional fields to include in response
- `service_tier`: Priority level (`default`, `priority`, `flex`)
- `prompt_cache_key`: Cache key for prompt caching
- `text`: Text generation parameters (verbosity, output schema)

**Location**: `codex-rs/codex-api/src/endpoint/responses.rs`

### Response Stream Events (SSE)

The server sends Server-Sent Events with the following event types:

1. **response.created**
   ```json
   event: response.created
   data: {"response_id": "resp_123", "status": "in_progress"}
   ```

2. **response.output_item.added**
   ```json
   event: response.output_item.added
   data: {"item": {"type": "message", "role": "assistant", "content": []}}
   ```

3. **response.content_part.added**
   ```json
   event: response.content_part.added
   data: {"part": {"type": "text", "text": ""}}
   ```

4. **response.content_part.delta**
   ```json
   event: response.content_part.delta
   data: {"delta": {"text": "Hello"}}
   ```

5. **response.output_item.done**
   ```json
   event: response.output_item.done
   data: {"item": {"type": "message", "role": "assistant", "content": [...]}}
   ```

6. **response.done**
   ```json
   event: response.done
   data: {
     "response_id": "resp_123",
     "usage": {
       "input_tokens": 100,
       "output_tokens": 50,
       "total_tokens": 150,
       "cached_input_tokens": 0,
       "reasoning_output_tokens": 0
     }
   }
   ```

7. **error**
   ```json
   event: error
   data: {"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded"}}
   ```

**Location**: Event parsing in `codex-rs/codex-api/src/sse.rs`

### Models Response Schema

```json
{
  "models": [
    {
      "slug": "gpt-4",
      "display_name": "GPT-4",
      "description": "Most capable model",
      "default_reasoning_level": "medium",
      "supported_reasoning_levels": [
        {"effort": "low", "description": "Fast"},
        {"effort": "medium", "description": "Balanced"},
        {"effort": "high", "description": "Thorough"}
      ],
      "shell_type": "shell_command",
      "visibility": "list",
      "minimal_client_version": [0, 99, 0],
      "supported_in_api": true,
      "priority": 1,
      "upgrade": null,
      "base_instructions": "You are a helpful assistant",
      "supports_reasoning_summaries": true,
      "support_verbosity": true,
      "default_verbosity": "normal",
      "apply_patch_tool_type": "unified_diff",
      "truncation_policy": {"mode": "bytes", "limit": 100000},
      "supports_parallel_tool_calls": true,
      "supports_image_detail_original": true,
      "context_window": 128000,
      "experimental_supported_tools": []
    }
  ]
}
```

**Location**: `codex-rs/codex-api/src/endpoint/models.rs`

---

## Model List Retrieval

### Request Details

**Endpoint**: `GET /v1/models?client_version=<version>`

**Headers**:
- `Authorization: Bearer <token>`
- `ChatGPT-Account-ID: <account_id>` (if ChatGPT mode)
- `User-Agent: <codex_user_agent>`
- `originator: <originator>`

**Query Parameters**:
- `client_version`: Client version string (e.g., `0.99.0`)

### Response Handling

The response includes an `ETag` header for caching:

```rust
let header_etag = resp
    .headers
    .get(ETAG)
    .and_then(|value| value.to_str().ok())
    .map(ToString::to_string);
```

**Location**: `codex-rs/codex-api/src/endpoint/models.rs:58-62`

### Model Selection

Models are filtered based on:
1. `visibility`: Must be `"list"` to appear in UI
2. `minimal_client_version`: Client version must meet minimum
3. `supported_in_api`: Must be `true` for API usage

---

## Streaming Responses

### HTTP/SSE Transport

1. **Connection Setup**
   - POST request to `/v1/responses`
   - `Accept: text/event-stream` header
   - Optional `Content-Encoding: zstd` for compression

2. **Event Stream Processing**
   - Parse SSE events line-by-line
   - Handle `event:` and `data:` lines
   - Reconstruct JSON from multi-line data
   - Parse event-specific payloads

3. **Idle Timeout**
   - Default: 300 seconds (5 minutes)
   - Configurable via `stream_idle_timeout_ms`
   - Connection reset if no data received within timeout

4. **Retry Logic**
   - Default max retries: 5 attempts
   - Exponential backoff: 200ms base delay
   - Retry on: 5xx errors, transport errors
   - No retry on: 429 (rate limit), 401 (unauthorized)

**Location**: `codex-rs/codex-api/src/sse.rs`

### WebSocket Transport

1. **Connection Handshake**
   - Upgrade HTTP connection to WebSocket
   - URL: `wss://chatgpt.com/backend-api/codex/responses`
   - Headers: Same as HTTP plus `OpenAI-Beta: responses_websockets=2026-02-06`

2. **Request Format**
   ```json
   {
     "type": "response.create",
     "response": {
       "model": "gpt-4",
       "instructions": "...",
       "input": [...],
       "client_metadata": {
         "x-codex-window-id": "...",
         "x-openai-subagent": "...",
         "x-codex-parent-thread-id": "...",
         "x-codex-turn-metadata": "..."
       }
     }
   }
   ```

3. **Incremental Requests**
   - Reuse WebSocket connection for multiple requests
   - Send only delta items with `previous_response_id`
   - Server maintains conversation state

4. **Connection Reuse**
   - Connection cached per turn
   - Reused across multiple requests in same turn
   - Reset on window generation change

5. **Fallback to HTTP**
   - On `426 Upgrade Required` response
   - On connection timeout (15 seconds default)
   - On WebSocket errors

**Location**: `codex-rs/codex-api/src/websocket.rs`

---

## Message Conversion Between OpenAI and Codex Formats

### Overview

Codex uses the OpenAI Responses API format which is more structured than the traditional Chat Completions API. Understanding how to convert between standard OpenAI message formats and Codex's internal format is essential for implementing compatible clients.

### Key Type Definitions

#### Codex Internal Types (`ResponseInputItem` and `ResponseItem`)

Codex uses two main types for messages:

1. **`ResponseInputItem`** - Messages sent TO the API
2. **`ResponseItem`** - Messages received FROM the API

```rust
// From codex-rs/protocol/src/models.rs

// Input items (sent to API)
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ResponseInputItem {
    Message {
        role: String,
        content: Vec<ContentItem>,
    },
    FunctionCallOutput {
        call_id: String,
        output: FunctionCallOutputPayload,
    },
    McpToolCallOutput {
        call_id: String,
        output: CallToolResult,
    },
    CustomToolCallOutput {
        call_id: String,
        name: Option<String>,
        output: FunctionCallOutputPayload,
    },
    ToolSearchOutput {
        call_id: String,
        status: String,
        execution: String,
        tools: Vec<serde_json::Value>,
    },
}

// Output items (received from API)
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ResponseItem {
    Message { id: Option<String>, role: String, content: Vec<ContentItem>, ... },
    Reasoning { id: String, summary: Vec<ReasoningItemReasoningSummary>, ... },
    FunctionCall { id: Option<String>, name: String, arguments: String, call_id: String, ... },
    CustomToolCall { id: Option<String>, status: Option<String>, call_id: String, name: String, ... },
    // ... and more
}

// Content items within messages
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentItem {
    InputText { text: String },
    InputImage { image_url: String },
    OutputText { text: String },
}
```

**Location**: `codex-rs/protocol/src/models.rs:119-159`

### Converting User Input to Codex Format

#### Simple Text Messages

**Standard OpenAI format:**
```json
{
  "messages": [
    {"role": "user", "content": "Hello, how are you?"}
  ]
}
```

**Codex format:**
```json
{
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {"type": "input_text", "text": "Hello, how are you?"}
      ]
    }
  ]
}
```

**Conversion logic:**
```rust
// From codex-rs/protocol/src/models.rs:1015-1053
impl From<Vec<UserInput>> for ResponseInputItem {
    fn from(items: Vec<UserInput>) -> Self {
        Self::Message {
            role: "user".to_string(),
            content: items
                .into_iter()
                .flat_map(|c| match c {
                    UserInput::Text { text, .. } => {
                        vec![ContentItem::InputText { text }]
                    }
                    // ... handle images, local images, etc.
                })
                .collect(),
        }
    }
}
```

#### Messages with Images

**Standard OpenAI format:**
```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "What's in this image?"},
        {
          "type": "image_url",
          "image_url": {"url": "data:image/png;base64,..."}
        }
      ]
    }
  ]
}
```

**Codex format (with image tags):**
```json
{
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {"type": "input_text", "text": "<image>"},
        {"type": "input_image", "image_url": "data:image/png;base64,..."},
        {"type": "input_text", "text": "</image>What's in this image?"}
      ]
    }
  ]
}
```

**Image tagging rules:**
- Remote images: wrapped with `<image>` and `</image>` tags
- Local images: wrapped with `<image name=[Image #N]>` and `</image>` tags
- Multiple images share a sequential label counter

**Location**: `codex-rs/protocol/src/models.rs:867-906`

### Converting Tool Calls/Function Calls

#### Tool Call Request (Model → API)

**Codex receives from model:**
```rust
// From codex-rs/protocol/src/models.rs:227-240
ResponseItem::FunctionCall {
    name: "shell",
    arguments: "{\"command\": [\"ls\"]}",
    call_id: "call_123",
    namespace: Some("mcp"),
}
```

**Wire format (Responses API):**
```json
{
  "type": "function_call",
  "name": "shell",
  "arguments": "{\"command\": [\"ls\"]}",
  "call_id": "call_123"
}
```

#### Tool Result Response (API → Model)

**Codex sends back to API:**
```rust
ResponseInputItem::FunctionCallOutput {
    call_id: "call_123".to_string(),
    output: FunctionCallOutputPayload {
        body: FunctionCallOutputBody::Text("total 0".to_string()),
        success: Some(true),
    },
}
```

**Wire format:**
```json
{
  "type": "function_call_output",
  "call_id": "call_123",
  "output": "total 0"
}
```

Or for multimodal tool outputs:
```json
{
  "type": "function_call_output",
  "call_id": "call_123",
  "output": [
    {"type": "input_text", "text": "File listing:"},
    {"type": "input_image", "image_url": "data:image/png;base64,..."}
  ]
}
```

**Location**: `codex-rs/protocol/src/models.rs:1180-1288`

### Tool Definition Format

**Codex tool format (JSON Schema):**
```rust
// Tools are passed to the Responses API in OpenAI function format
{
  "type": "function",
  "name": "shell",
  "description": "Execute a shell command",
  "parameters": {
    "type": "object",
    "properties": {
      "command": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Command as array of strings"
      },
      "workdir": {
        "type": "string",
        "description": "Working directory"
      }
    },
    "required": ["command"]
  }
}
```

**Location**: `codex-rs/codex-tools/src/lib.rs`

### Streaming Message Handling

#### SSE Events to ResponseItem Conversion

The Responses API streams events that must be assembled into `ResponseItem` objects:

```rust
// From codex-rs/codex-api/src/sse.rs

// Event sequence:
// 1. response.created - Start of response
// 2. response.output_item.added - New item created
// 3. response.content_part.added - Content started
// 4. response.content_part.delta - Incremental content
// 5. response.output_item.done - Item complete
// 6. response.done - All done

// Each event type maps to internal types:
// - response.output_item.added (type=message) -> ResponseItem::Message
// - response.output_item.added (type=function_call) -> ResponseItem::FunctionCall
// - response.output_item.added (type=reasoning) -> ResponseItem::Reasoning
```

**Location**: `codex-rs/codex-api/src/sse.rs`

#### Converting Streaming Deltas to Codex Format

```rust
// Incremental text delta
{
  "event": "response.content_part.delta",
  "data": {
    "delta": {"text": "Hello"}
  }
}

// Becomes:
ResponseItem::Message {
    content: vec![ContentItem::OutputText { text: "Hello" }],
    // ...
}
```

### Complete Conversion Flow

#### Non-Streaming Request Flow

1. **User Input → Codex Input:**
   ```rust
   // User input (text, images, etc.)
   let user_input = vec![UserInput::Text { text: "Hello".to_string() }];
   
   // Convert to ResponseInputItem
   let input_item: ResponseInputItem = user_input.into();
   // Results in: ResponseInputItem::Message { role: "user", content: [...] }
   ```

2. **Build Request:**
   ```rust
   // From codex-rs/core/src/client.rs:749-815
   let request = ResponsesApiRequest {
       model: "gpt-4".to_string(),
       instructions: base_instructions.text,
       input: vec![input_item],  // ResponseInputItem array
       tools: create_tools_json(tools)?,
       // ... other fields
   };
   ```

3. **Response → ResponseItem:**
   ```rust
   // Parse JSON response into ResponseItem
   let response_item: ResponseItem = serde_json::from_value(response_json)?;
   // Handle Message, FunctionCall, Reasoning, etc.
   ```

#### Streaming Request Flow

1. **Send Request** (same as non-streaming)
2. **Process SSE Events:**
   ```rust
   // From codex-rs/core/src/client.rs:1496-1576
   while let Some(event) = stream.next().await {
       match event {
           Ok(ResponseEvent::OutputItemDone(item)) => {
               // Item is complete, convert to ResponseItem
               items_added.push(item);
           }
           Ok(ResponseEvent::ContentPartDelta { delta }) => {
               // Accumulate incremental text
           }
           Ok(ResponseEvent::Completed { response_id, usage }) => {
               // Final response with usage stats
           }
       }
   }
   ```

3. **Reconstruct Full Message:**
   ```rust
   // Multiple deltas are assembled into complete ResponseItem
   // e.g., multiple response.content_part.delta events -> complete message
   ```

### WebSocket Message Format

For WebSocket transport, messages use a different structure:

```rust
// From codex-rs/codex-api/src/websocket.rs

// Request (WebSocket)
{
  "type": "response.create",
  "response": {
    "model": "gpt-4",
    "instructions": "...",
    "input": [...],
    "client_metadata": {
      "x-codex-window-id": "...",
      "x-openai-subagent": "..."
    }
  }
}

// Incremental request (subsequent requests in same turn)
{
  "type": "response.create",
  "previous_response_id": "resp_123",
  "input": [...],  // Only new items, not full history
  "response": { ... }
}
```

**Location**: `codex-rs/codex-api/src/websocket.rs`

### Summary: Key Conversion Points

| Aspect | OpenAI Standard | Codex Internal |
|--------|----------------|----------------|
| Messages field | `messages` | `input` |
| Message structure | `{role, content}` | `{type: message, role, content[]}` |
| Content structure | `{type, text}` or `{type, image_url}` | `{type: input_text/input_image/output_text}` |
| Tool calls | `tool_calls` array | `ResponseItem::FunctionCall` |
| Tool results | `function_call_output` (string) | `FunctionCallOutputPayload` (string or array) |
| Images | Simple array | Wrapped with `<image>` tags |
| Streaming | SSE with deltas | Assembled into complete `ResponseItem` |

### Important Implementation Notes

1. **Content Array**: Messages always have a `content` array, even for single text
2. **Type Tags**: All items use snake_case type tags (`message`, `function_call`, `input_text`)
3. **Image Handling**: Images require special tagging with `<image>` and `</image>`
4. **Tool Output**: Can be plain text OR array of content items for multimodal
5. **Namespace**: MCP tools include `namespace` field; built-in tools don't

---

## WebSocket Support

### Prewarm/Preconnect

Before sending the first request, the client can establish a WebSocket connection:

```rust
pub async fn preconnect_websocket(
    &mut self,
    session_telemetry: &SessionTelemetry,
    _model_info: &ModelInfo,
) -> std::result::Result<(), ApiError>
```

This reduces latency for the first actual request.

### Warmup Request

A special request with `generate: false` to establish connection without generating output:

```json
{
  "type": "response.create",
  "response": {
    "model": "gpt-4",
    "generate": false,
    ...
  }
}
```

The client waits for completion before sending the actual request.

**Location**: `codex-rs/core/src/client.rs:1303-1351`

---

## Implementation Examples

### Example 1: Basic Request (HTTP/SSE)

```rust
use codex_api::{ResponsesClient, ResponsesApiRequest, ResponsesOptions};
use codex_api::requests::responses::Compression;

// Setup
let transport = ReqwestTransport::new(build_reqwest_client());
let provider = Provider {
    name: "OpenAI".to_string(),
    base_url: "https://api.openai.com/v1".to_string(),
    query_params: None,
    headers: HeaderMap::new(),
    retry: RetryConfig { /* ... */ },
    stream_idle_timeout: Duration::from_secs(300),
};
let auth = /* implement AuthProvider */;

let client = ResponsesClient::new(transport, provider, auth);

// Build request
let request = ResponsesApiRequest {
    model: "gpt-4".to_string(),
    instructions: "You are a helpful assistant".to_string(),
    input: vec![/* conversation items */],
    tools: vec![],
    tool_choice: "auto".to_string(),
    parallel_tool_calls: true,
    reasoning: None,
    store: false,
    stream: true,
    include: vec![],
    service_tier: None,
    prompt_cache_key: Some("conversation_123".to_string()),
    text: None,
};

let options = ResponsesOptions {
    conversation_id: Some("conversation_123".to_string()),
    session_source: None,
    extra_headers: HeaderMap::new(),
    compression: Compression::None,
    turn_state: None,
};

// Stream response
let mut stream = client.stream_request(request, options).await?;
while let Some(event) = stream.next().await {
    match event {
        Ok(ResponseEvent::ContentPartDelta { delta }) => {
            print!("{}", delta.text);
        }
        Ok(ResponseEvent::Completed { response_id, token_usage }) => {
            println!("\nCompleted: {}", response_id);
        }
        Err(e) => {
            eprintln!("Error: {}", e);
            break;
        }
        _ => {}
    }
}
```

### Example 2: Retrieve Models

```rust
use codex_api::{ModelsClient, Provider};

let transport = ReqwestTransport::new(build_reqwest_client());
let provider = Provider { /* ... */ };
let auth = /* implement AuthProvider */;

let client = ModelsClient::new(transport, provider, auth);

let (models, etag) = client
    .list_models("0.99.0", HeaderMap::new())
    .await?;

for model in models {
    println!("{}: {}", model.slug, model.display_name);
}
```

### Example 3: WebSocket Request

```rust
use codex_api::{ResponsesWebsocketClient, ResponseCreateWsRequest};

let provider = Provider { /* ... */ };
let auth = /* implement AuthProvider */;

let ws_client = ResponsesWebsocketClient::new(provider, auth);

// Connect
let mut connection = ws_client
    .connect(headers, default_headers, turn_state, telemetry)
    .await?;

// Send request
let request = ResponsesWsRequest::ResponseCreate(ResponseCreateWsRequest {
    model: "gpt-4".to_string(),
    instructions: "You are a helpful assistant".to_string(),
    input: vec![/* items */],
    client_metadata: HashMap::new(),
    /* ... */
});

let mut stream = connection.stream_request(request, false).await?;

// Process events
while let Some(event) = stream.next().await {
    // Handle events
}
```

### Example 4: Authentication Headers

```rust
// API Key Mode
struct ApiKeyAuth {
    api_key: String,
}

impl AuthProvider for ApiKeyAuth {
    fn bearer_token(&self) -> Option<String> {
        Some(self.api_key.clone())
    }
}

// ChatGPT Mode
struct ChatGptAuth {
    access_token: String,
    account_id: String,
}

impl AuthProvider for ChatGptAuth {
    fn bearer_token(&self) -> Option<String> {
        Some(self.access_token.clone())
    }
    
    fn account_id(&self) -> Option<String> {
        Some(self.account_id.clone())
    }
}
```

### Example 5: User-Agent Construction

```rust
pub fn get_codex_user_agent() -> String {
    let build_version = env!("CARGO_PKG_VERSION");
    let os_info = os_info::get();
    let originator = originator();
    let prefix = format!(
        "{}/{build_version} ({} {}; {}) {}",
        originator.value.as_str(),
        os_info.os_type(),
        os_info.version(),
        os_info.architecture().unwrap_or("unknown"),
        user_agent() // terminal detection
    );
    let suffix = USER_AGENT_SUFFIX
        .lock()
        .ok()
        .and_then(|guard| guard.clone());
    let suffix = suffix
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map_or_else(String::new, |value| format!(" ({value})"));

    format!("{prefix}{suffix}")
}
```

**Result**: `codex_cli_rs/0.99.0 (Linux 6.12; x86_64) xterm-256color (vscode; 1.86.0)`

---

## Key Implementation Details

### 1. Base URL Selection

```rust
pub fn to_api_provider(&self, auth_mode: Option<AuthMode>) -> CodexResult<ApiProvider> {
    let default_base_url = if matches!(auth_mode, Some(AuthMode::Chatgpt)) {
        "https://chatgpt.com/backend-api/codex"
    } else {
        "https://api.openai.com/v1"
    };
    let base_url = self
        .base_url
        .clone()
        .unwrap_or_else(|| default_base_url.to_string());
    // ...
}
```

**Location**: `codex-rs/model-provider-info/src/lib.rs:184-193`

### 2. Request Compression

```rust
fn responses_request_compression(&self, auth: Option<&CodexAuth>) -> Compression {
    if self.client.state.enable_request_compression
        && auth.is_some_and(CodexAuth::is_chatgpt_auth)
        && self.client.state.provider.is_openai()
    {
        Compression::Zstd
    } else {
        Compression::None
    }
}
```

**Location**: `codex-rs/core/src/client.rs:1040-1049`

### 3. Retry Logic

```rust
pub struct RetryConfig {
    pub max_attempts: u64,
    pub base_delay: Duration,
    pub retry_429: bool,
    pub retry_5xx: bool,
    pub retry_transport: bool,
}
```

Default values:
- `max_attempts`: 4 (requests), 5 (streams)
- `base_delay`: 200ms
- `retry_429`: false
- `retry_5xx`: true
- `retry_transport`: true

**Location**: `codex-rs/codex-api/src/provider.rs:16-22`

### 4. Sticky Routing (Turn State)

```rust
/// Turn state for sticky routing.
///
/// This is an `OnceLock` that stores the turn state value received from the server
/// on turn start via the `x-codex-turn-state` response header. Once set, this value
/// should be sent back to the server in the `x-codex-turn-state` request header for
/// all subsequent requests within the same turn to maintain sticky routing.
turn_state: Arc<OnceLock<String>>,
```

**Location**: `codex-rs/core/src/client.rs:209-219`

### 5. Session vs Turn Scope

- **Session-scoped**: `ModelClient` - lives for entire conversation
- **Turn-scoped**: `ModelClientSession` - created per turn, manages WebSocket connection

```rust
pub fn new_session(&self) -> ModelClientSession {
    ModelClientSession {
        client: self.clone(),
        websocket_session: self.take_cached_websocket_session(),
        turn_state: Arc::new(OnceLock::new()),
    }
}
```

**Location**: `codex-rs/core/src/client.rs:300-306`

---

## Session Flow

### Overview of a Complete Session

A session represents an entire conversation from start to finish. Understanding the flow of requests and how conversation state is maintained is essential for implementing a compatible client.

### Lifecycle of a Session

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SESSION LIFETIME                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Initialization                                                          │
│     ├── Load/validate authentication credentials                           │
│     ├── Fetch available models from /v1/models                            │
│     └── Create ModelClient (session-scoped)                               │
│                                                                             │
│  2. Turn 1: User Input → First Response                                   │
│     ├── Create ModelClientSession (turn-scoped)                          │
│     ├── Preconnect WebSocket (optional, recommended)                  │
│     ├── Build request with base instructions                             │
│     ├── Send user message in input array                                 │
│     ├── Receive streaming response (SSE events)                        │
│     └── Extract response items, tool calls                               │
│                                                                             │
│  3. Tool Execution Loop (within Turn N)                                   │
│     ├── API emits FunctionCall item                                      │
│     ├── Client executes tool locally                                     │
│     ├── Send FunctionCallOutput back in next request                    │
│     └── Continue receiving response (may loop)                          │
│                                                                             │
│  4. Turn N: Subsequent Requests                                           │
│     ├── Build request with previous_response_id                         │
│     ├── Include all tool call results since turn start                  │
│     ├── Optionally compact conversation history                         │
│     └── Receive updated conversation state                               │
│                                                                             │
│  5. Session End                                                           │
│     ├── Final response received                                          │
│     ├── Close WebSocket connection                                      │
│     └── Session cleanup                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Detailed Turn Flow

#### Turn 1: Initial Request

```rust
// 1. Create session (turn-scoped)
let session = client.new_session();

// 2. Optionally preconnect WebSocket for lower latency
session.preconnect_websocket(telemetry, &model_info).await?;

// 3. Build first request
let request = ResponsesApiRequest {
    model: "gpt-4".to_string(),
    instructions: base_instructions.text,  // Required for ChatGPT mode
    input: vec![
        // Developer message (optional, for system context)
        ResponseInputItem::Message {
            role: "developer".to_string(),
            content: vec![ContentItem::InputText {
                text: permissions_instructions
            }],
        },
        // User message
        ResponseInputItem::Message {
            role: "user".to_string(),
            content: vec![ContentItem::InputText {
                text: user_input.clone()
            }],
        },
    ],
    tools: create_tools_json(tools)?,
    // ...other fields
};

// 4. Send request and process streaming response
let mut stream = session.stream_request(request, options).await?;

while let Some(event) = stream.next().await {
    match event {
        Ok(ResponseEvent::OutputItemAdded { item }) => {
            // New item created - could be Message, FunctionCall, Reasoning
            match item {
                ResponseItem::FunctionCall { name, arguments, call_id, .. } => {
                    // Tool call to execute
                    tool_calls_to_execute.push((call_id, name, arguments));
                }
                ResponseItem::Message { content, .. } => {
                    // Text response
                }
                _ => {}
            }
        }
        Ok(ResponseEvent::ContentPartDelta { delta }) => {
            // Accumulate incremental text
        }
        Ok(ResponseEvent::Completed { response_id, usage }) => {
            // Turn complete
        }
        Err(e) => { /* Handle error */ }
    }
}
```

**Location**: `codex-rs/core/src/client.rs:1303-1576`

#### Subsequent Turns: Tool Execution Loop

```rust
// After receiving a FunctionCall, execute the tool and send results back

// 1. Execute tool (shell command, file operation, etc.)
let tool_result = execute_tool(&tool_name, tool_args).await?;

// 2. Send tool result back to API
let next_request = ResponsesApiRequest {
    model: "gpt-4".to_string(),
    instructions: base_instructions.text,
    input: vec![
        // Include original user message
        user_message.clone(),
        // Include the assistant's function call
        ResponseItem::FunctionCall { ... }.into(),
        // Send tool result
        ResponseInputItem::FunctionCallOutput {
            call_id: tool_call.call_id,
            output: FunctionCallOutputPayload {
                body: FunctionCallOutputBody::Text(tool_result),
                success: Some(true),
            },
        },
    ],
    // ...
};
```

**Location**: `codex-rs/protocol/src/models.rs:1180-1288`

### Conversation State Management

#### Maintaining Conversation History

Codex maintains conversation state across requests within a turn. This is handled in two ways:

1. **HTTP/SSE**: Full `input` array sent with each request
2. **WebSocket**: Server maintains state, client sends `previous_response_id`

```rust
// For HTTP: Include full conversation history
let input_items: Vec<ResponseInputItem> = conversation
    .items()
    .iter()
    .flat_map(|item| item.to_input_item())
    .collect();

let request = ResponsesApiRequest {
    // ...
    input: input_items,
    // ...
};

// For WebSocket: Only send new items + previous_response_id
let request = ResponseCreateWsRequest {
    previous_response_id: last_response_id,  // Links to previous
    input: new_items_only,  // Just the new messages
    // ...
};
```

**Location**: `codex-rs/codex-api/src/websocket.rs:89-156`

#### Session vs Turn

Understanding the distinction between session and turn is critical:

| Concept      | Scope               | Description                                              |
|--------------|---------------------|----------------------------------------------------------|
| **Session**  | Entire conversation | From first user message to session end                  |
| **Turn**     | Single exchange     | One user message + all subsequent tool calls + response |
| **Window**   | UI context          | Visible context in the interface                         |

```rust
// Session lives for the entire conversation
pub struct ModelClient {
    // Authentication and transport (permanent)
    transport: T,
    provider: Provider,
    auth: Box<dyn CodexAuth>,
}

// Turn is created fresh for each user message
pub struct ModelClientSession {
    client: ModelClient,
    websocket_session: Option<WebSocketSession>,
    turn_state: Arc<OnceLock<String>>,  // Turn-scoped sticky routing
}
```

**Location**: `codex-rs/core/src/client.rs:183-306`

### Compact/Summarize Flow

When conversation history grows too large, Codex can compact it:

```rust
// Compact request (HTTP)
let compact_request = ResponsesApiRequest {
    model: model.slug.clone(),
    instructions: base_instructions.text,
    input: vec![/* conversation items to compact */],
    tools: vec![],
    // ...
};

// Or via MCP subagent
let subagent_request = ResponsesApiRequestWithMetadata {
    // ...
    metadata: RequestMetadata {
        x_openai_subagent: Some("compact"),
        // ...
    },
};
```

**Location**: `codex-rs/core/src/client.rs:1610-1650`

### Error Handling and Recovery

#### Retry on Transient Errors

```rust
async fn with_retry<R, F, Fut>(&self, request: R, mut attempts: u64) -> Result<F::Output, ApiError>
where
    R: Clone,
    F: Fn(T, R) -> Fut,
    Fut: Future<Output = Result<F::Output, ApiError>>,
{
    let base_delay = Duration::from_millis(200);
    
    loop {
        match self.send_request(request.clone()).await {
            Ok(response) => return Ok(response),
            Err(ApiError::ServerError(status)) if status.as_u16() >= 500 && attempts > 0 => {
                // Exponential backoff
                tokio::time::sleep(base_delay * 2_u64.pow(4 - attempts)).await;
                attempts -= 1;
            }
            Err(e) => return Err(e),
        }
    }
}
```

#### Rate Limit Handling

```rust
match error {
    ApiError::RateLimited { retry_after } => {
        // Wait and retry (or notify user)
        tokio::time::sleep(Duration::from_secs(retry_after)).await;
    }
    _ => return Err(error),
}
```

---

## Summary

To implement a compatible client that mimics codex-cli:

1. **Use the Responses API** (`/v1/responses`), not Chat Completions
2. **Implement proper authentication** with Bearer token and optional ChatGPT-Account-ID
3. **Set correct User-Agent** following the format: `{originator}/{version} ({os} {version}; {arch}) {terminal}`
4. **Include required headers**: `originator`, `x-client-request-id`, `session_id`
5. **Handle SSE streaming** with proper event parsing
6. **Implement retry logic** with exponential backoff
7. **Support WebSocket transport** for better performance
8. **Handle turn state** for sticky routing
9. **Compress requests** with zstd when using ChatGPT auth
10. **Parse model capabilities** from `/v1/models` endpoint

All code references are from the `codex-rs` directory in the repository.
