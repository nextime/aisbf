# AISBF - AI Service Broker Framework || AI Should Be Free

## Overview

AISBF is a modular proxy server for managing multiple AI provider integrations. It provides a unified API interface for interacting with various AI services (Google, OpenAI, Anthropic, Claude Code, Ollama, Kiro, Kilocode, Codex, Qwen, CoderAI, RunPod) with support for provider rotation, AI-assisted model selection, marketplace exports, multimodal Studio workflows, unified wallet operations, and operational analytics.

### Key Features

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, Claude Code (OAuth2 or CLI), Ollama, Kiro (Amazon Q Developer), Kilocode (OAuth2), Codex (OAuth2), Qwen (API Key/OAuth2), CoderAI, and RunPod
- **Unified Wallet System**: Fiat wallet with crypto/PayPal/Stripe top-ups and auto top-up for subscription renewals
- **Claude OAuth2 Authentication**: Full OAuth2 PKCE flow for Claude Code with automatic token refresh, Chrome extension for remote servers, and curl_cffi TLS fingerprinting support
- **Claude CLI Mode**: When the `claude` binary is present in PATH at startup, AISBF automatically enables CLI proxy mode and uses per-user isolated config directories with automatic idle cleanup
- **Kiro-cli Support**: Full support for Amazon Q Developer CLI authentication with Device Authorization Grant
- **Kilocode OAuth2 Authentication**: OAuth2 Device Authorization Grant for Kilo Code with automatic token refresh
- **Codex OAuth2 Authentication**: OAuth2 Device Authorization Grant for OpenAI Codex with automatic token refresh and API key exchange
- **Qwen Authentication**: API key authentication (recommended) or OAuth2 (discontinued as of April 2026)
- **CoderAI Broker & Bridge**: Broker-backed and direct CoderAI integrations with WebSocket transport, NAT-friendly outbound registration, session persistence, runtime telemetry, and Studio-native proxy forwarding
- **RunPod Runtime Integration**: Pod-backed, serverless-template, and public-catalog RunPod providers with lifecycle management, persistent runtime state, startup polling, idle shutdown, and protocol-aware delegation to OpenAI, Ollama, or CoderAI handlers
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
- **Token Usage Analytics**: Comprehensive analytics dashboard with token usage tracking, cost estimation, performance metrics, broker telemetry, and export functionality
- **Marketplace & References**: Publish providers, models, rotations, and autoselects to a shared market, import them as locked references, settle usage revenue, and administer listings from dedicated dashboard pages
- **AISBF Studio**: Multimodal dashboard workspace with function bindings for chat, image, video, audio, embeddings, and 3D workflows, plus reusable characters, environments, voices, archive assets, and custom pipelines
- **Context Management**: Automatic context condensation with 8+ methods when approaching model limits
- **SSL/TLS Support**: Built-in HTTPS support with Let's Encrypt integration and automatic certificate renewal
- **TOR Hidden Service**: Full support for exposing AISBF over TOR network as a hidden service
- **MCP Server**: Model Context Protocol server for remote agent configuration and model access
- **Persistent Database**: SQLite/MySQL-based tracking of token usage, context dimensions, market data, RunPod runtime state, broker sessions, and user configurations
- **Multi-User Support**: User management with isolated configurations, role-based access control, and API token management
- **User-Specific API Endpoints**: Dedicated API endpoints for authenticated users to access their own configurations with Bearer token authentication
- **Proxy-Awareness**: Full support for reverse proxy deployments with automatic URL generation and subpath support

## New Since 0.99.65

### CoderAI broker and telemetry

- Added broker-side WebSocket endpoints for global and user-scoped CoderAI sessions
- Added provider-scoped registration tokens with inline rotation in the provider editor
- Persisted broker session metadata to `~/.aisbf/coderai_broker_sessions.json` so dashboards keep the last known status after restart
- Added dashboard visibility into session owner, client ID, connection state, transport, advertised Studio endpoints, and estimated performance metrics such as latency and tokens-per-second
- Expanded bridge proxy support so Studio-native endpoints, long-running jobs, multipart payloads, progress polling, and non-chat streaming envelopes can transit the broker connection

### RunPod provider runtime management

- Added `runpod` provider type with validation and dashboard configuration support
- Added `pod`, `serverless_template`, and `public` RunPod operating modes
- Added wrapper delegation so non-public RunPod resources can expose OpenAI-compatible, Ollama, or CoderAI-backed runtimes through one AISBF provider
- Added persistent RunPod runtime state in the database, including endpoint URL, resource kind, public catalog metadata, and last-used timestamps
- Added startup polling, timeout controls, idle shutdown, and runtime refresh actions in the provider dashboard
- Added public catalog support with per-model protocol override for `runpod_public`, `openai`, `ollama`, or `coderai`

### Marketplace and reference imports

- Added a dedicated market administration page for filtering, reviewing, and paging through listings
- Added marketplace publishing and settlement logic so providers, models, rotations, and autoselects can be shared and monetized
- Added listing analytics snapshots, revenue tracking, usage counters, and market fee support
- Added market import references so users can import shared resources as locked read-only references inside their provider, rotation, and autoselect selectors
- Added runtime resolution of market references plus improved dashboard rendering for locked resources and import variants
- Added user filtering and improved relevance ordering for market discovery and admin search

### AISBF Studio expansion

- Added Studio dashboard shell with multimodal tabs for chat, image, video, audio, embeddings, profiles, pipelines, archive, and 3D workflows
- Added Studio function-binding APIs for admin and user scopes so each workflow can be bound to the right provider/model role
- Added file-backed and database-backed persistence for Studio characters, environments, voices, archive items, custom pipelines, and binding definitions
- Added custom pipeline creation, update, delete, and run endpoints in both admin and user scopes
- Added capability-aware Studio adapter inference and profile shaping so different providers receive the payload format they expect for multimodal endpoints
- Added support for progress endpoints, reusable thumbnails, and user-owned Studio assets

### Operational hardening and dashboard fixes

- Added automatic cleanup of stale self-registered accounts that never log in within 14 days
- Reused cached provider model data before forced auto-detect refreshes to reduce unnecessary upstream calls
- Normalized remaining dashboard proxy-aware paths and bootstrap URLs to improve reverse-proxy compatibility
- Fixed analytics, dashboard state restoration, helper regressions, and market rendering issues introduced during the 0.99.65 to 0.99.66 cycle

## Project Structure

```
aisbf/
├── aisbf/                        # Main Python module
│   ├── __init__.py               # Module initialization with exports
│   ├── config.py                 # Configuration management
│   ├── models.py                 # Pydantic models
│   ├── handlers.py               # Request handlers
│   ├── analytics.py              # Analytics and telemetry
│   ├── coderai_broker.py         # CoderAI broker session registry and transport
│   ├── studio.py                 # Studio catalog helpers
│   ├── studio_adapters.py        # Studio adapter inference and payload shaping
│   ├── studio_services.py        # Studio persistence and runtime services
│   ├── providers/                # Provider handlers
│   │   ├── __init__.py
│   │   ├── base.py               # Shared provider utilities
│   │   ├── claude.py
│   │   ├── coderai.py            # CoderAI direct and bridge integration
│   │   ├── codex.py
│   │   ├── google.py
│   │   ├── ollama.py
│   │   ├── openai.py
│   │   ├── qwen.py
│   │   ├── runpod.py             # RunPod runtime lifecycle and delegation
│   │   └── kiro/
│   ├── auth/                     # Authentication modules
│   ├── routes/                   # FastAPI routes
│   │   ├── coderai_broker.py     # Broker transport endpoints
│   │   ├── dashboard/            # Dashboard views and APIs
│   │   └── user_api.py           # User-scoped API routes
│   ├── payments/                 # Payment system
│   └── [other modules...]
├── config/                       # Configuration files
├── docs/                         # Documentation and integration references
├── static/                       # Static assets (CSS, JS, images)
├── templates/                    # HTML templates
├── main.py                       # FastAPI application entry point
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
- `~/.aisbf/coderai_broker_sessions.json` - Persisted broker session snapshots
- `~/.aisbf/studio/` - File-backed admin Studio assets
- `~/.aisbf/pipelines.json` - Admin custom pipeline definitions
- `~/.aisbf/studio_bindings.json` - Admin Studio function bindings

**Development Mode:**
- `config/providers.json` and `config/rotations.json` in source tree

### First Run Behavior
1. Checks for config files in installed location
2. Creates `~/.aisbf/` directory if needed
3. Copies default configs from installed location to `~/.aisbf/`
4. Loads configuration from `~/.aisbf/` on subsequent runs

### Main Configuration (`aisbf.json`)
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

### Provider Highlights

#### CoderAI provider

Use `type: "coderai"` for local bridges, direct HTTP/WebSocket transport, or broker-first deployments.

Important `coderai_config` fields:
- `transport` - `http` or `websocket` for direct mode
- `broker_enabled` - allow broker registration and queue-based routing
- `broker_mode` - prefer inbound broker connectivity instead of direct calls
- `broker_preferred` - prefer the broker even when direct transport is configured
- `client_id` - stable client identity used for broker routing
- `registration_token` - required provider-scoped secret for broker admission
- `bridge_path` and `registration_path` - direct transport paths advertised to AISBF

Broker endpoints:
- `GET /api/coderai/broker/sessions`
- `GET /api/coderai/broker/providers/{provider_id}/status`
- `GET /api/coderai/wss`
- `GET /api/u/{username}/coderai/wss`

#### RunPod provider

Use `type: "runpod"` for managed remote runtimes.

Important `runpod_config` fields:
- `mode` - `pod`, `serverless_template`, or `public`
- `wrapper_mode` - `openai`, `ollama`, or `coderai` for non-public resources
- `pod_id`, `endpoint_id`, `template_id`, `serverless_template_id` - mode-specific resource identifiers
- `startup_poll_interval_ms` and `startup_timeout_ms` - runtime readiness controls
- `idle_shutdown_ms` - automatic stop window for inactive pods
- `public_endpoint_protocol_default` - protocol used when public catalog entries do not override it
- `public_models` - per-model protocol and capability overrides for public catalog entries

Dashboard support includes runtime refresh, status inspection, public catalog import, and persisted state tracking.

## Security Filters and Prompt Analysis

AISBF includes native request-time prompt analysis and content-safety controls that can be enabled globally and overridden at provider, rotation, autoselect, or model level.

### Prompt-security controls

The `prompt_security` feature group in `aisbf.json` controls:

- `security_scan` - enables local prompt scanning before upstream execution
- `context_lens` - enables prompt composition analytics and risk telemetry capture
- `block_high_risk_prompts` - blocks requests whose local prompt analysis resolves to `high` risk
- `persist_prompt_text` - stores raw prompt text when explicitly enabled
- `redact_before_persist` - keeps redaction enabled before persistence to avoid storing sensitive content in plain text by default
- `risk_threshold` - controls the blocking threshold, defaulting to `high`

Default shipped posture:
- prompt-security scanning: disabled
- Context Lens analytics: disabled
- block-high-risk prompts: disabled
- persist raw prompt text: disabled
- redact-before-persist: enabled

### Request-time behavior

When enabled, AISBF performs local prompt analysis before proxying the request upstream:

- scans prompts using regex and heuristic detectors for suspicious prompt-injection and policy-evasion patterns
- computes a risk level and aggregate risk score
- builds a composition summary including prompt shape, dominant role, system-prompt presence, and tool usage posture
- stores redacted summaries in prompt analytics tables for later dashboard inspection
- can stop execution locally when `block_high_risk_prompts` is enabled and the resolved risk level is `high`

### Content classification filters

AISBF also supports request classification flags for:

- NSFW-sensitive traffic via `enable_nsfw_classification`
- privacy-sensitive traffic via `enable_privacy_classification`

These controls can be applied on providers, rotations, autoselect configurations, and model entries so routing decisions can respect the sensitivity of the content being processed.

### Dashboard visibility

Prompt-security and analytics controls are exposed in the dashboard settings and resource editors:

- global defaults can be configured from dashboard settings
- provider/model editors expose tri-state overrides for prompt security and Context Lens analytics
- rotation/autoselect editors expose inherited or explicit overrides for the same controls
- prompt analysis results appear in the prompt analytics dashboard when scanning or Context Lens capture is enabled

## AISBF Studio

AISBF Studio is the dashboard-native multimodal workspace exposed at `/dashboard/studio`.

### Studio capabilities

- Chat with bound text-generation models
- Image generation, editing, inpainting, upscaling, segmentation, deblurring, outfit change, and 2D/3D conversions
- Video generation, interpolation, subtitling, dubbing, upscaling, face swap, outfit change, and 3D-related transforms
- Audio generation, TTS, transcription, voice cloning, voice conversion, stem extraction, and cleanup
- Embeddings and model-binding aware workflow routing
- Reusable profile assets: characters, environments, voices
- Archive storage and custom pipelines for repeatable workflows

### Studio persistence model

- Admin/global Studio assets are stored under `~/.aisbf/studio/`
- Admin custom pipelines are stored in `~/.aisbf/pipelines.json`
- Admin function bindings are stored in `~/.aisbf/studio_bindings.json`
- User-owned assets and pipelines are stored in the database
- User-owned function bindings are stored in user prompt override state

### Studio APIs

Examples:
- `GET /dashboard/api/studio/cached-models`
- `GET /dashboard/api/studio/function-bindings`
- `PUT /dashboard/api/studio/function-bindings/{binding_id}`
- `GET /dashboard/api/studio/pipelines/custom`
- `POST /dashboard/api/studio/pipelines/custom/{pipeline_id}/run`
- `GET /dashboard/api/studio/u/{username}/characters`
- `GET /dashboard/api/studio/u/{username}/audio/voices`

## Marketplace and References

AISBF includes a built-in marketplace for sharing configured resources between users.

### What can be published

- Providers
- Individual provider models
- Rotations
- Autoselect configurations

### Marketplace features

- Dedicated admin market page at `/dashboard/admin/market`
- Listing filters by search term, owner, source type, active status, and availability
- Pricing per million tokens and per 1,000 requests
- Revenue, request-count, vote, and analytics snapshots for each listing
- Settlement support for usage-based sharing
- User export controls and market visibility filtering

### Publishing model

Listings can be created from:

- full provider configurations
- specific provider/model pairs
- rotations
- autoselect resources

Each listing stores a sanitized configuration snapshot so secrets and local credential material are not exposed through the market export path.

### Imported references

Users can import market listings as references instead of duplicating the underlying configuration.

Reference behavior:
- Imported entries appear as read-only locked resources in provider, rotation, and autoselect selectors
- AISBF resolves references at runtime before handling requests
- Availability is tied to the source listing state
- Dashboard UI clearly distinguishes imported resources from locally owned ones

## CoderAI Integration

AISBF supports CoderAI both as a directly reachable provider and as a brokered remote runtime.

### Transport modes

- direct HTTP mode for OpenAI-compatible endpoints
- direct WebSocket bridge mode for framed request/response routing
- broker mode for outbound-only NAT traversal where the CoderAI worker connects into AISBF

### Broker features

- provider-scoped registration tokens
- global and user-scoped broker endpoints
- persisted broker session snapshots in `~/.aisbf/coderai_broker_sessions.json`
- dashboard session visibility with owner, client ID, transport, endpoint, Studio endpoints, and performance telemetry
- Studio-native proxy forwarding for non-chat endpoints and long-running jobs

### CoderAI dashboard workflow

- create or edit a `coderai` provider
- choose direct transport or broker mode
- assign a stable `client_id`
- generate or rotate the `registration_token`
- connect the remote worker to the broker endpoint
- inspect connection health and advertised capabilities from the providers page

For protocol-level implementation details, see `docs/coderai-integration.md`.

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
- **Process**: Generate unique address -> User sends crypto -> Automatic balance credit
- **Confirmation**: Requires blockchain confirmations (6 for BTC, 12 for ETH/ERC20)

#### 2. PayPal Top-Up
- **Integration**: PayPal Checkout Orders API
- **Amounts**: Fixed presets or custom amounts
- **Process**: Create payment link -> User completes PayPal payment -> Automatic balance credit

#### 3. Stripe Top-Up (Credit Cards)
- **Integration**: Stripe PaymentIntents API
- **Amounts**: Fixed presets or custom amounts
- **Process**: Secure card payment -> User completes payment -> Automatic balance credit

## API Endpoints

### Core chat endpoints
- `POST /api/v1/chat/completions`
- `GET /api/v1/models`
- `POST /api/{provider_id}/chat/completions`
- `GET /api/{provider_id}/models`

### User-scoped endpoints
- `POST /api/u/{username}/chat/completions`
- `GET /api/u/{username}/models`
- `GET /api/u/{username}/providers`
- `GET /api/u/{username}/rotations`
- `GET /api/u/{username}/autoselects`

### Broker and runtime endpoints
- `GET /api/coderai/broker/sessions`
- `GET /api/coderai/broker/providers/{provider_id}/status`
- `GET /dashboard/providers/{provider_id}/runpod-status`
- `POST /dashboard/providers/{provider_id}/runpod-refresh`

### Dashboard and Studio endpoints
- `GET /dashboard`
- `GET /dashboard/providers`
- `GET /dashboard/studio`
- `GET /dashboard/admin/market`

## Development

### Documentation notes for 0.99.66

The 0.99.66 documentation refresh covers the major product additions since 0.99.65:
- CoderAI broker state persistence and performance telemetry
- RunPod provider lifecycle management
- Marketplace publication, settlement, and reference imports
- Studio bindings, assets, and custom pipelines
- Stale signup cleanup and dashboard proxy hardening

### Additional references

- `README.md` - High-level feature overview
- `docs/coderai-integration.md` - CoderAI integration contract
- `docs/coderai-broker-implementation-reference.md` - Mirror reference for broker-side implementers
- `RUNPOD_IMPLEMENTATION_PLAN.md` - RunPod rollout notes and recovery plan
- `CHANGELOG.md` - Release-by-release history
