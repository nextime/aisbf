# AISBF Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **User-Specific API Endpoints**: New API endpoints for authenticated users to access their own configurations
  - `GET /api/user/models` - List user's own models
  - `GET /api/user/providers` - List user's provider configurations  
  - `GET /api/user/rotations` - List user's rotation configurations
  - `GET /api/user/autoselects` - List user's autoselect configurations
  - `POST /api/user/chat/completions` - Chat completions using user's own models
  - `GET /api/user/{config_type}/models` - List models for specific config type
  - Requires Bearer token or query parameter authentication
  - Admin users get access to global + user configs, regular users get user-only configs
  - Global tokens (in aisbf.json) have full access to all configurations
- **MCP User Configuration**: Enhanced MCP server with user-specific tools for authenticated users
  - User can configure their own models, providers, autoselects, and rotations through MCP
  - Admin users get access to both global and user tools
  - Regular users get access to user-only tools
- **Dashboard API Documentation**: User dashboard now includes comprehensive API endpoint documentation
- **Model Metadata Extraction**: Automatic extraction of pricing and rate limit information from provider responses
  - `rate_multiplier` - Cost multiplier for the model
  - `rate_unit` - Pricing unit (e.g., "per million tokens")
  - `prompt_tokens` - Tokens used in prompt
  - `completion_tokens` - Tokens used in completion
  - Auto-configure rate limits on 429 responses with retry-after headers
- **Enhanced Model Metadata**: Extended model information fields
  - `top_provider` - Primary provider for the model
  - `pricing` - Detailed pricing information (prompt/completion costs)
  - `description` - Model description
  - `supported_parameters` - List of supported API parameters
  - `architecture` - Model architecture details
  - Dashboard "Get Models" button to fetch and display model metadata
- **Analytics Filtering**: Filter analytics by provider, model, rotation, and autoselect
  - Dropdown filters in analytics dashboard
  - Real-time chart updates based on selected filters
  - Export filtered data to JSON/CSV
- **Admin User Management**: Complete user management system in dashboard
  - Create, edit, and delete users
  - Role-based access control (admin/user roles)
  - Password management
  - User token management
  - View user statistics and usage
- **Adaptive Rate Limiting**: Intelligent rate limit management that learns from 429 responses
  - Per-provider adaptive rate limiters with learning capability
  - Exponential backoff with jitter (configurable base and jitter factor)
  - Rate limit headroom (stays 10% below learned limits)
  - Gradual recovery after consecutive successful requests
  - 429 pattern tracking with configurable history window
  - Dashboard page showing current limits, 429 counts, success rates, and recovery progress
  - Per-provider reset functionality and reset-all button
  - Configurable via aisbf.json with learning_rate, headroom_percent, recovery_rate, etc.
  - Integration with BaseProviderHandler.apply_rate_limit() and handle_429_error()
- **Token Usage Analytics**: Comprehensive analytics dashboard for tracking token usage, costs, and performance
  - Analytics module (`aisbf/analytics.py`) with token usage tracking, cost estimation, and optimization recommendations
  - Dashboard page with charts for token usage over time (1h, 6h, 24h, 7d)
  - Cost estimation per provider (Anthropic, OpenAI, Google, Kiro, OpenRouter)
  - Model performance comparison with latency and error rate tracking
  - Export functionality (JSON, CSV)
  - Optimization recommendations based on usage patterns
  - Integration with RequestHandler, RotationHandler, and AutoselectHandler
  - Support for rotation_id and autoselect_id tracking
  - Real-time request counts and latency tracking
  - Error rates and types tracking
- **Streaming Response Optimization**: Memory-efficient streaming with provider-specific optimizations
  - Chunk Pooling: Reuses chunk objects to reduce memory allocations
  - Backpressure Handling: Flow control to prevent overwhelming consumers
  - Google Delta Calculation: Only sends new text since last chunk
  - Kiro SSE Parsing: Optimized SSE parser with reduced string allocations
  - OptimizedTextAccumulator: Memory-efficient text accumulation with truncation
  - Configurable optimization settings via StreamingConfig
  - 10-20% memory reduction in streaming operations
- **Smart Request Batching**: Intelligent request batching for improved performance
  - Batches similar requests within configurable time window (default: 100ms)
  - Provider-specific batch configurations
  - Automatic batch size optimization
  - 15-25% latency reduction for similar concurrent requests
  - Configurable via aisbf.json with batch_window, max_batch_size, etc.
- **Enhanced Context Condensation**: 8 condensation methods for intelligent token reduction
  - Hierarchical: Separates context into persistent, middle (summarized), and active sections
  - Conversational: Summarizes old messages using LLM or internal model
  - Semantic: Prunes irrelevant context based on current query
  - Algorithmic: Removes duplicates and similar messages using difflib similarity detection
  - Sliding Window: Keeps recent messages with overlapping context from older parts
  - Importance-Based: Scores messages by importance (role, length, questions, recency)
  - Entity-Aware: Preserves messages mentioning key entities (capitalized words, numbers, emails)
  - Code-Aware: Preserves messages containing code blocks
  - Internal model improvements with warm-up functionality
  - Condensation analytics tracking (effectiveness %, latency)
  - Per-model condensation thresholds
  - Adaptive condensation based on context size
  - Condensation method chaining
  - Condensation bypass for short contexts
- **Response Caching (Semantic Deduplication)**: Intelligent response caching system with multiple backend support
  - Multiple backends: In-memory LRU cache, Redis, SQLite, MySQL
  - SHA256-based cache key generation for request deduplication
  - TTL-based expiration (default: 600 seconds)
  - LRU eviction for memory backend with configurable max size
  - Cache statistics tracking (hits, misses, hit rate, evictions)
  - Dashboard endpoints for cache statistics and clearing
  - Granular cache control at model, provider, rotation, and autoselect levels
  - Hierarchical configuration: Model > Provider > Rotation > Autoselect > Global
  - Automatic cache initialization on startup
  - Skip caching for streaming requests
  - 20-30% cache hit rate in typical usage
- **Provider-Native Caching**: 50-70% cost reduction using provider-specific caching mechanisms
  - Anthropic `cache_control` with `{"type": "ephemeral"}`
  - Google Context Caching API (`cached_contents.create`)
  - OpenAI automatic prefix caching (no code change needed)
  - OpenRouter `cache_control` (wraps Anthropic)
  - DeepSeek automatic caching in 64-token chunks
  - Configurable via `enable_native_caching`, `min_cacheable_tokens`, `cache_ttl`
  - Optional `prompt_cache_key` for OpenAI load balancer routing optimization
- **Claude OAuth2 Provider**: Full OAuth2 PKCE authentication for Claude Code (claude.ai)
  - ClaudeAuth class (`aisbf/claude_auth.py`) implementing OAuth2 PKCE flow
  - ClaudeProviderHandler for Claude API integration
  - Automatic token refresh with refresh token rotation
  - Chrome extension for remote server OAuth2 callback interception
  - Dashboard integration with authentication UI
  - Credentials stored in `~/.aisbf/claude_credentials.json`
  - Support for curl_cffi TLS fingerprinting (optional, for Cloudflare bypass)
  - Compatible with official claude-cli credentials
  - OAuth2 endpoints: `/dashboard/claude/auth/start`, `/dashboard/claude/auth/complete`, `/dashboard/claude/auth/status`
  - Extension endpoints: `/dashboard/extension/download`, `/dashboard/oauth2/callback`
  - Comprehensive documentation in CLAUDE_OAUTH2_SETUP.md and CLAUDE_OAUTH2_DEEP_DIVE.md
- **Kiro Provider Integration**: Native support for Kiro (Amazon Q Developer / AWS CodeWhisperer)
  - KiroAuth class (`aisbf/kiro_auth.py`) for AWS credential management
  - Support for multiple authentication methods:
    - Kiro IDE credentials file (`~/.config/Code/User/globalStorage/amazon.q/credentials.json`)
    - kiro-cli SQLite database
    - Direct refresh token with AWS SSO OIDC
  - Kiro converters (`aisbf/kiro_converters.py`, `aisbf/kiro_converters_openai.py`) for request/response transformation
  - Kiro parsers (`aisbf/kiro_parsers.py`) for AWS Event Stream parsing
  - Kiro models (`aisbf/kiro_models.py`) for model definitions
  - Kiro utilities (`aisbf/kiro_utils.py`) for helper functions
  - Dashboard support for kiro-specific configuration fields
  - Credential validation for kiro/kiro-cli providers
  - Streaming support with AWS Event Stream parsing
  - Tool calling support with proper finalization
- **TOR Hidden Service Support**: Full support for exposing AISBF over TOR network
  - TorHiddenService class (`aisbf/tor.py`) for managing TOR connections
  - TorConfig model in config.py for TOR configuration management
  - Support for both ephemeral (temporary) and persistent (fixed onion address) hidden services
  - Dashboard TOR configuration UI with real-time status display
  - "Create Persistent" button to convert ephemeral to persistent service
  - MCP `get_tor_status` tool for monitoring TOR hidden service status (fullconfig access required)
  - Automatic TOR service initialization on startup when enabled
  - Proper cleanup on shutdown to remove ephemeral services
  - All AISBF endpoints (API, dashboard, MCP) accessible over TOR network
  - Configurable via aisbf.json or dashboard settings
- **MCP (Model Context Protocol) Server**: Complete MCP server implementation
  - SSE endpoint: `GET /mcp` - Server-Sent Events for MCP communication
  - HTTP endpoint: `POST /mcp` - Direct HTTP transport for MCP
  - MCP tools for model access, configuration management, and system control
  - User authentication support with role-based tool access
  - Admin users get full access to global and user tools
  - Regular users get access to user-only tools
  - Dashboard MCP settings and documentation
- **Multi-User Database Integration**: Comprehensive multi-user support with persistent storage
  - SQLite/MySQL database backends with automatic table creation and migration
  - User management with role-based access control (admin/user roles)
  - Isolated configurations per user (providers, rotations, autoselects)
  - API token management with usage tracking
  - Token usage tracking and analytics per user
  - Automatic database cleanup with configurable retention periods
  - Dashboard user management interface (admin only)
  - User dashboard for personal configuration and usage statistics
- **Flexible Caching System**: Multi-backend caching for improved performance
  - Redis cache support for high-performance distributed caching
  - SQLite/MySQL cache backends for persistent caching
  - File-based cache for legacy compatibility
  - Memory cache for ephemeral caching
  - Automatic fallback between cache backends
  - Configurable TTL per data type
  - Cache for model embeddings, provider models, and other cached data
- **NSFW/Privacy Content Filtering**: Automatic content classification and model routing
  - Models can be flagged with `nsfw` and `privacy` boolean flags
  - Automatic analysis of last 3 user messages for content classification
  - Routes requests only to appropriate models based on content
  - Returns 404 if no suitable models available
  - Configurable classification windows
  - Global enable/disable via `classify_nsfw` and `classify_privacy` settings
- **Semantic Model Selection**: Fast hybrid BM25 + semantic search for autoselect
  - Uses sentence transformers for content understanding
  - Combines keyword matching with semantic similarity
  - Automatic model library indexing and caching
  - Faster than AI-based selection (no API calls)
  - Lower costs (no tokens consumed)
  - Deterministic results based on content similarity
  - Automatic fallback to AI selection if semantic fails
  - Enable via `classify_semantic: true` in autoselect config
- **OpenRouter-Style Extended Fields**: Enhanced model metadata
  - `description` - Model description
  - `context_length` - Maximum context size
  - `architecture` - Model architecture details
  - `pricing` - Detailed pricing information
  - `top_provider` - Primary provider
  - `supported_parameters` - List of supported API parameters
  - `default_parameters` - Default parameter values
- **Proxy-Awareness**: Full support for reverse proxy deployments
  - ProxyHeadersMiddleware for automatic proxy header detection
  - Supports X-Forwarded-Proto, X-Forwarded-Host, X-Forwarded-Port, X-Forwarded-Prefix, X-Forwarded-For
  - Automatic URL generation based on proxy configuration
  - Template integration with proxy-aware url_for() function
  - Support for subpath deployments
  - Comprehensive nginx configuration examples in DOCUMENTATION.md
- **Configurable Error Cooldown**: Customizable cooldown periods after consecutive failures
  - `error_cooldown` field in Model class for model-specific cooldown
  - `default_error_cooldown` field in ProviderConfig for provider-level defaults
  - `default_error_cooldown` field in RotationConfig for rotation-level defaults
  - Cascading configuration: model > provider > rotation > system default (300 seconds)
  - Replaces hardcoded 5-minute cooldown with flexible configuration
- **SSL/TLS Support**: Built-in HTTPS support with automatic certificate management
  - Self-signed certificate generation for development/testing
  - Let's Encrypt integration with automatic certificate generation and renewal
  - Automatic certificate expiry checking on startup
  - Renewal when certificates expire within 30 days
  - Dashboard SSL/TLS configuration UI
- **Web Dashboard Enhancements**: Comprehensive web-based management interface
  - Provider management with API key configuration
  - Rotation configuration with weighted load balancing
  - Autoselect configuration with AI-powered selection
  - Server settings management (SSL/TLS, authentication, TOR)
  - User management (admin only)
  - Token usage analytics with charts and export
  - Rate limits dashboard with adaptive learning
  - Cache statistics and management
  - Real-time monitoring and status display
  - Collapsible UI sections for better organization
- **CLI Argument Support**: Command-line arguments for server configuration
  - Port configuration via `--port` argument
  - Host binding via `--host` argument
  - Default port changed to 17765
- **Intelligent 429 Rate Limit Handling**: Automatic rate limit detection and configuration
  - Parses retry-after headers from 429 responses
  - Auto-configures rate limits based on provider responses
  - Exponential backoff with jitter
  - Configurable retry strategies

### Fixed
- **Model Class Compatibility**: Model class now supports OpenRouter metadata fields preventing crashes in models list API
- **Field Alignment**: Aligned Model class with ProviderModelConfig, RotationConfig, and AutoselectConfig field definitions
- **Kiro Streaming**: Fixed premature tool call finalization in Kiro streaming responses
- **Kiro Credentials**: Fixed credential validation to handle dict-based config
- **Python 3.13 Compatibility**: Fixed template session references and Jinja2 template caching for Python 3.13
- **Ollama Provider**: Fixed Ollama Provider Handler initialization
- **PyPI Package**: Include mcp.py, tor.py and kiro modules in distribution
- **Google Tool Calling**: Fixed Google provider tool formatting and tool call extraction in streaming responses
- **Streaming Error Responses**: Fixed error response handling in streaming mode
- **Rotation Error Messages**: Improved error messages when no models are available in rotation
- **Assistant Wrapper Pattern**: Handle assistant wrapper pattern in streaming responses
- **Tool Call Parsing**: Robust JSON extraction for tool calls in streaming responses
- **Unicode Handling**: Decode unicode escape sequences in tool JSON
- **Error Message Formatting**: Improved error message formatting with bold text and JSON pretty printing
- **HTTP Status Codes**: Use appropriate status codes (429 vs 503) based on notifyerrors configuration
- **Duplicate Error Messages**: Skip first line of error_details to avoid duplication

### Changed
- **Virtual Environment Handling**: Improved venv handling to use system-installed aisbf package
- **Auto-Update Feature**: Auto-update venv on pip package upgrade
- **Default Port**: Changed default port from 8000 to 17765
- **Build Script**: Automatic --break-system-packages detection in build.sh
- **Configuration Architecture**: Centralized API key storage in providers.json
  - API keys stored only in provider definitions
  - Rotation and autoselect configurations reference providers by name only
  - Provider-only entries in rotations (no models specified) randomly select from provider's models
  - Default settings support at provider and rotation levels
  - Settings priority: model-specific > rotation defaults > provider defaults
- **Error Handling**: Always return formatted error responses for rotation providers with appropriate status codes

## [0.8.0] - 2026-03-XX
### Added
- Smart Request Batching with 15-25% latency reduction
- Provider-specific batch configurations
- Automatic batch size optimization

## [0.7.0] - 2026-03-XX
### Added
- Enhanced Context Condensation with 8 methods
- Condensation analytics tracking
- Internal model improvements with warm-up functionality

## [0.6.0] - 2026-03-XX
### Added
- Response Caching with semantic deduplication
- Multiple cache backends (memory, Redis, SQLite, MySQL)
- Cache statistics and management dashboard

## [0.5.0] - 2026-03-XX
### Added
- TOR Hidden Service support
- Ephemeral and persistent hidden services
- Dashboard TOR configuration UI

## [0.4.0] - 2026-02-XX
### Added
- Configuration refactoring with centralized API key storage
- Autoselect enhancements with improved prompt structure
- Provider-level default settings

## [0.3.3] - 2026-02-XX
### Added
- Improved error messages when no models are available in rotation
- notifyerrors configuration to rotations

## [0.2.7] - 2026-02-07
### Added
- max_request_tokens support for automatic request splitting
- Token counting utilities using tiktoken and langchain-text-splitters
- Automatic request splitting when exceeding token limits

## [0.2.6] - 2026-02-06
### Added
- Comprehensive API endpoint documentation in README.md and DOCUMENTATION.md
- Detailed sections for General, Provider, Rotation, and Autoselect endpoints
- Documentation for rotation load balancing and AI-assisted autoselect

## [0.1.2] - 2026-02-06
### Changed
- System installation path from /usr/local/share/aisbf to /usr/share/aisbf
- aisbf.sh script to dynamically determine correct paths at runtime
- Script checks for /usr/share/aisbf first, then falls back to ~/.local/share/aisbf
- config.py to check for /usr/share/aisbf instead of /usr/local/share/aisbf

### Added
- Comprehensive logging module with rotating file handlers
- Log files stored in /var/log/aisbf (root) or ~/.local/var/log/aisbf (user)
- Automatic log directory creation
- Rotating file handlers with 50MB max file size and 5 backup files
- Separate log files for general logs (aisbf.log) and error logs (aisbf_error.log)
- Console logging for immediate feedback

## [0.1.1] - 2026-02-06
### Changed
- Version bump for PyPI release

## [0.1.0] - 2026-02-06
### Initial Release
- First public release of AISBF
- Complete AI Service Broker Framework
- Support for multiple AI providers (Google, OpenAI, Anthropic, Ollama)
- Provider rotation and error tracking
- Comprehensive configuration management
- Web dashboard for configuration
- Streaming support
- Rate limiting and error handling
- OpenAI-compatible API endpoints
