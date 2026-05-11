import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aisbf.config import ProviderConfig, config
from aisbf.database import DatabaseManager, DatabaseRegistry
from aisbf.providers import PROVIDER_HANDLERS, get_provider_handler
from aisbf.providers.base import BaseProviderHandler
from aisbf.providers.runpod import RunpodProviderHandler
from aisbf.app.model_cache import get_provider_models, _model_cache, _model_cache_timestamps, _endpoint_model_cache
from fastapi.responses import HTMLResponse

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app


class StubRunpodHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str | None = None, user_id: int | None = None, provider_config=None):
        self.provider_config = provider_config
        self.user_provider_config = provider_config if isinstance(provider_config, dict) else None
        super().__init__(provider_id, api_key, user_id=user_id)

    def validate_credentials(self) -> bool:
        return True

    async def get_models(self):
        return []


@pytest.fixture(autouse=True)
def reset_runpod_state(monkeypatch, tmp_path):
    original_handlers = dict(PROVIDER_HANDLERS)
    original_provider = config.providers.get("runpod-test")
    original_error = config.error_tracking.get("runpod-test")
    original_instances = dict(DatabaseRegistry._instances)

    PROVIDER_HANDLERS["runpod"] = StubRunpodHandler
    config.providers["runpod-test"] = ProviderConfig(
        id="runpod-test",
        name="RunPod Test",
        endpoint="https://rest.runpod.io/v1",
        type="runpod",
        api_key_required=True,
        api_key="test-key",
        rate_limit=0,
        runpod_config={
            "mode": "public",
            "account_name": "test-account",
            "public_endpoint_protocol_default": "auto",
        },
    )
    config.error_tracking["runpod-test"] = {
        "enabled": True,
        "max_errors": 5,
        "cooldown_seconds": 60,
        "failures": 0,
        "last_failure": 0,
        "disabled_until": None,
    }

    _model_cache.clear()
    _model_cache_timestamps.clear()
    _endpoint_model_cache.clear()

    db_path = tmp_path / "runpod-test.db"
    DatabaseRegistry._instances = {}
    db = DatabaseRegistry.get_config_database({"type": "sqlite", "sqlite_path": str(db_path)})

    yield db

    PROVIDER_HANDLERS.clear()
    PROVIDER_HANDLERS.update(original_handlers)
    if original_provider is None:
        config.providers.pop("runpod-test", None)
    else:
        config.providers["runpod-test"] = original_provider
    if original_error is None:
        config.error_tracking.pop("runpod-test", None)
    else:
        config.error_tracking["runpod-test"] = original_error
    DatabaseRegistry._instances = original_instances


def test_provider_config_accepts_runpod_config():
    provider = ProviderConfig(
        id="runpod-test",
        name="RunPod",
        endpoint="https://rest.runpod.io/v1",
        type="runpod",
        api_key_required=True,
        api_key="key",
        rate_limit=0,
        runpod_config={
            "mode": "pod",
            "wrapper_mode": "openai",
            "pod_id": "pod-123",
        },
    )

    assert provider.runpod_config["wrapper_mode"] == "openai"
    assert provider.runpod_config["pod_id"] == "pod-123"


def test_get_provider_handler_supports_runpod(reset_runpod_state):
    handler = get_provider_handler("runpod-test")

    assert isinstance(handler, StubRunpodHandler)
    assert handler.provider_id == "runpod-test"


def test_database_migration_creates_runpod_provider_state_table(reset_runpod_state):
    conn = sqlite3.connect(reset_runpod_state.db_config["sqlite_path"])
    try:
        rows = conn.execute("PRAGMA table_info(runpod_provider_state)").fetchall()
    finally:
        conn.close()

    column_names = {row[1] for row in rows}
    assert rows
    assert {"provider_id", "resource_kind", "status", "metadata", "updated_at"}.issubset(column_names)


@pytest.mark.asyncio
async def test_runpod_public_models_use_cached_catalog(reset_runpod_state):
    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="public",
        wrapper_mode=None,
        resource_id="public-catalog",
        resource_kind="public",
        status="ready",
        endpoint_url="https://api.runpod.ai/v2",
        public_catalog_json=[
            {
                "id": "black-forest-labs-flux-1-dev",
                "name": "Flux Dev",
                "protocol": "runpod_public",
                "capabilities": ["image"],
                "route_base": "https://api.runpod.ai/v2/black-forest-labs-flux-1-dev",
                "request_mode": "runsync",
            }
        ],
        metadata={"source": "test"},
    )

    models = await get_provider_models("runpod-test", config.providers["runpod-test"], config)

    assert len(models) == 1
    assert models[0]["id"] == "runpod-test/black-forest-labs-flux-1-dev"
    assert models[0]["source"] == "api_cache"
    assert models[0]["capabilities"] == ["image"]


@pytest.mark.asyncio
async def test_runpod_refresh_public_catalog_normalizes_live_entries(reset_runpod_state, monkeypatch):
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=config.providers["runpod-test"])

    async def fake_public_catalog_source():
        return [
            {
                "id": "black-forest-labs-flux-1-dev",
                "name": "Flux Dev",
                "route_base": "https://api.runpod.ai/v2/black-forest-labs-flux-1-dev",
                "description": "Image model",
                "schema": {"input": {"prompt": "string"}},
            }
        ]

    monkeypatch.setattr(handler, "_fetch_live_public_catalog_entries", fake_public_catalog_source)

    catalog = await handler.refresh_public_catalog()

    assert len(catalog) == 1
    assert catalog[0]["id"] == "black-forest-labs-flux-1-dev"
    assert catalog[0]["route_base"] == "https://api.runpod.ai/v2/black-forest-labs-flux-1-dev"
    assert catalog[0]["protocol"] in {"runpod_public", "openai"}
    state = reset_runpod_state.get_runpod_provider_state("global", None, "runpod-test")
    assert state["metadata"]["catalog_item_count"] == 1


@pytest.mark.asyncio
async def test_runpod_public_refresh_applies_manual_protocol_override(reset_runpod_state, monkeypatch):
    provider = config.providers["runpod-test"]
    provider.runpod_config["public_models"] = {
        "black-forest-labs-flux-1-dev": {"protocol": "openai"}
    }
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=provider)

    async def fake_public_catalog_source():
        return [
            {
                "id": "black-forest-labs-flux-1-dev",
                "route_base": "https://api.runpod.ai/v2/black-forest-labs-flux-1-dev",
                "protocol": "runpod_public",
            }
        ]

    monkeypatch.setattr(handler, "_fetch_live_public_catalog_entries", fake_public_catalog_source)

    catalog = await handler.refresh_public_catalog()

    assert catalog[0]["protocol"] == "openai"


@pytest.mark.asyncio
async def test_runpod_public_refresh_preserves_cached_catalog_on_failure(reset_runpod_state, monkeypatch):
    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="public",
        wrapper_mode=None,
        resource_id="public-catalog",
        resource_kind="public",
        status="ready",
        endpoint_url="https://api.runpod.ai/v2",
        public_catalog_json=[
            {
                "id": "cached-model",
                "name": "Cached Model",
                "protocol": "runpod_public",
                "route_base": "https://api.runpod.ai/v2/cached-model",
                "request_mode": "runsync",
                "capabilities": [],
            }
        ],
        metadata={"catalog_source": "cached"},
    )
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=config.providers["runpod-test"])

    async def fake_public_catalog_source():
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(handler, "_fetch_live_public_catalog_entries", fake_public_catalog_source)

    with pytest.raises(RuntimeError):
        await handler.refresh_public_catalog()

    states = [
        state
        for state in reset_runpod_state.list_runpod_provider_states()
        if state["provider_scope"] == "global" and state["provider_id"] == "runpod-test"
    ]
    state = next(
        state for state in states if "catalog_refresh_error" in (state.get("metadata") or {})
    )
    assert state["public_catalog_json"][0]["id"] == "cached-model"
    assert "upstream unavailable" in state["metadata"]["catalog_refresh_error"]


def test_runpod_global_state_save_updates_existing_row(reset_runpod_state):
    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="public",
        wrapper_mode=None,
        resource_id="public-catalog",
        resource_kind="public",
        status="ready",
        endpoint_url="https://api.runpod.ai/v2",
        public_catalog_json=[{"id": "cached-model"}],
        metadata={"catalog_source": "cached"},
    )

    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="public",
        wrapper_mode=None,
        resource_id="public-catalog",
        resource_kind="public",
        status="ready",
        endpoint_url="https://api.runpod.ai/v2",
        public_catalog_json=[{"id": "live-model"}],
        metadata={"catalog_source": "live", "catalog_refresh_error": "upstream unavailable"},
    )

    state = reset_runpod_state.get_runpod_provider_state("global", None, "runpod-test")
    matching_states = [
        item
        for item in reset_runpod_state.list_runpod_provider_states()
        if item["provider_scope"] == "global" and item["provider_id"] == "runpod-test"
    ]

    assert len(matching_states) == 1
    assert state["public_catalog_json"][0]["id"] == "live-model"
    assert state["metadata"]["catalog_source"] == "live"
    assert state["metadata"]["catalog_refresh_error"] == "upstream unavailable"


@pytest.mark.asyncio
async def test_runpod_pod_mode_starts_stopped_pod_and_waits_until_ready(reset_runpod_state, monkeypatch):
    provider = config.providers["runpod-test"]
    provider.runpod_config.update({"mode": "pod", "wrapper_mode": "openai", "pod_id": "pod-123"})
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=provider)

    calls = []
    responses = iter([
        {"id": "pod-123", "desiredStatus": "EXITED", "publicIp": None, "portMappings": []},
        {"id": "pod-123", "desiredStatus": "RUNNING", "publicIp": None, "portMappings": []},
        {"id": "pod-123", "desiredStatus": "RUNNING", "publicIp": "1.2.3.4", "portMappings": [{"publicPort": 8000}]},
    ])

    async def fake_management_request(method, path, params=None, json_body=None):
        calls.append((method, path))
        if method == "POST" and path == "/pods/pod-123/start":
            return {"ok": True}
        return next(responses)

    monkeypatch.setattr(handler, "_management_request", fake_management_request)

    runtime = await handler._ensure_pod_ready()

    assert ("POST", "/pods/pod-123/start") in calls
    assert runtime["endpoint_url"] == "http://1.2.3.4:8000/v1"


@pytest.mark.asyncio
async def test_runpod_idle_shutdown_stops_running_pod_after_threshold(reset_runpod_state, monkeypatch):
    provider = config.providers["runpod-test"]
    provider.runpod_config.update({"mode": "pod", "wrapper_mode": "openai", "pod_id": "pod-123", "idle_shutdown_ms": 1000})
    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="pod",
        wrapper_mode="openai",
        resource_id="pod-123",
        resource_kind="pod",
        status="running",
        endpoint_url="http://1.2.3.4:8000/v1",
        public_catalog_json=[],
        metadata={},
        last_used_at=0,
    )
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=provider)

    calls = []

    async def fake_management_request(method, path, params=None, json_body=None):
        calls.append((method, path))
        return {"ok": True}

    monkeypatch.setattr(handler, "_management_request", fake_management_request)
    monkeypatch.setattr("aisbf.providers.runpod.time.time", lambda: 5)

    stopped = await handler.poll_idle_shutdown()

    assert stopped is True
    assert calls == [("POST", "/pods/pod-123/stop")]
    states = [
        state
        for state in reset_runpod_state.list_runpod_provider_states()
        if state["provider_scope"] == "global" and state["provider_id"] == "runpod-test"
    ]
    state = next(state for state in states if state["status"] == "stopped")
    assert state["resource_id"] == "pod-123"


def test_runpod_build_runtime_status_serializes_cached_state(reset_runpod_state):
    provider = config.providers["runpod-test"]
    provider.runpod_config.update({"mode": "public"})
    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="public",
        wrapper_mode=None,
        resource_id="public-catalog",
        resource_kind="public",
        status="ready",
        endpoint_url="https://api.runpod.ai/v2",
        public_catalog_json=[
            {
                "id": "black-forest-labs-flux-1-dev",
                "name": "Flux Dev",
                "protocol": "runpod_public",
                "route_base": "https://api.runpod.ai/v2/black-forest-labs-flux-1-dev",
                "request_mode": "runsync",
                "capabilities": ["image"],
            }
        ],
        metadata={
            "catalog_source": "live",
            "catalog_refreshed_at": 123,
            "catalog_item_count": 1,
            "catalog_refresh_error": "stale failure",
        },
        last_used_at=111,
        last_status_sync_at=222,
    )
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=provider)

    status = handler.build_runtime_status()

    assert status["provider_id"] == "runpod-test"
    assert status["mode"] == "public"
    assert status["status"] == "ready"
    assert status["resource_kind"] == "public"
    assert status["endpoint_url"] == "https://api.runpod.ai/v2"
    assert status["catalog"]["item_count"] == 1
    assert status["catalog"]["refreshed_at"] == 123
    assert status["catalog"]["source"] == "live"
    assert status["catalog"]["refresh_error"] == "stale failure"
    assert status["catalog"]["models"][0]["id"] == "black-forest-labs-flux-1-dev"
    assert status["last_used_at"] == 111
    assert status["last_status_sync_at"] == 222


def test_runpod_build_delegate_handler_uses_runtime_endpoint_for_openai(reset_runpod_state):
    provider = config.providers["runpod-test"]
    provider.runpod_config.update({"mode": "pod", "wrapper_mode": "openai", "pod_id": "pod-123"})
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=provider)

    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="pod",
        wrapper_mode="openai",
        resource_id="pod-123",
        resource_kind="pod",
        status="running",
        endpoint_url="http://1.2.3.4:8000/v1",
        public_catalog_json=[],
        metadata={},
    )

    delegate = handler._build_delegate_handler("openai")

    assert str(delegate.client.base_url).rstrip("/") == "http://1.2.3.4:8000/v1"


def test_runpod_build_delegate_handler_uses_runtime_endpoint_for_ollama(reset_runpod_state):
    provider = config.providers["runpod-test"]
    provider.runpod_config.update({"mode": "pod", "wrapper_mode": "ollama", "pod_id": "pod-123"})
    handler = RunpodProviderHandler("runpod-test", api_key="test-key", provider_config=provider)

    reset_runpod_state.save_runpod_provider_state(
        provider_scope="global",
        owner_user_id=None,
        provider_id="runpod-test",
        mode="pod",
        wrapper_mode="ollama",
        resource_id="pod-123",
        resource_kind="pod",
        status="running",
        endpoint_url="http://1.2.3.4:11434",
        public_catalog_json=[],
        metadata={},
    )

    delegate = handler._build_delegate_handler("ollama")

    assert str(delegate.client.base_url).rstrip("/") == "http://1.2.3.4:11434"


def test_dashboard_save_preserves_runpod_config(reset_runpod_state, monkeypatch):
    client = TestClient(app)

    client.cookies.set("session", "stub")

    def fake_require_dashboard_auth(request):
        request.session.update({"logged_in": True, "user_id": 1, "username": "alice", "role": "user"})
        return None

    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "require_dashboard_auth", fake_require_dashboard_auth)
    monkeypatch.setattr(
        dashboard_providers,
        "_templates",
        type("TemplatesStub", (), {"TemplateResponse": staticmethod(lambda *args, **kwargs: HTMLResponse("ok"))})(),
    )

    saved = {}

    def fake_save_user_provider(user_id, provider_key, provider_config):
        saved[provider_key] = provider_config

    monkeypatch.setattr(reset_runpod_state, "get_user_providers", lambda user_id: [])
    monkeypatch.setattr(reset_runpod_state, "save_user_provider", fake_save_user_provider)

    response = client.post(
        "/dashboard/providers",
        data={
            "config": json.dumps({
                "runpod-test": {
                    "type": "runpod",
                    "name": "RunPod",
                    "endpoint": "https://rest.runpod.io/v1",
                    "api_key_required": True,
                    "api_key": "test-key",
                    "runpod_config": {
                        "mode": "pod",
                        "wrapper_mode": "ollama",
                        "pod_id": "pod-123",
                    },
                }
            })
        },
    )

    assert response.status_code == 200
    assert saved["runpod-test"]["runpod_config"]["wrapper_mode"] == "ollama"


def test_dashboard_runpod_status_returns_runtime_state(reset_runpod_state, monkeypatch):
    client = TestClient(app)
    client.cookies.set("session", "stub")

    def fake_require_dashboard_auth(request):
        request.session.update({"logged_in": True, "user_id": 1, "username": "alice", "role": "user"})
        return None

    from aisbf.routes.dashboard import providers as dashboard_providers

    monkeypatch.setattr(dashboard_providers, "require_dashboard_auth", fake_require_dashboard_auth)

    saved_provider = {
        "provider_id": "runpod-test",
        "config": {
            "type": "runpod",
            "name": "RunPod",
            "endpoint": "https://rest.runpod.io/v1",
            "api_key": "test-key",
            "runpod_config": {"mode": "public"},
        },
    }
    monkeypatch.setattr(reset_runpod_state, "get_user_provider", lambda user_id, provider_id: saved_provider if provider_id == "runpod-test" else None)

    class StubRunpodStatusHandler:
        def __init__(self, provider_id, api_key=None, user_id=None, provider_config=None):
            self.provider_id = provider_id

        def build_runtime_status(self):
            return {
                "provider_id": self.provider_id,
                "mode": "public",
                "status": "ready",
                "catalog": {"item_count": 1},
            }

    monkeypatch.setattr(dashboard_providers, "RunpodProviderHandler", StubRunpodStatusHandler, raising=False)

    response = client.get("/dashboard/providers/runpod-test/runpod-status")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["status"]["provider_id"] == "runpod-test"
    assert response.json()["status"]["catalog"]["item_count"] == 1


def test_dashboard_runpod_refresh_returns_refreshed_status(reset_runpod_state, monkeypatch):
    client = TestClient(app)
    client.cookies.set("session", "stub")

    def fake_require_dashboard_auth(request):
        request.session.update({"logged_in": True, "user_id": 1, "username": "alice", "role": "user"})
        return None

    from aisbf.routes.dashboard import providers as dashboard_providers

    monkeypatch.setattr(dashboard_providers, "require_dashboard_auth", fake_require_dashboard_auth)

    saved_provider = {
        "provider_id": "runpod-test",
        "config": {
            "type": "runpod",
            "name": "RunPod",
            "endpoint": "https://rest.runpod.io/v1",
            "api_key": "test-key",
            "runpod_config": {"mode": "public"},
        },
    }
    monkeypatch.setattr(reset_runpod_state, "get_user_provider", lambda user_id, provider_id: saved_provider if provider_id == "runpod-test" else None)

    class StubRunpodRefreshHandler:
        def __init__(self, provider_id, api_key=None, user_id=None, provider_config=None):
            self.provider_id = provider_id

        async def refresh_public_catalog(self):
            return [{"id": "black-forest-labs-flux-1-dev"}]

        def build_runtime_status(self):
            return {
                "provider_id": self.provider_id,
                "mode": "public",
                "status": "ready",
                "catalog": {"item_count": 1, "models": [{"id": "black-forest-labs-flux-1-dev"}]},
            }

    monkeypatch.setattr(dashboard_providers, "RunpodProviderHandler", StubRunpodRefreshHandler, raising=False)

    response = client.post("/dashboard/providers/runpod-test/runpod-refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["catalog_count"] == 1
    assert body["status"]["provider_id"] == "runpod-test"
    assert body["status"]["catalog"]["models"][0]["id"] == "black-forest-labs-flux-1-dev"


def test_dashboard_providers_page_includes_runpod_runtime_ui(reset_runpod_state, monkeypatch):
    client = TestClient(app)
    client.cookies.set("session", "stub")

    from aisbf.routes.dashboard import providers as dashboard_providers

    def fake_require_dashboard_auth(request):
        request.session.update({"logged_in": True, "user_id": None, "username": "admin", "role": "admin"})
        return None

    class TemplatesStub:
        @staticmethod
        def TemplateResponse(*args, **kwargs):
            context = kwargs.get("context") or {}
            html = "\n".join([
                str(context.get("providers_json", "")),
                "RunPod Runtime Status",
                "refreshRunpodCatalog",
                "loadRunpodRuntimeStatus",
            ])
            return HTMLResponse(html)

        env = type("EnvStub", (), {"cache": {}})()

    monkeypatch.setattr(dashboard_providers, "require_dashboard_auth", fake_require_dashboard_auth)
    monkeypatch.setattr(dashboard_providers, "_templates", TemplatesStub())

    response = client.get("/dashboard/providers")

    assert response.status_code == 200
    assert "RunPod Runtime Status" in response.text
    assert "refreshRunpodCatalog" in response.text
    assert "loadRunpodRuntimeStatus" in response.text
