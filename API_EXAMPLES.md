# AISBF API Examples

This document provides practical examples for using the AISBF API endpoints.

## Table of Contents
- [OpenAI-Compatible v1 Endpoints](#openai-compatible-v1-endpoints)
- [Chat Completions](#chat-completions)
- [Audio Endpoints](#audio-endpoints)
- [Image Generation](#image-generation)
- [Embeddings](#embeddings)
- [Model Listing](#model-listing)
- [Rotations](#rotations)
- [Autoselect](#autoselect)

## OpenAI-Compatible v1 Endpoints

The v1 endpoints follow the standard OpenAI API format with `provider/model` notation.

### Chat Completions

#### Using cURL

```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

#### Using Python

```python
import requests

response = requests.post(
    "http://localhost:17765/api/v1/chat/completions",
    json={
        "model": "openai/gpt-4",
        "messages": [
            {"role": "user", "content": "Hello, how are you?"}
        ]
    }
)

print(response.json())
```

#### Using Python with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"  # Not required if auth is disabled
)

response = client.chat.completions.create(
    model="openai/gpt-4",
    messages=[
        {"role": "user", "content": "Hello, how are you?"}
    ]
)

print(response.choices[0].message.content)
```

#### Streaming Response

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

stream = client.chat.completions.create(
    model="gemini/gemini-2.0-flash",
    messages=[
        {"role": "user", "content": "Write a short poem"}
    ],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

#### Using Different Providers

```bash
# Google Gemini
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini/gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Anthropic Claude
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-3-5-sonnet-20241022",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Ollama (local)
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ollama/llama2",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Audio Endpoints

### Audio Transcription

```bash
curl -X POST http://localhost:17765/api/v1/audio/transcriptions \
  -F "file=@audio.mp3" \
  -F "model=openai/whisper-1"
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

with open("audio.mp3", "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="openai/whisper-1",
        file=audio_file
    )

print(transcript.text)
```

### Text-to-Speech

```bash
curl -X POST http://localhost:17765/api/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/tts-1",
    "input": "Hello, this is a test.",
    "voice": "alloy"
  }' \
  --output speech.mp3
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.audio.speech.create(
    model="openai/tts-1",
    voice="alloy",
    input="Hello, this is a test."
)

response.stream_to_file("speech.mp3")
```

## Image Generation

```bash
curl -X POST http://localhost:17765/api/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/dall-e-3",
    "prompt": "A beautiful sunset over mountains",
    "n": 1,
    "size": "1024x1024"
  }'
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.images.generate(
    model="openai/dall-e-3",
    prompt="A beautiful sunset over mountains",
    n=1,
    size="1024x1024"
)

print(response.data[0].url)
```

## Embeddings

```bash
curl -X POST http://localhost:17765/api/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/text-embedding-ada-002",
    "input": "The quick brown fox jumps over the lazy dog"
  }'
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

response = client.embeddings.create(
    model="openai/text-embedding-ada-002",
    input="The quick brown fox jumps over the lazy dog"
)

print(response.data[0].embedding)
```

## Model Listing

### List All Models

```bash
curl http://localhost:17765/api/v1/models
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

models = client.models.list()
for model in models.data:
    print(f"{model.id} - {model.owned_by}")
```

## Rotations

Rotations provide weighted load balancing across multiple providers.

### Using Rotation with v1 Endpoint

```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "coding",
    "messages": [
      {"role": "user", "content": "Write a Python function to sort a list"}
    ]
  }'
```

### Using Legacy Rotation Endpoint

```bash
curl -X POST http://localhost:17765/api/rotations/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "coding",
    "messages": [
      {"role": "user", "content": "Write a Python function to sort a list"}
    ]
  }'
```

### List Available Rotations

```bash
curl http://localhost:17765/api/rotations
```

### List Rotation Models

```bash
curl http://localhost:17765/api/rotations/models
```

## Autoselect

Autoselect uses AI to automatically select the best model based on your request.

### Using Autoselect with v1 Endpoint

```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autoselect",
    "messages": [
      {"role": "user", "content": "Debug this Python code: def add(a,b): return a-b"}
    ]
  }'
```

### Using Legacy Autoselect Endpoint

```bash
curl -X POST http://localhost:17765/api/autoselect/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autoselect",
    "messages": [
      {"role": "user", "content": "Debug this Python code: def add(a,b): return a-b"}
    ]
  }'
```

### List Available Autoselect Configurations

```bash
curl http://localhost:17765/api/autoselect
```

## Legacy Provider Endpoints

You can also use provider-specific endpoints:

```bash
# Direct provider access
curl -X POST http://localhost:17765/api/openai/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# List provider models
curl http://localhost:17765/api/openai/models
```

## Authentication

If authentication is enabled in your configuration:

```bash
curl -X POST http://localhost:17765/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="YOUR_TOKEN_HERE"
)

response = client.chat.completions.create(
    model="openai/gpt-4",
    messages=[{"role": "user", "content": "Hello"}]
)
```

## JavaScript/Node.js Examples

### Using fetch API

```javascript
const response = await fetch('http://localhost:17765/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'openai/gpt-4',
    messages: [
      { role: 'user', content: 'Hello, how are you?' }
    ]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

### Using OpenAI SDK

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:17765/api/v1',
  apiKey: 'dummy'
});

const response = await client.chat.completions.create({
  model: 'openai/gpt-4',
  messages: [
    { role: 'user', content: 'Hello, how are you?' }
  ]
});

console.log(response.choices[0].message.content);
```

### Streaming in JavaScript

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:17765/api/v1',
  apiKey: 'dummy'
});

const stream = await client.chat.completions.create({
  model: 'gemini/gemini-2.0-flash',
  messages: [
    { role: 'user', content: 'Write a short poem' }
  ],
  stream: true
});

for await (const chunk of stream) {
  const content = chunk.choices[0]?.delta?.content || '';
  process.stdout.write(content);
}
```

## Error Handling

```python
from openai import OpenAI, OpenAIError

client = OpenAI(
    base_url="http://localhost:17765/api/v1",
    api_key="dummy"
)

try:
    response = client.chat.completions.create(
        model="openai/gpt-4",
        messages=[
            {"role": "user", "content": "Hello"}
        ]
    )
    print(response.choices[0].message.content)
except OpenAIError as e:
    print(f"Error: {e}")
```

## Advanced Features

### Context Condensation

When using models with large context windows, AISBF automatically condenses context when approaching limits:

```python
# Large context will be automatically condensed
response = client.chat.completions.create(
    model="gemini/gemini-2.0-flash",
    messages=[
        {"role": "user", "content": "Very long prompt..."},
        # ... many messages
    ]
)
```

### Rate Limiting

AISBF automatically handles rate limits and rotates to available providers:

```python
# If rate limit is hit, AISBF will automatically use another provider
for i in range(100):
    response = client.chat.completions.create(
        model="coding",  # Rotation with multiple providers
        messages=[{"role": "user", "content": f"Request {i}"}]
    )
```

## Dashboard Access

Access the web dashboard at:
```
http://localhost:17765/dashboard
```

Default credentials:
- Username: `admin`
- Password: `admin` (SHA256 hashed in config)

## License

Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
