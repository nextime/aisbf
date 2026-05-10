import json
from pathlib import Path
import sys
from base64 import b64encode
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aisbf.routes.dashboard import providers as dashboard_providers
from aisbf.database import DatabaseRegistry
from aisbf.studio import build_studio_catalog
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


def test_dashboard_studio_renders_empty_diagnostics_contract_for_shell_boot():
    client = TestClient(app)
    _login_as_admin(client)

    response = client.get("/dashboard/studio")

    assert response.status_code == 200
    assert 'id="studio-diagnostics" data-empty-message="No diagnostics yet."' in response.text
    assert '<span data-i18n="studio.diagnostics_empty">No diagnostics yet.</span>' in response.text
    assert '<script id="studio-bootstrap" type="application/json">{}</script>' in response.text


def test_dashboard_studio_catalog_returns_global_resources_for_admin(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(
        dashboard_providers,
        "build_studio_catalog",
        lambda **kwargs: {
            "scope": kwargs["scope"],
            "owner_id": kwargs["owner_id"],
            "entries": [{"id": "provider/openai/gpt-4o", "owner_scope": "admin"}],
        },
    )

    response = client.get("/dashboard/studio/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "scope": "admin",
        "owner_id": None,
        "entries": [{"id": "provider/openai/gpt-4o", "owner_scope": "admin"}],
    }


def test_dashboard_studio_catalog_uses_api_auth_json_when_logged_out():
    client = TestClient(app)

    response = client.get("/dashboard/studio/catalog")

    assert response.status_code == 401
    assert response.json() == {"error": "Authentication required"}


def test_dashboard_studio_catalog_returns_user_resources_for_user(monkeypatch):
    client = TestClient(app)
    db = DatabaseRegistry.get_config_database()
    user_id = db.create_user(f"studio-demo-{uuid4().hex}", "not-used", role="user")
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": "demo",
            "role": "user",
            "user_id": user_id,
            "expires_at": 4102444800,
        },
    )

    monkeypatch.setattr(
        dashboard_providers,
        "build_studio_catalog",
        lambda **kwargs: {
            "scope": kwargs["scope"],
            "owner_id": kwargs["owner_id"],
            "entries": [{"id": "provider/demo/gpt-4o-mini", "owner_scope": "user"}],
        },
    )

    response = client.get("/dashboard/studio/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "scope": "user",
        "owner_id": user_id,
        "entries": [{"id": "provider/demo/gpt-4o-mini", "owner_scope": "user"}],
    }


def test_dashboard_studio_catalog_does_not_treat_user_role_without_user_id_as_admin(monkeypatch):
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

    monkeypatch.setattr(
        dashboard_providers,
        "build_studio_catalog",
        lambda **kwargs: {
            "scope": kwargs["scope"],
            "owner_id": kwargs["owner_id"],
            "entries": [],
        },
    )

    response = client.get("/dashboard/studio/catalog")

    assert response.status_code == 200
    assert response.json()["scope"] == "user"
    assert response.json()["owner_id"] is None


def test_build_studio_catalog_uses_global_config_for_admin_scope():
    class ModelStub:
        def __init__(self, name, description=None, capabilities=None, context_length=None, architecture=None):
            self.name = name
            self.description = description
            self.capabilities = capabilities
            self.context_length = context_length
            self.architecture = architecture

    class ProviderStub:
        def __init__(self, provider_type, models):
            self.type = provider_type
            self.models = models

    class ConfigStub:
        providers = {
            "openai": ProviderStub(
                "openai",
                [ModelStub("gpt-4o", description="Flagship", capabilities=["chat", "vision"], context_length=128000)],
            )
        }
        rotations = {
            "team-default": {
                "model_name": "Team default",
                "providers": [{"provider": "openai", "model": "gpt-4o"}],
                "capabilities": ["chat"],
            }
        }
        autoselect = {
            "writer": {
                "model_name": "Writer",
                "description": "General writing",
                "fallback": "openai/gpt-4o",
                "selection_model": "internal",
                "available_models": [{"model_id": "openai/gpt-4o", "description": "Primary"}],
                "capabilities": ["chat"],
            }
        }

    catalog = build_studio_catalog(scope="admin", owner_id=None, config=ConfigStub())

    assert catalog["scope"] == "admin"
    assert catalog["owner_id"] is None
    assert {entry["kind"] for entry in catalog["entries"]} == {"provider_model", "rotation", "autoselect"}
    provider_entry = next(entry for entry in catalog["entries"] if entry["kind"] == "provider_model")
    assert provider_entry["id"] == "provider/openai/gpt-4o"
    assert provider_entry["owner_scope"] == "admin"
    assert provider_entry["metadata"]["context_length"] == 128000


def test_build_studio_catalog_falls_back_to_dashboard_global_provider_source(monkeypatch):
    monkeypatch.setattr(
        "aisbf.studio._load_global_providers_from_source",
        lambda: {
            "fallback-openai": {
                "type": "openai",
                "models": [{"name": "gpt-4.1-mini", "description": "Fallback model", "capabilities": ["chat"]}],
            }
        },
    )

    catalog = build_studio_catalog(scope="admin", owner_id=None, config=None)

    assert catalog["scope"] == "admin"
    provider_entry = next(entry for entry in catalog["entries"] if entry["kind"] == "provider_model")
    assert provider_entry["id"] == "provider/fallback-openai/gpt-4.1-mini"
    assert provider_entry["owner_scope"] == "admin"


def test_build_studio_catalog_reuses_catalog_entry_contract_for_non_provider_resources():
    class ConfigStub:
        providers = {}
        rotations = {
            "team-default": {
                "model_name": "Team default",
                "providers": [{"provider": "openai", "model": "gpt-4o"}],
                "capabilities": ["chat"],
            }
        }
        autoselect = {
            "writer": {
                "model_name": "Writer",
                "description": "General writing",
                "fallback": "openai/gpt-4o",
                "selection_model": "internal",
                "available_models": [{"model_id": "openai/gpt-4o", "description": "Primary"}],
                "capabilities": ["chat"],
            }
        }

    catalog = build_studio_catalog(scope="admin", owner_id=None, config=ConfigStub())

    rotation_entry = next(entry for entry in catalog["entries"] if entry["kind"] == "rotation")
    autoselect_entry = next(entry for entry in catalog["entries"] if entry["kind"] == "autoselect")
    assert rotation_entry["source_id"] == "rotation"
    assert rotation_entry["target_id"] == "team-default"
    assert rotation_entry["id"] == "rotation/rotation/team-default"
    assert autoselect_entry["source_id"] == "autoselect"
    assert autoselect_entry["target_id"] == "writer"
    assert autoselect_entry["id"] == "autoselect/autoselect/writer"


def test_build_studio_catalog_uses_user_owned_resources_for_user_scope():
    class DbStub:
        def get_user_providers(self, user_id):
            assert user_id == 17
            return [{
                "provider_id": "local-openai",
                "config": {
                    "type": "openai",
                    "models": [{"name": "gpt-4o-mini", "description": "Mini", "capabilities": ["chat"]}],
                },
            }]

        def get_user_rotations(self, user_id):
            assert user_id == 17
            return [{
                "rotation_id": "my-rotation",
                "config": {"model_name": "My rotation", "providers": [{"provider": "local-openai", "model": "gpt-4o-mini"}]},
            }]

        def get_user_autoselects(self, user_id):
            assert user_id == 17
            return [{
                "autoselect_id": "my-autoselect",
                "config": {
                    "model_name": "My autoselect",
                    "description": "Pick best model",
                    "fallback": "local-openai/gpt-4o-mini",
                    "selection_model": "internal",
                    "available_models": [{"model_id": "local-openai/gpt-4o-mini", "description": "Mini"}],
                },
            }]

    catalog = build_studio_catalog(scope="user", owner_id=17, db=DbStub())

    assert catalog["scope"] == "user"
    assert catalog["owner_id"] == 17
    assert all(entry["owner_scope"] == "user" for entry in catalog["entries"])
    assert {entry["id"] for entry in catalog["entries"]} == {
        "provider/local-openai/gpt-4o-mini",
        "rotation/rotation/my-rotation",
        "autoselect/autoselect/my-autoselect",
    }


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
