from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import logging, time
from aisbf.models import ChatCompletionRequest
from aisbf.database import DatabaseRegistry
from aisbf.app.model_cache import get_provider_models

router = APIRouter()
_config = None
_get_user_handler = None

def init(config, get_user_handler_fn):
    global _config, _get_user_handler
    _config = config
    _get_user_handler = get_user_handler_fn

logger = logging.getLogger(__name__)

def parse_provider_from_model(model: str) -> tuple[str, str]:
    if '/' in model:
        parts = model.split('/', 1)
        return parts[0], parts[1]
    return None, model

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
