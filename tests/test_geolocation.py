import pytest
import time
import ipaddress
from unittest.mock import patch, AsyncMock, Mock
from aisbf.geolocation import get_ip_country, _subnet_cache, _find_in_cache, _fallback_prefix


@pytest.fixture(autouse=True)
def clear_cache():
    _subnet_cache.clear()
    yield
    _subnet_cache.clear()


def _mock_json_response(country: str, network: str, status: int = 200):
    m = Mock()
    m.status_code = status
    m.json.return_value = {"country_code": country, "network": network}
    return m


# --- _fallback_prefix ---

def test_fallback_prefix_ipv4():
    assert _fallback_prefix(ipaddress.ip_address("1.2.3.4")) == ipaddress.ip_network("1.2.3.0/24")

def test_fallback_prefix_ipv6():
    assert _fallback_prefix(ipaddress.ip_address("2001:db8::1")) == ipaddress.ip_network("2001:db8::/48")


# --- _find_in_cache ---

def test_find_in_cache_hit():
    _subnet_cache["10.0.0.0/8"] = ("US", time.time() + 3600)
    addr = ipaddress.ip_address("10.1.2.3")
    assert _find_in_cache(addr) == "US"

def test_find_in_cache_miss():
    _subnet_cache["192.168.0.0/24"] = ("DE", time.time() + 3600)
    addr = ipaddress.ip_address("10.0.0.1")
    assert _find_in_cache(addr) is None

def test_find_in_cache_expired_entry_removed():
    _subnet_cache["10.0.0.0/8"] = ("US", time.time() - 1)
    addr = ipaddress.ip_address("10.1.2.3")
    assert _find_in_cache(addr) is None
    assert "10.0.0.0/8" not in _subnet_cache


# --- invalid IP ---

@pytest.mark.asyncio
async def test_invalid_ip_returns_none_no_api_call():
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        assert await get_ip_country("not-an-ip") is None
        mock_get.assert_not_called()


# --- uses actual network prefix from API ---

@pytest.mark.asyncio
async def test_uses_provider_network_prefix():
    """API returns /16; the cache key should be the /16, not a /24."""
    resp = _mock_json_response("US", "1.2.0.0/16")
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=resp):
        await get_ip_country("1.2.3.4")

    assert "1.2.0.0/16" in _subnet_cache
    assert "1.2.3.0/24" not in _subnet_cache


@pytest.mark.asyncio
async def test_ips_in_same_provider_block_share_single_lookup():
    """Two IPs in the same announced /16 should cause only one API call."""
    resp = _mock_json_response("US", "1.2.0.0/16")
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=resp) as mock_get:
        await get_ip_country("1.2.3.4")
        await get_ip_country("1.2.100.200")   # same /16, different /24

        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_ips_in_different_provider_blocks_each_call_api():
    resp1 = _mock_json_response("US", "1.2.0.0/16")
    resp2 = _mock_json_response("DE", "5.6.0.0/16")
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [resp1, resp2]
        r1 = await get_ip_country("1.2.3.4")
        r2 = await get_ip_country("5.6.7.8")
        assert r1 == "US"
        assert r2 == "DE"
        assert mock_get.call_count == 2


# --- fallback when network field is absent or invalid ---

@pytest.mark.asyncio
async def test_fallback_to_slash24_when_network_absent():
    m = Mock(status_code=200)
    m.json.return_value = {"country_code": "FR"}   # no "network" key
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=m):
        result = await get_ip_country("9.9.9.9")

    assert result == "FR"
    assert "9.9.9.0/24" in _subnet_cache


@pytest.mark.asyncio
async def test_fallback_to_slash24_when_network_invalid():
    m = Mock(status_code=200)
    m.json.return_value = {"country_code": "FR", "network": "not-a-network"}
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=m):
        result = await get_ip_country("9.9.9.9")

    assert result == "FR"
    assert "9.9.9.0/24" in _subnet_cache


# --- failure handling — must not pollute cache ---

@pytest.mark.asyncio
async def test_api_exception_not_cached():
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("timeout")
        assert await get_ip_country("1.2.3.4") is None
    assert len(_subnet_cache) == 0


@pytest.mark.asyncio
async def test_non_200_not_cached():
    m = Mock(status_code=429)
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=m):
        assert await get_ip_country("1.2.3.4") is None
    assert len(_subnet_cache) == 0


@pytest.mark.asyncio
async def test_failure_then_success_retries():
    fail = Mock(status_code=500)
    ok   = _mock_json_response("IT", "1.2.0.0/16")
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = fail
        await get_ip_country("1.2.3.4")
        assert len(_subnet_cache) == 0

        mock_get.return_value = ok
        result = await get_ip_country("1.2.3.4")
        assert result == "IT"
        assert "1.2.0.0/16" in _subnet_cache


# --- TTL expiry ---

@pytest.mark.asyncio
async def test_expired_entry_re_fetched():
    _subnet_cache["1.2.3.0/24"] = ("US", time.time() - 1)
    resp = _mock_json_response("US", "1.2.3.0/24")
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=resp) as mock_get:
        result = await get_ip_country("1.2.3.4")
        assert result == "US"
        mock_get.assert_called_once()
