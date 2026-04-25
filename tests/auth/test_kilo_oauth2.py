import pytest
import time
import json
import tempfile
import os
from aisbf.auth.kilo import KiloOAuth2


@pytest.fixture
def temp_credentials_file():
    """Create a temporary credentials file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def valid_credentials():
    """Valid credentials with future expiry."""
    return {
        "type": "oauth",
        "access": "valid_access_token",
        "refresh": "valid_refresh_token",
        "expires": int(time.time()) + 3600,
        "userEmail": "test@example.com"
    }


@pytest.fixture
def expired_credentials():
    """Expired credentials."""
    return {
        "type": "oauth",
        "access": "expired_access_token",
        "refresh": "expired_refresh_token",
        "expires": int(time.time()) - 3600,
        "userEmail": "test@example.com"
    }


@pytest.mark.asyncio
async def test_get_valid_token_with_refresh_returns_valid_token(temp_credentials_file, valid_credentials):
    """Test that get_valid_token_with_refresh returns token when valid."""
    with open(temp_credentials_file, 'w') as f:
        json.dump(valid_credentials, f)
    
    oauth2 = KiloOAuth2(credentials_file=temp_credentials_file)
    
    token = await oauth2.get_valid_token_with_refresh()
    
    assert token == "valid_access_token"


@pytest.mark.asyncio
async def test_get_valid_token_with_refresh_returns_none_when_expired(temp_credentials_file, expired_credentials):
    """Test that get_valid_token_with_refresh returns None when token expired."""
    with open(temp_credentials_file, 'w') as f:
        json.dump(expired_credentials, f)
    
    oauth2 = KiloOAuth2(credentials_file=temp_credentials_file)
    
    token = await oauth2.get_valid_token_with_refresh()
    
    assert token is None
