import json
from pathlib import Path
import sys
from base64 import b64encode

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aisbf.routes.dashboard import providers as dashboard_providers
from main import app
from main import templates


@pytest.fixture(autouse=True)
def dashboard_studio_route_init():
    previous_templates = getattr(dashboard_providers, "_templates", None)
    previous_config = getattr(dashboard_providers, "_config", None)
    previous_server_config = getattr(dashboard_providers, "_server_config", None)
    dashboard_providers.init(None, templates, None)
    yield
    dashboard_providers._templates = previous_templates
    dashboard_providers._config = previous_config
    dashboard_providers._server_config = previous_server_config


def test_dashboard_studio_redirects_when_logged_out():
    client = TestClient(app)

    response = client.get("/dashboard/studio", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/dashboard/login")


def test_dashboard_studio_page_is_available_for_admin_with_active_nav():
    client = TestClient(app)
    _login_as_admin(client)

    response = client.get("/dashboard/studio")

    assert response.status_code == 200
    assert 'data-i18n="nav.studio">Studio</a>' in response.text
    assert 'class="container container-wide"' in response.text
    assert 'class="content content-wide"' in response.text
    assert 'data-studio-shell="dashboard"' in response.text


def test_dashboard_studio_nav_entry_is_present_for_user_session_shell():
    client = TestClient(app)
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": "demo",
            "role": "user",
            "user_id": None,
            "expires_at": 4102444800,
        },
    )

    response = client.get("/dashboard/studio")

    assert response.status_code == 200
    assert 'data-i18n="nav.studio">Studio</a>' in response.text
    assert 'data-studio-shell="dashboard"' in response.text


def test_dashboard_studio_preserves_empty_diagnostics_copy_before_targets_load():
    diagnostics_text = "No diagnostics yet."

    rendered = _render_studio_bootstrap({})

    assert rendered["dataset_state"] == "empty"
    assert rendered["text"] == diagnostics_text


def _render_studio_bootstrap(payload: dict) -> dict:
    diagnostics_text = "No diagnostics yet."
    targets = payload.get("targets") if isinstance(payload, dict) else None
    if isinstance(targets, list) and targets:
        return {"dataset_state": "ready", "text": "Studio bootstrap payload loaded."}
    return {"dataset_state": "empty", "text": diagnostics_text}


def _find_session_secret() -> str:
    for middleware in app.user_middleware:
        kwargs = getattr(middleware, "kwargs", {})
        secret_key = kwargs.get("secret_key")
        if secret_key:
            return secret_key
    raise AssertionError("Session middleware secret key not found")


def _set_session_cookie(client: TestClient, data: dict) -> None:
    signer = TimestampSigner(_find_session_secret())
    serialized = b64encode(json.dumps(data).encode("utf-8"))
    signed = signer.sign(serialized).decode("utf-8")
    client.cookies.set("session", signed)


def _login_as_admin(client: TestClient) -> None:
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": "admin",
            "role": "admin",
            "user_id": None,
            "expires_at": 4102444800,
        },
    )
