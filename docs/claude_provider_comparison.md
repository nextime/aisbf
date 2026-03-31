# Claude Provider Comparison: AISBF vs Original Claude Code Source

**Date:** 2026-03-31  
**Reviewed by:** AI Assistant  
**AISBF File:** [`aisbf/providers.py`](aisbf/providers.py:2300)  
**Original Source:** `vendors/claude/src/`

---

## Overview

This document compares the [`ClaudeProviderHandler`](aisbf/providers.py:2300) implementation in AISBF with the original Claude Code TypeScript source code found in `vendors/claude/src/`.

---

## 1. Architecture & Approach

| Aspect | AISBF Implementation | Original Claude Code |
|--------|---------------------|---------------------|
| **Language** | Python | TypeScript/React |
| **API Method** | Direct HTTP via `httpx.AsyncClient` | Anthropic SDK + internal `callModel` |
| **Authentication** | OAuth2 via `ClaudeAuth` class | Internal OAuth2 + session management |
| **Endpoint** | `https://api.anthropic.com/v1/messages` | Internal SDK routing |

**Assessment:** AISBF correctly uses the direct HTTP approach (kilocode method) which is appropriate for OAuth2 tokens. This matches the pattern used in the original's internal API layer.

---

## 2. Message Format Conversion

**Method:** [`_convert_messages_to_anthropic()`](aisbf/providers.py:2516)

### What AISBF does well:
- Correctly extracts system messages to separate `system` parameter
- Handles tool messages by converting to `tool_result` content blocks
- Converts assistant `tool_calls` to Anthropic `tool_use` blocks
- Handles message role alternation requirements

### Differences from original:
The original ([`normalizeMessagesForAPI()`](vendors/claude/src/utils/messages.ts)) has more sophisticated handling including:
- Thinking block preservation rules
- Protected thinking block signatures
- More complex tool result merging
- Message UUID tracking for caching

---

## 3. Tool Conversion

**Method:** [`_convert_tools_to_anthropic()`](aisbf/providers.py:2419)

### What AISBF does well:
- Correctly converts OpenAI `parameters` → Anthropic `input_schema`
- Normalizes JSON Schema types (e.g., `["string", "null"]` → `"string"`)
- Removes `additionalProperties: false` (Anthropic doesn't need it)
- Recursively normalizes nested schemas

### Missing from original:
The original has additional tool validation including:
- Tool name length limits
- Parameter size limits
- Schema validation against Anthropic's stricter requirements
- Tool result size budgeting (`applyToolResultBudget` in [`query.ts:379`](vendors/claude/src/query.ts:379))

---

## 4. Tool Choice Conversion

**Method:** [`_convert_tool_choice_to_anthropic()`](aisbf/providers.py:2367)

### Correctly handles:
- `"auto"` → `{"type": "auto"}`
- `"required"` → `{"type": "any"}`
- Specific function → `{"type": "tool", "name": "..."}`

### Missing:
- The original has more nuanced tool choice handling including `disable_parallel_tool_use` support

---

## 5. Streaming Implementation

**Method:** [`_handle_streaming_request()`](aisbf/providers.py:2800)

### What AISBF does:
- Uses SSE format parsing (`data:` prefixed lines)
- Handles `content_block_delta` events with `text_delta`
- Handles `message_stop` for final chunk
- Yields OpenAI-compatible chunks

### Differences from original:
The original's streaming ([`callModel()`](vendors/claude/src/query.ts:659)) is more complex:
- Handles thinking blocks during streaming
- Has streaming tool executor (`StreamingToolExecutor`)
- Supports fallback model switching mid-stream
- Has token budget tracking during streaming
- Handles `tool_use` blocks during streaming (not just text)
- Has message backfill for tool inputs

### Missing features in AISBF streaming:
- No thinking block handling
- No tool call streaming
- No fallback model support
- No token budget tracking

---

## 6. Response Conversion

**Method:** [`_convert_to_openai_format()`](aisbf/providers.py:2916)

### Correctly handles:
- Text content extraction
- `tool_use` → OpenAI `tool_calls` format
- Stop reason mapping (`end_turn` → `stop`, etc.)
- Usage metadata extraction

### Differences:
Original has more complex response handling including:
- Thinking block preservation
- Protected thinking signatures
- More detailed usage tracking (cache tokens, etc.)

---

## 7. Headers & Authentication

**Method:** [`_get_auth_headers()`](aisbf/providers.py:2331)

### AISBF includes:
- OAuth2 Bearer token
- `Anthropic-Version: 2023-06-01`
- `Anthropic-Beta` with multiple beta features
- `X-App: cli` and other stainless headers

**Assessment:** Headers match the original's CLI proxy pattern well. The beta features list (`claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,context-management-2025-06-27,prompt-caching-scope-2026-01-05`) is comprehensive.

---

## 8. Rate Limiting

### AISBF has:
- Adaptive rate limiter with 429 learning
- Exponential backoff with jitter
- Provider disable/enable cycles

### Original has:
- Similar rate limiting but integrated with the query loop
- Model fallback on rate limits
- More sophisticated retry logic

---

## 9. Model Discovery

**Method:** [`get_models()`](aisbf/providers.py:3217)

### AISBF approach:
1. Primary API call to `https://api.anthropic.com/v1/models`
2. Fallback to `http://lisa.nexlab.net:5000/claude/models`
3. Local cache (24-hour TTL)
4. Static fallback list

**Assessment:** Good fallback strategy. The original doesn't have a models endpoint (Anthropic doesn't provide one publicly), so the fallback strategy is appropriate.

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

### Strengths of AISBF implementation:
1. Clean OAuth2 integration matching kilocode patterns
2. Comprehensive message format conversion
3. Good tool schema normalization
4. Proper streaming SSE handling
5. Robust fallback strategy for model discovery
6. Adaptive rate limiting with learning

### Areas for improvement:
1. Add thinking block support for models that use it
2. Add tool call streaming
3. Add more detailed usage metadata (cache tokens)
4. Consider adding model fallback support
5. Add tool result size validation

### Overall assessment:
The AISBF Claude provider is a solid implementation that correctly handles the core API communication, message conversion, and tool handling. It appropriately focuses on the provider-level concerns (API translation) while leaving higher-level concerns (conversation management, compaction) to the rest of the framework.
