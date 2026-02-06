#!/bin/bash
# Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
#
# Test script for AISBF proxy
#

PROXY_URL="http://127.0.0.1:17765"

echo "=========================================="
echo "AISBF Proxy Test Script"
echo "=========================================="
echo ""

# Test 1: Non-streaming request to autoselect endpoint
echo "Test 1: Non-streaming request to autoselect endpoint"
echo "----------------------------------------"
curl -X POST "${PROXY_URL}/api/autoselect/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autoselect",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": false
  }' \
  2>/dev/null | jq '.' || echo "Response received (jq not available)"
echo ""
echo ""

# Test 2: Streaming request to autoselect endpoint
echo "Test 2: Streaming request to autoselect endpoint"
echo "----------------------------------------"
echo "Note: Streaming responses will appear as data: lines"
echo ""
curl -X POST "${PROXY_URL}/api/autoselect/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autoselect",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": true
  }' \
  2>/dev/null
echo ""
echo ""

# Test 3: List available providers
echo "Test 3: List available providers"
echo "----------------------------------------"
curl -X GET "${PROXY_URL}/" 2>/dev/null | jq '.' || echo "Response received (jq not available)"
echo ""
echo ""

# Test 4: List models for autoselect endpoint
echo "Test 4: List models for autoselect endpoint"
echo "----------------------------------------"
curl -X GET "${PROXY_URL}/api/autoselect/models" 2>/dev/null | jq '.' || echo "Response received (jq not available)"
echo ""
echo ""

echo "=========================================="
echo "Test script completed"
echo "=========================================="
echo ""
echo "Note: If jq is not installed, responses will not be formatted"
echo "Install jq with: sudo apt-get install jq (Debian/Ubuntu)"
echo "                    brew install jq (macOS)"