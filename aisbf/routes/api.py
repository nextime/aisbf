from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, Response, FileResponse
from typing import Optional
import time, logging, os, json
from pathlib import Path
from aisbf.models import ChatCompletionRequest
from aisbf.database import DatabaseRegistry
from aisbf.app.model_cache import get_provider_models, _refresh_provider_usage_if_stale, _background_tasks

router = APIRouter()
_config = None
_get_user_handler = None
_rotation_handler = None
_request_handler = None

def init(config, get_user_handler_fn, rotation_handler):
    global _config, _get_user_handler, _rotation_handler, _request_handler
    _config = config
    _get_user_handler = get_user_handler_fn
    _rotation_handler = rotation_handler
    _request_handler = get_user_handler_fn('request', None)

logger = logging.getLogger(__name__)

def parse_provider_from_model(model: str) -> tuple[str, str]:
    if '/' in model:
        parts = model.split('/', 1)
        return parts[0], parts[1]
    return None, model

@router.get("/")
async def root():
    return {
        "message": "AI Proxy Server is running",
        "providers": list(_config.providers.keys()),
        "rotations": list(_config.rotations.keys()),
        "autoselect": list(_config.autoselect.keys())
    }

@router.get("/favicon.ico")
async def favicon():
    search_paths = [
        Path(__file__).parent.parent.parent / 'static' / 'extension' / 'icons' / 'icon16.png',
        Path(__file__).parent.parent.parent / 'static' / 'favicon.ico',
        Path.home() / '.local' / 'share' / 'aisbf' / 'static' / 'extension' / 'icons' / 'icon16.png',
    ]
    for favicon_path in search_paths:
        if favicon_path.exists():
            return FileResponse(
                path=favicon_path,
                media_type="image/png" if favicon_path.suffix == '.png' else "image/x-icon"
            )
    return Response(status_code=204)

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/api/v1/models/{model_id}")
async def v1_get_model(model_id: str, request: Request):
    all_models_response = await v1_list_all_models(request)
    all_models = all_models_response.get("data", [])
    for model in all_models:
        if model.get("id") == model_id:
            return model
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

@router.post("/api/v1/completions")
async def v1_completions(request: Request):
    body = await request.body()
    data = json.loads(body) if body else {}
    prompt = data.get("prompt", "")
    model = data.get("model", "")
    max_tokens = data.get("max_tokens", 2048)
    temperature = data.get("temperature", 1.0)
    messages = [{"role": "user", "content": prompt}]
    chat_request = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    return await v1_chat_completions(chat_request, request)

@router.post("/api/v1/chat/completions")
async def v1_chat_completions(request: Request, body: ChatCompletionRequest):
    logger.info(f"=== V1 CHAT COMPLETION REQUEST ===")
    logger.info(f"Model: {body.model}")
    provider_id, actual_model = parse_provider_from_model(body.model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    logger.info(f"Parsed provider: {provider_id}, model: {actual_model}")
    body_dict = body.model_dump()

    if provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        body_dict['model'] = actual_model
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = _get_user_handler('autoselect', user_id)
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)

    if provider_id == "rotation" or provider_id == "rotations":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        body_dict['model'] = actual_model
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = _get_user_handler('rotation', user_id)
        return await handler.handle_rotation_request(actual_model, body_dict, user_id, token_id)

    if provider_id == "autoselections":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        body_dict['model'] = actual_model
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = _get_user_handler('autoselect', user_id)
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)

    if provider_id not in _config.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body_dict['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    if body.stream:
        return await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
    else:
        return await handler.handle_chat_completion(request, provider_id, body_dict)

async def _build_model_list(request: Request) -> dict:
    """Shared model listing logic used by all /models endpoints."""
    all_models = []
    user_id = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            db = DatabaseRegistry.get_config_database()
            token = auth_header.split(" ")[1]
            user = db.get_user_by_token(token)
            if user:
                user_id = user.get("id")
        except Exception as e:
            logger.debug(f"Auth check failed for models request: {e}")
    for provider_id, provider_config in _config.providers.items():
        try:
            provider_models = await get_provider_models(provider_id, provider_config, _config, user_id=user_id)
            all_models.extend(provider_models)
        except Exception as e:
            logger.warning(f"Error listing models for provider {provider_id}: {e}")
    for rotation_id, rotation_config in _config.rotations.items():
        try:
            all_models.append({'id': f"rotation/{rotation_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-rotation', 'type': 'rotation', 'rotation_id': rotation_id, 'model_name': rotation_config.model_name, 'capabilities': getattr(rotation_config, 'capabilities', [])})
        except Exception as e:
            logger.warning(f"Error listing rotation {rotation_id}: {e}")
    for autoselect_id, autoselect_config in _config.autoselect.items():
        try:
            all_models.append({'id': f"autoselect/{autoselect_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-autoselect', 'type': 'autoselect', 'autoselect_id': autoselect_id, 'model_name': autoselect_config.model_name, 'description': autoselect_config.description, 'capabilities': getattr(autoselect_config, 'capabilities', [])})
        except Exception as e:
            logger.warning(f"Error listing autoselect {autoselect_id}: {e}")
    logger.info(f"Returning {len(all_models)} total models")
    return {"object": "list", "data": all_models}

@router.get("/api/models")
async def list_all_models(request: Request):
    logger.info("=== LIST ALL MODELS REQUEST ===")
    return await _build_model_list(request)

@router.get("/api/v1/models")
async def v1_list_all_models(request: Request):
    logger.info("=== V1 LIST ALL MODELS REQUEST ===")
    return await _build_model_list(request)

@router.get("/v1/models")
async def v1_list_all_models_alias(request: Request):
    return await v1_list_all_models(request)

@router.get("/v1/chat/models")
async def v1_chat_models_alias(request: Request):
    return await v1_list_all_models(request)

@router.get("/models")
async def models_root_alias(request: Request):
    return await v1_list_all_models(request)

@router.post("/api/v1/audio/transcriptions")
async def v1_audio_transcriptions(request: Request):
    logger.info("=== V1 AUDIO TRANSCRIPTION REQUEST ===")
    form = await request.form()
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(form.get('model', ''), user_id=user_id, handler=handler)
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        updated_form[key] = actual_model if key == 'model' else value
    return await handler.handle_audio_transcription(request, provider_id, updated_form)

@router.post("/api/v1/audio/speech")
async def v1_audio_speech(request: Request, body: dict):
    logger.info("=== V1 TEXT-TO-SPEECH REQUEST ===")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_text_to_speech(request, provider_id, body)

@router.post("/api/v1/images/generations")
async def v1_image_generations(request: Request, body: dict):
    logger.info("=== V1 IMAGE GENERATION REQUEST ===")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_image_generation(request, provider_id, body)

@router.post("/api/v1/embeddings")
async def v1_embeddings(request: Request, body: dict):
    logger.info("=== V1 EMBEDDINGS REQUEST ===")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_embeddings(request, provider_id, body)

@router.get("/api/rotations")
async def list_rotations():
    logger.info("=== LIST ROTATIONS REQUEST ===")
    rotations_info = {}
    for rotation_id, rotation_config in _config.rotations.items():
        models = []
        for provider in rotation_config.providers:
            for model in provider['models']:
                models.append({"name": model['name'], "provider_id": provider['provider_id'], "weight": model['weight'], "rate_limit": model.get('rate_limit')})
        rotations_info[rotation_id] = {"model_name": rotation_config.model_name, "models": models}
    return rotations_info

@router.post("/api/rotations/chat/completions")
async def rotation_chat_completions(request: Request, body: ChatCompletionRequest):
    logger.info(f"=== ROTATION CHAT COMPLETION REQUEST START ===")
    body_dict = body.model_dump()
    if body.model not in _config.rotations:
        raise HTTPException(status_code=404, detail=f"Rotation '{body.model}' not found. Available: {list(_config.rotations.keys())}")
    try:
        user_id = getattr(request.state, 'user_id', None)
        token_id = getattr(request.state, 'token_id', None)
        handler = _get_user_handler('rotation', user_id)
        return await handler.handle_rotation_request(body.model, body_dict, user_id, token_id)
    except Exception as e:
        logger.error(f"Error handling rotation chat_completions: {str(e)}", exc_info=True)
        raise

@router.get("/api/rotations/models")
async def list_rotation_models():
    logger.info("=== LIST ROTATION MODELS REQUEST ===")
    all_models = []
    for rotation_id, rotation_config in _config.rotations.items():
        for provider in rotation_config.providers:
            for model in provider['models']:
                all_models.append({"id": f"{rotation_id}/{model['name']}", "name": rotation_id, "object": "model", "created": int(time.time()), "owned_by": provider['provider_id'], "rotation_id": rotation_id, "actual_model": model['name'], "provider_id": provider['provider_id'], "weight": model['weight'], "rate_limit": model.get('rate_limit')})
    return {"data": all_models}

@router.get("/api/autoselect")
async def list_autoselect():
    logger.info("=== LIST AUTOSELECT REQUEST ===")
    autoselect_info = {}
    for autoselect_id, autoselect_config in _config.autoselect.items():
        autoselect_info[autoselect_id] = {"model_name": autoselect_config.model_name, "description": autoselect_config.description, "fallback": autoselect_config.fallback, "available_models": [{"model_id": m.model_id, "description": m.description} for m in autoselect_config.available_models]}
    return autoselect_info

@router.post("/api/autoselect/chat/completions")
async def autoselect_chat_completions(request: Request, body: ChatCompletionRequest):
    logger.info(f"=== AUTOSELECT CHAT COMPLETION REQUEST START ===")
    body_dict = body.model_dump()
    user_id = getattr(request.state, 'user_id', None)
    token_id = getattr(request.state, 'token_id', None)
    handler = _get_user_handler('autoselect', user_id)
    if body.model not in _config.autoselect and (not user_id or body.model not in handler.user_autoselects):
        raise HTTPException(status_code=400, detail=f"Model '{body.model}' not found. Available autoselect: {list(_config.autoselect.keys())}")
    try:
        if body.stream:
            return await handler.handle_autoselect_streaming_request(body.model, body_dict)
        else:
            return await handler.handle_autoselect_request(body.model, body_dict, user_id, token_id)
    except Exception as e:
        logger.error(f"Error handling autoselect chat_completions: {str(e)}", exc_info=True)
        raise

@router.get("/api/autoselect/models")
async def list_autoselect_models():
    logger.info("=== LIST AUTOSELECT MODELS REQUEST ===")
    all_models = []
    for autoselect_id, autoselect_config in _config.autoselect.items():
        for model_info in autoselect_config.available_models:
            all_models.append({"id": model_info.model_id, "name": autoselect_id, "object": "model", "created": int(time.time()), "owned_by": "autoselect", "autoselect_id": autoselect_id, "description": model_info.description, "fallback": autoselect_config.fallback})
    return {"data": all_models}

@router.get("/api/autoselections/models")
async def list_autoselection_models():
    return await list_autoselect_models()

@router.post("/api/{provider_id}/chat/completions")
async def provider_chat_completions(request: Request, provider_id: str, body: dict):
    logger.info(f"=== PROVIDER CHAT COMPLETIONS REQUEST === Provider ID: {provider_id}")
    model = body.get('model', '')
    if '/' not in model:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    actual_model = model.split('/', 1)[1]
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    body_dict = dict(body)
    body_dict['model'] = actual_model
    if provider_id not in _config.providers and (not user_id or provider_id not in handler.user_providers):
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")
    try:
        if body.get('stream'):
            result = await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
        else:
            result = await handler.handle_chat_completion(request, provider_id, body_dict)
        import asyncio as _asyncio
        _t = _asyncio.create_task(_refresh_provider_usage_if_stale(provider_id, user_id))
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)
        return result
    except Exception as e:
        logger.error(f"Error handling chat_completions: {str(e)}", exc_info=True)
        raise

@router.get("/api/{provider_id}/models")
async def list_models(request: Request, provider_id: str):
    logger.debug(f"Received list_models request for provider: {provider_id}")
    AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')
    user_id = getattr(request.state, 'user_id', None)
    if provider_id in _config.autoselect or (user_id and provider_id in _get_user_handler('autoselect', user_id).user_autoselects):
        handler = _get_user_handler('autoselect', user_id)
        try:
            return await handler.handle_autoselect_model_list(provider_id)
        except Exception as e:
            logger.error(f"Error handling autoselect model list: {str(e)}", exc_info=True)
            raise
    if provider_id in _config.rotations or (user_id and provider_id in _get_user_handler('rotation', user_id).rotations):
        handler = _get_user_handler('rotation', user_id)
        return await handler.handle_rotation_model_list(provider_id)
    handler = _get_user_handler('request', user_id)
    if provider_id not in _config.providers and (not user_id or provider_id not in handler.user_providers):
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")
    try:
        return await handler.handle_model_list(request, provider_id)
    except Exception as e:
        logger.error(f"Error handling list_models: {str(e)}", exc_info=True)
        raise

@router.post("/api/audio/transcriptions")
async def audio_transcriptions(request: Request):
    logger.info("=== AUDIO TRANSCRIPTION REQUEST ===")
    form = await request.form()
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(form.get('model', ''), user_id=user_id, handler=handler)
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        updated_form[key] = actual_model if key == 'model' else value
    return await handler.handle_audio_transcription(request, provider_id, updated_form)

@router.post("/api/audio/speech")
async def audio_speech(request: Request, body: dict):
    logger.info("=== TEXT-TO-SPEECH REQUEST ===")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_text_to_speech(request, provider_id, body)

@router.post("/api/images/generations")
async def image_generations(request: Request, body: dict):
    logger.info("=== IMAGE GENERATION REQUEST ===")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_image_generation(request, provider_id, body)

@router.post("/api/embeddings")
async def embeddings(request: Request, body: dict):
    logger.info("=== EMBEDDINGS REQUEST ===")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_embeddings(request, provider_id, body)

def _resolve_provider(model: str, user_id=None, handler=None) -> tuple[str, str]:
    """Resolve provider_id and actual_model. Checks user providers when handler is given."""
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model'")
    if provider_id in ("rotation", "rotations"):
        rot_handler = _get_user_handler('rotation', user_id) if user_id else _rotation_handler
        if actual_model not in _config.rotations and actual_model not in getattr(rot_handler, 'rotations', {}):
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found")
        provider_id, actual_model = rot_handler._select_provider_and_model(actual_model)
    elif provider_id in ("autoselect", "autoselections"):
        asel_handler = _get_user_handler('autoselect', user_id) if user_id else None
        asel_cfg = _config.autoselect.get(actual_model) or (asel_handler and getattr(asel_handler, 'user_autoselects', {}).get(actual_model))
        if not asel_cfg:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found")
        fallback = asel_cfg.fallback if hasattr(asel_cfg, 'fallback') else asel_cfg.get('fallback', '')
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        elif fallback in _config.rotations:
            provider_id, actual_model = _rotation_handler._select_provider_and_model(fallback)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid fallback for autoselect '{actual_model}'")
    user_providers = getattr(handler, 'user_providers', {}) if handler else {}
    if provider_id not in _config.providers and provider_id not in user_providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return provider_id, actual_model


async def _generic_proxy(request: Request, body: dict, endpoint_path: str, method: str = "POST") -> JSONResponse:
    """Resolve provider from body['model'] and forward to provider endpoint."""
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    provider_id, actual_model = _resolve_provider(body.get('model', ''), user_id=user_id, handler=handler)
    body['model'] = actual_model
    return await handler.handle_generic_proxy(request, provider_id, endpoint_path, body, method=method)


# ── Images ────────────────────────────────────────────────────────────────────

@router.post("/api/v1/images/edits")
async def v1_image_edits(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/edits")

@router.post("/api/v1/images/variations")
async def v1_image_variations(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/variations")

@router.post("/api/v1/images/upscale")
async def v1_image_upscale(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/upscale")

@router.post("/api/v1/images/inpaint")
async def v1_image_inpaint(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/inpaint")

@router.post("/api/v1/images/outpaint")
async def v1_image_outpaint(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/outpaint")

@router.post("/api/v1/images/caption")
async def v1_image_caption(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/caption")

@router.post("/api/v1/images/detect")
async def v1_image_detect(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/detect")

@router.post("/api/v1/images/segment")
async def v1_image_segment(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/segment")

@router.post("/api/v1/images/restore")
async def v1_image_restore(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/restore")

@router.post("/api/v1/images/colorize")
async def v1_image_colorize(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/colorize")

@router.post("/api/v1/images/style-transfer")
async def v1_image_style_transfer(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/style-transfer")

@router.post("/api/v1/images/remove-bg")
async def v1_image_remove_bg(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/images/remove-bg")


# ── Video ─────────────────────────────────────────────────────────────────────

@router.post("/api/v1/video/generations")
async def v1_video_generations(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/video/generations")

@router.post("/api/v1/video/animations")
async def v1_video_animations(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/video/animations")

@router.post("/api/v1/video/edits")
async def v1_video_edits(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/video/edits")

@router.post("/api/v1/video/descriptions")
async def v1_video_descriptions(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/video/descriptions")

@router.post("/api/v1/video/transcriptions")
async def v1_video_transcriptions(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/video/transcriptions")

@router.post("/api/v1/video/upscale")
async def v1_video_upscale(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/video/upscale")


# ── Audio ─────────────────────────────────────────────────────────────────────

@router.post("/api/v1/audio/generations")
async def v1_audio_generations(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/generations")

@router.post("/api/v1/audio/translations")
async def v1_audio_translations(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/translations")

@router.post("/api/v1/audio/identify")
async def v1_audio_identify(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/identify")

@router.post("/api/v1/audio/split")
async def v1_audio_split(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/split")

@router.post("/api/v1/audio/denoise")
async def v1_audio_denoise(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/denoise")

@router.post("/api/v1/audio/label")
async def v1_audio_label(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/label")

@router.post("/api/v1/audio/diarize")
async def v1_audio_diarize(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/diarize")

@router.post("/api/v1/audio/translate")
async def v1_audio_translate(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/audio/translate")


# ── Text / NLP ────────────────────────────────────────────────────────────────

@router.post("/api/v1/moderations")
async def v1_moderations(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/moderations")

@router.post("/api/v1/translate")
async def v1_translate(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/translate")

@router.post("/api/v1/summarize")
async def v1_summarize(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/summarize")

@router.post("/api/v1/classify")
async def v1_classify(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/classify")

@router.post("/api/v1/sentiment")
async def v1_sentiment(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/sentiment")

@router.post("/api/v1/ner")
async def v1_ner(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/ner")

@router.post("/api/v1/answers")
async def v1_answers(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/answers")

@router.post("/api/v1/reasoning")
async def v1_reasoning(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/reasoning")

@router.post("/api/v1/search")
async def v1_search(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/search")

@router.post("/api/v1/tools")
async def v1_tools(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/tools")

@router.post("/api/v1/function-call")
async def v1_function_call(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/function-call")

@router.post("/api/v1/parse")
async def v1_parse(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/parse")


# ── Code ──────────────────────────────────────────────────────────────────────

@router.post("/api/v1/code/generate")
async def v1_code_generate(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/code/generate")

@router.post("/api/v1/code/complete")
async def v1_code_complete(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/code/complete")

@router.post("/api/v1/code/explain")
async def v1_code_explain(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/code/explain")

@router.post("/api/v1/code/refactor")
async def v1_code_refactor(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/code/refactor")

@router.post("/api/v1/code/review")
async def v1_code_review(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/code/review")

@router.post("/api/v1/code/test")
async def v1_code_test(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/code/test")

@router.post("/api/v1/math")
async def v1_math(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/math")

@router.post("/api/v1/reason")
async def v1_reason(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/reason")


# ── Vision / Multimodal ───────────────────────────────────────────────────────

@router.post("/api/v1/vision/describe")
async def v1_vision_describe(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/vision/describe")

@router.post("/api/v1/vision/ocr")
async def v1_vision_ocr(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/vision/ocr")

@router.post("/api/v1/vision/analyze")
async def v1_vision_analyze(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/vision/analyze")

@router.post("/api/v1/vision/detect")
async def v1_vision_detect(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/vision/detect")

@router.post("/api/v1/depth")
async def v1_depth(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/depth")

@router.post("/api/v1/pose")
async def v1_pose(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/pose")


# ── 3D & Advanced ─────────────────────────────────────────────────────────────

@router.post("/api/v1/3d/generate")
async def v1_3d_generate(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/3d/generate")

@router.post("/api/v1/3d/convert")
async def v1_3d_convert(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/3d/convert")

@router.post("/api/v1/animate")
async def v1_animate(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/animate")

@router.post("/api/v1/avatar")
async def v1_avatar(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/avatar")

@router.post("/api/v1/face-swap")
async def v1_face_swap(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/face-swap")

@router.post("/api/v1/face-restore")
async def v1_face_restore(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/face-restore")


# ── Fine-tuning ───────────────────────────────────────────────────────────────

async def _get_handler_for_provider(request: Request, provider: str):
    """Resolve a provider_id from query param and return (provider_id, handler)."""
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    user_providers = getattr(handler, 'user_providers', {})
    if not provider or (provider not in _config.providers and provider not in user_providers):
        available = list(_config.providers.keys()) + list(user_providers.keys())
        raise HTTPException(status_code=400, detail=f"Query param 'provider' required. Available: {available}")
    return provider, handler


# ── Fine-tuning ───────────────────────────────────────────────────────────────

@router.get("/api/v1/fine-tunes")
async def v1_list_fine_tunes(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/fine-tunes", {}, method="GET")

@router.post("/api/v1/fine-tunes")
async def v1_create_fine_tune(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/fine-tunes")

@router.get("/api/v1/fine-tunes/{job_id}")
async def v1_get_fine_tune(job_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/fine-tunes/{job_id}", {}, method="GET")

@router.post("/api/v1/fine-tunes/{job_id}/cancel")
async def v1_cancel_fine_tune(job_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/fine-tunes/{job_id}/cancel", {})


# ── Files ─────────────────────────────────────────────────────────────────────

@router.get("/api/v1/files")
async def v1_list_files(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/files", {}, method="GET")

@router.post("/api/v1/files")
async def v1_upload_file(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/files")

@router.get("/api/v1/files/{file_id}")
async def v1_get_file(file_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/files/{file_id}", {}, method="GET")

@router.delete("/api/v1/files/{file_id}")
async def v1_delete_file(file_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/files/{file_id}", {}, method="DELETE")


# ── Assistants ────────────────────────────────────────────────────────────────

@router.get("/api/v1/assistants")
async def v1_list_assistants(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/assistants", {}, method="GET")

@router.post("/api/v1/assistants")
async def v1_create_assistant(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/assistants")

@router.get("/api/v1/assistants/{assistant_id}")
async def v1_get_assistant(assistant_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/assistants/{assistant_id}", {}, method="GET")

@router.delete("/api/v1/assistants/{assistant_id}")
async def v1_delete_assistant(assistant_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/assistants/{assistant_id}", {}, method="DELETE")


# ── Threads ───────────────────────────────────────────────────────────────────

@router.get("/api/v1/threads")
async def v1_list_threads(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/threads", {}, method="GET")

@router.post("/api/v1/threads")
async def v1_create_thread(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/threads")

@router.get("/api/v1/threads/{thread_id}")
async def v1_get_thread(thread_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/threads/{thread_id}", {}, method="GET")

@router.post("/api/v1/threads/{thread_id}/runs")
async def v1_create_run(thread_id: str, request: Request, body: dict):
    return await _generic_proxy(request, body, f"v1/threads/{thread_id}/runs")

@router.get("/api/v1/threads/{thread_id}/runs")
async def v1_list_runs(thread_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/threads/{thread_id}/runs", {}, method="GET")


# ── Vector stores ─────────────────────────────────────────────────────────────

@router.get("/api/v1/vector-stores")
async def v1_list_vector_stores(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/vector-stores", {}, method="GET")

@router.post("/api/v1/vector-stores")
async def v1_create_vector_store(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/vector-stores")

@router.get("/api/v1/vector-stores/{store_id}")
async def v1_get_vector_store(store_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/vector-stores/{store_id}", {}, method="GET")

@router.delete("/api/v1/vector-stores/{store_id}")
async def v1_delete_vector_store(store_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/vector-stores/{store_id}", {}, method="DELETE")


# ── Batch ─────────────────────────────────────────────────────────────────────

@router.post("/api/v1/batch")
async def v1_create_batch(request: Request, body: dict):
    return await _generic_proxy(request, body, "v1/batch")

@router.get("/api/v1/batch/{batch_id}")
async def v1_get_batch(batch_id: str, request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, f"v1/batch/{batch_id}", {}, method="GET")


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/usage")
async def v1_usage(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/usage", {}, method="GET")

@router.get("/api/v1/usage/costs")
async def v1_usage_costs(request: Request, provider: str = ""):
    pid, handler = await _get_handler_for_provider(request, provider)
    return await handler.handle_generic_proxy(request, pid, "v1/usage/costs", {}, method="GET")

@router.get("/api/v1/providers/health")
async def v1_providers_health():
    health = {}
    for provider_id, provider_config in _config.providers.items():
        from aisbf.providers import get_provider_handler
        try:
            h = get_provider_handler(provider_id, getattr(provider_config, 'api_key', None))
            health[provider_id] = {"status": "unavailable" if h.is_rate_limited() else "ok"}
        except Exception as e:
            health[provider_id] = {"status": "error", "detail": str(e)}
    return health

@router.get("/api/v1/cache/stats")
async def v1_cache_stats():
    from aisbf.cache import get_response_cache
    cache = get_response_cache()
    try:
        return cache.stats() if hasattr(cache, 'stats') else {"status": "unavailable"}
    except Exception:
        return {"status": "unavailable"}


# ── MCP config endpoints ──────────────────────────────────────────────────────

@router.get("/api/autoselect/{autoselect_id}")
async def get_autoselect_config(autoselect_id: str):
    if autoselect_id not in _config.autoselect:
        raise HTTPException(status_code=404, detail=f"Autoselect '{autoselect_id}' not found")
    cfg = _config.autoselect[autoselect_id]
    return {"id": autoselect_id, "model_name": cfg.model_name, "description": cfg.description,
            "fallback": cfg.fallback, "available_models": [{"model_id": m.model_id, "description": m.description} for m in cfg.available_models]}

@router.get("/api/rotations/{rotation_id}")
async def get_rotation_config(rotation_id: str):
    if rotation_id not in _config.rotations:
        raise HTTPException(status_code=404, detail=f"Rotation '{rotation_id}' not found")
    cfg = _config.rotations[rotation_id]
    return {"id": rotation_id, "model_name": cfg.model_name,
            "providers": [{"provider_id": p["provider_id"], "models": p["models"]} for p in cfg.providers]}

@router.get("/api/v1/providers")
async def get_providers_config(request: Request):
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    user_providers = getattr(handler, 'user_providers', {})
    providers = {pid: {"endpoint": pc.endpoint, "type": getattr(pc, 'type', 'unknown')}
                 for pid, pc in _config.providers.items()}
    for pid, pc in user_providers.items():
        providers[pid] = {"endpoint": pc.get('endpoint', ''), "type": pc.get('type', 'unknown'), "user_defined": True}
    return {"providers": providers}


# ── Legacy OpenAI engines format ──────────────────────────────────────────────

@router.post("/api/v1/engines/{engine}/embeddings")
async def v1_engines_embeddings(engine: str, request: Request, body: dict):
    # engine is in format "provider--model" or just used as model; normalise to provider/model
    if '--' in engine:
        provider_id, model = engine.split('--', 1)
    else:
        provider_id, model = parse_provider_from_model(engine)
        if not provider_id:
            raise HTTPException(status_code=400, detail="Engine must be in format 'provider--model' or 'provider/model'")
    body['model'] = f"{provider_id}/{model}"
    return await _generic_proxy(request, body, "v1/embeddings")

@router.post("/api/v1/engines/{engine}/completions")
async def v1_engines_completions(engine: str, request: Request, body: dict):
    if '--' in engine:
        provider_id, model = engine.split('--', 1)
    else:
        provider_id, model = parse_provider_from_model(engine)
        if not provider_id:
            raise HTTPException(status_code=400, detail="Engine must be in format 'provider--model' or 'provider/model'")
    body['model'] = f"{provider_id}/{model}"
    return await _generic_proxy(request, body, "v1/completions")


@router.post("/api/{provider_id}")
async def catch_all_post(provider_id: str, request: Request):
    logger.info(f"=== CATCH-ALL POST REQUEST === path: {request.url.path}, provider: {provider_id}")
    error_msg = f"Invalid endpoint: {request.url.path}\n\nThe correct endpoint format is: /api/{{provider_id}}/chat/completions\n\nAvailable providers: {list(_config.providers.keys())}\nAvailable rotations: {list(_config.rotations.keys())}\nAvailable autoselect: {list(_config.autoselect.keys())}\n\nExample: POST /api/ollama/chat/completions"
    raise HTTPException(status_code=404, detail=error_msg.strip())


@router.get("/api/proxy/{content_id}")
async def proxy_content(content_id: str):
    """Proxy generated content (images, audio, etc.)"""
    from fastapi import HTTPException
    try:
        result = await _request_handler.handle_content_proxy(content_id)
        return result
    except Exception as e:
        logging.getLogger(__name__).error(f"Error proxying content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
