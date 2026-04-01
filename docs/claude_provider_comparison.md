# Claude Provider Comparison: AISBF vs vendors/kilocode vs vendors/claude

**Date:** 2026-03-31  
**Reviewed by:** AI Assistant  
**Updated:** 2026-04-01 - Deep dive into vendors/claude/src/services/api/claude.ts (3419 lines)

**Sources compared:**
- **AISBF:** [`aisbf/providers.py`](aisbf/providers.py:2300) - `ClaudeProviderHandler` class
- **vendors/kilocode:** `vendors/kilocode/packages/opencode/src/provider/` - Provider transform + SDK integration
- **vendors/claude:** `vendors/claude/src/` - Original Claude Code TypeScript source (3419-line `claude.ts` + `messages.ts`)

---

## Overview

This document compares three Claude provider implementations found in the codebase:

1. **AISBF** (`aisbf/providers.py`) - Direct HTTP implementation using OAuth2 tokens via `httpx.AsyncClient`
2. **vendors/kilocode** (`vendors/kilocode/packages/opencode/src/provider/`) - TypeScript implementation using AI SDK (`@ai-sdk/anthropic`)
3. **vendors/claude** (`vendors/claude/src/`) - Original Claude Code TypeScript/React implementation from Anthropic

---

## 1. Architecture & Approach

| Aspect | AISBF | vendors/kilocode | vendors/claude |
|--------|-------|------------------|----------------|
| **Language** | Python | TypeScript | TypeScript/React |
| **API Method** | Direct HTTP via `httpx.AsyncClient` | AI SDK (`@ai-sdk/anthropic`) | Anthropic SDK + internal `callModel` |
| **Authentication** | OAuth2 via `ClaudeAuth` class | API key / OAuth via Auth system | Internal OAuth2 + session management |
| **Endpoint** | `https://api.anthropic.com/v1/messages` | Configurable (baseURL) | Internal SDK routing |
| **Response Format** | Standard JSON / SSE | AI SDK streaming | SDK streaming |
| **Protocol** | Anthropic Messages API | AI SDK (unified) | Anthropic Messages API |
| **Beta Headers** | `claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,...` | `claude-code-20250219,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14` | Internal |

**Assessment:** 
- AISBF uses direct HTTP approach appropriate for OAuth2 tokens
- vendors/kilocode uses AI SDK (`@ai-sdk/anthropic`) for unified provider interface
- vendors/kilocode's custom loader ([`provider.ts:125`](vendors/kilocode/packages/opencode/src/provider/provider.ts:125)) sets beta headers similar to AISBF

---

## 2. Message Format Conversion

### AISBF: [`_convert_messages_to_anthropic()`](aisbf/providers.py:2890)

**What it does well:**
- Correctly extracts system messages to separate `system` parameter
- Handles tool messages by converting to `tool_result` content blocks
- Converts assistant `tool_calls` to Anthropic `tool_use` blocks
- Handles message role alternation requirements
- Extracts images from OpenAI format content blocks

### vendors/kilocode: [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:49) + [`applyCaching()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:177)

**What it does well:**
- **Empty content filtering**: Removes empty string messages and empty text/reasoning parts from array content
- **Tool call ID sanitization**: Sanitizes tool call IDs for Claude models (replaces non-alphanumeric chars with `_`)
- **Prompt caching**: Applies `cacheControl: { type: "ephemeral" }` to system messages and last 2 messages
- **Provider option remapping**: Remaps providerOptions keys from stored providerID to expected SDK key
- **Duplicate reasoning fix**: Removes duplicate reasoning_details from OpenRouter responses

### vendors/claude: [`normalizeMessagesForAPI()`](vendors/claude/src/utils/messages.ts:1989)

**What it does well (3419-line implementation):**
- **Thinking block preservation**: Walking backward to merge thinking blocks with their parent assistant messages
- **Protected thinking block signatures**: Preserves `signature` field on thinking blocks
- **Tool result pairing**: `ensureToolResultPairing()` inserts synthetic errors for orphaned tool_uses
- **Message UUID tracking**: Uses `message.id` for merging fragmented assistant messages
- **Tool input normalization**: `normalizeToolInputForAPI()` validates tool arguments
- **Caller field stripping**: Removes `caller` field from tool_use blocks for non-tool-search models
- **Advisor block stripping**: Removes advisor blocks when beta header not present
- **Media limit enforcement**: `stripExcessMediaItems()` caps at 100 media items per request
- **Empty content handling**: Inserts placeholder content for empty assistant messages
- **Tool use deduplication**: Prevents duplicate tool_use IDs across merged assistant messages
- **Orphan tool result handling**: Converts orphaned tool_results to user messages with error text

### Key Architectural Difference:
| Feature | AISBF | vendors/kilocode | vendors/claude |
|---------|-------|------------------|----------------|
| **Conversion Strategy** | Direct OpenAI → Anthropic | AI SDK message normalization | Internal SDK normalization |
| **Image Support** | Yes (Phase 4.1) | Via AI SDK | Yes (native, with 100-item cap) |
| **Message Validation** | Basic role normalization | Empty content filtering, ID sanitization | Thinking preservation, UUID tracking, media limits |
| **Tool Result Pairing** | No | No | Yes (ensureToolResultPairing) |
| **Synthetic Messages** | No | No | Yes (orphan tool_result → user error) |
| **Caching** | Yes (ephemeral cache on last 2 msgs) | Yes (ephemeral cache on system/last 2 msgs) | Yes (sophisticated cache_control with 1h TTL) |
| **Media Stripping** | No | No | Yes (stripExcessMediaItems at 100) |

---

## 3. Tool Conversion

### AISBF: [`_convert_tools_to_anthropic()`](aisbf/providers.py:2419)

**What it does well:**
- Correctly converts OpenAI `parameters` → Anthropic `input_schema`
- Normalizes JSON Schema types (e.g., `["string", "null"]` → `"string"`)
- Removes `additionalProperties: false` (Anthropic doesn't need it)
- Recursively normalizes nested schemas

### vendors/kilocode: AI SDK handles conversion internally

**What it does:**
- Uses `@ai-sdk/anthropic` which handles OpenAI → Anthropic tool conversion internally
- Tool schemas pass through [`schema()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:954) for Gemini/Google models (integer enum → string enum conversion)
- No explicit Anthropic-specific tool conversion needed (SDK handles it)

### vendors/claude: Internal SDK handling

**What it does:**
- Tool validation including name length limits
- Parameter size limits
- Schema validation against Anthropic's stricter requirements
- Tool result size budgeting ([`applyToolResultBudget`](vendors/claude/src/query.ts:379))

---

## 4. Tool Choice Conversion

### AISBF: [`_convert_tool_choice_to_anthropic()`](aisbf/providers.py:2367)

**Correctly handles:**
- `"auto"` → `{"type": "auto"}`
- `"required"` → `{"type": "any"}`
- Specific function → `{"type": "tool", "name": "..."}`

### vendors/kilocode: AI SDK handles internally
- Uses AI SDK's unified tool choice handling
- No explicit tool_choice conversion needed

### vendors/claude: Internal SDK handling
- More nuanced tool choice handling including `disable_parallel_tool_use` support

---

## 5. Streaming Implementation

### AISBF: [`_handle_streaming_request()`](aisbf/providers.py:3369)

**What it does:**
- Uses SSE format parsing (`data:` prefixed lines)
- Handles `content_block_delta` events with `text_delta`
- Handles `input_json_delta` for tool call argument streaming (Phase 2.2)
- Handles `content_block_stop` to emit tool calls
- Handles `message_stop` for final chunk
- Yields OpenAI-compatible chunks
- Streaming retry with fallback models via `_wrap_streaming_with_retry()`

### vendors/kilocode: AI SDK streaming

**What it does:**
- Uses AI SDK's built-in streaming via `sdk.languageModel(modelId).doStream()` or `generateText()`
- Handles thinking blocks, tool calls, and text content through unified SDK interface
- Provider-specific streaming handled by `@ai-sdk/anthropic` package
- Supports `fine-grained-tool-streaming-2025-05-14` beta header for streaming tool calls
- Custom fetch wrapper with timeout handling ([`provider.ts:1138`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1138))

### vendors/claude: Raw stream via Anthropic SDK ([`queryModel()`](vendors/claude/src/services/api/claude.ts:1017))

**What it does (3419-line implementation):**
- **Raw stream access**: Uses `anthropic.beta.messages.create({ stream: true }).withResponse()` instead of BetaMessageStream to avoid O(n²) partial JSON parsing
- **Streaming idle watchdog**: `STREAM_IDLE_TIMEOUT_MS` (default 90s) aborts hung streams via setTimeout
- **Stall detection**: Tracks gaps between events, logs stalls >30s with analytics
- **Content block accumulation**: Manually accumulates `input_json_delta` into tool_use blocks
- **Thinking block streaming**: Handles `thinking_delta` and `signature_delta` events
- **Connector text support**: Custom `connector_text_delta` event type for internal use
- **Advisor tool tracking**: Tracks `advisor` server_tool_use blocks with analytics
- **Research field capture**: Internal-only `research` field from message_start/content_block_delta
- **Non-streaming fallback**: Automatic fallback on stream errors with `executeNonStreamingRequest()`
- **Fallback timeout**: `getNonstreamingFallbackTimeoutMs()` (300s default, 120s for remote)
- **Stream resource cleanup**: `releaseStreamResources()` cancels Response body to prevent native memory leaks
- **Request ID tracking**: Generates `clientRequestId` for correlating timeout errors with server logs
- **Cache break detection**: `checkResponseForCacheBreak()` compares cache tokens across requests
- **Quota status extraction**: `extractQuotaStatusFromHeaders()` parses rate limit headers
- **Cost tracking**: `calculateUSDCost()` + `addToTotalSessionCost()` for session billing
- **Fast mode support**: Dynamic `speed='fast'` parameter with latched beta header
- **Task budget support**: `output_config.task_budget` for API-side token budgeting
- **Context management**: `getAPIContextManagement()` for API-side context compression
- **LSP tool deferral**: `shouldDeferLspTool()` defers tools until LSP init completes
- **Dynamic tool loading**: Only includes discovered deferred tools, not all upfront
- **Tool search beta**: Provider-specific beta headers (1P vs Bedrock vs Vertex)
- **Cache editing beta**: Latched `cache-editing` beta header for cached microcompact
- **AFK mode beta**: Latched `afk-mode` beta header for auto mode sessions
- **Thinking clear latch**: Latched `thinking-clear` beta after 1h idle to bust cache
- **Effort params**: `configureEffortParams()` for adaptive/budget thinking modes
- **Structured outputs**: `output_config.format` with `structured-outputs-2025-05-22` beta
- **Media stripping**: `stripExcessMediaItems()` caps at 100 media items before API call
- **Fingerprint computation**: `computeFingerprintFromMessages()` for attribution headers
- **System prompt building**: `buildSystemPromptBlocks()` with cache_control per block
- **Cache breakpoints**: `addCacheBreakpoints()` with cache_edits and pinned edits support
- **Global cache strategy**: `shouldUseGlobalCacheScope()` for prompt_caching_scope beta
- **MCP tool cache gating**: Disables global cache when MCP tools present (dynamic schemas)
- **1h TTL caching**: `should1hCacheTTL()` for eligible users with GrowthBook allowlist
- **Bedrock 1h TTL**: `ENABLE_PROMPT_CACHING_1H_BEDROCK` for 3P Bedrock users
- **Prompt cache break detection**: `recordPromptState()` hashes everything affecting cache key
- **LLM span tracing**: `startLLMRequestSpan()` for beta tracing integration
- **Session activity**: `startSessionActivity('api_call')` for OS-level activity indicators
- **VCR recording**: `withStreamingVCR()` for recording/replaying API responses
- **Anti-distillation**: `fake_tools` opt-in for 1P CLI only

### Key Differences:
| Feature | AISBF | vendors/kilocode | vendors/claude |
|---------|-------|------------------|----------------|
| **Protocol** | SSE (text) | AI SDK (abstracted) | Raw SDK stream |
| **Tool Streaming** | Yes (Phase 2.2) | Yes (via fine-grained-tool-streaming beta) | Yes (manual accumulation) |
| **Thinking Blocks** | Yes (Phase 2.1) | Yes (via SDK) | Yes (native, with signature) |
| **Usage Tracking** | Yes (Phase 2.3) | Yes (via SDK) | Yes (cumulative, with cache_creation) |
| **Error Recovery** | Fallback models | SDK-level | Non-streaming fallback + model fallback |
| **Content Dedup** | No | No | Yes (text block dedup) |
| **Idle Watchdog** | No | No | Yes (90s timeout) |
| **Stall Detection** | No | No | Yes (30s threshold) |
| **Memory Cleanup** | Basic | SDK-level | Explicit Response body cancel |
| **Request ID** | No | No | Yes (client-generated UUID) |
| **Cache Tracking** | No | No | Yes (cache_break detection) |
| **Cost Tracking** | No | Yes (via SDK) | Yes (session-level USD) |
| **VCR Support** | No | No | Yes (record/replay) |

---

## 6. Response Conversion

### AISBF: [`_convert_to_openai_format()`](aisbf/providers.py:2916)

**Correctly handles:**
- Text content extraction
- `tool_use` → OpenAI `tool_calls` format
- Stop reason mapping (`end_turn` → `stop`, etc.)
- Usage metadata extraction

### vendors/kilocode: AI SDK handles internally
- AI SDK provides unified response format across all providers
- No manual response conversion needed
- Usage metadata includes cache tokens via SDK
- Cost calculation handles provider-specific differences ([`session/index.ts:860`](vendors/kilocode/packages/opencode/src/session/index.ts:860))

### vendors/claude: Internal SDK handling
- Thinking block preservation
- Protected thinking signatures
- More detailed usage tracking (cache tokens, etc.)

---

## 7. Headers & Authentication

### AISBF: [`_get_auth_headers()`](aisbf/providers.py:2331)

**Includes:**
- OAuth2 Bearer token
- `Anthropic-Version: 2023-06-01`
- `Anthropic-Beta` with multiple beta features
- `X-App: cli` and other stainless headers

### vendors/kilocode: [`CUSTOM_LOADERS.anthropic()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:125)

**Includes:**
- API key via `options.apiKey` or auth system
- `anthropic-beta: claude-code-20250219,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14`
- Custom fetch wrapper with timeout handling
- TODO comment for adaptive thinking headers: `adaptive-thinking-2026-01-28,effort-2025-11-24,max-effort-2026-01-24`

### vendors/claude: Internal OAuth2

**Includes:**
- Internal OAuth2 session management
- Internal SDK routing

---

## 8. Model Name Resolution

### AISBF: Direct API call
- Queries `https://api.anthropic.com/v1/models`
- Uses model names as returned by API

### vendors/kilocode: Model ID passthrough
- Uses model IDs from models.dev database
- Model variants generated via [`variants()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:381) for reasoning efforts
- Model sorting via [`sort()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1348) with priority: `gpt-5`, `claude-sonnet-4`, `big-pickle`, `gemini-3-pro`
- Small model selection via [`getSmallModel()`](vendors/kilocode/packages/opencode/src/provider/provider.ts:1277) with priority list including `claude-haiku-4-5`

### vendors/claude: Internal SDK handling
- Uses internal model registry
- No public models endpoint

---

## 9. Reasoning/Thinking Support

### AISBF: No explicit support
- No thinking block handling in current implementation

### vendors/kilocode: Full thinking support via AI SDK

**Features ([`variants()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:381)):**
- **Adaptive thinking** for Opus 4.6 / Sonnet 4.6: `thinking: { type: "adaptive" }` with effort levels
- **Budget-based thinking** for other Claude models: `thinking: { type: "enabled", budgetTokens: N }`
- Effort levels: `low`, `medium`, `high`, `max`
- Temperature returns `undefined` for Claude models (let SDK decide)

### vendors/claude: Full thinking support

**Features:**
- Thinking block preservation during streaming
- Protected thinking block signatures
- Interleaved thinking support (`interleaved-thinking-2025-05-14` beta)

---

## 10. Prompt Caching

### AISBF: No explicit support
- No cache_control headers applied

### vendors/kilocode: Automatic ephemeral caching

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

### vendors/claude: Internal caching
- Internal prompt caching via Anthropic API
- Message UUID tracking for cache hits

---

## 11. Advanced Features

### vendors/kilocode Exclusive Features:

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

### vendors/claude Exclusive Features:

| Feature | Description | Location |
|---------|-------------|----------|
| **Query loop** | Multi-turn tool execution with auto-compact, reactive compact | [`query.ts:219`](vendors/claude/src/query.ts:219) |
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
1. Clean OAuth2 integration matching vendors/kilocode patterns
2. Comprehensive message format conversion
3. Good tool schema normalization
4. Proper streaming SSE handling
5. Robust fallback strategy for model discovery
6. Adaptive rate limiting with learning

### Strengths of vendors/kilocode implementation:
1. **AI SDK abstraction**: Unified interface across all providers
2. **Automatic prompt caching**: Ephemeral caching on system/last 2 messages
3. **Full thinking support**: Adaptive thinking + budget-based thinking for Claude models
4. **Message validation**: Empty content filtering, tool call ID sanitization
5. **Reasoning variants**: Auto-generates effort level variants for reasoning models
6. **Provider option remapping**: Handles provider-specific SDK key differences
7. **Robust error handling**: Duplicate reasoning fix, unsupported part handling
8. **Model management**: Small model selection, priority sorting

### Strengths of vendors/claude implementation:
1. **Full conversation management**: Query loop with auto-compact, reactive compact
2. **Token budgeting**: Per-turn output limits with continuation nudges
3. **Streaming tool execution**: Parallel tool execution during streaming
4. **Model fallback**: Automatic fallback to alternative models
5. **Memory prefetch**: Relevant memory file preloading
6. **Skill discovery**: Dynamic skill file detection
7. **Stop hooks**: Pre/post-turn hook execution

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

The vendors/kilocode implementation demonstrates the power of using the AI SDK (`@ai-sdk/anthropic`) for provider abstraction, with automatic handling of thinking, caching, and tool conversion. Its message validation pipeline (empty content filtering, ID sanitization, duplicate reasoning fix) provides robustness that AISBF could benefit from.

The vendors/claude implementation is the most comprehensive, with full conversation management including auto-compaction, token budgeting, streaming tool execution, and model fallback. Many of these features are out of scope for a provider handler but represent the full Claude Code experience.
