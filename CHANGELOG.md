# AISBF Changelog

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
- OpenRouter-style extended fields to Model class (description, context_length, architecture, pricing, top_provider, supported_parameters, default_parameters)
- Web dashboard section to README with screenshot reference
- Comprehensive dashboard documentation including features and access information
- Kiro AWS Event Stream parsing, converters, and TODO roadmap
- Credential validation for kiro/kiro-cli providers
- TOR hidden service support with persistent/ephemeral options
- MCP (Model Context Protocol) server endpoint
- Proxy-awareness with configurable error cooldown features
- Kiro provider integration
- **Database Configuration**: Support for SQLite and MySQL backends with automatic table creation and migration
- **Flexible Caching System**: Redis, file-based, and memory caching backends for model embeddings and API responses
- **Cache Abstraction Layer**: Unified caching interface with automatic fallback and configurable TTL
- **Redis Cache Support**: High-performance distributed caching for production deployments
- **Database Manager Updates**: Multi-database support with SQL syntax adaptation between SQLite and MySQL
- **Cache Manager**: Configurable cache backends with SQLite, MySQL, Redis, file-based, and memory options with automatic fallback
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
  - Comprehensive test suite with 6 test scenarios
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
- **Streaming Response Optimization**: Memory-efficient streaming with provider-specific optimizations
  - Chunk Pooling: Reuses chunk objects to reduce memory allocations
  - Backpressure Handling: Flow control to prevent overwhelming consumers
  - Google Delta Calculation: Only sends new text since last chunk
  - Kiro SSE Parsing: Optimized SSE parser with reduced string allocations
  - OptimizedTextAccumulator: Memory-efficient text accumulation with truncation
  - Configurable optimization settings via StreamingConfig

### Fixed
- Model class now supports OpenRouter metadata fields preventing crashes in models list API
- Aligned Model class with ProviderModelConfig, RotationConfig, and AutoselectConfig field definitions
- Premature tool call finalization in Kiro streaming responses
- Kiro credential validation to handle dict-based config
- Template session references for Python 3.13 compatibility
- Python 3.13 compatibility issue with Jinja2 template caching
- Ollama Provider Handler initialization
- PyPI package: include mcp.py, tor.py and kiro modules in distribution

### Changed
- Improved venv handling to use system-installed aisbf package
- Auto-update venv feature on pip package upgrade
- Default port changed to 17765
- Intelligent 429 rate limit handling and improved configuration
- Automatic --break-system-packages detection in build.sh

## [0.1.2] - 2026-02-06
### Changed
- Updated version from 0.1.1 to 0.1.2 for PyPI release
- Changed system installation path from /usr/local/share/aisbf to /usr/share/aisbf
- Updated aisbf.sh script to dynamically determine correct paths at runtime
- Script now checks for /usr/share/aisbf first, then falls back to ~/.local/share/aisbf
- Updated setup.py to install script with dynamic path detection
- Updated config.py to check for /usr/share/aisbf instead of /usr/local/share/aisbf
- Updated AI.PROMPT documentation to reflect new installation paths
- Script creates venv in appropriate location based on installation type
- Ensures proper main.py location is used regardless of who launches the script

### Added
- Comprehensive logging module with rotating file handlers
- Log files stored in /var/log/aisbf when launched by root
- Log files stored in ~/.local/var/log/aisbf when launched by user
- Automatic log directory creation if it doesn't exist
- Rotating file handlers with 50MB max file size and 5 backup files
- Separate log files for general logs (aisbf.log) and error logs (aisbf_error.log)
- stdout and stderr output duplicated to rotating log files
- Console logging for immediate feedback
- Logging configuration in main.py with proper setup function
- Updated aisbf.sh script to redirect output to log files
- Updated setup.py to include logging configuration in installed script

## [0.1.1] - 2026-02-06
### Changed
- Updated version from 0.1.0 to 0.1.1 for PyPI release

## [0.1.0] - 2026-02-06
### Initial Release
- First public release of AISBF
- Complete AI Service Broker Framework
- Support for multiple AI providers
- Provider rotation and error tracking
- Comprehensive configuration management