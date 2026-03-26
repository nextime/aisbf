# AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations with unified API interface. AISBF provides intelligent routing, load balancing, and AI-assisted model selection to optimize AI service usage across multiple providers.

![AISBF Dashboard](screenshot.png)

## Web Dashboard

AISBF includes a comprehensive web-based dashboard for easy configuration and management:

- **Provider Management**: Configure API keys, endpoints, and model settings
- **Rotation Configuration**: Set up weighted load balancing across providers
- **Autoselect Configuration**: Configure AI-powered model selection
- **Server Settings**: Manage SSL/TLS, authentication, and TOR hidden service
- **User Management**: Create/manage users with role-based access control (admin users only)
- **Multi-User Support**: Isolated configurations per user with API token management
- **Real-time Monitoring**: View provider status and configuration

Access the dashboard at `http://localhost:17765/dashboard` (default credentials: admin/admin)

## Key Features

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, Ollama, and Kiro (Amazon Q Developer)
- **Rotation Models**: Weighted load balancing across multiple providers with automatic failover
- **Autoselect Models**: AI-powered model selection based on content analysis and request characteristics
- **Semantic Classification**: Fast hybrid BM25 + semantic model selection using sentence transformers (optional)
- **Content Classification**: NSFW/privacy content filtering with configurable classification windows
- **Streaming Support**: Full support for streaming responses from all providers
- **Error Tracking**: Automatic provider disabling after consecutive failures with cooldown periods
- **Rate Limiting**: Built-in rate limiting and graceful error handling
- **Request Splitting**: Automatic splitting of large requests when exceeding `max_request_tokens` limit
- **Token Rate Limiting**: Per-model token usage tracking with TPM (tokens per minute), TPH (tokens per hour), and TPD (tokens per day) limits
- **Automatic Provider Disabling**: Providers automatically disabled when token rate limits are exceeded
- **Context Management**: Automatic context condensation when approaching model limits with multiple condensation methods
- **Provider-Level Defaults**: Set default condensation settings at provider level with cascading fallback logic
- **Effective Context Tracking**: Reports total tokens used (effective_context) for every request
- **SSL/TLS Support**: Built-in HTTPS support with Let's Encrypt integration and automatic certificate renewal
- **Self-Signed Certificates**: Automatic generation of self-signed certificates for development/testing
- **TOR Hidden Service**: Full support for exposing AISBF over TOR network as a hidden service
- **MCP Server**: Model Context Protocol server for remote agent configuration and model access (SSE and HTTP streaming)
- **Persistent Database**: SQLite-based tracking of token usage, context dimensions, and model embeddings with automatic cleanup
- **Multi-User Support**: User management with isolated configurations, role-based access control, and API token management
- **Database Integration**: SQLite-based persistent storage for user configurations, token usage tracking, and context management
- **User-Specific Configurations**: Each user can have their own providers, rotations, and autoselect configurations stored in the database

## Author

Stefy Lanza <stefy@nexlab.net>

## Repository

Official repository: https://git.nexlab.net/nexlab/aisbf.git

## Quick Start

### Installation

#### From PyPI (Recommended)
```bash
pip install aisbf
```

#### From Source
```bash
python setup.py install
```

### Usage
```bash
aisbf
```

Server starts on `http://127.0.0.1:17765`

## Development

### Building the Package

To build the package for PyPI distribution:

```bash
./build.sh
```

This creates distribution files in the `dist/` directory.

### Cleaning Build Artifacts

To remove all build artifacts and temporary files:

```bash
./clean.sh
```

### PyPI Publishing

See [`PYPI.md`](PYPI.md) for detailed instructions on publishing to PyPI.

## Supported Providers
- Google (google-genai)
- OpenAI and openai-compatible endpoints (openai)
- Anthropic (anthropic)
- Ollama (direct HTTP)
- Kiro (Amazon Q Developer / AWS CodeWhisperer)
## Configuration

### SSL/TLS Configuration

AISBF supports HTTPS with automatic certificate management:

#### Self-Signed Certificates (Default)
- Automatically generated on first run when HTTPS is enabled
- Stored in `~/.aisbf/cert.pem` and `~/.aisbf/key.pem`
- Valid for 365 days
- Suitable for development and internal use

#### Let's Encrypt Integration
Configure a public domain in the dashboard settings to enable Let's Encrypt:
- Automatic certificate generation using certbot
- Automatic renewal when certificates expire within 30 days
- Valid certificates trusted by all browsers
- Requires certbot to be installed on the system

**Installation:**
```bash
# Ubuntu/Debian
sudo apt-get install certbot

# CentOS/RHEL
sudo yum install certbot

# macOS
brew install certbot
```

**Configuration:**
1. Navigate to Dashboard → Settings
2. Set Protocol to "HTTPS"
3. Enter your public domain (e.g., `api.example.com`)
4. Optionally specify custom certificate/key paths
5. Save settings

The system will automatically:
- Generate certificates using Let's Encrypt if a public domain is configured
- Fall back to self-signed certificates if Let's Encrypt fails
- Check certificate expiry on startup
- Renew certificates when they expire within 30 days

### TOR Hidden Service Configuration

AISBF can be exposed over the TOR network as a hidden service, providing anonymous access to your AI proxy server.

#### Prerequisites
- TOR must be installed and running on your system
- TOR control port must be enabled (default: 9051)

**Installation:**
```bash
# Ubuntu/Debian
sudo apt-get install tor

# CentOS/RHEL
sudo yum install tor

# macOS
brew install tor
```

**Enable TOR Control Port:**
Edit `/etc/tor/torrc` (or `~/.torrc` on macOS) and add:
```
ControlPort 9051
CookieAuthentication 1
```

Then restart TOR:
```bash
sudo systemctl restart tor  # Linux
brew services restart tor   # macOS
```

#### Configuration

**Via Dashboard:**
1. Navigate to Dashboard → Settings
2. Scroll to "TOR Hidden Service" section
3. Enable "Enable TOR Hidden Service"
4. Configure settings:
   - **Control Host**: TOR control port host (default: 127.0.0.1)
   - **Control Port**: TOR control port (default: 9051)
   - **Control Password**: Optional password for TOR control authentication
   - **Hidden Service Directory**: Leave blank for ephemeral service, or specify path for persistent service
   - **Hidden Service Port**: Port exposed on the hidden service (default: 80)
   - **SOCKS Proxy Host**: TOR SOCKS proxy host (default: 127.0.0.1)
   - **SOCKS Proxy Port**: TOR SOCKS proxy port (default: 9050)
5. Save settings and restart server

**Via Configuration File:**
Edit `~/.aisbf/aisbf.json`:
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

#### Ephemeral vs Persistent Hidden Services

**Ephemeral (Default):**
- Temporary hidden service created on startup
- New onion address generated each time
- No files stored on disk
- Ideal for temporary or testing purposes
- Set `hidden_service_dir` to `null` or leave blank

**Persistent:**
- Permanent hidden service with fixed onion address
- Address persists across restarts
- Keys stored in specified directory
- Ideal for production use
- Set `hidden_service_dir` to a path (e.g., `~/.aisbf/tor_hidden_service`)

#### Accessing Your Hidden Service

Once enabled, the onion address will be displayed:
- In the server logs on startup
- In the Dashboard → Settings → TOR Hidden Service status section
- Via MCP `get_tor_status` tool (requires fullconfig access)

Access your service via TOR Browser or any TOR-enabled client:
```
http://your-onion-address.onion/
```

#### Security Considerations

- TOR hidden services provide anonymity but not authentication
- Enable API authentication in AISBF settings for additional security
- Use strong dashboard passwords
- Consider using persistent hidden services for production
- Monitor access logs for suspicious activity
- Keep TOR and AISBF updated

### Provider-Level Defaults

Providers can now define default settings that cascade to all models:

- **`default_context_size`**: Default maximum context size for all models in this provider
- **`default_condense_context`**: Default condensation threshold percentage (0-100)
- **`default_condense_method`**: Default condensation method(s) for all models

**Cascading Priority:**
1. Rotation model config (highest priority, only if explicitly set)
2. Provider model-specific config
3. Provider default config (NEW)
4. System defaults

This allows minimal model definitions in rotations - unspecified fields automatically inherit from provider defaults.

### Model Configuration

Models can be configured with the following optional fields:

- **`max_request_tokens`**: Maximum tokens allowed per request. Requests exceeding this limit are automatically split into multiple smaller requests.
- **`rate_limit_TPM`**: Maximum tokens allowed per minute (Tokens Per Minute)
- **`rate_limit_TPH`**: Maximum tokens allowed per hour (Tokens Per Hour)
- **`rate_limit_TPD`**: Maximum tokens allowed per day (Tokens Per Day)
- **`context_size`**: Maximum context size in tokens for the model. Used to determine when to trigger context condensation.
- **`condense_context`**: Percentage (0-100) at which to trigger context condensation. 0 means disabled, any other value triggers condensation when context reaches this percentage of context_size.
- **`condense_method`**: String or list of strings specifying condensation method(s). Supported values: "hierarchical", "conversational", "semantic", "algorithmic". Multiple methods can be chained together.

When token rate limits are exceeded, providers are automatically disabled:
- TPM limit exceeded: Provider disabled for 1 minute
- TPH limit exceeded: Provider disabled for 1 hour
- TPD limit exceeded: Provider disabled for 1 day

### Context Condensation Methods

When context exceeds the configured percentage of `context_size`, the system automatically condenses the prompt using one or more methods:

1. **Hierarchical**: Separates context into persistent (long-term facts) and transient (immediate task) layers - Pure algorithmic, no LLM needed
2. **Conversational**: Summarizes old messages using a smaller model to maintain conversation continuity - LLM-based
3. **Semantic**: Prunes irrelevant context based on current query using a smaller "janitor" model - LLM-based
4. **Algorithmic**: Uses mathematical compression for technical data and logs (similar to LLMLingua) - Pure algorithmic, no LLM needed

**Note:** Only `conversational` and `semantic` methods require LLM calls and use prompt files from `config/`. The `hierarchical` and `algorithmic` methods are pure algorithmic transformations.

See `config/providers.json` and `config/rotations.json` for configuration examples.

### Multi-User Database Integration

AISBF includes comprehensive multi-user support with isolated configurations stored in a SQLite database:

#### User Management
- **Admin Users**: Full access to global configurations and user management
- **Regular Users**: Access to their own configurations and usage statistics
- **Role-Based Access**: Secure separation between admin and user roles

#### Database Features
- **Persistent Storage**: All configurations stored in SQLite database with automatic initialization
- **Token Usage Tracking**: Per-user API token usage statistics and analytics
- **Configuration Isolation**: Each user has separate providers, rotations, and autoselect configurations
- **Automatic Cleanup**: Database maintenance with configurable retention periods

#### User-Specific Configurations
Users can create and manage their own:
- **Providers**: Custom API endpoints, models, and authentication settings
- **Rotations**: Personal load balancing configurations across providers
- **Autoselect**: Custom AI-powered model selection rules
- **API Tokens**: Multiple API tokens with usage tracking and management

#### Dashboard Access
- **Admin Dashboard**: Global configuration management and user administration
- **User Dashboard**: Personal configuration management and usage statistics
- **API Token Management**: Create, view, and delete API tokens with usage analytics

### Content Classification and Semantic Selection

AISBF provides advanced content filtering and intelligent model selection based on content analysis:

#### NSFW/Privacy Content Filtering

Models can be configured with `nsfw` and `privacy` boolean flags to indicate their suitability for sensitive content:

- **`nsfw`**: Model supports NSFW (Not Safe For Work) content
- **`privacy`**: Model supports privacy-sensitive content (e.g., medical, financial, legal data)

When global `classify_nsfw` or `classify_privacy` is enabled, AISBF automatically analyzes the last 3 user messages to classify content and routes requests only to appropriate models. If no suitable models are available, the request returns a 404 error.

**Configuration:**
- Provider models: Set in `config/providers.json`
- Rotation models: Override in `config/rotations.json`
- Global settings: Enable/disable in `config/aisbf.json` or dashboard

#### Semantic Model Selection

For enhanced performance, autoselect configurations can use semantic classification instead of AI model selection:

- **Hybrid BM25 + Semantic Search**: Combines fast keyword matching with semantic similarity
- **Sentence Transformers**: Uses pre-trained embeddings for content understanding
- **Automatic Fallback**: Falls back to AI model selection if semantic classification fails

**Enable Semantic Classification:**
```json
{
  "autoselect": {
    "autoselect": {
      "classify_semantic": true,
      "selection_model": "openai/gpt-4",
      "available_models": [...]
    }
  }
}
```

**Benefits:**
- Faster model selection (no API calls required)
- Lower costs (no tokens consumed for selection)
- Deterministic results based on content similarity
- Automatic model library indexing and caching

See `config/autoselect.json` for configuration examples.

## API Endpoints

### Three Proxy Paths

AISBF provides three ways to proxy AI models:

#### PATH 1: Direct Provider Models
Format: `{provider_id}/{model_name}`
- Access specific models from configured providers
- Example: `openai/gpt-4`, `gemini/gemini-2.0-flash`, `anthropic/claude-3-5-sonnet-20241022`, `kilotest/kilo/free`

#### PATH 2: Rotations
Format: `rotation/{rotation_name}`
- Weighted load balancing across multiple providers
- Automatic failover on errors
- Example: `rotation/coding`, `rotation/general`

#### PATH 3: Autoselect
Format: `autoselect/{autoselect_name}`
- AI-powered model selection based on content analysis
- Automatic routing to specialized models
- Example: `autoselect/autoselect`

### General Endpoints
- `GET /` - Server status and provider list (includes providers, rotations, and autoselect)
- `GET /api/models` - List all available models from all three proxy paths
- `GET /api/v1/models` - OpenAI-compatible model listing (same as `/api/models`)

### Chat Completions

#### Unified Endpoints (Recommended)
These endpoints accept all three proxy path formats in the model field:

**OpenAI-Compatible Format:**
```bash
POST /api/v1/chat/completions
{
  "model": "openai/gpt-4",           # PATH 1: Direct provider
  "messages": [...]
}

POST /api/v1/chat/completions
{
  "model": "rotation/coding",        # PATH 2: Rotation
  "messages": [...]
}

POST /api/v1/chat/completions
{
  "model": "autoselect/autoselect",  # PATH 3: Autoselect
  "messages": [...]
}
```

**Alternative Format:**
```bash
POST /api/{provider_id}/chat/completions
# Where provider_id can be:
# - A provider name (e.g., "openai", "gemini")
# - A rotation name (e.g., "coding", "general")
# - An autoselect name (e.g., "autoselect")
```

### Audio Endpoints
Model specified in request (supports all three proxy paths):

- `POST /api/audio/transcriptions` - Audio transcription
  - Example: `{"model": "openai/whisper-1", "file": ...}` or `{"model": "rotation/coding", "file": ...}`
- `POST /api/audio/speech` - Text-to-speech
  - Example: `{"model": "openai/tts-1", "input": "Hello"}` or `{"model": "rotation/coding", "input": "Hello"}`
- `POST /api/v1/audio/transcriptions` - OpenAI-compatible audio transcription
- `POST /api/v1/audio/speech` - OpenAI-compatible text-to-speech

### Image Endpoints
Model specified in request (supports all three proxy paths):

- `POST /api/images/generations` - Image generation
  - Example: `{"model": "openai/dall-e-3", "prompt": "A cat"}` or `{"model": "rotation/coding", "prompt": "A cat"}`
- `POST /api/v1/images/generations` - OpenAI-compatible image generation

### Embeddings Endpoints
Model specified in request (supports all three proxy paths):

- `POST /api/embeddings` - Text embeddings
  - Example: `{"model": "openai/text-embedding-ada-002", "input": "Hello"}` or `{"model": "rotation/coding", "input": "Hello"}`
- `POST /api/v1/embeddings` - OpenAI-compatible embeddings

### Legacy Endpoints
These endpoints are maintained for backward compatibility:

- `GET /api/rotations` - List all available rotation configurations
- `POST /api/rotations/chat/completions` - Chat completions using rotation (model name = rotation name)
- `GET /api/rotations/models` - List all models across all rotation configurations
- `GET /api/autoselect` - List all available autoselect configurations
- `POST /api/autoselect/chat/completions` - Chat completions using autoselect (model name = autoselect name)
- `GET /api/autoselect/models` - List all models across all autoselect configurations
- `GET /api/{provider_id}/models` - List available models for a specific provider, rotation, or autoselect

### Content Proxy
- `GET /api/proxy/{content_id}` - Proxy generated content (images, audio, etc.)

### Dashboard Endpoints
- `GET /dashboard` - Web-based configuration dashboard
- `GET /dashboard/login` - Dashboard login page
- `POST /dashboard/login` - Handle dashboard authentication
- `GET /dashboard/logout` - Logout from dashboard
- `GET /dashboard/providers` - Edit providers configuration (includes provider-level defaults for condensation)
- `GET /dashboard/rotations` - Edit rotations configuration
- `GET /dashboard/autoselect` - Edit autoselect configuration (supports multiple autoselect configs with "internal" model option)
- `GET /dashboard/settings` - Edit server settings (includes SSL/TLS configuration with Let's Encrypt support)
- `POST /dashboard/restart` - Restart the server

**Dashboard Features:**
- **Provider Configuration**: Set default condensation settings at provider level that cascade to all models
- **Autoselect Configuration**: Configure multiple autoselect models with "internal" option for using local HuggingFace models
- **SSL/TLS Management**: Configure HTTPS with automatic Let's Encrypt certificate generation and renewal
- **Collapsible UI**: All configuration sections use collapsible panels for better organization

## Error Handling
- Rate limiting for failed requests
- Automatic retry with provider rotation
- Proper error tracking and logging
- Fixed streaming response serialization for OpenAI-compatible providers
- Improved autoselect model selection with explicit output requirements

## Donations
The project includes multiple donation options to support its development:

### Ethereum Donation
ETH to 0xdA6dAb526515b5cb556d20269207D43fcc760E51

### PayPal Donation
https://paypal.me/nexlab

### Bitcoin Donation
Address: bc1qcpt2uutqkz4456j5r78rjm3gwq03h5fpwmcc5u
Traditional BTC donation method

## Documentation
See `DOCUMENTATION.md` for complete API documentation, configuration details, and development guides.

## License
GNU General Public License v3.0
