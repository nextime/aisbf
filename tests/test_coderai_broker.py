import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aisbf.coderai_broker import broker
from aisbf.config import ProviderConfig, config

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
    config.providers["coderai-user"] = ProviderConfig(
        id="coderai-user",
        name="CoderAI User",
        endpoint="http://127.0.0.1:11437",
        type="coderai",
        api_key_required=False,
        rate_limit=0,
        coderai_config={"registration_token": "user-token"},
    )
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/api/u/alice/coderai/wss?provider_id=coderai-user&client_id=user-client&registration_token=user-token&username=alice") as websocket:
                registered = websocket.receive_json()
                assert registered["username"] == "alice"
                assert registered["scope_name"] == "alice"
    finally:
        if original_provider is None:
            config.providers.pop("coderai-user", None)
        else:
            config.providers["coderai-user"] = original_provider
