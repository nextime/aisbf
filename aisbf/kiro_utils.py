"""
Kiro Utilities for AISBF
Adapted from kiro-gateway utils.py
"""

import hashlib
import uuid
import socket
import getpass
import json
from typing import Dict, Any, List, Optional
import hashlib
import uuid as uuid_lib

def get_machine_fingerprint() -> str:
    """Generate a unique machine fingerprint"""
    try:
        hostname = socket.gethostname()
        username = getpass.getuser()
        unique_string = f"{hostname}-{username}-kiro-gateway"
        return hashlib.sha256(unique_string.encode()).hexdigest()
    except:
        return hashlib.sha256(b"default-machine-fingerprint").hexdigest()

def generate_completion_id() -> str:
    """Generate a unique completion ID"""
    return f"chatcmpl-{uuid_lib.uuid4().hex}"

def generate_conversation_id(messages: Optional[List[dict]] = None) -> str:
    """Generate a stable conversation ID from messages"""
    if not messages:
        return str(uuid_lib.uuid4())
    
    # Use first 3 messages and last message for hashing
    key_messages = messages[:3]
    if len(messages) > 3:
        key_messages.append(messages[-1])
    
    # Create a stable string for hashing
    content = ""
    for msg in key_messages:
        role = msg.get('role', '')
        content_text = str(msg.get('content', ''))[:100]
        content += f"{role}:{content_text[:50]}"
    
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def generate_tool_call_id() -> str:
    """Generate a unique ID for tool calls"""
    return f"call_{uuid_lib.uuid4().hex[:8]}"

def get_kiro_headers(auth_manager, token: str) -> dict:
    """Get headers for Kiro API requests"""
    fingerprint = get_machine_fingerprint()
    
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"aws-sdk-js/1.0.27 KiroIDE-0.7.45-{fingerprint}",
        "x-amz-user-agent": f"aws-sdk-js/1.0.27 KiroIDE-0.7.45-{fingerprint}",
        "x-amz-codewhisperer-optout": "true",
        "x-amzn-kiro-agent-mode": "vibe",
        "amz-sdk-invocation-id": str(uuid_lib.uuid4()),
        "amz-sdk-request": "attempt=1; max=3"
    }

def normalize_model_name(model_name: str) -> str:
    """Normalize model name for Kiro API"""
    # Convert various model name formats to Kiro's expected format
    model_map = {
        'claude-sonnet-4-5': 'claude-sonnet-4-5',
        'claude-sonnet-4.5': 'claude-sonnet-4-5',
        'claude-sonnet-4': 'claude-sonnet-4',
        'claude-haiku-4-5': 'claude-haiku-4-5',
        'claude-haiku-4.5': 'claude-haiku-4-5',
        'claude-opus-4-5': 'claude-opus-4-5',
        'claude-opus-4.5': 'claude-opus-4-5',
        'claude-3-5-sonnet': 'claude-sonnet-4-5',
        'claude-3-5-sonnet': 'claude-sonnet-4-5',
    }
    
    # Normalize the model name
    model_lower = model_name.lower().replace('_', '-')
    
    # Check for known aliases
    for alias, normalized in model_map.items():
        if model_lower == alias or model_lower == alias.replace('-', '_'):
            return normalized
    
    # If not in map, try to normalize common patterns
    if 'sonnet' in model_lower and '4.5' in model_lower:
        return 'claude-sonnet-4-5'
    elif 'haiku' in model_lower and '4.5' in model_lower:
        return 'claude-haiku-4-5'
    elif 'opus' in model_lower and '4.5' in model_lower:
        return 'claude-opus-4-5'
    elif 'sonnet' in model_lower and '4' in model_lower:
        return 'claude-sonnet-4'
    
    # Default to the original name if no match
    return model_lower

def build_kiro_request(messages: list, model: str, max_tokens: int = None, 
                       temperature: float = 1.0, stream: bool = False) -> dict:
    """Build a Kiro API request from OpenAI-style request"""
    
    # Convert messages to Kiro format
    kiro_messages = []
    for msg in messages:
        role = msg.get('role')
        content = msg.get('content', '')
        
        if role == 'system':
            # System messages need special handling
            kiro_messages.append({
                "role": "user",
                "content": content
            })
        elif role in ['user', 'assistant', 'system']:
            kiro_messages.append({
                "role": role,
                "content": content
            })
        elif role == 'tool':
            # Tool messages need special handling
            kiro_messages.append({
                "role": "user",
                "content": f"[Tool result: {content}]"
            })
    
    request = {
        "model": normalize_model_name(model),
        "messages": kiro_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream
    }
    
    return request

def parse_kiro_response(response_data: dict) -> dict:
    """Parse Kiro API response to OpenAI format"""
    if not response_data:
        return {
            "id": f"kiro-{uuid_lib.uuid4().hex}",
            "object": "chat.completion",
            "created": 0,
            "model": "unknown",
            "choices": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    
    # Extract the response
    choices = []
    if 'choices' in response_data:
        for choice in response_data.get('choices', []):
            message = choice.get('message', {})
            choices.append({
                "index": choice.get('index', 0),
                "message": {
                    "role": "assistant",
                    "content": message.get('content', ''),
                    "tool_calls": message.get('tool_calls', [])
                },
                "finish_reason": choice.get('finish_reason', 'stop')
            })
    
    return {
        "id": response_data.get('id', f"kiro-{uuid_lib.uuid4().hex}"),
        "object": "chat.completion",
        "created": response_data.get('created', 0),
        "model": response_data.get('model', 'unknown'),
        "choices": choices,
        "usage": response_data.get('usage', {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        })
    }