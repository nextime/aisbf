from __future__ import annotations

import json
import logging
import time
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from aisbf.coderai_broker import broker
from aisbf.coderai_registry import validate_coderai_registration_token


router = APIRouter()
logger = logging.getLogger(__name__)


async def _coderai_broker_websocket_impl(websocket: WebSocket, scope_name: str):
    provider_id = websocket.query_params.get("provider_id") or websocket.headers.get("x-coderai-provider-id") or "coderai"
    client_id = websocket.query_params.get("client_id") or websocket.headers.get("x-coderai-client-id") or f"anon-{int(time.time())}"
    username = websocket.query_params.get("username") or websocket.headers.get("x-coderai-username") or scope_name
    presented_token = websocket.query_params.get("registration_token") or websocket.headers.get("x-coderai-registration-token")
    valid, owner_user_id, provider_config, error = validate_coderai_registration_token(provider_id, presented_token, username=username)
    if not valid:
        await websocket.close(code=1008, reason=error or "registration rejected")
        return
    await websocket.accept()
    expected_scope = scope_name
    session = await broker.register(websocket, provider_id, client_id, metadata={"source": "websocket", "owner_user_id": owner_user_id, "username": username, "scope_name": expected_scope, "proxy_scheme": websocket.url.scheme})

    try:
        await websocket.send_text(json.dumps({
            "v": 1,
            "event": "registered",
            "session_id": session.session_id,
            "provider_id": session.provider_id,
            "client_id": session.client_id,
            "username": username,
            "scope_name": expected_scope,
            "accepted": True,
        }))
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                message = json.loads(raw)
                op = message.get("op")
                if op == "register":
                    payload = message.get("payload") or {}
                    payload_token = payload.get("registration_token") or message.get("registration_token")
                    if payload_token and payload_token != presented_token:
                        await websocket.send_text(json.dumps({
                            "v": 1,
                            "request_id": message.get("request_id"),
                            "status": "error",
                            "error": "Registration token mismatch",
                        }))
                        continue
                    capabilities = payload.get("capabilities") or message.get("capabilities") or {}
                    metadata = {
                        "endpoint": payload.get("endpoint"),
                        "transport": payload.get("transport"),
                        "studio_endpoints": payload.get("studio_endpoints") or [],
                        "hardware": payload.get("hardware") or {},
                        "gpus": payload.get("gpus") or ((payload.get("hardware") or {}).get("gpus")) or [],
                        "gpu_count": payload.get("gpu_count") or ((payload.get("hardware") or {}).get("gpu_count")),
                        "total_vram_mb": payload.get("total_vram_mb") or ((payload.get("hardware") or {}).get("total_vram_mb")),
                        "available_vram_mb": payload.get("available_vram_mb") or ((payload.get("hardware") or {}).get("available_vram_mb")),
                        "owner_user_id": owner_user_id,
                        "username": username,
                        "scope_name": expected_scope,
                        "proxy_scheme": websocket.url.scheme,
                    }
                    await broker.touch(session.session_id, metadata=metadata, capabilities=capabilities)
                    await websocket.send_text(json.dumps({
                        "v": 1,
                        "request_id": message.get("request_id"),
                        "status": "ok",
                        "payload": {
                            "accepted": True,
                            "session_id": session.session_id,
                            "provider_id": session.provider_id,
                            "client_id": session.client_id,
                            "owner_user_id": owner_user_id,
                            "username": username,
                            "scope_name": expected_scope,
                            "expires_at": int(time.time()) + 86400,
                        },
                    }))
                    continue
                if op == "heartbeat":
                    await broker.touch(session.session_id, metadata=message.get("payload") or {})
                    await websocket.send_text(json.dumps({
                        "v": 1,
                        "request_id": message.get("request_id"),
                        "status": "ok",
                        "event": "heartbeat",
                        "payload": {"ts": int(time.time())},
                    }))
                    continue
                await broker.touch(session.session_id)
                await broker.publish_response(message)
            except asyncio.TimeoutError:
                queued = await broker.consume_request(session.session_id, timeout=1)
                if queued is not None:
                    await websocket.send_text(json.dumps(queued))
                await broker.touch(session.session_id, metadata={"proxy_scheme": websocket.url.scheme, "username": username, "scope_name": expected_scope})
                continue
    except WebSocketDisconnect:
        logger.info(f"CoderAI broker disconnected provider={provider_id} client={client_id}")
    except Exception as e:
        logger.error(f"CoderAI broker websocket error: {e}", exc_info=True)
    finally:
        await broker.unregister(session.session_id)
        await broker.fail_session_requests(session.session_id, f"CoderAI session '{session.session_id}' disconnected")


@router.websocket("/api/coderai/wss")
async def coderai_broker_websocket_global(websocket: WebSocket):
    await _coderai_broker_websocket_impl(websocket, "global")


@router.websocket("/api/u/{username}/coderai/wss")
async def coderai_broker_websocket_user(websocket: WebSocket, username: str):
    await _coderai_broker_websocket_impl(websocket, username)


@router.get("/api/coderai/broker/sessions")
async def coderai_broker_sessions():
    return {"sessions": await broker.list_sessions()}


@router.get("/api/coderai/broker/providers/{provider_id}/status")
async def coderai_broker_status(provider_id: str, client_id: Optional[str] = Query(default=None)):
    session = await broker.get_session(provider_id, client_id)
    if not session:
        snapshot = await broker.get_session_snapshot(provider_id, client_id)
        if not snapshot:
            return JSONResponse(status_code=404, content={"connected": False, "provider_id": provider_id, "client_id": client_id})
        snapshot["provider_id"] = provider_id
        snapshot["client_id"] = snapshot.get("client_id") or client_id
        return JSONResponse(status_code=200, content=snapshot)
    return {
        "connected": True,
        "provider_id": session.provider_id,
        "client_id": session.client_id,
        "session_id": session.session_id,
        "connected_at": session.connected_at,
        "last_seen": session.last_seen,
        "metadata": dict(session.metadata),
        "capabilities": dict(session.capabilities),
    }
