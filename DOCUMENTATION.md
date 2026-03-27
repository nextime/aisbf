# AISBF - AI Service Broker Framework || AI Should Be Free

## Overview

AISBF is a modular proxy server for managing multiple AI provider integrations. It provides a unified API interface for interacting with various AI services (Google, OpenAI, Anthropic, Ollama) with support for provider rotation, AI-assisted model selection, and error tracking.

### Key Features

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, Ollama, and Kiro (Amazon Q Developer)
- **Rotation Models**: Intelligent load balancing across multiple providers with weighted model selection and automatic failover
- **Autoselect Models**: AI-powered model selection that analyzes request content to route to the most appropriate specialized model
- **Streaming Support**: Full support for streaming responses from all providers with proper serialization
- **Error Tracking**: Automatic provider disabling after consecutive failures with configurable cooldown periods
- **Rate Limiting**: Built-in rate limiting and graceful error handling with persistent tracking across restarts
- **Provider-Native Caching**: 50-70% cost reduction using Anthropic `cache_control` and Google Context Caching APIs
- **Persistent Database**: SQLite-based tracking of token usage, context dimensions, and model embeddings with automatic cleanup
- **Multi-User Support**: User management with isolated configurations, role-based access control, and API token management
- **Security**: Default localhost-only access for improved security
- **Token Usage Analytics**: Comprehensive analytics dashboard with token usage tracking, cost estimation, model performance comparison, and optimization recommendations
- **Token Usage Analytics**: Comprehensive analytics dashboard for tracking token usage, costs, and performance with charts and export functionality

## Author

Stefy Lanza <stefy@nexlab.net>

## Repository

Official repository: https://git.nexlab.net/nexlab/aisbf.git

## Project Structure

```
geminiproxy/
├── aisbf/                    # Main Python module
│   ├── __init__.py          # Module initialization with exports
│   ├── config.py            # Configuration management
│   ├── models.py            # Pydantic models
│   ├── providers.py         # Provider handlers
│   ├── handlers.py          # Request handlers
│   ├── providers.json       # Default provider configs (moved to config/)
│   └── rotations.json       # Default rotation configs (moved to config/)
├── config/                   # Configuration files directory
│   ├── providers.json       # Default provider configurations
│   └── rotations.json       # Default rotation configurations
├── main.py                   # FastAPI application entry point
├── setup.py                  # Installation script
├── pyproject.toml            # Modern packaging configuration
├── MANIFEST.in               # Package manifest for distribution
├── build.sh                  # Build script for PyPI packages
├── clean.sh                  # Clean script for build artifacts
├── start_proxy.sh           # Development start script
├── aisbf.sh                 # Alternative start script
├── requirements.txt         # Python dependencies
├── INSTALL.md               # Installation guide
├── PYPI.md                 # PyPI publishing guide
└── README.md                # Project documentation
```

## Installation

### User Installation (no root required)
```bash
python setup.py install
```

Installs to:
- `~/.local/lib/python*/site-packages/aisbf/` - Package
- `~/.local/aisbf-venv/` - Virtual environment
- `~/.local/share/aisbf/` - Config files
- `~/.local/bin/aisbf` - Executable script

### System-wide Installation (requires root)
```bash
sudo python setup.py install
```

Installs to:
- `/usr/local/lib/python*/dist-packages/aisbf/` - Package
- `/usr/local/aisbf-venv/` - Virtual environment
- `/usr/local/share/aisbf/` - Config files
- `/usr/local/bin/aisbf` - Executable script

## Configuration Management

### Configuration File Locations

**Installed Configuration Files (read-only defaults):**
- User: `~/.local/share/aisbf/providers.json`, `~/.local/share/aisbf/rotations.json`
- System: `/usr/local/share/aisbf/providers.json`, `/usr/local/share/aisbf/rotations.json`

**User Configuration Files (writable):**
- `~/.aisbf/providers.json` - Provider configurations
- `~/.aisbf/rotations.json` - Rotation configurations

**Development Mode:**
- `config/providers.json` and `config/rotations.json` in source tree

### First Run Behavior
1. Checks for config files in installed location
2. Creates `~/.aisbf/` directory if needed
3. Copies default configs from installed location to `~/.aisbf/`
4. Loads configuration from `~/.aisbf/` on subsequent runs

## TOR Hidden Service Support

AISBF includes full support for exposing the API and dashboard over the TOR network as a hidden service. This provides anonymous access to your AI proxy server without revealing your server's IP address.

### Prerequisites

**TOR Installation:**
```bash
# Ubuntu/Debian
sudo apt-get install tor

# CentOS/RHEL
sudo yum install tor

# macOS
brew install tor
```

**Python stem Library:**
```bash
pip install stem
```

**Enable TOR Control Port:**

Edit `/etc/tor/torrc` (or `~/.torrc` on macOS):
```
ControlPort 9051
CookieAuthentication 1
```

Restart TOR:
```bash
sudo systemctl restart tor  # Linux
brew services restart tor   # macOS
```

### Configuration

TOR hidden service can be configured via the dashboard or configuration file.

**Configuration File (`~/.aisbf/aisbf.json`):**
```json
{
  "tor": {
    "enabled": true,
    "control_port": 9051,
    "control_host": "127.0.0.1",
    "control_password": null,
    "hidden_service_dir": null,
    "hidden_service_port": 80,
    "socks_port": 9050,
    "socks_host": "127.0.0.1"
  }
}
```

**Configuration Options:**

- **`enabled`**: Enable/disable TOR hidden service (default: false)
- **`control_port`**: TOR control port (default: 9051)
- **`control_host`**: TOR control host (default: 127.0.0.1)
- **`control_password`**: Optional password for TOR control authentication
- **`hidden_service_dir`**: Directory for persistent hidden service keys (null for ephemeral)
- **`hidden_service_port`**: Port exposed on the hidden service (default: 80)
- **`socks_port`**: TOR SOCKS proxy port (default: 9050)
- **`socks_host`**: TOR SOCKS proxy host (default: 127.0.0.1)

### Ephemeral vs Persistent Hidden Services

**Ephemeral Hidden Service (Default):**
- Temporary service created on startup
- New onion address generated each time
- No files stored on disk
- Ideal for testing or temporary deployments
- Set `hidden_service_dir` to `null`

**Persistent Hidden Service:**
- Permanent service with fixed onion address
- Address persists across restarts
- Keys stored in specified directory
- Ideal for production use
- Set `hidden_service_dir` to a path (e.g., `~/.aisbf/tor_hidden_service`)

Example persistent configuration:
```json
{
  "tor": {
    "enabled": true,
    "hidden_service_dir": "~/.aisbf/tor_hidden_service",
    "hidden_service_port": 80
  }
}
```

### Dashboard Configuration

1. Navigate to **Dashboard → Settings**
2. Scroll to **TOR Hidden Service** section
3. Enable **Enable TOR Hidden Service** checkbox
4. Configure options as needed
5. Save settings and restart server

The dashboard displays:
- Current TOR status (Active/Disabled/Error)
- Onion address (when active)
- Real-time status updates

### Accessing the Hidden Service

Once enabled, the onion address is displayed:
- In server logs on startup
- In Dashboard → Settings → TOR Hidden Service status
- Via MCP `get_tor_status` tool (fullconfig access required)

Access via TOR Browser or TOR-enabled client:
```
http://your-onion-address.onion/
```

All AISBF endpoints are available over TOR:
- API endpoints: `http://your-onion-address.onion/api/v1/chat/completions`
- Dashboard: `http://your-onion-address.onion/dashboard`
- MCP server: `http://your-onion-address.onion/mcp`

### Security Considerations

**Authentication:**
- TOR provides anonymity, not authentication
- Enable API authentication in AISBF settings
- Use strong dashboard passwords
- Consider IP-based access controls for clearnet access

**Best Practices:**
- Use persistent hidden services for production
- Regularly update TOR and AISBF
- Monitor access logs for suspicious activity
- Enable rate limiting
- Use HTTPS for clearnet access (TOR handles encryption)

**Network Isolation:**
- TOR traffic is automatically encrypted
- Hidden services don't reveal server IP
- Consider running AISBF in isolated environment
- Use firewall rules to restrict clearnet access

### Troubleshooting

**Connection Failed:**
- Verify TOR is running: `systemctl status tor` or `brew services list`
- Check TOR control port is enabled in torrc
- Verify control port is accessible: `telnet 127.0.0.1 9051`
- Check AISBF logs for detailed error messages

**Authentication Failed:**
- Verify CookieAuthentication is enabled in torrc
- Check control_password matches torrc configuration
- Ensure AISBF has permission to read TOR cookie file

**Onion Address Not Generated:**
- Check TOR logs: `journalctl -u tor` or `tail -f /var/log/tor/log`
- Verify hidden_service_dir permissions (if using persistent)
- Ensure stem library is installed: `pip list | grep stem`

**Service Not Accessible:**
- Verify AISBF is running and listening on configured port
- Check hidden_service_port matches AISBF local port
- Test local access first: `curl http://localhost:17765`
- Verify TOR Browser is configured correctly

### MCP Integration

The MCP server includes a `get_tor_status` tool for monitoring TOR hidden service status:

```json
{
  "method": "tools/call",
  "params": {
    "name": "get_tor_status",
    "arguments": {}
  }
}
```

Response includes:
- `enabled`: Whether TOR is enabled
- `connected`: Connection status to TOR control port
- `onion_address`: Current onion address (if active)
- `service_id`: Service ID for ephemeral services
- `control_host` and `control_port`: TOR control connection details

## Database Features

AISBF includes a comprehensive database system that provides persistent tracking and multi-user support, with support for both SQLite (default) and MySQL databases:

### Database Schema

The database (`~/.aisbf/aisbf.db`) contains the following tables:

#### Core Tracking Tables
- **`context_dimensions`**: Tracks context size, condensation settings, and effective context per model
- **`token_usage`**: Persistent token usage tracking with TPM/TPH/TPD rate limiting across restarts
- **`model_embeddings`**: Caches model embeddings for semantic classification performance

#### Multi-User Tables
- **`users`**: User management with authentication, roles (admin/user), and metadata
- **`user_providers`**: Isolated provider configurations per user (JSON stored configurations)
- **`user_rotations`**: Isolated rotation configurations per user (JSON stored configurations)
- **`user_autoselects`**: Isolated autoselect configurations per user (JSON stored configurations)
- **`user_api_tokens`**: API token management per user for MCP and API access
- **`user_token_usage`**: Per-user token usage tracking and analytics

### Database Backends

AISBF supports two database backends:

#### SQLite (Default)
- **Recommended for most users**: No additional setup required
- **File-based**: Single database file stored in `~/.aisbf/aisbf.db`
- **Zero configuration**: Works out of the box
- **Performance**: Excellent for typical workloads

#### MySQL
- **For advanced users**: Requires MySQL server setup
- **Network-based**: Can be hosted on separate server
- **Scalability**: Better for high-traffic deployments
- **Features**: Full MySQL feature set and ecosystem

### Database Configuration

Database backend can be configured via the web dashboard or configuration file:

**Configuration File (`~/.aisbf/aisbf.json`):**
```json
{
  "database": {
    "type": "sqlite",  // or "mysql"
    "sqlite_path": "~/.aisbf/aisbf.db",
    "mysql_host": "localhost",
    "mysql_port": 3306,
    "mysql_user": "aisbf",
    "mysql_password": "your-password",
    "mysql_database": "aisbf"
  }
}
```

**Dashboard Configuration:**
1. Navigate to **Dashboard → Settings**
2. Scroll to **Database Configuration** section
3. Select database type (SQLite or MySQL)
4. Configure connection parameters as needed
5. Save settings and restart server

**Migration Notes:**
- Switching between database types requires manual data migration
- SQLite to MySQL: Use tools like `sqlite3-to-mysql` or manual export/import
- MySQL to SQLite: Use MySQL export and SQLite import tools
- All database schemas are compatible between backends

### Database Initialization

The database is automatically initialized on startup:
- WAL mode enabled for better concurrency (SQLite)
- Foreign key constraints enabled
- Automatic cleanup of old records (>7 days)
- Schema migrations handled automatically
- Compatible schema across all supported database backends

### Multi-User Support

AISBF supports multiple users with complete isolation through database-backed configurations:

#### User Authentication System
- **Database-First Authentication**: User credentials stored in SQLite database with SHA256 password hashing
- **Config Admin Fallback**: Legacy config-based admin authentication for backward compatibility
- **Role-Based Access Control**: Two roles - `admin` (full access) and `user` (isolated access)
- **Session-Based Authentication**: Secure session management for dashboard access

#### User Isolation Architecture
Each user has completely isolated configurations stored as JSON in the database:

- **Provider Configurations**: `user_providers` table stores individual API keys, endpoints, and model settings
- **Rotation Configurations**: `user_rotations` table stores personal load balancing rules
- **Autoselect Configurations**: `user_autoselects` table stores custom AI-assisted model selection rules
- **API Tokens**: `user_api_tokens` table manages multiple API tokens per user
- **Usage Tracking**: `user_token_usage` table provides per-user analytics and rate limiting

#### Handler Architecture
The system uses user-specific handler instances that load configurations from the database:

```python
# Handler instantiation with user context
request_handler = RequestHandler(user_id=user_id)
rotation_handler = RotationHandler(user_id=user_id)
autoselect_handler = AutoselectHandler(user_id=user_id)

# Automatic loading of user configs
handler.user_providers = db.get_user_providers(user_id)
handler.user_rotations = db.get_user_rotations(user_id)
handler.user_autoselects = db.get_user_autoselects(user_id)
```

#### Configuration Priority
When processing requests, handlers check for user-specific configurations first:

1. **User-specific configs** (from database)
2. **Global configs** (from JSON files)
3. **System defaults**

#### Admin Features
- Create and manage users via database
- Full access to global configurations and user management
- System-wide analytics and monitoring
- User administration dashboard

#### User Dashboard Features
- **Personal Configuration Management**: Create/edit/delete provider, rotation, and autoselect configs
- **Usage Statistics**: Real-time token usage tracking and analytics
- **API Token Management**: Generate, view, and delete API tokens
- **Isolated Access**: No visibility of other users' configurations or system settings

### Persistent Tracking

#### Token Usage Tracking
- Persistent across application restarts
- TPM/TPH/TPD rate limiting maintained
- Per-user and per-provider tracking
- Automatic cleanup of old records

#### Context Dimension Tracking
- Context size monitoring per model
- Condensation effectiveness tracking
- Effective context reporting in API responses
- Analytics foundation for optimization

#### Model Embeddings Caching
- Semantic classification performance optimization
- Automatic model library indexing
- Reduced API calls for autoselect operations
- Cached embeddings for faster similarity matching

### Cache Configuration

AISBF includes a flexible caching system for model embeddings and other performance-critical data:

#### Cache Backends

##### SQLite Cache (Default)
- **Recommended for most users**: No additional services required
- **Persistent**: Cache survives application restarts
- **Database-backed**: Structured storage with automatic cleanup
- **Performance**: Fast local database access
- **Storage**: Uses `~/.aisbf/cache.db` file

##### MySQL Cache
- **For database users**: Shares MySQL server with main database
- **Network-based**: Can be hosted on separate server
- **Scalability**: Better for multi-server deployments
- **Features**: Full MySQL feature set and ecosystem

##### Redis Cache
- **For performance**: Requires Redis server
- **Distributed**: Can be shared across multiple AISBF instances
- **Memory-based**: Extremely fast access
- **Scalability**: Better for high-traffic deployments

##### File-based Cache
- **Legacy option**: Simple file-based storage
- **Persistent**: Cache survives application restarts
- **Basic**: No advanced features like TTL or cleanup
- **Storage**: Uses `~/.aisbf/cache/` directory

##### Memory Cache
- **For development**: In-memory only
- **Fastest**: No disk I/O
- **Temporary**: Lost on application restart
- **Limited**: Not suitable for production use

##### Memory Cache
- **For development**: In-memory only
- **Fastest**: No disk I/O
- **Temporary**: Lost on application restart
- **Limited**: Not suitable for production use

#### Cache Configuration

Cache backend can be configured via the web dashboard or configuration file:

**Configuration File (`~/.aisbf/aisbf.json`):**
```json
{
  "cache": {
    "type": "sqlite",  // "sqlite", "mysql", "redis", "file", or "memory"
    "sqlite_path": "~/.aisbf/cache.db",
    "mysql_host": "localhost",
    "mysql_port": 3306,
    "mysql_user": "aisbf",
    "mysql_password": "your-password",
    "mysql_database": "aisbf_cache",
    "redis_host": "localhost",
    "redis_port": 6379,
    "redis_db": 0,
    "redis_password": null,
    "redis_key_prefix": "aisbf:"
  }
}
```

**Dashboard Configuration:**
1. Navigate to **Dashboard → Settings**
2. Scroll to **Cache Configuration** section
3. Select cache type (File-based, Redis, or Memory)
4. Configure connection parameters as needed (for Redis)
5. Save settings and restart server

**Cache Features:**
- **Model Embeddings**: Semantic classification model embeddings
- **TTL Support**: Configurable time-to-live for cache entries
- **Automatic Fallback**: Falls back to memory cache if Redis is unavailable
- **Key Prefixing**: Redis keys are prefixed to avoid conflicts

### Backup and Maintenance

- Automatic cleanup removes records older than 7 days
- WAL mode ensures data integrity
- Database file can be backed up manually from `~/.aisbf/aisbf.db`
- No external dependencies required (uses built-in SQLite)

## API Endpoints

### General Endpoints
- `GET /` - Returns server status and list of available providers, rotations, and autoselect configurations

### Provider Endpoints
- `POST /api/{provider_id}/chat/completions` - Handle chat completion requests for a specific provider
  - Supports both streaming and non-streaming responses
- `GET /api/{provider_id}/models` - List available models for a specific provider

### Rotation Endpoints
- `GET /api/rotations` - List all available rotation configurations
- `POST /api/rotations/chat/completions` - Chat completions using rotation (load balancing across providers)
  - **Rotation Models**: Weighted random selection of models across multiple providers
  - Automatic failover between providers on errors
  - Configurable weights for each model to prioritize preferred options
  - Supports both streaming and non-streaming responses
  - Error tracking and rate limiting per provider
- `GET /api/rotations/models` - List all models across all rotation configurations

### Autoselect Endpoints
- `GET /api/autoselect` - List all available autoselect configurations
- `POST /api/autoselect/chat/completions` - Chat completions using AI-assisted selection based on content analysis
  - **Autoselect Models**: AI analyzes request content to select the most appropriate model
  - Automatic routing to specialized models based on task type:
    - Coding/Programming tasks → Models optimized for code generation
    - Analysis tasks → Models optimized for reasoning and problem-solving
    - Creative tasks → Models optimized for creative writing
    - General queries → General-purpose models
  - Fallback to default model if selection fails
  - Supports both streaming and non-streaming responses
- `GET /api/autoselect/models` - List all models across all autoselect configurations

## Provider Support

AISBF supports the following AI providers:

### Google
- Uses google-genai SDK
- Requires API key
- Supports streaming and non-streaming responses

### OpenAI
- Uses openai SDK
- Requires API key
- Supports streaming and non-streaming responses

### Anthropic
- Uses anthropic SDK
- Requires API key
- Static model list (no dynamic model discovery)

### Ollama
- Uses direct HTTP API
- No API key required
- Local model hosting support

### Kiro (Amazon Q Developer / AWS CodeWhisperer)
- Native integration with Kiro authentication
- Supports IDE credentials and CLI authentication
- Access to Claude models through Kiro
- No separate API key required (uses Kiro credentials)
- Supports streaming, tool calling, and extended thinking

## Rotation Models

AISBF supports provider rotation with weighted model selection, allowing intelligent load balancing across multiple AI providers:

### How Rotation Models Work

Rotation models provide automatic load balancing and failover by:
1. **Weighted Selection**: Each model is assigned a weight that determines its selection probability
2. **Automatic Failover**: If a provider fails, the system automatically tries the next best model
3. **Error Tracking**: Providers are temporarily disabled after 3 consecutive failures (5-minute cooldown)
4. **Rate Limiting**: Respects provider rate limits to avoid service disruptions

### Rotation Configuration
```json
{
  "rotations": {
    "my_rotation": {
      "providers": [
        {
          "provider_id": "openai",
          "models": [
            {"name": "gpt-4", "weight": 1},
            {"name": "gpt-3.5-turbo", "weight": 3}
          ]
        },
        {
          "provider_id": "anthropic",
          "models": [
            {"name": "claude-3-haiku-20240307", "weight": 2}
          ]
        }
      ]
    }
  }
}
```

### Rotation Behavior

When using rotation models:
- Models with higher weights are selected more frequently
- The system automatically retries with alternative models on failures
- Failed providers are temporarily disabled and automatically re-enabled after cooldown
- All requests are logged for monitoring and debugging

### Example Use Cases

- **High Availability**: Configure multiple providers with the same model for redundancy
- **Cost Optimization**: Use cheaper models with higher weights, fallback to expensive models when needed
- **Performance**: Prioritize faster models, fallback to slower models if they fail
- **Geographic Distribution**: Route requests to providers in different regions

## Autoselect Models

AISBF supports AI-assisted model selection that automatically routes requests to the most appropriate model based on content analysis:

### How Autoselect Models Work

Autoselect models use AI to analyze the user's request and select the best model:
1. **Content Analysis**: The AI analyzes the request to determine task type, complexity, and domain
2. **Model Matching**: Matches request characteristics to available model capabilities
3. **Automatic Routing**: Routes the request to the most suitable model
4. **Fallback**: Uses a default model if selection fails or is uncertain

### Semantic Classification (New Feature)

Autoselect configurations can now use semantic classification instead of AI model selection for faster and potentially more accurate model selection:

- **Hybrid BM25 + Semantic Search**: Combines fast keyword matching with semantic similarity using sentence transformers
- **Automatic Model Library Indexing**: Builds and caches model embeddings for efficient similarity matching
- **Performance Optimized**: No API calls required, significantly faster than AI-based selection
- **Fallback Support**: Falls back to AI model selection if semantic classification fails

**Enable Semantic Classification:**
```json
{
  "autoselect": {
    "smart": {
      "classify_semantic": true,
      "selection_model": "openai/gpt-4",
      "available_models": [...]
    }
  }
}
```

**Benefits:**
- Faster model selection (no API costs)
- Deterministic results based on semantic similarity
- Automatic model library caching in `~/.aisbf/`
- Lower latency for model selection

### Content Classification and Filtering (New Feature)

AISBF provides advanced content classification for NSFW and privacy-sensitive content:

#### NSFW/Privacy Content Filtering

Models can be configured with boolean flags to indicate their suitability for sensitive content:
- **`nsfw`**: Model supports NSFW (Not Safe For Work) content
- **`privacy`**: Model supports privacy-sensitive content (medical, financial, legal data)

When global `classify_nsfw` or `classify_privacy` is enabled, AISBF analyzes the last 3 user messages and routes requests only to appropriate models. If no suitable models are available, requests return a 404 error.

**Configuration Levels (cascading priority):**
1. Rotation model config (highest priority)
2. Provider model config
3. Global AISBF config (enables/disables classification)

**Example Model Configuration:**
```json
{
  "models": [
    {
      "name": "gpt-4",
      "nsfw": true,
      "privacy": true
    },
    {
      "name": "gpt-3.5-turbo",
      "nsfw": false,
      "privacy": true
    }
  ]
}
```

**Global Classification Settings:**
```json
{
  "classify_nsfw": true,
  "classify_privacy": true
}
```

**Content Classification Window:**
- Only analyzes the last 3 user messages for performance
- Avoids processing full conversation history
- Uses HuggingFace transformers for content analysis
- Automatic fallback if classification models are unavailable

### Autoselect Configuration

```json
{
  "autoselect": {
    "smart": {
      "model_name": "smart",
      "description": "AI-assisted model selection",
      "fallback": "general",
      "available_models": [
        {
          "model_id": "coding",
          "description": "Best for programming, code generation, debugging, and technical tasks"
        },
        {
          "model_id": "analysis",
          "description": "Best for analysis, reasoning, and problem-solving"
        },
        {
          "model_id": "creative",
          "description": "Best for creative writing, storytelling, and content generation"
        },
        {
          "model_id": "general",
          "description": "General purpose model for everyday tasks and conversations"
        }
      ]
    }
  }
}
```

### Autoselect Behavior

When using autoselect models:
- The AI analyzes the request content to determine the best model
- Requests are automatically routed to specialized models based on task type
- The system provides explicit output requirements to ensure reliable model selection
- Falls back to a default model if selection is uncertain

### Example Use Cases

- **Intelligent Routing**: Automatically route coding tasks to code-optimized models
- **Cost Efficiency**: Use cheaper models for simple tasks, expensive models for complex ones
- **User Experience**: Provide optimal responses without manual model selection
- **Adaptive Selection**: Dynamically adjust model selection based on request characteristics

## Context Management

AISBF provides intelligent context management to handle large conversation histories and prevent exceeding model context limits:

### How Context Management Works

Context management automatically monitors and condenses conversation context:

1. **Effective Context Tracking**: Calculates and reports total tokens used (effective_context) for every request
2. **Automatic Condensation**: When context exceeds configured percentage of model's context_size, triggers condensation
3. **Multiple Condensation Methods**: Supports 8 condensation methods including hierarchical, conversational, semantic, algorithmic, sliding window, importance-based, entity-aware, and code-aware condensation
4. **Method Chaining**: Multiple condensation methods can be applied in sequence for optimal results
5. **Condensation Analytics**: Tracks effectiveness (token reduction %) and latency for each condensation operation

### Context Configuration

Models can be configured with context management fields:

```json
{
  "models": [
    {
      "name": "gemini-2.0-flash",
      "context_size": 1000000,
      "condense_context": 80,
      "condense_method": ["hierarchical", "semantic"]
    }
  ]
}
```

**Configuration Fields:**
- **`context_size`**: Maximum context size in tokens for the model
- **`condense_context`**: Percentage (0-100) at which to trigger condensation. 0 means disabled
- **`condense_method`**: String or list of strings specifying condensation method(s)

### Condensation Methods

#### 1. Hierarchical Context Engineering
Separates context into persistent (long-term facts) and transient (immediate task) layers:
- **Persistent State**: Architecture, project state, core principles
- **Recent History**: Summarized conversation history
- **Active Code**: High-fidelity current code
- **Instruction**: Current task/goal

#### 2. Conversational Summarization (Memory Buffering)
Replaces old messages with high-density summaries:
- Uses a smaller model to summarize conversation progress
- Maintains continuity without hitting token caps
- Preserves key facts, decisions, and current goals

#### 3. Semantic Context Pruning (Observation Masking)
Removes irrelevant details based on current query:
- Uses a smaller "janitor" model to extract relevant facts
- Can reduce history by 50-80% without losing critical information
- Focuses on information relevant to the specific current request

#### 4. Algoritmic Token Compression
Mathematical compression for technical data and logs:
- Similar to LLMLingua compression
- Achieves up to 20x compression for technical data
- Removes low-information tokens systematically

### Effective Context Reporting

All responses include `effective_context` in the usage field:

**Non-streaming responses:**
```json
{
  "usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 500,
    "total_tokens": 1500,
    "effective_context": 1000
  }
}
```

**Streaming responses:**
The final chunk includes effective_context:
```json
{
  "usage": {
    "prompt_tokens": null,
    "completion_tokens": null,
    "total_tokens": null,
    "effective_context": 1000
  }
}
```

### Example Use Cases

- **Long Conversations**: Maintain context across extended conversations without hitting limits
- **Code Analysis**: Handle large codebases with intelligent context pruning
- **Document Processing**: Process large documents with automatic summarization
- **Multi-turn Tasks**: Maintain task context across multiple interactions

## Provider-Native Caching

AISBF supports provider-native caching APIs to dramatically reduce costs by caching reusable content like system prompts and conversation prefixes. This feature provides 50-70% cost reduction for supported providers.

### Supported Providers

#### Anthropic (cache_control)
Anthropic's `cache_control` feature allows caching of system messages and conversation prefixes to reduce API costs.

**Features:**
- **Automatic Detection**: System messages and long conversation prefixes are automatically marked as cacheable
- **Token Threshold**: Configurable minimum token count for content to be cacheable (default: 1000)
- **Ephemeral Caching**: Uses Anthropic's ephemeral cache type for optimal performance

#### Google (Context Caching)
Google's Context Caching API allows caching of conversation context for reuse across multiple requests.

**Features:**
- **TTL Support**: Configurable cache time-to-live (default: 3600 seconds / 1 hour)
- **Framework Ready**: Configuration and logging infrastructure in place for future full implementation

### Configuration

Provider-native caching can be configured via the web dashboard or configuration file:

#### Dashboard Configuration
1. Navigate to **Dashboard → Providers**
2. Select the provider (Anthropic or Google)
3. Enable **Native Caching** checkbox
4. Configure **Cache TTL** (Google only, in seconds)
5. Set **Min Cacheable Tokens** (minimum token count for cacheable content)
6. Save settings

#### Configuration File (`~/.aisbf/providers.json`)

```json
{
  "providers": {
    "anthropic": {
      "id": "anthropic",
      "name": "Anthropic",
      "endpoint": "https://api.anthropic.com/v1",
      "type": "anthropic",
      "api_key_required": true,
      "api_key": "YOUR_ANTHROPIC_API_KEY",
      "enable_native_caching": true,
      "cache_ttl": null,
      "min_cacheable_tokens": 1000
    },
    "gemini": {
      "id": "gemini",
      "name": "Google AI Studio",
      "endpoint": "https://generativelanguage.googleapis.com/v1beta",
      "type": "google",
      "api_key_required": true,
      "api_key": "YOUR_GEMINI_API_KEY",
      "enable_native_caching": true,
      "cache_ttl": 3600,
      "min_cacheable_tokens": 1000
    }
  }
}
```

### Configuration Fields

- **`enable_native_caching`**: Enable/disable native caching for this provider (default: false)
- **`cache_ttl`**: Cache time-to-live in seconds (Google only, default: 3600)
- **`min_cacheable_tokens`**: Minimum token count for content to be cacheable (default: 1000)

### How It Works

#### Anthropic Caching Logic
When `enable_native_caching: true` for Anthropic:

1. **System Messages**: Always marked as cacheable with `{"type": "ephemeral"}`
2. **Conversation Prefixes**: Messages before the last 2 are evaluated for caching
3. **Token Counting**: Cumulative token count determines cache eligibility
4. **Automatic Application**: Eligible messages get `cache_control` parameter automatically

**Example of cached request:**
```json
{
  "model": "claude-3-haiku-20240307",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant...",
      "cache_control": {"type": "ephemeral"}
    },
    {
      "role": "user",
      "content": "Tell me about...",
      "cache_control": {"type": "ephemeral"}
    },
    {
      "role": "assistant",
      "content": "Let me explain..."
    },
    {
      "role": "user",
      "content": "What about..."
    }
  ]
}
```

#### Google Context Caching
Google's Context Caching API requires separate cache creation and reference calls:

1. **Cache Creation**: Content is cached using dedicated API calls
2. **Cache References**: Subsequent requests reference cached content by ID
3. **TTL Management**: Automatic cache expiration and cleanup
4. **Cost Optimization**: Significant reduction in input token costs

**Note**: Full Google Context Caching implementation is planned for future releases. Current version includes configuration framework and logging.

### Cost Savings

**Expected Cost Reductions:**
- **Anthropic**: 50-70% reduction for requests with cacheable content
- **Google**: 50-70% reduction for supported Gemini models (when fully implemented)

**Factors Affecting Savings:**
- **System Prompt Length**: Longer system prompts provide higher savings
- **Conversation Reuse**: Repeated conversation patterns maximize cache hits
- **Token Threshold**: Higher `min_cacheable_tokens` focuses caching on substantial content

### Best Practices

1. **Enable for Production**: Enable caching for production workloads with consistent prompts
2. **Monitor Usage**: Check logs for cache application statistics
3. **Tune Thresholds**: Adjust `min_cacheable_tokens` based on your use case
4. **Test Thoroughly**: Verify caching doesn't affect response quality

### Monitoring

Cache usage is logged in AISBF's application logs:

```
AnthropicProviderHandler: Applied cache_control to message 0 (1250 tokens, cumulative: 1250)
AnthropicProviderHandler: Applied cache_control to message 1 (850 tokens, cumulative: 2100)
GoogleProviderHandler: Native caching enabled but not yet implemented
```

### Troubleshooting

**Caching Not Applied:**
- Verify `enable_native_caching: true` in provider configuration
- Check that content exceeds `min_cacheable_tokens` threshold
- Ensure system messages are present for Anthropic

**Configuration Not Taking Effect:**
- Restart AISBF after configuration changes
- Check provider configuration in dashboard
- Verify JSON syntax in configuration files

## Error Tracking and Rate Limiting

### Error Tracking
- Tracks failures per provider
- Disables providers after 3 consecutive failures
- Configurable cooldown period for disabled providers (default: 5 minutes)
- Automatic re-enabling after cooldown period expires

### Configurable Error Cooldown

The cooldown period after 3 consecutive failures can be configured at multiple levels with cascading defaults:

**Configuration Levels (in order of precedence):**
1. **Model-specific**: Set `error_cooldown` in individual model configuration
2. **Provider default**: Set `default_error_cooldown` in provider configuration
3. **System default**: 300 seconds (5 minutes) if not configured

**Example Provider Configuration:**
```json
{
  "providers": {
    "openai": {
      "id": "openai",
      "name": "OpenAI",
      "endpoint": "https://api.openai.com/v1",
      "type": "openai",
      "api_key_required": true,
      "default_error_cooldown": 600,
      "models": [
        {
          "name": "gpt-4",
          "error_cooldown": 900
        },
        {
          "name": "gpt-3.5-turbo",
          "error_cooldown": 300
        }
      ]
    }
  }
}
```

In this example:
- `gpt-4` will have a 900-second (15-minute) cooldown after failures
- `gpt-3.5-turbo` will have a 300-second (5-minute) cooldown
- Any other OpenAI models will use the provider default of 600 seconds (10 minutes)
- Providers without configuration will use the system default of 300 seconds

**Rotation Configuration:**
```json
{
  "rotations": {
    "balanced": {
      "model_name": "balanced",
      "default_error_cooldown": 450,
      "providers": [...]
    }
  }
}
```

### Rate Limiting
- Automatic provider disabling when rate limited
- Intelligent parsing of 429 responses to determine wait time
- Graceful error handling
- Configurable retry behavior

## Development vs Production

### Development
Use `start_proxy.sh`:
- Creates local venv in `./venv/`
- Installs dependencies from `requirements.txt`
- Starts server with auto-reload enabled
- Uses `config/` directory for configuration

### Production
Install with `python setup.py install`:
- Creates isolated venv
- Installs all dependencies
- Provides `aisbf` command with daemon support
- Uses installed config files

## PyPI Packaging

### Building the Package

To build the package for PyPI distribution:

```bash
./build.sh
```

This script:
- Checks for build tools (build, twine)
- Installs them if not present
- Cleans previous build artifacts
- Builds the package using `python -m build`
- Verifies the package with `twine check`
- Displays created files and upload instructions

### Cleaning Build Artifacts

To remove all build artifacts and temporary files:

```bash
./clean.sh
```

This removes:
- `dist/` directory (distribution packages)
- `build/` directory (build artifacts)
- `*.egg-info` directories (package metadata)
- `__pycache__/` directories (Python bytecode cache)
- `*.pyc`, `*.pyo`, `*.pyd` files (compiled Python files)
- `.pytest_cache/`, `.mypy_cache/` directories
- `.coverage` file, `htmlcov/` directory

### Package Structure

The package includes:
- **Python Module**: `aisbf/` directory with all Python code
- **Configuration Files**: `config/` directory with JSON configs
- **Main Application**: `main.py` - FastAPI application
- **Documentation**: `README.md`, `DOCUMENTATION.md`
- **License**: `LICENSE.txt` (GPL-3.0-or-later)
- **Requirements**: `requirements.txt`

### Installation from PyPI

Users can install AISBF with:

```bash
# User installation (recommended)
pip install aisbf

# System-wide installation (requires root)
sudo pip install aisbf
```

### Publishing to PyPI

See [`PYPI.md`](PYPI.md) for detailed instructions on:
- Setting up PyPI account and API tokens
- Building and testing packages
- Publishing to TestPyPI and PyPI
- Version management
- Troubleshooting

## AISBF Script Commands

### Starting in Foreground (Default)
```bash
aisbf
```
Starts server in foreground with visible output on `http://127.0.0.1:17765`.

### Starting as Daemon
```bash
aisbf daemon
```
- Starts in background on `http://127.0.0.1:17765`
- Saves PID to `/tmp/aisbf.pid`
- Redirects output to `/dev/null`
- Prints PID of started process

### Checking Status
```bash
aisbf status
```
Checks if AISBF is running and reports status/PID.

### Stopping the Daemon
```bash
aisbf stop
```
Stops running daemon and removes PID file.

## Proxy Deployment

AISBF is fully proxy-aware and can be deployed behind reverse proxies like nginx, Apache, or Caddy. The application automatically detects and respects standard proxy headers to ensure correct URL generation and routing.

### Proxy-Awareness Features

AISBF automatically handles:
- **X-Forwarded-Proto**: Detects original protocol (http/https)
- **X-Forwarded-Host**: Detects original hostname
- **X-Forwarded-Port**: Detects original port
- **X-Forwarded-Prefix** or **X-Script-Name**: Detects URL subpath/prefix
- **X-Forwarded-For**: Detects original client IP address

All URLs in the dashboard, redirects, and API responses are automatically adjusted based on these headers.

### Nginx Proxy Configuration Examples

#### Example 1: Simple Reverse Proxy (Root Path)

Deploy AISBF at the root of a domain (e.g., `https://aisbf.example.com/`):

```nginx
server {
    listen 80;
    server_name aisbf.example.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name aisbf.example.com;
    
    # SSL configuration
    ssl_certificate /etc/ssl/certs/aisbf.example.com.crt;
    ssl_certificate_key /etc/ssl/private/aisbf.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Proxy settings
    location / {
        proxy_pass http://127.0.0.1:17765;
        proxy_http_version 1.1;
        
        # Proxy headers for AISBF proxy-awareness
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # WebSocket support for streaming
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts for long-running requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Buffering settings for streaming
        proxy_buffering off;
        proxy_cache off;
    }
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Logging
    access_log /var/log/nginx/aisbf_access.log;
    error_log /var/log/nginx/aisbf_error.log;
}
```

#### Example 2: Reverse Proxy with Subpath

Deploy AISBF at a subpath (e.g., `https://example.com/aisbf/`):

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;
    
    # SSL configuration
    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # AISBF at /aisbf subpath
    location /aisbf/ {
        # Remove /aisbf prefix before proxying
        rewrite ^/aisbf/(.*) /$1 break;
        
        proxy_pass http://127.0.0.1:17765;
        proxy_http_version 1.1;
        
        # Proxy headers for AISBF proxy-awareness
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # IMPORTANT: Set the subpath prefix
        proxy_set_header X-Forwarded-Prefix /aisbf;
        
        # WebSocket support for streaming
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts for long-running requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Buffering settings for streaming
        proxy_buffering off;
        proxy_cache off;
    }
    
    # Other locations for your main application
    location / {
        # Your main application configuration
        root /var/www/html;
        index index.html;
    }
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Logging
    access_log /var/log/nginx/example_access.log;
    error_log /var/log/nginx/example_error.log;
}
```

#### Example 3: Load Balancing Multiple AISBF Instances

Deploy multiple AISBF instances for high availability:

```nginx
upstream aisbf_backend {
    # Multiple AISBF instances
    server 127.0.0.1:17765 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:17766 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:17767 max_fails=3 fail_timeout=30s;
    
    # Load balancing method
    least_conn;  # Route to instance with fewest connections
    
    # Session persistence (optional, for dashboard sessions)
    ip_hash;
}

server {
    listen 443 ssl http2;
    server_name aisbf.example.com;
    
    # SSL configuration
    ssl_certificate /etc/ssl/certs/aisbf.example.com.crt;
    ssl_certificate_key /etc/ssl/private/aisbf.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    location / {
        proxy_pass http://aisbf_backend;
        proxy_http_version 1.1;
        
        # Proxy headers for AISBF proxy-awareness
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # WebSocket support for streaming
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts for long-running requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Buffering settings for streaming
        proxy_buffering off;
        proxy_cache off;
        
        # Health check
        proxy_next_upstream error timeout http_502 http_503 http_504;
    }
    
    # Health check endpoint
    location /health {
        proxy_pass http://aisbf_backend/health;
        access_log off;
    }
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Logging
    access_log /var/log/nginx/aisbf_access.log;
    error_log /var/log/nginx/aisbf_error.log;
}
```

#### Example 4: API-Only Deployment with Rate Limiting

Deploy AISBF as an API-only service with rate limiting:

```nginx
# Define rate limiting zones
limit_req_zone $binary_remote_addr zone=aisbf_api:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=aisbf_dashboard:10m rate=5r/s;

server {
    listen 443 ssl http2;
    server_name api.example.com;
    
    # SSL configuration
    ssl_certificate /etc/ssl/certs/api.example.com.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # API endpoints with rate limiting
    location /api/ {
        # Apply rate limiting
        limit_req zone=aisbf_api burst=20 nodelay;
        
        proxy_pass http://127.0.0.1:17765;
        proxy_http_version 1.1;
        
        # Proxy headers for AISBF proxy-awareness
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # WebSocket support for streaming
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts for long-running AI requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        
        # Buffering settings for streaming
        proxy_buffering off;
        proxy_cache off;
        
        # CORS headers (if needed)
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    }
    
    # Dashboard with stricter rate limiting
    location /dashboard/ {
        limit_req zone=aisbf_dashboard burst=10 nodelay;
        
        proxy_pass http://127.0.0.1:17765;
        proxy_http_version 1.1;
        
        # Proxy headers for AISBF proxy-awareness
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Standard proxy settings
        proxy_buffering off;
    }
    
    # Block all other paths
    location / {
        return 404;
    }
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Logging
    access_log /var/log/nginx/aisbf_api_access.log;
    error_log /var/log/nginx/aisbf_api_error.log;
}
```

### Testing Proxy Configuration

After configuring nginx, test the setup:

1. **Test nginx configuration:**
   ```bash
   sudo nginx -t
   ```

2. **Reload nginx:**
   ```bash
   sudo systemctl reload nginx
   ```

3. **Test AISBF through proxy:**
   ```bash
   # Test root endpoint
   curl https://aisbf.example.com/
   
   # Test with subpath
   curl https://example.com/aisbf/
   
   # Test API endpoint
   curl -X POST https://aisbf.example.com/api/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "provider/model-name", "messages": [{"role": "user", "content": "Hello"}]}'
   ```

4. **Check dashboard URLs:**
   - Open the dashboard in a browser
   - Verify all links and redirects work correctly
   - Check that the restart button uses the correct URL

### Troubleshooting Proxy Issues

If you encounter issues:

1. **Check nginx error logs:**
   ```bash
   sudo tail -f /var/log/nginx/aisbf_error.log
   ```

2. **Verify proxy headers are being sent:**
   - Check AISBF logs for received headers
   - Enable debug logging in AISBF if needed

3. **Common issues:**
   - **404 errors with subpath**: Ensure `X-Forwarded-Prefix` header is set correctly
   - **Redirect loops**: Check that `X-Forwarded-Proto` is set to `https`
   - **Broken dashboard links**: Verify all proxy headers are configured
   - **Streaming not working**: Ensure `proxy_buffering off` is set

### Security Considerations

When deploying behind a proxy:

1. **Bind AISBF to localhost only** (default: `127.0.0.1:17765`)
2. **Use HTTPS** for all external connections
3. **Enable authentication** in AISBF configuration
4. **Configure rate limiting** in nginx
5. **Set security headers** in nginx configuration
6. **Keep SSL certificates up to date**
7. **Monitor access logs** for suspicious activity

## Key Classes and Functions

### aisbf/config.py
- `Config` - Configuration management class
- `ProviderConfig` - Provider configuration model
- `RotationConfig` - Rotation configuration model
- `AppConfig` - Application configuration model

### aisbf/models.py
- `Message` - Chat message structure
- `ChatCompletionRequest` - Request model
- `ChatCompletionResponse` - Response model
- `Model` - Model information (includes context_size, condense_context, condense_method fields)
- `Provider` - Provider information
- `ErrorTracking` - Error tracking data

### aisbf/providers.py
- `BaseProviderHandler` - Base provider handler class
- `GoogleProviderHandler` - Google provider implementation
- `OpenAIProviderHandler` - OpenAI provider implementation
- `AnthropicProviderHandler` - Anthropic provider implementation
- `OllamaProviderHandler` - Ollama provider implementation
- `get_provider_handler()` - Factory function for provider handlers

### aisbf/context.py
- `ContextManager` - Context management class for automatic condensation
- `get_context_config_for_model()` - Retrieves context configuration from provider or rotation model config

### aisbf/handlers.py
- `RequestHandler` - Request handling logic with streaming support and context management
- `RotationHandler` - Rotation handling logic with streaming support and context management
- `AutoselectHandler` - AI-assisted model selection with streaming support

## Dependencies

Key dependencies from requirements.txt:
- fastapi - Web framework
- uvicorn - ASGI server
- pydantic - Data validation
- httpx - HTTP client
- google-genai - Google AI SDK
- openai - OpenAI SDK
- anthropic - Anthropic SDK
- langchain-text-splitters - Intelligent text splitting for request chunking
- tiktoken - Accurate token counting for context management

## Adding New Providers

### Steps to Add a New Provider
1. Create handler class in `aisbf/providers.py` inheriting from `BaseProviderHandler`
2. Add to `PROVIDER_HANDLERS` dictionary
3. Add provider configuration to `config/providers.json`

### Provider Handler Requirements
- Implement `handle_request()` method
- Implement `get_models()` method
- Handle error tracking and rate limiting

## Configuration Examples

### Provider Configuration
```json
{
  "providers": {
    "openai": {
      "id": "openai",
      "name": "OpenAI",
      "endpoint": "https://api.openai.com/v1",
      "type": "openai",
      "api_key_required": true
    }
  }
}
```

### Rotation Configuration
```json
{
  "rotations": {
    "balanced": {
      "providers": [
        {
          "provider_id": "openai",
          "models": [
            {"name": "gpt-4", "weight": 1},
            {"name": "gpt-3.5-turbo", "weight": 3}
          ]
        },
        {
          "provider_id": "anthropic",
          "models": [
            {"name": "claude-3-haiku-20240307", "weight": 2}
          ]
        }
      ]
    }
  }
}
```

## Testing and Development

### Development Workflow
1. Use `start_proxy.sh` for development
2. Test with `start_proxy.sh` for development
3. Install with `python setup.py install` for production testing
4. Test all `aisbf` script commands (default, daemon, status, stop)
5. Verify configuration file locations and behavior
6. Test both user and system installations
7. Test streaming responses with OpenAI-compatible providers
8. Verify autoselect model selection returns only the model ID tag

### Common Development Tasks
- Adding new providers
- Modifying configuration
- Updating installation
- Testing error handling

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

## Version 0.3.0 Changes

### Streaming Improvements
- Fixed streaming response serialization for OpenAI-compatible providers
- Properly serialize Stream chunks to JSON format
- Convert ChatCompletionChunk objects before yielding
- Resolves socket.send() exceptions during streaming

### Autoselect Enhancements
- Made autoselect skill file more explicit about output requirements
- Added prominent warnings about outputting ONLY the model selection tag
- Improved reliability of AI-assisted model selection

### Security Improvements
- Changed default listening address from 0.0.0.0:8000 to 127.0.0.1:17765
- Server now only accepts connections from localhost by default

## Contributing

When making changes:
1. Update AI.PROMPT file with significant changes
2. Test all functionality including streaming
3. Update documentation as needed
4. Follow the project's coding conventions
5. Ensure all tests pass
6. Verify localhost-only access when appropriate

## Support

For support and questions:
- Check the AI.PROMPT file for project-specific instructions
- Review the INSTALL.md file for installation details
- Check the README.md file for project overview
- Test with development scripts before production deployment

## Donations

The extension includes multiple donation options to support its development:

### Ethereum Donation
ETH to 0xdA6dAb526515b5cb556d20269207D43fcc760E51

### PayPal Donation
https://paypal.me/nexlab

### Bitcoin Donation
Address: bc1qcpt2uutqkz4456j5r78rjm3gwq03h5fpwmcc5u
Traditional BTC donation method
