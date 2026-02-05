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