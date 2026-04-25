import pytest
import time
import json
import tempfile
import os
from aisbf.auth.claude import ClaudeAuth


@pytest.fixture
def temp_credentials_file():
    """Create a temporary credentials file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def valid_tokens():
    """Valid tokens with future expiry."""
    return {
        "access_token": "valid_access_token",
        "refresh_token": "valid_refresh_token",
        "expires_in": 3600,
        "expires_at": time.time() + 3600,  # Expires in 1 hour
        "token_type": "Bearer"
    }


@pytest.fixture
def expired_tokens():
    """Expired tokens."""
    return {
        "access_token": "expired_access_token",
        "refresh_token": "expired_refresh_token",
        "expires_in": 3600,
        "expires_at": time.time() - 3600,  # Expired 1 hour ago
        "token_type": "Bearer"
    }


def test_get_valid_token_returns_token_when_valid(temp_credentials_file, valid_tokens):
    """Test that get_valid_token returns token when valid (no refresh)."""
    # Save valid tokens
    with open(temp_credentials_file, 'w') as f:
        json.dump(valid_tokens, f)
    
    auth = ClaudeAuth(credentials_file=temp_credentials_file)
    
    token = auth.get_valid_token()
    
    assert token == "valid_access_token"


def test_get_valid_token_returns_none_when_expired(temp_credentials_file, expired_tokens):
    """Test that get_valid_token returns None when expired (no refresh attempt)."""
    # Save expired tokens
    with open(temp_credentials_file, 'w') as f:
        json.dump(expired_tokens, f)
    
    auth = ClaudeAuth(credentials_file=temp_credentials_file)
    
    token = auth.get_valid_token()
    
    assert token is None


@pytest.mark.asyncio
async def test_get_valid_token_with_refresh_returns_valid_token(temp_credentials_file, valid_tokens):
    """Test that get_valid_token_with_refresh returns token when valid."""
    # Save valid tokens
    with open(temp_credentials_file, 'w') as f:
        json.dump(valid_tokens, f)
    
    auth = ClaudeAuth(credentials_file=temp_credentials_file)
    
    token = await auth.get_valid_token_with_refresh()
    
    assert token == "valid_access_token"
