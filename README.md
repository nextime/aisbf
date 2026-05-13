# AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations with unified API interface. AISBF provides intelligent routing, load balancing, AI-assisted model selection, hosted model marketplaces, and multimodal Studio workflows across local and remote providers.

---

## 🌐 Try AISBF Now — No Installation Required!

> **[➡️ Launch AISBF at https://aisbf.cloud](https://aisbf.cloud)**
>
> The fully hosted service is free to use. Just open your browser and start routing AI requests across all supported providers — no setup, no configuration, no API keys needed to get started.

Also available via TOR for privacy-first access:
[http://aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion](http://aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion)

![AISBF Dashboard](https://git.nexlab.net/nexlab/aisbf/raw/master/screenshot.png)

---

## Key Features

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, Claude Code (OAuth2 or CLI), Ollama, Kiro, Kilocode, Codex, Qwen, CoderAI, and RunPod
- **CoderAI Broker Mode**: NAT-friendly outbound WebSocket broker with provider-scoped registration tokens, persisted session metadata, direct dashboard status, and Studio endpoint forwarding
- **RunPod Runtime Management**: Pod-backed, serverless-template, and public-catalog RunPod providers with runtime state persistence, startup polling, idle shutdown, and wrapper-mode delegation to OpenAI, Ollama, or CoderAI
- **AISBF Studio**: Multimodal dashboard workspace for chat, image, video, audio, embedding, and 3D workflows with reusable characters, environments, voices, archives, and custom pipelines
- **Marketplace & References**: Publish providers, models, rotations, and autoselects to a shared market, import them as locked references, and track listing analytics and revenue
- **Claude CLI Mode**: When the `claude` binary is in PATH, requests are proxied through the official Anthropic CLI (`claude -p`) using each user's own account
- **Unified Wallet System**: Fiat wallet with crypto/PayPal/Stripe top-ups and auto top-up for subscription renewals
- **Intelligent Routing**: Weighted load balancing and AI-assisted model selection
- **Streaming Support**: Full support for streaming responses from all providers
- **Web Dashboard**: Complete configuration and management interface
- **Multi-User Support**: Isolated configurations with role-based access control
- **Token Usage Analytics**: Comprehensive analytics with cost estimation, broker telemetry, and export
- **Adaptive Rate Limiting**: Learns from 429 responses for optimal request rates
- **Provider-Native Caching**: 50-70% cost reduction with Anthropic, Google, and OpenAI caching
- **Context Management**: Automatic condensation with 8+ methods when approaching limits
- **SSL/TLS & TOR**: Built-in HTTPS with Let's Encrypt and TOR hidden service support
- **MCP Server**: Model Context Protocol for remote agent integration

## What's New Since 0.99.65

- **CoderAI broker telemetry and NAT traversal**: Broker sessions now persist state across restarts, expose connection and performance telemetry in the dashboard, and support Studio-native proxying over WebSocket for remote or firewalled workers
- **RunPod provider support**: AISBF can now manage RunPod pods, serverless templates, and public endpoints from the provider editor, including runtime refresh and protocol-aware delegation
- **Marketplace administration**: Added dedicated market admin pages, publishing and settlement flows, user export filters, locked imported references, and improved search and ordering
- **Studio expansion**: Added dashboard Studio bindings, multimodal function routing, reusable profile assets, custom pipelines, and admin/user scoped Studio persistence APIs
- **Operational hardening**: Signup cleanup removes stale self-registered accounts after 14 days of inactivity, dashboard proxy path handling was normalized, and provider model caches are reused before refresh

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

## Web Dashboard

Access the dashboard at `http://localhost:17765/dashboard` (default credentials: `admin` / `admin`)

> **Security — change the default password immediately.**
> The default `admin/admin` credentials are publicly known. Open the dashboard → Settings → Change Password before exposing AISBF to any network.
> For HTTPS deployments, set the environment variable `AISBF_HTTPS=true` to mark session cookies as Secure.

The dashboard provides:
- Provider configuration and API key management
- RunPod runtime controls and CoderAI broker session monitoring
- Rotation and autoselect model setup
- Prompt security controls, Context Lens analytics, and NSFW/privacy routing filters
- AISBF Studio multimodal workflows and pipeline bindings
- User wallet management and top-up options
- Token usage analytics, broker telemetry, and cost tracking
- Marketplace publishing, importing, and administration
- SSL/TLS and TOR configuration
- Multi-user administration

## Featured Capabilities

### Market

- Publish providers, single models, rotations, and autoselect configurations to the built-in AISBF marketplace
- Import published resources as locked references instead of cloning their full configuration locally
- Track listing activity, usage settlement, revenue, and admin-side market visibility from the dashboard

### CoderAI

- Use `coderai` providers in direct HTTP mode, direct WebSocket bridge mode, or NAT-friendly broker mode
- Register remote workers with provider-scoped tokens and inspect broker session status from the dashboard
- Forward Studio-native endpoints over the CoderAI bridge so chat, multimodal, and long-running jobs can work through the same connection

### Security Filters

- Enable prompt-security scanning to detect suspicious prompt patterns before upstream execution
- Enable Context Lens analytics to capture prompt composition metadata, risk summaries, and redacted evidence
- Enable NSFW and privacy classification so AISBF can route or restrict traffic based on content sensitivity
- Optionally block high-risk prompts and keep persisted prompt text disabled by default while redaction remains enabled
- Prompt analytics stay empty until Prompt Security or Context Lens Analytics is explicitly enabled in settings or resource overrides

## API Usage

### Basic Chat Completion
```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Wallet Top-Up
```bash
curl -X POST http://localhost:17765/api/wallet/topup \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 10.00,
    "currency": "USD",
    "payment_method": "stripe"
  }'
```

### CoderAI Broker Session Status
```bash
curl http://localhost:17765/api/coderai/broker/sessions
```

## Documentation

For complete documentation, configuration guides, and API reference:
- **[📚 Full Documentation](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md)** - Comprehensive user and developer guide
- **[🔧 Installation Guide](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#installation)** - Detailed setup instructions
- **[⚙️ Configuration](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#configuration)** - All configuration options
- **[🛡️ Security Filters](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#security-filters-and-prompt-analysis)** - Prompt security, Context Lens analytics, and content classification
- **[🎛️ Studio Guide](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#aisbf-studio)** - Multimodal Studio, bindings, and pipelines
- **[🛒 Marketplace](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#marketplace-and-references)** - Publishing, imports, and settlements
- **[🤖 CoderAI Broker](https://git.nexlab.net/nexlab/aisbf/blob/master/docs/coderai-integration.md)** - Broker protocol and integration reference
- **[💰 Wallet System](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#wallet-system)** - Complete wallet documentation
- **[🔌 API Reference](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#api-endpoints)** - Complete API documentation
- **[🛠️ Development](https://git.nexlab.net/nexlab/aisbf/blob/master/DOCUMENTATION.md#development)** - Development and deployment guides

## 🚀 Support AISBF - Your Donations Matter!

The project includes multiple donation options to support its development:

### Ethereum Donation
ETH to `0xdA6dAb526515b5cb556d20269207D43fcc760E51`

### PayPal Donation
https://paypal.me/nexlab

### Bitcoin Donation
Address: `bc1qcpt2uutqkz4456j5r78rjm3gwq03h5fpwmcc5u`

## Author

Stefy Lanza <stefy@nexlab.net>

## Repository

Official repository: https://git.nexlab.net/nexlab/aisbf.git

## License

GNU General Public License v3.0
