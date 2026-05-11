import json
import base64
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from aisbf.providers.coderai import CoderAIProviderHandler
from aisbf.config import config
from aisbf.config import ProviderConfig
from aisbf.app.model_cache import _is_broker_only_coderai


@pytest.fixture(autouse=True)
def mock_coderai_error_tracking():
    original = dict(config.error_tracking)
    config.error_tracking["coderai_local"] = {
        "enabled": True,
        "max_errors": 5,
        "cooldown_seconds": 60,
        "failures": 0,
        "last_failure": 0,
        "disabled_until": None,
    }
    config.error_tracking["coderai_nat"] = {
        "enabled": True,
        "max_errors": 5,
        "cooldown_seconds": 60,
        "failures": 0,
        "last_failure": 0,
        "disabled_until": None,
    }
    config.providers["coderai_local"] = ProviderConfig(
        id="coderai_local",
        name="CoderAI",
        endpoint="http://127.0.0.1:11437",
        type="coderai",
        api_key_required=False,
        rate_limit=0,
    )
    config.providers["coderai_nat"] = ProviderConfig(
        id="coderai_nat",
        name="CoderAI NAT",
        endpoint="wss://broker.example.test/coderai/ws",
        type="coderai",
        api_key_required=False,
        rate_limit=0,
    )
    yield
    config.error_tracking.clear()
    config.error_tracking.update(original)
    config.providers.pop("coderai_local", None)
    config.providers.pop("coderai_nat", None)


@pytest.mark.asyncio
async def test_coderai_http_models_parses_openai_shape(monkeypatch):
    provider_config = {
        "id": "coderai_local",
        "name": "CoderAI",
        "endpoint": "http://127.0.0.1:11437",
        "type": "coderai",
        "api_key_required": False,
        "coderai_config": {"transport": "http"},
    }
    handler = CoderAIProviderHandler("coderai_local", provider_config=provider_config)

    class ModelsStub:
        def list(self):
            return [
                {
                    "id": "llama3.1:8b",
                    "context_length": 131072,
                    "description": "Local model",
                    "supported_parameters": ["temperature"],
                }
            ]

    handler.client = Mock(models=ModelsStub())

    models = await handler.get_models()

    assert len(models) == 1
    assert models[0].id == "llama3.1:8b"
    assert models[0].context_length == 131072
    assert models[0].supported_parameters == ["temperature"]


@pytest.mark.asyncio
async def test_coderai_websocket_models_parses_bridge_payload(monkeypatch):
    provider_config = {
        "id": "coderai_nat",
        "name": "CoderAI NAT",
        "endpoint": "wss://broker.example.test/coderai/ws",
        "type": "coderai",
        "api_key_required": False,
        "coderai_config": {"transport": "websocket", "bridge_path": "/coderai/ws"},
    }
    handler = CoderAIProviderHandler("coderai_nat", provider_config=provider_config)

    async def fake_roundtrip(op, payload, timeout=None):
        assert op == "models.list"
        return {
            "status": "ok",
            "payload": {
                "data": [
                    {
                        "id": "qwen2.5-coder:32b",
                        "context_window": 65536,
                        "architecture": {"input_modalities": ["text"]},
                    }
                ]
            },
        }

    monkeypatch.setattr(handler, "_ws_roundtrip", fake_roundtrip)

    models = await handler.get_models()

    assert len(models) == 1
    assert models[0].id == "qwen2.5-coder:32b"
    assert models[0].context_length == 65536


@pytest.mark.asyncio
async def test_coderai_websocket_stream_emits_sse_bytes(monkeypatch):
    provider_config = {
        "id": "coderai_nat",
        "name": "CoderAI NAT",
        "endpoint": "wss://broker.example.test/coderai/ws",
        "type": "coderai",
        "api_key_required": False,
        "coderai_config": {"transport": "websocket", "bridge_path": "/coderai/ws"},
    }
    handler = CoderAIProviderHandler("coderai_nat", provider_config=provider_config)

    async def fake_stream(op, payload, timeout=None):
        assert op == "chat.completions"
        yield b"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\n"
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(handler, "_ws_stream", fake_stream)

    stream = await handler.handle_request(
        model="llama3.1",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )

    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert chunks[0].startswith(b"data: ")
    assert chunks[-1] == b"data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_coderai_broker_stream_supports_progress_and_binary_chunks(monkeypatch):
    provider_config = {
        "id": "coderai_nat",
        "name": "CoderAI NAT",
        "endpoint": "wss://broker.example.test/coderai/ws",
        "type": "coderai",
        "api_key_required": False,
        "coderai_config": {"transport": "websocket", "bridge_path": "/coderai/ws"},
    }
    handler = CoderAIProviderHandler("coderai_nat", provider_config=provider_config)

    async def fake_broker_request(op, payload, timeout=None):
        assert op == "proxy"
        return {
            "status": "ok",
            "event": "progress",
            "request_id": "req-1",
            "payload": {"chunk": {"data_base64": base64.b64encode(b"event: progress\\ndata: {\"pct\":25}\\n\\n").decode("ascii")}},
        }

    async def fake_wait_for_stream_event(request_id, timeout=300.0):
        assert request_id == "req-1"
        return {"status": "ok", "event": "done", "request_id": "req-1", "payload": {}}

    async def fake_use_broker():
        return True

    monkeypatch.setattr(handler, "_broker_request", fake_broker_request)
    monkeypatch.setattr(handler, "_use_broker", fake_use_broker)
    monkeypatch.setattr("aisbf.providers.coderai.coderai_broker.wait_for_stream_event", fake_wait_for_stream_event)

    status_code, payload = await handler.proxy_native_request("v1/video/progress", method="GET", stream=True)

    assert status_code == 200
    assert payload["stream_encoding"] == "base64"
    assert base64.b64decode(payload["stream_chunks"][0]).startswith(b"event: progress")


def test_coderai_broker_mode_forces_broker_transport_and_skips_outbound_validation():
    provider_config = {
        "id": "coderai_nat",
        "name": "CoderAI NAT",
        "endpoint": "http://127.0.0.1:11437",
        "type": "coderai",
        "api_key_required": False,
        "coderai_config": {"broker_mode": True, "registration_token": "nat-token"},
    }

    handler = CoderAIProviderHandler("coderai_nat", provider_config=provider_config)

    assert handler._transport == "broker"
    assert handler.validate_credentials() is True


@pytest.mark.asyncio
async def test_coderai_non_broker_mode_uses_openai_compatible_http_api():
    provider_config = {
        "id": "coderai_local",
        "name": "CoderAI",
        "endpoint": "http://127.0.0.1:11437",
        "type": "coderai",
        "api_key_required": False,
        "api_key": "local-api-token",
        "coderai_config": {"broker_mode": False, "broker_enabled": False, "transport": "http"},
    }

    handler = CoderAIProviderHandler("coderai_local", provider_config=provider_config)

    assert handler._transport == "http"
    assert handler._effective_api_key() == "local-api-token"
    assert handler.validate_credentials() is True


def test_model_cache_detects_broker_only_coderai_provider():
    provider_config = SimpleNamespace(
        type="coderai",
        coderai_config={"broker_mode": True},
    )

    assert _is_broker_only_coderai(provider_config) is True


def test_model_cache_allows_direct_http_coderai_provider():
    provider_config = SimpleNamespace(
        type="coderai",
        coderai_config={"broker_mode": False, "broker_enabled": False, "transport": "http"},
    )

    assert _is_broker_only_coderai(provider_config) is False
