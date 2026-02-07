#!/bin/bash
# Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
#
# Test script for AISBF proxy
#

PROXY_URL="http://127.0.0.1:17765"


# Test 1: Streaming request to rotations endpoint with googletest model
echo "Test 1: Streaming request to rotations endpoint with googletest model"
echo "----------------------------------------"
echo "Note: Streaming responses will appear as data: lines"
echo ""
curl -X POST "${PROXY_URL}/api/rotations/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "googletest",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": true
  }' \
  2>/dev/null
echo ""
echo ""

# Test 2: Streaming request to rotations endpoint with kilotest model
echo "Test 2: Streaming request to rotations endpoint with kilotest model"
echo "----------------------------------------"
echo "Note: Streaming responses will appear as data: lines"
echo ""
curl -X POST "${PROXY_URL}/api/rotations/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kilotest",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": true
  }' \
  2>/dev/null
echo ""
echo ""

