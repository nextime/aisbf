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
    # OpenRouter-style extended fields
    description: Optional[str] = None
    context_length: Optional[int] = None
    architecture: Optional[Dict] = None  # modality, input_modalities, output_modalities, tokenizer, instruct_type
    pricing: Optional[Dict] = None  # prompt, completion, input_cache_read
    top_provider: Optional[Dict] = None  # context_length, max_completion_tokens, is_moderated
    supported_parameters: Optional[List[str]] = None
    default_parameters: Optional[Dict] = None

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


class AccountTier(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price_monthly: float = 0.0
    price_yearly: float = 0.0
    is_default: bool = False
    is_active: bool = True
    is_visible: bool = True  # If False, tier is hidden from user selection but can be assigned by admin
    
    # Limits
    max_requests_per_day: int = -1
    max_requests_per_month: int = -1
    max_providers: int = -1
    max_rotations: int = -1
    max_autoselections: int = -1
    max_rotation_models: int = -1
    max_autoselection_models: int = -1
    
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class UserSubscription(BaseModel):
    id: Optional[int] = None
    user_id: int
    tier_id: int
    status: str = "active"  # active, canceled, expired, suspended
    start_date: int
    end_date: Optional[int] = None
    next_billing_date: Optional[int] = None
    trial_end_date: Optional[int] = None
    payment_method_id: Optional[int] = None
    auto_renew: bool = True
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class PaymentMethod(BaseModel):
    id: Optional[int] = None
    user_id: int
    type: str  # paypal, stripe, bitcoin, eth, usdt, usdc
    identifier: str
    is_default: bool = False
    is_active: bool = True
    metadata: Optional[Dict] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class PaymentTransaction(BaseModel):
    id: Optional[int] = None
    user_id: int
    tier_id: Optional[int] = None
    subscription_id: Optional[int] = None
    payment_method_id: Optional[int] = None
    amount: float
    currency: str = "USD"
    status: str  # pending, completed, failed, refunded
    transaction_type: str  # subscription, one_time, renewal
    external_transaction_id: Optional[str] = None
    metadata: Optional[Dict] = None
    created_at: Optional[int] = None
    completed_at: Optional[int] = None
