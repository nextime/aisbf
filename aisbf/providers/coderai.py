"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

CoderAI provider handler.

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

Why did the programmer quit his job? Because he didn't get arrays!
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union
import base64
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from ..coderai_broker import broker as coderai_broker
from ..config import config
from ..models import Model
from ..app.templates import get_base_url
from .base import AISBF_DEBUG, BaseProviderHandler


logger = logging.getLogger(__name__)


class CoderAIProviderHandler(BaseProviderHandler):
    """Provider for CoderAI local servers over HTTP or WebSocket bridge."""

    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None, provider_config: Optional[Any] = None):
        self.provider_config = provider_config if provider_config is not None else config.get_provider(provider_id)
        super().__init__(provider_id, api_key, user_id=user_id)
        self._raw_endpoint = self._get_provider_value("endpoint") or "http://127.0.0.1:11437"
        self._coderai_config = self._resolve_coderai_config()
        self._transport = str(self._coderai_config.get("transport") or self._infer_transport(self._raw_endpoint)).lower()
        self._client_id = self._coderai_config.get("client_id") or provider_id
        self._username = self._coderai_config.get("username") or ("global" if user_id is None else None)
        self._bridge_path = str(self._coderai_config.get("bridge_path") or "/coderai/ws").strip() or "/coderai/ws"
        self._registration_path = str(self._coderai_config.get("registration_path") or "/coderai/register").strip() or "/coderai/register"
        self._broker_ws_path = str(self._coderai_config.get("broker_ws_path") or "/api/coderai/wss").strip() or "/api/coderai/wss"
        self._request_timeout = float(self._coderai_config.get("request_timeout") or 300.0)
        self._model_timeout = float(self._coderai_config.get("model_timeout") or 30.0)
        self._websocket_enabled = bool(self._coderai_config.get("websocket_enabled", True))
        self._http_enabled = bool(self._coderai_config.get("http_enabled", True))
        self._discovery_enabled = bool(self._coderai_config.get("discovery_enabled", True))
        self._registration_token = self._coderai_config.get("registration_token")
        self._bridge_token = self._coderai_config.get("bridge_token")
        self._broker_enabled = bool(self._coderai_config.get("broker_enabled", True))
        self._broker_mode = bool(self._coderai_config.get("broker_mode", False))
        self._broker_preferred = bool(self._coderai_config.get("broker_preferred", False))
        if self._broker_mode:
            self._transport = "broker"
        self._base_endpoint = self._normalize_http_base(self._raw_endpoint)
        self._ws_endpoint = self._normalize_ws_endpoint(self._raw_endpoint)
        self._apply_provider_defaults()
        self.client = OpenAI(base_url=f"{self._base_endpoint}/v1", api_key=self._effective_api_key())

    def _get_provider_value(self, key: str, default: Any = None) -> Any:
        if isinstance(self.provider_config, dict):
            return self.provider_config.get(key, default)
        return getattr(self.provider_config, key, default)

    def _load_disabled_until_from_cache(self):
        try:
            super()._load_disabled_until_from_cache()
        except KeyError:
            self.error_tracking = self._build_default_error_tracking()

    def _build_default_error_tracking(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "max_errors": 5,
            "cooldown_seconds": 60,
            "failures": 0,
            "last_failure": 0,
            "disabled_until": None,
        }

    def _build_default_rate_limit(self) -> float:
        value = self._get_provider_value("rate_limit", 0)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _apply_provider_defaults(self) -> None:
        if self.user_id is not None:
            self.user_provider_config = self.provider_config
        self.error_tracking = self._build_default_error_tracking()
        self.rate_limit = self._build_default_rate_limit()

    @property
    def _usage_cache_key(self) -> str:
        return f"coderai:{self.provider_id}"

    def _resolve_coderai_config(self) -> Dict[str, Any]:
        if isinstance(self.provider_config, dict):
            raw = self.provider_config.get("coderai_config") or {}
        else:
            raw = getattr(self.provider_config, "coderai_config", None) or {}
        return raw if isinstance(raw, dict) else {}

    def _effective_api_key(self) -> str:
        configured = self._get_provider_value("api_key")
        key = self.api_key or configured
        if isinstance(key, str) and key.strip() and not key.strip().startswith("YOUR_"):
            return key.strip()
        return self._bridge_token or self._registration_token or "coderai-local"

    @staticmethod
    def _infer_transport(endpoint: str) -> str:
        scheme = urlparse((endpoint or "").strip()).scheme.lower()
        if scheme in {"ws", "wss"}:
            return "websocket"
        return "http"

    @staticmethod
    def _normalize_http_base(endpoint: str) -> str:
        raw = (endpoint or "http://127.0.0.1:11437").strip().rstrip("/")
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return raw
        if parsed.scheme in {"ws", "wss"}:
            target_scheme = "https" if parsed.scheme == "wss" else "http"
            return parsed._replace(scheme=target_scheme).geturl().rstrip("/")
        return raw

    def _normalize_ws_endpoint(self, endpoint: str) -> str:
        raw = (endpoint or "http://127.0.0.1:11437").strip().rstrip("/")
        parsed = urlparse(raw)
        if parsed.scheme in {"ws", "wss"}:
            ws_url = raw
        elif parsed.scheme in {"http", "https"}:
            target_scheme = "wss" if parsed.scheme == "https" else "ws"
            ws_url = parsed._replace(scheme=target_scheme).geturl().rstrip("/")
        else:
            ws_url = raw
        path = urlparse(ws_url).path.rstrip("/")
        if path.endswith(self._bridge_path.rstrip("/")):
            return ws_url
        return ws_url + self._bridge_path

    def _build_ws_headers(self) -> Dict[str, str]:
        headers = {
            "x-coderai-client-id": self._client_id,
            "x-coderai-provider-id": self.provider_id,
        }
        if self._username:
            headers["x-coderai-username"] = self._username
        token = self._bridge_token or self._registration_token or self.api_key
        if token:
            headers["authorization"] = f"Bearer {token}"
        return headers

    def _build_http_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CoderAI-Client-Id": self._client_id,
            "X-CoderAI-Provider-Id": self.provider_id,
        }
        if self._username:
            headers["X-CoderAI-Username"] = self._username
        token = self._bridge_token or self._registration_token or self.api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _is_direct_http_mode(self) -> bool:
        return self._transport == "http" and not self._broker_mode

    def _is_direct_websocket_mode(self) -> bool:
        return self._transport == "websocket" and not self._broker_mode

    async def _use_broker(self) -> bool:
        if not self._broker_enabled:
            return False
        if self._broker_mode:
            return True
        # Use get_session_snapshot() so clustered deployments are handled correctly:
        # the session may live on a different node; send_request() routes via the
        # shared-cache queue in that case — no direct HTTP fallback needed.
        snapshot = await coderai_broker.get_session_snapshot(self.provider_id, self._client_id)
        if not snapshot or not snapshot.get("connected"):
            return False
        meta = snapshot.get("metadata") or {}
        if self.user_id is None:
            return meta.get("owner_user_id") is None
        return meta.get("owner_user_id") == self.user_id

    async def _broker_request(self, op: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        extra = {}
        if self._registration_token:
            extra["registration_token"] = self._registration_token
        if self._bridge_token:
            extra["bridge_token"] = self._bridge_token
        return await coderai_broker.send_request(
            self.provider_id,
            op,
            payload,
            timeout=timeout,
            client_id=self._client_id,
            owner_user_id=self.user_id,
            extra=extra,
        )

    async def _broker_stream(self, op: str, payload: Dict[str, Any], timeout: float) -> AsyncIterator[bytes]:
        message = await self._broker_request(op, payload, timeout=timeout)
        status = message.get("status") or "ok"
        if status == "error":
            raise Exception(message.get("error") or "CoderAI broker bridge error")
        async for chunk in self._iter_broker_stream_chunks(message, timeout):
            yield chunk

    @staticmethod
    def _decode_broker_chunk(chunk: Any) -> bytes:
        if isinstance(chunk, bytes):
            return chunk
        if isinstance(chunk, str):
            return chunk.encode("utf-8")
        if isinstance(chunk, dict):
            if isinstance(chunk.get("data_base64"), str):
                return base64.b64decode(chunk["data_base64"])
            if chunk.get("encoding") == "base64" and isinstance(chunk.get("data"), str):
                return base64.b64decode(chunk["data"])
            if "chunk" in chunk:
                return CoderAIProviderHandler._decode_broker_chunk(chunk.get("chunk"))
            return f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
        return str(chunk).encode("utf-8")

    async def _iter_broker_stream_chunks(self, initial_message: Dict[str, Any], timeout: float) -> AsyncIterator[bytes]:
        message = initial_message
        while True:
            status = message.get("status") or "ok"
            if status == "error":
                raise Exception(message.get("error") or "CoderAI broker bridge error")

            event = message.get("event")
            payload_data = message.get("payload") or {}

            # Broker HTTP envelope (ASGI bridge buffered the full response into payload.body).
            # Yield the body as raw bytes — SSE or JSON — then stop.
            if "status_code" in payload_data and "body" in payload_data:
                body = payload_data.get("body")
                if isinstance(body, str):
                    yield body.encode("utf-8")
                elif isinstance(body, bytes):
                    yield body
                elif isinstance(body, (dict, list)):
                    yield json.dumps(body, separators=(",", ":")).encode("utf-8")
                return

            if event in {"chunk", "progress", "output", "log", "data"}:
                chunk = payload_data.get("chunk", payload_data)
                yield self._decode_broker_chunk(chunk)
            elif isinstance(payload_data.get("chunks"), list):
                for item in payload_data.get("chunks", []):
                    yield self._decode_broker_chunk(item)

            if event in {None, "done", "completed"}:
                return

            next_request_id = message.get("request_id")
            if not next_request_id:
                return
            message = await coderai_broker.wait_for_stream_event(next_request_id, timeout=timeout)

    def validate_credentials(self) -> bool:
        if self._broker_mode:
            logger.info(f"[{self.provider_id}] CoderAI broker mode enabled; waiting for inbound broker session")
            return True
        if self._transport == "websocket" and not self._websocket_enabled:
            logger.error(f"[{self.provider_id}] WebSocket transport selected but disabled")
            return False
        if self._transport == "http" and not self._http_enabled:
            logger.error(f"[{self.provider_id}] HTTP transport selected but disabled")
            return False
        endpoint = self._ws_endpoint if self._transport == "websocket" else self._base_endpoint
        if not endpoint:
            logger.error(f"[{self.provider_id}] Missing endpoint configuration")
            return False
        logger.info(f"[{self.provider_id}] CoderAI transport={self._transport} endpoint={endpoint}")
        return True

    async def _ws_roundtrip(self, op: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        import websockets

        request_id = f"{self.provider_id}-{int(time.time() * 1000)}"
        envelope = {
            "v": 1,
            "op": op,
            "request_id": request_id,
            "provider_id": self.provider_id,
            "client_id": self._client_id,
            "payload": payload,
        }
        if self._registration_token:
            envelope["registration_token"] = self._registration_token
        if AISBF_DEBUG:
            logger.info(f"CoderAI WS send op={op} endpoint={self._ws_endpoint}")

        async with websockets.connect(self._ws_endpoint, additional_headers=self._build_ws_headers(), max_size=None, open_timeout=timeout or self._request_timeout) as websocket:
            await websocket.send(json.dumps(envelope))
            raw = await asyncio.wait_for(websocket.recv(), timeout=timeout or self._request_timeout)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            message = json.loads(raw)
            if message.get("request_id") not in (None, request_id):
                logger.warning(f"CoderAI WS mismatched request_id: {message.get('request_id')} != {request_id}")
            return message

    async def _ws_stream(self, op: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> AsyncIterator[bytes]:
        import websockets

        request_id = f"{self.provider_id}-{int(time.time() * 1000)}"
        envelope = {
            "v": 1,
            "op": op,
            "request_id": request_id,
            "provider_id": self.provider_id,
            "client_id": self._client_id,
            "payload": payload,
        }
        if self._registration_token:
            envelope["registration_token"] = self._registration_token

        async with websockets.connect(self._ws_endpoint, additional_headers=self._build_ws_headers(), max_size=None, open_timeout=timeout or self._request_timeout) as websocket:
            await websocket.send(json.dumps(envelope))
            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout=timeout or self._request_timeout)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                message = json.loads(raw)
                status = message.get("status") or "ok"
                if status == "error":
                    raise Exception(message.get("error") or "CoderAI WebSocket bridge error")
                payload_data = message.get("payload") or {}
                if message.get("event") == "chunk":
                    chunk = payload_data.get("chunk")
                    if isinstance(chunk, str):
                        yield chunk.encode("utf-8")
                    elif isinstance(chunk, bytes):
                        yield chunk
                    elif isinstance(chunk, dict):
                        yield f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
                    continue
                if message.get("event") == "done":
                    break

    async def _http_json(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        url = f"{self._base_endpoint.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=timeout or self._request_timeout) as client:
            response = await client.request(method.upper(), url, headers=self._build_http_headers(), json=payload)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _unwrap_broker_body(payload: Dict[str, Any]) -> Any:
        """Unwrap the HTTP envelope that the broker dispatcher puts around ASGI responses."""
        body = payload.get("body")
        if isinstance(body, str):
            try:
                return json.loads(body)
            except Exception:
                return payload
        if isinstance(body, (dict, list)):
            return body
        return payload

    def _extract_models(self, payload: Dict[str, Any]) -> List[Model]:
        models_data = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(models_data, list):
            models_data = payload.get("models", []) if isinstance(payload, dict) else []

        result: List[Model] = []
        for item in models_data:
            if isinstance(item, str):
                model_id = item
                metadata: Dict[str, Any] = {}
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model") or ""
                metadata = item
            else:
                continue

            if not model_id:
                continue

            context_size = metadata.get("context_window") or metadata.get("context_length") or metadata.get("max_context_length")
            result.append(Model(
                id=model_id,
                name=metadata.get("name") or model_id,
                provider_id=self.provider_id,
                context_size=context_size,
                context_length=context_size,
                architecture=metadata.get("architecture"),
                pricing=metadata.get("pricing"),
                top_provider=metadata.get("top_provider"),
                supported_parameters=metadata.get("supported_parameters"),
                default_parameters=metadata.get("default_parameters"),
                description=metadata.get("description"),
                type=metadata.get("type"),
                capabilities=metadata.get("capabilities") or None,
            ))
        return result

    def _build_chat_payload(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int],
        temperature: Optional[float],
        stream: Optional[bool],
        tools: Optional[List[Dict]],
        tool_choice: Optional[Union[str, Dict]],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [],
            "stream": bool(stream),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        for msg in messages:
            item = {"role": msg["role"]}
            for field in ("content", "tool_calls", "tool_call_id", "name"):
                if field in msg and msg[field] is not None:
                    item[field] = msg[field]
            if item["role"] == "tool" and not item.get("tool_call_id"):
                logger.warning(f"Skipping CoderAI tool message without tool_call_id: {msg}")
                continue
            payload["messages"].append(item)
        return payload

    async def handle_request(
        self,
        model: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 1.0,
        stream: Optional[bool] = False,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[Union[str, Dict]] = None,
    ) -> Union[Dict, object, AsyncIterator[bytes]]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        await self.apply_rate_limit()
        payload = self._build_chat_payload(model, messages, max_tokens, temperature, stream, tools, tool_choice)

        try:
            if await self._use_broker():
                if stream:
                    return self._broker_stream("chat.completions", payload, timeout=self._request_timeout)
                message = await self._broker_request("chat.completions", payload, timeout=self._request_timeout)
                if (message.get("status") or "ok") == "error":
                    raise Exception(message.get("error") or "CoderAI broker request failed")
                self.record_success()
                return self._unwrap_broker_body(message.get("payload") or {})
            if self._is_direct_websocket_mode():
                if stream:
                    return self._ws_stream("chat.completions", payload, timeout=self._request_timeout)
                message = await self._ws_roundtrip("chat.completions", payload, timeout=self._request_timeout)
                if (message.get("status") or "ok") == "error":
                    raise Exception(message.get("error") or "CoderAI WebSocket request failed")
                self.record_success()
                return message.get("payload") or {}
            if self._broker_preferred:
                raise RuntimeError(f"[{self.provider_id}] No active CoderAI broker session; direct fallback not allowed with broker_preferred=True")

            response = self.client.chat.completions.create(**payload)
            # Streaming returns a lazy iterator; recording success here would
            # prematurely reset the failure counter before the stream is consumed.
            # The caller records success after priming/consuming the stream.
            if not stream:
                self.record_success()
            return response
        except Exception:
            self.record_failure()
            raise

    async def get_models(self) -> List[Model]:
        await self.apply_rate_limit()
        try:
            if await self._use_broker():
                message = await self._broker_request("models.list", {}, timeout=self._model_timeout)
                if (message.get("status") or "ok") == "error":
                    raise Exception(message.get("error") or "CoderAI broker model discovery failed")
                http_payload = message.get("payload") or {}
                http_status = http_payload.get("status_code", 200)
                if isinstance(http_status, int) and http_status >= 400:
                    raise Exception(f"CoderAI model discovery failed: HTTP {http_status} from remote")
                return self._extract_models(self._unwrap_broker_body(http_payload))
            if self._is_direct_websocket_mode():
                message = await self._ws_roundtrip("models.list", {}, timeout=self._model_timeout)
                if (message.get("status") or "ok") == "error":
                    raise Exception(message.get("error") or "CoderAI model discovery failed")
                return self._extract_models(message.get("payload") or {})
            if self._broker_preferred:
                raise RuntimeError(f"[{self.provider_id}] No active CoderAI broker session; direct fallback not allowed with broker_preferred=True")
            models = self.client.models.list()
            payload = {"data": [m.model_dump() if hasattr(m, "model_dump") else m for m in models]}
            return self._extract_models(payload)
        except Exception:
            logger.error(f"CoderAIProviderHandler: Error getting models", exc_info=True)
            raise

    async def discover_capabilities(self) -> Dict[str, Any]:
        if not self._discovery_enabled:
            return {}
        if await self._use_broker():
            message = await self._broker_request("capabilities", {}, timeout=self._model_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or "CoderAI broker capability discovery failed")
            return self._unwrap_broker_body(message.get("payload") or {})
        if self._is_direct_websocket_mode():
            message = await self._ws_roundtrip("capabilities", {}, timeout=self._model_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or "CoderAI capability discovery failed")
            return message.get("payload") or {}
        if self._broker_mode or self._broker_preferred:
            raise Exception(f"[{self.provider_id}] No active CoderAI broker session; direct fallback not allowed")
        return await self._http_json("GET", "/coderai/capabilities", timeout=self._model_timeout)

    async def register_client(self) -> Dict[str, Any]:
        payload = {
            "provider_id": self.provider_id,
            "client_id": self._client_id,
            "transport": self._transport,
            "endpoint": self._raw_endpoint,
        }
        if await self._use_broker():
            message = await self._broker_request("register", payload, timeout=self._model_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or "CoderAI broker registration failed")
            return self._unwrap_broker_body(message.get("payload") or {})
        if self._is_direct_websocket_mode():
            message = await self._ws_roundtrip("register", payload, timeout=self._model_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or "CoderAI registration failed")
            return message.get("payload") or {}
        if self._broker_mode or self._broker_preferred:
            raise Exception(f"[{self.provider_id}] No active CoderAI broker session; direct fallback not allowed")
        return await self._http_json("POST", self._registration_path, payload, timeout=self._model_timeout)

    async def proxy_native_request(
        self,
        endpoint_path: str,
        body: Optional[Dict[str, Any]] = None,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        content_type: Optional[str] = None,
        multipart: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Tuple[int, Dict[str, Any]]:
        payload = {
            "endpoint_path": endpoint_path,
            "method": method.upper(),
            "body": body or {},
            "headers": headers or {},
            "query_params": query_params or {},
        }
        if content_type:
            payload["content_type"] = content_type
        if multipart is not None:
            payload["multipart"] = multipart
        if stream:
            payload["stream"] = True
        if await self._use_broker():
            if stream:
                chunks = []
                async for chunk in self._broker_stream("proxy", payload, timeout=self._request_timeout):
                    chunks.append(chunk)
                return 200, {"stream_chunks": [base64.b64encode(chunk).decode("ascii") for chunk in chunks], "stream_encoding": "base64"}
            message = await self._broker_request("proxy", payload, timeout=self._request_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or "CoderAI broker proxy request failed")
            envelope = message.get("payload") or {}
            return int(envelope.get("status_code") or 200), envelope
        if self._is_direct_websocket_mode():
            message = await self._ws_roundtrip("proxy", payload, timeout=self._request_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or "CoderAI proxy request failed")
            envelope = message.get("payload") or {}
            return int(envelope.get("status_code") or 200), envelope
        if self._broker_mode or self._broker_preferred:
            raise Exception(f"[{self.provider_id}] No active CoderAI broker session; direct fallback not allowed")
        response = await self._http_json(method.upper(), endpoint_path, body or {}, timeout=self._request_timeout)
        return 200, response

    async def fetch_file(self, path: str) -> Tuple[bytes, str]:
        """Fetch a generated file from coderai.

        For broker-connected providers the file is transferred through the WSS
        tunnel (no direct network access required).  For direct providers it
        falls back to a plain HTTP GET.
        """
        if await self._use_broker():
            message = await self._broker_request("proxy", {
                "endpoint_path": path,
                "method": "GET",
                "body": {},
                "headers": {},
                "query_params": {},
            }, timeout=self._request_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or f"CoderAI broker file fetch failed: {path}")
            envelope = message.get("payload") or {}
            content_type = envelope.get("content_type") or "application/octet-stream"
            if envelope.get("body_base64"):
                return base64.b64decode(envelope["body_base64"]), content_type
            if isinstance(envelope.get("body"), str):
                return envelope["body"].encode("utf-8"), content_type
            raise Exception(f"No file content in broker response for {path}")
        if self._is_direct_websocket_mode():
            message = await self._ws_roundtrip("proxy", {
                "endpoint_path": path,
                "method": "GET",
                "body": {},
                "headers": {},
                "query_params": {},
            }, timeout=self._request_timeout)
            if (message.get("status") or "ok") == "error":
                raise Exception(message.get("error") or f"CoderAI file fetch failed: {path}")
            envelope = message.get("payload") or {}
            content_type = envelope.get("content_type") or "application/octet-stream"
            if envelope.get("body_base64"):
                return base64.b64decode(envelope["body_base64"]), content_type
            if isinstance(envelope.get("body"), str):
                return envelope["body"].encode("utf-8"), content_type
            raise Exception(f"No file content in WS response for {path}")
        if self._broker_mode or self._broker_preferred:
            raise Exception(f"[{self.provider_id}] No active CoderAI broker session; direct fallback not allowed")
        url = f"{self._base_endpoint.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self._request_timeout) as client:
            resp = await client.get(url, headers=self._build_http_headers(), follow_redirects=True)
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "application/octet-stream")
