from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from typing import Optional
import logging, time
from aisbf.models import ChatCompletionRequest
from aisbf.database import DatabaseRegistry
from aisbf.app.model_cache import get_provider_models
from aisbf.studio_services import studio_service

router = APIRouter()
_config = None
_get_user_handler = None

def init(config, get_user_handler_fn):
    global _config, _get_user_handler
    _config = config
    _get_user_handler = get_user_handler_fn

logger = logging.getLogger(__name__)


def _resolve_market_provider_alias(model: str):
    parts = (model or '').split('/')
    if len(parts) < 3:
        return None
    username = parts[0].strip()
    provider_id = parts[1].strip()
    model_id = '/'.join(parts[2:]).strip()
    if not username or not provider_id or not model_id:
        return None
    return username, provider_id, model_id


def _resolve_market_share_alias(model: str):
    parts = (model or '').split('/')
    if len(parts) < 3:
        return None
    username = parts[0].strip()
    share_type = parts[1].strip()
    share_id = parts[2].strip()
    trailing = '/'.join(parts[3:]).strip() if len(parts) > 3 else ''
    if share_type not in {'provider', 'rotation', 'autoselect'}:
        return None
    return {'username': username, 'share_type': share_type, 'share_id': share_id, 'trailing': trailing}

def parse_provider_from_model(model: str) -> tuple[str, str]:
    if '/' in model:
        parts = model.split('/', 1)
        return parts[0], parts[1]
    return None, model


def _normalize_studio_proxy_body(endpoint_path: str, body: dict) -> dict:
    normalized = dict(body or {})

    def prefer_model(*keys):
        for key in keys:
            value = normalized.get(key)
            if isinstance(value, str) and value.strip():
                normalized['model'] = value.strip()
                return

    if endpoint_path == "v1/video/dub":
        prefer_model('video_model', 'stt_model', 'tts_model', 'model')
    elif endpoint_path == "v1/audio/clone":
        prefer_model('model', 'tts_model')
    elif endpoint_path == "v1/audio/convert":
        prefer_model('model', 'audio_model', 'tts_model', 'stt_model')
    elif endpoint_path in {"v1/audio/split", "v1/audio/denoise"}:
        prefer_model('model', 'audio_model')
    elif endpoint_path in {"v1/images/faceswap", "v1/images/outfit"}:
        prefer_model('model', 'image_model', 'video_model')
    elif endpoint_path in {"v1/images/to3d", "v1/images/from3d", "v1/video/to3d", "v1/video/from3d", "v1/3d/generate"}:
        prefer_model('model', 'render_model', 'image_model', 'video_model')

    return normalized

@router.get("/api/u/{username}/models")
async def user_list_models(request: Request, username: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    if is_global_token or is_admin:
        all_models = []
        for provider_id, provider_config in _config.providers.items():
            try:
                provider_models = await get_provider_models(provider_id, provider_config)
                all_models.extend(provider_models)
            except Exception as e:
                logger.warning(f"Error listing models for provider {provider_id}: {e}")
        for rotation_id, rotation_config in _config.rotations.items():
            try:
                all_models.append({'id': f"rotation/{rotation_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-rotation', 'type': 'rotation', 'rotation_id': rotation_id, 'model_name': rotation_config.model_name, 'source': 'global'})
            except Exception as e:
                logger.warning(f"Error listing rotation {rotation_id}: {e}")
        for autoselect_id, autoselect_config in _config.autoselect.items():
            try:
                all_models.append({'id': f"autoselect/{autoselect_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-autoselect', 'type': 'autoselect', 'autoselect_id': autoselect_id, 'model_name': autoselect_config.model_name, 'description': autoselect_config.description, 'source': 'global'})
            except Exception as e:
                logger.warning(f"Error listing autoselect {autoselect_id}: {e}")
        if user_id and not is_global_token:
            handler = _get_user_handler('request', user_id)
            for provider_id, provider_config in handler.user_providers.items():
                try:
                    if hasattr(provider_config, 'models') and provider_config.models:
                        for model in provider_config.models:
                            all_models.append({'id': f"{provider_id}/{model.name}", 'object': 'model', 'created': int(time.time()), 'owned_by': provider_id, 'provider': provider_id, 'type': 'user_provider', 'model_name': model.name, 'source': 'user_config'})
                except Exception as e:
                    logger.warning(f"Error listing models for user provider {provider_id}: {e}")
            rotation_handler = _get_user_handler('rotation', user_id)
            for rotation_id in rotation_handler.rotations:
                try:
                    all_models.append({'id': f"rotation/{rotation_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-rotation', 'type': 'rotation', 'rotation_id': rotation_id, 'source': 'user_config'})
                except Exception as e:
                    logger.warning(f"Error listing user rotation {rotation_id}: {e}")
            autoselect_handler = _get_user_handler('autoselect', user_id)
            for autoselect_id in autoselect_handler.autoselects:
                try:
                    all_models.append({'id': f"autoselect/{autoselect_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-autoselect', 'type': 'autoselect', 'autoselect_id': autoselect_id, 'source': 'user_config'})
                except Exception as e:
                    logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
        return {"object": "list", "data": all_models}
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required. Use a valid API token."})
    all_models = []
    handler = _get_user_handler('request', user_id)
    for provider_id, provider_config in handler.user_providers.items():
        try:
            if hasattr(provider_config, 'models') and provider_config.models:
                for model in provider_config.models:
                    all_models.append({'id': f"{provider_id}/{model.name}", 'object': 'model', 'created': int(time.time()), 'owned_by': provider_id, 'provider': provider_id, 'type': 'user_provider', 'model_name': model.name, 'context_size': getattr(model, 'context_size', None), 'capabilities': getattr(model, 'capabilities', []), 'description': getattr(model, 'description', None), 'source': 'user_config'})
        except Exception as e:
            logger.warning(f"Error listing models for user provider {provider_id}: {e}")
    rotation_handler = _get_user_handler('rotation', user_id)
    for rotation_id, rotation_config in rotation_handler.rotations.items():
        try:
            all_models.append({'id': f"rotation/{rotation_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-rotation', 'type': 'rotation', 'rotation_id': rotation_id, 'model_name': rotation_config.get('model_name', rotation_id), 'capabilities': rotation_config.get('capabilities', []), 'source': 'user_config'})
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    autoselect_handler = _get_user_handler('autoselect', user_id)
    for autoselect_id, autoselect_config in autoselect_handler.autoselects.items():
        try:
            all_models.append({'id': f"autoselect/{autoselect_id}", 'object': 'model', 'created': int(time.time()), 'owned_by': 'aisbf-autoselect', 'type': 'autoselect', 'autoselect_id': autoselect_id, 'model_name': autoselect_config.get('model_name', autoselect_id), 'description': autoselect_config.get('description'), 'capabilities': autoselect_config.get('capabilities', []), 'source': 'user_config'})
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    return {"object": "list", "data": all_models}

@router.get("/api/u/{username}/models/{model_id}")
async def user_get_model(model_id: str, request: Request, username: str):
    result = await user_list_models(request, username)
    for model in (result.get("data", []) if isinstance(result, dict) else []):
        if model.get("id") == model_id:
            return model
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

@router.get("/api/u/{username}/providers")
async def user_list_providers(request: Request, username: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    if is_global_token or is_admin:
        providers_info = {}
        for provider_id, provider_config in _config.providers.items():
            try:
                config_dict = provider_config.model_dump() if hasattr(provider_config, 'model_dump') else vars(provider_config) if hasattr(provider_config, '__dict__') else {}
                safe_config = {k: v for k, v in config_dict.items() if k not in ['api_key', 'password', 'secret', 'token']}
                providers_info[provider_id] = {'name': getattr(provider_config, 'name', provider_id), 'type': getattr(provider_config, 'type', 'unknown'), 'endpoint': getattr(provider_config, 'endpoint', None), 'models_count': len(getattr(provider_config, 'models', [])), 'config': safe_config, 'source': 'global'}
            except Exception as e:
                logger.warning(f"Error listing global provider {provider_id}: {e}")
        if user_id and not is_global_token:
            handler = _get_user_handler('request', user_id)
            for provider_id, provider_config in handler.user_providers.items():
                try:
                    config_dict = provider_config.model_dump() if hasattr(provider_config, 'model_dump') else vars(provider_config) if hasattr(provider_config, '__dict__') else {}
                    safe_config = {k: v for k, v in config_dict.items() if k not in ['api_key', 'password', 'secret', 'token']}
                    providers_info[provider_id] = {'name': getattr(provider_config, 'name', provider_id), 'type': getattr(provider_config, 'type', 'unknown'), 'endpoint': getattr(provider_config, 'endpoint', None), 'models_count': len(getattr(provider_config, 'models', [])), 'config': safe_config, 'source': 'user_config'}
                except Exception as e:
                    logger.warning(f"Error listing user provider {provider_id}: {e}")
        return {"providers": providers_info}
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required. Use a valid API token."})
    handler = _get_user_handler('request', user_id)
    providers_info = {}
    for provider_id, provider_config in handler.user_providers.items():
        try:
            config_dict = provider_config.model_dump() if hasattr(provider_config, 'model_dump') else vars(provider_config) if hasattr(provider_config, '__dict__') else {}
            safe_config = {k: v for k, v in config_dict.items() if k not in ['api_key', 'password', 'secret', 'token']}
            providers_info[provider_id] = {'name': getattr(provider_config, 'name', provider_id), 'type': getattr(provider_config, 'type', 'unknown'), 'endpoint': getattr(provider_config, 'endpoint', None), 'models_count': len(getattr(provider_config, 'models', [])), 'config': safe_config}
        except Exception as e:
            logger.warning(f"Error listing user provider {provider_id}: {e}")
    return {"providers": providers_info}

@router.get("/api/u/{username}/rotations")
async def user_list_rotations(request: Request, username: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    if is_global_token or is_admin:
        rotations_info = {}
        for rotation_id, rotation_config in _config.rotations.items():
            try:
                rotations_info[rotation_id] = {"model_name": rotation_config.model_name, "providers": rotation_config.providers, "source": "global"}
            except Exception as e:
                logger.warning(f"Error listing global rotation {rotation_id}: {e}")
        if user_id and not is_global_token:
            handler = _get_user_handler('rotation', user_id)
            for rotation_id, rotation_config in handler.rotations.items():
                try:
                    rotations_info[rotation_id] = {"model_name": rotation_config.get('model_name', rotation_id), "providers": rotation_config.get('providers', []), "source": "user_config"}
                except Exception as e:
                    logger.warning(f"Error listing user rotation {rotation_id}: {e}")
        return {"rotations": rotations_info}
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required. Use a valid API token."})
    handler = _get_user_handler('rotation', user_id)
    rotations_info = {}
    for rotation_id, rotation_config in handler.rotations.items():
        try:
            rotations_info[rotation_id] = {"model_name": rotation_config.get('model_name', rotation_id), "providers": rotation_config.get('providers', [])}
        except Exception as e:
            logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    return {"rotations": rotations_info}

@router.get("/api/u/{username}/autoselects")
async def user_list_autoselects(request: Request, username: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    if is_global_token or is_admin:
        autoselects_info = {}
        for autoselect_id, autoselect_config in _config.autoselect.items():
            try:
                autoselects_info[autoselect_id] = {"model_name": autoselect_config.model_name, "description": autoselect_config.description, "fallback": autoselect_config.fallback, "available_models": [{"model_id": m.model_id, "description": m.description} for m in autoselect_config.available_models], "source": "global"}
            except Exception as e:
                logger.warning(f"Error listing global autoselect {autoselect_id}: {e}")
        if user_id and not is_global_token:
            handler = _get_user_handler('autoselect', user_id)
            for autoselect_id, autoselect_config in handler.autoselects.items():
                try:
                    autoselects_info[autoselect_id] = {"model_name": autoselect_config.get('model_name', autoselect_id), "description": autoselect_config.get('description', ''), "fallback": autoselect_config.get('fallback', ''), "available_models": autoselect_config.get('available_models', []), "source": "user_config"}
                except Exception as e:
                    logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
        return {"autoselects": autoselects_info}
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required. Use a valid API token."})
    handler = _get_user_handler('autoselect', user_id)
    autoselects_info = {}
    for autoselect_id, autoselect_config in handler.autoselects.items():
        try:
            autoselects_info[autoselect_id] = {"model_name": autoselect_config.get('model_name', autoselect_id), "description": autoselect_config.get('description', ''), "fallback": autoselect_config.get('fallback', ''), "available_models": autoselect_config.get('available_models', [])}
        except Exception as e:
            logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    return {"autoselects": autoselects_info}

@router.post("/api/u/{username}/chat/completions")
async def user_chat_completions(request: Request, username: str, body: ChatCompletionRequest):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            raise HTTPException(status_code=403, detail="Access denied. Username in URL must match authenticated user.")
    market_share = _resolve_market_share_alias(body.model)
    if market_share and market_share['username'] != username:
        db = DatabaseRegistry.get_config_database()
        owner_username = market_share['username']
        owner = db.get_user_by_username(owner_username)
        if not owner:
            raise HTTPException(status_code=404, detail=f"User '{owner_username}' not found")
        listing = db.get_market_listing_for_share(owner_username, market_share['share_type'], market_share['share_id'])
        if not listing:
            raise HTTPException(status_code=404, detail='Market listing not found for requested resource')

        if not user_id:
            raise HTTPException(status_code=401, detail='Authentication required for market usage')

        body_dict = body.model_dump()
        share_type = market_share['share_type']
        actual_model = market_share['trailing']
        if share_type == 'provider':
            provider_id = market_share['share_id']
            owner_provider = db.get_user_provider(owner['id'], provider_id)
            if not owner_provider:
                raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found for user '{owner_username}'")
            owner_handler = _get_user_handler('request', owner['id'])
            body_dict['model'] = actual_model
            result = await owner_handler.handle_chat_completion(request, provider_id, body_dict) if not body.stream else await owner_handler.handle_streaming_chat_completion(request, provider_id, body_dict)
        elif share_type == 'rotation':
            owner_handler = _get_user_handler('rotation', owner['id'])
            body_dict['model'] = market_share['share_id']
            result = await owner_handler.handle_rotation_request(market_share['share_id'], body_dict, owner['id'], getattr(request.state, 'token_id', None))
        elif share_type == 'autoselect':
            owner_handler = _get_user_handler('autoselect', owner['id'])
            body_dict['model'] = market_share['share_id']
            result = await owner_handler.handle_autoselect_request(market_share['share_id'], body_dict, owner['id'], getattr(request.state, 'token_id', None)) if not body.stream else await owner_handler.handle_autoselect_streaming_request(market_share['share_id'], body_dict)
        else:
            raise HTTPException(status_code=400, detail='Unsupported market share type')

        return result

    market_alias = _resolve_market_provider_alias(body.model)
    if market_alias and market_alias[0] != username:
        owner_username, provider_id, actual_model = market_alias
        db = DatabaseRegistry.get_config_database()
        owner = db.get_user_by_username(owner_username)
        if not owner:
            raise HTTPException(status_code=404, detail=f"User '{owner_username}' not found")
        owner_provider = db.get_user_provider(owner['id'], provider_id)
        if not owner_provider:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found for user '{owner_username}'")
        listing = db.get_market_listing_for_share(owner_username, 'provider', provider_id)
        if not listing:
            raise HTTPException(status_code=404, detail='Market listing not found for requested provider')
        if not user_id:
            raise HTTPException(status_code=401, detail='Authentication required for market usage')

        owner_handler = _get_user_handler('request', owner['id'])
        body_dict = body.model_dump()
        body_dict['model'] = actual_model
        provider_config = owner_provider['config']
        result = await owner_handler.handle_chat_completion(request, provider_id, body_dict) if not body.stream else await owner_handler.handle_streaming_chat_completion(request, provider_id, body_dict)
        return result

    provider_id, actual_model = parse_provider_from_model(body.model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', 'autoselect/name', 'user-provider/model', 'user-rotation/name', or 'user-autoselect/name'")
    body_dict = body.model_dump()
    if provider_id == "user-autoselect":
        handler = _get_user_handler('autoselect', user_id)
        if actual_model not in handler.user_autoselects:
            raise HTTPException(status_code=400, detail=f"User autoselect '{actual_model}' not found. Available: {list(handler.user_autoselects.keys())}")
        body_dict['model'] = actual_model
        if body.stream:
            return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
        else:
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)
    if provider_id == "user-rotation":
        handler = _get_user_handler('rotation', user_id)
        if actual_model not in handler.rotations:
            raise HTTPException(status_code=400, detail=f"User rotation '{actual_model}' not found. Available: {list(handler.rotations.keys())}")
        body_dict['model'] = actual_model
        token_id = getattr(request.state, 'token_id', None)
        return await handler.handle_rotation_request(actual_model, body_dict, user_id, token_id)
    if provider_id == "user-provider":
        handler = _get_user_handler('request', user_id)
        if actual_model not in handler.user_providers:
            raise HTTPException(status_code=400, detail=f"User provider '{actual_model}' not found. Available: {list(handler.user_providers.keys())}")
        body_dict['model'] = actual_model
        if body.stream:
            return await handler.handle_streaming_chat_completion(request, actual_model, body_dict)
        else:
            return await handler.handle_chat_completion(request, actual_model, body_dict)
    if is_global_token or is_admin:
        if provider_id == "autoselect":
            if actual_model not in _config.autoselect:
                raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found. Available: {list(_config.autoselect.keys())}")
            handler = _get_user_handler('autoselect', None)
            body_dict['model'] = actual_model
            if body.stream:
                return await handler.handle_autoselect_streaming_request(actual_model, body_dict)
            else:
                token_id = getattr(request.state, 'token_id', None)
                return await handler.handle_autoselect_request(actual_model, body_dict, user_id, token_id)
        if provider_id == "rotation":
            if actual_model not in _config.rotations:
                raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found. Available: {list(_config.rotations.keys())}")
            handler = _get_user_handler('rotation', None)
            body_dict['model'] = actual_model
            token_id = getattr(request.state, 'token_id', None)
            return await handler.handle_rotation_request(actual_model, body_dict, user_id, token_id)
        if provider_id in _config.providers:
            body_dict['model'] = actual_model
            handler = _get_user_handler('request', None)
            if body.stream:
                return await handler.handle_streaming_chat_completion(request, provider_id, body_dict)
            else:
                return await handler.handle_chat_completion(request, provider_id, body_dict)
    raise HTTPException(status_code=400, detail="Model must be in format 'provider/model', 'rotation/name', or 'autoselect/name'. Global configurations are only available to admin users.")

@router.get("/api/u/{username}/rotations/models")
async def user_list_rotation_models(request: Request, username: str):
    return await user_list_config_models(request, username, "rotations")

@router.get("/api/u/{username}/autoselections/models")
async def user_list_autoselection_models(request: Request, username: str):
    return await user_list_config_models(request, username, "autoselects")

@router.get("/api/u/{username}/{config_type}/models")
async def user_list_config_models(request: Request, username: str, config_type: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not is_global_token and not is_admin and user_id:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required. Use a valid API token."})
    all_models = []
    if config_type == "providers":
        handler = _get_user_handler('request', user_id)
        for provider_id, provider_config in handler.user_providers.items():
            try:
                if hasattr(provider_config, 'models') and provider_config.models:
                    for model in provider_config.models:
                        all_models.append({"id": f"user-provider/{provider_id}/{model.name}", "name": model.name, "object": "model", "created": int(time.time()), "owned_by": provider_id, "provider_id": provider_id, "type": "user_provider"})
            except Exception as e:
                logger.warning(f"Error listing models for user provider {provider_id}: {e}")
    elif config_type == "rotations":
        handler = _get_user_handler('rotation', user_id)
        for rotation_id, rotation_config in handler.rotations.items():
            try:
                for provider in rotation_config.get('providers', []):
                    for model in provider.get('models', []):
                        all_models.append({"id": f"rotation/{rotation_id}/{model.get('name', '')}", "name": rotation_id, "object": "model", "created": int(time.time()), "owned_by": provider.get('provider_id', ''), "rotation_id": rotation_id, "actual_model": model.get('name', ''), "provider_id": provider.get('provider_id', ''), "weight": model.get('weight', 1), "type": "user_rotation"})
            except Exception as e:
                logger.warning(f"Error listing user rotation {rotation_id}: {e}")
    elif config_type == "autoselects":
        handler = _get_user_handler('autoselect', user_id)
        for autoselect_id, autoselect_config in handler.autoselects.items():
            try:
                for model_info in autoselect_config.get('available_models', []):
                    all_models.append({"id": f"user-autoselect/{autoselect_id}/{model_info.get('model_id', '')}", "name": autoselect_id, "object": "model", "created": int(time.time()), "owned_by": "user-autoselect", "autoselect_id": autoselect_id, "description": model_info.get('description', ''), "type": "user_autoselect"})
            except Exception as e:
                logger.warning(f"Error listing user autoselect {autoselect_id}: {e}")
    else:
        raise HTTPException(status_code=400, detail="Invalid config type. Use 'providers', 'rotations', or 'autoselects'")
    return {"data": all_models}


@router.get("/api/u/{username}/{user_provider_id}/models")
async def user_list_provider_models_by_username(request: Request, username: str, user_provider_id: str):
    """List models for a specific user provider."""
    import time as _time
    from aisbf.app.model_cache import fetch_provider_models
    db = DatabaseRegistry.get_config_database()
    target_user = db.get_user_by_username(username)
    if not target_user:
        return JSONResponse(status_code=404, content={"error": f"User '{username}' not found"})
    target_user_id = target_user['id']
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    authenticated_user_id = getattr(request.state, 'user_id', None)
    if not (is_admin or is_global_token or authenticated_user_id == target_user_id):
        return JSONResponse(status_code=403, content={"error": "Permission denied"})
    handler = _get_user_handler('request', target_user_id)
    if user_provider_id not in handler.user_providers:
        return JSONResponse(status_code=404, content={"error": f"User provider '{user_provider_id}' not found"})
    provider_config = handler.user_providers[user_provider_id]
    all_models = []
    try:
        if hasattr(provider_config, 'models') and provider_config.models:
            for model in provider_config.models:
                all_models.append({"id": f"{user_provider_id}/{model.name}", "name": model.name,
                                   "object": "model", "created": int(_time.time()),
                                   "owned_by": user_provider_id, "type": "user_provider"})
        else:
            models = await fetch_provider_models(user_provider_id, _config, user_id=target_user_id)
            for model in models:
                all_models.append({"id": f"{user_provider_id}/{model.get('id', model.get('name', ''))}",
                                   "name": model.get('name', ''), "object": "model",
                                   "created": int(_time.time()), "owned_by": user_provider_id,
                                   "type": "user_provider"})
    except Exception as e:
        logging.getLogger(__name__).warning(f"Error listing models for user provider {user_provider_id}: {e}")
    return {"data": all_models}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _check_user_access(request: Request, username: str):
    """Extract user_id. Access control (global token rejection, username match) is enforced by middleware."""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user_id


async def _user_generic_proxy(request: Request, username: str, body: dict, endpoint_path: str, method: str = "POST") -> JSONResponse:
    """Resolve provider from body['model'] scoped to the user and forward to provider endpoint."""
    user_id = _check_user_access(request, username)
    handler = _get_user_handler('request', user_id)
    body = _normalize_studio_proxy_body(endpoint_path, body)
    model = body.get('model', '')
    provider_id, actual_model = parse_provider_from_model(model)
    if not provider_id:
        raise HTTPException(status_code=400, detail="Model must be in format 'provider/model'")
    # Resolve rotation/autoselect
    if provider_id in ("rotation", "rotations"):
        rot_handler = _get_user_handler('rotation', user_id)
        if actual_model not in rot_handler.rotations and actual_model not in _config.rotations:
            raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found")
        provider_id, actual_model = rot_handler._select_provider_and_model(actual_model)
    elif provider_id in ("autoselect", "autoselections"):
        asel_handler = _get_user_handler('autoselect', user_id)
        asel_cfg = _config.autoselect.get(actual_model) or asel_handler.user_autoselects.get(actual_model)
        if not asel_cfg:
            raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found")
        fallback = asel_cfg.fallback if hasattr(asel_cfg, 'fallback') else asel_cfg.get('fallback', '')
        if '/' in fallback:
            provider_id, actual_model = fallback.split('/', 1)
        elif fallback in _config.rotations:
            from aisbf.handlers import RotationHandler
            provider_id, actual_model = RotationHandler()._select_provider_and_model(fallback)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid fallback for autoselect '{actual_model}'")
    user_providers = getattr(handler, 'user_providers', {})
    if provider_id not in _config.providers and provider_id not in user_providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    body['model'] = actual_model
    return await handler.handle_generic_proxy(request, provider_id, endpoint_path, body, method=method)


async def _user_get_proxy(request: Request, username: str, provider: str, endpoint_path: str) -> JSONResponse:
    """Forward a GET request to the provider endpoint for a specific user."""
    user_id = _check_user_access(request, username)
    handler = _get_user_handler('request', user_id)
    user_providers = getattr(handler, 'user_providers', {})
    if not provider or (provider not in _config.providers and provider not in user_providers):
        available = list(_config.providers.keys()) + list(user_providers.keys())
        raise HTTPException(status_code=400, detail=f"Query param 'provider' required. Available: {available}")
    return await handler.handle_generic_proxy(request, provider, endpoint_path, {}, method="GET")


async def _user_delete_proxy(request: Request, username: str, provider: str, endpoint_path: str) -> JSONResponse:
    user_id = _check_user_access(request, username)
    handler = _get_user_handler('request', user_id)
    user_providers = getattr(handler, 'user_providers', {})
    if not provider or (provider not in _config.providers and provider not in user_providers):
        raise HTTPException(status_code=400, detail="Query param 'provider' required")
    return await handler.handle_generic_proxy(request, provider, endpoint_path, {}, method="DELETE")


async def _user_progress_proxy(request: Request, username: str, endpoint_path: str) -> JSONResponse:
    user_id = _check_user_access(request, username)
    handler = _get_user_handler('request', user_id)
    provider = request.query_params.get('provider', '').strip()
    model = request.query_params.get('model', '').strip()
    if not provider and model:
        provider, _ = parse_provider_from_model(model)
    if provider:
        return await handler.handle_generic_proxy(request, provider, endpoint_path, {}, method="GET")
    return {"active": False, "current": 0, "total": 0, "pct": 0, "elapsed": 0}


# ── Audio ─────────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/audio/transcriptions")
async def user_audio_transcriptions(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/transcriptions")

@router.post("/api/u/{username}/audio/speech")
async def user_audio_speech(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/speech")

@router.post("/api/u/{username}/audio/translations")
async def user_audio_translations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/translations")

@router.post("/api/u/{username}/audio/generations")
async def user_audio_generations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/generations")

@router.post("/api/u/{username}/audio/generate")
async def user_audio_generate_alias(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/generations")

@router.post("/api/u/{username}/audio/translate")
async def user_audio_translate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/translate")

@router.post("/api/u/{username}/audio/stems")
async def user_audio_stems(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/split")

@router.post("/api/u/{username}/audio/cleanup")
async def user_audio_cleanup(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/denoise")

@router.post("/api/u/{username}/audio/clone")
async def user_audio_clone(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/clone")

@router.post("/api/u/{username}/audio/convert")
async def user_audio_convert(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/convert")


@router.get("/api/u/{username}/audio/progress")
async def user_audio_progress(request: Request, username: str):
    return await _user_progress_proxy(request, username, "v1/audio/progress")

@router.post("/api/u/{username}/audio/identify")
async def user_audio_identify(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/identify")

@router.post("/api/u/{username}/audio/split")
async def user_audio_split(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/split")

@router.post("/api/u/{username}/audio/denoise")
async def user_audio_denoise(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/denoise")

@router.post("/api/u/{username}/audio/label")
async def user_audio_label(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/label")

@router.post("/api/u/{username}/audio/diarize")
async def user_audio_diarize(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/audio/diarize")


# ── Images ────────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/images/generations")
async def user_image_generations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/generations")

@router.post("/api/u/{username}/images/edits")
async def user_image_edits(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/edits")

@router.post("/api/u/{username}/images/variations")
async def user_image_variations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/variations")

@router.post("/api/u/{username}/images/upscale")
async def user_image_upscale(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/upscale")

@router.post("/api/u/{username}/images/inpaint")
async def user_image_inpaint(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/inpaint")

@router.post("/api/u/{username}/images/outpaint")
async def user_image_outpaint(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/outpaint")

@router.post("/api/u/{username}/images/caption")
async def user_image_caption(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/caption")

@router.post("/api/u/{username}/images/detect")
async def user_image_detect(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/detect")

@router.post("/api/u/{username}/images/segment")
async def user_image_segment(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/segment")

@router.post("/api/u/{username}/images/depth")
async def user_image_depth(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/depth")

@router.post("/api/u/{username}/images/restore")
async def user_image_restore(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/restore")

@router.post("/api/u/{username}/images/colorize")
async def user_image_colorize(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/colorize")

@router.post("/api/u/{username}/images/style-transfer")
async def user_image_style_transfer(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/style-transfer")

@router.post("/api/u/{username}/images/remove-bg")
async def user_image_remove_bg(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/remove-bg")

@router.post("/api/u/{username}/images/faceswap")
async def user_image_faceswap(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/faceswap")

@router.post("/api/u/{username}/images/deblur")
async def user_image_deblur(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/deblur")

@router.post("/api/u/{username}/images/unpixelate")
async def user_image_unpixelate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/unpixelate")

@router.post("/api/u/{username}/images/outfit")
async def user_image_outfit(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/outfit")

@router.post("/api/u/{username}/images/to3d")
async def user_image_to3d(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/to3d")

@router.post("/api/u/{username}/images/from3d")
async def user_image_from3d(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/images/from3d")


@router.get("/api/u/{username}/images/progress")
async def user_images_progress(request: Request, username: str):
    return await _user_progress_proxy(request, username, "v1/images/progress")


# ── Video ─────────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/video/generations")
async def user_video_generations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/generations")

@router.post("/api/u/{username}/video/animations")
async def user_video_animations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/animations")

@router.post("/api/u/{username}/video/edits")
async def user_video_edits(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/edits")

@router.post("/api/u/{username}/video/descriptions")
async def user_video_descriptions(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/descriptions")

@router.post("/api/u/{username}/video/transcriptions")
async def user_video_transcriptions(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/transcriptions")

@router.post("/api/u/{username}/video/upscale")
async def user_video_upscale(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/upscale")

@router.post("/api/u/{username}/video/interpolate")
async def user_video_interpolate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/interpolate")

@router.post("/api/u/{username}/video/subtitle")
async def user_video_subtitle(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/subtitle")

@router.post("/api/u/{username}/video/dub")
async def user_video_dub(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/dub")

@router.post("/api/u/{username}/video/to3d")
async def user_video_to3d(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/to3d")

@router.post("/api/u/{username}/video/from3d")
async def user_video_from3d(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/video/from3d")


@router.get("/api/u/{username}/video/progress")
async def user_video_progress(request: Request, username: str):
    return await _user_progress_proxy(request, username, "v1/video/progress")


# ── Embeddings ────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/embeddings")
async def user_embeddings(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/embeddings")


def _studio_user_scope(request: Request, username: str) -> tuple[str, Optional[int]]:
    user_id = _check_user_access(request, username)
    return "user", user_id


@router.get("/api/u/{username}/archive")
async def user_studio_archive(request: Request, username: str):
    scope, owner_id = _studio_user_scope(request, username)
    return {"files": studio_service.list_archive(scope, owner_id)}


@router.delete("/api/u/{username}/archive/{filename}")
async def user_studio_archive_delete(request: Request, username: str, filename: str):
    scope, owner_id = _studio_user_scope(request, username)
    archive_dir = studio_service._scope_dir(studio_service.archive_dir, scope, owner_id)
    target = archive_dir / filename
    if target.exists():
        target.unlink()
    return {"success": True}


@router.get("/api/u/{username}/characters")
async def user_studio_characters(request: Request, username: str):
    scope, owner_id = _studio_user_scope(request, username)
    return {"characters": studio_service.list_characters(scope, owner_id)}


@router.get("/api/u/{username}/characters/{name}")
async def user_studio_character_detail(request: Request, username: str, name: str):
    scope, owner_id = _studio_user_scope(request, username)
    item = studio_service.get_character(scope, owner_id, name)
    if not item:
        raise HTTPException(status_code=404, detail="Character not found")
    return item


@router.post("/api/u/{username}/characters/extract")
async def user_studio_character_extract(request: Request, username: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    return studio_service.save_character(scope, owner_id, body)


@router.post("/api/u/{username}/characters/generate")
async def user_studio_character_generate(request: Request, username: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    payload = dict(body)
    payload.setdefault("images", [])
    return studio_service.save_character(scope, owner_id, payload)


@router.get("/api/u/{username}/characters/{name}/thumbnail")
async def user_studio_character_thumbnail(request: Request, username: str, name: str):
    scope, owner_id = _studio_user_scope(request, username)
    payload = studio_service.get_character_thumbnail_bytes(scope, owner_id, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.get("/api/u/{username}/environments")
async def user_studio_environments(request: Request, username: str):
    scope, owner_id = _studio_user_scope(request, username)
    return {"environments": studio_service.list_environments(scope, owner_id)}


@router.get("/api/u/{username}/environments/{name}")
async def user_studio_environment_detail(request: Request, username: str, name: str):
    scope, owner_id = _studio_user_scope(request, username)
    item = studio_service.get_environment(scope, owner_id, name)
    if not item:
        raise HTTPException(status_code=404, detail="Environment not found")
    return item


@router.get("/api/u/{username}/environments/{name}/thumbnail")
async def user_studio_environment_thumbnail(request: Request, username: str, name: str):
    scope, owner_id = _studio_user_scope(request, username)
    payload = studio_service.get_environment_thumbnail_bytes(scope, owner_id, name)
    if not payload:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=payload, media_type="image/png")


@router.post("/api/u/{username}/environments/extract")
async def user_studio_environment_extract(request: Request, username: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    return studio_service.save_environment(scope, owner_id, body)


@router.post("/api/u/{username}/environments/generate")
async def user_studio_environment_generate(request: Request, username: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    payload = dict(body)
    payload.setdefault("images", [])
    return studio_service.save_environment(scope, owner_id, payload)


@router.get("/api/u/{username}/audio/voices")
async def user_studio_audio_voices(request: Request, username: str):
    scope, owner_id = _studio_user_scope(request, username)
    return {"voices": studio_service.list_voices(scope, owner_id)}


@router.post("/api/u/{username}/audio/voices")
async def user_studio_audio_voice_create(request: Request, username: str):
    form = await request.form()
    scope, owner_id = _studio_user_scope(request, username)
    payload = {
        "name": str(form.get("name") or f"voice-{int(time.time())}"),
        "description": str(form.get("description") or ""),
        "samples": [],
    }
    return studio_service.save_voice(scope, owner_id, payload)


@router.post("/api/u/{username}/audio/voices/extract")
async def user_studio_audio_voice_extract(request: Request, username: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    payload = {
        "name": body.get("name") or f"voice-{int(time.time())}",
        "description": body.get("description", ""),
        "quote": body.get("transcript", ""),
        "samples": body.get("samples", []),
    }
    return studio_service.save_voice(scope, owner_id, payload)


@router.delete("/api/u/{username}/audio/voices/{name}")
async def user_studio_audio_voice_delete(request: Request, username: str, name: str):
    scope, owner_id = _studio_user_scope(request, username)
    studio_service.delete_voice(scope, owner_id, name)
    return {"success": True}


@router.get("/api/u/{username}/pipelines/step-types")
async def user_studio_pipeline_step_types(request: Request, username: str):
    _studio_user_scope(request, username)
    return {"step_types": studio_service.pipeline_step_types()}


@router.get("/api/u/{username}/studio/function-bindings")
async def user_studio_function_bindings(request: Request, username: str):
    scope, owner_id = _studio_user_scope(request, username)
    return {
        "bindings": studio_service.list_function_bindings(scope, owner_id),
        "definitions": studio_service.function_binding_definitions(),
    }


@router.put("/api/u/{username}/studio/function-bindings/{binding_id}")
async def user_studio_function_binding_save(request: Request, username: str, binding_id: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    bindings = studio_service.save_function_binding(scope, owner_id, binding_id, body.get("roles") or {})
    return {"bindings": bindings, "binding_id": binding_id}


@router.delete("/api/u/{username}/studio/function-bindings/{binding_id}")
async def user_studio_function_binding_delete(request: Request, username: str, binding_id: str):
    scope, owner_id = _studio_user_scope(request, username)
    bindings = studio_service.delete_function_binding(scope, owner_id, binding_id)
    return {"bindings": bindings, "binding_id": binding_id}


@router.get("/api/u/{username}/pipelines/custom")
async def user_studio_pipeline_custom_list(request: Request, username: str):
    scope, owner_id = _studio_user_scope(request, username)
    return {"pipelines": studio_service.list_pipelines(scope, owner_id)}


@router.post("/api/u/{username}/pipelines/custom")
async def user_studio_pipeline_custom_create(request: Request, username: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    return {"pipeline": studio_service.save_pipeline(scope, owner_id, body)}


@router.put("/api/u/{username}/pipelines/custom/{pipeline_id}")
async def user_studio_pipeline_custom_update(request: Request, username: str, pipeline_id: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    payload = dict(body)
    payload["id"] = pipeline_id
    return {"pipeline": studio_service.save_pipeline(scope, owner_id, payload)}


@router.delete("/api/u/{username}/pipelines/custom/{pipeline_id}")
async def user_studio_pipeline_custom_delete(request: Request, username: str, pipeline_id: str):
    scope, owner_id = _studio_user_scope(request, username)
    studio_service.delete_pipeline(scope, owner_id, pipeline_id)
    return {"success": True}


@router.post("/api/u/{username}/pipelines/custom/{pipeline_id}/run")
async def user_studio_pipeline_custom_run(request: Request, username: str, pipeline_id: str, body: dict):
    scope, owner_id = _studio_user_scope(request, username)
    pipeline = studio_service.get_pipeline(scope, owner_id, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    payload = dict(pipeline)
    payload.update(body or {})
    payload["_api_base"] = f"/api/u/{username}"
    return studio_service.run_pipeline(payload)


@router.post("/api/u/{username}/pipelines/run")
async def user_studio_pipeline_run(request: Request, username: str, body: dict):
    _studio_user_scope(request, username)
    payload = dict(body or {})
    payload["_api_base"] = f"/api/u/{username}"
    return studio_service.run_pipeline(payload)


# ── Text / NLP ────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/moderations")
async def user_moderations(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/moderations")

@router.post("/api/u/{username}/translate")
async def user_translate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/translate")

@router.post("/api/u/{username}/summarize")
async def user_summarize(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/summarize")

@router.post("/api/u/{username}/classify")
async def user_classify(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/classify")

@router.post("/api/u/{username}/sentiment")
async def user_sentiment(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/sentiment")

@router.post("/api/u/{username}/ner")
async def user_ner(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/ner")

@router.post("/api/u/{username}/answers")
async def user_answers(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/answers")

@router.post("/api/u/{username}/reasoning")
async def user_reasoning(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/reasoning")

@router.post("/api/u/{username}/search")
async def user_search(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/search")

@router.post("/api/u/{username}/tools")
async def user_tools(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/tools")

@router.post("/api/u/{username}/function-call")
async def user_function_call(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/function-call")

@router.post("/api/u/{username}/parse")
async def user_parse(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/parse")


# ── Code ──────────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/code/generate")
async def user_code_generate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/code/generate")

@router.post("/api/u/{username}/code/complete")
async def user_code_complete(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/code/complete")

@router.post("/api/u/{username}/code/explain")
async def user_code_explain(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/code/explain")

@router.post("/api/u/{username}/code/refactor")
async def user_code_refactor(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/code/refactor")

@router.post("/api/u/{username}/code/review")
async def user_code_review(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/code/review")

@router.post("/api/u/{username}/code/test")
async def user_code_test(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/code/test")

@router.post("/api/u/{username}/math")
async def user_math(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/math")

@router.post("/api/u/{username}/reason")
async def user_reason(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/reason")


# ── Vision / Multimodal ───────────────────────────────────────────────────────

@router.post("/api/u/{username}/vision/describe")
async def user_vision_describe(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/vision/describe")

@router.post("/api/u/{username}/vision/ocr")
async def user_vision_ocr(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/vision/ocr")

@router.post("/api/u/{username}/vision/analyze")
async def user_vision_analyze(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/vision/analyze")

@router.post("/api/u/{username}/vision/detect")
async def user_vision_detect(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/vision/detect")

@router.post("/api/u/{username}/depth")
async def user_depth(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/depth")

@router.post("/api/u/{username}/pose")
async def user_pose(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/pose")


# ── 3D & Advanced ─────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/3d/generate")
async def user_3d_generate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/3d/generate")

@router.post("/api/u/{username}/3d/convert")
async def user_3d_convert(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/3d/convert")

@router.post("/api/u/{username}/animate")
async def user_animate(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/animate")

@router.post("/api/u/{username}/avatar")
async def user_avatar(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/avatar")

@router.post("/api/u/{username}/face-swap")
async def user_face_swap(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/face-swap")

@router.post("/api/u/{username}/face-restore")
async def user_face_restore(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/face-restore")


# ── Fine-tuning ───────────────────────────────────────────────────────────────

@router.get("/api/u/{username}/fine-tunes")
async def user_list_fine_tunes(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/fine-tunes")

@router.post("/api/u/{username}/fine-tunes")
async def user_create_fine_tune(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/fine-tunes")

@router.get("/api/u/{username}/fine-tunes/{job_id}")
async def user_get_fine_tune(job_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/fine-tunes/{job_id}")

@router.post("/api/u/{username}/fine-tunes/{job_id}/cancel")
async def user_cancel_fine_tune(job_id: str, request: Request, username: str, provider: str = ""):
    user_id = _check_user_access(request, username)
    handler = _get_user_handler('request', user_id)
    user_providers = getattr(handler, 'user_providers', {})
    if not provider or (provider not in _config.providers and provider not in user_providers):
        raise HTTPException(status_code=400, detail="Query param 'provider' required")
    return await handler.handle_generic_proxy(request, provider, f"v1/fine-tunes/{job_id}/cancel", {})


# ── Files ─────────────────────────────────────────────────────────────────────

@router.get("/api/u/{username}/files")
async def user_list_files(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/files")

@router.post("/api/u/{username}/files")
async def user_upload_file(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/files")

@router.get("/api/u/{username}/files/{file_id}")
async def user_get_file(file_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/files/{file_id}")

@router.delete("/api/u/{username}/files/{file_id}")
async def user_delete_file(file_id: str, request: Request, username: str, provider: str = ""):
    return await _user_delete_proxy(request, username, provider, f"v1/files/{file_id}")


# ── Assistants ────────────────────────────────────────────────────────────────

@router.get("/api/u/{username}/assistants")
async def user_list_assistants(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/assistants")

@router.post("/api/u/{username}/assistants")
async def user_create_assistant(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/assistants")

@router.get("/api/u/{username}/assistants/{assistant_id}")
async def user_get_assistant(assistant_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/assistants/{assistant_id}")

@router.delete("/api/u/{username}/assistants/{assistant_id}")
async def user_delete_assistant(assistant_id: str, request: Request, username: str, provider: str = ""):
    return await _user_delete_proxy(request, username, provider, f"v1/assistants/{assistant_id}")


# ── Threads ───────────────────────────────────────────────────────────────────

@router.get("/api/u/{username}/threads")
async def user_list_threads(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/threads")

@router.post("/api/u/{username}/threads")
async def user_create_thread(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/threads")

@router.get("/api/u/{username}/threads/{thread_id}")
async def user_get_thread(thread_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/threads/{thread_id}")

@router.post("/api/u/{username}/threads/{thread_id}/runs")
async def user_create_run(thread_id: str, request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, f"v1/threads/{thread_id}/runs")

@router.get("/api/u/{username}/threads/{thread_id}/runs")
async def user_list_runs(thread_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/threads/{thread_id}/runs")


# ── Vector stores ─────────────────────────────────────────────────────────────

@router.get("/api/u/{username}/vector-stores")
async def user_list_vector_stores(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/vector-stores")

@router.post("/api/u/{username}/vector-stores")
async def user_create_vector_store(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/vector-stores")

@router.get("/api/u/{username}/vector-stores/{store_id}")
async def user_get_vector_store(store_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/vector-stores/{store_id}")

@router.delete("/api/u/{username}/vector-stores/{store_id}")
async def user_delete_vector_store(store_id: str, request: Request, username: str, provider: str = ""):
    return await _user_delete_proxy(request, username, provider, f"v1/vector-stores/{store_id}")


# ── Batch ─────────────────────────────────────────────────────────────────────

@router.post("/api/u/{username}/batch")
async def user_create_batch(request: Request, username: str, body: dict):
    return await _user_generic_proxy(request, username, body, "v1/batch")

@router.get("/api/u/{username}/batch/{batch_id}")
async def user_get_batch(batch_id: str, request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, f"v1/batch/{batch_id}")


# ── Completions (legacy) ──────────────────────────────────────────────────────

@router.post("/api/u/{username}/completions")
async def user_completions(request: Request, username: str, body: dict):
    prompt = body.get("prompt", "")
    body.setdefault("messages", [{"role": "user", "content": prompt}])
    return await _user_generic_proxy(request, username, body, "v1/completions")

@router.post("/api/u/{username}/engines/{engine}/completions")
async def user_engines_completions(engine: str, request: Request, username: str, body: dict):
    if '--' in engine:
        provider_id, model = engine.split('--', 1)
    else:
        provider_id, model = parse_provider_from_model(engine)
        if not provider_id:
            raise HTTPException(status_code=400, detail="Engine must be in format 'provider--model' or 'provider/model'")
    body['model'] = f"{provider_id}/{model}"
    return await _user_generic_proxy(request, username, body, "v1/completions")

@router.post("/api/u/{username}/engines/{engine}/embeddings")
async def user_engines_embeddings(engine: str, request: Request, username: str, body: dict):
    if '--' in engine:
        provider_id, model = engine.split('--', 1)
    else:
        provider_id, model = parse_provider_from_model(engine)
        if not provider_id:
            raise HTTPException(status_code=400, detail="Engine must be in format 'provider--model' or 'provider/model'")
    body['model'] = f"{provider_id}/{model}"
    return await _user_generic_proxy(request, username, body, "v1/embeddings")


# ── Analytics & monitoring ────────────────────────────────────────────────────

@router.get("/api/u/{username}/usage")
async def user_usage(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/usage")

@router.get("/api/u/{username}/usage/costs")
async def user_usage_costs(request: Request, username: str, provider: str = ""):
    return await _user_get_proxy(request, username, provider, "v1/usage/costs")

@router.get("/api/u/{username}/providers/health")
async def user_providers_health(request: Request, username: str):
    user_id = _check_user_access(request, username)
    handler = _get_user_handler('request', user_id)
    from aisbf.providers import get_provider_handler as _get_ph
    health = {}
    all_providers = {**_config.providers, **getattr(handler, 'user_providers', {})}
    for provider_id, provider_config in all_providers.items():
        try:
            api_key = provider_config.get('api_key') if isinstance(provider_config, dict) else getattr(provider_config, 'api_key', None)
            h = _get_ph(provider_id, api_key, user_id=user_id)
            health[provider_id] = {"status": "unavailable" if h.is_rate_limited() else "ok"}
        except Exception as e:
            health[provider_id] = {"status": "error", "detail": str(e)}
    return health

@router.get("/api/u/{username}/cache/stats")
async def user_cache_stats(request: Request, username: str):
    _check_user_access(request, username)
    from aisbf.cache import get_response_cache
    cache = get_response_cache()
    try:
        return cache.stats() if hasattr(cache, 'stats') else {"status": "unavailable"}
    except Exception:
        return {"status": "unavailable"}
