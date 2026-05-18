from fastapi import APIRouter, Request, Form, Query, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response, StreamingResponse
from typing import Optional
import json, logging, os, time, re, asyncio
from pathlib import Path
from datetime import datetime, timedelta
from aisbf.database import DatabaseRegistry
from aisbf.database import _hash_password as _db_hash_password
from aisbf import __version__
from aisbf.app.templates import url_for, get_base_url
from aisbf.app.startup import (_reload_global_config, _apply_condense_defaults_provider,
    _apply_condense_defaults_rotation, _providers_json_path, _rotations_json_path,
    _autoselect_json_path, get_aisbf_config_path)
from aisbf.routes.auth import require_dashboard_auth, require_api_auth, require_api_admin, require_admin
from aisbf.studio_services import studio_service
import httpx


def _dashboard_studio_user_scope(request: Request, username: str) -> tuple[str, Optional[int]]:
    auth_check = require_dashboard_auth(request)
    if auth_check:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_username = request.session.get('username')
    user_id = request.session.get('user_id')
    is_config_admin = request.session.get('role') == 'admin' and user_id is None
    if current_username != username and not is_config_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return "user", user_id

router = APIRouter()
_config = None
_templates = None

logger = logging.getLogger(__name__)


@router.get("/admin/api/cached-models")
async def admin_cached_models(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse(studio_service.get_cached_models())


@router.get("/dashboard/api/studio/cached-models")
async def dashboard_studio_cached_models(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse(studio_service.get_cached_models())


@router.get("/admin/api/tokens")
async def admin_tokens(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse([])
    db = DatabaseRegistry.get_config_database()
    return JSONResponse(db.get_user_api_tokens(user_id))


@router.get("/dashboard/api/studio/tokens")
async def dashboard_studio_tokens(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse([])
    db = DatabaseRegistry.get_config_database()
    return JSONResponse(db.get_user_api_tokens(user_id))


@router.get("/admin/api/characters")
async def admin_characters(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse(studio_service.list_characters("admin", None))


@router.get("/dashboard/api/studio/characters")
async def dashboard_studio_characters(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({"characters": studio_service.list_characters("admin", None)})


@router.get("/admin/api/characters/{name}")
async def admin_character_detail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    item = studio_service.get_character("admin", None, name)
    if not item:
        raise HTTPException(status_code=404, detail="Character not found")
    return JSONResponse(item)


@router.get("/dashboard/api/studio/characters/{name}")
async def dashboard_studio_character_detail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    item = studio_service.get_character("admin", None, name)
    if not item:
        raise HTTPException(status_code=404, detail="Character not found")
    return JSONResponse(item)


@router.delete("/admin/api/characters/{name}")
async def admin_character_delete(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_character("admin", None, name)
    return JSONResponse({"success": True})


@router.delete("/dashboard/api/studio/characters/{name}")
async def dashboard_studio_character_delete(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_character("admin", None, name)
    return JSONResponse({"success": True})


@router.get("/admin/api/characters/{name}/thumbnail")
async def admin_character_thumbnail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    payload = studio_service.get_character_thumbnail_bytes("admin", None, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/dashboard/api/studio/characters/{name}/thumbnail")
async def dashboard_studio_character_thumbnail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    payload = studio_service.get_character_thumbnail_bytes("admin", None, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/admin/api/environments")
async def admin_environments(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse(studio_service.list_environments("admin", None))


@router.get("/dashboard/api/studio/environments")
async def dashboard_studio_environments(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({"environments": studio_service.list_environments("admin", None)})


@router.get("/admin/api/environments/{name}")
async def admin_environment_detail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    item = studio_service.get_environment("admin", None, name)
    if not item:
        raise HTTPException(status_code=404, detail="Environment not found")
    return JSONResponse(item)


@router.get("/dashboard/api/studio/environments/{name}")
async def dashboard_studio_environment_detail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    item = studio_service.get_environment("admin", None, name)
    if not item:
        raise HTTPException(status_code=404, detail="Environment not found")
    return JSONResponse(item)


@router.delete("/admin/api/environments/{name}")
async def admin_environment_delete(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_environment("admin", None, name)
    return JSONResponse({"success": True})


@router.delete("/dashboard/api/studio/environments/{name}")
async def dashboard_studio_environment_delete(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_environment("admin", None, name)
    return JSONResponse({"success": True})


@router.get("/admin/api/environments/{name}/thumbnail")
async def admin_environment_thumbnail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    payload = studio_service.get_environment_thumbnail_bytes("admin", None, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/dashboard/api/studio/environments/{name}/thumbnail")
async def dashboard_studio_environment_thumbnail(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    payload = studio_service.get_environment_thumbnail_bytes("admin", None, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/admin/api/voices")
async def admin_voices(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse(studio_service.list_voices("admin", None))


@router.get("/dashboard/api/studio/audio/voices")
async def dashboard_studio_voices(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({"voices": studio_service.list_voices("admin", None)})


@router.delete("/admin/api/voices/{name}")
async def admin_voice_delete(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_voice("admin", None, name)
    return JSONResponse({"success": True})


@router.delete("/dashboard/api/studio/audio/voices/{name}")
async def dashboard_studio_voice_delete(request: Request, name: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_voice("admin", None, name)
    return JSONResponse({"success": True})


@router.get("/dashboard/api/studio/pipelines/step-types")
async def dashboard_studio_pipeline_step_types(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({"step_types": studio_service.pipeline_step_types()})


@router.get("/dashboard/api/studio/function-bindings")
async def dashboard_studio_function_bindings(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({
        "bindings": studio_service.list_function_bindings("admin", None),
        "definitions": studio_service.function_binding_definitions(),
    })


@router.put("/dashboard/api/studio/function-bindings/{binding_id}")
async def dashboard_studio_function_binding_save(request: Request, binding_id: str, body: dict):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    bindings = studio_service.save_function_binding("admin", None, binding_id, body.get("roles") or {})
    return JSONResponse({"bindings": bindings, "binding_id": binding_id})


@router.delete("/dashboard/api/studio/function-bindings/{binding_id}")
async def dashboard_studio_function_binding_delete(request: Request, binding_id: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    bindings = studio_service.delete_function_binding("admin", None, binding_id)
    return JSONResponse({"bindings": bindings, "binding_id": binding_id})


@router.get("/dashboard/api/studio/pipelines/custom")
async def dashboard_studio_pipeline_custom_list(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({"pipelines": studio_service.list_pipelines("admin", None)})


@router.post("/dashboard/api/studio/pipelines/custom")
async def dashboard_studio_pipeline_custom_create(request: Request, body: dict):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    return JSONResponse({"pipeline": studio_service.save_pipeline("admin", None, body)})


@router.put("/dashboard/api/studio/pipelines/custom/{pipeline_id}")
async def dashboard_studio_pipeline_custom_update(request: Request, pipeline_id: str, body: dict):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    payload = dict(body)
    payload["id"] = pipeline_id
    return JSONResponse({"pipeline": studio_service.save_pipeline("admin", None, payload)})


@router.delete("/dashboard/api/studio/pipelines/custom/{pipeline_id}")
async def dashboard_studio_pipeline_custom_delete(request: Request, pipeline_id: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    studio_service.delete_pipeline("admin", None, pipeline_id)
    return JSONResponse({"success": True})


@router.post("/dashboard/api/studio/pipelines/custom/{pipeline_id}/run")
async def dashboard_studio_pipeline_custom_run(request: Request, pipeline_id: str, body: dict):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    pipeline = studio_service.get_pipeline("admin", None, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    payload = dict(pipeline)
    payload.setdefault("seed_input", body.get("input") or "")
    payload.setdefault("seed_story", body.get("story") or "")
    return JSONResponse(studio_service.run_pipeline("admin", None, payload))


def _parse_studio_model_id(model: str):
    """Parse studio model IDs → (kind, source_id, target_id).

    <provider>/<model>         → ('provider', provider, model)
    rotation/<name>            → ('rotation', name, name)
    autoselect[ion]/<name>     → ('autoselect', name, name)
    provider/<src>/<tgt>       → ('provider', src, tgt)  # legacy 3-part form
    """
    parts = (model or '').split('/', 2)
    if not parts or not parts[0]:
        return None, None, None
    kind = parts[0].lower()
    if kind in ('rotation',):
        name = parts[1] if len(parts) > 1 else ''
        return 'rotation', name, name
    if kind in ('autoselect', 'autoselection'):
        name = parts[1] if len(parts) > 1 else ''
        return 'autoselect', name, name
    if kind == 'provider' and len(parts) == 3:
        return 'provider', parts[1], parts[2]
    if len(parts) >= 2:
        return 'provider', parts[0], '/'.join(parts[1:])
    return None, None, None


@router.post("/dashboard/api/studio/chat/completions")
async def dashboard_studio_chat_completions(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
    body = await request.json()
    kind, source_id, target_id = _parse_studio_model_id(body.get('model') or '')
    if not kind:
        raise HTTPException(status_code=400, detail="model required in format provider/source/target, rotation/name, or autoselect/name")
    body_dict = dict(body)
    if kind == 'rotation':
        handler = RotationHandler(user_id=None)
        body_dict['model'] = source_id
        return await handler.handle_rotation_request(source_id, body_dict, None, None)
    if kind == 'autoselect':
        handler = AutoselectHandler(user_id=None)
        body_dict['model'] = source_id
        return await handler.handle_autoselect_request(source_id, body_dict, None, None)
    handler = RequestHandler(user_id=None)
    body_dict['model'] = target_id
    return await handler.handle_chat_completion(request, source_id, body_dict)


@router.post("/dashboard/api/studio/u/{username}/chat/completions")
async def dashboard_user_studio_chat_completions(request: Request, username: str):
    scope, user_id = _dashboard_studio_user_scope(request, username)
    from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
    body = await request.json()
    kind, source_id, target_id = _parse_studio_model_id(body.get('model') or '')
    if not kind:
        raise HTTPException(status_code=400, detail="model required in format provider/source/target, rotation/name, or autoselect/name")
    body_dict = dict(body)
    if kind == 'rotation':
        handler = RotationHandler(user_id=user_id)
        body_dict['model'] = source_id
        return await handler.handle_rotation_request(source_id, body_dict, user_id, None)
    if kind == 'autoselect':
        handler = AutoselectHandler(user_id=user_id)
        body_dict['model'] = source_id
        return await handler.handle_autoselect_request(source_id, body_dict, user_id, None)
    handler = RequestHandler(user_id=user_id)
    body_dict['model'] = target_id
    return await handler.handle_chat_completion(request, source_id, body_dict)


@router.get("/dashboard/api/studio/u/{username}/characters")
async def dashboard_user_studio_characters(request: Request, username: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse({"characters": studio_service.list_characters(scope, owner_id)})


@router.get("/dashboard/api/studio/u/{username}/characters/{name}")
async def dashboard_user_studio_character_detail(request: Request, username: str, name: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    item = studio_service.get_character(scope, owner_id, name)
    if not item:
        raise HTTPException(status_code=404, detail="Character not found")
    return JSONResponse(item)


@router.post("/dashboard/api/studio/u/{username}/characters/extract")
async def dashboard_user_studio_character_extract(request: Request, username: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse(studio_service.save_character(scope, owner_id, body))


@router.post("/dashboard/api/studio/u/{username}/characters/generate")
async def dashboard_user_studio_character_generate(request: Request, username: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    payload = dict(body)
    payload.setdefault("images", [])
    return JSONResponse(studio_service.save_character(scope, owner_id, payload))


@router.get("/dashboard/api/studio/u/{username}/characters/{name}/thumbnail")
async def dashboard_user_studio_character_thumbnail(request: Request, username: str, name: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    payload = studio_service.get_character_thumbnail_bytes(scope, owner_id, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/dashboard/api/studio/u/{username}/environments")
async def dashboard_user_studio_environments(request: Request, username: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse({"environments": studio_service.list_environments(scope, owner_id)})


@router.get("/dashboard/api/studio/u/{username}/environments/{name}")
async def dashboard_user_studio_environment_detail(request: Request, username: str, name: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    item = studio_service.get_environment(scope, owner_id, name)
    if not item:
        raise HTTPException(status_code=404, detail="Environment not found")
    return JSONResponse(item)


@router.post("/dashboard/api/studio/u/{username}/environments/extract")
async def dashboard_user_studio_environment_extract(request: Request, username: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse(studio_service.save_environment(scope, owner_id, body))


@router.post("/dashboard/api/studio/u/{username}/environments/generate")
async def dashboard_user_studio_environment_generate(request: Request, username: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    payload = dict(body)
    payload.setdefault("images", [])
    return JSONResponse(studio_service.save_environment(scope, owner_id, payload))


@router.get("/dashboard/api/studio/u/{username}/environments/{name}/thumbnail")
async def dashboard_user_studio_environment_thumbnail(request: Request, username: str, name: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    payload = studio_service.get_environment_thumbnail_bytes(scope, owner_id, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/dashboard/api/studio/u/{username}/audio/voices")
async def dashboard_user_studio_audio_voices(request: Request, username: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse({"voices": studio_service.list_voices(scope, owner_id)})


@router.post("/dashboard/api/studio/u/{username}/audio/voices")
async def dashboard_user_studio_audio_voice_create(request: Request, username: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    form = await request.form()
    payload = {
        "name": str(form.get("name") or f"voice-{int(time.time())}"),
        "description": str(form.get("description") or ""),
        "samples": [],
    }
    return JSONResponse(studio_service.save_voice(scope, owner_id, payload))


@router.post("/dashboard/api/studio/u/{username}/audio/voices/extract")
async def dashboard_user_studio_audio_voice_extract(request: Request, username: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    payload = {
        "name": body.get("name") or f"voice-{int(time.time())}",
        "description": body.get("description", ""),
        "quote": body.get("transcript", ""),
        "samples": body.get("samples", []),
    }
    return JSONResponse(studio_service.save_voice(scope, owner_id, payload))


@router.delete("/dashboard/api/studio/u/{username}/audio/voices/{name}")
async def dashboard_user_studio_audio_voice_delete(request: Request, username: str, name: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    studio_service.delete_voice(scope, owner_id, name)
    return JSONResponse({"success": True})


@router.get("/dashboard/api/studio/u/{username}/pipelines/step-types")
async def dashboard_user_studio_pipeline_step_types(request: Request, username: str):
    _dashboard_studio_user_scope(request, username)
    return JSONResponse({"step_types": studio_service.pipeline_step_types()})


@router.get("/dashboard/api/studio/u/{username}/function-bindings")
async def dashboard_user_studio_function_bindings(request: Request, username: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse({
        "bindings": studio_service.list_function_bindings(scope, owner_id),
        "definitions": studio_service.function_binding_definitions(),
    })


@router.put("/dashboard/api/studio/u/{username}/function-bindings/{binding_id}")
async def dashboard_user_studio_function_binding_save(request: Request, username: str, binding_id: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    bindings = studio_service.save_function_binding(scope, owner_id, binding_id, body.get("roles") or {})
    return JSONResponse({"bindings": bindings, "binding_id": binding_id})


@router.delete("/dashboard/api/studio/u/{username}/function-bindings/{binding_id}")
async def dashboard_user_studio_function_binding_delete(request: Request, username: str, binding_id: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    bindings = studio_service.delete_function_binding(scope, owner_id, binding_id)
    return JSONResponse({"bindings": bindings, "binding_id": binding_id})


@router.get("/dashboard/api/studio/u/{username}/pipelines/custom")
async def dashboard_user_studio_pipeline_custom_list(request: Request, username: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse({"pipelines": studio_service.list_pipelines(scope, owner_id)})


@router.post("/dashboard/api/studio/u/{username}/pipelines/custom")
async def dashboard_user_studio_pipeline_custom_create(request: Request, username: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    return JSONResponse({"pipeline": studio_service.save_pipeline(scope, owner_id, body)})


@router.put("/dashboard/api/studio/u/{username}/pipelines/custom/{pipeline_id}")
async def dashboard_user_studio_pipeline_custom_update(request: Request, username: str, pipeline_id: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    payload = dict(body)
    payload["id"] = pipeline_id
    return JSONResponse({"pipeline": studio_service.save_pipeline(scope, owner_id, payload)})


@router.delete("/dashboard/api/studio/u/{username}/pipelines/custom/{pipeline_id}")
async def dashboard_user_studio_pipeline_custom_delete(request: Request, username: str, pipeline_id: str):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    studio_service.delete_pipeline(scope, owner_id, pipeline_id)
    return JSONResponse({"success": True})


@router.post("/dashboard/api/studio/u/{username}/pipelines/custom/{pipeline_id}/run")
async def dashboard_user_studio_pipeline_custom_run(request: Request, username: str, pipeline_id: str, body: dict):
    scope, owner_id = _dashboard_studio_user_scope(request, username)
    pipeline = studio_service.get_pipeline(scope, owner_id, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    payload = dict(pipeline)
    payload.setdefault("seed_input", body.get("input") or "")
    payload.setdefault("seed_story", body.get("story") or "")
    return JSONResponse(studio_service.run_pipeline(scope, owner_id, payload))

def init(config, templates):
    global _config, _templates
    _config = config
    _templates = templates

# User API token management routes
@router.get("/dashboard/user/tokens", response_class=HTMLResponse)
async def dashboard_user_tokens(request: Request):
    """User API token management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()

    # Get user API tokens
    user_tokens = db.get_user_api_tokens(user_id)
    
    # Convert datetime objects to strings for JSON serialization
    for token in user_tokens:
        if 'created_at' in token and token['created_at']:
            token['created_at'] = token['created_at'].isoformat() if hasattr(token['created_at'], 'isoformat') else str(token['created_at'])
        if 'last_used' in token and token['last_used']:
            token['last_used'] = token['last_used'].isoformat() if hasattr(token['last_used'], 'isoformat') else str(token['last_used'])

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/user_tokens.html",
        context={
        "request": request,
        "session": request.session,
        "__version__": __version__,
        "user_tokens": user_tokens,
        "user_id": user_id
    }
    )

@router.post("/dashboard/user/tokens")
async def dashboard_user_tokens_create(request: Request, description: str = Form(""), scope: str = Form("api")):
    """Create a new user API token"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if scope not in ('api', 'mcp', 'both'):
        scope = 'api'

    import secrets

    db = DatabaseRegistry.get_config_database()

    # Generate a secure token
    token = secrets.token_urlsafe(32)

    try:
        token_id = db.create_user_api_token(user_id, token, description.strip() or None, scope)
        return JSONResponse({
            "message": "Token created successfully",
            "token": token,
            "token_id": token_id,
            "scope": scope
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/dashboard/user/tokens/{token_id}")
async def dashboard_user_tokens_delete(request: Request, token_id: int):
    """Delete a user API token"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    db = DatabaseRegistry.get_config_database()

    try:
        db.delete_user_api_token(user_id, token_id)
        return JSONResponse(content={"success": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/dashboard/cache-settings", response_class=HTMLResponse)
async def dashboard_user_cache_settings(request: Request):
    """User prompt cache settings page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()
    
    # Get all cache settings for user
    cache_settings = db.get_all_user_cache_settings(user_id)
    
    # Convert datetime objects to strings
    for setting in cache_settings:
        if 'created_at' in setting and setting['created_at']:
            setting['created_at'] = setting['created_at'].isoformat() if hasattr(setting['created_at'], 'isoformat') else str(setting['created_at'])
        if 'updated_at' in setting and setting['updated_at']:
            setting['updated_at'] = setting['updated_at'].isoformat() if hasattr(setting['updated_at'], 'isoformat') else str(setting['updated_at'])
    
    # Get user's providers for dropdown
    user_providers = db.get_user_providers(user_id)

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/cache_settings.html",
        context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "cache_settings": cache_settings,
            "user_providers": user_providers,
            "user_id": user_id
        }
    )

@router.get("/dashboard/api/cache-settings")
async def dashboard_api_get_cache_settings(request: Request):
    """Get logged-in user's cache settings"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()
    
    provider_id = request.query_params.get('provider_id')
    model_name = request.query_params.get('model_name')
    
    if provider_id or model_name:
        # Get specific setting
        setting = db.get_user_cache_settings(user_id, provider_id, model_name)
        # Convert datetime to string if present
        if setting and 'updated_at' in setting and setting['updated_at']:
            setting['updated_at'] = setting['updated_at'].isoformat() if hasattr(setting['updated_at'], 'isoformat') else str(setting['updated_at'])
        return JSONResponse(setting)
    else:
        # Get all settings
        settings = db.get_all_user_cache_settings(user_id)
        # Convert datetime objects to strings
        for setting in settings:
            if 'updated_at' in setting and setting['updated_at']:
                setting['updated_at'] = setting['updated_at'].isoformat() if hasattr(setting['updated_at'], 'isoformat') else str(setting['updated_at'])
            if 'created_at' in setting and setting['created_at']:
                setting['created_at'] = setting['created_at'].isoformat() if hasattr(setting['created_at'], 'isoformat') else str(setting['created_at'])
        return JSONResponse({"settings": settings})

@router.post("/dashboard/api/cache-settings")
async def dashboard_api_set_cache_setting(request: Request):
    """Set logged-in user's cache setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')

    try:
        body = await request.json()
        provider_id = body.get('provider_id')
        model_name = body.get('model_name')
        cache_enabled = body.get('cache_enabled', True)
        
        db = DatabaseRegistry.get_config_database()
        success = db.set_user_cache_setting(user_id, cache_enabled, provider_id, model_name)
        
        if success:
            return JSONResponse({"success": True, "message": "Cache setting updated"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to update setting"})
    except Exception as e:
        logger.error(f"Error setting cache setting: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/dashboard/api/cache-settings")
async def dashboard_api_delete_cache_setting(request: Request):
    """Delete logged-in user's cache setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')

    try:
        provider_id = request.query_params.get('provider_id')
        model_name = request.query_params.get('model_name')
        
        db = DatabaseRegistry.get_config_database()
        success = db.delete_user_cache_setting(user_id, provider_id, model_name)
        
        if success:
            return JSONResponse({"success": True, "message": "Cache setting deleted"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to delete setting"})
    except Exception as e:
        logger.error(f"Error deleting cache setting: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/dashboard/response-cache/stats")
async def dashboard_response_cache_stats(request: Request):
    """Get response cache statistics"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    from aisbf.cache import get_response_cache
    
    try:
        cache = get_response_cache()
        
        if is_admin:
            # Admin sees global stats
            stats = cache.get_stats()
        else:
            # Regular users see their own personal cache impact
            stats = cache.get_user_stats(current_user_id)
            
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Error getting response cache stats: {e}")
        return JSONResponse({
            'enabled': False,
            'hits': 0,
            'misses': 0,
            'hit_rate': 0.0,
            'size': 0,
            'evictions': 0,
            'backend': 'unknown',
            'error': str(e)
        })

@router.get("/dashboard/admin/tiers")
async def dashboard_admin_tiers(request: Request):
    """Admin account tiers management page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tiers = db.get_all_tiers()
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/admin_tiers.html",
        context={
        "request": request,
        "session": request.session,
        "tiers": tiers
    }
    )

# API endpoints for tiers CRUD operations
@router.get("/api/admin/tiers")
async def api_list_tiers(request: Request):
    """List all tiers - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tiers = db.get_all_tiers()
    return JSONResponse(tiers)

@router.get("/api/admin/tiers/{tier_id}")
async def api_get_tier(tier_id: int, request: Request):
    """Get specific tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tier = db.get_tier_by_id(tier_id)
    if not tier:
        return JSONResponse({"error": "Tier not found"}, status_code=404)
    
    return JSONResponse(tier)

@router.post("/api/admin/tiers")
async def api_create_tier(request: Request):
    """Create a new tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        body = await request.json()
        
        tier_id = db.create_tier(
            name=body.get('name'),
            description=body.get('description', ''),
            price_monthly=body.get('price_monthly', 0.0),
            price_yearly=body.get('price_yearly', 0.0),
            max_requests_per_day=body.get('max_requests_per_day', -1),
            max_requests_per_month=body.get('max_requests_per_month', -1),
            max_providers=body.get('max_providers', -1),
            max_rotations=body.get('max_rotations', -1),
            max_autoselections=body.get('max_autoselections', -1),
            max_rotation_models=body.get('max_rotation_models', -1),
            max_autoselection_models=body.get('max_autoselection_models', -1),
            market_fee_percentage=body.get('market_fee_percentage', 10.0),
            is_active=body.get('is_active', True),
            is_visible=body.get('is_visible', True)
        )
        
        return JSONResponse({"success": True, "tier_id": tier_id})
    except Exception as e:
        logger.error(f"Error creating tier: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.put("/api/admin/tiers/{tier_id}")
async def api_update_tier(request: Request, tier_id: int):
    """Update an existing tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        body = await request.json()
        
        # Build update kwargs
        update_kwargs = {}
        if 'name' in body:
            update_kwargs['name'] = body['name']
        if 'description' in body:
            update_kwargs['description'] = body['description']
        if 'price_monthly' in body:
            update_kwargs['price_monthly'] = body['price_monthly']
        if 'price_yearly' in body:
            update_kwargs['price_yearly'] = body['price_yearly']
        if 'max_requests_per_day' in body:
            update_kwargs['max_requests_per_day'] = body['max_requests_per_day']
        if 'max_requests_per_month' in body:
            update_kwargs['max_requests_per_month'] = body['max_requests_per_month']
        if 'max_providers' in body:
            update_kwargs['max_providers'] = body['max_providers']
        if 'max_rotations' in body:
            update_kwargs['max_rotations'] = body['max_rotations']
        if 'max_autoselections' in body:
            update_kwargs['max_autoselections'] = body['max_autoselections']
        if 'max_rotation_models' in body:
            update_kwargs['max_rotation_models'] = body['max_rotation_models']
        if 'max_autoselection_models' in body:
            update_kwargs['max_autoselection_models'] = body['max_autoselection_models']
        if 'market_fee_percentage' in body:
            update_kwargs['market_fee_percentage'] = body['market_fee_percentage']
        if 'is_active' in body:
            update_kwargs['is_active'] = body['is_active']
        if 'is_visible' in body:
            update_kwargs['is_visible'] = body['is_visible']
        
        success = db.update_tier(tier_id, **update_kwargs)
        
        if not success:
            return JSONResponse({"error": "Tier not found or no changes"}, status_code=404)
        
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error updating tier: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.delete("/api/admin/tiers/{tier_id}")
async def api_delete_tier(request: Request, tier_id: int):
    """Delete a tier - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        success = db.delete_tier(tier_id)
        
        if not success:
            return JSONResponse({"error": "Cannot delete default tier or tier not found"}, status_code=400)
        
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error deleting tier: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# Tier form pages
@router.get("/dashboard/admin/tiers/create")
async def dashboard_admin_tier_create(request: Request):
    """Create tier page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/admin_tier_form.html",
        context={
            "request": request,
            "session": request.session,
            "tier": None
        }
    )

@router.get("/dashboard/admin/tiers/edit/{tier_id}")
async def dashboard_admin_tier_edit(request: Request, tier_id: int):
    """Edit tier page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    tier = db.get_tier_by_id(tier_id)
    if not tier:
        return RedirectResponse(url=url_for(request, "/dashboard/admin/tiers"), status_code=303)
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/admin_tier_form.html",
        context={
            "request": request,
            "session": request.session,
            "tier": tier
        }
    )

@router.post("/dashboard/admin/tiers/save")
async def dashboard_admin_tier_save(request: Request):
    """Save tier (create or update)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        form = await request.form()
        tier_id = form.get('tier_id')
        
        tier_data = {
            'name': form.get('name'),
            'description': form.get('description', ''),
            'price_monthly': float(form.get('price_monthly', 0)),
            'price_yearly': float(form.get('price_yearly', 0)),
            'max_requests_per_day': int(form.get('max_requests_per_day', -1)),
            'max_requests_per_month': int(form.get('max_requests_per_month', -1)),
            'max_providers': int(form.get('max_providers', -1)),
            'max_rotations': int(form.get('max_rotations', -1)),
            'max_autoselections': int(form.get('max_autoselections', -1)),
            'max_rotation_models': int(form.get('max_rotation_models', -1)),
            'max_autoselection_models': int(form.get('max_autoselection_models', -1)),
            'market_fee_percentage': float(form.get('market_fee_percentage', 10.0)),
            'is_active': form.get('is_active') == '1',
            'is_visible': form.get('is_visible') == '1'
        }
        
        if tier_id:
            # Update existing tier
            db.update_tier(int(tier_id), **tier_data)
        else:
            # Create new tier
            db.create_tier(**tier_data)
        
        return RedirectResponse(url=url_for(request, "/dashboard/admin/tiers"), status_code=303)
    except Exception as e:
        logger.error(f"Error saving tier: {e}")
        return RedirectResponse(url=url_for(request, "/dashboard/admin/tiers"), status_code=303)

# Currency settings endpoints
@router.get("/api/admin/settings/currency")
async def api_get_currency_settings(request: Request):
    """Get currency settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get currency settings from database
    settings = db.get_currency_settings()
    
    return JSONResponse(settings)

@router.post("/api/admin/settings/currency")
async def api_save_currency_settings(request: Request):
    """Save currency settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        
        db = DatabaseRegistry.get_config_database()
        
        # Save currency settings to database
        db.save_currency_settings(body)
        
        return JSONResponse({"success": True, "message": "Currency settings saved"})
    except Exception as e:
        logger.error(f"Error saving currency settings: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# Payment gateway settings endpoints
@router.get("/api/admin/settings/payment-gateways")
async def api_get_payment_gateways(request: Request):
    """Get payment gateway settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get payment gateway settings from database
    gateways = db.get_payment_gateway_settings()
    
    return JSONResponse(gateways)

@router.post("/api/admin/settings/payment-gateways")
async def api_save_payment_gateways(request: Request):
    """Save payment gateway settings - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        
        db = DatabaseRegistry.get_config_database()
        
        # Save payment gateway settings to database
        db.save_payment_gateway_settings(body)
        
        return JSONResponse({"success": True, "message": "Payment gateway settings saved"})
    except Exception as e:
        logger.error(f"Error saving payment gateway settings: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/api/admin/settings/encryption-key")
async def api_get_encryption_key_status(request: Request):
    """Get encryption key status - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        encryption_key = db.get_encryption_key()
        
        # Check if key is set in database or environment
        env_key = os.getenv('ENCRYPTION_KEY')
        
        if encryption_key:
            source = 'database'
            is_set = True
        elif env_key:
            source = 'environment'
            is_set = True
        else:
            source = 'temporary'
            is_set = False
        
        return JSONResponse({
            "is_set": is_set,
            "source": source
        })
    except Exception as e:
        logger.error(f"Error getting encryption key status: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/api/admin/crypto/prices")
async def api_get_crypto_prices(request: Request):
    """Get crypto prices (BTC, ETH, USDT, USDC) from all enabled sources - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        
        # Get enabled price sources
        with db._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT name, is_enabled
                    FROM crypto_price_sources
                """)
                sources = {row[0].lower(): bool(row[1]) for row in cursor.fetchall()}
            except Exception:
                # Default if table doesn't exist yet
                sources = {'coinbase': True, 'binance': True, 'kraken': True}
        
        # Get currency settings
        currency_settings = db.get_currency_settings()
        currency_code = currency_settings.get('currency_code', 'EUR')
        
        result = {}
        
        # Cache for supported pairs
        supported_pairs_cache = getattr(asyncio, '__pair_cache', {})
        cache_expiry = getattr(asyncio, '__pair_cache_expiry', 0)
        
        if time.time() > cache_expiry:
            supported_pairs_cache = {}
            cache_expiry = time.time() + 86400  # 24 hour cache
            setattr(asyncio, '__pair_cache', supported_pairs_cache)
            setattr(asyncio, '__pair_cache_expiry', cache_expiry)
        
        # Fetch prices for each cryptocurrency
        for crypto_symbol, crypto_name in [('BTC', 'btc'), ('ETH', 'eth'), ('USDT', 'usdt'), ('USDC', 'usdc')]:
            prices = {}
            enabled_prices = []
            cache_key = f"{crypto_symbol}:{currency_code}"
            
            # Coinbase
            if sources.get('coinbase', False):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(f'https://api.coinbase.com/v2/prices/{crypto_symbol}-{currency_code}/spot')
                        if response.status_code == 200:
                            data = response.json()
                            price = float(data['data']['amount'])
                            prices['coinbase'] = price
                            enabled_prices.append(price)
                            supported_pairs_cache[f"coinbase:{cache_key}"] = True
                except Exception as e:
                    supported_pairs_cache[f"coinbase:{cache_key}"] = False
                    logger.debug(f"Coinbase does not support {crypto_symbol}/{currency_code} pair: {e}")
                    prices['coinbase'] = None
            else:
                prices['coinbase'] = None
            
            # Binance
            if sources.get('binance', False):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # Try direct pair first
                        symbol = f"{crypto_symbol}{currency_code}"
                        response = await client.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}')
                        
                        if response.status_code != 200:
                            # Fallback to USDT pair if direct pair not available
                            symbol = f"{crypto_symbol}USDT"
                            response = await client.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}')
                            
                            if response.status_code == 200:
                                # Get USD/EUR rate if needed
                                if currency_code != 'USD':
                                    usd_resp = await client.get('https://api.coinbase.com/v2/prices/USD-EUR/spot')
                                    if usd_resp.status_code == 200:
                                        usd_eur = float(usd_resp.json()['data']['amount'])
                                        data = response.json()
                                        price = float(data['price']) * usd_eur
                                        prices['binance'] = price
                                        enabled_prices.append(price)
                                        supported_pairs_cache[f"binance:{cache_key}"] = "usdt_fallback"
                        else:
                            data = response.json()
                            price = float(data['price'])
                            prices['binance'] = price
                            enabled_prices.append(price)
                            supported_pairs_cache[f"binance:{cache_key}"] = True
                            
                except Exception as e:
                    supported_pairs_cache[f"binance:{cache_key}"] = False
                    logger.debug(f"Binance does not support {crypto_symbol}/{currency_code} pair: {e}")
                    prices['binance'] = None
            else:
                prices['binance'] = None
            
            # Kraken
            if sources.get('kraken', False):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # Kraken symbols
                        kraken_prefix = {
                            'BTC': 'XXBT',
                            'ETH': 'XETH',
                            'USDT': 'USDT',
                            'USDC': 'USDC'
                        }.get(crypto_symbol, crypto_symbol)
                        
                        pair = f"{kraken_prefix}Z{currency_code}"
                        response = await client.get(f'https://api.kraken.com/0/public/Ticker?pair={pair}')
                        
                        if response.status_code == 200:
                            data = response.json()
                            if not data.get('error') and 'result' in data and data['result']:
                                result_key = list(data['result'].keys())[0]
                                price = float(data['result'][result_key]['c'][0])
                                prices['kraken'] = price
                                enabled_prices.append(price)
                                supported_pairs_cache[f"kraken:{cache_key}"] = True
                            else:
                                supported_pairs_cache[f"kraken:{cache_key}"] = False
                except Exception as e:
                    supported_pairs_cache[f"kraken:{cache_key}"] = False
                    logger.debug(f"Kraken does not support {crypto_symbol}/{currency_code} pair: {e}")
                    prices['kraken'] = None
            else:
                prices['kraken'] = None
            
            # Calculate average only if we have valid prices
            if enabled_prices:
                prices['average'] = sum(enabled_prices) / len(enabled_prices)
            else:
                prices['average'] = None
            
            result[crypto_name] = prices
        
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Error getting crypto prices: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/api/admin/crypto/btc-prices")
async def api_get_btc_prices(request: Request):
    """Get BTC prices from all enabled sources - API endpoint (legacy, redirects to /prices)"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        # Call the new endpoint and extract BTC data
        full_response = await api_get_crypto_prices(request)
        if isinstance(full_response, JSONResponse):
            import json
            data = json.loads(full_response.body.decode())
            if 'btc' in data:
                return JSONResponse(data['btc'])
        return full_response
    except Exception as e:
        logger.error(f"Error getting BTC prices: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/api/admin/settings/encryption-key")
async def api_save_encryption_key(request: Request):
    """Save encryption key - API endpoint"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        encryption_key = body.get('encryption_key', '').strip()
        
        if not encryption_key:
            return JSONResponse({"success": False, "error": "Encryption key is required"}, status_code=400)
        
        if len(encryption_key) != 44:
            return JSONResponse({"success": False, "error": "Encryption key must be 44 characters (base64 encoded)"}, status_code=400)
        
        db = DatabaseRegistry.get_config_database()
        success = db.save_encryption_key(encryption_key)
        
        if success:
            logger.info("Encryption key saved to database by admin")
            return JSONResponse({"success": True, "message": "Encryption key saved successfully. Restart server to apply."})
        else:
            return JSONResponse({"success": False, "error": "Failed to save encryption key"}, status_code=500)
    except Exception as e:
        logger.error(f"Error saving encryption key: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/admin/settings/crypto-seeds-reset")
async def api_reset_crypto_seeds(request: Request):
    """Delete all crypto master seeds so they are regenerated on next restart"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check

    try:
        db = DatabaseRegistry.get_config_database()
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM crypto_master_keys")
            deleted = cursor.rowcount
            conn.commit()
        logger.warning(f"Admin reset crypto master seeds: {deleted} rows deleted")
        return JSONResponse({"success": True, "deleted": deleted})
    except Exception as e:
        logger.error(f"Error resetting crypto seeds: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Admin configuration API endpoints
@router.get("/api/admin/config/price-sources")
async def get_price_sources(request: Request):
    """Get crypto price source configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT crypto_type, price_source, api_key, update_interval_seconds, is_enabled
            FROM crypto_price_sources
        """)
        rows = cursor.fetchall()
    
    sources = [
        {
            'crypto_type': row[0],
            'price_source': row[1],
            'api_key': row[2],
            'update_interval': row[3],
            'enabled': bool(row[4])
        }
        for row in rows
    ]
    
    return JSONResponse({'price_sources': sources})


@router.put("/api/admin/payment-system/config/price-sources")
async def update_payment_price_sources(request: Request):
    """Update crypto price source configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            for source in body.get('price_sources', []):
                cursor.execute(f"""
                    UPDATE crypto_price_sources
                    SET price_source = {placeholder},
                        api_key = {placeholder},
                        update_interval_seconds = {placeholder},
                        is_enabled = {placeholder}
                    WHERE crypto_type = {placeholder}
                """, (
                    source['price_source'],
                    source.get('api_key'),
                    source['update_interval'],
                    source['enabled'],
                    source['crypto_type']
                ))
            
            conn.commit()
        
        return JSONResponse({'success': True, 'message': 'Price sources updated'})
    except Exception as e:
        logger.error(f"Error updating price sources: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)

@router.post("/api/admin/config/price-sources")
async def update_price_sources(request: Request):
    """Update crypto price source configuration (legacy endpoint)"""
    return await update_payment_price_sources(request)


@router.get("/api/admin/config/consolidation")
async def get_consolidation_config(request: Request):
    """Get wallet consolidation configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT crypto_type, threshold_amount, admin_address, is_enabled
            FROM crypto_consolidation_settings
        """)
        rows = cursor.fetchall()
    
    settings = [
        {
            'crypto_type': row[0],
            'threshold': float(row[1]),
            'admin_address': row[2],
            'enabled': bool(row[3])
        }
        for row in rows
    ]
    
    return JSONResponse({'consolidation_settings': settings})


@router.put("/api/admin/payment-system/config/consolidation")
async def update_payment_consolidation_config(request: Request):
    """Update wallet consolidation configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        logger.info(f"Received consolidation config update: {body}")
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            # Handle both old format (consolidation_settings array) and new format (btc/eth/usdt/usdc keys)
            if 'consolidation_settings' in body:
                # Old format
                for setting in body['consolidation_settings']:
                    cursor.execute(f"""
                        UPDATE crypto_consolidation_settings
                        SET threshold_amount = {placeholder},
                            admin_address = {placeholder},
                            is_enabled = {placeholder}
                        WHERE crypto_type = {placeholder}
                    """, (
                        setting['threshold'],
                        setting.get('admin_address', ''),
                        setting.get('enabled', True),
                        setting['crypto_type']
                    ))
                    logger.info(f"Updated {setting['crypto_type']} threshold to {setting['threshold']}")
            else:
                # New format - simple key-value pairs
                crypto_map = {
                    'btc': 'BTC',
                    'eth': 'ETH',
                    'usdt': 'USDT',
                    'usdc': 'USDC'
                }
                
                updated_count = 0
                for key, crypto_type in crypto_map.items():
                    if key in body:
                        threshold = float(body[key])
                        
                        # Use UPSERT to handle missing records
                        if db.db_type == 'sqlite':
                            cursor.execute(f"""
                                INSERT INTO crypto_consolidation_settings (crypto_type, threshold_amount, admin_address, is_enabled)
                                VALUES (?, ?, '', 0)
                                ON CONFLICT(crypto_type) DO UPDATE SET threshold_amount = ?
                            """, (crypto_type, threshold, threshold))
                        else:  # MySQL
                            cursor.execute(f"""
                                INSERT INTO crypto_consolidation_settings (crypto_type, threshold_amount, admin_address, is_enabled)
                                VALUES (%s, %s, '', 0)
                                ON DUPLICATE KEY UPDATE threshold_amount = %s
                            """, (crypto_type, threshold, threshold))
                        
                        rows_affected = cursor.rowcount
                        logger.info(f"Upserted {crypto_type} threshold to {threshold}, rows affected: {rows_affected}")
                        updated_count += rows_affected
                
                logger.info(f"Total rows affected: {updated_count}")
            
            conn.commit()
            logger.info("Consolidation settings committed to database")
        
        return JSONResponse({'success': True, 'message': 'Consolidation settings updated'})
    except Exception as e:
        logger.error(f"Error updating consolidation settings: {e}", exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@router.post("/api/admin/config/consolidation")
async def update_consolidation_config(request: Request):
    """Update wallet consolidation configuration (legacy endpoint)"""
    return await update_payment_consolidation_config(request)


@router.get("/api/admin/config/email")
async def get_email_config(request: Request):
    """Get email notification configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get SMTP config
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT smtp_host, smtp_port, smtp_username, from_email, from_name, use_tls
            FROM email_config
            LIMIT 1
        """)
        smtp_row = cursor.fetchone()
        
        # Get notification settings
        cursor.execute("""
            SELECT notification_type, is_enabled, subject_template
            FROM email_notification_settings
        """)
        notif_rows = cursor.fetchall()
    
    smtp_config = None
    if smtp_row:
        smtp_config = {
            'smtp_host': smtp_row[0],
            'smtp_port': smtp_row[1],
            'smtp_username': smtp_row[2],
            'from_email': smtp_row[3],
            'from_name': smtp_row[4],
            'use_tls': bool(smtp_row[5])
        }
    
    notifications = [
        {
            'type': row[0],
            'enabled': bool(row[1]),
            'subject': row[2]
        }
        for row in notif_rows
    ]
    
    return JSONResponse({
        'smtp_config': smtp_config,
        'notifications': notifications
    })


@router.put("/api/admin/payment-system/config/email")
async def update_payment_email_config(request: Request):
    """Update email notification configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            # Update SMTP config
            if 'smtp_config' in body:
                smtp = body['smtp_config']
                
                # Check if _config exists
                cursor.execute("SELECT id FROM email_config LIMIT 1")
                exists = cursor.fetchone()
                
                if exists:
                    cursor.execute(f"""
                        UPDATE email_config
                        SET smtp_host = {placeholder},
                            smtp_port = {placeholder},
                            smtp_username = {placeholder},
                            smtp_password = {placeholder},
                            from_email = {placeholder},
                            from_name = {placeholder},
                            use_tls = {placeholder}
                    """, (
                        smtp['smtp_host'],
                        smtp['smtp_port'],
                        smtp.get('smtp_username'),
                        smtp.get('smtp_password'),
                        smtp['from_email'],
                        smtp.get('from_name'),
                        smtp.get('use_tls', True)
                    ))
                else:
                    cursor.execute(f"""
                        INSERT INTO email_config
                        (smtp_host, smtp_port, smtp_username, smtp_password, from_email, from_name, use_tls)
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                    """, (
                        smtp['smtp_host'],
                        smtp['smtp_port'],
                        smtp.get('smtp_username'),
                        smtp.get('smtp_password'),
                        smtp['from_email'],
                        smtp.get('from_name'),
                        smtp.get('use_tls', True)
                    ))
            
            # Update notification settings
            if 'notifications' in body:
                for notif in body['notifications']:
                    cursor.execute(f"""
                        UPDATE email_notification_settings
                        SET is_enabled = {placeholder},
                            subject_template = {placeholder}
                        WHERE notification_type = {placeholder}
                    """, (
                        notif['enabled'],
                        notif['subject'],
                        notif['type']
                    ))
            
            conn.commit()
        
        return JSONResponse({'success': True, 'message': 'Email configuration updated'})
    except Exception as e:
        logger.error(f"Error updating email configuration: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)

@router.post("/api/admin/config/email")
async def update_email_config(request: Request):
    """Update email notification configuration (legacy endpoint)"""
    return await update_payment_email_config(request)


@router.put("/api/admin/payment-system/config/blockchain")
async def update_payment_blockchain_config(request: Request):
    """Update blockchain monitoring configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            for config in body.get('blockchain_config', []):
                cursor.execute(f"""
                    UPDATE blockchain_monitoring_config
                    SET rpc_url = {placeholder},
                        confirmations_required = {placeholder},
                        scan_interval_seconds = {placeholder},
                        is_enabled = {placeholder}
                    WHERE crypto_type = {placeholder}
                """, (
                    config['rpc_url'],
                    config['confirmations'],
                    config['scan_interval'],
                    config['enabled'],
                    config['crypto_type']
                ))
            
            conn.commit()
        
        return JSONResponse({'success': True, 'message': 'Blockchain monitoring configuration updated'})
    except Exception as e:
        logger.error(f"Error updating blockchain monitoring configuration: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@router.get("/api/admin/scheduler/status")
async def get_scheduler_status(request: Request):
    """Get payment scheduler status"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    if not payment_service:
        return JSONResponse({'error': 'Payment service not initialized'}, status_code=503)
    
    try:
        from aisbf.payments.scheduler import PaymentScheduler
        # Get scheduler from payment service if available
        if hasattr(payment_service, 'scheduler'):
            status = payment_service.scheduler.get_job_status()
            return JSONResponse(status)
        else:
            return JSONResponse({'error': 'Scheduler not available'}, status_code=503)
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@router.post("/api/admin/scheduler/run-job")
async def run_scheduler_job(request: Request):
    """Manually trigger a scheduler job"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    if not payment_service:
        return JSONResponse({'error': 'Payment service not initialized'}, status_code=503)
    
    try:
        body = await request.json()
        job_name = body.get('job_name')
        
        if not job_name:
            return JSONResponse({'error': 'job_name required'}, status_code=400)
        
        if hasattr(payment_service, 'scheduler'):
            await payment_service.scheduler.run_job_now(job_name)
            return JSONResponse({'success': True, 'message': f'Job {job_name} triggered'})
        else:
            return JSONResponse({'error': 'Scheduler not available'}, status_code=503)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Error running scheduler job: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@router.get("/api/admin/payment-system/status")
async def get_payment_system_status(request: Request):
    """Get payment system status including master keys, balances, and payment counts"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check master keys status
            cursor.execute("SELECT COUNT(*) FROM crypto_master_keys")
            master_keys_count = cursor.fetchone()[0]
            
            # Get total crypto balances from user_crypto_wallets
            try:
                cursor.execute("""
                    SELECT crypto_type, SUM(balance_fiat) as total
                    FROM user_crypto_wallets
                    GROUP BY crypto_type
                """)
                balances = {row[0]: float(row[1]) for row in cursor.fetchall()}
                total_balance_usd = sum(balances.values())
            except Exception:
                balances = {}
                total_balance_usd = 0.0
            
            # Get pending payments count from payment_transactions
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM payment_transactions
                    WHERE status = 'pending'
                """)
                pending_count = cursor.fetchone()[0]
            except Exception:
                pending_count = 0
            
            # Get failed payments count from payment_transactions
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM payment_transactions
                    WHERE status = 'failed'
                """)
                failed_count = cursor.fetchone()[0]
            except Exception:
                failed_count = 0
        
        return JSONResponse({
            'master_keys_initialized': master_keys_count > 0,
            'master_keys_count': master_keys_count,
            'total_balance_usd': total_balance_usd,
            'pending_payments': pending_count,
            'failed_payments': failed_count
        })
    except Exception as e:
        logger.error(f"Error getting payment system status: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)


@router.get("/api/admin/payment-system/config")
async def get_payment_system_config(request: Request):
    """Get all payment system configuration"""
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    
    try:
        db = DatabaseRegistry.get_config_database()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get price sources
            try:
                cursor.execute("""
                    SELECT name, api_type, endpoint_url, api_key, is_enabled
                    FROM crypto_price_sources
                """)
                price_sources = {
                    row[0].lower(): bool(row[4])
                    for row in cursor.fetchall()
                }
            except Exception:
                price_sources = {
                    'coinbase': True,
                    'binance': True,
                    'kraken': True
                }
            
            # Get blockchain monitoring config (default values)
            blockchain_config = {
                'mode': 'api',
                'polling_interval': 60
            }
            
            # Get email notification config (default values)
            email_config = {
                'payment_success': True,
                'payment_failed': True,
                'subscription_upgraded': True,
                'subscription_downgraded': True,
                'subscription_cancelled': True,
                'payment_retry': True
            }
            
            # Get consolidation settings
            try:
                cursor.execute("""
                    SELECT crypto_type, threshold_amount
                    FROM crypto_consolidation_settings
                """)
                consolidation = {
                    row[0].lower(): float(row[1])
                    for row in cursor.fetchall()
                }
            except Exception:
                consolidation = {
                    'btc': 0.01,
                    'eth': 0.1,
                    'usdt': 100,
                    'usdc': 100
                }
        
        return JSONResponse({
            'price_sources': price_sources,
            'blockchain': blockchain_config,
            'email_notifications': email_config,
            'consolidation': consolidation
        })
    except Exception as e:
        logger.error(f"Error getting payment system config: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)



@router.get("/dashboard/admin/payment-settings")
async def dashboard_admin_payment_settings(request: Request):
    """Admin payment system settings page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/admin_payment_settings.html",
        context={
            "request": request,
            "session": request.session,
            "currency_symbol": DatabaseRegistry.get_config_database().get_currency_settings().get('currency_symbol', '$'),
            "market_settings": DatabaseRegistry.get_config_database().get_market_settings(),
        }
    )

@router.get("/api/admin/settings/market")
async def api_get_market_settings(request: Request):
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    db = DatabaseRegistry.get_config_database()
    return JSONResponse(db.get_market_settings())

@router.post("/api/admin/settings/market")
async def api_save_market_settings(request: Request):
    auth_check = require_api_admin(request)
    if auth_check:
        return auth_check
    db = DatabaseRegistry.get_config_database()
    try:
        body = await request.json()
        db.save_market_settings({
            'enabled': bool(body.get('enabled', False)),
            'allow_user_publish': bool(body.get('allow_user_publish', True)),
            'allow_admin_publish': bool(body.get('allow_admin_publish', True)),
            'allow_import': bool(body.get('allow_import', True)),
        })
        return JSONResponse({'success': True, 'message': 'Market settings saved'})
    except Exception as e:
        logger.error(f"Error saving market settings: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)

@router.get("/dashboard/pricing")
async def dashboard_pricing(request: Request):
    """Pricing plans page for users"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    tiers = db.get_visible_tiers()
    current_tier = db.get_user_tier(user_id)

    # Mark the most expensive non-free tier as recommended if none marked
    paid_tiers = [t for t in tiers if not t.get('is_default')]
    if paid_tiers:
        most_expensive = max(paid_tiers, key=lambda t: t['price_monthly'])
        for t in tiers:
            t['is_recommended'] = (not t.get('is_default') and t['id'] == most_expensive['id'])

    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)

    # Get currency settings
    currency_settings = db.get_currency_settings()
    currency_symbol = currency_settings.get('currency_symbol', '$')

    # Get wallet balance for display
    wallet_balance = None
    has_stripe_card = False
    if user_id:
        try:
            from aisbf.payments.wallet.manager import WalletManager
            wallet_manager = WalletManager(db)
            wallet = await wallet_manager.get_wallet(user_id)
            wallet_balance = float(wallet.get('balance', 0))
        except Exception:
            wallet_balance = 0.0
        payment_methods = db.get_user_payment_methods(user_id)
        has_stripe_card = any(m.get('type') == 'stripe' and m.get('is_active') for m in payment_methods)

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/pricing.html",
        context={
            "request": request,
            "session": request.session,
            "tiers": tiers,
            "current_tier": current_tier,
            "enabled_gateways": enabled_gateways,
            "currency_symbol": currency_symbol,
            "wallet_balance": wallet_balance,
            "has_stripe_card": has_stripe_card,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )


@router.post("/dashboard/subscribe/free")
async def dashboard_subscribe_free(request: Request):
    """Downgrade to the free tier"""
    from fastapi.responses import JSONResponse

    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    free_tiers = [t for t in db.get_visible_tiers() if t.get('is_default')]
    if not free_tiers:
        return JSONResponse({"error": "No free tier configured"}, status_code=404)
    free_tier = free_tiers[0]

    ph = db.placeholder
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE user_subscriptions SET status = 'cancelled' WHERE user_id = {ph} AND status = 'active'",
            (user_id,)
        )
        conn.commit()
    db.set_user_tier(user_id, free_tier['id'])
    return JSONResponse({"success": True, "message": "Downgraded to free plan. Changes are effective immediately."})


def _create_subscription_record(db, user_id: int, tier_id: int):
    """Cancel existing active subscriptions and create a new one for the given tier."""
    from datetime import datetime, timedelta
    ph = db.placeholder
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE user_subscriptions SET status = 'cancelled' WHERE user_id = {ph} AND status = 'active'",
            (user_id,)
        )
        start_date = datetime.now()
        end_date = start_date + timedelta(days=30)
        cursor.execute(f"""
            INSERT INTO user_subscriptions (user_id, tier_id, status, start_date, next_billing_date)
            VALUES ({ph}, {ph}, 'active', {ph}, {ph})
        """, (user_id, tier_id, start_date, end_date))
        conn.commit()

@router.post("/dashboard/subscribe/{tier_id}")
async def dashboard_subscribe_tier(request: Request, tier_id: int):
    """Subscribe/upgrade to a paid tier using wallet or saved Stripe card"""
    from fastapi.responses import JSONResponse
    from decimal import Decimal

    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    target_tier = db.get_tier_by_id(tier_id)
    if not target_tier or not target_tier.get('is_active'):
        return JSONResponse({"error": "Invalid or inactive plan"}, status_code=404)

    current_tier = db.get_user_tier(user_id)
    if current_tier and current_tier['id'] == tier_id:
        return JSONResponse({"error": "You are already on this plan"}, status_code=400)

    tier_price = float(target_tier['price_monthly'])

    # Get wallet balance
    from aisbf.payments.wallet.manager import WalletManager
    wallet_manager = WalletManager(db)
    try:
        wallet = await wallet_manager.get_wallet(user_id)
        wallet_balance = float(wallet.get('balance', 0))
    except Exception:
        wallet_balance = 0.0

    if wallet_balance >= tier_price:
        # Pay with wallet
        try:
            await wallet_manager.debit_wallet(user_id, Decimal(str(tier_price)), {
                "description": f"Plan upgrade to {target_tier['name']}",
                "payment_gateway": "wallet",
                "gateway_transaction_id": None,
                "payment_method_id": None,
            })
        except Exception as e:
            return JSONResponse({"error": f"Failed to debit wallet: {str(e)}"}, status_code=400)
        _create_subscription_record(db, user_id, tier_id)
        db.set_user_tier(user_id, tier_id)
        return JSONResponse({
            "success": True,
            "message": f"Upgraded to {target_tier['name']}. ${tier_price:.2f} deducted from your wallet."
        })

    # Wallet insufficient — check Stripe
    payment_methods = db.get_user_payment_methods(user_id)
    stripe_methods = [m for m in payment_methods if m.get('type') == 'stripe' and m.get('is_active')]

    if not stripe_methods:
        shortage = tier_price - wallet_balance
        return JSONResponse({
            "error": "insufficient_funds",
            "wallet_balance": wallet_balance,
            "required": tier_price,
            "shortage": round(shortage, 2),
            "message": (
                f"Your wallet balance (${wallet_balance:.2f}) is insufficient. "
                f"You need ${shortage:.2f} more. Top up your wallet or add a card."
            ),
        }, status_code=402)

    # Charge the default (or first) Stripe card for the exact plan amount
    default_method = next((m for m in stripe_methods if m.get('is_default')), stripe_methods[0])
    if payment_service is None:
        return JSONResponse({"error": "Payment service unavailable"}, status_code=503)

    result = await payment_service.stripe_handler.auto_charge(
        user_id,
        Decimal(str(tier_price)),
        default_method['identifier'],
        description=f"Subscription upgrade to {target_tier['name']}",
        metadata={'user_id': str(user_id), 'tier_id': str(tier_id), 'tier_name': target_tier['name'], 'amount': str(tier_price)},
        off_session=False
    )
    if not result.get('success'):
        return JSONResponse({"error": result.get('error', 'Card charge failed')}, status_code=402)

    _create_subscription_record(db, user_id, tier_id)
    db.set_user_tier(user_id, tier_id)
    return JSONResponse({
        "success": True,
        "message": f"Upgraded to {target_tier['name']}. ${tier_price:.2f} charged to your saved card."
    })


@router.get("/dashboard/usage", response_class=HTMLResponse)
async def dashboard_usage(request: Request):
    """Usage and quota page for users"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    from datetime import datetime, timedelta
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    current_tier = db.get_user_tier(user_id) if user_id else None
    all_tiers = db.get_visible_tiers()

    # Quota limits from tier
    max_requests_per_day = current_tier.get('max_requests_per_day', -1) if current_tier else -1
    max_requests_per_month = current_tier.get('max_requests_per_month', -1) if current_tier else -1
    max_providers = current_tier.get('max_providers', -1) if current_tier else -1
    max_rotations = current_tier.get('max_rotations', -1) if current_tier else -1
    max_autoselections = current_tier.get('max_autoselections', -1) if current_tier else -1

    # Actual usage
    requests_today = 0
    requests_month = 0
    tokens_24h = 0
    providers_count = 0
    rotations_count = 0
    autoselects_count = 0

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Exact reset timestamps as JS-compatible millisecond Unix timestamps
    daily_reset_ts  = int((today_start + timedelta(days=1)).timestamp() * 1000)
    monthly_reset_ts = int((month_start + timedelta(days=32)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    if user_id:
        token_usage = db.get_user_token_usage(user_id)
        day_ago = now - timedelta(days=1)

        for row in token_usage:
            ts = row['timestamp']
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    continue
            if ts >= today_start:
                requests_today += 1
            if ts >= month_start:
                requests_month += 1
            if ts >= day_ago:
                tokens_24h += int(row.get('token_count', 0) or 0)

        providers_count = len(db.get_user_providers(user_id))
        rotations_count = len(db.get_user_rotations(user_id))
        autoselects_count = len(db.get_user_autoselects(user_id))

    upgrade_tiers = [
        t for t in all_tiers
        if not t.get('is_default') and (
            current_tier is None or t['price_monthly'] > current_tier.get('price_monthly', 0)
        )
    ]

    currency_settings = db.get_currency_settings()
    currency_symbol = currency_settings.get('currency_symbol', '$')

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/usage.html",
        context={
            "request": request,
            "session": request.session,
            "current_tier": current_tier,
            "max_requests_per_day": max_requests_per_day,
            "max_requests_per_month": max_requests_per_month,
            "max_providers": max_providers,
            "max_rotations": max_rotations,
            "max_autoselections": max_autoselections,
            "requests_today": requests_today,
            "requests_month": requests_month,
            "tokens_24h": tokens_24h,
            "providers_count": providers_count,
            "rotations_count": rotations_count,
            "autoselects_count": autoselects_count,
            "upgrade_tiers": upgrade_tiers,
            "currency_symbol": currency_symbol,
            "daily_reset_ts": daily_reset_ts,
            "monthly_reset_ts": monthly_reset_ts,
        }
    )


@router.get("/dashboard/subscription")
async def dashboard_subscription(request: Request):
    """User subscription status and payment methods management page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    # Get user subscription info
    subscription = db.get_user_subscription(user_id)
    current_tier = db.get_user_tier(user_id)
    payment_methods = db.get_user_payment_methods(user_id)
    
    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)
    
    # Get currency settings
    currency_settings = db.get_currency_settings()
    currency_symbol = currency_settings.get('currency_symbol', '$')
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/subscription.html",
        context={
        "request": request,
        "session": request.session,
        "subscription": subscription,
        "current_tier": current_tier,
        "payment_methods": payment_methods,
        "enabled_gateways": enabled_gateways,
        "currency_symbol": currency_symbol
    }
    )

@router.get("/dashboard/wallet", response_class=HTMLResponse)
async def dashboard_wallet(request: Request):
    """User wallet dashboard page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        db = DatabaseRegistry.get_config_database()
        user_id = request.session.get('user_id')

        from aisbf.payments.wallet.manager import WalletManager
        wallet_manager = WalletManager(db)
        wallet = await wallet_manager.get_wallet(user_id)

        all_gateways = db.get_payment_gateway_settings()
        enabled_gateways = {k: v for k, v in all_gateways.items() if v.get('enabled', False)}

        # Get user's saved Stripe credit cards for auto top-up
        stripe_cards = [m for m in db.get_user_payment_methods(user_id)
                        if m.get('type') == 'stripe' or m.get('gateway') == 'stripe']

        # Determine if there are upgrade plans available
        current_tier = db.get_user_tier(user_id)
        all_tiers = db.get_visible_tiers()
        upgrade_tiers = [
            t for t in all_tiers
            if not t.get('is_default') and (
                current_tier is None or t['price_monthly'] > current_tier.get('price_monthly', 0)
            )
        ]

        return _templates.TemplateResponse(
            request=request,
            name="dashboard/wallet.html",
            context={
                "request": request,
                "wallet": wallet,
                "enabled_gateways": enabled_gateways,
                "currency_symbol": db.get_currency_settings().get('currency_symbol', '$'),
                "stripe_cards": stripe_cards,
                "upgrade_tiers": upgrade_tiers,
            }
        )
    except ImportError:
        return HTMLResponse("Wallet functionality not available", status_code=503)
    except Exception as e:
        logger.error(f"Failed to load wallet page: {e}")
        return _templates.TemplateResponse(request=request, name="dashboard/error.html", context={
            "request": request,
            "error": "Failed to load wallet. Please try again later."
        }, status_code=500)

@router.post("/dashboard/wallet/topup")
async def dashboard_wallet_topup(request: Request):
    """Session-authenticated wallet top-up — supports all admin-enabled gateways."""
    from fastapi.responses import JSONResponse
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    method = (body.get('payment_method') or '').lower()
    amount = body.get('amount')

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid amount"}, status_code=400)

    if amount < 5 or amount > 500:
        return JSONResponse({"error": "Amount must be between $5 and $500"}, status_code=400)

    db = DatabaseRegistry.get_config_database()
    gateways = db.get_payment_gateway_settings()
    gw = gateways.get(method, {})
    if not gw.get('enabled', False):
        return JSONResponse({"error": f"Payment method '{method}' is not enabled"}, status_code=400)

    # Crypto: generate per-user HD wallet address
    crypto_methods = {'bitcoin': 'btc', 'ethereum': 'eth', 'usdt': 'usdt', 'usdc': 'usdc'}
    if method in crypto_methods:
        crypto_type = crypto_methods[method]
        ps = getattr(request.app.state, 'payment_service', None)
        if ps is None:
            return JSONResponse({"error": "Payment service unavailable"}, status_code=503)
        try:
            address = await ps.wallet_manager.get_or_create_user_address(user_id, crypto_type)
        except Exception as e:
            import traceback as _tb
            logger.error(f"Crypto address generation error: {e!r}\n{_tb.format_exc()}")
            return JSONResponse({"error": "Could not generate deposit address"}, status_code=503)
        db.record_dashboard_event(
            event_type='wallet_topup_started',
            path=request.url.path,
            user_id=user_id,
            username=request.session.get('username'),
            method=request.method,
            metadata={'payment_method': method, 'amount': amount, 'crypto_type': crypto_type},
        )
        return JSONResponse({
            "type": "crypto",
            "method": method,
            "address": address,
            "amount": amount,
            "network": gw.get('network', ''),
            "confirmations": gw.get('confirmations', 3),
        })

    # Stripe: create checkout session (hosted redirect flow)
    if method == 'stripe':
        try:
            db.record_dashboard_event(
                event_type='wallet_topup_started',
                path=request.url.path,
                user_id=user_id,
                username=request.session.get('username'),
                method=request.method,
                metadata={'payment_method': method, 'amount': amount},
            )
            payment_service = getattr(request.app.state, 'payment_service', None)
            if not payment_service or not hasattr(payment_service, 'stripe_handler'):
                return JSONResponse({"error": "Stripe payment service unavailable"}, status_code=503)
            from decimal import Decimal
            base = get_base_url(request)
            result = await payment_service.stripe_handler.create_topup_checkout_session(
                user_id,
                Decimal(str(amount)),
                success_url=f"{base}/dashboard/wallet?topup=success",
                cancel_url=f"{base}/dashboard/wallet?topup=cancelled",
            )
            if not result.get('success'):
                return JSONResponse({"error": result.get('error', 'Stripe error')}, status_code=502)
            return JSONResponse({"type": "stripe", "checkout_url": result['checkout_url']})
        except Exception as e:
            logger.error(f"Stripe top-up error: {e}")
            return JSONResponse({"error": "Stripe checkout failed. Please try again."}, status_code=502)

    # PayPal: create order
    if method == 'paypal':
        try:
            db.record_dashboard_event(
                event_type='wallet_topup_started',
                path=request.url.path,
                user_id=user_id,
                username=request.session.get('username'),
                method=request.method,
                metadata={'payment_method': method, 'amount': amount},
            )
            payment_service = getattr(request.app.state, 'payment_service', None)
            if not payment_service or not hasattr(payment_service, 'paypal_handler'):
                return JSONResponse({"error": "PayPal payment service unavailable"}, status_code=503)
            from decimal import Decimal
            result = await payment_service.paypal_handler.create_topup_order(user_id, Decimal(str(amount)))
            if not result.get('success'):
                logger.error(f"PayPal top-up error: {result.get('error')}")
                return JSONResponse({"error": "PayPal checkout failed. Please try again."}, status_code=502)
            return JSONResponse({"type": "paypal", "approval_url": result['approval_url']})
        except Exception as e:
            logger.error(f"PayPal top-up error: {e}")
            return JSONResponse({"error": "PayPal checkout failed. Please try again."}, status_code=502)

    return JSONResponse({"error": f"Unsupported payment method: {method}"}, status_code=400)


@router.get("/dashboard/wallet/transactions")
async def dashboard_wallet_transactions(request: Request, limit: int = 50, offset: int = 0):
    """Session-authenticated wallet transaction history (used by the wallet dashboard page)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    try:
        from aisbf.payments.wallet.manager import WalletManager
        db = DatabaseRegistry.get_config_database()
        wallet_manager = WalletManager(db)
        transactions = await wallet_manager.get_transactions(user_id, limit=limit, offset=offset)
        return transactions
    except Exception as e:
        logger.error(f"Failed to load wallet transactions: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Failed to load transactions"}, status_code=500)


@router.put("/dashboard/wallet/auto-topup")
async def dashboard_wallet_auto_topup(request: Request):
    """Session-authenticated auto-topup configuration (used by the wallet dashboard page)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')
    try:
        body = await request.json()
        from aisbf.payments.wallet.manager import WalletManager
        db = DatabaseRegistry.get_config_database()
        wallet_manager = WalletManager(db)
        result = await wallet_manager.configure_auto_topup(user_id, body)
        from fastapi.responses import JSONResponse
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Failed to configure auto-topup: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Failed to save settings"}, status_code=500)


@router.get("/dashboard/billing")
async def dashboard_billing(request: Request):
    """User payment transaction history page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    # Get user payment methods
    payment_methods = db.get_user_payment_methods(user_id)

    # Get payment transactions
    transactions = db.get_user_payment_transactions(user_id)

    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)

    # Get user wallet
    currency_settings = db.get_currency_settings()
    currency_code = currency_settings.get('currency_code', 'EUR')
    try:
        from aisbf.payments.wallet.manager import WalletManager
        wallet_manager = WalletManager(db)
        wallet = await wallet_manager.get_wallet(user_id)
    except Exception:
        wallet = {'balance': '0.00', 'currency_code': currency_code, 'auto_topup_enabled': False}

    # Get Stripe publishable key
    stripe_publishable_key = ""
    if 'stripe' in gateways and gateways['stripe'].get('enabled'):
        stripe_publishable_key = gateways['stripe'].get('publishable_key', '')

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/billing.html",
        context={
        "request": request,
        "session": request.session,
        "payment_methods": payment_methods,
        "transactions": transactions,
        "enabled_gateways": enabled_gateways,
        "wallet": wallet,
        "currency_symbol": currency_settings.get('currency_symbol', '$'),
        "stripe_publishable_key": stripe_publishable_key,
    }
    )
