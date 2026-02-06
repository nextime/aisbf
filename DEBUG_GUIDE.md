# Debug Logging Guide for AISBF

## Overview

Comprehensive debug logging has been added throughout the AISBF codebase to help understand how models and providers are selected. This guide explains what information is logged and how to use it.

## Recent Fixes

### Fixed: Ollama Provider Handler Initialization
**Issue**: `TypeError: OllamaProviderHandler.__init__() takes 2 positional arguments but 3 were given`

**Cause**: The `get_provider_handler()` function was passing an `api_key` parameter to `OllamaProviderHandler`, but the handler only accepted `provider_id`.

**Solution**: Updated `OllamaProviderHandler.__init__()` to accept an optional `api_key` parameter. This allows:
- Local Ollama instances to work without an API key
- Ollama cloud models to use an API key when provided

The API key is now optional for Ollama and will be added to request headers as `Authorization: Bearer {api_key}` if provided.

## What Was Changed

### 1. main.py
- Added detailed logging at the start of each request showing:
  - Request path and provider ID
  - Available providers, rotations, and autoselect configurations
  - Request headers and body
- Enhanced error messages when provider not found
- Added catch-all endpoint for invalid routes

### 2. aisbf/handlers.py
- **RequestHandler**: Logs provider config, handler selection, and request parameters
- **RotationHandler**: Logs rotation config, weighted models, and selected model details
- Shows model selection process and rate limiting

### 3. aisbf/providers.py
- **get_provider_handler**: Logs provider config, handler class selection
- **OllamaProviderHandler**: Logs endpoint, model, request details, and response

### 4. aisbf/config.py
- Logs configuration file locations
- Shows loaded providers and their details
- Logs provider lookup results

## Understanding Your Issue

You're seeing:
```
INFO:     127.0.0.1:44892 - "POST /api/ollama HTTP/1.1" 404 Not Found
```

This is because the correct endpoint format is:
```
POST /api/{provider_id}/chat/completions
```

For example:
```
POST /api/ollama/chat/completions
```

## How to Use the Debug Logs

### 1. Start the Server
```bash
python main.py
```

### 2. Make a Request
```bash
curl -X POST http://localhost:8000/api/ollama/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### 3. Check the Logs

The logs will show:

#### Request Entry
```
=== CHAT COMPLETION REQUEST START ===
Request path: /api/ollama/chat/completions
Provider ID: ollama
Available providers: ['google', 'openai', 'anthropic', 'ollama']
Available rotations: ['general']
Available autoselect: []
```

#### Provider Selection
```
Provider ID 'ollama' found in providers
Provider config: id='ollama' name='Ollama' endpoint='http://localhost:11434' type='ollama' api_key_required=False
```

#### Handler Creation
```
=== get_provider_handler START ===
Provider ID: ollama
Provider type: ollama
Handler class: OllamaProviderHandler
Handler created: OllamaProviderHandler
```

#### Request Processing
```
=== OllamaProviderHandler.handle_request START ===
Provider ID: ollama
Endpoint: http://localhost:11434
Model: llama2
Messages count: 1
Sending POST request to http://localhost:11434/api/generate
Response status code: 200
```

## Common Issues and Solutions

### Issue 1: 404 Not Found
**Cause**: Incorrect endpoint path
**Solution**: Use `/api/{provider_id}/chat/completions` instead of `/api/{provider_id}`

### Issue 2: Provider Not Found
**Cause**: Provider ID doesn't exist in configuration
**Solution**: Check the logs for available providers and verify your provider_id

### Issue 3: Model Not Found
**Cause**: Model name doesn't exist in the provider
**Solution**: Check the provider's available models using `/api/{provider_id}/models`

### Issue 4: Connection Refused
**Cause**: Provider endpoint is not reachable
**Solution**: Check the endpoint URL in the provider configuration and ensure the provider is running

## Log Levels

- **INFO**: Normal operation flow, shows what's happening
- **DEBUG**: Detailed information for troubleshooting
- **ERROR**: Problems that need attention

## Log Files

Logs are written to:
- `~/.local/var/log/aisbf/aisbf.log` - General logs
- `~/.local/var/log/aisbf/aisbf_error.log` - Error logs
- `~/.local/var/log/aisbf/aisbf_stderr.log` - Standard error

## Configuration Files

The system looks for configuration files in this order:
1. `~/.aisbf/` - User configuration (highest priority)
2. `/usr/share/aisbf/` - System-wide configuration
3. `~/.local/share/aisbf/` - User-local configuration
4. `config/` - Source tree configuration (development mode)

## Example Debug Session

1. **Check available providers**:
```bash
curl http://localhost:8000/
```

2. **List models for a provider**:
```bash
curl http://localhost:8000/api/ollama/models
```

3. **Make a chat completion request**:
```bash
curl -X POST http://localhost:8000/api/ollama/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

4. **Review the logs** to see the complete flow of the request

## Next Steps

After reviewing the debug logs, you should be able to:
- Identify which provider is being selected
- See which model is being used
- Understand the request flow
- Diagnose any issues with provider or model selection

If you still have issues, the debug logs will provide detailed information about what's happening at each step of the process.