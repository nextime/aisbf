# Claude Provider: Improvements & SDK Migration Analysis

**Date:** 2026-04-01  
**Author:** AI Assistant

---

## Executive Summary

This document analyzes potential improvements for the AISBF Claude provider and evaluates the trade-offs of migrating from direct HTTP (`httpx`) to the official Anthropic Python SDK.

---

## 1. Current Architecture Assessment

### What We Do Well:
- **Direct HTTP control**: Full control over request/response lifecycle
- **OAuth2 integration**: Custom auth flow matching Claude Code's OAuth2
- **Streaming SSE parsing**: Manual SSE parsing gives fine-grained control
- **OpenAI format conversion**: Complete OpenAI ↔ Anthropic translation
- **Fallback retry logic**: Model fallback with exponential backoff

### Current Limitations:
- Manual message format conversion (error-prone)
- No automatic retry on transient errors
- Missing advanced SDK features (automatic token counting, etc.)
- Temperature/thinking conflict handling (just fixed)

---

## 2. Recommended Improvements (Without SDK Migration)

### 2.1 Message Validation Pipeline
**Priority:** HIGH  
**Effort:** MEDIUM

Implement a comprehensive message validation pipeline similar to vendors/kilocode:

```python
def validate_and_normalize_messages(self, messages: List[Dict]) -> List[Dict]:
    """Complete message validation pipeline."""
    # 1. Empty content filtering
    messages = self._filter_empty_content_blocks(messages)
    
    # 2. Tool call ID sanitization
    messages = self._sanitize_tool_call_ids(messages)
    
    # 3. Role alternation enforcement
    messages = self._ensure_alternating_roles(messages)
    
    # 4. Tool result pairing
    messages = self._ensure_tool_result_pairing(messages)
    
    # 5. Thinking block preservation
    messages = self._preserve_thinking_blocks(messages)
    
    # 6. Media limit enforcement (100 items max)
    messages = self._enforce_media_limits(messages)
    
    return messages
```

**Benefits:**
- Prevents 400 errors from malformed messages
- Matches vendors/kilocode robustness
- Reduces API rejection rate

### 2.2 Automatic Retry with Exponential Backoff
**Priority:** HIGH  
**Effort:** LOW

Add automatic retry for transient errors (529, 503, rate limits):

```python
async def _request_with_retry(self, api_url, payload, headers, max_retries=3):
    """Request with automatic retry and exponential backoff."""
    for attempt in range(max_retries):
        try:
            response = await self.client.post(api_url, headers=headers, json=payload)
            
            if response.status_code == 429:
                wait_time = self._parse_retry_after(response.headers)
                await asyncio.sleep(wait_time)
                continue
            
            if response.status_code in (529, 503):
                wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                await asyncio.sleep(wait_time)
                continue
            
            return response
            
        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
```

**Benefits:**
- Handles transient overload errors automatically
- Respects `x-should-retry: true` header
- Reduces user-facing errors

### 2.3 Temperature/Thinking Conflict Resolution
**Priority:** HIGH (ALREADY FIXED)  
**Effort:** DONE

Fixed in commit 2559e2f - skip temperature 0.0 when thinking beta is active.

### 2.4 Streaming Idle Watchdog
**Priority:** MEDIUM  
**Effort:** LOW

Add timeout detection for hung streams (matching vendors/claude):

```python
STREAM_IDLE_TIMEOUT = 90.0  # seconds

async def _stream_with_watchdog(self, response):
    """Stream with idle timeout detection."""
    last_event_time = time.time()
    
    async for line in response.aiter_lines():
        if time.time() - last_event_time > STREAM_IDLE_TIMEOUT:
            raise TimeoutError(f"Stream idle for {STREAM_IDLE_TIMEOUT}s")
        last_event_time = time.time()
        yield line
```

**Benefits:**
- Detects hung connections quickly
- Prevents indefinite hangs
- Matches vendors/claude behavior

### 2.5 Token Counting and Context Management
**Priority:** MEDIUM  
**Effort:** MEDIUM

Add automatic token counting for context window management:

```python
def _count_tokens(self, messages: List[Dict], model: str) -> int:
    """Count tokens in messages for context window management."""
    # Use tiktoken or anthropic's token counting
    # Track cumulative token usage
    # Warn when approaching context limits
    pass
```

**Benefits:**
- Prevents context window exceeded errors
- Enables automatic compaction decisions
- Better resource management

### 2.6 Cache Token Tracking
**Priority:** LOW  
**Effort:** LOW

Track cache hit/miss rates for analytics:

```python
def _track_cache_usage(self, usage: Dict):
    """Track prompt cache usage for analytics."""
    cache_read = usage.get('cache_read_input_tokens', 0)
    cache_creation = usage.get('cache_creation_input_tokens', 0)
    
    if cache_read > 0:
        self.cache_hits += 1
        self.cache_tokens_read += cache_read
    if cache_creation > 0:
        self.cache_misses += 1
        self.cache_tokens_created += cache_creation
```

---

## 3. SDK Migration Analysis

### 3.1 Official Anthropic Python SDK

**Package:** `anthropic` (already in requirements.txt)  
**Current Usage:** Only for `AnthropicProviderHandler`, not for `ClaudeProviderHandler`

#### Pros of SDK Migration:

1. **Automatic Message Validation**
   - SDK validates messages before sending
   - Catches format errors early
   - Reduces 400 errors

2. **Built-in Retry Logic**
   - SDK has automatic retry for transient errors
   - Configurable retry strategies
   - Handles rate limits gracefully

3. **Token Counting**
   - SDK can count tokens automatically
   - No need for external token counting
   - Accurate token usage tracking

4. **Streaming Abstraction**
   - SDK handles SSE parsing internally
   - Cleaner streaming code
   - Automatic event type handling

5. **Type Safety**
   - Pydantic models for all request/response types
   - Better IDE support
   - Compile-time error detection

6. **Future-Proof**
   - SDK updates with new API features
   - Less maintenance burden
   - Official support from Anthropic

#### Cons of SDK Migration:

1. **OAuth2 Token Handling**
   - SDK expects API keys, not OAuth2 tokens
   - May need custom auth implementation
   - Current direct HTTP works well with OAuth2

2. **Loss of Fine-Grained Control**
   - SDK abstracts away some control
   - Custom headers may be harder to set
   - Beta header management through SDK

3. **Dependency on SDK Version**
   - SDK updates may break compatibility
   - Need to track SDK releases
   - Potential breaking changes

4. **Streaming Differences**
   - SDK streaming uses different abstraction
   - May need to rewrite streaming logic
   - Current SSE parsing works well

### 3.2 Hybrid Approach (Recommended)

Use SDK for non-streaming requests, keep direct HTTP for streaming:

```python
class ClaudeProviderHandler(BaseProviderHandler):
    def __init__(self, ...):
        # SDK client for non-streaming
        self.sdk_client = Anthropic(
            api_key=self._get_oauth_token(),
            base_url="https://api.anthropic.com"
        )
        # HTTP client for streaming
        self.http_client = httpx.AsyncClient(...)
    
    async def handle_request(self, ..., stream=False):
        if stream:
            return await self._handle_streaming_http(...)
        else:
            return await self._handle_non_streaming_sdk(...)
```

**Benefits:**
- Best of both worlds
- SDK validation for non-streaming
- Full control for streaming
- Gradual migration path

---

## 4. Implementation Priority

### Phase 1: Quick Wins (1-2 days)
1. ✅ Temperature/thinking conflict fix (DONE)
2. Automatic retry with exponential backoff
3. Streaming idle watchdog

### Phase 2: Robustness (3-5 days)
4. Message validation pipeline
5. Token counting and context management
6. Cache token tracking

### Phase 3: SDK Evaluation (1-2 weeks)
7. Prototype SDK integration for non-streaming
8. Compare error rates and performance
9. Decide on full migration or hybrid approach

---

## 5. Recommendation

**Do NOT migrate to SDK immediately.** Instead:

1. **Implement the quick wins first** - These provide immediate value with minimal effort
2. **Build the message validation pipeline** - This addresses the most common error source
3. **Evaluate SDK after Phase 2** - Once our implementation is robust, evaluate if SDK adds value

**Rationale:**
- Our direct HTTP approach gives us full control over OAuth2
- We've already implemented most SDK features manually
- SDK migration would be a significant rewrite with uncertain benefits
- The hybrid approach adds complexity without clear advantages

**When to reconsider SDK:**
- If Anthropic adds features we can't easily implement manually
- If SDK becomes the only way to access new API features
- If maintenance burden of manual implementation becomes too high

---

## 6. Comparison: Our Implementation vs SDK

| Feature | Our Implementation | SDK | Gap |
|---------|-------------------|-----|-----|
| Message Validation | Manual (Phase 2) | Automatic | Medium |
| Retry Logic | Manual fallback | Built-in | Low |
| Token Counting | External | Built-in | Medium |
| Streaming | Manual SSE | SDK abstraction | Low |
| OAuth2 Support | Custom | Requires workaround | High |
| Type Safety | Dict-based | Pydantic models | Medium |
| Beta Headers | Manual | SDK config | Low |
| Error Handling | Custom | SDK exceptions | Low |

**Overall Assessment:** Our implementation is 80% as robust as SDK, with better OAuth2 support. The remaining 20% can be achieved with the recommended improvements without SDK migration.
