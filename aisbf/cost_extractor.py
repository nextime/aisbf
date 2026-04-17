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
        # AWS Bedrock - may include cost in usage
        if provider_id in ['amazon', 'bedrock', 'aws']:
            usage = response.get('usage', {})
            if isinstance(usage, dict):
                cost = usage.get('cost')
                if cost is not None:
                    return float(cost)
        
        # Cohere - has billed_units but not direct cost
        # Would need pricing config to convert
        if provider_id == 'cohere':
            meta = response.get('meta', {})
            if isinstance(meta, dict):
                billed_units = meta.get('billed_units', {})
                if billed_units:
                    # Return None - we'll calculate from tokens
                    # Could enhance this to calculate from billed_units
                    pass
        
        # Replicate - has prediction time
        if provider_id == 'replicate':
            metrics = response.get('metrics', {})
            if isinstance(metrics, dict):
                predict_time = metrics.get('predict_time')
                if predict_time:
                    # Would need pricing per second to calculate
                    # Return None for now - calculate from tokens
                    pass
        
        # Check for generic cost fields that some providers might use
        for cost_field in ['cost', 'price', 'amount', 'total_cost']:
            if cost_field in response:
                cost = response[cost_field]
                if cost is not None:
                    return float(cost)
            
            # Check in usage object
            usage = response.get('usage', {})
            if isinstance(usage, dict) and cost_field in usage:
                cost = usage[cost_field]
                if cost is not None:
                    return float(cost)
        
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
        # Check if this is a final chunk with usage/cost info
        usage = chunk.get('usage', {})
        if isinstance(usage, dict):
            # Try to extract cost from usage
            cost = usage.get('cost')
            if cost is not None:
                return float(cost)
        
        # Some providers might include cost at top level in final chunk
        cost = chunk.get('cost')
        if cost is not None:
            return float(cost)
        
        return None
        
    except Exception as e:
        logger.debug(f"Error extracting cost from {provider_id} streaming chunk: {e}")
        return None
