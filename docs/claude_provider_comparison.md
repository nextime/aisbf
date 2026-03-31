# Claude Provider Comparison: AISBF vs Original Claude Code vs Kiro Gateway

**Date:** 2026-03-31  
**Reviewed by:** AI Assistant  
**AISBF Files:** 
- [`aisbf/providers.py`](aisbf/providers.py:2300) - Claude provider
- [`aisbf/kiro_converters.py`](aisbf/kiro_converters.py) - Kiro core converters
- [`aisbf/kiro_converters_openai.py`](aisbf/kiro_converters_openai.py) - Kiro OpenAI adapters
- [`aisbf/kiro_parsers.py`](aisbf/kiro_parsers.py) - Kiro response parser
**Original Source:** `vendors/claude/src/`

---

## Overview

This document compares three implementations:

1. **AISBF Claude Provider** - Direct HTTP implementation using OAuth2 tokens
2. **Original Claude Code** - TypeScript/React implementation from Anthropic
3. **Kiro Gateway** - Python implementation for Amazon Q Developer (Claude-based)

---

## 1. Architecture & Approach

| Aspect | AISBF Claude | Original Claude Code | Kiro Gateway |
|--------|-------------|---------------------|--------------|
| **Language** | Python | TypeScript/React | Python |
| **API Method** | Direct HTTP via `httpx.AsyncClient` | Anthropic SDK + internal `callModel` | AWS Event Stream via `httpx` |
| **Authentication** | OAuth2 via `ClaudeAuth` class | Internal OAuth2 + session management | AWS SSO OIDC / Kiro Desktop |
| **Endpoint** | `https://api.anthropic.com/v1/messages` | Internal SDK routing | `https://q.{region}.amazonaws.com/generateAssistantResponse` |
| **Response Format** | Standard JSON / SSE | SDK streaming | AWS Event Stream binary |
| **Protocol** | Anthropic Messages API | Anthropic Messages API | AWS CodeWhisperer API |

**Assessment:** 
- AISBF uses the direct HTTP approach (kilocode method) appropriate for OAuth2 tokens
- Kiro uses a completely different API (AWS CodeWhisperer) with binary Event Stream responses
- Both AISBF and Kiro are Python, making them easier to compare directly

---

## 2. Message Format Conversion

### AISBF Claude: [`_convert_messages_to_anthropic()`](aisbf/providers.py:2516)

**What it does well:**
- Correctly extracts system messages to separate `system` parameter
- Handles tool messages by converting to `tool_result` content blocks
- Converts assistant `tool_calls` to Anthropic `tool_use` blocks
- Handles message role alternation requirements

### Kiro Gateway: [`convert_openai_messages_to_unified()`](aisbf/kiro_converters_openai.py:249) + [`build_kiro_history()`](aisbf/kiro_converters.py:1256)

**What it does well:**
- Uses a **unified intermediate format** (`UnifiedMessage`) for API-agnostic processing
- Extracts images from both OpenAI and Anthropic formats
- Handles tool results from both field and content block formats
- **Message merging**: Merges adjacent messages with same role
- **Role normalization**: Normalizes unknown roles to 'user'
- **Alternating roles**: Inserts synthetic assistant messages when needed
- **First message validation**: Ensures conversation starts with user message

### Differences from original:
The original ([`normalizeMessagesForAPI()`](vendors/claude/src/utils/messages.ts)) has more sophisticated handling including:
- Thinking block preservation rules
- Protected thinking block signatures
- More complex tool result merging
- Message UUID tracking for caching

### Key Architectural Difference:
| Feature | AISBF Claude | Kiro Gateway |
|---------|-------------|--------------|
| **Conversion Strategy** | Direct OpenAI → Anthropic | OpenAI → Unified → Kiro |
| **Image Support** | No | Yes (full multimodal) |
| **Message Validation** | Basic | Comprehensive (role normalization, merging, alternation) |
| **Synthetic Messages** | No | Yes (for role alternation, first message) |

---

## 3. Tool Conversion

### AISBF Claude: [`_convert_tools_to_anthropic()`](aisbf/providers.py:2419)

**What it does well:**
- Correctly converts OpenAI `parameters` → Anthropic `input_schema`
- Normalizes JSON Schema types (e.g., `["string", "null"]` → `"string"`)
- Removes `additionalProperties: false` (Anthropic doesn't need it)
- Recursively normalizes nested schemas

### Kiro Gateway: [`convert_tools_to_kiro_format()`](aisbf/kiro_converters.py:537) + [`sanitize_json_schema()`](aisbf/kiro_converters.py:374)

**What it does well:**
- **JSON Schema sanitization**: Removes `additionalProperties` and empty `required` arrays
- **Long description handling**: Moves descriptions > 1000 chars to system prompt
- **Tool name validation**: Validates against 64-character limit
- **Kiro-specific format**: Converts to `toolSpecification` with `inputSchema.json`

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

### Kiro Gateway:
Kiro doesn't use tool_choice in the same way - tools are specified in `userInputMessageContext.tools` and the model decides which to use.

---

## 5. Streaming Implementation

### AISBF Claude: [`_handle_streaming_request()`](aisbf/providers.py:2800)

**What it does:**
- Uses SSE format parsing (`data:` prefixed lines)
- Handles `content_block_delta` events with `text_delta`
- Handles `message_stop` for final chunk
- Yields OpenAI-compatible chunks

### Kiro Gateway: [`AwsEventStreamParser`](aisbf/kiro_parsers.py:220)

**What it does:**
- Parses **AWS Event Stream binary format** (not SSE)
- Handles multiple event types: `content`, `tool_start`, `tool_input`, `tool_stop`, `usage`, `context_usage`
- **Tool call assembly**: Accumulates tool input across multiple events
- **Content deduplication**: Skips repeating content chunks
- **JSON truncation detection**: Diagnoses truncated tool arguments
- **Tool call deduplication**: Removes duplicate tool calls by ID and name+args

### Key Differences:
| Feature | AISBF Claude | Kiro Gateway |
|---------|-------------|--------------|
| **Protocol** | SSE (text) | AWS Event Stream (binary) |
| **Tool Streaming** | No | Yes (tool_start/input/stop events) |
| **Usage Tracking** | No | Yes (usage + context_usage events) |
| **Error Recovery** | Basic | Truncation detection and diagnosis |
| **Content Dedup** | No | Yes |

---

## 6. Response Conversion

### AISBF Claude: [`_convert_to_openai_format()`](aisbf/providers.py:2916)

**Correctly handles:**
- Text content extraction
- `tool_use` → OpenAI `tool_calls` format
- Stop reason mapping (`end_turn` → `stop`, etc.)
- Usage metadata extraction

### Kiro Gateway: [`AwsEventStreamParser.get_content()`](aisbf/kiro_parsers.py:557) + [`get_tool_calls()`](aisbf/kiro_parsers.py:561)

**What it does:**
- Accumulates content chunks into single string
- Finalizes and deduplicates tool calls
- Returns OpenAI-compatible tool call format

---

## 7. Headers & Authentication

### AISBF Claude: [`_get_auth_headers()`](aisbf/providers.py:2331)

**Includes:**
- OAuth2 Bearer token
- `Anthropic-Version: 2023-06-01`
- `Anthropic-Beta` with multiple beta features
- `X-App: cli` and other stainless headers

### Kiro Gateway: AWS SigV4 / OAuth2

**Uses:**
- AWS authentication (SSO OIDC or desktop credentials)
- `profileArn` for user identification
- Region-based endpoint routing

---

## 8. Model Name Resolution

### AISBF Claude: Direct API call
- Queries `https://api.anthropic.com/v1/models`
- Uses model names as returned by API

### Kiro Gateway: [`normalize_model_name()`](aisbf/kiro_converters_openai.py:52) + [`get_model_id_for_kiro()`](aisbf/kiro_converters_openai.py:130)

**Sophisticated normalization:**
- `claude-haiku-4-5` → `claude-haiku-4.5` (dash to dot)
- `claude-haiku-4-5-20251001` → `claude-haiku-4.5` (strip date)
- `claude-3-7-sonnet` → `claude-3.7-sonnet` (legacy format)
- `claude-4.5-opus-high` → `claude-opus-4.5` (inverted format)
- **Hidden models**: Maps display names to internal API IDs

---

## 9. Advanced Features

### Kiro Gateway Exclusive Features:

| Feature | Description | Location |
|---------|-------------|----------|
| **Thinking Mode Injection** | Injects `<thinking_mode>` tags for extended reasoning | [`inject_thinking_tags()`](aisbf/kiro_converters.py:329) |
| **Tool Content Stripping** | Converts tool content to text when no tools defined | [`strip_all_tool_content()`](aisbf/kiro_converters.py:846) |
| **Orphaned Tool Result Handling** | Converts orphaned tool_results to text | [`ensure_assistant_before_tool_results()`](aisbf/kiro_converters.py:930) |
| **Image Extraction** | Full multimodal support (OpenAI + Anthropic formats) | [`extract_images_from_content()`](aisbf/kiro_converters.py:154) |
| **JSON Truncation Recovery** | Detects and diagnoses truncated tool arguments | [`_diagnose_json_truncation()`](aisbf/kiro_parsers.py:471) |

---

## 10. Missing Features (Not in AISBF)

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

### Strengths of Kiro Gateway implementation:
1. **Unified intermediate format** for API-agnostic processing
2. **Comprehensive message validation** (role normalization, merging, alternation)
3. **Full multimodal support** (image extraction from multiple formats)
4. **Sophisticated tool handling** (long descriptions, name validation, content stripping)
5. **AWS Event Stream parsing** with tool call assembly
6. **Model name normalization** for multiple Claude naming conventions
7. **Thinking mode injection** for extended reasoning
8. **Error recovery** (truncation detection, orphaned tool result handling)

### Areas for improvement (AISBF):
1. Add thinking block support for models that use it
2. Add tool call streaming
3. Add more detailed usage metadata (cache tokens)
4. Consider adding model fallback support
5. Add tool result size validation
6. Consider adopting Kiro's unified message format approach
7. Add message role normalization and validation
8. Add image/multimodal support

### Overall assessment:
The AISBF Claude provider is a solid implementation that correctly handles the core API communication, message conversion, and tool handling. It appropriately focuses on the provider-level concerns (API translation) while leaving higher-level concerns (conversation management, compaction) to the rest of the framework.

The Kiro Gateway implementation demonstrates more sophisticated message handling with its unified intermediate format, comprehensive validation, and multimodal support. Several of these patterns (particularly the message validation pipeline and unified format approach) could be valuable additions to the AISBF codebase.
