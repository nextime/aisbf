"""
CoderAI broker and session registry for NAT-friendly outbound connections.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import WebSocket

from .cache import get_cache_manager


logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 120
REQUEST_TTL_SECONDS = 300
REPLY_TTL_SECONDS = 300
HEARTBEAT_POLL_SECONDS = 1
PERFORMANCE_WINDOW_SIZE = 100


class BrokerPlaceholderWebSocket:
    async def send_text(self, payload: str):
        raise RuntimeError("CoderAI broker session is offline and cannot accept requests")


@dataclass
class PendingCoderAIRequest:
    future: asyncio.Future
    created_at: float
    stream_queue: asyncio.Queue | None = None
    event_log: list[Dict[str, Any]] = field(default_factory=list)
    request_snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoderAISession:
    session_id: str
    provider_id: str
    client_id: str
    websocket: WebSocket
    connected_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    closed: bool = False
    recent_requests: deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=PERFORMANCE_WINDOW_SIZE))


class CoderAIBroker:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._sessions_by_key: Dict[str, CoderAISession] = {}
        self._sessions_by_id: Dict[str, CoderAISession] = {}
        self._pending: Dict[str, PendingCoderAIRequest] = {}
        self._state_path = Path.home() / '.aisbf' / 'coderai_broker_sessions.json'
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = get_cache_manager()
        self._node_id = self._cache.broker_node_id()
        self._load_persisted_sessions()

    @staticmethod
    def _session_key(provider_id: str, client_id: str) -> str:
        return f"{provider_id}:{client_id}"

    @staticmethod
    def _request_queue_key(session_id: str) -> str:
        return f"request_queue:{session_id}"

    @staticmethod
    def _reply_key(request_id: str) -> str:
        return f"reply:{request_id}"

    @staticmethod
    def _session_meta_key(provider_id: str, client_id: str) -> str:
        return f"session:{provider_id}:{client_id}"

    @staticmethod
    def _session_index_key() -> str:
        return "session_index"

    def _serialize_session(self, session: CoderAISession) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "provider_id": session.provider_id,
            "client_id": session.client_id,
            "connected_at": session.connected_at,
            "last_seen": session.last_seen,
            "closed": session.closed,
            "metadata": dict(session.metadata),
            "capabilities": dict(session.capabilities),
            "performance": self._build_performance_snapshot(session),
        }

    @staticmethod
    def _normalize_hardware_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        result = dict(metadata or {})
        gpus = result.get("gpus") or result.get("gpu") or []
        if isinstance(gpus, dict):
            gpus = [gpus]
        normalized_gpus = []
        total_vram_mb = 0.0
        available_vram_mb = 0.0
        for gpu in gpus if isinstance(gpus, list) else []:
            if not isinstance(gpu, dict):
                continue
            normalized_gpu = dict(gpu)
            total_mb = normalized_gpu.get("total_vram_mb")
            available_mb = normalized_gpu.get("available_vram_mb")
            used_mb = normalized_gpu.get("used_vram_mb")
            if total_mb is None and normalized_gpu.get("total_vram_gb") is not None:
                total_mb = float(normalized_gpu.get("total_vram_gb")) * 1024.0
            if available_mb is None and normalized_gpu.get("available_vram_gb") is not None:
                available_mb = float(normalized_gpu.get("available_vram_gb")) * 1024.0
            if used_mb is None and normalized_gpu.get("used_vram_gb") is not None:
                used_mb = float(normalized_gpu.get("used_vram_gb")) * 1024.0
            if total_mb is None and available_mb is not None and used_mb is not None:
                total_mb = float(available_mb) + float(used_mb)
            if available_mb is None and total_mb is not None and used_mb is not None:
                available_mb = max(float(total_mb) - float(used_mb), 0.0)
            if used_mb is None and total_mb is not None and available_mb is not None:
                used_mb = max(float(total_mb) - float(available_mb), 0.0)
            if total_mb is not None:
                normalized_gpu["total_vram_mb"] = float(total_mb)
                total_vram_mb += float(total_mb)
            if available_mb is not None:
                normalized_gpu["available_vram_mb"] = float(available_mb)
                available_vram_mb += float(available_mb)
            if used_mb is not None:
                normalized_gpu["used_vram_mb"] = float(used_mb)
            normalized_gpus.append(normalized_gpu)
        if normalized_gpus:
            result["gpus"] = normalized_gpus
            result["gpu_count"] = len(normalized_gpus)
            result["total_vram_mb"] = total_vram_mb
            # Only overwrite the top-level available_vram_mb when the GPU loop
            # actually produced data; otherwise keep the value that arrived at
            # the top level of the metadata (e.g. coderai sends it there but
            # does not repeat it inside each GPU dict).
            if available_vram_mb > 0:
                result["available_vram_mb"] = available_vram_mb
            elif result.get("available_vram_mb") is None:
                result["available_vram_mb"] = 0.0
            # Propagate top-level free VRAM into the single GPU so the UI can
            # read it from the per-GPU entry too.
            if len(normalized_gpus) == 1 and normalized_gpus[0].get("available_vram_mb") is None:
                top_free = result.get("available_vram_mb")
                if top_free is not None:
                    normalized_gpus[0]["available_vram_mb"] = float(top_free)
            final_free = result.get("available_vram_mb") or 0.0
            result["used_vram_mb"] = max(total_vram_mb - final_free, 0.0)
        return result

    @staticmethod
    def _estimate_performance_sample(message: Dict[str, Any], started_at: float) -> Dict[str, Any]:
        payload = message.get("payload") or {}
        latency_ms = payload.get("latency_ms")
        if latency_ms is None:
            latency_ms = max((time.time() - started_at) * 1000.0, 0.0)
        usage = payload.get("usage") or {}
        prompt_tokens = payload.get("prompt_tokens")
        completion_tokens = payload.get("completion_tokens")
        total_tokens = payload.get("total_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage.get("prompt_tokens")
        if completion_tokens is None:
            completion_tokens = usage.get("completion_tokens")
        if total_tokens is None:
            total_tokens = usage.get("total_tokens")
        if total_tokens is None:
            values = [value for value in (prompt_tokens, completion_tokens) if isinstance(value, (int, float))]
            total_tokens = sum(values) if values else None
        tokens_per_second = payload.get("tokens_per_second") or payload.get("tok_per_s") or payload.get("throughput_tps")
        if tokens_per_second is None and isinstance(total_tokens, (int, float)) and latency_ms:
            seconds = float(latency_ms) / 1000.0
            if seconds > 0:
                tokens_per_second = float(total_tokens) / seconds
        return {
            "latency_ms": float(latency_ms),
            "prompt_tokens": int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else None,
            "completion_tokens": int(completion_tokens) if isinstance(completion_tokens, (int, float)) else None,
            "total_tokens": int(total_tokens) if isinstance(total_tokens, (int, float)) else None,
            "tokens_per_second": float(tokens_per_second) if isinstance(tokens_per_second, (int, float)) else None,
            "success": (message.get("status") or "ok") != "error",
            "recorded_at": time.time(),
        }

    @staticmethod
    def _build_performance_snapshot(session: CoderAISession) -> Dict[str, Any]:
        samples = list(session.recent_requests)
        if not samples:
            return {
                "window_size": PERFORMANCE_WINDOW_SIZE,
                "sample_count": 0,
                "estimated": True,
                "avg_latency_ms": 0.0,
                "avg_tokens_per_second": 0.0,
                "avg_total_tokens": 0.0,
                "success_rate": 0.0,
                "last_latency_ms": None,
                "last_tokens_per_second": None,
                "last_total_tokens": None,
            }
        latencies = [sample["latency_ms"] for sample in samples if isinstance(sample.get("latency_ms"), (int, float))]
        tps_values = [sample["tokens_per_second"] for sample in samples if isinstance(sample.get("tokens_per_second"), (int, float))]
        total_tokens = [sample["total_tokens"] for sample in samples if isinstance(sample.get("total_tokens"), (int, float))]
        success_count = sum(1 for sample in samples if sample.get("success"))
        last = samples[-1]
        return {
            "window_size": PERFORMANCE_WINDOW_SIZE,
            "sample_count": len(samples),
            "estimated": True,
            "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
            "avg_tokens_per_second": (sum(tps_values) / len(tps_values)) if tps_values else 0.0,
            "avg_total_tokens": (sum(total_tokens) / len(total_tokens)) if total_tokens else 0.0,
            "success_rate": success_count / len(samples),
            "last_latency_ms": last.get("latency_ms"),
            "last_tokens_per_second": last.get("tokens_per_second"),
            "last_total_tokens": last.get("total_tokens"),
        }

    async def _record_request_metric(self, request_id: str, message: Dict[str, Any]) -> None:
        async with self._lock:
            pending = self._pending.get(request_id)
            if not pending:
                return
            session_id = (pending.request_snapshot or {}).get("session_id")
            session = self._sessions_by_id.get(session_id) if session_id else None
            if not session:
                return
            session.recent_requests.append(self._estimate_performance_sample(message, pending.created_at))
            self._store_session_cache(session)
            self._persist_sessions_locked()

    def _persist_sessions_locked(self) -> None:
        payload = {
            "sessions": [
                self._serialize_session(session)
                for session in self._sessions_by_id.values()
            ],
            "updated_at": time.time(),
        }
        temp_path = self._state_path.with_suffix(self._state_path.suffix + '.tmp')
        with open(temp_path, 'w') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self._state_path)

    def _quarantine_invalid_state_file(self) -> Optional[Path]:
        if not self._state_path.exists():
            return None
        timestamp = int(time.time())
        quarantine_path = self._state_path.with_name(f"{self._state_path.name}.corrupt.{timestamp}")
        counter = 1
        while quarantine_path.exists():
            quarantine_path = self._state_path.with_name(f"{self._state_path.name}.corrupt.{timestamp}.{counter}")
            counter += 1
        try:
            self._state_path.replace(quarantine_path)
            return quarantine_path
        except Exception:
            logger.exception("Failed to quarantine invalid CoderAI broker session state file")
            return None

    def _load_persisted_sessions(self) -> None:
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path) as f:
                payload = json.load(f)
        except Exception as e:
            quarantine_path = self._quarantine_invalid_state_file()
            if quarantine_path is not None:
                logger.warning(
                    "Failed to load persisted CoderAI broker sessions: %s. Moved invalid state file to %s",
                    e,
                    quarantine_path,
                )
            else:
                logger.warning(f"Failed to load persisted CoderAI broker sessions: {e}")
            return

        for raw_session in payload.get("sessions") or []:
            if not isinstance(raw_session, dict):
                continue
            provider_id = raw_session.get("provider_id")
            client_id = raw_session.get("client_id")
            session_id = raw_session.get("session_id") or f"coderai_{uuid.uuid4().hex}"
            if not provider_id or not client_id:
                continue
            session = CoderAISession(
                session_id=session_id,
                provider_id=provider_id,
                client_id=client_id,
                websocket=BrokerPlaceholderWebSocket(),
                connected_at=float(raw_session.get("connected_at") or time.time()),
                metadata=dict(raw_session.get("metadata") or {}),
                capabilities=dict(raw_session.get("capabilities") or {}),
                last_seen=float(raw_session.get("last_seen") or time.time()),
                closed=bool(raw_session.get("closed", True)),
            )
            perf = raw_session.get("performance") or {}
            if isinstance(perf, dict) and int(perf.get("sample_count") or 0) > 0:
                sample_count = min(int(perf.get("sample_count") or 0), PERFORMANCE_WINDOW_SIZE)
                for _ in range(sample_count):
                    session.recent_requests.append({
                        "latency_ms": float(perf.get("avg_latency_ms") or 0.0),
                        "tokens_per_second": float(perf.get("avg_tokens_per_second")) if isinstance(perf.get("avg_tokens_per_second"), (int, float)) else None,
                        "total_tokens": float(perf.get("avg_total_tokens")) if isinstance(perf.get("avg_total_tokens"), (int, float)) else None,
                        "success": True,
                        "recorded_at": session.last_seen,
                    })
            session.metadata.setdefault("persisted", True)
            session.metadata.setdefault("connection_state", "disconnected")
            key = self._session_key(provider_id, client_id)
            self._sessions_by_key[key] = session
            self._sessions_by_id[session_id] = session

    def _store_session_cache(self, session: CoderAISession) -> None:
        payload = self._serialize_session(session)
        payload["metadata"] = dict(payload.get("metadata") or {})
        payload["metadata"]["broker_node_id"] = session.metadata.get("broker_node_id") or self._node_id
        session.metadata.setdefault("broker_node_id", self._node_id)
        payload["metadata"]["connection_state"] = "connected" if not session.closed else "disconnected"
        self._cache.broker_set(self._session_meta_key(session.provider_id, session.client_id), payload, ttl=SESSION_TTL_SECONDS)

        index = self._cache.broker_get(self._session_index_key()) or []
        if not isinstance(index, list):
            index = []
        key = self._session_meta_key(session.provider_id, session.client_id)
        if key not in index:
            index.append(key)
            self._cache.broker_set(self._session_index_key(), index, ttl=SESSION_TTL_SECONDS * 10)

    def _delete_session_cache(self, provider_id: str, client_id: str) -> None:
        key = self._session_meta_key(provider_id, client_id)
        self._cache.broker_delete(key)
        index = self._cache.broker_get(self._session_index_key()) or []
        if isinstance(index, list) and key in index:
            index = [item for item in index if item != key]
            self._cache.broker_set(self._session_index_key(), index, ttl=SESSION_TTL_SECONDS * 10)

    async def register(self, websocket: WebSocket, provider_id: str, client_id: str, metadata: Optional[Dict[str, Any]] = None, capabilities: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> CoderAISession:
        async with self._lock:
            key = self._session_key(provider_id, client_id)
            existing = self._sessions_by_key.get(key)
            if existing:
                existing.closed = True
            resolved_session_id = session_id or f"coderai_{uuid.uuid4().hex}"
            session = CoderAISession(
                session_id=resolved_session_id,
                provider_id=provider_id,
                client_id=client_id,
                websocket=websocket,
                metadata=self._normalize_hardware_metadata(metadata),
                capabilities=dict(capabilities or {}),
            )
            session.closed = False
            session.metadata.setdefault("connection_state", "connected")
            session.metadata["persisted"] = True
            self._sessions_by_key[key] = session
            self._sessions_by_id[resolved_session_id] = session
            self._store_session_cache(session)
            self._persist_sessions_locked()
            logger.info(f"CoderAI broker registered session provider={provider_id} client={client_id} session_id={resolved_session_id}")
            return session

    async def unregister(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions_by_id.get(session_id)
            if not session:
                return
            key = self._session_key(session.provider_id, session.client_id)
            session.closed = True
            session.websocket = BrokerPlaceholderWebSocket()
            session.metadata["connection_state"] = "disconnected"
            session.last_seen = time.time()
            self._sessions_by_key[key] = session
            self._store_session_cache(session)
            self._persist_sessions_locked()
            logger.info(f"CoderAI broker unregistered session provider={session.provider_id} client={session.client_id} session_id={session.session_id}")

    async def touch(self, session_id: str, metadata: Optional[Dict[str, Any]] = None, capabilities: Optional[Dict[str, Any]] = None) -> Optional[CoderAISession]:
        async with self._lock:
            session = self._sessions_by_id.get(session_id)
            if not session:
                return None
            session.last_seen = time.time()
            if metadata:
                session.metadata.update(self._normalize_hardware_metadata(metadata))
            if capabilities:
                session.capabilities = dict(capabilities)
            self._store_session_cache(session)
            self._persist_sessions_locked()
            return session

    async def get_session(self, provider_id: str, client_id: Optional[str] = None) -> Optional[CoderAISession]:
        async with self._lock:
            if client_id:
                session = self._sessions_by_key.get(self._session_key(provider_id, client_id))
                if session and not session.closed:
                    return session
            else:
                candidates = [session for session in self._sessions_by_key.values() if session.provider_id == provider_id and not session.closed]
                if candidates:
                    candidates.sort(key=lambda session: session.last_seen, reverse=True)
                    return candidates[0]

        # Session exists on another broker node: we have no local WebSocket handle,
        # so we cannot deliver requests directly. Return None; send_request will
        # route through the Redis queue to the owning node.
        snapshot = await self.get_session_snapshot(provider_id, client_id)
        if snapshot and snapshot.get("connected"):
            logger.debug(f"CoderAI session for provider={provider_id} is connected on a remote broker node")
        return None

    async def list_sessions(self) -> list[Dict[str, Any]]:
        cache_sessions = []
        index = self._cache.broker_get(self._session_index_key()) or []
        if isinstance(index, list):
            for key in index:
                meta = self._cache.broker_get(key.replace(self._cache.broker_key(''), '')) if False else None
                stored = self._cache.get(key) if key.startswith(self._cache.config.get('redis_key_prefix', 'aisbf:')) else self._cache.broker_get(key)
                if stored:
                    cache_sessions.append(stored)

        merged: Dict[str, Dict[str, Any]] = {}
        for item in cache_sessions:
            if not isinstance(item, dict):
                continue
            merged[item.get("session_id") or f"missing:{uuid.uuid4().hex}"] = {
                "session_id": item.get("session_id"),
                "provider_id": item.get("provider_id"),
                "client_id": item.get("client_id"),
                "connected_at": item.get("connected_at"),
                "last_seen": item.get("last_seen"),
                "metadata": item.get("metadata") or {},
                "capabilities": item.get("capabilities") or {},
                "connected": not bool(item.get("closed")),
            }

        async with self._lock:
            for session in self._sessions_by_id.values():
                merged[session.session_id] = {
                    "session_id": session.session_id,
                    "provider_id": session.provider_id,
                    "client_id": session.client_id,
                    "connected_at": session.connected_at,
                    "last_seen": session.last_seen,
                    "metadata": dict(session.metadata),
                    "capabilities": dict(session.capabilities),
                    "connected": not session.closed,
                }

        return list(merged.values())

    async def get_session_snapshot(self, provider_id: str, client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if client_id:
            payload = self._cache.broker_get(self._session_meta_key(provider_id, client_id))
            if payload:
                payload["connected"] = not bool(payload.get("closed"))
                return payload
            async with self._lock:
                local_session = self._sessions_by_key.get(self._session_key(provider_id, client_id))
                if local_session:
                    return {
                        "session_id": local_session.session_id,
                        "provider_id": local_session.provider_id,
                        "client_id": local_session.client_id,
                        "connected_at": local_session.connected_at,
                        "last_seen": local_session.last_seen,
                        "closed": local_session.closed,
                        "metadata": dict(local_session.metadata),
                        "capabilities": dict(local_session.capabilities),
                        "connected": not local_session.closed,
                    }

        candidates = []
        for session in await self.list_sessions():
            if session.get("provider_id") == provider_id:
                candidates.append(session)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.get("last_seen") or 0, reverse=True)
        return candidates[0]

    async def send_request(self, provider_id: str, op: str, payload: Dict[str, Any], timeout: float = 300.0, client_id: Optional[str] = None, owner_user_id: Optional[int] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        snapshot = await self.get_session_snapshot(provider_id, client_id)
        if (not snapshot or not snapshot.get("connected")) and client_id:
            fallback_snapshot = await self.get_session_snapshot(client_id, client_id)
            fallback_metadata = (fallback_snapshot or {}).get("metadata") or {}
            if fallback_snapshot and fallback_snapshot.get("connected") and fallback_metadata.get("owner_user_id") == owner_user_id:
                snapshot = fallback_snapshot
                provider_id = snapshot.get("provider_id") or provider_id
        if not snapshot or not snapshot.get("connected"):
            raise RuntimeError(f"No active CoderAI broker session for provider '{provider_id}'")
        if owner_user_id != ((snapshot.get('metadata') or {}).get('owner_user_id')):
            raise RuntimeError(f"No active CoderAI broker session for provider '{provider_id}' owned by the current principal")

        request_id = f"broker_{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        stream_queue = asyncio.Queue() if payload.get("stream") else None
        envelope = {
            "v": 1,
            "op": op,
            "request_id": request_id,
            "provider_id": snapshot.get("provider_id") or provider_id,
            "client_id": snapshot.get("client_id") or client_id,
            "payload": payload,
            "reply_key": self._reply_key(request_id),
            "requester_node_id": self._node_id,
        }
        if extra:
            envelope.update(extra)

        async with self._lock:
            self._pending[request_id] = PendingCoderAIRequest(
                future=future,
                created_at=time.time(),
                stream_queue=stream_queue,
                request_snapshot={
                    "session_id": snapshot.get("session_id"),
                    "provider_id": snapshot.get("provider_id") or provider_id,
                    "client_id": snapshot.get("client_id") or client_id,
                    "op": op,
                },
            )

        local_session = None
        target_node_id = None
        async with self._lock:
            local_session = self._sessions_by_id.get(snapshot["session_id"])
            local_node_id = local_session.metadata.get("broker_node_id") if local_session else None
            target_node_id = ((snapshot.get("metadata") or {}).get("broker_node_id") if snapshot else None)
            if target_node_id is None:
                target_node_id = local_node_id

        use_local_fast_path = bool(
            local_session
            and not local_session.closed
            and (target_node_id is None or target_node_id == self._node_id)
        )

        try:
            if use_local_fast_path:
                await local_session.websocket.send_text(json.dumps(envelope))
                logger.debug(f"CoderAI broker fast-pathed op={op} provider={provider_id} client={snapshot.get('client_id')} request_id={request_id}")
            else:
                self._cache.broker_push(self._request_queue_key(snapshot["session_id"]), envelope, ttl=REQUEST_TTL_SECONDS)
                logger.debug(f"CoderAI broker enqueued op={op} provider={provider_id} client={snapshot.get('client_id')} request_id={request_id}")

            async def wait_reply() -> Dict[str, Any]:
                if use_local_fast_path:
                    return await asyncio.wait_for(future, timeout=timeout)

                deadline = time.time() + timeout
                while time.time() < deadline:
                    reply = self._cache.broker_get(self._reply_key(request_id))
                    if reply is not None:
                        self._cache.broker_delete(self._reply_key(request_id))
                        return reply
                    if future.done():
                        return future.result()
                    await asyncio.sleep(0.1)
                raise asyncio.TimeoutError()

            result = await asyncio.wait_for(wait_reply(), timeout=timeout)
            if not future.done():
                future.set_result(result)
            return result
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def consume_request(self, session_id: str, timeout: int = HEARTBEAT_POLL_SECONDS) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._cache.broker_blocking_pop, self._request_queue_key(session_id), timeout)

    async def publish_response(self, message: Dict[str, Any]) -> None:
        request_id = message.get("request_id")
        if not request_id:
            return
        event = message.get("event")
        if event in {"chunk", "progress", "output", "log", "data", "done", "completed"}:
            await self._publish_stream_response(message)
            return
        await self._record_request_metric(request_id, message)
        self._cache.broker_set(self._reply_key(request_id), message, ttl=REPLY_TTL_SECONDS)
        await self.resolve_response(message)

    async def _publish_stream_response(self, message: Dict[str, Any]) -> None:
        request_id = message.get("request_id")
        async with self._lock:
            pending = self._pending.get(request_id)
            queue = pending.stream_queue if pending else None
        if queue is not None:
            pending.event_log.append(message)
            if message.get("event") in {"done", "completed"} and not pending.future.done():
                await self._record_request_metric(request_id, message)
                pending.future.set_result(message)
            else:
                await queue.put(message)
            return
        self._cache.broker_push(self._reply_key(request_id), message, ttl=REPLY_TTL_SECONDS)

    async def wait_for_stream_event(self, request_id: str, timeout: float = 300.0) -> Dict[str, Any]:
        async with self._lock:
            pending = self._pending.get(request_id)
            queue = pending.stream_queue if pending else None
            if pending and pending.event_log:
                for idx, event in enumerate(pending.event_log):
                    if event.get("event") not in {"done", "completed"}:
                        pending.event_log.pop(idx)
                        return event
        if queue is not None:
            return await asyncio.wait_for(queue.get(), timeout=timeout)

        deadline = time.time() + timeout
        while time.time() < deadline:
            reply = self._cache.broker_pop_nowait(self._reply_key(request_id))
            if reply is not None:
                return reply
            await asyncio.sleep(0.1)
        raise asyncio.TimeoutError()

    async def resolve_response(self, message: Dict[str, Any]) -> bool:
        request_id = message.get("request_id")
        if not request_id:
            return False
        async with self._lock:
            pending = self._pending.get(request_id)
            if not pending:
                return False
            if not pending.future.done():
                pending.future.set_result(message)
            return True

    async def fail_session_requests(self, session_id: str, error: str) -> None:
        async with self._lock:
            pending_items = list(self._pending.items())
        for request_id, pending in pending_items:
            if not pending.future.done():
                pending.future.set_exception(RuntimeError(error))
            async with self._lock:
                self._pending.pop(request_id, None)


broker = CoderAIBroker()
