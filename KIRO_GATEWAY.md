# Kiro Gateway Integration Guide

This guide explains how to use [kiro-gateway](vendor/kiro-gateway) with AISBF to access Claude models through Kiro (Amazon Q Developer / AWS CodeWhisperer) credentials.

## Table of Contents

- [Overview](#overview)
- [What is Kiro Gateway?](#what-is-kiro-gateway)
- [Prerequisites](#prerequisites)
- [Setup Instructions](#setup-instructions)
  - [Step 1: Configure Kiro Gateway](#step-1-configure-kiro-gateway)
  - [Step 2: Start Kiro Gateway](#step-2-start-kiro-gateway)
  - [Step 3: Configure AISBF](#step-3-configure-aisbf)
- [Usage Examples](#usage-examples)
- [Available Models](#available-models)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)

## Overview

Kiro Gateway is a proxy gateway that provides OpenAI and Anthropic-compatible APIs for accessing Claude models through Kiro credentials. By integrating it with AISBF, you can:

- Access Claude models using Kiro IDE or kiro-cli credentials
- Use Claude models in AISBF rotations alongside other providers
- Benefit from automatic failover and load balancing
- Leverage Kiro's free tier or paid plans without direct Anthropic API access

## What is Kiro Gateway?

Kiro Gateway is a standalone FastAPI application located in [`vendor/kiro-gateway`](vendor/kiro-gateway) that:

- Proxies requests to Kiro's backend API
- Provides OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/models`)
- Provides Anthropic-compatible endpoints (`/v1/messages`)
- Supports both Kiro IDE and kiro-cli authentication methods
- Includes features like extended thinking, tool calling, and streaming

## Prerequisites

Before setting up kiro-gateway with AISBF, ensure you have:

1. **Kiro Credentials**: Either Kiro IDE or kiro-cli configured and authenticated
2. **Python 3.8+**: Required for running kiro-gateway
3. **AISBF Installed**: AISBF should be installed and configured
4. **Network Access**: Both services should be able to communicate (typically on localhost)

## Setup Instructions

### Step 1: Configure Kiro Gateway

1. Navigate to the kiro-gateway directory:
   ```bash
   cd vendor/kiro-gateway
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file with your configuration:
   ```bash
   # Authentication method (choose one)
   KIRO_AUTH_METHOD=ide  # or 'cli'
   
   # For IDE authentication
   KIRO_IDE_CONFIG_PATH=/path/to/your/.kiro/config.json
   
   # For CLI authentication
   KIRO_CLI_PATH=/path/to/kiro-cli
   
   # API Key for securing the proxy
   PROXY_API_KEY=your-secure-api-key-here
   
   # Optional: Server configuration
   HOST=0.0.0.0
   PORT=8000
   LOG_LEVEL=INFO
   ```

4. **Important**: Choose your authentication method:

   **Option A: Kiro IDE Authentication**
   - Set `KIRO_AUTH_METHOD=ide`
   - Set `KIRO_IDE_CONFIG_PATH` to your Kiro IDE config location
   - Default location: `~/.kiro/config.json`

   **Option B: kiro-cli Authentication**
   - Set `KIRO_AUTH_METHOD=cli`
   - Set `KIRO_CLI_PATH` to your kiro-cli executable
   - Ensure kiro-cli is authenticated: `kiro-cli auth login`

### Step 2: Start Kiro Gateway

Start the kiro-gateway server:

```bash
cd vendor/kiro-gateway
python main.py
```

You should see output indicating the server is running:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Tip**: Run kiro-gateway in a separate terminal or as a background service to keep it running while using AISBF.

### Step 3: Configure AISBF

1. **Add Kiro Provider to `~/.aisbf/providers.json`**:

   ```json
   {
     "kiro": {
       "id": "kiro",
       "name": "Kiro Gateway (Amazon Q Developer)",
       "endpoint": "http://localhost:8000/v1",
       "type": "kiro",
       "api_key_required": true,
       "rate_limit": 0,
       "models": [
         {
           "name": "claude-sonnet-4-5",
           "rate_limit": 0,
           "max_request_tokens": 200000,
           "context_size": 200000
         },
         {
           "name": "claude-haiku-4-5",
           "rate_limit": 0,
           "max_request_tokens": 200000,
           "context_size": 200000
         },
         {
           "name": "claude-opus-4-5",
           "rate_limit": 0,
           "max_request_tokens": 200000,
           "context_size": 200000
         },
         {
           "name": "claude-sonnet-4",
           "rate_limit": 0,
           "max_request_tokens": 200000,
           "context_size": 200000
         },
         {
           "name": "auto",
           "rate_limit": 0,
           "max_request_tokens": 200000,
           "context_size": 200000
         }
       ]
     }
   }
   ```

   **Important**: Replace `YOUR_KIRO_GATEWAY_API_KEY` with the `PROXY_API_KEY` you set in kiro-gateway's `.env` file.

2. **Add Kiro Rotation to `~/.aisbf/rotations.json`** (optional):

   ```json
   {
     "kiro-claude": {
       "model_name": "kiro-claude",
       "providers": [
         {
           "provider_id": "kiro",
           "api_key": "YOUR_KIRO_GATEWAY_API_KEY",
           "models": [
             {
               "name": "claude-sonnet-4-5",
               "weight": 3,
               "rate_limit": 0
             },
             {
               "name": "claude-haiku-4-5",
               "weight": 1,
               "rate_limit": 0
             }
           ]
         }
       ]
     }
   }
   ```

3. **Restart AISBF** to apply the configuration changes:
   ```bash
   # If running as a service
   sudo systemctl restart aisbf
   
   # If running manually
   ./aisbf.sh
   ```

## Usage Examples

### Direct Provider Access

Access kiro-gateway directly through AISBF:

```bash
curl -X POST http://localhost:5000/api/kiro/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_AISBF_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

### Rotation Access

Use kiro-gateway through a rotation (with automatic model selection):

```bash
curl -X POST http://localhost:5000/api/kiro-claude/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_AISBF_API_KEY" \
  -d '{
    "messages": [
      {"role": "user", "content": "Explain quantum computing"}
    ]
  }'
```

### Streaming Responses

Enable streaming for real-time responses:

```bash
curl -X POST http://localhost:5000/api/kiro/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_AISBF_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [
      {"role": "user", "content": "Write a short story"}
    ],
    "stream": true
  }'
```

### Tool Calling

Use Claude's tool calling capabilities:

```bash
curl -X POST http://localhost:5000/api/kiro/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_AISBF_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [
      {"role": "user", "content": "What is the weather in San Francisco?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get the current weather",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string"}
            }
          }
        }
      }
    ]
  }'
```

### List Available Models

Query available models through kiro-gateway:

```bash
curl http://localhost:5000/api/kiro/models \
  -H "Authorization: Bearer YOUR_AISBF_API_KEY"
```

## Available Models

Kiro Gateway provides access to the following Claude models:

| Model ID | Description | Context Size | Best For |
|----------|-------------|--------------|----------|
| `claude-sonnet-4-5` | Enhanced Sonnet model | 200K tokens | Balanced performance and quality |
| `claude-haiku-4-5` | Fast Haiku model | 200K tokens | Quick responses, lower cost |
| `claude-opus-4-5` | Top-tier Opus model | 200K tokens | Complex tasks (may require paid tier) |
| `claude-sonnet-4` | Previous generation Sonnet | 200K tokens | Stable, proven performance |
| `auto` | Automatic model selection | Varies | Let Kiro choose the best model |

**Note**: Model availability depends on your Kiro subscription tier. Some models may require a paid plan.

## Troubleshooting

### Kiro Gateway Not Starting

**Problem**: Kiro Gateway fails to start or crashes immediately.

**Solutions**:
1. Check that all dependencies are installed: `pip install -r requirements.txt`
2. Verify your `.env` file has correct configuration
3. Ensure Kiro credentials are valid and authenticated
4. Check logs for specific error messages

### Authentication Errors

**Problem**: Getting 401 Unauthorized errors from kiro-gateway.

**Solutions**:
1. Verify `PROXY_API_KEY` in kiro-gateway's `.env` matches the API key in AISBF's configuration
2. For IDE auth: Check that `KIRO_IDE_CONFIG_PATH` points to a valid config file
3. For CLI auth: Run `kiro-cli auth status` to verify authentication
4. Try re-authenticating: `kiro-cli auth login`

### Connection Refused

**Problem**: AISBF cannot connect to kiro-gateway.

**Solutions**:
1. Verify kiro-gateway is running: `curl http://localhost:8000/health`
2. Check that the endpoint in AISBF's `providers.json` matches kiro-gateway's address
3. Ensure no firewall is blocking the connection
4. Verify the port (default 8000) is not in use by another service

### Model Not Available

**Problem**: Requested model returns an error or is not available.

**Solutions**:
1. Check your Kiro subscription tier - some models require paid plans
2. Use `auto` model to let Kiro select an available model
3. Try a different model (e.g., `claude-haiku-4-5` instead of `claude-opus-4-5`)
4. Check kiro-gateway logs for specific error messages

### Rate Limiting

**Problem**: Requests are being rate limited.

**Solutions**:
1. Check your Kiro account's rate limits
2. Adjust `rate_limit` values in AISBF's configuration
3. Use rotations to distribute load across multiple providers
4. Consider upgrading your Kiro subscription for higher limits

### Streaming Not Working

**Problem**: Streaming responses are not working correctly.

**Solutions**:
1. Ensure `stream: true` is set in the request
2. Check that your client supports Server-Sent Events (SSE)
3. Verify no proxy or middleware is buffering the response
4. Check kiro-gateway logs for streaming-related errors

## Architecture

### Integration Overview

```
┌─────────────┐         ┌─────────────┐         ┌──────────────┐
│   Client    │ ──────> │    AISBF    │ ──────> │ Kiro Gateway │
│             │         │   Proxy     │         │              │
└─────────────┘         └─────────────┘         └──────────────┘
                              │                        │
                              │                        │
                              v                        v
                        ┌─────────────┐         ┌──────────────┐
                        │  Rotations  │         │  Kiro API    │
                        │  Failover   │         │  (Claude)    │
                        └─────────────┘         └──────────────┘
```

### Request Flow

1. **Client Request**: Client sends request to AISBF endpoint
2. **AISBF Processing**: AISBF validates, routes, and applies rotation logic
3. **Provider Selection**: AISBF selects kiro provider based on configuration
4. **Kiro Gateway**: Request is forwarded to kiro-gateway
5. **Authentication**: Kiro Gateway authenticates using IDE or CLI credentials
6. **Kiro API**: Request is sent to Kiro's backend API
7. **Response**: Response flows back through the chain to the client

### Key Components

- **[`KiroProviderHandler`](aisbf/providers.py)**: Handler class in AISBF that manages kiro-gateway communication
- **OpenAI SDK**: Used to communicate with kiro-gateway's OpenAI-compatible endpoints
- **Kiro Gateway**: Standalone FastAPI proxy in [`vendor/kiro-gateway`](vendor/kiro-gateway)
- **Kiro Credentials**: IDE or CLI authentication for accessing Kiro API

### Benefits of This Architecture

1. **Clean Separation**: Kiro Gateway runs independently, no code duplication
2. **Easy Maintenance**: Update kiro-gateway without modifying AISBF
3. **Flexibility**: Use kiro-gateway with other tools or directly
4. **Standard Interface**: OpenAI-compatible API works with existing tools
5. **Rotation Support**: Combine with other providers for failover and load balancing

## Additional Resources

- [AISBF Documentation](DOCUMENTATION.md)
- [Kiro Gateway README](vendor/kiro-gateway/README.md)
- [Kiro Gateway Architecture](vendor/kiro-gateway/ARCHITECTURE.md)
- [AISBF AI.PROMPT](AI.PROMPT) - Contains integration details and configuration examples

## Support

For issues related to:
- **AISBF**: Check [DOCUMENTATION.md](DOCUMENTATION.md) and [DEBUG_GUIDE.md](DEBUG_GUIDE.md)
- **Kiro Gateway**: Check [`vendor/kiro-gateway/README.md`](vendor/kiro-gateway/README.md)
- **Kiro Credentials**: Refer to Amazon Q Developer / AWS CodeWhisperer documentation

---

**Last Updated**: 2026-03-21
