"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import inspect
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
from aisbf.routes.dashboard import settings as dashboard_settings
from aisbf.models import Message
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


def test_dashboard_studio_bootstraps_initial_catalog_data(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(
        dashboard_providers,
        "build_studio_catalog",
        lambda **kwargs: {
            "scope": kwargs["scope"],
            "owner_id": kwargs["owner_id"],
            "entries": [
                {
                    "id": "rotation/creative-rotation",
                    "kind": "rotation",
                    "label": "Creative Rotation",
                    "capabilities": ["chat"],
                    "partial_capabilities": ["vision"],
                }
            ],
        },
    )

    response = client.get("/dashboard/studio")

    assert response.status_code == 200
    assert '"id": "rotation/creative-rotation"' in response.text
    assert '"partial_capabilities": ["vision"]' in response.text


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
    assert rotation_entry["source_id"] == "team-default"
    assert rotation_entry["target_id"] == "team-default"
    assert rotation_entry["id"] == "rotation/team-default"
    assert autoselect_entry["source_id"] == "writer"
    assert autoselect_entry["target_id"] == "writer"
    assert autoselect_entry["id"] == "autoselect/writer"


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
        "rotation/my-rotation",
        "autoselect/my-autoselect",
    }


def test_api_provider_save_persists_inferred_studio_metadata_for_manual_models(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)

    saved_payload = {}

    monkeypatch.setattr(dashboard_providers, "_providers_json_path", lambda: Path("/tmp/providers-source.json"))
    monkeypatch.setattr(dashboard_providers, "_reload_global_config", lambda: None)
    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: DummyOpen(saved_payload), raising=False)

    response = client.post(
        "/dashboard/api/provider",
        json={
            "provider_id": "openai",
            "config": {
                "type": "openai",
                "models": [
                    {
                        "name": "whisper-large-v3",
                        "architecture": {"input_modalities": ["audio"], "output_modalities": ["text"]},
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    saved = json.loads(saved_payload["writes"][-1])
    model = saved["providers"]["openai"]["models"][0]
    assert model["studio_capabilities"] == ["audio_input", "transcription"]
    assert model["studio_capability_source"] in {"provider_metadata", "heuristic"}
    assert model["studio_capability_unknown"] is False


def test_dashboard_providers_save_persists_inferred_studio_metadata_for_bulk_save(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)

    saved_payload = {}
    monkeypatch.setattr(dashboard_providers, "_reload_global_config", lambda: None)
    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: DummyOpen(saved_payload), raising=False)

    response = client.post(
        "/dashboard/providers",
        data={
            "config": json.dumps(
                {
                    "openai": {
                        "type": "openai",
                        "models": [
                            {
                                "name": "whisper-large-v3",
                                "architecture": {"input_modalities": ["audio"], "output_modalities": ["text"]},
                            }
                        ],
                    }
                }
            )
        },
    )

    assert response.status_code == 200
    saved = json.loads(saved_payload["writes"][-1])
    model = saved["providers"]["openai"]["models"][0]
    assert model["studio_capabilities"] == ["audio_input", "transcription"]
    assert model["studio_capability_source"] in {"provider_metadata", "heuristic"}
    assert model["studio_capability_unknown"] is False
    assert "capabilities" not in model


def test_build_studio_catalog_prefers_persisted_studio_capabilities_over_legacy_capabilities():
    class ConfigStub:
        providers = {
            "openai": {
                "type": "openai",
                "models": [
                    {
                        "name": "whisper-large-v3",
                        "capabilities": ["chat"],
                        "studio_capabilities": ["audio_input", "transcription"],
                        "studio_capability_source": "heuristic",
                        "studio_capability_unknown": False,
                    }
                ],
            }
        }
        rotations = {}
        autoselect = {}

    catalog = build_studio_catalog(scope="admin", owner_id=None, config=ConfigStub())

    provider_entry = next(entry for entry in catalog["entries"] if entry["kind"] == "provider_model")
    assert provider_entry["capabilities"] == ["audio_input", "transcription"]
    assert provider_entry["metadata"]["studio_capabilities"] == ["audio_input", "transcription"]


@pytest.mark.asyncio
async def test_auto_detect_provider_models_persists_studio_metadata_without_overwriting_legacy_capabilities(monkeypatch):
    class ResponseStub:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {
                        "id": "whisper-large-v3",
                        "capabilities": ["legacy-audio"],
                        "architecture": {"input_modalities": ["audio"], "output_modalities": ["text"]},
                    }
                ]
            }

    class ClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            return ResponseStub()

    monkeypatch.setattr(dashboard_providers.httpx, "AsyncClient", lambda *args, **kwargs: ClientStub())

    models = await dashboard_providers._auto_detect_provider_models(
        "openai",
        {"type": "openai", "endpoint": "https://example.test", "api_key": "secret"},
    )

    assert models[0]["capabilities"] == ["legacy-audio"]
    assert models[0]["studio_capabilities"] == ["legacy-audio"]
    assert models[0]["studio_capability_source"] == "explicit"


def test_search_provider_models_refresh_uses_autodetect_flow_without_exposing_studio_metadata(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)

    class SourceOpen:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "providers": {
                        "openai": {
                            "type": "openai",
                            "endpoint": "https://example.test",
                            "api_key": "secret",
                            "models": [],
                        }
                    }
                }
            )

    async def fake_fetch_provider_models(provider_id, user_id=None):
        return await dashboard_providers._auto_detect_provider_models(
            provider_id,
            {"type": "openai", "endpoint": "https://example.test", "api_key": "secret"},
        )

    class ResponseStub:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {
                        "id": "whisper-large-v3",
                        "architecture": {"input_modalities": ["audio"], "output_modalities": ["text"]},
                    }
                ]
            }

    class ClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            return ResponseStub()

    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: SourceOpen(), raising=False)
    monkeypatch.setattr(dashboard_providers, "fetch_provider_models", fake_fetch_provider_models)
    monkeypatch.setattr(dashboard_providers.httpx, "AsyncClient", lambda *args, **kwargs: ClientStub())

    response = client.get("/dashboard/providers/openai/search-models?refresh=true")

    assert response.status_code == 200
    assert response.json() == {"models": ["whisper-large-v3"], "fetched_live": True}


def test_message_model_uses_pydantic_v2_model_config():
    assert Message.model_config.get("extra") == "allow"
    assert "Config" not in Message.__dict__


def test_dashboard_user_query_uses_pattern_constraints():
    route = next(route for route in dashboard_settings.router.routes if route.endpoint is dashboard_settings.dashboard_users)
    query_params = {param.name: param for param in route.dependant.query_params}

    def pattern_for(param_name):
        metadata = query_params[param_name].field_info.metadata
        return next((item.pattern for item in metadata if hasattr(item, "pattern")), None)

    assert pattern_for("order_by") == "^(username|last_login|created_at|tier_name)$"
    assert pattern_for("direction") == "^(asc|desc)$"
    assert pattern_for("status_filter") == "^(active|inactive)$"
    assert pattern_for("role_filter") == "^(admin|user)$"

    source = inspect.getsource(dashboard_settings.dashboard_users)
    assert "regex=" not in source


def test_fastapi_app_uses_lifespan_instead_of_on_event_decorators():
    lifespan_context = getattr(app.router, "lifespan_context", None)
    assert lifespan_context is not None
    assert not getattr(app.router, "on_startup", [])
    assert not getattr(app.router, "on_shutdown", [])


class DummyOpen:
    def __init__(self, sink):
        self.sink = sink
        self.buffer = ""
        self.sink.setdefault("writes", [])

    def __call__(self, path, mode="r", *args, **kwargs):
        self.path = str(path)
        self.mode = mode
        self.buffer = ""
        return self

    def __enter__(self):
        if "w" in getattr(self, "mode", ""):
            self.sink.setdefault("writes", []).append("")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if any(token in getattr(self, "path", "") for token in ["providers-source", ".aisbf/providers.json", "routes/dashboard/config/providers.json"]):
            return json.dumps({"providers": {}})
        writes = self.sink.get("writes") or []
        return writes[-1] if writes else json.dumps({"providers": {}})

    def write(self, data):
        self.buffer += data
        self.sink.setdefault("writes", [""])
        if not self.sink["writes"]:
            self.sink["writes"].append("")
        self.sink["writes"][-1] = self.buffer


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
