import asyncio
import httpx
import ipaddress
import logging
import time
from typing import Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

_IPAddr = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
_IPNet  = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# net_str -> (country, expires_at).  Only successful lookups are stored;
# failures are not cached so they are retried on the next request.
_CACHE_TTL = 30 * 24 * 3600  # 30 days
_subnet_cache: Dict[str, Tuple[str, float]] = {}


def _fallback_prefix(addr: _IPAddr) -> _IPNet:
    """Conservative fallback prefix when the API does not return one."""
    prefix = 24 if isinstance(addr, ipaddress.IPv4Address) else 48
    return ipaddress.ip_network(f"{addr}/{prefix}", strict=False)


def _find_in_cache(addr: _IPAddr) -> Optional[str]:
    """Return cached country for addr if it falls inside any cached subnet."""
    now = time.time()
    expired: List[str] = []
    result: Optional[str] = None
    matched_net: Optional[str] = None

    for net_str, (country, expires_at) in _subnet_cache.items():
        if now >= expires_at:
            expired.append(net_str)
            continue
        try:
            if addr in ipaddress.ip_network(net_str):
                result = country
                matched_net = net_str
                break
        except ValueError:
            expired.append(net_str)

    for k in expired:
        _subnet_cache.pop(k, None)

    if result is not None:
        logger.debug("geo cache hit: %s -> subnet %s -> %s", addr, matched_net, result)

    return result


async def get_ip_country(ip: str) -> Optional[str]:
    """Return the two-letter country code for an IP via ipapi.co.

    Results are cached against the provider's actual BGP prefix (from the
    ``network`` field in the JSON response) for 30 days, so all IPs in the
    same announced block share a single lookup.  Falls back to /24 (IPv4)
    or /48 (IPv6) when the API does not return a prefix.  Failures are never
    cached and will be retried on the next request.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        logger.debug("geo lookup: invalid IP %r", ip)
        return None

    cached = _find_in_cache(addr)
    if cached is not None:
        return cached

    logger.debug("geo lookup: querying ipapi.co for %s", ip)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"https://ipapi.co/{ip}/json/")
            if response.status_code != 200:
                logger.debug("geo lookup: %s returned HTTP %d", ip, response.status_code)
                return None

            data = response.json()
            country = data.get("country_code", "").strip().upper() or None
            raw_net = data.get("network", "")
            logger.debug("geo lookup: %s -> country=%s network=%r (raw response keys: %s)",
                         ip, country, raw_net, list(data.keys()))

            if not country:
                return None

            try:
                network = ipaddress.ip_network(raw_net, strict=False) if raw_net else _fallback_prefix(addr)
            except ValueError:
                logger.debug("geo lookup: %s invalid network %r, falling back to %s",
                             ip, raw_net, _fallback_prefix(addr))
                network = _fallback_prefix(addr)

            logger.debug("geo lookup: caching %s under %s for 30 days", ip, network)
            _subnet_cache[str(network)] = (country, time.time() + _CACHE_TTL)
            return country

    except Exception as exc:
        logger.debug("geo lookup: %s failed with %s: %s", ip, type(exc).__name__, exc)
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
