"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

A modular proxy server for managing multiple AI provider integrations.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Why did the programmer quit his job? Because he didn't get arrays!

A modular proxy server for managing multiple AI provider integrations.
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Union

class Message(BaseModel):
    role: str
    content: Union[str, List[Dict], List, None] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    class Config:
        extra = "allow"  # Allow extra fields not defined in the model
class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False
    tools: Optional[List[Dict]] = None
    tool_choice: Optional[Union[str, Dict]] = None

class ChatCompletionResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: List[Dict]
    usage: Optional[Dict] = None
    stream: Optional[bool] = False

class Model(BaseModel):
    id: str
    name: str
    provider_id: str
    weight: int = 1
    rate_limit: Optional[float] = None
    max_request_tokens: Optional[int] = None
    rate_limit_TPM: Optional[int] = None  # Max tokens per minute
    rate_limit_TPH: Optional[int] = None  # Max tokens per hour
    rate_limit_TPD: Optional[int] = None  # Max tokens per day
    context_size: Optional[int] = None  # Max context size in tokens for the model
    condense_context: Optional[int] = None  # Percentage (0-100) at which to condense context
    condense_method: Optional[Union[str, List[str]]] = None  # Method(s) for condensation: "hierarchical", "conversational", "semantic", "algorithmic"
    error_cooldown: Optional[int] = None  # Cooldown period in seconds after 3 consecutive failures (default: 300)

class Provider(BaseModel):
    id: str
    name: str
    type: str
    endpoint: str
    api_key_required: bool
    models: List[Model] = []

class ErrorTracking(BaseModel):
    failures: int
    last_failure: Optional[int]
    disabled_until: Optional[int]
