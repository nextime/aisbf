# AISBF Claude Provider Improvement Plan

**Date:** 2026-03-31  
**Based on:** Claude Provider Comparison ([`docs/claude_provider_comparison.md`](docs/claude_provider_comparison.md))  
**Target:** [`aisbf/providers.py`](aisbf/providers.py:2300) - `ClaudeProviderHandler` class

---

## Overview

This plan outlines the implementation of improvements identified in the Claude provider comparison between AISBF, vendors/kilocode, and vendors/claude. The improvements are prioritized by impact and complexity.

---

## Phase 1: Quick Wins (Low Complexity, High Impact)

### 1.1 Tool Call ID Sanitization

**Problem:** Claude API requires tool call IDs to contain only alphanumeric characters, underscores, and hyphens. OpenAI-style IDs may contain invalid characters.

**Reference:** vendors/kilocode [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:76)

**Implementation:**
- Add `_sanitize_tool_call_id()` method to `ClaudeProviderHandler`
- Replace non-alphanumeric chars (except `_` and `-`) with `_`
- Apply to all tool_call IDs in messages before sending to API
- Apply to tool_use IDs in response conversion

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class

**Estimated effort:** 1-2 hours

---

### 1.2 Empty Content Filtering

**Problem:** Claude API rejects messages with empty content strings or empty text/reasoning parts in array content.

**Reference:** vendors/kilocode [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:49)

**Implementation:**
- Add `_filter_empty_content()` method to `ClaudeProviderHandler`
- Filter out empty string messages
- Remove empty text parts from array content
- Apply during message conversion in `_convert_messages_to_anthropic()`

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class

**Estimated effort:** 1-2 hours

---

### 1.3 Prompt Caching (Ephemeral)

**Problem:** No cache_control headers applied, missing opportunity for cost savings via prompt caching.

**Reference:** vendors/kilocode [`applyCaching()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:177)

**Implementation:**
- Add `enable_prompt_caching` config option to provider config
- Add `_apply_cache_control()` method to `ClaudeProviderHandler`
- Apply `cache_control: {"type": "ephemeral"}` to:
  - System message (if present)
  - Last 2 non-system messages before the final user message
- Only apply when message count > 4 (avoid overhead for short conversations)
- Add cache_control to the message content block format

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class
- `aisbf/models.py` - Add cache_control field if needed

**Estimated effort:** 2-3 hours

---

## Phase 2: Core Improvements (Medium Complexity, High Impact)

### 2.1 Thinking Block Support

**Problem:** No thinking block handling in current implementation. Claude 3.7+ Sonnet and Opus support extended thinking.

**Reference:** vendors/kilocode [`variants()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:381)

**Implementation:**
- Add `enable_thinking` config option to provider config
- Add `thinking_budget_tokens` config option (default: 16000)
- Add `thinking` parameter to API request payload when enabled
- Parse thinking blocks from response content
- Add thinking content to response metadata (optional, for logging)
- Handle thinking blocks in streaming response

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class
- `aisbf/models.py` - Add thinking config fields
- `config/providers.json` - Add thinking config schema

**Estimated effort:** 4-6 hours

---

### 2.2 Tool Call Streaming

**Problem:** No tool call streaming. Missing `fine-grained-tool-streaming-2025-05-14` beta feature.

**Reference:** vendors/kilocode beta headers + vendors/claude `StreamingToolExecutor`

**Implementation:**
- Add `fine-grained-tool-streaming-2025-05-14` to Anthropic-Beta header (already partially there)
- Update streaming parser to handle `content_block_start` events with `tool_use` type
- Parse `content_block_delta` events with `input_json_delta` type
- Accumulate partial JSON and emit tool call chunks in OpenAI format
- Handle `content_block_stop` events for tool_use blocks

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler._handle_streaming_request()`

**Estimated effort:** 4-6 hours

---

### 2.3 Detailed Usage Metadata

**Problem:** No cache token tracking in usage metadata. Missing cache_read_input_tokens and cache_creation_input_tokens.

**Reference:** vendors/kilocode [`session/index.ts:860`](vendors/kilocode/packages/opencode/src/session/index.ts:860)

**Implementation:**
- Extract `cache_read_input_tokens` from Claude API response usage
- Extract `cache_creation_input_tokens` from Claude API response usage
- Add to OpenAI-format response usage metadata:
  - `cache_read_tokens`
  - `cache_creation_tokens`
- Log cache hit/miss for analytics

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler._convert_to_openai_format()`

**Estimated effort:** 1-2 hours

---

## Phase 3: Robustness Improvements (Medium Complexity, Medium Impact)

### 3.1 Message Role Normalization and Validation

**Problem:** No validation of message roles or content structure before sending to API.

**Reference:** vendors/kilocode [`normalizeMessages()`](vendors/kilocode/packages/opencode/src/provider/transform.ts:49)

**Implementation:**
- Add `_validate_messages()` method to `ClaudeProviderHandler`
- Validate message roles are one of: user, assistant, system
- Validate system messages only appear at start
- Validate alternating user/assistant roles (after system)
- Log warnings for invalid messages instead of failing
- Add option to auto-fix common issues (e.g., consecutive user messages)

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class

**Estimated effort:** 2-3 hours

---

### 3.2 Tool Result Size Validation

**Problem:** No validation of tool result sizes before sending to API.

**Reference:** vendors/claude [`applyToolResultBudget`](vendors/claude/src/query.ts:379)

**Implementation:**
- Add `max_tool_result_chars` config option (default: 100000)
- Add `_truncate_tool_result()` method
- Truncate tool results that exceed limit with truncation notice
- Log warnings when truncation occurs
- Track cumulative tool result size per turn

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class
- `aisbf/models.py` - Add max_tool_result_chars config

**Estimated effort:** 2-3 hours

---

### 3.3 Model Fallback Support

**Problem:** No automatic fallback to alternative models when primary model fails.

**Reference:** vendors/claude [`query.ts:894`](vendors/claude/src/query.ts:894)

**Implementation:**
- Add `fallback_models` config option (list of model IDs)
- Add fallback logic to `handle_request()` method
- On specific error types (rate limit, overloaded), retry with next fallback model
- Track fallback usage for analytics
- Limit fallback attempts to prevent infinite loops

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class
- `aisbf/models.py` - Add fallback_models config

**Estimated effort:** 3-4 hours

---

## Phase 4: Advanced Features (High Complexity, Medium Impact)

### 4.1 Image/Multimodal Support

**Problem:** No image/multimodal support in current implementation.

**Reference:** vendors/kilocode AI SDK image handling

**Implementation:**
- Add image content block support in `_convert_messages_to_anthropic()`
- Handle OpenAI image_url format → Anthropic image source format
- Support base64-encoded images
- Support image URLs (Claude API supports URL-based images)
- Add image validation (size, format, encoding)
- Add max image size config option

**Files to modify:**
- `aisbf/providers.py` - `ClaudeProviderHandler` class
- `aisbf/models.py` - Add image config options

**Estimated effort:** 4-6 hours

---

## Implementation Order

| Phase | Item | Priority | Effort | Dependencies |
|-------|------|----------|--------|--------------|
| 1 | 1.1 Tool Call ID Sanitization | High | 1-2h | None |
| 1 | 1.2 Empty Content Filtering | High | 1-2h | None |
| 1 | 1.3 Prompt Caching | High | 2-3h | None |
| 2 | 2.3 Detailed Usage Metadata | High | 1-2h | None |
| 2 | 2.1 Thinking Block Support | High | 4-6h | None |
| 2 | 2.2 Tool Call Streaming | Medium | 4-6h | 2.1 |
| 3 | 3.1 Message Role Validation | Medium | 2-3h | None |
| 3 | 3.2 Tool Result Size Validation | Medium | 2-3h | None |
| 3 | 3.3 Model Fallback Support | Low | 3-4h | None |
| 4 | 4.1 Image/Multimodal Support | Low | 4-6h | None |

**Total estimated effort:** 24-37 hours

---

## Testing Strategy

For each improvement:

1. **Unit tests:** Test the new method/function in isolation
2. **Integration tests:** Test with mock Claude API responses
3. **End-to-end tests:** Test with actual Claude API (using test credentials)
4. **Regression tests:** Ensure existing functionality still works

### Test Files to Create/Update:
- `tests/test_claude_provider.py` - Main test file for ClaudeProviderHandler
- `tests/test_claude_streaming.py` - Streaming-specific tests
- `tests/test_claude_tools.py` - Tool handling tests
- `tests/test_claude_messages.py` - Message conversion tests

---

## Configuration Changes

### New config options to add to `config/providers.json`:

```json
{
  "claude_config": {
    "enable_thinking": true,
    "thinking_budget_tokens": 16000,
    "enable_prompt_caching": true,
    "max_tool_result_chars": 100000,
    "fallback_models": [],
    "max_image_size_bytes": 5242880
  }
}
```

---

## Risk Assessment

| Item | Risk | Mitigation |
|------|------|------------|
| Tool Call ID Sanitization | Low - purely additive change | Unit tests for edge cases |
| Empty Content Filtering | Low - filters invalid data | Unit tests for edge cases |
| Prompt Caching | Medium - may affect response quality | Config option, default off |
| Thinking Block Support | Medium - new API feature | Config option, beta header required |
| Tool Call Streaming | Medium - complex parsing | Extensive streaming tests |
| Usage Metadata | Low - additive change | Unit tests |
| Message Validation | Low - validation only | Unit tests for invalid inputs |
| Tool Result Size | Low - truncation only | Config option, clear truncation notice |
| Model Fallback | Medium - may increase costs | Config option, limited attempts |
| Image Support | Medium - new feature | Config option, size limits |

---

## Rollout Plan

1. **Week 1:** Phase 1 items (Tool Call ID, Empty Content, Prompt Caching)
2. **Week 2:** Phase 2 items (Thinking, Streaming, Usage Metadata)
3. **Week 3:** Phase 3 items (Validation, Size Limits, Fallback)
4. **Week 4:** Phase 4 items (Image Support) + Testing + Documentation

Each phase should be:
- Implemented
- Tested
- Reviewed
- Merged to main
- Deployed to staging
- Validated before proceeding to next phase
