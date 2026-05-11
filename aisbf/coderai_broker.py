"""
CoderAI broker and session registry for NAT-friendly outbound connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class BrokerPlaceholderWebSocket:
    async def send_text(self, payload: str):
        raise RuntimeError("CoderAI broker session is offline and cannot accept requests")


@dataclass
class PendingCoderAIRequest:
    future: asyncio.Future
    created_at: float


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


class CoderAIBroker:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._sessions_by_key: Dict[str, CoderAISession] = {}
        self._sessions_by_id: Dict[str, CoderAISession] = {}
        self._pending: Dict[str, PendingCoderAIRequest] = {}
        self._state_path = Path.home() / '.aisbf' / 'coderai_broker_sessions.json'
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_persisted_sessions()

    @staticmethod
    def _session_key(provider_id: str, client_id: str) -> str:
        return f"{provider_id}:{client_id}"

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
        }

    def _persist_sessions_locked(self) -> None:
        payload = {
            "sessions": [
                self._serialize_session(session)
                for session in self._sessions_by_id.values()
                if not session.closed
            ],
            "updated_at": time.time(),
        }
        with open(self._state_path, 'w') as f:
            json.dump(payload, f, indent=2)

    def _load_persisted_sessions(self) -> None:
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path) as f:
                payload = json.load(f)
        except Exception as e:
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
                closed=True,
            )
            session.metadata.setdefault("persisted", True)
            session.metadata.setdefault("connection_state", "disconnected")
            key = self._session_key(provider_id, client_id)
            self._sessions_by_key[key] = session
            self._sessions_by_id[session_id] = session

    async def register(self, websocket: WebSocket, provider_id: str, client_id: str, metadata: Optional[Dict[str, Any]] = None, capabilities: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> CoderAISession:
        async with self._lock:
            key = self._session_key(provider_id, client_id)
            existing = self._sessions_by_key.get(key)
            if existing:
                existing.closed = True
                self._sessions_by_id.pop(existing.session_id, None)
            resolved_session_id = session_id or f"coderai_{uuid.uuid4().hex}"
            session = CoderAISession(
                session_id=resolved_session_id,
                provider_id=provider_id,
                client_id=client_id,
                websocket=websocket,
                metadata=dict(metadata or {}),
                capabilities=dict(capabilities or {}),
            )
            session.closed = False
            session.metadata.setdefault("connection_state", "connected")
            session.metadata["persisted"] = True
            self._sessions_by_key[key] = session
            self._sessions_by_id[resolved_session_id] = session
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
            self._persist_sessions_locked()
            logger.info(f"CoderAI broker unregistered session provider={session.provider_id} client={session.client_id} session_id={session.session_id}")

    async def touch(self, session_id: str, metadata: Optional[Dict[str, Any]] = None, capabilities: Optional[Dict[str, Any]] = None) -> Optional[CoderAISession]:
        async with self._lock:
            session = self._sessions_by_id.get(session_id)
            if not session:
                return None
            session.last_seen = time.time()
            if metadata:
                session.metadata.update(metadata)
            if capabilities:
                session.capabilities = dict(capabilities)
            self._persist_sessions_locked()
            return session

    async def get_session(self, provider_id: str, client_id: Optional[str] = None) -> Optional[CoderAISession]:
        async with self._lock:
            if client_id:
                session = self._sessions_by_key.get(self._session_key(provider_id, client_id))
                return session if session and not session.closed else None
            candidates = [session for session in self._sessions_by_key.values() if session.provider_id == provider_id and not session.closed]
            if not candidates:
                return None
            candidates.sort(key=lambda session: session.last_seen, reverse=True)
            return candidates[0]

    async def list_sessions(self) -> list[Dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "session_id": session.session_id,
                    "provider_id": session.provider_id,
                    "client_id": session.client_id,
                    "connected_at": session.connected_at,
                    "last_seen": session.last_seen,
                    "metadata": dict(session.metadata),
                    "capabilities": dict(session.capabilities),
                    "connected": not session.closed,
                }
                for session in self._sessions_by_id.values()
            ]

    async def get_session_snapshot(self, provider_id: str, client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        async with self._lock:
            session = self._sessions_by_key.get(self._session_key(provider_id, client_id)) if client_id else None
            if session is None:
                candidates = [item for item in self._sessions_by_key.values() if item.provider_id == provider_id]
                if not candidates:
                    return None
                candidates.sort(key=lambda item: item.last_seen, reverse=True)
                session = candidates[0]
            return self._serialize_session(session) | {"connected": not session.closed}

    async def send_request(self, provider_id: str, op: str, payload: Dict[str, Any], timeout: float = 300.0, client_id: Optional[str] = None, owner_user_id: Optional[int] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = await self.get_session(provider_id, client_id)
        if not session:
            raise RuntimeError(f"No active CoderAI broker session for provider '{provider_id}'")
        if owner_user_id != session.metadata.get('owner_user_id'):
            raise RuntimeError(f"No active CoderAI broker session for provider '{provider_id}' owned by the current principal")

        request_id = f"broker_{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        envelope = {
            "v": 1,
            "op": op,
            "request_id": request_id,
            "provider_id": provider_id,
            "client_id": session.client_id,
            "payload": payload,
        }
        if extra:
            envelope.update(extra)

        async with self._lock:
            self._pending[request_id] = PendingCoderAIRequest(future=future, created_at=time.time())

        try:
            await session.websocket.send_text(json.dumps(envelope))
            logger.debug(f"CoderAI broker sent op={op} provider={provider_id} client={session.client_id} request_id={request_id}")
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

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
