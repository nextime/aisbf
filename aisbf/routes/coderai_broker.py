from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import JSONResponse

from aisbf.coderai_broker import broker
from aisbf.coderai_registry import validate_coderai_registration_token


router = APIRouter()
logger = logging.getLogger(__name__)


async def _broker_refresh_models(provider_id: str, user_id: Optional[int]) -> None:
    """Fetch and cache the model list for a provider that just connected via broker."""
    try:
        from aisbf.app.model_cache import fetch_provider_models, invalidate_provider_cache
        from aisbf.config import config as aisbf_config
        # Always bypass the cache so a reconnect or re-register produces a live fetch,
        # not a 24-hour stale snapshot.
        invalidate_provider_cache(provider_id, user_id)
        models = await fetch_provider_models(provider_id, aisbf_config, user_id=user_id)
        logger.info(
            "CoderAI broker model refresh: provider=%s user=%s models=%d",
            provider_id, user_id, len(models),
        )
    except Exception:
        logger.warning(
            "CoderAI broker model refresh failed for provider=%s user=%s",
            provider_id, user_id, exc_info=True,
        )


def _coderai_register_payload(
    provider_id: str,
    client_id: str,
    username: str,
    owner_user_id: Optional[int],
    scope_name: str,
) -> dict:
    return {
        "v": 1,
        "event": "registered",
        "provider_id": provider_id,
        "client_id": client_id,
        "username": username,
        "scope_name": scope_name,
        "accepted": True,
        "owner_user_id": owner_user_id,
        "expires_at": int(time.time()) + 86400,
    }


def _extract_register_metadata(
    payload: dict,
    owner_user_id: Optional[int],
    username: str,
    scope_name: str,
    proxy_scheme: str,
) -> dict:
    hardware = payload.get("hardware") or {}
    return {
        "endpoint": payload.get("endpoint"),
        "transport": payload.get("transport"),
        "studio_endpoints": payload.get("studio_endpoints") or [],
        "hardware": hardware,
        "gpus": payload.get("gpus") or hardware.get("gpus") or [],
        "gpu_count": payload.get("gpu_count") or hardware.get("gpu_count"),
        "total_vram_mb": payload.get("total_vram_mb") or hardware.get("total_vram_mb"),
        "available_vram_mb": payload.get("available_vram_mb") or hardware.get("available_vram_mb"),
        "owner_user_id": owner_user_id,
        "username": username,
        "scope_name": scope_name,
        "proxy_scheme": proxy_scheme,
    }


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

    # Client speaks first: wait for op=register before creating the session.
    # This ensures the session is stored with full capability and hardware metadata
    # from the very beginning rather than via a follow-up touch().
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="registration timeout: expected op=register")
        return
    first_msg = json.loads(raw)
    if first_msg.get("op") != "register":
        await websocket.close(code=1008, reason=f"expected op=register, got {first_msg.get('op')!r}")
        return
    first_payload = first_msg.get("payload") or {}
    payload_token = first_payload.get("registration_token") or first_msg.get("registration_token")
    if payload_token and payload_token != presented_token:
        await websocket.close(code=1008, reason="registration token mismatch")
        return

    capabilities = first_payload.get("capabilities") or first_msg.get("capabilities") or {}
    metadata = _extract_register_metadata(first_payload, owner_user_id, username, expected_scope, websocket.url.scheme)

    session = await broker.register(
        websocket, provider_id, client_id,
        metadata=metadata, capabilities=capabilities,
    )

    # Respond to op=register with event=registered.
    registered_payload = _coderai_register_payload(session.provider_id, session.client_id, username, owner_user_id, expected_scope)
    registered_payload.update({"session_id": session.session_id, "status": "ok", "request_id": first_msg.get("request_id")})
    await websocket.send_text(json.dumps(registered_payload))
    _gpu_names = ", ".join(
        g.get("name", "?") for g in (metadata.get("gpus") or [])
    ) or "none"
    logger.info(
        "CoderAI broker registered provider=%s client=%s session_id=%s scope=%s"
        " gpu_count=%s gpus=[%s] total_vram_mb=%s available_vram_mb=%s",
        provider_id, client_id, session.session_id, expected_scope,
        metadata.get("gpu_count"), _gpu_names,
        metadata.get("total_vram_mb"), metadata.get("available_vram_mb"),
    )

    # Populate the model cache in the background now that the session is live.
    asyncio.create_task(_broker_refresh_models(session.provider_id, owner_user_id))

    async def _drain_broker_queue() -> None:
        while True:
            queued = await broker.consume_request(session.session_id, timeout=1)
            if queued is not None:
                await websocket.send_text(json.dumps(queued))

    queue_task = asyncio.create_task(_drain_broker_queue())
    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            op = message.get("op")
            if op == "register":
                # Re-registration during an active session (e.g. after model reload).
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
                new_caps = payload.get("capabilities") or message.get("capabilities") or {}
                new_meta = _extract_register_metadata(payload, owner_user_id, username, expected_scope, websocket.url.scheme)
                await broker.touch(session.session_id, metadata=new_meta, capabilities=new_caps)
                re_payload = _coderai_register_payload(session.provider_id, session.client_id, username, owner_user_id, expected_scope)
                re_payload.update({"session_id": session.session_id, "status": "ok", "request_id": message.get("request_id")})
                await websocket.send_text(json.dumps(re_payload))
                asyncio.create_task(_broker_refresh_models(session.provider_id, owner_user_id))
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
    except WebSocketDisconnect:
        logger.info(f"CoderAI broker disconnected provider={provider_id} client={client_id}")
    except Exception as e:
        logger.error(f"CoderAI broker websocket error: {e}", exc_info=True)
    finally:
        queue_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await queue_task
        await broker.unregister(session.session_id)
        await broker.fail_session_requests(session.session_id, f"CoderAI session '{session.session_id}' disconnected")


@router.websocket("/api/coderai/wss")
async def coderai_broker_websocket_global(websocket: WebSocket):
    await _coderai_broker_websocket_impl(websocket, "global")


@router.websocket("/api/u/{username}/coderai/wss")
async def coderai_broker_websocket_user(websocket: WebSocket, username: str):
    await _coderai_broker_websocket_impl(websocket, username)


@router.post("/api/coderai/register")
async def coderai_register_global(body: dict = Body(default={})):  # nosec B008
    provider_id = body.get("provider_id") or "coderai"
    client_id = body.get("client_id") or f"anon-{int(time.time())}"
    username = body.get("username") or "global"
    presented_token = body.get("registration_token")
    valid, owner_user_id, _provider_config, error = validate_coderai_registration_token(provider_id, presented_token, username=username)
    if not valid:
        raise HTTPException(status_code=403, detail=error or "registration rejected")
    return _coderai_register_payload(provider_id, client_id, username, owner_user_id, "global")


@router.post("/api/u/{username}/coderai/register")
async def coderai_register_user(username: str, body: dict = Body(default={})):  # nosec B008
    provider_id = body.get("provider_id") or "coderai"
    client_id = body.get("client_id") or f"anon-{int(time.time())}"
    presented_token = body.get("registration_token")
    effective_username = body.get("username") or username
    valid, owner_user_id, _provider_config, error = validate_coderai_registration_token(provider_id, presented_token, username=effective_username)
    if not valid:
        raise HTTPException(status_code=403, detail=error or "registration rejected")
    return _coderai_register_payload(provider_id, client_id, effective_username, owner_user_id, effective_username)


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
