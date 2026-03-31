# Claude Provider Comparison: AISBF vs Original Claude Code vs KiloCode

**Date:** 2026-03-31  
**Reviewed by:** AI Assistant  
**AISBF File:** [`aisbf/providers.py`](aisbf/providers.py:2300) - Claude provider  
**Original Source:** `vendors/claude/src/`  
**KiloCode Source:** `vendors/kilocode/packages/opencode/src/provider/`

---

## Overview

This document compares three Claude provider implementations:

1. **AISBF Claude Provider** - Direct HTTP implementation using OAuth2 tokens
2. **Original Claude Code** - TypeScript/React implementation from Anthropic
3. **KiloCode** - TypeScript implementation using AI SDK (`@ai-sdk/anthropic`)

---

## 1. Architecture & Approach

| Aspect | AISBF Claude | Original Claude Code | KiloCode |
|--------|-------------|---------------------|----------|
| **Language** | Python | TypeScript/React | TypeScript |
| **API Method** | Direct HTTP via `httpx.AsyncClient` | Anthropic SDK + internal `callModel` | AI SDK (`@ai-sdk/anthropic`) |
| **Authentication** | OAuth2 via `ClaudeAuth` class | Internal OAuth2 + session management | API key / OAuth via Auth system |
| **Endpoint** | `https://api.anthropic.com/v1/messages` | Internal SDK routing | Configurable (baseURL) |
| **Response Format** | Standard JSON / SSE | SDK streaming | AI SDK streaming |
| **Protocol** | Anthropic Messages API | Anthropic Messages API | AI SDK (unified) |
| **Beta Headers** | `claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,...` | Internal | `claude-code-20250219,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14` |

**Assessment:** 
- AISBF uses the direct HTTP approach appropriate for OAuth2 tokens
- KiloCode uses the AI SDK (`@ai-sdk/anthropic`) which provides a unified interface across providers
- KiloCode's custom loader for Anthropic ([`provider.ts:125`](vendors/kilocode/packages/opencode/src/provider/provider.ts:125)) sets beta headers similar to AISBF

---

## 2. Message Format Conversion

### AISBF Claude: [`_convert_messages_to_anthropic()`](aisbf/providers.py:2516)

**What it does well:**
- Correctly extracts system messages to separate `system` parameter
- Handles tool messages by converting to `tool_result` content blocks
- Converts assistant `tool_calls` to Anthropic `tool_use` blocks
- Handles message role alternation requirements

### KiloCode: [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:49) + [`applyCaching()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:177)

**What it does well:**
- **Empty content filtering**: Removes empty string messages and empty text/reasoning parts from array content
- **Tool call ID sanitization**: Sanitizes tool call IDs for Claude models (replaces non-alphanumeric chars with `_`)
- **Prompt caching**: Applies `cacheControl: { type: "ephemeral" }` to system messages and last 2 messages
- **Provider option remapping**: Remaps providerOptions keys from stored providerID to expected SDK key
- **Duplicate reasoning fix**: Removes duplicate reasoning_details from OpenRouter responses

### Differences from original:
The original ([`normalizeMessagesForAPI()`](vendors/claude/src/utils/messages.ts)) has more sophisticated handling including:
- Thinking block preservation rules
- Protected thinking block signatures
- More complex tool result merging
- Message UUID tracking for caching

### Key Architectural Difference:
| Feature | AISBF Claude | KiloCode |
|---------|-------------|----------|
| **Conversion Strategy** | Direct OpenAI → Anthropic | AI SDK message normalization |
| **Image Support** | No | Via AI SDK |
| **Message Validation** | Basic | Empty content filtering, ID sanitization |
| **Synthetic Messages** | No | No |
| **Caching** | No | Yes (ephemeral cache on system/last 2 msgs) |

---

## 3. Tool Conversion

### AISBF Claude: [`_convert_tools_to_anthropic()`](aisbf/providers.py:2419)

**What it does well:**
- Correctly converts OpenAI `parameters` → Anthropic `input_schema`
- Normalizes JSON Schema types (e.g., `["string", "null"]` → `"string"`)
- Removes `additionalProperties: false` (Anthropic doesn't need it)
- Recursively normalizes nested schemas

### KiloCode: AI SDK handles conversion internally

**What it does:**
- Uses `@ai-sdk/anthropic` which handles OpenAI → Anthropic tool conversion internally
- Tool schemas pass through [`schema()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:954) for Gemini/Google models (integer enum → string enum conversion)
- No explicit Anthropic-specific tool conversion needed (SDK handles it)

### Missing from original:
The original has additional tool validation including:
- Tool name length limits
- Parameter size limits
- Schema validation against Anthropic's stricter requirements
- Tool result size budgeting (`applyToolResultBudget` in [`query.ts:379`](vendors/claude/src/query.ts:379))

---

## 4. Tool Choice Conversion

### AISBF Claude: [`_convert_tool_choice_to_anthropic()`](aisbf/providers.py:2367)

**Correctly handles:**
- `"auto"` → `{"type": "auto"}`
- `"required"` → `{"type": "any"}`
- Specific function → `{"type": "tool", "name": "..."}`

### KiloCode: AI SDK handles internally
- Uses AI SDK's unified tool choice handling
- No explicit tool_choice conversion needed

---

## 5. Streaming Implementation

### AISBF Claude: [`_handle_streaming_request()`](aisbf/providers.py:2800)

**What it does:**
- Uses SSE format parsing (`data:` prefixed lines)
- Handles `content_block_delta` events with `text_delta`
- Handles `message_stop` for final chunk
- Yields OpenAI-compatible chunks

### KiloCode: AI SDK streaming

**What it does:**
- Uses AI SDK's built-in streaming via `sdk.languageModel(modelId).doStream()` or `generateText()`
- Handles thinking blocks, tool calls, and text content through unified SDK interface
- Provider-specific streaming handled by `@ai-sdk/anthropic` package
- Supports `fine-grained-tool-streaming-2025-05-14` beta header for streaming tool calls
- Custom fetch wrapper with timeout handling ([`provider.ts:1138`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1138))

### Key Differences:
| Feature | AISBF Claude | KiloCode |
|---------|-------------|----------|
| **Protocol** | SSE (text) | AI SDK (abstracted) |
| **Tool Streaming** | No | Yes (via fine-grained-tool-streaming beta) |
| **Thinking Blocks** | No | Yes (via SDK) |
| **Usage Tracking** | No | Yes (via SDK) |
| **Error Recovery** | Basic | SDK-level |
| **Content Dedup** | No | No |

---

## 6. Response Conversion

### AISBF Claude: [`_convert_to_openai_format()`](aisbf/providers.py:2916)

**Correctly handles:**
- Text content extraction
- `tool_use` → OpenAI `tool_calls` format
- Stop reason mapping (`end_turn` → `stop`, etc.)
- Usage metadata extraction

### KiloCode: AI SDK handles internally
- AI SDK provides unified response format across all providers
- No manual response conversion needed
- Usage metadata includes cache tokens via SDK
- Cost calculation handles provider-specific differences ([`session/index.ts:860`](vendors/kilocode/packages/opencode/src/session/index.ts:860))

---

## 7. Headers & Authentication

### AISBF Claude: [`_get_auth_headers()`](aisbf/providers.py:2331)

**Includes:**
- OAuth2 Bearer token
- `Anthropic-Version: 2023-06-01`
- `Anthropic-Beta` with multiple beta features
- `X-App: cli` and other stainless headers

### KiloCode: [`CUSTOM_LOADERS.anthropic()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:125)

**Includes:**
- API key via `options.apiKey` or auth system
- `anthropic-beta: claude-code-20250219,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14`
- Custom fetch wrapper with timeout handling
- TODO comment for adaptive thinking headers: `adaptive-thinking-2026-01-28,effort-2025-11-24,max-effort-2026-01-24`

---

## 8. Model Name Resolution

### AISBF Claude: Direct API call
- Queries `https://api.anthropic.com/v1/models`
- Uses model names as returned by API

### KiloCode: Model ID passthrough
- Uses model IDs from models.dev database
- Model variants generated via [`variants()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:381) for reasoning efforts
- Model sorting via [`sort()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1348) with priority: `gpt-5`, `claude-sonnet-4`, `big-pickle`, `gemini-3-pro`
- Small model selection via [`getSmallModel()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1277) with priority list including `claude-haiku-4-5`

---

## 9. Reasoning/Thinking Support

### AISBF Claude: No explicit support
- No thinking block handling in current implementation

### KiloCode: Full thinking support via AI SDK

**Features ([`variants()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:381)):**
- **Adaptive thinking** for Opus 4.6 / Sonnet 4.6: `thinking: { type: "adaptive" }` with effort levels
- **Budget-based thinking** for other Claude models: `thinking: { type: "enabled", budgetTokens: N }`
- Effort levels: `low`, `medium`, `high`, `max`
- Temperature returns `undefined` for Claude models (let SDK decide)

---

## 10. Prompt Caching

### AISBF Claude: No explicit support
- No cache_control headers applied

### KiloCode: Automatic ephemeral caching

**Implementation ([`applyCaching()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:177)):**
- Applies `cacheControl: { type: "ephemeral" }` to:
  - First 2 system messages
  - Last 2 non-system messages
- Provider-specific cache options:
  - Anthropic: `cacheControl: { type: "ephemeral" }`
  - OpenRouter: `cacheControl: { type: "ephemeral" }`
  - Bedrock: `cachePoint: { type: "default" }`
  - OpenAI Compatible: `cache_control: { type: "ephemeral" }`
  - GitHub Copilot: `copilot_cache_control: { type: "ephemeral" }`

---

## 11. Advanced Features

### KiloCode Exclusive Features:

| Feature | Description | Location |
|---------|-------------|----------|
| **Reasoning Variants** | Auto-generates low/medium/high/max variants for reasoning models | [`variants()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:381) |
| **Small Model Selection** | Automatic fallback to haiku/flash/nano models | [`getSmallModel()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1277) |
| **Empty Content Filtering** | Removes empty messages and text/reasoning parts | [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:49) |
| **Tool Call ID Sanitization** | Replaces non-alphanumeric chars in tool call IDs for Claude | [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:76) |
| **Duplicate Reasoning Fix** | Removes duplicate reasoning_details from OpenRouter | [`fixDuplicateReasoning()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:256) |
| **Provider Option Remapping** | Remaps providerOptions keys to match SDK expectations | [`message()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:318) |
| **Gemini Schema Sanitization** | Converts integer enums to string enums for Google models | [`schema()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:954) |
| **Unsupported Part Handling** | Converts unsupported media types to error text | [`unsupportedParts()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:217) |

---

## 12. Missing Features (Not in AISBF)

The original Claude Code has many features that are out of scope for a provider handler but worth noting:

| Feature | Description | Location in Original |
|---------|-------------|---------------------|
| **Query loop** | Multi-turn tool execution with auto-compact, reactive compact, context collapse | [`query.ts:219`](vendors/claude/src/query.ts:219) |
| **Token budgeting** | Per-turn output token limits with continuation nudges | [`query.ts:1308`](vendors/claude/src/query.ts:1308) |
| **Auto-compaction** | Automatic conversation summarization when context gets large | [`query.ts:454`](vendors/claude/src/query.ts:454) |
| **Context collapse** | Granular context compression | [`query.ts:440`](vendors/claude/src/query.ts:440) |
| **Stop hooks** | Pre/post-turn hook execution | [`query.ts:1267`](vendors/claude/src/query.ts:1267) |
| **Memory prefetch** | Relevant memory file preloading | [`query.ts:301`](vendors/claude/src/query.ts:301) |
| **Skill discovery** | Dynamic skill file detection | [`query.ts:331`](vendors/claude/src/query.ts:331) |
| **Streaming tool execution** | Parallel tool execution during streaming | [`query.ts:1380`](vendors/claude/src/query.ts:1380) |
| **Model fallback** | Automatic fallback to alternative models | [`query.ts:894`](vendors/claude/src/query.ts:894) |
| **Task budget** | Agentic turn budget management | [`query.ts:291`](vendors/claude/src/query.ts:291) |

---

## Summary

### Strengths of AISBF Claude implementation:
1. Clean OAuth2 integration matching kilocode patterns
2. Comprehensive message format conversion
3. Good tool schema normalization
4. Proper streaming SSE handling
5. Robust fallback strategy for model discovery
6. Adaptive rate limiting with learning

### Strengths of KiloCode implementation:
1. **AI SDK abstraction**: Unified interface across all providers
2. **Automatic prompt caching**: Ephemeral caching on system/last 2 messages
3. **Full thinking support**: Adaptive thinking + budget-based thinking for Claude models
4. **Message validation**: Empty content filtering, tool call ID sanitization
5. **Reasoning variants**: Auto-generates effort level variants for reasoning models
6. **Provider option remapping**: Handles provider-specific SDK key differences
7. **Robust error handling**: Duplicate reasoning fix, unsupported part handling
8. **Model management**: Small model selection, priority sorting

### Areas for improvement (AISBF):
1. Add thinking block support for models that use it
2. Add tool call streaming (fine-grained-tool-streaming beta)
3. Add more detailed usage metadata (cache tokens)
4. Consider adding model fallback support
5. Add tool result size validation
6. Add message role normalization and validation
7. Add image/multimodal support
8. Add prompt caching (ephemeral cache on system/last 2 messages)
9. Add tool call ID sanitization for Claude compatibility

### Overall assessment:
The AISBF Claude provider is a solid implementation that correctly handles the core API communication, message conversion, and tool handling. It appropriately focuses on the provider-level concerns (API translation) while leaving higher-level concerns (conversation management, compaction) to the rest of the framework.

The KiloCode implementation demonstrates the power of using the AI SDK (`@ai-sdk/anthropic`) for provider abstraction, with automatic handling of thinking, caching, and tool conversion. Its message validation pipeline (empty content filtering, ID sanitization, duplicate reasoning fix) provides robustness that AISBF could benefit from.
