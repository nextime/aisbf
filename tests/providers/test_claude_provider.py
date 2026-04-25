import pytest
from unittest.mock import Mock, AsyncMock, patch
from aisbf.providers.claude import ClaudeProviderHandler


@pytest.fixture
def mock_auth_valid():
    """Mock ClaudeAuth with valid token."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value="valid_access_token")
    return mock


@pytest.fixture
def mock_auth_expired():
    """Mock ClaudeAuth with expired token (returns None)."""
    mock = Mock()
    mock.get_valid_token_with_refresh = AsyncMock(return_value=None)
    return mock


@pytest.mark.asyncio
async def test_handle_request_uses_refreshed_token(mock_auth_valid):
    """Test that handle_request uses get_valid_token_with_refresh."""
    handler = ClaudeProviderHandler(provider_id="test_claude", api_key=None, user_id=1)
    handler.auth = mock_auth_valid
    
    # Mock the HTTP client to avoid actual API calls
    with patch.object(handler, 'client') as mock_client:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-3-5-sonnet-20241022",
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # This should call get_valid_token_with_refresh
        await handler.handle_request(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "Hello"}],
            stream=False
        )
        
        mock_auth_valid.get_valid_token_with_refresh.assert_called()


@pytest.mark.asyncio
async def test_handle_request_raises_error_when_token_refresh_fails(mock_auth_expired):
    """Test that handle_request raises error when token refresh fails."""
    handler = ClaudeProviderHandler(provider_id="test_claude", api_key=None, user_id=1)
    handler.auth = mock_auth_expired
    
    with pytest.raises(Exception) as exc_info:
        await handler.handle_request(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "Hello"}],
            stream=False
        )
    
    assert "authentication required" in str(exc_info.value).lower() or "token" in str(exc_info.value).lower()
    mock_auth_expired.get_valid_token_with_refresh.assert_called()
