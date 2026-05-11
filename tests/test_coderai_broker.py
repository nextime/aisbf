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
        with client.websocket_connect("/api/coderai/broker/ws?provider_id=coderai&client_id=nat-client&registration_token=global-token") as websocket:
            registered = websocket.receive_json()
            assert registered["event"] == "registered"

            websocket.send_json({
                "op": "register",
                "request_id": "reg-1",
                "payload": {
                    "endpoint": "ws://local-tunnel",
                    "transport": "websocket",
                    "registration_token": "global-token",
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


def test_broker_rejects_missing_registration_token():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/coderai/broker/ws?provider_id=coderai&client_id=bad-client"):
                pass


def test_broker_routes_request_to_registered_session():
    async def scenario():
        class StubWebSocket:
            def __init__(self):
                self.sent = []

            async def send_text(self, payload: str):
                self.sent.append(payload)
                message = json.loads(payload)
                await broker.resolve_response({
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
        finally:
            await broker.unregister(session.session_id)

    asyncio.run(scenario())
