"""
CoderAI broker – cluster-aware WebSocket session manager.

Design contract:
  - A CoderAI client connects via WSS to whichever AISBF instance the load
    balancer picks.  That instance owns the WebSocket for the lifetime of the
    connection.
  - Requests from ANY instance in the cluster are enqueued in the shared cache
    under request_queue:{session_id}.  The owning instance drains that queue
    and forwards each envelope to the CoderAI client.
  - Replies are stored in the shared cache under reply:{request_id}.  The
    requesting instance polls until the reply appears (or the session dies).
  - Streaming chunks follow the same reply-key path when the request originates
    on a remote instance; when it originates locally the asyncio.Queue fast-path
    is used.
  - Session metadata (including broker_node_id and connection_state) is kept in
    the shared cache with a TTL.  The owning instance refreshes the TTL via a
    background heartbeat task.  If the instance crashes without a clean
    disconnect, the TTL expires and the session disappears from the cache –
    every other instance will then see the provider as offline within
    SESSION_TTL_SECONDS seconds.
  - node_id is a UUID generated fresh at process start and is NEVER shared
    through the cache.  Each instance has its own unique node_id.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import WebSocket

from .cache import get_cache_manager


logger = logging.getLogger(__name__)

# Session metadata TTL in the shared cache.  The owning instance refreshes
# this every SESSION_HEARTBEAT_SECONDS, so the effective death-detection
# window is SESSION_TTL_SECONDS after the last heartbeat.
SESSION_TTL_SECONDS = 90
SESSION_HEARTBEAT_SECONDS = 30
REQUEST_TTL_SECONDS = 300
REPLY_TTL_SECONDS = 300
# How long broker_blocking_pop blocks waiting for a new queue item before
# looping.  Keep at 1 s so the drain loop stays responsive to cancellation.
HEARTBEAT_POLL_SECONDS = 1
PERFORMANCE_WINDOW_SIZE = 100
# How often (seconds) the slow-path polling checks session liveness.
LIVENESS_CHECK_INTERVAL = 5.0


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
        # In-memory local sessions (WebSocket is on this instance).
        self._sessions_by_key: Dict[str, CoderAISession] = {}
        self._sessions_by_id: Dict[str, CoderAISession] = {}
        # Pending requests whose Future/Queue lives on this instance.
        self._pending: Dict[str, PendingCoderAIRequest] = {}
        # Per-session background heartbeat tasks (only for locally owned sessions).
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self._cache = get_cache_manager()
        # Unique per process restart – never written to the shared cache.
        self._node_id = uuid.uuid4().hex

    # ------------------------------------------------------------------ keys

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

    # --------------------------------------------------------- serialisation

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
            if available_vram_mb > 0:
                result["available_vram_mb"] = available_vram_mb
            elif result.get("available_vram_mb") is None:
                result["available_vram_mb"] = 0.0
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
        prompt_tokens = payload.get("prompt_tokens") or usage.get("prompt_tokens")
        completion_tokens = payload.get("completion_tokens") or usage.get("completion_tokens")
        total_tokens = payload.get("total_tokens") or usage.get("total_tokens")
        if total_tokens is None:
            values = [v for v in (prompt_tokens, completion_tokens) if isinstance(v, (int, float))]
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
        latencies = [s["latency_ms"] for s in samples if isinstance(s.get("latency_ms"), (int, float))]
        tps_values = [s["tokens_per_second"] for s in samples if isinstance(s.get("tokens_per_second"), (int, float))]
        total_tokens = [s["total_tokens"] for s in samples if isinstance(s.get("total_tokens"), (int, float))]
        success_count = sum(1 for s in samples if s.get("success"))
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

    # -------------------------------------------------- shared cache helpers

    def _store_session_cache(self, session: CoderAISession) -> None:
        payload = self._serialize_session(session)
        payload["metadata"] = dict(payload.get("metadata") or {})
        payload["metadata"]["broker_node_id"] = self._node_id
        payload["metadata"]["connection_state"] = "connected" if not session.closed else "disconnected"
        meta_key = self._session_meta_key(session.provider_id, session.client_id)
        self._cache.broker_set(meta_key, payload, ttl=SESSION_TTL_SECONDS)
        # Keep a global index of all live session meta keys so list_sessions
        # can enumerate them without a Redis SCAN.
        index = self._cache.broker_get(self._session_index_key()) or []
        if not isinstance(index, list):
            index = []
        if meta_key not in index:
            index.append(meta_key)
            self._cache.broker_set(self._session_index_key(), index, ttl=SESSION_TTL_SECONDS * 10)

    def _mark_session_offline_cache(self, provider_id: str, client_id: str) -> None:
        """Write a closed=True tombstone so remote nodes see the disconnect immediately."""
        meta_key = self._session_meta_key(provider_id, client_id)
        existing = self._cache.broker_get(meta_key) or {}
        existing["closed"] = True
        existing["metadata"] = dict(existing.get("metadata") or {})
        existing["metadata"]["connection_state"] = "disconnected"
        existing["last_seen"] = time.time()
        # Keep tombstone visible for a short window so pollers detect it fast.
        self._cache.broker_set(meta_key, existing, ttl=SESSION_TTL_SECONDS)

    def _remove_session_from_index(self, provider_id: str, client_id: str) -> None:
        meta_key = self._session_meta_key(provider_id, client_id)
        index = self._cache.broker_get(self._session_index_key()) or []
        if isinstance(index, list) and meta_key in index:
            index = [k for k in index if k != meta_key]
            self._cache.broker_set(self._session_index_key(), index, ttl=SESSION_TTL_SECONDS * 10)

    # -------------------------------------------------- heartbeat management

    def _start_heartbeat(self, session_id: str) -> None:
        task = asyncio.create_task(self._heartbeat_loop(session_id))
        self._heartbeat_tasks[session_id] = task

    def _stop_heartbeat(self, session_id: str) -> None:
        task = self._heartbeat_tasks.pop(session_id, None)
        if task:
            task.cancel()

    async def _heartbeat_loop(self, session_id: str) -> None:
        """Refresh the shared-cache TTL for a locally owned session."""
        try:
            while True:
                await asyncio.sleep(SESSION_HEARTBEAT_SECONDS)
                async with self._lock:
                    session = self._sessions_by_id.get(session_id)
                    if not session or session.closed:
                        return
                    session.last_seen = time.time()
                    self._store_session_cache(session)
        except asyncio.CancelledError:
            pass

    # -------------------------------------------------- session lifecycle

    async def register(
        self,
        websocket: WebSocket,
        provider_id: str,
        client_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        capabilities: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> CoderAISession:
        async with self._lock:
            key = self._session_key(provider_id, client_id)
            existing = self._sessions_by_key.get(key)
            if existing:
                existing.closed = True
                old_task = self._heartbeat_tasks.pop(existing.session_id, None)
                if old_task:
                    old_task.cancel()
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
            session.metadata["connection_state"] = "connected"
            session.metadata["broker_node_id"] = self._node_id
            self._sessions_by_key[key] = session
            self._sessions_by_id[resolved_session_id] = session
            self._store_session_cache(session)

        # Start heartbeat outside the lock so the task is independent.
        self._start_heartbeat(resolved_session_id)
        logger.info(
            "CoderAI broker registered provider=%s client=%s session_id=%s node=%s",
            provider_id, client_id, resolved_session_id, self._node_id,
        )
        return session

    async def unregister(self, session_id: str) -> None:
        # Cancel heartbeat first – no more TTL refreshes after this point.
        self._stop_heartbeat(session_id)
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
            # Write closed tombstone so all cluster nodes see offline immediately.
            self._mark_session_offline_cache(session.provider_id, session.client_id)
            logger.info(
                "CoderAI broker unregistered provider=%s client=%s session_id=%s",
                session.provider_id, session.client_id, session.session_id,
            )

    async def touch(
        self,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> Optional[CoderAISession]:
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
            return session

    # ------------------------------------------------------- session queries

    async def get_session(
        self, provider_id: str, client_id: Optional[str] = None
    ) -> Optional[CoderAISession]:
        """Return the local CoderAISession if this node owns the WebSocket, else None."""
        async with self._lock:
            if client_id:
                session = self._sessions_by_key.get(self._session_key(provider_id, client_id))
                if session and not session.closed:
                    return session
            else:
                candidates = [
                    s for s in self._sessions_by_key.values()
                    if s.provider_id == provider_id and not s.closed
                ]
                if candidates:
                    candidates.sort(key=lambda s: s.last_seen, reverse=True)
                    return candidates[0]

        # Not local – check the shared cache to report remote status to callers.
        snapshot = await self.get_session_snapshot(provider_id, client_id)
        if snapshot and snapshot.get("connected"):
            node = (snapshot.get("metadata") or {}).get("broker_node_id", "unknown")
            logger.debug(
                "CoderAI session provider=%s is connected on remote node %s",
                provider_id, node,
            )
        return None

    async def list_sessions(self) -> list[Dict[str, Any]]:
        """Return all known sessions across the cluster (from shared cache + local)."""
        merged: Dict[str, Dict[str, Any]] = {}

        # Pull all sessions written by any cluster node via the shared index.
        index = self._cache.broker_get(self._session_index_key()) or []
        if isinstance(index, list):
            for meta_key in index:
                stored = self._cache.broker_get(meta_key)
                if not stored or not isinstance(stored, dict):
                    continue
                sid = stored.get("session_id") or meta_key
                merged[sid] = {
                    "session_id": stored.get("session_id"),
                    "provider_id": stored.get("provider_id"),
                    "client_id": stored.get("client_id"),
                    "connected_at": stored.get("connected_at"),
                    "last_seen": stored.get("last_seen"),
                    "metadata": stored.get("metadata") or {},
                    "capabilities": stored.get("capabilities") or {},
                    "connected": not bool(stored.get("closed")),
                }

        # Local sessions are always authoritative – they have the live WebSocket.
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

    async def get_session_snapshot(
        self, provider_id: str, client_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if client_id:
            # Shared cache is the first source of truth for status queries.
            payload = self._cache.broker_get(self._session_meta_key(provider_id, client_id))
            if payload and isinstance(payload, dict):
                payload["connected"] = not bool(payload.get("closed"))
                return payload
            # Fall back to local in-memory (e.g. cache miss on first heartbeat).
            async with self._lock:
                local = self._sessions_by_key.get(self._session_key(provider_id, client_id))
                if local:
                    return {
                        "session_id": local.session_id,
                        "provider_id": local.provider_id,
                        "client_id": local.client_id,
                        "connected_at": local.connected_at,
                        "last_seen": local.last_seen,
                        "closed": local.closed,
                        "metadata": dict(local.metadata),
                        "capabilities": dict(local.capabilities),
                        "connected": not local.closed,
                    }
            return None

        candidates = [s for s in await self.list_sessions() if s.get("provider_id") == provider_id]
        if not candidates:
            return None
        candidates.sort(key=lambda s: s.get("last_seen") or 0, reverse=True)
        return candidates[0]

    # -------------------------------------------------- request / reply flow

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

    async def send_request(
        self,
        provider_id: str,
        op: str,
        payload: Dict[str, Any],
        timeout: float = 300.0,
        client_id: Optional[str] = None,
        owner_user_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        snapshot = await self.get_session_snapshot(provider_id, client_id)
        # Allow a fallback where the client_id itself is the provider_id.
        if (not snapshot or not snapshot.get("connected")) and client_id:
            fallback = await self.get_session_snapshot(client_id, client_id)
            fb_meta = (fallback or {}).get("metadata") or {}
            if fallback and fallback.get("connected") and fb_meta.get("owner_user_id") == owner_user_id:
                snapshot = fallback
                provider_id = snapshot.get("provider_id") or provider_id
        if not snapshot or not snapshot.get("connected"):
            raise RuntimeError(f"No active CoderAI broker session for provider '{provider_id}'")
        if owner_user_id != ((snapshot.get("metadata") or {}).get("owner_user_id")):
            raise RuntimeError(
                f"No active CoderAI broker session for provider '{provider_id}' owned by the current principal"
            )

        request_id = f"broker_{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        stream_queue: asyncio.Queue | None = asyncio.Queue() if payload.get("stream") else None
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

        # Fast path: the WebSocket lives on this node.
        # Slow path: enqueue in the shared cache; the owning node drains it.
        target_node_id = (snapshot.get("metadata") or {}).get("broker_node_id")
        async with self._lock:
            local_session = self._sessions_by_id.get(snapshot["session_id"])
        use_local_fast_path = bool(
            local_session
            and not local_session.closed
            and target_node_id == self._node_id
        )

        resolved_client_id = snapshot.get("client_id") or client_id

        try:
            if use_local_fast_path:
                await local_session.websocket.send_text(json.dumps(envelope))
                logger.debug(
                    "CoderAI broker fast-path op=%s provider=%s request_id=%s",
                    op, provider_id, request_id,
                )
            else:
                self._cache.broker_push(
                    self._request_queue_key(snapshot["session_id"]),
                    envelope,
                    ttl=REQUEST_TTL_SECONDS,
                )
                logger.debug(
                    "CoderAI broker queued op=%s provider=%s target_node=%s request_id=%s",
                    op, provider_id, target_node_id, request_id,
                )

            async def wait_reply() -> Dict[str, Any]:
                if use_local_fast_path:
                    return await asyncio.wait_for(future, timeout=timeout)

                # Slow path: poll the shared cache for the reply.
                deadline = time.time() + timeout
                last_liveness = time.time()
                while time.time() < deadline:
                    reply = self._cache.broker_get(self._reply_key(request_id))
                    if reply is not None:
                        self._cache.broker_delete(self._reply_key(request_id))
                        return reply
                    if future.done():
                        return future.result()
                    # Periodically verify the session is still alive on the remote node.
                    now = time.time()
                    if now - last_liveness >= LIVENESS_CHECK_INTERVAL:
                        live = self._cache.broker_get(
                            self._session_meta_key(provider_id, resolved_client_id)
                        )
                        if live is None:
                            raise RuntimeError(
                                f"CoderAI session for provider '{provider_id}' expired while waiting for reply"
                            )
                        if live.get("closed"):
                            raise RuntimeError(
                                f"CoderAI session for provider '{provider_id}' went offline while waiting for reply"
                            )
                        last_liveness = now
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
        """Block-pop the next request for this session from the shared queue."""
        return await asyncio.to_thread(
            self._cache.broker_blocking_pop,
            self._request_queue_key(session_id),
            timeout,
        )

    async def publish_response(self, message: Dict[str, Any]) -> None:
        request_id = message.get("request_id")
        if not request_id:
            return
        event = message.get("event")
        if event in {"chunk", "progress", "output", "log", "data", "done", "completed"}:
            await self._publish_stream_response(message)
            return
        await self._record_request_metric(request_id, message)
        # Write to shared cache so the requesting node (possibly remote) can poll it.
        self._cache.broker_set(self._reply_key(request_id), message, ttl=REPLY_TTL_SECONDS)
        # Also resolve any local Future for the fast-path case.
        await self.resolve_response(message)

    async def _publish_stream_response(self, message: Dict[str, Any]) -> None:
        request_id = message.get("request_id")
        async with self._lock:
            pending = self._pending.get(request_id)
            queue = pending.stream_queue if pending else None

        if queue is not None:
            # Fast path: local asyncio.Queue for this instance's pending request.
            pending.event_log.append(message)
            if message.get("event") in {"done", "completed"} and not pending.future.done():
                await self._record_request_metric(request_id, message)
                pending.future.set_result(message)
            else:
                await queue.put(message)
            return

        # Slow path: push chunk to the shared cache list for the remote requester.
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

        # Slow path: poll the shared cache list.
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
            snap_sid = (pending.request_snapshot or {}).get("session_id")
            if snap_sid and snap_sid != session_id:
                continue
            if not pending.future.done():
                pending.future.set_exception(RuntimeError(error))
            async with self._lock:
                self._pending.pop(request_id, None)


broker = CoderAIBroker()
