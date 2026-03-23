# AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations with unified API interface. AISBF provides intelligent routing, load balancing, and AI-assisted model selection to optimize AI service usage across multiple providers.

## Key Features

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, and Ollama
- **Rotation Models**: Weighted load balancing across multiple providers with automatic failover
- **Autoselect Models**: AI-powered model selection based on content analysis and request characteristics
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
