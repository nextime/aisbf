"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Cost extraction utilities for provider responses.

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
"""

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


def _coerce_cost_value(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        if isinstance(value, dict):
            for key in ('usd', 'amount', 'value', 'total'):
                if key in value:
                    coerced = _coerce_cost_value(value[key])
                    if coerced is not None:
                        return coerced
            return None
        if isinstance(value, str):
            cleaned = value.strip().replace('$', '')
            if cleaned.lower().startswith('usd '):
                cleaned = cleaned[4:]
            return float(cleaned)
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_nested_cost(obj: Any) -> Optional[float]:
    if isinstance(obj, dict):
        prioritized_keys = (
            'cost', 'total_cost', 'total_price', 'price', 'amount', 'usd_cost',
            'billed_cost', 'request_cost', 'charge', 'credits_cost'
        )
        for key in prioritized_keys:
            if key in obj:
                coerced = _coerce_cost_value(obj.get(key))
                if coerced is not None:
                    return coerced
        for value in obj.values():
            nested = _find_nested_cost(value)
            if nested is not None:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _find_nested_cost(item)
            if nested is not None:
                return nested
    return None


def extract_cost_from_response(response: Dict[str, Any], provider_id: str) -> Optional[float]:
    """
    Extract actual cost from provider response if available.
    
    Args:
        response: Provider response dictionary
        provider_id: Provider identifier
        
    Returns:
        Cost in USD if found, None otherwise
    """
    if not response or not isinstance(response, dict):
        return None
    
    try:
        provider_id_lower = (provider_id or '').lower()

        if 'x_openai_metadata' in response:
            cost = _find_nested_cost(response['x_openai_metadata'])
            if cost is not None:
                return cost

        if provider_id_lower in ['amazon', 'bedrock', 'aws', 'openrouter', 'openai', 'codex', 'claude', 'anthropic', 'google', 'qwen', 'kiro', 'kilo', 'replicate', 'cohere']:
            cost = _find_nested_cost(response)
            if cost is not None:
                return cost

        return None
        
    except Exception as e:
        logger.debug(f"Error extracting cost from {provider_id} response: {e}")
        return None


def extract_cost_from_streaming_chunk(chunk: Dict[str, Any], provider_id: str) -> Optional[float]:
    """
    Extract cost from streaming response chunk if available.
    
    Most providers don't include cost in streaming chunks, but some might
    include it in the final chunk.
    
    Args:
        chunk: Streaming chunk dictionary
        provider_id: Provider identifier
        
    Returns:
        Cost in USD if found, None otherwise
    """
    if not chunk or not isinstance(chunk, dict):
        return None
    
    try:
        return _find_nested_cost(chunk)
        
    except Exception as e:
        logger.debug(f"Error extracting cost from {provider_id} streaming chunk: {e}")
        return None
