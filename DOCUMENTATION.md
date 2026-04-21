# AISBF - AI Service Broker Framework || AI Should Be Free

## Overview

AISBF is a modular proxy server for managing multiple AI provider integrations. It provides a unified API interface for interacting with various AI services (Google, OpenAI, Anthropic, Claude Code, Ollama, Kiro, Kilocode, Codex, Qwen) with support for provider rotation, AI-assisted model selection, unified wallet system, and error tracking.

### Key Features

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, Claude Code (OAuth2), Ollama, Kiro (Amazon Q Developer), Kilocode (OAuth2), Codex (OAuth2), and Qwen (API Key/OAuth2)
- **Unified Wallet System**: Fiat wallet with crypto/PayPal/Stripe top-ups and auto top-up for subscription renewals
- **Claude OAuth2 Authentication**: Full OAuth2 PKCE flow for Claude Code with automatic token refresh, Chrome extension for remote servers, and curl_cffi TLS fingerprinting support
- **Kiro-cli Support**: Full support for Amazon Q Developer CLI authentication with Device Authorization Grant
- **Kilocode OAuth2 Authentication**: OAuth2 Device Authorization Grant for Kilo Code with automatic token refresh
- **Codex OAuth2 Authentication**: OAuth2 Device Authorization Grant for OpenAI Codex with automatic token refresh and API key exchange
- **Qwen Authentication**: API key authentication (recommended) or OAuth2 (discontinued as of April 2026)
- **Rotation Models**: Intelligent load balancing across multiple providers with weighted model selection and automatic failover
- **Autoselect Models**: AI-powered model selection that analyzes request content to route to the most appropriate specialized model
- **Semantic Classification**: Fast hybrid BM25 + semantic model selection using sentence transformers (optional)
- **Content Classification**: NSFW/privacy content filtering with configurable classification windows
- **Streaming Support**: Full support for streaming responses from all providers with proper serialization
- **Error Tracking**: Automatic provider disabling after consecutive failures with configurable cooldown periods
- **Adaptive Rate Limiting**: Intelligent rate limit management that learns from 429 responses with exponential backoff, gradual recovery, and dashboard monitoring
- **Provider-Native Caching**: 50-70% cost reduction using Anthropic `cache_control`, Google Context Caching, and OpenAI-compatible APIs
- **Response Caching**: 20-30% cache hit rate with intelligent request deduplication using SHA256-based cache keys
- **Smart Request Batching**: 15-25% latency reduction by batching similar requests within 100ms window
- **Token Usage Analytics**: Comprehensive analytics dashboard with token usage tracking, cost estimation, performance metrics, and export functionality
- **Context Management**: Automatic context condensation with 8+ methods when approaching model limits
- **SSL/TLS Support**: Built-in HTTPS support with Let's Encrypt integration and automatic certificate renewal
- **TOR Hidden Service**: Full support for exposing AISBF over TOR network as a hidden service
- **MCP Server**: Model Context Protocol server for remote agent configuration and model access
- **Persistent Database**: SQLite/MySQL-based tracking of token usage, context dimensions, model embeddings, and user configurations
- **Multi-User Support**: User management with isolated configurations, role-based access control, and API token management
- **User-Specific API Endpoints**: Dedicated API endpoints for authenticated users to access their own configurations with Bearer token authentication
- **Proxy-Awareness**: Full support for reverse proxy deployments with automatic URL generation and subpath support

## Project Structure

```
aisbf/
├── aisbf/                        # Main Python module
│   ├── __init__.py               # Module initialization with exports
│   ├── config.py                 # Configuration management
│   ├── models.py                 # Pydantic models
│   ├── providers.py              # Provider handlers
│   ├── handlers.py               # Request handlers
│   ├── payments/                 # Payment system
│   │   ├── __init__.py
│   │   ├── models.py             # Payment models
│   │   ├── service.py            # Payment service
│   │   ├── fiat/                 # Fiat payment handlers
│   │   │   ├── __init__.py
│   │   │   ├── stripe_handler.py # Stripe integration
│   │   │   └── paypal_handler.py # PayPal integration
│   │   ├── crypto/               # Crypto payment handlers
│   │   │   ├── __init__.py
│   │   │   ├── wallet.py         # HD wallet manager
│   │   │   └── monitor.py        # Crypto payment monitor
│   │   ├── subscription/         # Subscription management
│   │   │   ├── __init__.py
│   │   │   ├── manager.py        # Subscription lifecycle
│   │   │   ├── renewal.py        # Renewal processing
│   │   │   └── quota.py          # Quota management
│   │   └── wallet/               # Wallet system (NEW)
│   │       ├── __init__.py
│   │       └── manager.py        # Wallet operations
│   ├── notifications/            # Notification system
│   ├── __init__.py
│   └── [other modules...]
├── config/                       # Configuration files
│   ├── providers.json            # Default provider configs
│   ├── rotations.json            # Default rotation configs
│   ├── autoselect.json           # Default autoselect configs
│   └── aisbf.json                # Main configuration
├── templates/                    # HTML templates
│   └── dashboard/                # Dashboard templates
├── static/                       # Static assets (CSS, JS, images)
├── docs/                         # Documentation
├── main.py                       # FastAPI application entry point
├── cli.py                        # Command-line interface
├── setup.py                      # Installation script
├── pyproject.toml                # Modern packaging configuration
├── requirements.txt              # Python dependencies
├── README.md                     # Project overview
└── DOCUMENTATION.md              # Comprehensive documentation (this file)
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

### Development Installation
```bash
./start_proxy.sh
```

Creates local virtual environment and installs in development mode with auto-reload.

## Configuration

### Configuration File Locations

**Installed Configuration Files (read-only defaults):**
- User: `~/.local/share/aisbf/providers.json`, `~/.local/share/aisbf/rotations.json`
- System: `/usr/local/share/aisbf/providers.json`, `/usr/local/share/aisbf/rotations.json`

**User Configuration Files (writable):**
- `~/.aisbf/providers.json` - Provider configurations
- `~/.aisbf/rotations.json` - Rotation configurations
- `~/.aisbf/autoselect.json` - Autoselect configurations
- `~/.aisbf/aisbf.json` - Main server configuration

**Development Mode:**
- `config/providers.json` and `config/rotations.json` in source tree

### First Run Behavior
1. Checks for config files in installed location
2. Creates `~/.aisbf/` directory if needed
3. Copies default configs from installed location to `~/.aisbf/`
4. Loads configuration from `~/.aisbf/` on subsequent runs

### Main Configuration (aisbf.json)
```json
{
  "host": "127.0.0.1",
  "port": 17765,
  "database": {
    "type": "sqlite",
    "sqlite_path": "~/.aisbf/aisbf.db"
  },
  "cache": {
    "type": "sqlite",
    "sqlite_path": "~/.aisbf/cache.db"
  },
  "ssl": {
    "enabled": false,
    "cert_file": null,
    "key_file": null
  },
  "tor": {
    "enabled": false,
    "control_port": 9051,
    "control_host": "127.0.0.1"
  },
  "adaptive_rate_limiting": {
    "enabled": true,
    "learning_rate": 0.1,
    "headroom_percent": 10
  },
  "response_cache": {
    "enabled": true,
    "backend": "memory",
    "ttl": 600
  }
}
```

## Wallet System

AISBF includes a comprehensive unified wallet system that manages user fiat balances for subscription payments and provides multiple top-up methods.

### Features

- **Unified Fiat Wallet**: Single wallet per user in system-configured currency
- **Multiple Top-Up Methods**: Crypto (BTC, ETH, USDT, USDC), PayPal, Stripe (credit cards)
- **Auto Top-Up**: Automatic balance replenishment when subscription renewal fails
- **Transaction History**: Complete audit trail of all wallet operations
- **Subscription Integration**: Automatic deduction for subscription renewals
- **Configurable Amounts**: Fixed preset amounts (10, 15, 20, 50, 100) plus custom amounts

### Wallet Balance Management

Each user has a single fiat wallet with the following properties:
- **Balance**: Current fiat balance in system currency
- **Currency**: Configurable system-wide currency (default: USD)
- **Auto Top-Up**: Optional automatic top-up when balance falls below threshold
- **Transaction History**: Complete log of all credits and debits

### Top-Up Methods

#### 1. Cryptocurrency Top-Up
- **Supported Currencies**: BTC, ETH, USDT (ERC20), USDC (ERC20)
- **Process**: Generate unique address → User sends crypto → Automatic balance credit
- **Confirmation**: Requires blockchain confirmations (6 for BTC, 12 for ETH/ERC20)

#### 2. PayPal Top-Up
- **Integration**: PayPal Checkout Orders API
- **Amounts**: Fixed presets or custom amounts
- **Process**: Create payment link → User completes PayPal payment → Automatic balance credit

#### 3. Stripe Top-Up (Credit Cards)
- **Integration**: Stripe PaymentIntents API
- **Amounts**: Fixed presets or custom amounts
- **Process**: Secure card payment → User completes payment → Automatic balance credit

### Auto Top-Up System

Auto top-up automatically replenishes wallet balance when needed for subscription renewals:

#### Configuration
```json
{
  "wallet": {
    "auto_topup_enabled": true,
    "auto_topup_amount": 20.00,
    "auto_topup_threshold": 5.00,
    "auto_topup_payment_method_id": "stripe_card_123"
  }
}
```

#### How It Works
1. **Threshold Monitoring**: System checks wallet balance before subscription renewal
2. **Auto Top-Up Trigger**: If balance < threshold, auto top-up is activated
3. **Payment Processing**: Uses stored Stripe payment method for automatic charge
4. **Balance Credit**: Wallet is topped up with configured amount
5. **Renewal Retry**: Subscription renewal proceeds with sufficient balance

### Subscription Renewal Flow

```
Subscription Renewal Process:
   ↳ Check Wallet Balance
      ↳ Sufficient? → Deduct Amount → Success ✅
      ↳ Insufficient?
         ↳ Auto Top-Up Enabled?
            ↳ Yes → Charge Stripe → Top Up Wallet → Retry Deduction → Success ✅
            ↳ No → Renewal Failed → Grace Period → Future Retry ❌
```

### Wallet API Endpoints

#### Get Wallet Balance
```http
GET /api/wallet/balance
Authorization: Bearer <token>
```

Response:
```json
{
  "balance": 25.50,
  "currency": "USD",
  "auto_topup_enabled": true,
  "auto_topup_threshold": 10.00
}
```

#### Top-Up Wallet
```http
POST /api/wallet/topup
Content-Type: application/json
Authorization: Bearer <token>

{
  "amount": 20.00,
  "payment_method": "stripe",
  "custom_amount": false
}
```

#### Configure Auto Top-Up
```http
POST /api/wallet/auto-topup
Content-Type: application/json
Authorization: Bearer <token>

{
  "enabled": true,
  "amount": 15.00,
  "threshold": 5.00,
  "payment_method_id": "stripe_pm_123"
}
```

#### Transaction History
```http
GET /api/wallet/transactions?page=1&limit=20
Authorization: Bearer <token>
```

Response:
```json
{
  "transactions": [
    {
      "id": 123,
      "type": "credit",
      "amount": 10.00,
      "description": "Stripe top-up",
      "created_at": "2026-04-21T10:30:00Z"
    }
  ],
  "total": 45,
  "page": 1,
  "pages": 3
}
```

### Dashboard Wallet Management

The dashboard provides complete wallet management:

- **Balance Display**: Current balance and recent transactions
- **Top-Up Options**: Quick top-up buttons for preset amounts
- **Custom Top-Up**: Enter custom amounts with payment method selection
- **Auto Top-Up Settings**: Configure automatic top-up preferences
- **Transaction History**: Paginated view of all wallet activity
- **Payment Method Management**: Add/remove payment methods for auto top-up

### Supported Top-Up Amounts

- **Fixed Amounts**: $10, $15, $20, $50, $100
- **Custom Amounts**: $5 - $500 (configurable per payment method)
- **Currency**: System-configured currency (default: USD)

### Security Features

- **Atomic Transactions**: All wallet operations use database transactions
- **Audit Trail**: Complete transaction history with tamper-evident logging
- **Payment Method Security**: Secure storage of payment method tokens
- **Rate Limiting**: Protection against excessive top-up attempts
- **Fraud Prevention**: Monitoring for suspicious transaction patterns

### Integration with Subscriptions

Wallet system integrates seamlessly with subscription management:

- **Automatic Deduction**: Subscription renewals deduct from wallet first
- **Graceful Handling**: Failed renewals enter grace period with retry logic
- **Cost Tracking**: All subscription charges logged in transaction history
- **Multi-Currency**: Supports system-wide currency configuration

## API Endpoints

### Three Proxy Paths

AISBF provides three ways to proxy AI models:

#### PATH 1: Direct Provider Models
Format: `{provider_id}/{model_name}`
- Access specific models from configured providers
- Example: `openai/gpt-4`, `gemini/gemini-2.0-flash`, `anthropic/claude-3-5-sonnet-20241022`

#### PATH 2: Rotations
Format: `rotation/{rotation_name}`
- Weighted load balancing across multiple providers
- Example: `rotation/coding`, `rotation/general`

#### PATH 3: Autoselect
Format: `autoselect/{autoselect_name}`
- AI-powered model selection based on content analysis
- Example: `autoselect/autoselect`

### General Endpoints
- `GET /` - Server status and provider list
- `GET /api/models` - List all available models from all three proxy paths
- `GET /api/v1/models` - OpenAI-compatible model listing

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

### User-Specific API Endpoints

Authenticated users can access their own configurations via user-specific API endpoints. These endpoints require either a valid API token (generated in the user dashboard) or session authentication.

#### Authentication

**Option 1: Bearer Token (Recommended for API access)**
```bash
Authorization: Bearer YOUR_API_TOKEN
```

**Option 2: Query Parameter**
```bash
?token=YOUR_API_TOKEN
```

#### User API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/u/{username}/models` | List available models from user's own configurations |
| `GET /api/u/{username}/providers` | List user's provider configurations |
| `GET /api/u/{username}/rotations` | List user's rotation configurations |
| `GET /api/u/{username}/autoselects` | List user's autoselect configurations |
| `POST /api/u/{username}/chat/completions` | Chat completions using user's own models |
| `GET /api/u/{username}/{config_type}/models` | List models for specific config type |

**Access Control:**
- **Global Tokens** (from `aisbf.json`): Access to global endpoints only (`/api/...`), no access to user-specific endpoints
- **User Tokens** (from dashboard): Access to their user-specific endpoints (`/api/u/username/...`) and global endpoints, but not admin functions
- **Admin Users**: Full access to all configurations and endpoints

#### Example: Using User API with cURL

```bash
# List user models
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:17765/api/u/yourusername/models

# Chat using user's own models
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "your-rotation/model", "messages": [{"role": "user", "content": "Hello"}]}' \
  http://localhost:17765/api/u/yourusername/chat/completions
```

### MCP (Model Context Protocol)

AISBF provides an MCP server for remote agent configuration and model access:

**Global MCP Endpoints (Admin-configured tokens):**
- `GET /mcp` - SSE endpoint for MCP communication
- `POST /mcp` - HTTP POST endpoint for MCP
- `GET /mcp/tools` - List available global MCP tools
- `POST /mcp/tools/call` - Call global MCP tools

**User-Specific MCP Endpoints (User API tokens):**
- `GET /mcp/u/{username}/tools` - List user's MCP tools
- `POST /mcp/u/{username}/tools/call` - Call user's MCP tool

MCP tools include:
- `list_models` - List available models
- `chat_completions` - Send chat completion requests
- `get_wallet_balance` - Check wallet balance
- `get_providers` - Get provider configurations
- `get_rotations` - Get rotation configurations
- `get_autoselects` - Get autoselect configurations

## Provider Support

### Model Metadata Extraction

AISBF automatically extracts and tracks model metadata from provider responses:

**Automatic Extraction:**
- **Pricing Information**: `rate_multiplier`, `rate_unit` (e.g., "per million tokens")
- **Token Usage**: `prompt_tokens`, `completion_tokens` from API responses
- **Rate Limits**: Auto-configures rate limits from 429 responses with retry-after headers
- **Model Details**: `description`, `context_length`, `architecture`, `supported_parameters`

**Dashboard Features:**
- **"Get Models" Button**: Fetches and displays comprehensive model metadata
- **Real-time Display**: Shows pricing, rate limits, and capabilities for each model
- **Extended Fields**: OpenRouter-style metadata including top_provider, pricing details, and architecture

### Google
- Uses google-genai SDK
- Requires API key
- Supports streaming and non-streaming responses
- Context Caching API support for cost reduction

### OpenAI
- Uses openai SDK
- Requires API key
- Supports streaming and non-streaming responses
- Automatic prefix caching (no configuration needed)

### Anthropic
- Uses anthropic SDK
- Requires API key
- Static model list (no dynamic model discovery)
- cache_control support for cost reduction

### Claude Code (OAuth2)
- Full OAuth2 PKCE authentication flow
- Automatic token refresh with refresh token rotation
- Chrome extension for remote server OAuth2 callback interception
- Proxy-aware extension serving: automatically detects reverse proxy deployments
- Supports all Claude models with streaming, tool calling, vision, and extended thinking

### Ollama
- Uses direct HTTP API
- No API key required
- Local model hosting support

### Kiro (Amazon Q Developer)
- Native integration with Kiro authentication
- Supports IDE credentials and CLI authentication
- No separate API key required

### Kilocode
- OAuth2 Device Authorization Grant flow
- Supports both API key and OAuth2 authentication
- Dashboard OAuth2 authentication UI

### Codex
- OAuth2 Device Authorization Grant for OpenAI protocol
- API key exchange from ID token
- Dashboard authentication UI

### Qwen
- API key authentication (recommended)
- OpenAI-compatible DashScope API endpoint
- Supports all Qwen models

## Advanced Features

### Provider-Native Caching

AISBF supports provider-native caching APIs for cost reduction:

#### Supported Providers
- **Anthropic**: `cache_control` with ephemeral caching
- **Google**: Context Caching API with TTL support
- **OpenAI**: Automatic prefix caching

#### Configuration
```json
{
  "providers": {
    "anthropic": {
      "enable_native_caching": true,
      "min_cacheable_tokens": 1024
    }
  }
}
```

### Response Caching

Intelligent response caching with semantic deduplication:

#### Features
- SHA256-based cache key generation
- Multiple backends (Redis, SQLite, MySQL, memory)
- TTL-based expiration
- Cache statistics and dashboard management

#### Configuration
```json
{
  "response_cache": {
    "enabled": true,
    "backend": "redis",
    "ttl": 600,
    "max_size": 1000
  }
}
```

### Adaptive Rate Limiting

Intelligent rate limit management that learns from provider responses:

#### Features
- Learns optimal request rates from 429 responses
- Exponential backoff with jitter
- Per-provider tracking
- Dashboard monitoring

#### Configuration
```json
{
  "adaptive_rate_limiting": {
    "enabled": true,
    "learning_rate": 0.1,
    "headroom_percent": 10
  }
}
```

### Context Management

Automatic context condensation with multiple methods:

#### Condensation Methods
1. **Hierarchical**: Separates persistent and transient layers
2. **Conversational**: Summarizes old messages
3. **Semantic**: Prunes irrelevant context
4. **Algorithmic**: Mathematical compression

#### Configuration
```json
{
  "models": [
    {
      "name": "gpt-4",
      "context_size": 128000,
      "condense_context": 80,
      "condense_method": ["hierarchical", "semantic"]
    }
  ]
}
```

### SSL/TLS Support

Built-in HTTPS with Let's Encrypt integration:

#### Self-Signed Certificates
- Automatic generation for development
- Stored in `~/.aisbf/cert.pem` and `key.pem`

#### Let's Encrypt
- Automatic certificate generation and renewal
- Requires certbot installation
- Public domain configuration in dashboard

### TOR Hidden Service

Anonymous access via TOR network:

#### Configuration
```json
{
  "tor": {
    "enabled": true,
    "control_port": 9051,
    "hidden_service_dir": "~/.aisbf/tor_hidden_service"
  }
}
```

## Development

### Building the Package

```bash
./build.sh
```

Creates distribution files in `dist/`.

### PyPI Publishing

See `PYPI.md` for detailed publishing instructions.

### Running Tests

```bash
pytest tests/
```

### Code Style

- Follow PEP 8
- Use type hints
- Add docstrings to all functions

## Troubleshooting

### Common Issues

#### Import Errors
- Ensure AISBF is properly installed
- Check Python path
- Verify dependencies in requirements.txt

#### Authentication Failures
- Check API keys in provider configuration
- Verify OAuth2 credentials are valid
- Check network connectivity to provider endpoints

#### Rate Limiting Issues
- Monitor dashboard rate limit statistics
- Adjust adaptive rate limiting settings
- Check provider account limits

#### Database Issues
- Verify database file permissions
- Check SQLite/MySQL connectivity
- Run database migrations if needed

### Debug Mode

Enable debug logging:
```bash
export AISBF_DEBUG=1
aisbf
```

### Logs Location

- Application logs: Console output
- Database logs: `~/.aisbf/aisbf.log`
- Error logs: Check application output

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

GNU General Public License v3.0

## Author

Stefy Lanza <stefy@nexlab.net>

## Repository

https://git.nexlab.net/nexlab/aisbf.git