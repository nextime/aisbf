# AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations with unified API interface.

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

Server starts on `http://localhost:8000`

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
- `GET /api/rotations/models` - List all models across all rotation configurations

### Autoselect Endpoints
- `GET /api/autoselect` - List all available autoselect configurations
- `POST /api/autoselect/chat/completions` - Chat completions using AI-assisted selection based on content analysis
- `GET /api/autoselect/models` - List all models across all autoselect configurations

## Error Handling
- Rate limiting for failed requests
- Automatic retry with provider rotation
- Proper error tracking and logging

## Donations
The project includes multiple donation options to support its development:

### Web3/MetaMask Donation
Works on any website - The Web3 donation is completely independent of the current page
Click the "🦊 Donate with MetaMask" button in the extension popup (only appears if MetaMask is detected)
Supports both modern window.ethereum and legacy window.web3 providers
Default donation: 0.1 ETH to 0xdA6dAb526515b5cb556d20269207D43fcc760E51
Users can modify the amount in MetaMask before confirming

### PayPal Donation
Click the "💳 Donate with PayPal" button in the extension popup
Opens PayPal donation page for info@nexlab.net
Traditional payment method for users without cryptocurrency wallets
Always available regardless of browser setup

### Bitcoin Donation
Address: bc1qcpt2uutqkz4456j5r78rjm3gwq03h5fpwmcc5u
Traditional BTC donation method

## Documentation
See `DOCUMENTATION.md` for complete API documentation, configuration details, and development guides.

## License
GNU General Public License v3.0