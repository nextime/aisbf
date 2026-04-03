# -*- coding: utf-8 -*-

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
Converters for transforming OpenAI format to Kiro format.

This module is an adapter layer that converts OpenAI-specific formats
to the unified format used by converters_core.py.

Contains functions for:
- Converting OpenAI messages to unified format
- Converting OpenAI tools to unified format
- Building Kiro payload from OpenAI requests
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

# Use standard Python logging
logger = logging.getLogger(__name__)

# Import Kiro models for type hints
from .models import ChatMessage, Tool

# Hidden models - not returned by Kiro /ListAvailableModels API but still functional.
# These need special internal IDs that differ from their display names.
# Format: "normalized_display_name" → "internal_kiro_id"
# Matches kiro-gateway's config.py HIDDEN_MODELS
HIDDEN_MODELS = {
    # Claude 3.7 Sonnet - legacy flagship model, still works!
    "claude-3.7-sonnet": "CLAUDE_3_7_SONNET_20250219_V1_0",
}


def normalize_model_name(name: str) -> str:
    """
    Normalize client model name to Kiro format.
    
    Ported from kiro-gateway's model_resolver.py normalize_model_name().
    
    Transformations applied:
    1. claude-haiku-4-5 → claude-haiku-4.5 (dash to dot for minor version)
    2. claude-haiku-4-5-20251001 → claude-haiku-4.5 (strip date suffix)
    3. claude-haiku-4-5-latest → claude-haiku-4.5 (strip 'latest' suffix)
    4. claude-sonnet-4-20250514 → claude-sonnet-4 (strip date, no minor)
    5. claude-3-7-sonnet → claude-3.7-sonnet (legacy format normalization)
    6. claude-3-7-sonnet-20250219 → claude-3.7-sonnet (legacy + strip date)
    7. claude-4.5-opus-high → claude-opus-4.5 (inverted format with suffix)
    
    Args:
        name: External model name from client
    
    Returns:
        Normalized model name in Kiro format
    """
    if not name:
        return name
    
    # Lowercase for consistent matching
    name_lower = name.lower()
    
    # Pattern 1: Standard format - claude-{family}-{major}-{minor}(-{suffix})?
    # Matches: claude-haiku-4-5, claude-haiku-4-5-20251001, claude-haiku-4-5-latest
    # IMPORTANT: Minor version is 1-2 digits only! 8-digit dates should NOT match here.
    standard_pattern = r'^(claude-(?:haiku|sonnet|opus)-\d+)-(\d{1,2})(?:-(?:\d{8}|latest|\d+))?$'
    match = re.match(standard_pattern, name_lower)
    if match:
        base = match.group(1)  # claude-haiku-4
        minor = match.group(2)  # 5
        return f"{base}.{minor}"  # claude-haiku-4.5
    
    # Pattern 2: Standard format without minor - claude-{family}-{major}(-{date})?
    # Matches: claude-sonnet-4, claude-sonnet-4-20250514
    no_minor_pattern = r'^(claude-(?:haiku|sonnet|opus)-\d+)(?:-\d{8})?$'
    match = re.match(no_minor_pattern, name_lower)
    if match:
        return match.group(1)  # claude-sonnet-4
    
    # Pattern 3: Legacy format - claude-{major}-{minor}-{family}(-{suffix})?
    # Matches: claude-3-7-sonnet, claude-3-7-sonnet-20250219
    legacy_pattern = r'^(claude)-(\d+)-(\d+)-(haiku|sonnet|opus)(?:-(?:\d{8}|latest|\d+))?$'
    match = re.match(legacy_pattern, name_lower)
    if match:
        prefix = match.group(1)  # claude
        major = match.group(2)   # 3
        minor = match.group(3)   # 7
        family = match.group(4)  # sonnet
        return f"{prefix}-{major}.{minor}-{family}"  # claude-3.7-sonnet
    
    # Pattern 4: Already normalized with dot but has date suffix
    # Matches: claude-haiku-4.5-20251001, claude-3.7-sonnet-20250219
    dot_with_date_pattern = r'^(claude-(?:\d+\.\d+-)?(?:haiku|sonnet|opus)(?:-\d+\.\d+)?)-\d{8}$'
    match = re.match(dot_with_date_pattern, name_lower)
    if match:
        return match.group(1)
    
    # Pattern 5: Inverted format with suffix - claude-{major}.{minor}-{family}-{suffix}
    # Matches: claude-4.5-opus-high, claude-4.5-sonnet-low
    # Convert to: claude-{family}-{major}.{minor}
    # NOTE: Requires a suffix to avoid matching already-normalized formats
    inverted_with_suffix_pattern = r'^claude-(\d+)\.(\d+)-(haiku|sonnet|opus)-(.+)$'
    match = re.match(inverted_with_suffix_pattern, name_lower)
    if match:
        major = match.group(1)   # 4
        minor = match.group(2)   # 5
        family = match.group(3)  # opus
        return f"claude-{family}-{major}.{minor}"  # claude-opus-4.5
    
    # No transformation needed - return as-is
    return name


def get_model_id_for_kiro(model: str, hidden_models: dict) -> str:
    """
    Get the model ID to send to Kiro API.
    
    Normalizes the name first (dashes→dots, strip dates),
    then checks hidden_models for special internal IDs.
    
    Ported from kiro-gateway's model_resolver.py get_model_id_for_kiro().
    
    Args:
        model: External model name from client
        hidden_models: Dict mapping display names to internal Kiro IDs
    
    Returns:
        Model ID to send to Kiro API
    """
    normalized = normalize_model_name(model)
    return hidden_models.get(normalized, normalized)

# Import from core - reuse shared logic
from .converters import (
    extract_text_content,
    extract_images_from_content,
    UnifiedMessage,
    UnifiedTool,
    build_kiro_payload as core_build_kiro_payload,
)


# ==================================================================================================
# OpenAI-specific Message Processing
# ==================================================================================================

def _extract_tool_results_from_openai(content: Any) -> List[Dict[str, Any]]:
    """
    Extracts tool results from OpenAI message content.
    
    Args:
        content: Message content (can be a list with tool_result blocks)
    
    Returns:
        List of tool results in unified format for UnifiedMessage
    """
    tool_results = []
    
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": item.get("tool_use_id", ""),
                    "content": extract_text_content(item.get("content", "")) or "(empty result)"
                })
    
    return tool_results


def _extract_images_from_tool_message(content: Any) -> List[Dict[str, Any]]:
    """
    Extracts images from OpenAI tool message content.
    
    Tool messages from MCP servers (e.g., browsermcp) can contain images
    (screenshots) alongside text. This function extracts those images.
    
    Args:
        content: Tool message content (can be string or list of content blocks)
    
    Returns:
        List of images in unified format: [{"media_type": "image/jpeg", "data": "base64..."}]
    
    Example:
        >>> content = [
        ...     {"type": "text", "text": "Screenshot captured"},
        ...     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ... ]
        >>> images = _extract_images_from_tool_message(content)
        >>> len(images)
        1
    """
    # If content is not a list, no images to extract
    if not isinstance(content, list):
        return []
    
    # Use core function to extract images from content list
    images = extract_images_from_content(content)
    
    if images:
        logger.debug(f"Extracted {len(images)} image(s) from tool message content")
    
    return images


def _extract_tool_calls_from_openai(msg: ChatMessage) -> List[Dict[str, Any]]:
    """
    Extracts tool calls from OpenAI assistant message.
    
    Args:
        msg: OpenAI ChatMessage
    
    Returns:
        List of tool calls in unified format
    """
    tool_calls = []
    
    if msg.tool_calls:
        for tc in msg.tool_calls:
            if isinstance(tc, dict):
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}")
                    }
                })
    
    return tool_calls


def convert_openai_messages_to_unified(messages: List[ChatMessage]) -> Tuple[str, List[UnifiedMessage]]:
    """
    Converts OpenAI messages to unified format.
    
    Handles:
    - System messages (extracted as system prompt)
    - Tool messages (converted to user messages with tool_results)
    - Tool calls in assistant messages
    
    Args:
        messages: List of OpenAI ChatMessage objects
    
    Returns:
        Tuple of (system_prompt, unified_messages)
    """
    # Extract system prompt
    system_prompt = ""
    non_system_messages = []
    
    for msg in messages:
        if msg.role == "system":
            system_prompt += extract_text_content(msg.content) + "\n"
        else:
            non_system_messages.append(msg)
    
    system_prompt = system_prompt.strip()
    
    # Process tool messages - convert to user messages with tool_results
    processed = []
    pending_tool_results = []
    pending_tool_images = []
    total_tool_calls = 0
    total_tool_results = 0
    total_images = 0

    for msg in non_system_messages:
        if msg.role == "tool":
            # Collect tool results
            tool_result = {
                "type": "tool_result",
                "tool_use_id": msg.tool_call_id or "",
                "content": extract_text_content(msg.content) or "(empty result)"
            }
            pending_tool_results.append(tool_result)
            total_tool_results += 1
            
            # Extract images from tool message content (e.g., screenshots from MCP tools)
            tool_images = _extract_images_from_tool_message(msg.content)
            if tool_images:
                pending_tool_images.extend(tool_images)
                total_images += len(tool_images)
        else:
            # If there are accumulated tool results, create user message with them
            if pending_tool_results:
                unified_msg = UnifiedMessage(
                    role="user",
                    content="",
                    tool_results=pending_tool_results.copy(),
                    images=pending_tool_images.copy() if pending_tool_images else None
                )
                processed.append(unified_msg)
                pending_tool_results.clear()
                pending_tool_images.clear()
            
            # Convert regular message
            tool_calls = None
            tool_results = None
            images = None

            if msg.role == "assistant":
                tool_calls = _extract_tool_calls_from_openai(msg) or None
                if tool_calls:
                    total_tool_calls += len(tool_calls)
            elif msg.role == "user":
                tool_results = _extract_tool_results_from_openai(msg.content) or None
                if tool_results:
                    total_tool_results += len(tool_results)
                # Extract images from user messages
                images = extract_images_from_content(msg.content) or None
                if images:
                    total_images += len(images)

            unified_msg = UnifiedMessage(
                role=msg.role,
                content=extract_text_content(msg.content),
                tool_calls=tool_calls,
                tool_results=tool_results,
                images=images
            )
            processed.append(unified_msg)
    
    # If tool results remain at the end
    if pending_tool_results:
        unified_msg = UnifiedMessage(
            role="user",
            content="",
            tool_results=pending_tool_results.copy(),
            images=pending_tool_images.copy() if pending_tool_images else None
        )
        processed.append(unified_msg)
    
    # Log summary if any tool content or images were found
    if total_tool_calls > 0 or total_tool_results > 0 or total_images > 0:
        logger.debug(
            f"Converted {len(messages)} OpenAI messages: "
            f"{total_tool_calls} tool_calls, {total_tool_results} tool_results, {total_images} images"
        )
    
    return system_prompt, processed


def convert_openai_tools_to_unified(tools: Optional[List[Tool]]) -> Optional[List[UnifiedTool]]:
    """
    Converts OpenAI tools to unified format.
    
    Supports two formats:
    1. Standard OpenAI format: {"type": "function", "function": {"name": "...", ...}}
    2. Flat format (Cursor-style): {"name": "...", "description": "...", "input_schema": {...}}
    
    Args:
        tools: List of OpenAI Tool objects
    
    Returns:
        List of UnifiedTool objects, or None if no tools
    """
    if not tools:
        return None
    
    unified_tools = []
    for tool in tools:
        if tool.type != "function":
            continue
        
        # Standard OpenAI format (function field) takes priority
        if tool.function is not None:
            unified_tools.append(UnifiedTool(
                name=tool.function.name,
                description=tool.function.description,
                input_schema=tool.function.parameters
            ))
        # Flat format compatibility (Cursor-style)
        elif tool.name is not None:
            unified_tools.append(UnifiedTool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema
            ))
        # Skip invalid tools
        else:
            logger.warning(f"Skipping invalid tool: no function or name field found")
            continue
    
    return unified_tools if unified_tools else None


# ==================================================================================================
# Main Entry Point
# ==================================================================================================

def build_kiro_payload_from_dict(
    model: str,
    messages: list,
    tools: list = None,
    conversation_id: str = None,
    profile_arn: str = None
) -> dict:
    """
    Builds complete payload for Kiro API from dict-based OpenAI request.
    
    This is a convenience wrapper that converts dicts to dataclasses
    and then uses the full conversion pipeline.
    
    Args:
        model: Model name
        messages: List of message dicts
        tools: Optional list of tool dicts
        conversation_id: Unique conversation ID
        profile_arn: AWS CodeWhisperer profile ARN
    
    Returns:
        Payload dictionary for POST request to Kiro API
    
    Raises:
        ValueError: If there are no messages to send
    """
    from .models import create_chat_completion_request
    
    # Convert dicts to dataclasses
    request_data = create_chat_completion_request(
        model=model,
        messages=messages,
        tools=tools
    )
    
    # Convert messages to unified format
    system_prompt, unified_messages = convert_openai_messages_to_unified(request_data.messages)
    
    # Convert tools to unified format
    unified_tools = convert_openai_tools_to_unified(request_data.tools)
    
    # Get model ID for Kiro API (normalizes + resolves hidden models)
    model_id = get_model_id_for_kiro(request_data.model, HIDDEN_MODELS)
    
    logger.debug(
        f"Converting OpenAI request: model={request_data.model} -> {model_id}, "
        f"messages={len(unified_messages)}, tools={len(unified_tools) if unified_tools else 0}, "
        f"system_prompt_length={len(system_prompt)}"
    )
    
    # Use core function to build payload
    result = core_build_kiro_payload(
        messages=unified_messages,
        system_prompt=system_prompt,
        model_id=model_id,
        tools=unified_tools,
        conversation_id=conversation_id or "",
        profile_arn=profile_arn or "",
        inject_thinking=True
    )
    
    return result.payload