"""
Provider model fetching, caching, and background refresh.
Extracted from main.py.
"""
import time
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

_model_cache: dict = {}
_model_cache_timestamps: dict = {}
_cache_refresh_interval = 24 * 3600
_endpoint_model_cache: dict = {}
_background_tasks: set = set()


def _is_broker_only_coderai(provider_config) -> bool:
    provider_type = getattr(provider_config, 'type', '')
    if provider_type != 'coderai':
        return False
    coderai_config = getattr(provider_config, 'coderai_config', None) or {}
    if not isinstance(coderai_config, dict):
        return False
    return bool(coderai_config.get('broker_mode', False))


def _is_runpod_public_provider(provider_config) -> bool:
    provider_type = getattr(provider_config, 'type', '')
    if provider_type != 'runpod':
        return False
    runpod_config = getattr(provider_config, 'runpod_config', None) or {}
    if not isinstance(runpod_config, dict):
        return False
    return str(runpod_config.get('mode') or '').lower() == 'public'


def _cache_key_for_provider(provider_id: str, user_id: Optional[int] = None) -> str:
    return f"{provider_id}:{user_id}" if user_id is not None else provider_id


def _endpoint_cache_key(provider_config) -> Optional[str]:
    if provider_config is None:
        return None
    prov_type = getattr(provider_config, 'type', '') or ''
    endpoint = getattr(provider_config, 'endpoint', '') or ''
    if not prov_type and not endpoint:
        return None
    return f"{prov_type}:{endpoint}"


def _get_cached_provider_models(cache_key: str) -> Optional[list]:
    cached_at = _model_cache_timestamps.get(cache_key)
    if cached_at is None:
        return None
    if time.time() - cached_at >= _cache_refresh_interval:
        return None
    return _model_cache.get(cache_key)


def _store_provider_models_in_cache(cache_key: str, models: list, cached_at: Optional[float] = None) -> float:
    now = cached_at if cached_at is not None else time.time()
    _model_cache[cache_key] = models
    _model_cache_timestamps[cache_key] = now
    return now


def _get_cached_endpoint_models(endpoint_key: Optional[str]) -> Optional[tuple[list, float]]:
    if not endpoint_key:
        return None
    cached = _endpoint_model_cache.get(endpoint_key)
    if not cached:
        return None
    cached_models, cached_at = cached
    if time.time() - cached_at >= _cache_refresh_interval:
        return None
    return cached_models, cached_at


def _store_endpoint_models_in_cache(endpoint_key: Optional[str], models: list, cached_at: float) -> None:
    if not endpoint_key:
        return
    _endpoint_model_cache[endpoint_key] = (models, cached_at)


async def fetch_provider_models(provider_id: str, config, user_id: Optional[int] = None) -> list:
    global _model_cache, _model_cache_timestamps, _endpoint_model_cache

    cache_key = _cache_key_for_provider(provider_id, user_id)
    try:
        cached_models = _get_cached_provider_models(cache_key)
        if cached_models is not None:
            return cached_models

        provider_config = None
        endpoint_key = None
        if config is not None:
            try:
                provider_config = config.get_provider(provider_id)
                endpoint_key = _endpoint_cache_key(provider_config) if user_id is None else None
            except Exception:
                provider_config = None

        endpoint_cached = _get_cached_endpoint_models(endpoint_key)
        if endpoint_cached is not None:
            cached_models, cached_at = endpoint_cached
            _store_provider_models_in_cache(cache_key, cached_models, cached_at)
            return cached_models

        from aisbf.handlers import RequestHandler
        from starlette.requests import Request as StarletteRequest

        request_handler = RequestHandler(user_id=user_id)
        scope = {"type": "http", "method": "GET", "headers": [],
                 "query_string": b"", "path": f"/api/{provider_id}/models"}
        dummy_request = StarletteRequest(scope)

        models = await request_handler.handle_model_list(dummy_request, provider_id)

        now = _store_provider_models_in_cache(cache_key, models)
        _store_endpoint_models_in_cache(endpoint_key, models, now)

        logger.info(f"Cached {len(models)} models from provider: {provider_id}")
        return models
    except Exception as e:
        logger.error(f"Failed to fetch models from provider {provider_id}: {e}")
        return []


async def refresh_model_cache(config):
    global _endpoint_model_cache
    while True:
        try:
            await asyncio.sleep(_cache_refresh_interval)
            logger.info("Starting periodic model cache refresh...")
            _endpoint_model_cache.clear()
            for provider_id, provider_config in config.providers.items():
                if not (hasattr(provider_config, 'models') and provider_config.models):
                    await fetch_provider_models(provider_id, config)
            logger.info("Model cache refresh complete")
        except Exception as e:
            logger.error(f"Error in model cache refresh task: {e}")


async def get_provider_models(provider_id: str, provider_config, config, user_id: Optional[int] = None) -> list:
    current_time = int(time.time())

    if _is_runpod_public_provider(provider_config):
        from aisbf.database import DatabaseRegistry

        db = DatabaseRegistry.get_config_database()
        provider_scope = 'user' if user_id is not None else 'global'
        state = db.get_runpod_provider_state(provider_scope, user_id, provider_id)
        catalog = []
        if state:
            catalog = state.get('public_catalog_json') or []
        if catalog:
            models = []
            for item in catalog:
                model_id = item.get('id') or item.get('name') or ''
                if not model_id:
                    continue
                models.append({
                    'id': f"{provider_id}/{model_id}",
                    'object': 'model',
                    'created': current_time,
                    'owned_by': provider_config.name,
                    'provider': provider_id,
                    'type': 'provider',
                    'model_name': model_id,
                    'capabilities': item.get('capabilities', []),
                    'description': item.get('description'),
                    'architecture': item.get('architecture'),
                    'pricing': item.get('pricing'),
                    'supported_parameters': item.get('supported_parameters'),
                    'source': 'api_cache',
                })
            if models:
                return models

    try:
        from aisbf.providers import get_provider_handler
        api_key = getattr(provider_config, 'api_key', None)
        get_provider_handler(provider_id, api_key, user_id=user_id)
    except Exception as e:
        logger.debug(f"Skipping provider {provider_id}: {e}")
        return []

    if hasattr(provider_config, 'models') and provider_config.models:
        return [
            {
                'id': f"{provider_id}/{model.name}",
                'object': 'model',
                'created': current_time,
                'owned_by': provider_config.name,
                'provider': provider_id,
                'type': 'provider',
                'model_name': model.name,
                'context_size': getattr(model, 'context_size', None),
                'capabilities': getattr(model, 'capabilities', []),
                'description': getattr(model, 'description', None),
                'architecture': getattr(model, 'architecture', None),
                'pricing': getattr(model, 'pricing', None),
                'top_provider': getattr(model, 'top_provider', None),
                'supported_parameters': getattr(model, 'supported_parameters', None),
                'default_parameters': getattr(model, 'default_parameters', None),
                'source': 'local_config'
            }
            for model in provider_config.models
        ]

    cache_key = _cache_key_for_provider(provider_id, user_id)
    cached_models = _get_cached_provider_models(cache_key)
    if cached_models:
        models = []
        for model in cached_models:
            mc = model.copy()
            mc['id'] = f"{provider_id}/{model.get('id', model.get('name', ''))}"
            mc.setdefault('object', 'model')
            mc.setdefault('created', current_time)
            mc.setdefault('owned_by', provider_config.name)
            mc['provider'] = provider_id
            mc['type'] = 'provider'
            mc['source'] = 'api_cache'
            models.append(mc)
        return models

    api_key = getattr(provider_config, 'api_key', None)
    api_key_required = getattr(provider_config, 'api_key_required', True)
    if not api_key_required or (api_key and not api_key.startswith('YOUR_')):
        try:
            fetched = await fetch_provider_models(provider_id, config, user_id=user_id)
            if fetched:
                models = []
                for model in fetched:
                    mc = model.copy()
                    mc['id'] = f"{provider_id}/{model.get('id', model.get('name', ''))}"
                    mc.setdefault('object', 'model')
                    mc.setdefault('created', current_time)
                    mc.setdefault('owned_by', provider_config.name)
                    mc['provider'] = provider_id
                    mc['type'] = 'provider'
                    mc['source'] = 'api_cache'
                    models.append(mc)
                return models
        except Exception as e:
            logger.debug(f"Failed to fetch models for provider {provider_id}: {e}")

    return []


async def prefetch_global_provider_models(config):
    import os
    from aisbf.database import DatabaseRegistry

    logger.info("=== STARTUP MODEL PRE-FETCHING (background) ===")
    prefetch_count = 0
    total = 0

    for provider_id, provider_config in config.providers.items():
        total += 1
        if hasattr(provider_config, 'models') and provider_config.models:
            continue
        if _is_broker_only_coderai(provider_config):
            logger.info(f"Skipping model prefetch for broker-only CoderAI provider '{provider_id}' until a broker session connects")
            continue

        provider_type = getattr(provider_config, 'type', '')
        if provider_type in ('kilo', 'kilocode', 'coderai'):
            has_valid_auth = False
            api_key = getattr(provider_config, 'api_key', None)
            if api_key and not api_key.startswith('YOUR_'):
                has_valid_auth = True
            if provider_type == 'coderai':
                has_valid_auth = True
            if not has_valid_auth:
                try:
                    from aisbf.auth.kilo import KiloOAuth2
                    kilo_config = getattr(provider_config, 'kilo_config', None)
                    credentials_file = None
                    api_base = getattr(provider_config, 'endpoint', 'https://api.kilo.ai')
                    if kilo_config and isinstance(kilo_config, dict):
                        credentials_file = kilo_config.get('credentials_file')
                        if kilo_config.get('api_base'):
                            api_base = kilo_config['api_base']
                    oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=api_base)
                    if oauth2.is_authenticated():
                        has_valid_auth = True
                except Exception:
                    pass
            if not has_valid_auth:
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        for af in db.get_user_auth_files(0, provider_id):
                            if af.get('file_type') in ('credentials', 'kilo_credentials', 'config') and os.path.exists(af.get('file_path', '')):
                                has_valid_auth = True
                                break
                except Exception:
                    pass
            if not has_valid_auth:
                logger.info(f"Skipping model prefetch for Kilo provider '{provider_id}' (no valid auth)")
                continue

        try:
            models = await fetch_provider_models(provider_id, config)
            if models:
                prefetch_count += 1
                logger.info(f"✓ Pre-fetched {len(models)} models from provider: {provider_id}")
            else:
                logger.warning(f"✗ Pre-fetch returned empty model list from provider '{provider_id}'")
        except Exception as e:
            logger.error(f"✗ Failed to pre-fetch models from provider '{provider_id}': {e}")

    logger.info(f"=== MODEL PRE-FETCHING COMPLETE: {prefetch_count}/{total} providers ===")


def _apply_usage_disable(db, user_id, provider_id: str, usage_data: dict):
    import time as _time
    try:
        rl = usage_data.get('rate_limit') if usage_data else None
        if not rl:
            return
        windows = []
        if rl.get('primary_window'):
            windows.append(rl['primary_window'])
        if rl.get('secondary_window'):
            windows.append(rl['secondary_window'])
        windows.extend(rl.get('additional_rate_limits') or [])
        max_reset_at = None
        for w in windows:
            if w.get('used_percent', 0) >= 100 or rl.get('limit_reached'):
                reset_at = w.get('reset_at')
                if reset_at and (max_reset_at is None or reset_at > max_reset_at):
                    max_reset_at = float(reset_at)
        if max_reset_at and max_reset_at > _time.time():
            db.set_provider_disabled_until(user_id, provider_id, max_reset_at, 'usage_limit')
        else:
            db.clear_provider_disabled_until(user_id, provider_id)
    except Exception as e:
        logger.debug(f"_apply_usage_disable error for {provider_id}: {e}")


async def _refresh_provider_usage_if_stale(provider_id: str, user_id):
    try:
        import datetime as _dt
        from aisbf.database import DatabaseRegistry
        db = DatabaseRegistry.get_config_database()
        cached = db.get_provider_usage(user_id, provider_id)
        now = _dt.datetime.utcnow()
        if cached:
            lu = cached.get('last_updated')
            if lu:
                if hasattr(lu, 'utcoffset'):
                    lu = lu.replace(tzinfo=None)
                if isinstance(lu, str):
                    try:
                        lu = _dt.datetime.fromisoformat(lu)
                    except Exception:
                        lu = None
                if lu and (now - lu).total_seconds() < 120:
                    return
        from aisbf.providers import get_provider_handler
        handler = get_provider_handler(provider_id, user_id=user_id)
        if not handler.supports_usage():
            return
        usage_data = await handler.get_usage()
        if usage_data:
            usage_data = handler.normalize_usage_data(usage_data)
            db.save_provider_usage(user_id, provider_id, usage_data)
            _apply_usage_disable(db, user_id, provider_id, usage_data)
    except Exception as e:
        logger.debug(f"Background usage refresh failed for {provider_id}: {e}")
