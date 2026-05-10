import json
from pathlib import Path
import sys
from base64 import b64encode

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from main import app
from aisbf.routes.dashboard import providers as dashboard_providers
from main import templates


def _set_session_cookie(client: TestClient, data: dict) -> None:
    signer = TimestampSigner(app.user_middleware[2].kwargs["secret_key"])
    serialized = b64encode(json.dumps(data).encode("utf-8"))
    signed = signer.sign(serialized).decode("utf-8")
    client.cookies.set("session", signed)


dashboard_providers.init(None, templates, None)


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
