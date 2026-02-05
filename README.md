# AI Proxy Server

A unified proxy server for multiple AI providers with proper type handlers and library integration.

## Architecture

The proxy is organized into multiple modules for better maintainability:

- `main.py` - Entry point and FastAPI application setup
- `config.py` - Configuration management and provider loading
- `models.py` - Pydantic models for data structures
- `providers.py` - Provider type handlers with proper library integration
- `handlers.py` - Request/response handling logic

## Supported Providers

The proxy supports multiple AI providers with proper type handlers:

- **Google** - Uses `google-genai` library
- **OpenAI** - Uses `openai` library
- **Anthropic** - Uses `anthropic` library
- **Ollama** - Uses direct HTTP requests

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Start the proxy server:

```bash
./start_proxy.sh
```

The server will start on `http://localhost:8000`

## API Endpoints

### Chat Completions

```http
POST /api/{provider_id}/chat/completions
```

**Request Body:**
```json
{
  "model": "model_name",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "max_tokens": 100,
  "temperature": 0.7,
  "stream": false
}
```

### List Models

```http
GET /api/{provider_id}/models
```

## Configuration

Providers are configured in `providers.json` with proper type definitions:

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

## Error Handling

The proxy includes robust error handling with:

- Rate limiting for failed requests
- Automatic retry with provider rotation
- Proper error tracking and logging

## Donations

The extension includes multiple donation options to support its development:

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