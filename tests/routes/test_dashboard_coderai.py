import asyncio
import json
import sys
from base64 import b64encode
from pathlib import Path

from itsdangerous import TimestampSigner
from fastapi.testclient import TestClient

from aisbf.coderai_broker import broker
from aisbf.config import ProviderConfig, config
from aisbf.routes import auth as auth_routes
from aisbf.routes.dashboard import providers as dashboard_providers

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from main import app


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

    def save_user_provider(self, user_id, provider_id, provider_config):
        self.saved[(user_id, provider_id)] = provider_config

    def get_user_provider(self, user_id, provider_id):
        config = self.saved.get((user_id, provider_id))
        return {"config": config} if config else None

    def get_user_by_id(self, user_id):
        return {"id": user_id, "username": f"user{user_id}"}


class RegistryStub:
    def __init__(self, db):
        self._db = db

    def get_config_database(self):
        return self._db


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
        response = client.get("/dashboard/providers")
        assert response.status_code == 200
        assert "Broker Session Status" in response.text
        assert "workstation-01" in response.text
        assert "RTX 4090" in response.text
        assert "54.6 tok/s" in response.text
    finally:
        asyncio.run(_clear_broker_sessions())
        if original_provider is None:
            config.providers.pop("coderai", None)
        else:
            config.providers["coderai"] = original_provider


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
