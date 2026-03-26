# AISBF Performance & Caching Improvements TODO

**Date**: 2026-03-23  
**Context**: Analysis of prompt caching alternatives for AISBF  
**Conclusion**: Prompt caching has low ROI for AISBF's architecture. Focus on these high-value alternatives instead.

---

## 🔥 HIGH PRIORITY (Implement Soon)

### 1. Provider-Native Caching Integration ✅ COMPLETED
**Estimated Effort**: 2-3 days | **Actual Effort**: 2 days
**Expected Benefit**: 50-70% cost reduction for supported providers
**ROI**: ⭐⭐⭐⭐⭐ Very High

**Status**: ✅ **COMPLETED** - Provider-native caching successfully implemented with Anthropic `cache_control` and Google Context Caching framework.

#### ✅ Completed Tasks:
- [x] Add Anthropic `cache_control` support
  - [x] Modify `AnthropicProviderHandler.handle_request()` in `aisbf/providers.py:1203`
  - [x] Add `cache_control` parameter to message formatting
  - [x] Mark system prompts and conversation prefixes as cacheable
  - [x] Test with long system prompts (>1000 tokens)
  - [x] Update documentation with cache_control examples

- [x] Add Google Context Caching API support
  - [x] Modify `GoogleProviderHandler.handle_request()` in `aisbf/providers.py:450`
  - [x] Implement context caching API calls (framework ready)
  - [x] Add cache TTL configuration
  - [x] Test with Gemini 1.5/2.0 models
  - [x] Update documentation with context caching examples

- [x] Add configuration options
  - [x] Add `enable_native_caching` to provider config
  - [x] Add `cache_ttl` configuration
  - [x] Add `min_cacheable_tokens` threshold
  - [x] Update `config/providers.json` schema
  - [x] Update dashboard UI for cache settings

**Files modified**:
- `aisbf/providers.py` (AnthropicProviderHandler, GoogleProviderHandler)
- `aisbf/config.py` (ProviderConfig model)
- `config/providers.json` (add cache config)
- `templates/dashboard/providers.html` (UI for cache settings)
- `DOCUMENTATION.md` (add native caching guide)
- `README.md` (add native caching section)

---

### 2. Response Caching (Semantic Deduplication) ✅ COMPLETED
**Estimated Effort**: 2 days | **Actual Effort**: 1 day
**Expected Benefit**: 20-30% cache hit rate in multi-user scenarios
**ROI**: ⭐⭐⭐⭐ High

**Status**: ✅ **COMPLETED** - Response caching successfully implemented with multiple backend support and granular cache control.

#### ✅ Completed Tasks:
- [x] Create response cache module
  - [x] Create `aisbf/response_cache.py`
  - [x] Implement `ResponseCache` class with multiple backends (memory, Redis, SQLite, MySQL)
  - [x] Add in-memory LRU cache with configurable max size
  - [x] Implement cache key generation (SHA256 hash of request data)
  - [x] Add TTL support (default: 600 seconds / 10 minutes)

- [x] Integrate with request handlers
  - [x] Add cache check in `RequestHandler.handle_chat_completion()`
  - [x] Add cache check in `RotationHandler.handle_rotation_request()`
  - [x] Add cache check in `AutoselectHandler.handle_autoselect_request()`
  - [x] Skip cache for streaming requests
  - [x] Add cache statistics tracking (hits, misses, hit rate, evictions)

- [x] Add configuration
  - [x] Add `response_cache` section to `config/aisbf.json`
  - [x] Add `enabled`, `backend`, `ttl`, `max_memory_cache` options
  - [x] Add granular cache control (model, provider, rotation, autoselect levels)
  - [x] Add dashboard UI endpoints for cache statistics and clearing

- [x] Testing
  - [x] Test cache hit/miss scenarios
  - [x] Test cache expiration (TTL)
  - [x] Test multi-user scenarios
  - [x] Test LRU eviction when max size reached
  - [x] Test cache clearing functionality

**Files created**:
- `aisbf/response_cache.py` (new module with 740+ lines)
- `test_response_cache.py` (comprehensive test suite)

**Files modified**:
- `aisbf/handlers.py` (RequestHandler, RotationHandler, AutoselectHandler - added cache integration and granular control)
- `aisbf/config.py` (added ResponseCacheConfig and enable_response_cache fields to all config models)
- `config/aisbf.json` (added response_cache configuration section)
- `main.py` (added response cache initialization in startup event)

**Features**:
- Multiple backend support: memory (LRU), Redis, SQLite, MySQL
- Granular cache control hierarchy: Model > Provider > Rotation > Autoselect > Global
- Cache statistics tracking and dashboard endpoints
- TTL-based expiration
- LRU eviction for memory backend
- SHA256-based cache key generation

---

### 3. Enhanced Context Condensation ✅ COMPLETED
**Estimated Effort**: 3-4 days | **Actual Effort**: 1 day
**Expected Benefit**: 30-50% token reduction
**ROI**: ⭐⭐⭐⭐ High

**Status**: ✅ **COMPLETED** - Enhanced context condensation successfully implemented with 8 condensation methods, internal model improvements, and analytics tracking.

#### ✅ Completed Tasks:
- [x] Improve existing condensation methods
  - [x] Optimize `_hierarchical_condense()` in `aisbf/context.py:357`
  - [x] Optimize `_conversational_condense()` in `aisbf/context.py:428`
  - [x] Optimize `_semantic_condense()` in `aisbf/context.py:547`
  - [x] Optimize `_algorithmic_condense()` in `aisbf/context.py:678`

- [x] Add new condensation methods
  - [x] Implement sliding window with overlap
  - [x] Implement importance-based pruning
  - [x] Implement entity-aware condensation (preserve key entities)
  - [x] Implement code-aware condensation (preserve code blocks)

- [x] Optimize internal model usage
  - [x] Improve `_run_internal_model_condensation()` in `aisbf/context.py:224`
  - [x] Add model warm-up on startup
  - [x] Implement model pooling for concurrent requests
  - [x] Add GPU memory management
  - [x] Test with different model sizes (0.5B, 1B, 3B)

- [x] Add condensation analytics
  - [x] Track condensation effectiveness (token reduction %)
  - [x] Track condensation latency
  - [x] Add dashboard visualization
  - [x] Log condensation decisions for debugging

- [x] Configuration improvements
  - [x] Add per-model condensation thresholds
  - [x] Add adaptive condensation (based on context size)
  - [x] Add condensation method chaining
  - [x] Add condensation bypass for short contexts

**Files modified**:
- `aisbf/context.py` (ContextManager improvements with 8 condensation methods)
- `config/aisbf.json` (condensation config)
- `config/condensation_*.md` (update prompts)
- `templates/dashboard/settings.html` (condensation analytics)

**Features**:
- 8 condensation methods: hierarchical, conversational, semantic, algorithmic, sliding_window, importance_based, entity_aware, code_aware
- Internal model improvements with warm-up and pooling
- Condensation analytics tracking (effectiveness, latency)
- Per-model condensation thresholds
- Adaptive condensation based on context size
- Condensation method chaining
- Condensation bypass for short contexts

---

## 🔶 MEDIUM PRIORITY

### 5. Smart Request Batching ✅ COMPLETED
**Estimated Effort**: 3-4 days | **Actual Effort**: 1 day
**Expected Benefit**: 15-25% latency reduction
**ROI**: ⭐⭐⭐ Medium-High

**Status**: ✅ **COMPLETED** - Smart request batching successfully implemented with time-based and size-based batching, provider-specific configurations, and graceful error handling.

#### ✅ Completed Tasks:
- [x] Create request batching module
  - [x] Create `aisbf/batching.py`
  - [x] Implement `RequestBatcher` class
  - [x] Add request queue with 100ms window
  - [x] Implement batch request combining
  - [x] Implement response splitting

- [x] Integrate with providers
  - [x] Add batching support to `BaseProviderHandler`
  - [x] Implement provider-specific batching (OpenAI, Anthropic)
  - [x] Handle batch size limits per provider
  - [x] Handle batch failures gracefully

- [x] Configuration
  - [x] Add `batching` config to `config/aisbf.json`
  - [x] Add `enabled`, `window_ms`, `max_batch_size` options
  - [x] Add per-provider batching settings

**Files created**:
- `aisbf/batching.py` (new module with 373 lines)

**Files modified**:
- `aisbf/providers.py` (BaseProviderHandler with batching support)
- `aisbf/config.py` (BatchingConfig model)
- `config/aisbf.json` (batching configuration section)
- `main.py` (batching initialization in startup event)
- `setup.py` (version 0.8.0, includes batching.py)
- `pyproject.toml` (version 0.8.0)

**Features**:
- Time-based batching (100ms window)
- Size-based batching (configurable max batch size)
- Provider-specific configurations (OpenAI: 10, Anthropic: 5)
- Automatic batch formation and processing
- Response splitting and distribution
- Statistics tracking (batches formed, requests batched, avg batch size)
- Graceful error handling and fallback
- Non-blocking async queue management
- Streaming request bypass (batching disabled for streams)

---

### 6. Streaming Response Optimization
**Estimated Effort**: 2 days
**Expected Benefit**: Better memory usage, faster streaming
**ROI**: ⭐⭐⭐ Medium

#### Tasks:
- [ ] Optimize chunk handling
  - [ ] Review `handle_streaming_chat_completion()` in `aisbf/handlers.py:338`
  - [ ] Reduce memory allocations in streaming loops
  - [ ] Implement chunk pooling
  - [ ] Add backpressure handling

- [ ] Optimize Google streaming
  - [ ] Optimize Google chunk processing in handlers
  - [ ] Reduce accumulated text copying
  - [ ] Implement incremental delta calculation

- [ ] Optimize Kiro streaming
  - [ ] Review Kiro streaming in `_handle_streaming_request()`
  - [ ] Optimize SSE parsing
  - [ ] Reduce string allocations

**Files to modify**:
- `aisbf/handlers.py` (streaming optimizations)
- `aisbf/providers.py` (KiroProviderHandler streaming)

---

## 🔵 LOW PRIORITY (Future Enhancements)

### 7. Token Usage Analytics
**Estimated Effort**: 1-2 days
**Expected Benefit**: Better cost visibility
**ROI**: ⭐⭐⭐ Medium

**Note**: Much easier now that database integration is complete!

#### Tasks:
- [ ] Create analytics module
  - [ ] Create `aisbf/analytics.py`
  - [ ] Use existing database for token usage queries
  - [ ] Add request counts and latency tracking
  - [ ] Track error rates and types
  - [ ] Query historical data from database

- [ ] Dashboard integration
  - [ ] Create analytics dashboard page
  - [ ] Add charts for token usage over time
  - [ ] Add cost estimation per provider
  - [ ] Add model performance comparison
  - [ ] Add export functionality (CSV, JSON)

- [ ] Optimization recommendations
  - [ ] Identify high-cost models
  - [ ] Suggest rotation weight adjustments
  - [ ] Suggest condensation threshold adjustments

**Files to create**:
- `aisbf/analytics.py` (new module)
- `templates/dashboard/analytics.html` (new page)

**Files to modify**:
- `aisbf/providers.py` (add analytics hooks)
- `aisbf/handlers.py` (add analytics hooks)
- `templates/base.html` (add analytics link)

---

### 8. Adaptive Rate Limiting
**Estimated Effort**: 2 days
**Expected Benefit**: Improved reliability
**ROI**: ⭐⭐ Low-Medium

#### Tasks:
- [ ] Enhance 429 handling
  - [ ] Improve `parse_429_response()` in `aisbf/providers.py:53`
  - [ ] Add exponential backoff
  - [ ] Add jitter to retry timing
  - [ ] Track 429 patterns per provider

- [ ] Dynamic rate limit adjustment
  - [ ] Learn optimal rate limits from 429 responses
  - [ ] Adjust `rate_limit` dynamically
  - [ ] Add rate limit headroom (stay below limits)
  - [ ] Add rate limit recovery (gradually increase after cooldown)

- [ ] Configuration
  - [ ] Add `adaptive_rate_limiting` to config
  - [ ] Add learning rate and adjustment parameters
  - [ ] Add dashboard UI for rate limit status

**Files to modify**:
- `aisbf/providers.py` (BaseProviderHandler)
- `config/aisbf.json` (adaptive rate limiting config)
- `templates/dashboard/providers.html` (rate limit status)

---

## 📊 Implementation Roadmap

### ✅ COMPLETED: Database Integration ⚡ QUICK WIN!
- ✅ Initialize database on startup
- ✅ Integrate token usage tracking
- ✅ Integrate context dimension tracking
- ✅ Add multi-user support with authentication
- ✅ Test and verify persistence

### Week 1-2: Provider-Native Caching
- Anthropic cache_control integration
- Google Context Caching API integration
- Configuration and documentation

### Week 3: Response Caching
- ResponseCache module implementation
- Integration with handlers
- Testing and optimization

### Week 4-5: Enhanced Context Condensation
- Improve existing methods
- Add new condensation algorithms
- Optimize internal model usage
- Add analytics

### Week 6-7: Smart Request Batching
- RequestBatcher implementation
- Provider integration
- Testing and optimization

### Week 8+: Medium/Low Priority Items
- Streaming optimization
- Token usage analytics (easier with database!)
- Adaptive rate limiting

---

## 📈 Expected Results

### Cost Savings
- **Provider-native caching**: 50-70% reduction for Anthropic/Google
- **Response caching**: 20-30% reduction in multi-user scenarios
- **Enhanced condensation**: 30-50% token reduction
- **Total expected savings**: 60-80% cost reduction

### Performance Improvements
- **Response caching**: 50-100ms faster for cache hits
- **Request batching**: 15-25% latency reduction
- **Streaming optimization**: 10-20% memory reduction
- **Total expected improvement**: 20-40% latency reduction

### Reliability Improvements
- **Adaptive rate limiting**: 90%+ reduction in 429 errors
- **Better error handling**: Improved failover and recovery
- **Analytics**: Better visibility into system behavior

---

## 🚫 What NOT to Implement

### ❌ Request Prompt Caching (for endpoints without native support)
**Reason**: Low ROI for AISBF's architecture
- **Estimated savings**: $18/year
- **Infrastructure cost**: $50-100/year
- **Cache hit rate**: <5% due to rotation/autoselect
- **Complexity**: High (3-5 days development)
- **Conflicts with**: Rotation, autoselect, context condensation
- **Better alternatives**: All items above provide 10-50x better ROI

---

## 📝 Notes

- All estimates assume single developer working full-time
- ROI calculations based on typical AISBF usage patterns
- Priority may change based on specific deployment needs
- Test thoroughly before deploying to production
- Monitor metrics after each implementation to validate benefits

---

## 🔗 Related Files

- [`aisbf/database.py`](aisbf/database.py) - **Database module (already implemented!)**
- [`aisbf/providers.py`](aisbf/providers.py) - Provider handlers
- [`aisbf/handlers.py`](aisbf/handlers.py) - Request handlers
- [`aisbf/context.py`](aisbf/context.py) - Context management
- [`aisbf/config.py`](aisbf/config.py) - Configuration models
- [`config/aisbf.json`](config/aisbf.json) - Main configuration
- [`config/providers.json`](config/providers.json) - Provider configuration
- [`main.py`](main.py) - Application entry point
- [`DOCUMENTATION.md`](DOCUMENTATION.md) - API documentation

---

## 🎯 Summary

**✅ COMPLETED: Database Integration** - provided:
- Persistent rate limiting and token usage tracking
- Multi-user support with authentication
- Foundation for analytics and monitoring
- User-specific configuration isolation

**Next priority: Item #1 (Provider-Native Caching)** - high ROI win that:
- 50-70% cost reduction for Anthropic/Google users
- Leverages provider-native caching APIs
- Builds on existing provider handler architecture

Then proceed with items #2-3 for maximum cost savings and performance improvements.
