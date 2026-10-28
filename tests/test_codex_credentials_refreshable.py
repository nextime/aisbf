"""A refreshable codex credential must count as authenticated.

validate_credentials() is synchronous, so it asks CodexOAuth2.is_authenticated()
rather than the async get_valid_token_with_refresh() that every request path
uses.  While is_authenticated() was just "get_valid_token() is not None", an
expired cached access token made get_provider_handler() raise "credentials not
valid or not configured", which dropped the provider from its rotations for
good - nothing refreshes a provider it refuses to build.  On aisbf.cloud all
six codex providers sat dead that way with valid refresh tokens on disk.
"""
import base64
import json
import time

import pytest

from aisbf.auth.codex import CodexOAuth2


def _jwt(exp):
    """Minimal JWT - only the claims segment is ever parsed."""
    claims = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=")
    return "header.%s.signature" % claims.decode()


def _creds(tmp_path, access_exp=None, refresh_token="refresh-abc"):
    tokens = {}
    if access_exp is not None:
        tokens["access_token"] = _jwt(access_exp)
    if refresh_token is not None:
        tokens["refresh_token"] = refresh_token
    path = tmp_path / "codex_credentials.json"
    path.write_text(json.dumps({"auth_mode": "codex", "tokens": tokens}))
    return CodexOAuth2(credentials_file=str(path))


def test_live_access_token_is_authenticated(tmp_path):
    oauth = _creds(tmp_path, access_exp=time.time() + 3600)
    assert oauth.get_valid_token() is not None
    assert oauth.is_authenticated()


def test_expired_access_token_with_refresh_token_is_authenticated(tmp_path):
    """The regression: stale is not the same as missing."""
    oauth = _creds(tmp_path, access_exp=time.time() - 3600)
    assert oauth.get_valid_token() is None
    assert oauth.is_authenticated()


def test_access_token_inside_the_expiry_buffer_still_counts(tmp_path):
    """get_valid_token() rejects anything expiring within 5 minutes."""
    oauth = _creds(tmp_path, access_exp=time.time() + 60)
    assert oauth.get_valid_token() is None
    assert oauth.is_authenticated()


def test_expired_access_token_without_refresh_token_is_not_authenticated(tmp_path):
    oauth = _creds(tmp_path, access_exp=time.time() - 3600, refresh_token=None)
    assert not oauth.is_authenticated()


def test_no_tokens_at_all_is_not_authenticated(tmp_path):
    oauth = _creds(tmp_path, access_exp=None, refresh_token=None)
    assert not oauth.is_authenticated()


def test_missing_credentials_file_is_not_authenticated(tmp_path):
    oauth = CodexOAuth2(credentials_file=str(tmp_path / "absent.json"))
    assert not oauth.is_authenticated()


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b"])
def test_unparseable_access_token_falls_back_to_the_refresh_token(tmp_path, garbage):
    path = tmp_path / "codex_credentials.json"
    path.write_text(json.dumps(
        {"auth_mode": "codex",
         "tokens": {"access_token": garbage, "refresh_token": "refresh-abc"}}))
    oauth = CodexOAuth2(credentials_file=str(path))
    assert oauth.get_valid_token() is None
    assert oauth.is_authenticated()
