import pytest
from unittest.mock import patch, AsyncMock, Mock
from aisbf.geolocation import get_ip_country, _ip_country_cache

@pytest.mark.asyncio
async def test_invalid_ip_validation():
    """Test that invalid IPs return None without API call"""
    _ip_country_cache.clear()
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        result = await get_ip_country("invalid")
        assert result is None
        assert _ip_country_cache["invalid"] is None
        mock_get.assert_not_called()

@pytest.mark.asyncio
async def test_caching():
    """Test that results are cached and repeated calls return cached results"""
    _ip_country_cache.clear()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "US"
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result1 = await get_ip_country("1.1.1.1")
        assert result1 == "US"
        assert _ip_country_cache["1.1.1.1"] == "US"
        mock_get.assert_called_once()

        result2 = await get_ip_country("1.1.1.1")
        assert result2 == "US"
        mock_get.assert_called_once()  # cache hit — still only one call

@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for valid IPs when API fails"""
    _ip_country_cache.clear()
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("API fail")

        result = await get_ip_country("1.1.1.1")
        assert result is None
        assert _ip_country_cache["1.1.1.1"] is None
        mock_get.assert_called_once()
