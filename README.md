# AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations with unified API interface. AISBF provides intelligent routing, load balancing, and AI-assisted model selection to optimize AI service usage across multiple providers.

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

- **Multi-Provider Support**: Unified interface for Google, OpenAI, Anthropic, Claude Code (OAuth2), Ollama, Kiro, Kilocode, Codex, and Qwen
- **Unified Wallet System**: Fiat wallet with crypto/PayPal/Stripe top-ups and auto top-up for subscription renewals
- **Intelligent Routing**: Weighted load balancing and AI-assisted model selection
- **Streaming Support**: Full support for streaming responses from all providers
- **Web Dashboard**: Complete configuration and management interface
- **Multi-User Support**: Isolated configurations with role-based access control
- **Token Usage Analytics**: Comprehensive analytics with cost estimation and export
- **Adaptive Rate Limiting**: Learns from 429 responses for optimal request rates
- **Provider-Native Caching**: 50-70% cost reduction with Anthropic, Google, and OpenAI caching
- **Context Management**: Automatic condensation with 8+ methods when approaching limits
- **SSL/TLS & TOR**: Built-in HTTPS with Let's Encrypt and TOR hidden service support
- **MCP Server**: Model Context Protocol for remote agent integration

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
- Rotation and autoselect model setup
- User wallet management and top-up options
- Token usage analytics and cost tracking
- Real-time monitoring and rate limit management
- SSL/TLS and TOR configuration
- Multi-user administration

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

## Documentation

For complete documentation, configuration guides, and API reference:
- **[📚 Full Documentation](https://git.nexlab.net/nexlab/aisbf/src/master/DOCUMENTATION.md)** - Comprehensive user and developer guide
- **[🔧 Installation Guide](https://git.nexlab.net/nexlab/aisbf/src/master/DOCUMENTATION.md#installation)** - Detailed setup instructions
- **[⚙️ Configuration](https://git.nexlab.net/nexlab/aisbf/src/master/DOCUMENTATION.md#configuration)** - All configuration options
- **[💰 Wallet System](https://git.nexlab.net/nexlab/aisbf/src/master/DOCUMENTATION.md#wallet-system)** - Complete wallet documentation
- **[🔌 API Reference](https://git.nexlab.net/nexlab/aisbf/src/master/DOCUMENTATION.md#api-endpoints)** - Complete API documentation
- **[🛠️ Development](https://git.nexlab.net/nexlab/aisbf/src/master/DOCUMENTATION.md#development)** - Development and deployment guides

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