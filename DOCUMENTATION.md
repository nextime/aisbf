# AISBF - AI Service Broker Framework || AI Should Be Free

## Overview

AISBF is a modular proxy server for managing multiple AI provider integrations. It provides a unified API interface for interacting with various AI services (Google, OpenAI, Anthropic, Ollama) with support for provider rotation and error tracking.

## Author

Stefy Lanza <stefy@nexlab.net>

## Repository

Official repository: https://git.nexlab.net/nexlab/aisbf.git

## Project Structure

```
geminiproxy/
├── aisbf/                    # Main Python module
│   ├── __init__.py          # Module initialization with exports
│   ├── config.py            # Configuration management
│   ├── models.py            # Pydantic models
│   ├── providers.py         # Provider handlers
│   ├── handlers.py          # Request handlers
│   ├── providers.json       # Default provider configs (moved to config/)
│   └── rotations.json       # Default rotation configs (moved to config/)
├── config/                   # Configuration files directory
│   ├── providers.json       # Default provider configurations
│   └── rotations.json       # Default rotation configurations
├── main.py                   # FastAPI application entry point
├── setup.py                  # Installation script
├── start_proxy.sh           # Development start script
├── aisbf.sh                 # Alternative start script
├── requirements.txt         # Python dependencies
├── INSTALL.md               # Installation guide
└── README.md                # Project documentation
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

## Configuration Management

### Configuration File Locations

**Installed Configuration Files (read-only defaults):**
- User: `~/.local/share/aisbf/providers.json`, `~/.local/share/aisbf/rotations.json`
- System: `/usr/local/share/aisbf/providers.json`, `/usr/local/share/aisbf/rotations.json`

**User Configuration Files (writable):**
- `~/.aisbf/providers.json` - Provider configurations
- `~/.aisbf/rotations.json` - Rotation configurations

**Development Mode:**
- `config/providers.json` and `config/rotations.json` in source tree

### First Run Behavior
1. Checks for config files in installed location
2. Creates `~/.aisbf/` directory if needed
3. Copies default configs from installed location to `~/.aisbf/`
4. Loads configuration from `~/.aisbf/` on subsequent runs

## API Endpoints

### Root Endpoint
- `GET /` - Returns server status and list of available providers

### Chat Completions
- `POST /api/{provider_id}/chat/completions` - Handle chat completion requests
- Supports both streaming and non-streaming responses
- Provider ID can be a specific provider or rotation name

### Model List
- `GET /api/{provider_id}/models` - List available models for a provider or rotation

## Provider Support

AISBF supports the following AI providers:

### Google
- Uses google-genai SDK
- Requires API key
- Supports streaming and non-streaming responses

### OpenAI
- Uses openai SDK
- Requires API key
- Supports streaming and non-streaming responses

### Anthropic
- Uses anthropic SDK
- Requires API key
- Static model list (no dynamic model discovery)

### Ollama
- Uses direct HTTP API
- No API key required
- Local model hosting support

## Rotation Support

AISBF supports provider rotation with weighted model selection:

### Rotation Configuration
```json
{
  "rotations": {
    "my_rotation": {
      "providers": [
        {
          "provider_id": "openai",
          "models": [
            {"name": "gpt-4", "weight": 1},
            {"name": "gpt-3.5-turbo", "weight": 3}
          ]
        },
        {
          "provider_id": "anthropic",
          "models": [
            {"name": "claude-3-haiku-20240307", "weight": 2}
          ]
        }
      ]
    }
  }
}
```

### Rotation Behavior
- Weighted random selection of models
- Automatic failover between providers
- Error tracking and rate limiting

## Error Tracking and Rate Limiting

### Error Tracking
- Tracks failures per provider
- Disables providers after 3 consecutive failures
- 5-minute cooldown period for disabled providers

### Rate Limiting
- Automatic provider disabling when rate limited
- Graceful error handling
- Configurable retry behavior

## Development vs Production

### Development
Use `start_proxy.sh`:
- Creates local venv in `./venv/`
- Installs dependencies from `requirements.txt`
- Starts server with auto-reload enabled
- Uses `config/` directory for configuration

### Production
Install with `python setup.py install`:
- Creates isolated venv
- Installs all dependencies
- Provides `aisbf` command with daemon support
- Uses installed config files

## AISBF Script Commands

### Starting in Foreground (Default)
```bash
aisbf
```
Starts server in foreground with visible output.

### Starting as Daemon
```bash
aisbf daemon
```
- Starts in background
- Saves PID to `/tmp/aisbf.pid`
- Redirects output to `/dev/null`
- Prints PID of started process

### Checking Status
```bash
aisbf status
```
Checks if AISBF is running and reports status/PID.

### Stopping the Daemon
```bash
aisbf stop
```
Stops running daemon and removes PID file.

## Key Classes and Functions

### aisbf/config.py
- `Config` - Configuration management class
- `ProviderConfig` - Provider configuration model
- `RotationConfig` - Rotation configuration model
- `AppConfig` - Application configuration model

### aisbf/models.py
- `Message` - Chat message structure
- `ChatCompletionRequest` - Request model
- `ChatCompletionResponse` - Response model
- `Model` - Model information
- `Provider` - Provider information
- `ErrorTracking` - Error tracking data

### aisbf/providers.py
- `BaseProviderHandler` - Base provider handler class
- `GoogleProviderHandler` - Google provider implementation
- `OpenAIProviderHandler` - OpenAI provider implementation
- `AnthropicProviderHandler` - Anthropic provider implementation
- `OllamaProviderHandler` - Ollama provider implementation
- `get_provider_handler()` - Factory function for provider handlers

### aisbf/handlers.py
- `RequestHandler` - Request handling logic
- `RotationHandler` - Rotation handling logic

## Dependencies

Key dependencies from requirements.txt:
- fastapi - Web framework
- uvicorn - ASGI server
- pydantic - Data validation
- httpx - HTTP client
- google-genai - Google AI SDK
- openai - OpenAI SDK
- anthropic - Anthropic SDK

## Adding New Providers

### Steps to Add a New Provider
1. Create handler class in `aisbf/providers.py` inheriting from `BaseProviderHandler`
2. Add to `PROVIDER_HANDLERS` dictionary
3. Add provider configuration to `config/providers.json`

### Provider Handler Requirements
- Implement `handle_request()` method
- Implement `get_models()` method
- Handle error tracking and rate limiting

## Configuration Examples

### Provider Configuration
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

### Rotation Configuration
```json
{
  "rotations": {
    "balanced": {
      "providers": [
        {
          "provider_id": "openai",
          "models": [
            {"name": "gpt-4", "weight": 1},
            {"name": "gpt-3.5-turbo", "weight": 3}
          ]
        },
        {
          "provider_id": "anthropic",
          "models": [
            {"name": "claude-3-haiku-20240307", "weight": 2}
          ]
        }
      ]
    }
  }
}
```

## Testing and Development

### Development Workflow
1. Use `start_proxy.sh` for development
2. Test with `start_proxy.sh` for development
3. Install with `python setup.py install` for production testing
4. Test all `aisbf` script commands (default, daemon, status, stop)
5. Verify configuration file locations and behavior
6. Test both user and system installations

### Common Development Tasks
- Adding new providers
- Modifying configuration
- Updating installation
- Testing error handling

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

## Contributing

When making changes:
1. Update AI.PROMPT file with significant changes
2. Test all functionality
3. Update documentation as needed
4. Follow the project's coding conventions
5. Ensure all tests pass

## Support

For support and questions:
- Check the AI.PROMPT file for project-specific instructions
- Review the INSTALL.md file for installation details
- Check the README.md file for project overview
- Test with development scripts before production deployment

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
