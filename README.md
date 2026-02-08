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
- **Effective Context Tracking**: Reports total tokens used (effective_context) for every request

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

### Model Configuration

Models can be configured with the following optional fields:

- **`max_request_tokens`**: Maximum tokens allowed per request. Requests exceeding this limit are automatically split into multiple smaller requests.
- **`rate_limit_TPM`**: Maximum tokens allowed per minute (Tokens Per Minute)
- **`rate_limit_TPH`**: Maximum tokens allowed per hour (Tokens Per Hour)
- **`rate_limit_TPD`**: Maximum tokens allowed per day (Tokens Per Day)
- **`context_size`**: Maximum context size in tokens for the model. Used to determine when to trigger context condensation.
- **`condense_context`**: Percentage (0-100) at which to trigger context condensation. 0 means disabled, any other value triggers condensation when context reaches this percentage of context_size.
- **`condense_method`**: String or list of strings specifying condensation method(s). Supported values: "hierarchical", "conversational", "semantic", "algoritmic". Multiple methods can be chained together.

When token rate limits are exceeded, providers are automatically disabled:
- TPM limit exceeded: Provider disabled for 1 minute
- TPH limit exceeded: Provider disabled for 1 hour
- TPD limit exceeded: Provider disabled for 1 day

### Context Condensation Methods

When context exceeds the configured percentage of `context_size`, the system automatically condenses the prompt using one or more methods:

1. **Hierarchical**: Separates context into persistent (long-term facts) and transient (immediate task) layers
2. **Conversational**: Summarizes old messages using a smaller model to maintain conversation continuity
3. **Semantic**: Prunes irrelevant context based on current query using a smaller "janitor" model
4. **Algoritmic**: Uses mathematical compression for technical data and logs (similar to LLMLingua)

See `config/providers.json` and `config/rotations.json` for configuration examples.

## API Endpoints

### General Endpoints
- `GET /` - Server status and provider list (includes providers, rotations, and autoselect)

### Provider Endpoints
- `POST /api/{provider_id}/chat/completions` - Chat completions for a specific provider
- `GET /api/{provider_id}/models` - List available models for a specific provider

### Rotation Endpoints
- `GET /api/rotations` - List all available rotation configurations
- `POST /api/rotations/chat/completions` - Chat completions using rotation (load balancing across providers)
  - **Rotation Models**: Weighted random selection of models across multiple providers
  - Automatic failover between providers on errors
  - Configurable weights for each model to prioritize preferred options
  - Supports both streaming and non-streaming responses
- `GET /api/rotations/models` - List all models across all rotation configurations

### Autoselect Endpoints
- `GET /api/autoselect` - List all available autoselect configurations
- `POST /api/autoselect/chat/completions` - Chat completions using AI-assisted selection based on content analysis
  - **Autoselect Models**: AI analyzes request content to select the most appropriate model
  - Automatic routing to specialized models based on task type (coding, analysis, creative writing, etc.)
  - Fallback to default model if selection fails
  - Supports both streaming and non-streaming responses
- `GET /api/autoselect/models` - List all models across all autoselect configurations

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
