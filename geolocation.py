import asyncio
import httpx
from typing import Dict, Optional

# Global cache for IP -> country mappings
_ip_country_cache: Dict[str, str] = {}

async def get_ip_country(ip: str) -> Optional[str]:
    """Get country code for IP address using ipapi.co, with caching.
    
    Returns country code (e.g., 'IL') or None if failed.
    """
    if ip in _ip_country_cache:
        return _ip_country_cache[ip]
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://ipapi.co/{ip}/country/")
            if response.status_code == 200:
                country = response.text.strip().upper()
                _ip_country_cache[ip] = country
                return country
    except Exception:
        pass
    
    # Cache failure to avoid repeated calls
    _ip_country_cache[ip] = None
    return None

def is_ip_israeli(ip: str) -> bool:
    """Check if IP is from Israel."""
    # Run async function in sync context if needed
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is running, we can't use run_until_complete
            # For middleware, we'll need to handle this differently
            return False  # Temporary fallback
        else:
            country = loop.run_until_complete(get_ip_country(ip))
            return country == 'IL'
    except Exception:
        return False