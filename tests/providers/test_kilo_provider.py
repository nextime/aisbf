import pytest
import time
from unittest.mock import Mock, AsyncMock, patch
from aisbf.providers.kilo import KiloProviderHandler


@pytest.fixture
def mock_oauth2_valid():
    """Mock KiloOAuth2 with valid token."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value="valid_token")
    return mock


@pytest.fixture
def mock_oauth2_expired():
    """Mock KiloOAuth2 with expired token (returns None)."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value=None)
    mock.initiate_device_flow = AsyncMock(return_value={
        "code": "ABC123",
        "verification_url": "https://kilo.ai/device",
        "expires_in": 600,
        "poll_interval": 3.0
    })
    return mock


@pytest.mark.asyncio
async def test_ensure_authenticated_returns_token_when_valid(mock_oauth2_valid):
    """Test that _ensure_authenticated returns token when valid."""
    handler = KiloProviderHandler(provider_id="test_kilo", api_key=None, user_id=1)
    handler.oauth2 = mock_oauth2_valid
    handler._use_api_key_auth = False
    
    result = await handler._ensure_authenticated()
    
    assert result["status"] == "authenticated"
    assert result["token"] == "valid_token"
    mock_oauth2_valid.get_valid_token_with_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_initiates_device_flow_when_expired(mock_oauth2_expired):
    """Test that _ensure_authenticated initiates device flow when token expired."""
    handler = KiloProviderHandler(provider_id="test_kilo", api_key=None, user_id=1)
    handler.oauth2 = mock_oauth2_expired
    handler._use_api_key_auth = False
    
    result = await handler._ensure_authenticated()
    
    assert result["status"] == "pending_authorization"
    assert result["code"] == "ABC123"
    assert result["verification_url"] == "https://kilo.ai/device"
    mock_oauth2_expired.get_valid_token_with_refresh.assert_called_once()
    mock_oauth2_expired.initiate_device_flow.assert_called_once()
