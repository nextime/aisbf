import asyncio
import json
import sys
from base64 import b64encode
from pathlib import Path

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from itsdangerous import TimestampSigner
from fastapi.testclient import TestClient

from aisbf.coderai_broker import broker
from aisbf.config import ProviderConfig, config
from aisbf.routes import auth as auth_routes
from aisbf.routes.dashboard import providers as dashboard_providers

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from main import app


class TemplateCapture:
    def __init__(self):
        self.calls = []
        self._env = Environment(
            loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "templates")),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._env.globals["url_for"] = lambda request, path, **kwargs: f"{request.scope.get('root_path', '')}{path}"

    def TemplateResponse(self, *args, **kwargs):
        request = kwargs["request"]
        name = kwargs["name"]
        context = kwargs["context"]
        self.calls.append({"request": request, "name": name, "context": context})
        template = self._env.get_template(name)
        return HTMLResponse(template.render(**context))


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


def _login_as_user(client: TestClient, user_id: int = 17, username: str = "alice") -> None:
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": username,
            "role": "user",
            "user_id": user_id,
            "expires_at": 4102444800,
        },
    )


async def _clear_broker_sessions():
    sessions = await broker.list_sessions()
    for session in sessions:
        await broker.unregister(session["session_id"])


class DbStub:
    def __init__(self):
        self.saved = {}
        self.events = []

    def save_user_provider(self, user_id, provider_id, provider_config):
        self.saved[(user_id, provider_id)] = provider_config

    def get_user_provider(self, user_id, provider_id):
        config = self.saved.get((user_id, provider_id))
        return {"config": config} if config else None

    def get_user_by_id(self, user_id):
        return {"id": user_id, "username": f"user{user_id}"}

    def record_dashboard_event(self, **kwargs):
        self.events.append(kwargs)
        return len(self.events)


class RegistryStub:
    def __init__(self, db):
        self._db = db

    def get_config_database(self):
        return self._db


class ProvidersMutationDbStub(DbStub):
    def __init__(self):
        super().__init__()
        self.user_rotations = {}
        self.user_autoselects = {}

    def save_user_rotation(self, user_id, rotation_id, rotation_config):
        self.user_rotations[(user_id, rotation_id)] = rotation_config

    def delete_user_rotation(self, user_id, rotation_id):
        self.user_rotations.pop((user_id, rotation_id), None)

    def get_user_rotations(self, user_id):
        return [
            {"rotation_id": rotation_id, "config": config}
            for (uid, rotation_id), config in self.user_rotations.items()
            if uid == user_id
        ]

    def save_user_autoselect(self, user_id, autoselect_id, autoselect_config):
        self.user_autoselects[(user_id, autoselect_id)] = autoselect_config

    def delete_user_autoselect(self, user_id, autoselect_id):
        self.user_autoselects.pop((user_id, autoselect_id), None)

    def get_user_autoselects(self, user_id):
        return [
            {"autoselect_id": autoselect_id, "config": config}
            for (uid, autoselect_id), config in self.user_autoselects.items()
            if uid == user_id
        ]

    def get_sort_order(self, user_id, resource_type):
        return None


def test_api_provider_save_rejects_coderai_broker_without_registration_token(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)
    monkeypatch.setattr(dashboard_providers, "_reload_global_config", lambda: None)
    monkeypatch.setattr(dashboard_providers, "_providers_json_path", lambda: Path("/tmp/providers-source.json"))
    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: DummyOpen({}), raising=False)

    provider_config = dashboard_providers._ensure_coderai_token(
        {
            "id": "coderai",
            "name": "CoderAI",
            "endpoint": "http://127.0.0.1:11437",
            "api_key_required": False,
            "type": "coderai",
            "coderai_config": {
                "broker_enabled": True,
                "registration_token": "",
            },
        }
    )

    try:
        dashboard_providers._validate_coderai_provider_config("coderai", provider_config)
        raise AssertionError("Expected validation failure")
    except ValueError as exc:
        assert "requires a registration token" in str(exc)


def test_api_provider_save_allows_non_broker_coderai_without_registration_token():
    provider_config = dashboard_providers._ensure_coderai_token(
        {
            "id": "coderai-http",
            "name": "CoderAI HTTP",
            "endpoint": "http://127.0.0.1:11437",
            "api_key_required": False,
            "api_key": "local-token",
            "type": "coderai",
            "coderai_config": {
                "broker_enabled": False,
                "broker_mode": False,
                "registration_token": "",
            },
        }
    )

    dashboard_providers._validate_coderai_provider_config("coderai-http", provider_config)
    assert provider_config["coderai_config"]["registration_token"] == ""


def test_api_provider_save_persists_coderai_token_for_user(monkeypatch):
    db = DbStub()

    provider_config = dashboard_providers._ensure_coderai_token(
        {
            "id": "my-coderai",
            "name": "My CoderAI",
            "endpoint": "http://127.0.0.1:11437",
            "api_key_required": False,
            "type": "coderai",
            "coderai_config": {
                "broker_enabled": True,
                "registration_token": "user-token",
                "client_id": "workstation-01",
            },
        }
    )
    dashboard_providers._validate_coderai_provider_config("my-coderai", provider_config)
    db.save_user_provider(17, "my-coderai", provider_config)

    saved = db.saved[(17, "my-coderai")]
    assert saved["coderai_config"]["registration_token"] == "user-token"
    assert saved["coderai_config"]["client_id"] == "workstation-01"


def test_dashboard_providers_bulk_save_generates_and_persists_coderai_token(monkeypatch):
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
                    "coderai": {
                        "type": "coderai",
                        "coderai_config": {
                            "broker_enabled": True,
                            "registration_token": "admin-token",
                        },
                    }
                }
            )
        },
    )

    assert response.status_code == 200
    saved = json.loads(saved_payload["writes"][-1])
    assert saved["providers"]["coderai"]["coderai_config"]["registration_token"] == "admin-token"


def test_dashboard_providers_page_includes_broker_status_for_coderai(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)
    capture = TemplateCapture()
    asyncio.run(_clear_broker_sessions())
    original_provider = config.providers.get("coderai")
    config.providers["coderai"] = ProviderConfig(
        id="coderai",
        name="CoderAI",
        endpoint="http://127.0.0.1:11437",
        type="coderai",
        api_key_required=False,
        rate_limit=0,
        coderai_config={"registration_token": "global-token"},
    )
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    async def scenario():
        class StubWebSocket:
            async def send_text(self, payload: str):
                return None

        await broker.register(
            StubWebSocket(),
            "coderai",
            "workstation-01",
            metadata={
                "owner_user_id": None,
                "endpoint": "ws://nat-client",
                "transport": "websocket",
                "studio_endpoints": ["v1/images/generate"],
                "gpus": [{"name": "RTX 4090", "total_vram_mb": 24576, "available_vram_mb": 20480}],
                "gpu_count": 1,
                "total_vram_mb": 24576,
                "available_vram_mb": 20480,
            },
            capabilities={"studio": {"enabled": True}},
        )
        session = await broker.get_session("coderai", "workstation-01")
        session.recent_requests.append({
            "latency_ms": 842.0,
            "tokens_per_second": 54.6,
            "total_tokens": 460,
            "success": True,
            "recorded_at": 0,
        })

    asyncio.run(_clear_broker_sessions())
    asyncio.run(scenario())
    try:
        class RequestStub:
            session = {"logged_in": True, "user_id": None}

        broker_response = asyncio.run(dashboard_providers.api_coderai_broker_sessions(RequestStub()))
        sessions = json.loads(broker_response.body)["sessions"]
        coderai_session = next(session for session in sessions if session.get("client_id") == "workstation-01")
        metadata = coderai_session["metadata"]
        response = client.get("/dashboard/providers")
        assert response.status_code == 200
        assert "Broker Session Status" in response.text
        assert "workstation-01" in response.text
        assert metadata["gpu_count"] == 1
        assert metadata["gpus"][0]["name"] == "RTX 4090"
        status_map = asyncio.run(dashboard_providers._load_coderai_broker_status_map())
        assert "coderai" in status_map
        assert any(session.get("client_id") == "workstation-01" for session in sessions)
        augmented = dashboard_providers._augment_provider_broker_status(
            "coderai",
            config.providers["coderai"].model_dump(),
            {"coderai": coderai_session},
        )
        broker_session = augmented["coderai_config"]["broker_session"]
        assert broker_session["connected"] is True
        assert broker_session["client_id"] == "workstation-01"
        assert broker_session["metadata"]["gpu_count"] == 1
    finally:
        asyncio.run(_clear_broker_sessions())
        if original_provider is None:
            config.providers.pop("coderai", None)
        else:
            config.providers["coderai"] = original_provider


def test_augment_provider_broker_status_marks_disconnected_persisted_session_offline():
    provider_config = {
        "id": "coderai",
        "type": "coderai",
        "coderai_config": {"registration_token": "global-token"},
    }
    disconnected_session = {
        "session_id": "coderai_stale",
        "provider_id": "coderai",
        "client_id": "workstation-01",
        "connected": False,
        "connected_at": 1747079542,
        "last_seen": 1747079544,
        "metadata": {
            "owner_user_id": None,
            "transport": "websocket",
            "endpoint": "ws://nat-client",
            "connection_state": "disconnected",
        },
        "performance": {},
    }

    augmented = dashboard_providers._augment_provider_broker_status(
        "coderai",
        provider_config,
        {"coderai": disconnected_session},
    )

    broker_session = augmented["coderai_config"]["broker_session"]
    assert broker_session["connected"] is False
    assert broker_session["connection_state"] == "disconnected"


def test_dashboard_api_coderai_broker_sessions_filters_by_owner(monkeypatch):
    async def scenario():
        class StubWebSocket:
            async def send_text(self, payload: str):
                return None

        await broker.register(StubWebSocket(), "global-coderai", "global-client", metadata={"owner_user_id": None})
        await broker.register(StubWebSocket(), "user-coderai", "user-client", metadata={"owner_user_id": 42})

    asyncio.run(_clear_broker_sessions())
    asyncio.run(scenario())
    try:
        class RequestStub:
            session = {"logged_in": True, "user_id": 42}

        response = asyncio.run(dashboard_providers.api_coderai_broker_sessions(RequestStub()))
        sessions = json.loads(response.body)["sessions"]
        connected_sessions = [session for session in sessions if session.get("connected")]
        assert any(session["client_id"] == "user-client" for session in connected_sessions)
        assert not any(session.get("client_id") == "global-client" for session in connected_sessions)
        assert any(session["provider_id"] == "user-coderai" for session in sessions)
    finally:
        asyncio.run(_clear_broker_sessions())


def test_provider_coderai_token_rotate_records_saved_event_for_user(monkeypatch):
    client = TestClient(app)
    _login_as_user(client)
    recorded_events = []

    db = ProvidersMutationDbStub()
    db.saved[(17, "coderai-extra")] = {
        "id": "coderai-extra",
        "type": "coderai",
        "coderai_config": {"registration_token": "old-token"},
    }

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(
        dashboard_providers,
        "_record_dashboard_event",
        lambda request, event_type, **kwargs: recorded_events.append({"event_type": event_type, **kwargs}),
    )

    response = client.post("/dashboard/api/provider/coderai-extra/coderai-token")

    assert response.status_code == 200
    assert recorded_events[-1]["event_type"] == "provider_saved"
    assert recorded_events[-1]["provider_id"] == "coderai-extra"
    assert recorded_events[-1]["metadata"]["source"] == "coderai-token"
    assert db.saved[(17, "coderai-extra")]["coderai_config"]["registration_token"] != "old-token"


def test_provider_delete_records_removed_event_for_global(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)
    recorded_events = []

    saved_payload = {"providers": {"demo": {"id": "demo", "type": "openai"}}}
    db = ProvidersMutationDbStub()

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_reload_global_config", lambda: None)
    monkeypatch.setattr(dashboard_providers, "_providers_json_path", lambda: Path("/tmp/providers-source.json"))
    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: DummyOpen(saved_payload), raising=False)
    monkeypatch.setattr(
        dashboard_providers,
        "_record_dashboard_event",
        lambda request, event_type, **kwargs: recorded_events.append({"event_type": event_type, **kwargs}),
    )

    response = client.delete("/dashboard/api/provider/demo")

    assert response.status_code == 200
    assert recorded_events[-1]["event_type"] == "provider_removed"
    assert recorded_events[-1]["provider_id"] == "demo"


def test_rotation_save_and_delete_record_correct_global_events(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)
    recorded_events = []

    saved_payload = {"rotations": {}}
    db = ProvidersMutationDbStub()

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_reload_global_config", lambda: None)
    monkeypatch.setattr(dashboard_providers, "_rotations_json_path", lambda: Path("/tmp/rotations-source.json"))
    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: DummyOpen(saved_payload), raising=False)
    monkeypatch.setattr(
        dashboard_providers,
        "_record_dashboard_event",
        lambda request, event_type, **kwargs: recorded_events.append({"event_type": event_type, **kwargs}),
    )

    save_response = client.post(
        "/dashboard/api/rotation",
        json={"rotation_id": "rot-a", "config": {"providers": []}},
    )
    delete_response = client.delete("/dashboard/api/rotation/rot-a")

    assert save_response.status_code == 200
    assert delete_response.status_code == 200
    assert recorded_events[-2]["event_type"] == "rotation_saved"
    assert recorded_events[-2]["rotation_id"] == "rot-a"
    assert recorded_events[-1]["event_type"] == "rotation_removed"
    assert recorded_events[-1]["rotation_id"] == "rot-a"


def test_autoselect_save_and_delete_record_correct_global_events(monkeypatch):
    client = TestClient(app)
    _login_as_admin(client)
    recorded_events = []

    saved_payload = {}
    db = ProvidersMutationDbStub()

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_reload_global_config", lambda: None)
    monkeypatch.setattr(dashboard_providers, "_autoselect_json_path", lambda: Path("/tmp/autoselect-source.json"))
    monkeypatch.setattr(dashboard_providers, "open", lambda *args, **kwargs: DummyOpen(saved_payload), raising=False)
    monkeypatch.setattr(
        dashboard_providers,
        "_record_dashboard_event",
        lambda request, event_type, **kwargs: recorded_events.append({"event_type": event_type, **kwargs}),
    )

    save_response = client.post(
        "/dashboard/api/autoselect",
        json={
            "autoselect_id": "auto-a",
            "config": {"selection_model": "internal", "available_models": [{"model_id": "demo/model", "priority": 1, "description": "Demo"}]},
        },
    )
    delete_response = client.delete("/dashboard/api/autoselect/auto-a")

    assert save_response.status_code == 200
    assert delete_response.status_code == 200
    assert recorded_events[-2]["event_type"] == "autoselect_saved"
    assert recorded_events[-2]["autoselect_id"] == "auto-a"
    assert recorded_events[-1]["event_type"] == "autoselect_removed"
    assert recorded_events[-1]["autoselect_id"] == "auto-a"


def test_user_rotation_save_persists_tri_state_feature_overrides(monkeypatch):
    client = TestClient(app)
    _login_as_user(client)

    db = ProvidersMutationDbStub()
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))

    response = client.post(
        "/dashboard/api/rotation",
        json={
            "rotation_id": "rot-user",
            "config": {
                "providers": [
                    {
                        "provider_id": "demo-provider",
                        "models": [
                            {
                                "name": "demo-model",
                                "enable_context_condensation": True,
                                "enable_response_cache": False,
                                "enable_prompt_security": True,
                                "enable_context_lens": False,
                            }
                        ],
                    }
                ],
                "enable_prompt_batching": True,
                "block_high_risk_prompts": False,
                "enable_nsfw_classification": True,
                "enable_privacy_classification": False,
            },
        },
    )

    assert response.status_code == 200
    saved = db.user_rotations[(17, "rot-user")]
    assert saved["enable_prompt_batching"] is True
    assert saved["block_high_risk_prompts"] is False
    assert saved["enable_nsfw_classification"] is True
    assert saved["enable_privacy_classification"] is False
    model = saved["providers"][0]["models"][0]
    assert model["enable_context_condensation"] is True
    assert model["enable_response_cache"] is False
    assert model["enable_prompt_security"] is True
    assert model["enable_context_lens"] is False


def test_user_autoselect_save_persists_tri_state_feature_overrides(monkeypatch):
    client = TestClient(app)
    _login_as_user(client)

    db = ProvidersMutationDbStub()
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))

    response = client.post(
        "/dashboard/api/autoselect",
        json={
            "autoselect_id": "auto-user",
            "config": {
                "selection_model": "internal",
                "enable_context_condensation": True,
                "enable_response_cache": False,
                "enable_prompt_security": True,
                "enable_context_lens": False,
                "block_high_risk_prompts": True,
                "available_models": [
                    {
                        "model_id": "demo/model",
                        "description": "Demo",
                        "enable_prompt_batching": True,
                        "enable_nsfw_classification": False,
                        "enable_privacy_classification": True,
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    saved = db.user_autoselects[(17, "auto-user")]
    assert saved["enable_context_condensation"] is True
    assert saved["enable_response_cache"] is False
    assert saved["enable_prompt_security"] is True
    assert saved["enable_context_lens"] is False
    assert saved["block_high_risk_prompts"] is True
    model = saved["available_models"][0]
    assert model["enable_prompt_batching"] is True
    assert model["enable_nsfw_classification"] is False
    assert model["enable_privacy_classification"] is True
