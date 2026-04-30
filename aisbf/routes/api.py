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

@router.get("/api/models")
async def list_all_models(request: Request):
    logger.info("=== LIST ALL MODELS REQUEST ===")
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

@router.get("/api/v1/models")
async def v1_list_all_models(request: Request):
    logger.info("=== V1 LIST ALL MODELS REQUEST ===")
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
    model = form.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        updated_form[key] = actual_model if key == 'model' else value
    return await handler.handle_audio_transcription(request, provider_id, updated_form)

@router.post("/api/v1/audio/speech")
async def v1_audio_speech(request: Request, body: dict):
    logger.info("=== V1 TEXT-TO-SPEECH REQUEST ===")
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    return await handler.handle_text_to_speech(request, provider_id, body)

@router.post("/api/v1/images/generations")
async def v1_image_generations(request: Request, body: dict):
    logger.info("=== V1 IMAGE GENERATION REQUEST ===")
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    return await handler.handle_image_generation(request, provider_id, body)

@router.post("/api/v1/embeddings")
async def v1_embeddings(request: Request, body: dict):
    logger.info("=== V1 EMBEDDINGS REQUEST ===")
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
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
    model = form.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    from starlette.datastructures import FormData
    updated_form = FormData()
    for key, value in form.items():
        updated_form[key] = actual_model if key == 'model' else value
    return await handler.handle_audio_transcription(request, provider_id, updated_form)

@router.post("/api/audio/speech")
async def audio_speech(request: Request, body: dict):
    logger.info("=== TEXT-TO-SPEECH REQUEST ===")
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    return await handler.handle_text_to_speech(request, provider_id, body)

@router.post("/api/images/generations")
async def image_generations(request: Request, body: dict):
    logger.info("=== IMAGE GENERATION REQUEST ===")
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    return await handler.handle_image_generation(request, provider_id, body)

@router.post("/api/embeddings")
async def embeddings(request: Request, body: dict):
    logger.info("=== EMBEDDINGS REQUEST ===")
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'")
    if provider_id == "rotation":
        if actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
        selected_provider, selected_model = _rotation_handler._select_provider_and_model(actual_model)
        provider_id = selected_provider
        actual_model = selected_model
    elif provider_id == "autoselect":
        if actual_model not in _config.autoselect:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
        autoselect_config = _config.autoselect[actual_model]
        fallback = autoselect_config.fallback
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        else:
            if fallback in _config.rotations:
                selected_provider, selected_model = _rotation_handler._select_provider_and_model(fallback)
                provider_id = selected_provider
                actual_model = selected_model
            else:
                raise HTTPException(status_code=400, detail=f"Invalid fallback configuration for autoselect '{actual_model}'")
    if provider_id not in _config.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found. Available: {list(_config.providers.keys())}")
    body['model'] = actual_model
    user_id = getattr(request.state, 'user_id', None)
    handler = _get_user_handler('request', user_id)
    return await handler.handle_embeddings(request, provider_id, body)

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
