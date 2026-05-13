import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aisbf.coderai_broker import broker
from aisbf.config import ProviderConfig, config
from aisbf.database import DatabaseRegistry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app


@pytest.fixture(autouse=True)
def reset_broker_state():
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
    yield
    asyncio.run(_clear_broker_sessions())
    if original_provider is None:
        config.providers.pop("coderai", None)
    else:
        config.providers["coderai"] = original_provider


async def _clear_broker_sessions():
    sessions = await broker.list_sessions()
    for session in sessions:
        await broker.unregister(session["session_id"])


def test_broker_registers_websocket_session_and_reports_status():
    with TestClient(app) as client:
        with client.websocket_connect("/api/coderai/wss?provider_id=coderai&client_id=nat-client&registration_token=global-token&username=global") as websocket:
            registered = websocket.receive_json()
            assert registered["event"] == "registered"
            assert registered["scope_name"] == "global"

            websocket.send_json({
                "op": "register",
                "request_id": "reg-1",
                "payload": {
                    "endpoint": "ws://local-tunnel",
                    "transport": "websocket",
                    "registration_token": "global-token",
                    "hardware": {
                        "gpus": [
                            {
                                "name": "RTX 4090",
                                "total_vram_mb": 24576,
                                "available_vram_mb": 20480
                            }
                        ]
                    },
                    "capabilities": {"studio": {"enabled": True}},
                },
            })
            ack = websocket.receive_json()
            assert ack["status"] == "ok"

            response = client.get("/api/coderai/broker/providers/coderai/status", params={"client_id": "nat-client"})
            assert response.status_code == 200
            payload = response.json()
            assert payload["connected"] is True
            assert payload["client_id"] == "nat-client"
            assert payload["metadata"]["gpu_count"] == 1
            assert payload["metadata"]["total_vram_mb"] == 24576
            assert payload["metadata"]["available_vram_mb"] == 20480


def test_broker_rejects_missing_registration_token():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/coderai/wss?provider_id=coderai&client_id=bad-client&username=global"):
                pass


def test_broker_routes_request_to_registered_session():
    async def scenario():
        class StubWebSocket:
            def __init__(self):
                self.sent = []

            async def send_text(self, payload: str):
                self.sent.append(payload)
                message = json.loads(payload)
                await broker.publish_response({
                    "request_id": message["request_id"],
                    "status": "ok",
                    "payload": {"data": [{"id": "llama3.1:8b"}]},
                })

        websocket = StubWebSocket()
        session = await broker.register(websocket, "coderai", "bridge-client", metadata={"owner_user_id": None})
        try:
            response = await broker.send_request("coderai", "models.list", {}, client_id="bridge-client", owner_user_id=None, timeout=3.0)
            sent_message = json.loads(websocket.sent[0])
            assert sent_message["op"] == "models.list"
            assert response["status"] == "ok"
            assert response["payload"]["data"][0]["id"] == "llama3.1:8b"
            snapshot = await broker.get_session_snapshot("coderai", "bridge-client")
            assert snapshot["performance"]["sample_count"] == 1
            assert snapshot["performance"]["avg_latency_ms"] >= 0
            queued = await broker.consume_request(session.session_id, timeout=0)
            assert queued is None
        finally:
            await broker.unregister(session.session_id)

    asyncio.run(scenario())


def test_broker_uses_queue_for_remote_node_session():
    async def scenario():
        class StubWebSocket:
            async def send_text(self, payload: str):
                raise AssertionError("Remote-node session should not use direct websocket fast path")

        websocket = StubWebSocket()
        session = await broker.register(websocket, "coderai", "remote-client", metadata={"owner_user_id": None})
        await broker.touch(session.session_id, metadata={"broker_node_id": "remote-node"})
        try:
            async def responder():
                message = await broker.consume_request(session.session_id, timeout=1)
                assert message is not None
                await asyncio.sleep(0)
                await broker.publish_response({
                    "request_id": message["request_id"],
                    "status": "ok",
                    "payload": {"data": [{"id": "queue-model"}]},
                })

            response, _ = await asyncio.gather(
                broker.send_request("coderai", "models.list", {}, client_id="remote-client", owner_user_id=None, timeout=3.0),
                responder(),
            )
            assert response["payload"]["data"][0]["id"] == "queue-model"
        finally:
            await broker.unregister(session.session_id)

    asyncio.run(scenario())


def test_broker_stream_events_are_delivered_to_waiter():
    async def scenario():
        class StubWebSocket:
            def __init__(self):
                self.sent = []

            async def send_text(self, payload: str):
                self.sent.append(payload)
                message = json.loads(payload)
                await broker.publish_response({
                    "request_id": message["request_id"],
                    "status": "ok",
                    "event": "progress",
                    "payload": {"chunk": "event: progress\ndata: {\"pct\": 50}\n\n"},
                })
                await broker.publish_response({
                    "request_id": message["request_id"],
                    "status": "ok",
                    "event": "done",
                    "payload": {},
                })

        websocket = StubWebSocket()
        session = await broker.register(websocket, "coderai", "stream-client", metadata={"owner_user_id": None})
        try:
            response = await broker.send_request("coderai", "proxy", {"stream": True}, client_id="stream-client", owner_user_id=None, timeout=3.0)
            assert response["event"] == "done"
            snapshot = await broker.get_session_snapshot("coderai", "stream-client")
            assert snapshot["performance"]["sample_count"] == 1
        finally:
            await broker.unregister(session.session_id)

    asyncio.run(scenario())


def test_user_scoped_broker_websocket_path_registers_username():
    original_provider = config.providers.get("coderai-user")
    original_get_db = DatabaseRegistry.get_config_database
    config.providers["coderai-user"] = ProviderConfig(
        id="coderai-user",
        name="CoderAI User",
        endpoint="http://127.0.0.1:11437",
        type="coderai",
        api_key_required=False,
        rate_limit=0,
        coderai_config={"registration_token": "user-token"},
    )

    class DbStub:
        def get_user_by_username(self, username):
            if username == "alice":
                return {"id": 17, "username": "alice"}
            return None

        def get_all_user_providers(self):
            return [{
                "user_id": 17,
                "provider_id": "coderai-user",
                "config": {
                    "id": "coderai-user",
                    "type": "coderai",
                    "coderai_config": {"registration_token": "user-token"},
                },
            }]

    DatabaseRegistry.get_config_database = staticmethod(lambda: DbStub())
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/api/u/alice/coderai/wss?provider_id=coderai-user&client_id=user-client&registration_token=user-token&username=alice") as websocket:
                registered = websocket.receive_json()
                assert registered["username"] == "alice"
                assert registered["scope_name"] == "alice"
    finally:
        DatabaseRegistry.get_config_database = original_get_db
        if original_provider is None:
            config.providers.pop("coderai-user", None)
        else:
            config.providers["coderai-user"] = original_provider


def test_coderai_register_endpoint_bypasses_bearer_auth_when_using_registration_token(monkeypatch):
    original_get_db = DatabaseRegistry.get_config_database
    DatabaseRegistry.get_config_database = staticmethod(lambda: None)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/coderai/register",
                json={
                    "provider_id": "coderai",
                    "client_id": "nat-client",
                    "registration_token": "global-token",
                    "username": "global",
                },
            )
        assert response.status_code == 200
        assert response.json()["accepted"] is True
        assert response.json()["scope_name"] == "global"
    finally:
        DatabaseRegistry.get_config_database = original_get_db


def test_global_registration_rejects_user_scoped_provider_token(monkeypatch):
    class DbStub:
        def get_all_user_providers(self):
            return [{
                "user_id": 17,
                "provider_id": "coderai-user-only",
                "config": {
                    "id": "coderai-user-only",
                    "type": "coderai",
                    "coderai_config": {"registration_token": "user-token"},
                },
            }]

        def get_user_by_username(self, username):
            if username == "alice":
                return {"id": 17, "username": "alice"}
            return None

    original_get_db = DatabaseRegistry.get_config_database
    DatabaseRegistry.get_config_database = staticmethod(lambda: DbStub())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/coderai/register",
                json={
                    "provider_id": "coderai-user-only",
                    "client_id": "nat-client",
                    "registration_token": "user-token",
                    "username": "global",
                },
            )
        assert response.status_code == 403
    finally:
        DatabaseRegistry.get_config_database = original_get_db


def test_user_registration_rejects_global_provider_token(monkeypatch):
    original_provider = config.providers.get("coderai-global-only")
    config.providers["coderai-global-only"] = ProviderConfig(
        id="coderai-global-only",
        name="CoderAI Global Only",
        endpoint="http://127.0.0.1:11437",
        type="coderai",
        api_key_required=False,
        rate_limit=0,
        coderai_config={"registration_token": "global-only-token"},
    )

    class DbStub:
        def get_all_user_providers(self):
            return []

        def get_user_by_username(self, username):
            if username == "alice":
                return {"id": 17, "username": "alice"}
            return None

    original_get_db = DatabaseRegistry.get_config_database
    DatabaseRegistry.get_config_database = staticmethod(lambda: DbStub())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/u/alice/coderai/register",
                json={
                    "provider_id": "coderai-global-only",
                    "client_id": "user-client",
                    "registration_token": "global-only-token",
                    "username": "alice",
                },
            )
        assert response.status_code == 403
    finally:
        DatabaseRegistry.get_config_database = original_get_db
        if original_provider is None:
            config.providers.pop("coderai-global-only", None)
        else:
            config.providers["coderai-global-only"] = original_provider
