"""
Data models for Kiro integration.

Simple dataclasses to represent OpenAI-style requests for the Kiro converters.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


@dataclass
class FunctionDefinition:
    """Function definition for tools"""
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


@dataclass
class Tool:
    """Tool definition"""
    type: str = "function"
    function: Optional[FunctionDefinition] = None
    # Flat format support (Cursor-style)
    name: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None


@dataclass
class ChatMessage:
    """Chat message"""
    role: str
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class ChatCompletionRequest:
    """Chat completion request"""
    model: str
    messages: List[ChatMessage]
    tools: Optional[List[Tool]] = None
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


def dict_to_chat_message(msg_dict: Dict[str, Any]) -> ChatMessage:
    """Convert dict to ChatMessage"""
    return ChatMessage(
        role=msg_dict.get("role", "user"),
        content=msg_dict.get("content"),
        tool_calls=msg_dict.get("tool_calls"),
        tool_call_id=msg_dict.get("tool_call_id"),
        name=msg_dict.get("name")
    )


def dict_to_tool(tool_dict: Dict[str, Any]) -> Tool:
    """Convert dict to Tool"""
    tool_type = tool_dict.get("type", "function")
    
    # Standard OpenAI format
    if "function" in tool_dict:
        func_dict = tool_dict["function"]
        function = FunctionDefinition(
            name=func_dict.get("name", ""),
            description=func_dict.get("description"),
            parameters=func_dict.get("parameters")
        )
        return Tool(type=tool_type, function=function)
    
    # Flat format (Cursor-style)
    return Tool(
        type=tool_type,
        name=tool_dict.get("name"),
        description=tool_dict.get("description"),
        input_schema=tool_dict.get("input_schema") or tool_dict.get("parameters")
    )


def create_chat_completion_request(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = 1.0,
    max_tokens: Optional[int] = None,
    stream: Optional[bool] = False
) -> ChatCompletionRequest:
    """Create ChatCompletionRequest from dicts"""
    chat_messages = [dict_to_chat_message(msg) for msg in messages]
    chat_tools = [dict_to_tool(tool) for tool in tools] if tools else None
    
    return ChatCompletionRequest(
        model=model,
        messages=chat_messages,
        tools=chat_tools,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream
    )
