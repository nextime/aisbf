from fastapi import APIRouter, Request, Form, Query, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response, StreamingResponse, FileResponse
from typing import Optional
import json, logging, os, time, re
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from aisbf.database import DatabaseRegistry
from aisbf.database import _hash_password as _db_hash_password
from aisbf import __version__
from aisbf.studio import build_studio_catalog, stamp_inferred_capabilities, serialize_studio_capability_choices, derive_aggregate_capabilities, normalize_capabilities
from aisbf.studio_adapters import serialize_studio_adapter_choices, serialize_studio_adapter_profile_choices, effective_studio_adapter, infer_studio_adapter_profile
from aisbf.studio_services import studio_service
from aisbf.app.templates import url_for, get_base_url
from aisbf.app.startup import _reload_global_config, _apply_condense_defaults_provider, _apply_condense_defaults_rotation, _providers_json_path, _rotations_json_path, _autoselect_json_path, _claude_cli_mode
from aisbf.app.middleware import _is_local_client
from aisbf.app.model_cache import fetch_provider_models
from aisbf.routes.auth import require_dashboard_auth, require_api_auth, require_api_admin, require_admin
from aisbf.providers.runpod import RunpodProviderHandler
import httpx

router = APIRouter()
_config = None
_templates = None
_server_config = None

logger = logging.getLogger(__name__)


def _serialize_market_reference(reference: dict, listing: dict | None) -> dict:
    listing = listing or {}
    return {
        'id': f"market-ref:{reference['id']}",
        'name': reference.get('display_name') or reference.get('source_id') or reference.get('reference_type') or 'Market Reference',
        'type': reference.get('reference_type'),
        'market_reference': True,
        'read_only': True,
        'owner_username': reference.get('owner_username'),
        'listing_id': reference.get('listing_id'),
        'source_type': reference.get('source_type'),
        'source_id': reference.get('source_id'),
        'availability': 'active' if listing.get('is_active') else 'unavailable',
    }


def _list_dashboard_market_references(db, user_id: int, reference_type: str) -> list[dict]:
    references = []
    for reference in db.list_market_import_references(user_id) or []:
        if reference.get('reference_type') != reference_type:
            continue
        listing = db.get_market_listing(reference.get('listing_id')) if reference.get('listing_id') else None
        references.append(_serialize_market_reference(reference, listing))
    return references


def _market_reference_provider_choice(reference: dict) -> dict:
    return {
        'provider_id': reference['id'],
        'config': {
            'type': reference.get('type') or reference.get('source_type') or 'market_reference',
            'name': reference.get('name') or reference['id'],
            'market_reference': True,
            'read_only': True,
            'models': [],
        },
    }


def _market_reference_rotation_choice(reference: dict) -> dict:
    return {
        'rotation_id': reference['id'],
        'name': reference.get('name') or reference['id'],
        'type': 'rotation',
        'market_reference': True,
        'read_only': True,
    }


def _serialize_provider_usage_snapshot(snapshot):
    if not snapshot:
        return None
    last_updated = snapshot.get('last_updated')
    if isinstance(last_updated, datetime):
        last_updated = last_updated.isoformat()
    return {
        'usage_data': snapshot.get('usage_data'),
        'last_updated': last_updated,
    }


def _provider_model_capability_lookup(providers: dict) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = {}
    for provider_id, provider_config in (providers or {}).items():
        models = provider_config.get('models') if isinstance(provider_config, dict) else getattr(provider_config, 'models', None)
        provider_type = provider_config.get('type', 'openai') if isinstance(provider_config, dict) else getattr(provider_config, 'type', 'openai')
        for model in models or []:
            stamped = stamp_inferred_capabilities(model if isinstance(model, dict) else model.model_dump(), provider_type)
            model_name = stamped.get('name') or stamped.get('id')
            if model_name:
                lookup[f"{provider_id}/{model_name}"] = normalize_capabilities(stamped.get('studio_capabilities'))
    return lookup


def _rotation_inherited_capabilities(rotation_config: dict, provider_lookup: dict[str, list[str]]) -> dict:
    capability_sets = []
    for provider in rotation_config.get('providers') or []:
        provider_id = provider.get('provider_id')
        models = provider.get('models') or []
        for model in models:
            model_name = model.get('name')
            if provider_id and model_name:
                capability_sets.append(provider_lookup.get(f"{provider_id}/{model_name}", []))
    derived = derive_aggregate_capabilities(capability_sets)
    rotation_config['capabilities'] = derived.capabilities
    rotation_config['partial_capabilities'] = derived.partial_capabilities
    return rotation_config


def _autoselect_inherited_capabilities(autoselect_config: dict, provider_lookup: dict[str, list[str]], rotations: dict | None = None) -> dict:
    capability_sets = []
    rotations = rotations or {}
    for model in autoselect_config.get('available_models') or []:
        model_id = (model.get('model_id') or '').strip()
        if not model_id:
            continue
        if model_id in rotations:
            rot_caps = normalize_capabilities(rotations[model_id].get('capabilities'))
            capability_sets.append(rot_caps)
        else:
            capability_sets.append(provider_lookup.get(model_id, []))
    derived = derive_aggregate_capabilities(capability_sets)
    autoselect_config['capabilities'] = derived.capabilities
    autoselect_config['partial_capabilities'] = derived.partial_capabilities
    return autoselect_config


def _stamp_provider_models(provider_config: dict) -> dict:
    stamped = dict(provider_config)
    provider_id = stamped.get("provider_id") or ""
    provider_type = stamped.get("type", "openai")
    models = stamped.get("models")
    if isinstance(models, list):
        stamped_models = []
        for model in models:
            if not isinstance(model, dict):
                stamped_models.append(model)
                continue
            stamped_model = stamp_inferred_capabilities(model, provider_type)
            stamped_model["studio_adapter"] = effective_studio_adapter(provider_type, stamped_model)
            stamped_model["studio_adapter_profile"] = infer_studio_adapter_profile(provider_id, provider_type, {**stamped_model, "provider_endpoint": stamped.get("endpoint")})
            stamped_models.append(stamped_model)
        stamped["models"] = stamped_models
    return stamped


def _json_parse_bootstrap(payload) -> str:
    raw_json = json.dumps(payload)
    escaped_json = (
        raw_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    quoted = escaped_json.replace("\\", "\\\\").replace('"', '\\"')
    quoted = quoted.replace("\\\\u003c", "\\u003c").replace("\\\\u003e", "\\u003e").replace("\\\\u0026", "\\u0026")
    return f'"{quoted}"'


def _ensure_coderai_token(provider_config: dict) -> dict:
    stamped = dict(provider_config or {})
    if stamped.get('type') != 'coderai':
        return stamped
    coderai_config = stamped.get('coderai_config')
    if not isinstance(coderai_config, dict):
        coderai_config = {}
    if 'registration_token' not in coderai_config:
        coderai_config['registration_token'] = secrets.token_urlsafe(32)
    stamped['coderai_config'] = coderai_config
    return stamped


def _normalize_runpod_provider_config(provider_id: str, provider_config: dict) -> dict:
    stamped = dict(provider_config or {})
    if stamped.get('type') != 'runpod':
        return stamped

    runpod_config = stamped.get('runpod_config')
    if not isinstance(runpod_config, dict):
        runpod_config = {}

    mode = str(runpod_config.get('mode') or 'pod').strip().lower()
    wrapper_mode = str(runpod_config.get('wrapper_mode') or 'openai').strip().lower()
    runpod_config['mode'] = mode
    runpod_config['management_api'] = str(runpod_config.get('management_api') or 'auto').strip().lower() or 'auto'
    runpod_config['account_name'] = str(runpod_config.get('account_name') or provider_id).strip() or provider_id
    runpod_config['startup_poll_interval_ms'] = int(runpod_config.get('startup_poll_interval_ms') or 3000)
    runpod_config['startup_timeout_ms'] = int(runpod_config.get('startup_timeout_ms') or 300000)
    runpod_config['idle_shutdown_ms'] = int(runpod_config.get('idle_shutdown_ms') or 900000)
    runpod_config['public_endpoint_protocol_default'] = str(runpod_config.get('public_endpoint_protocol_default') or 'auto').strip().lower() or 'auto'

    if mode == 'public':
        public_models = runpod_config.get('public_models')
        if not isinstance(public_models, dict):
            runpod_config['public_models'] = {}
    else:
        runpod_config['wrapper_mode'] = wrapper_mode

    stamped['runpod_config'] = runpod_config
    if not stamped.get('endpoint'):
        stamped['endpoint'] = 'https://rest.runpod.io/v1'
    return stamped


def _validate_runpod_provider_config(provider_id: str, provider_config: dict) -> None:
    if not isinstance(provider_config, dict) or provider_config.get('type') != 'runpod':
        return
    runpod_config = provider_config.get('runpod_config') or {}
    mode = str(runpod_config.get('mode') or 'pod').strip().lower()
    if mode not in {'pod', 'serverless_template', 'public'}:
        raise ValueError(f"RunPod provider '{provider_id}' has unsupported mode '{mode}'")
    if mode != 'public':
        wrapper_mode = str(runpod_config.get('wrapper_mode') or 'openai').strip().lower()
        if wrapper_mode not in {'openai', 'ollama', 'coderai'}:
            raise ValueError(f"RunPod provider '{provider_id}' has unsupported wrapper_mode '{wrapper_mode}'")
    if mode == 'pod' and not str(runpod_config.get('pod_id') or '').strip():
        raise ValueError(f"RunPod provider '{provider_id}' requires runpod_config.pod_id in pod mode")
    if mode == 'serverless_template' and not (str(runpod_config.get('endpoint_id') or '').strip() or str(runpod_config.get('serverless_template_id') or '').strip() or str(runpod_config.get('template_id') or '').strip()):
        raise ValueError(f"RunPod provider '{provider_id}' requires endpoint_id or template_id in serverless_template mode")


def _validate_coderai_provider_config(provider_id: str, provider_config: dict) -> None:
    if not isinstance(provider_config, dict) or provider_config.get('type') != 'coderai':
        return
    coderai_config = provider_config.get('coderai_config') or {}
    broker_enabled = coderai_config.get('broker_enabled', True)
    broker_mode = coderai_config.get('broker_mode', False)
    registration_token = coderai_config.get('registration_token')
    token_provided = isinstance(registration_token, str) and registration_token.strip() != ''
    if isinstance(registration_token, str):
        registration_token = registration_token.strip()
        coderai_config['registration_token'] = registration_token
    if (broker_enabled or broker_mode) and not token_provided:
        raise ValueError(f"CoderAI provider '{provider_id}' requires a registration token when broker sessions are enabled")
    provider_config['coderai_config'] = coderai_config


async def _load_coderai_broker_status_map() -> dict[str, dict]:
    from aisbf.coderai_broker import broker

    status_map: dict[str, dict] = {}
    for session in await broker.list_sessions():
        provider_id = session.get('provider_id')
        if not provider_id:
            continue
        status_map[provider_id] = session
    return status_map


def _augment_provider_broker_status(provider_id: str, provider_config: dict, broker_status_map: dict[str, dict]) -> dict:
    stamped = dict(provider_config)
    if stamped.get('type') != 'coderai':
        return stamped
    status = broker_status_map.get(provider_id)
    coderai_config = dict(stamped.get('coderai_config') or {})
    status_metadata = dict((status or {}).get('metadata') or {})
    status_performance = dict((status or {}).get('performance') or {})
    coderai_config['broker_session'] = {
        'connected': bool(status),
        'client_id': status.get('client_id') if status else None,
        'session_id': status.get('session_id') if status else None,
        'connected_at': status.get('connected_at') if status else None,
        'last_seen': status.get('last_seen') if status else None,
        'owner_user_id': status_metadata.get('owner_user_id'),
        'transport': status_metadata.get('transport'),
        'endpoint': status_metadata.get('endpoint'),
        'studio_endpoints': status_metadata.get('studio_endpoints') or [],
        'capabilities': (status or {}).get('capabilities') or {},
        'connection_state': status_metadata.get('connection_state') or ('connected' if status else 'disconnected'),
        'metadata': status_metadata,
        'performance': status_performance,
    }
    stamped['coderai_config'] = coderai_config
    return stamped

def init(config, templates, server_config=None):
    global _config, _templates, _server_config
    _config = config
    _templates = templates
    _server_config = server_config


def _get_templates():
    global _templates
    if _templates is None:
        from main import templates as main_templates
        _templates = main_templates
    return _templates


def get_user_auth_files_dir(user_id) -> Path:
    auth_files_dir = Path.home() / '.aisbf' / 'user_auth_files' / str(user_id)
    auth_files_dir.mkdir(parents=True, exist_ok=True)
    return auth_files_dir


def get_admin_auth_files_dir() -> Path:
    auth_files_dir = Path.home() / '.aisbf' / 'admin_auth_files'
    auth_files_dir.mkdir(parents=True, exist_ok=True)
    return auth_files_dir


def _apply_usage_disable(db, user_id, provider_id: str, usage_data: dict):
    pass


def _resolve_dashboard_provider_config(request: Request, provider_id: str) -> tuple[dict, Optional[int]]:
    current_user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    if current_user_id is None:
        provider = _config.providers.get(provider_id) if _config else None
        if provider is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        if hasattr(provider, "model_dump"):
            return provider.model_dump(), None
        if hasattr(provider, "dict"):
            return provider.dict(), None
        return dict(provider), None

    provider_row = db.get_user_provider(current_user_id, provider_id)
    if not provider_row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return dict(provider_row.get("config") or {}), current_user_id


def _build_dashboard_runpod_handler(request: Request, provider_id: str) -> RunpodProviderHandler:
    provider_config, owner_user_id = _resolve_dashboard_provider_config(request, provider_id)
    if provider_config.get("type") != "runpod":
        raise HTTPException(status_code=404, detail="RunPod provider not found")
    api_key = provider_config.get("api_key")
    return RunpodProviderHandler(provider_id, api_key=api_key, user_id=owner_user_id, provider_config=provider_config)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    """Dashboard overview page"""
    # Clear template cache to prevent unhashable dict errors
    _templates.env.cache.clear()
    
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Welcome modal and footer links are handled by dashboard_context_middleware
    # No need to override them here - request.state already has the correct values

    if request.session.get('role') == 'admin':
        # Admin dashboard
        db = DatabaseRegistry.get_config_database()
        users_count = len(db.get_users())
        return _get_templates().TemplateResponse(
            request=request,
            name="dashboard/index.html",
            context={
                "request": request,
                "session": request.session,
                "__version__": __version__,
                "providers_count": len(_config.providers) if _config else 0,
                "rotations_count": len(_config.rotations) if _config else 0,
                "autoselect_count": len(_config.autoselect) if _config else 0,
                "server_config": _server_config or {},
                "users_count": users_count,
            }
        )
    else:
        # User dashboard - show user stats
        db = DatabaseRegistry.get_config_database()
        user_id = request.session.get('user_id')
        
        # Get user statistics
        usage_stats = {
            'total_tokens': 0,
            'requests_today': 0
        }
        
        if user_id:
            # Get token usage for this user
            token_usage = db.get_user_token_usage(user_id)
            usage_stats['total_tokens'] = sum(row['token_count'] for row in token_usage)
            
            # Count requests today
            from datetime import datetime, timedelta
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            usage_stats['requests_today'] = len([
                row for row in token_usage
                if (datetime.fromisoformat(row['timestamp']) if isinstance(row['timestamp'], str) else row['timestamp']) >= today
            ])
            
            # Get user config counts
            providers_count = len(db.get_user_providers(user_id))
            rotations_count = len(db.get_user_rotations(user_id))
            autoselects_count = len(db.get_user_autoselects(user_id))
            
            # Get recent activity (last 10)
            recent_activity = token_usage[-10:] if token_usage else []
        else:
            providers_count = 0
            rotations_count = 0
            autoselects_count = 0
            recent_activity = []
        
        # Get subscription info
        subscription = db.get_user_subscription(user_id) if user_id else None
        current_tier = db.get_user_tier(user_id) if user_id else None
        payment_methods = db.get_user_payment_methods(user_id) if user_id else []
        all_tiers = db.get_visible_tiers() if user_id else []

        # Get currency settings
        currency_settings = db.get_currency_settings()
        currency_symbol = currency_settings.get('currency_symbol', '$')

        # Determine if there are higher tiers available to upgrade to
        upgrade_tiers = []
        if current_tier:
            for t in all_tiers:
                if not t.get('is_default') and t['price_monthly'] > current_tier.get('price_monthly', 0):
                    upgrade_tiers.append(t)
        elif all_tiers:
            upgrade_tiers = [t for t in all_tiers if not t.get('is_default')]

        return _get_templates().TemplateResponse(
        request=request,
        name="dashboard/user_index.html",
        context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "usage_stats": usage_stats,
            "providers_count": providers_count,
            "rotations_count": rotations_count,
            "autoselects_count": autoselects_count,
            "recent_activity": recent_activity,
            "subscription": subscription,
            "current_tier": current_tier,
            "payment_methods": payment_methods,
            "currency_symbol": currency_symbol,
            "upgrade_tiers": upgrade_tiers,
            "display_name": (db.get_user_by_id(user_id) or {}).get('display_name') or request.session.get('username', '') if user_id else request.session.get('username', '')
        }
    )

@router.get("/dashboard/providers", response_class=HTMLResponse)
async def dashboard_providers(request: Request):
    """Edit providers configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    broker_status_map = await _load_coderai_broker_status_map()

    if is_config_admin:
        # Config admin: prefer live in-memory config when available
        live_config = _config
        if live_config is None:
            from aisbf.config import config as global_config
            live_config = global_config
        if live_config and getattr(live_config, 'providers', None):
            providers_data = {
                provider_id: (provider.model_dump() if hasattr(provider, 'model_dump') else dict(provider))
                for provider_id, provider in live_config.providers.items()
            }
        else:
            config_path = Path.home() / '.aisbf' / 'providers.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'providers.json'
            
            with open(config_path) as f:
                full_config = json.load(f)
            
            # Extract just the providers object (handle both nested and flat structures)
            if 'providers' in full_config and isinstance(full_config['providers'], dict):
                providers_data = full_config['providers']
            else:
                # Fallback for flat structure (backward compatibility)
                providers_data = {k: v for k, v in full_config.items() if k != 'condensation'}
        providers_data = {
            provider_id: _augment_provider_broker_status(provider_id, _ensure_coderai_token(provider_config), broker_status_map)
            for provider_id, provider_config in providers_data.items()
        }
    else:
        # Database user: load from database
        db = DatabaseRegistry.get_config_database()
        user_providers = db.get_user_providers(current_user_id)

        # Apply stored sort order if any
        saved_order = db.get_sort_order(current_user_id, 'provider')
        if saved_order:
            order_map = {k: i for i, k in enumerate(saved_order)}
            user_providers = sorted(user_providers, key=lambda p: order_map.get(p['provider_id'], len(saved_order)))

        # Convert datetime objects to strings for JSON serialization
        for provider in user_providers:
            if 'created_at' in provider and provider['created_at']:
                provider['created_at'] = provider['created_at'].isoformat() if hasattr(provider['created_at'], 'isoformat') else str(provider['created_at'])
            if 'updated_at' in provider and provider['updated_at']:
                provider['updated_at'] = provider['updated_at'].isoformat() if hasattr(provider['updated_at'], 'isoformat') else str(provider['updated_at'])

        # Always pass raw user providers format to the template (array)
        for provider in user_providers:
            provider['config'] = _augment_provider_broker_status(
                provider['provider_id'],
                _ensure_coderai_token(provider['config']),
                broker_status_map,
            )
        provider_references = _list_dashboard_market_references(db, current_user_id, 'provider')
        for reference in provider_references:
            user_providers.append({
                'provider_id': reference['id'],
                'config': reference,
                'created_at': None,
                'updated_at': None,
            })
        providers_data = user_providers
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    if is_config_admin:
        # Config admin: use admin template
        return _templates.TemplateResponse(
            request=request,
            name="dashboard/providers.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "providers_data": providers_data,
            "studio_capability_choices": serialize_studio_capability_choices(),
            "studio_adapter_choices": serialize_studio_adapter_choices(),
            "studio_adapter_profile_choices": serialize_studio_adapter_profile_choices(),
            "claude_cli_mode": _claude_cli_mode,
            "is_local_client": _is_local_client(request),
            "success": "Configuration saved successfully!" if success else None
        }
        )
    else:
        # Database user: use user template with proper context
        return _templates.TemplateResponse(
            request=request,
            name="dashboard/user_providers.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "user_providers_data": providers_data,
            "user_providers_bootstrap_json": _json_parse_bootstrap(providers_data),
            "studio_capability_choices": serialize_studio_capability_choices(),
            "studio_adapter_choices": serialize_studio_adapter_choices(),
            "studio_adapter_profile_choices": serialize_studio_adapter_profile_choices(),
            "user_id": current_user_id,
            "claude_cli_mode": _claude_cli_mode,
            "is_local_client": _is_local_client(request),
            "success": "Configuration saved successfully!" if success else None
        }
        )


@router.get("/dashboard/studio", response_class=HTMLResponse)
async def dashboard_studio(request: Request):
    """Dashboard Studio shell page."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    current_user_id = request.session.get("user_id")
    is_config_admin = request.session.get("role") == "admin" and current_user_id is None
    scope = "admin" if is_config_admin else "user"
    db = None if is_config_admin else DatabaseRegistry.get_config_database()
    catalog = build_studio_catalog(
        scope=scope,
        owner_id=current_user_id,
        config=_config,
        db=db,
    )

    return _get_templates().TemplateResponse(
        request=request,
        name="dashboard/studio.html",
        context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "studio_bootstrap_json": json.dumps(catalog),
            "studio_root_path_json": json.dumps("/api/v1") if is_config_admin else json.dumps(f"/api/u/{request.session.get('username', '')}"),
            "studio_username_json": json.dumps(request.session.get("username", "")),
            "studio_is_global_admin_json": json.dumps(is_config_admin),
            "studio_system_prompt_json": json.dumps(studio_service.load_studio_system_prompt(scope, current_user_id)),
            "studio_body_mode": "wide",
        },
    )


@router.get("/dashboard/studio/catalog")
async def dashboard_studio_catalog(request: Request):
    """Return Studio catalog for the current dashboard principal."""
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check

    current_user_id = request.session.get("user_id")
    scope = "admin" if request.session.get("role") == "admin" else "user"
    db = None if scope == "admin" else DatabaseRegistry.get_config_database()

    catalog = build_studio_catalog(
        scope=scope,
        owner_id=current_user_id,
        config=_config,
        db=db,
    )
    return JSONResponse(catalog)


async def _auto_detect_provider_models(provider_key: str, provider: dict) -> list:
    """
    Auto-detect models from a provider's API endpoint.
    
    Tries to fetch models from the provider's /v1/models or /models endpoint.
    For Kilo providers, uses OAuth2 authentication if available.
    
    Args:
        provider_key: Provider identifier (e.g., 'kilo', 'my-openai-provider')
        provider: Provider configuration dict
        
    Returns:
        List of model dicts, or empty list if detection fails
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        endpoint = provider.get('endpoint', '')
        if not endpoint:
            logger.debug(f"No endpoint for provider '{provider_key}', skipping auto-detection")
            return []
        
        provider_type = provider.get('type', 'openai')
        api_key = provider.get('api_key', '')
        
        # Skip if API key is a placeholder
        if api_key and api_key.startswith('YOUR_'):
            api_key = ''
        
        # Check if this is a Kilo or CoderAI provider (by type or by endpoint URL)
        is_kilo_provider = provider_type in ('kilo', 'kilocode')
        is_coderai_provider = provider_type == 'coderai'
        if not is_kilo_provider:
            # Also check endpoint URL for Kilo domains
            kilo_domains = ['kilocode.ai', 'api.kilo.ai', 'kilo.ai']
            for domain in kilo_domains:
                if domain in endpoint:
                    is_kilo_provider = True
                    break

        if is_coderai_provider:
            from aisbf.providers.coderai import CoderAIProviderHandler
            handler = CoderAIProviderHandler(provider_key, api_key=api_key or None, provider_config=provider)
            models = await handler.get_models()
            detected_models = []
            for model in models:
                detected_models.append({
                    'name': model.name,
                    'rate_limit': 0,
                    'max_request_tokens': int(model.context_length) if model.context_length else 100000,
                    'context_size': int(model.context_length) if model.context_length else 100000,
                    'architecture': model.architecture,
                    'pricing': model.pricing,
                    'supported_parameters': model.supported_parameters,
                    'default_parameters': model.default_parameters,
                    'description': model.description,
                })
            detected_models = [stamp_inferred_capabilities(model, provider_type) for model in detected_models]
            logger.info(f"Auto-detected {len(detected_models)} models for CoderAI provider '{provider_key}'")
            return detected_models
        
        # For Kilo providers, try to get OAuth2 token
        if is_kilo_provider:
            from aisbf.auth.kilo import KiloOAuth2
            kilo_config = provider.get('kilo_config', {})
            credentials_file = kilo_config.get('credentials_file', '~/.kilo_credentials.json')
            oauth2 = KiloOAuth2(credentials_file=credentials_file, api_base=endpoint)
            token = await oauth2.get_valid_token()
            if token:
                api_key = token
                logger.info(f"Using OAuth2 token for Kilo provider '{provider_key}'")
            else:
                logger.warning(f"No OAuth2 token available for Kilo provider '{provider_key}', please authenticate first")
                return []
        
        # Skip if no authentication available
        if not api_key:
            logger.debug(f"No API key or token for provider '{provider_key}', skipping auto-detection")
            return []
        
        # Build models URL - try multiple paths
        models_url = None
        response_data = None
        
        for path in ['/v1/models', '/models']:
            test_url = endpoint.rstrip('/') + path
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    headers = {'Authorization': f'Bearer {api_key}'}
                    response = await client.get(test_url, headers=headers)
                    
                    if response.status_code == 200:
                        models_url = test_url
                        response_data = response.json()
                        break
                    elif response.status_code == 401:
                        logger.debug(f"Authentication failed for {test_url}")
                    else:
                        logger.debug(f"Got status {response.status_code} from {test_url}")
            except Exception as e:
                logger.debug(f"Error fetching {test_url}: {e}")
                continue
        
        if not models_url or not response_data:
            logger.debug(f"Could not reach models endpoint for provider '{provider_key}'")
            return []
        
        # Parse response - handle both OpenAI format {data: [...]} and array format
        models_list = response_data.get('data', response_data) if isinstance(response_data, dict) else response_data
        if not isinstance(models_list, list):
            logger.debug(f"Unexpected models response format for provider '{provider_key}'")
            return []
        
        # Convert to our model format
        detected_models = []
        for model_data in models_list:
            if isinstance(model_data, str):
                # Simple string model ID
                detected_models.append({
                    'name': model_data,
                    'rate_limit': 0,
                    'max_request_tokens': 100000,
                    'context_size': 100000
                })
            elif isinstance(model_data, dict):
                # Dict with id/name
                model_id = model_data.get('id', model_data.get('model', ''))
                if not model_id:
                    continue
                
                # Extract context size
                context_size = (
                    model_data.get('context_window') or
                    model_data.get('context_length') or
                    model_data.get('max_input_tokens')
                )
                
                detected_models.append({
                    'name': model_id,
                    'rate_limit': 0,
                    'max_request_tokens': int(context_size) if context_size else 100000,
                    'context_size': int(context_size) if context_size else 100000,
                    'capabilities': model_data.get('capabilities'),
                    'architecture': model_data.get('architecture'),
                })

        detected_models = [stamp_inferred_capabilities(model, provider_type) for model in detected_models]
        
        logger.info(f"Auto-detected {len(detected_models)} models for provider '{provider_key}' from {models_url}")
        return detected_models
        
    except Exception as e:
        logger.warning(f"Failed to auto-detect models for provider '{provider_key}': {e}")
        return []


@router.post("/dashboard/providers")
async def dashboard_providers_save(request: Request, config: str = Form(...)):
    """Save providers configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    try:
        # Validate JSON
        providers_data = json.loads(config)
        
        # Apply defaults: if condense_method is set but condense_context is not, default to 80
        for provider_key, provider in providers_data.items():
            provider = _ensure_coderai_token(provider)
            provider = _normalize_runpod_provider_config(provider_key, provider)
            _validate_coderai_provider_config(provider_key, provider)
            _validate_runpod_provider_config(provider_key, provider)
            if 'models' in provider and isinstance(provider['models'], list):
                for model in provider['models']:
                    if 'condense_method' in model and model.get('condense_method'):
                        if 'condense_context' not in model or model.get('condense_context') is None:
                            model['condense_context'] = 80
            providers_data[provider_key] = _stamp_provider_models(provider)
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'providers.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'providers.json'
            
            # Read existing config to preserve condensation settings
            with open(config_path) as f:
                full_config = json.load(f)
            
            # Update providers section while preserving other keys
            full_config['providers'] = providers_data
            
            # Save to file with full structure
            save_path = Path.home() / '.aisbf' / 'providers.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            # Database user: save to database
            db = DatabaseRegistry.get_config_database()
            
            # Get existing providers to find which to delete
            existing_providers = db.get_user_providers(current_user_id)
            existing_provider_keys = {p['provider_id'] for p in existing_providers}
            new_provider_keys = set(providers_data.keys())
            
            # Delete providers that are no longer present
            providers_to_delete = existing_provider_keys - new_provider_keys
            for provider_key in providers_to_delete:
                db.delete_user_provider(current_user_id, provider_key)
            
            # Save each provider to database
            for provider_key, provider_config in providers_data.items():
                db.save_user_provider(current_user_id, provider_key, provider_config)
            
            logger.info(f"Saved {len(providers_data)} provider(s) to database for user {current_user_id}")
        
        if is_config_admin:
            success_msg = "Configuration saved successfully!"
            if _templates is None:
                return JSONResponse({"success": True, "message": success_msg, "providers_data": providers_data})
            return _get_templates().TemplateResponse(
                request=request,
                name="dashboard/providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "providers_data": providers_data,
                    "studio_capability_choices": serialize_studio_capability_choices(),
                    "studio_adapter_choices": serialize_studio_adapter_choices(),
                    "studio_adapter_profile_choices": serialize_studio_adapter_profile_choices(),
                    "claude_cli_mode": _claude_cli_mode,
                    "is_local_client": _is_local_client(request),
                    "success": success_msg
                }
            )
        else:
            success_msg = "Configuration saved successfully!"
            if _templates is None:
                return JSONResponse({"success": True, "message": success_msg, "providers_data": providers_data})

            return _get_templates().TemplateResponse(
                request=request,
                name="dashboard/user_providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_providers_data": list(providers_data.values()),
                    "user_providers_bootstrap_json": _json_parse_bootstrap([
                        {"provider_id": provider_id, "config": provider_config}
                        for provider_id, provider_config in providers_data.items()
                    ]),
                    "studio_capability_choices": serialize_studio_capability_choices(),
                    "studio_adapter_choices": serialize_studio_adapter_choices(),
                    "studio_adapter_profile_choices": serialize_studio_adapter_profile_choices(),
                    "user_id": current_user_id,
                    "claude_cli_mode": _claude_cli_mode,
                    "is_local_client": _is_local_client(request),
                    "success": success_msg
                }
            )
    except json.JSONDecodeError as e:
        # Reload current config on error
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None

        if is_config_admin:
            config_path = Path.home() / '.aisbf' / 'providers.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'providers.json'
            with open(config_path) as f:
                full_config = json.load(f)

            # Extract providers
            if 'providers' in full_config and isinstance(full_config['providers'], dict):
                providers_data = full_config['providers']
            else:
                providers_data = {k: v for k, v in full_config.items() if k != 'condensation'}

            return _get_templates().TemplateResponse(
                request=request,
                name="dashboard/providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "providers_data": providers_data,
                    "studio_capability_choices": serialize_studio_capability_choices(),
                    "studio_adapter_choices": serialize_studio_adapter_choices(),
                    "studio_adapter_profile_choices": serialize_studio_adapter_profile_choices(),
                    "claude_cli_mode": _claude_cli_mode,
                    "is_local_client": _is_local_client(request),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)

            return _get_templates().TemplateResponse(
                request=request,
                name="dashboard/user_providers.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_providers_data": user_providers,
                    "user_providers_bootstrap_json": _json_parse_bootstrap(user_providers),
                    "studio_capability_choices": serialize_studio_capability_choices(),
                    "studio_adapter_choices": serialize_studio_adapter_choices(),
                    "studio_adapter_profile_choices": serialize_studio_adapter_profile_choices(),
                    "user_id": current_user_id,
                    "claude_cli_mode": _claude_cli_mode,
                    "is_local_client": _is_local_client(request),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )

@router.post("/dashboard/providers/get-models")
async def dashboard_providers_get_models(request: Request):
    """Fetch models from provider API"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    try:
        # Parse request body
        body = await request.json()
        provider_key = body.get('provider_key')
        
        if not provider_key:
            return JSONResponse({
                "success": False,
                "error": "provider_key is required"
            }, status_code=400)
        
        # Get user ID from session
        current_user_id = request.session.get('user_id')
        
        # Get provider handler - pass user_id to automatically handle user-specific providers
        from aisbf.providers import get_provider_handler
        
        try:
            handler = get_provider_handler(provider_key, user_id=current_user_id)
        except ValueError as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=404)
        
        # Fetch models from provider
        models_result = await handler.get_models()
        
        # Handle pending authorization status
        if isinstance(models_result, dict) and models_result.get("status") == "pending_authorization":
            return JSONResponse({
                "success": False,
                "authorization_required": True,
                "authorization_url": models_result.get("verification_url"),
                "device_code": models_result.get("code"),
                "expires_in": models_result.get("expires_in"),
                "poll_interval": models_result.get("poll_interval"),
                "message": f"Please visit {models_result.get('verification_url')} and enter code: {models_result.get('code')}"
            }, status_code=401)
        
        models = models_result
        
        # Convert Model objects to dicts with all available fields
        models_data = []
        for model in models:
            model_dict = {
                "id": model.id,
                "name": model.name,
                "provider_id": model.provider_id
            }
            
            # Add all optional fields if present
            optional_fields = [
                'weight', 'rate_limit', 'max_request_tokens',
                'rate_limit_TPM', 'rate_limit_TPH', 'rate_limit_TPD',
                'context_size', 'context_length', 'condense_context', 'condense_method',
                'error_cooldown', 'description', 'architecture', 'pricing',
                'top_provider', 'supported_parameters', 'default_parameters'
            ]
            
            for field in optional_fields:
                if hasattr(model, field):
                    value = getattr(model, field)
                    if value is not None:
                        model_dict[field] = value
            
            models_data.append(model_dict)
        
        return JSONResponse({
            "success": True,
            "models": models_data
        })
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching models for provider: {str(e)}", exc_info=True)
        
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

@router.get("/dashboard/providers/{provider_id}/configured-models")
async def get_provider_configured_models(request: Request, provider_id: str, search: str = ""):
    """Return model names from a provider's local config (no external API calls)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"models": []}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    provider = None
    if is_config_admin:
        config_path = Path.home() / '.aisbf' / 'providers.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'providers.json'
        with open(config_path) as f:
            full_config = json.load(f)
        if 'providers' in full_config and isinstance(full_config['providers'], dict):
            providers_data = full_config['providers']
        else:
            providers_data = {k: v for k, v in full_config.items() if k != 'condensation'}
        provider = providers_data.get(provider_id)
    else:
        db = DatabaseRegistry.get_config_database()
        user_providers = db.get_user_providers(current_user_id)
        match = next((p for p in user_providers if p['provider_id'] == provider_id), None)
        if match:
            provider = match.get('config', match)

    if not provider:
        return JSONResponse({"models": []})

    models = provider.get('models', [])
    model_names = [m.get('name', '') if isinstance(m, dict) else str(m) for m in models]
    model_names = [n for n in model_names if n]

    if search:
        search_lower = search.lower()
        model_names = [n for n in model_names if search_lower in n.lower()]

    return JSONResponse({"models": model_names[:50]})


@router.get("/dashboard/providers/{provider_id}/search-models")
async def search_provider_models_api(request: Request, provider_id: str, query: str = "", refresh: bool = False):
    """Search provider models; fetches from live API if local config has none or refresh=True."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"models": [], "error": "unauthorized"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    models = []
    if is_config_admin:
        try:
            config_path = Path.home() / '.aisbf' / 'providers.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'providers.json'
            with open(config_path) as f:
                full_config = json.load(f)
            if 'providers' in full_config and isinstance(full_config['providers'], dict):
                providers_data = full_config['providers']
            else:
                providers_data = {k: v for k, v in full_config.items() if k != 'condensation'}
            provider = providers_data.get(provider_id, {})
            raw = provider.get('models', [])
            models = [m.get('name', '') if isinstance(m, dict) else str(m) for m in raw]
            models = [n for n in models if n]
        except Exception:
            pass
    else:
        try:
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            match = next((p for p in user_providers if p['provider_id'] == provider_id), None)
            if match:
                prov = match.get('config', match)
                raw = prov.get('models', [])
                models = [m.get('name', '') if isinstance(m, dict) else str(m) for m in raw]
                models = [n for n in models if n]
        except Exception:
            pass

    fetched_live = False
    if not models or refresh:
        try:
            live = await fetch_provider_models(provider_id, user_id=current_user_id)
            if live:
                models = [m.get('name', m.get('id', '')) if isinstance(m, dict) else str(m) for m in live]
                models = [n for n in models if n]
                fetched_live = True
        except Exception:
            pass

    if query:
        q = query.lower()
        models = [m for m in models if q in m.lower()]

    return JSONResponse({"models": models[:200], "fetched_live": fetched_live})


@router.get("/dashboard/providers/{provider_id}/runpod-status")
async def api_runpod_provider_status(provider_id: str, request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    try:
        handler = _build_dashboard_runpod_handler(request, provider_id)
        return JSONResponse({"success": True, "status": handler.build_runtime_status()})
    except HTTPException as exc:
        return JSONResponse({"success": False, "error": exc.detail}, status_code=exc.status_code)
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@router.post("/dashboard/providers/{provider_id}/runpod-refresh")
async def api_runpod_provider_refresh(provider_id: str, request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    try:
        handler = _build_dashboard_runpod_handler(request, provider_id)
        catalog = await handler.refresh_public_catalog()
        return JSONResponse({
            "success": True,
            "catalog_count": len(catalog),
            "status": handler.build_runtime_status(),
        })
    except HTTPException as exc:
        return JSONResponse({"success": False, "error": exc.detail}, status_code=exc.status_code)
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@router.get("/dashboard/search-all-models")
async def search_all_models_api(request: Request, query: str = "", refresh: bool = False):
    """Return all available models (rotations + provider models) for autoselect, with optional live refresh."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"models": [], "error": "unauthorized"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    all_models = []

    if is_config_admin:
        if _config:
            for rid in _config.rotations:
                all_models.append({'id': rid, 'name': f'{rid} (rotation)', 'type': 'rotation'})
        try:
            providers_path = Path.home() / '.aisbf' / 'providers.json'
            if not providers_path.exists():
                providers_path = Path(__file__).parent / 'config' / 'providers.json'
            with open(providers_path) as f:
                pc = json.load(f)
            pd_map = pc.get('providers', {k: v for k, v in pc.items() if k != 'condensation'})
            for pid, prov in pd_map.items():
                pmodels = prov.get('models', [])
                if not pmodels and refresh:
                    try:
                        live = await fetch_provider_models(pid)
                        if live:
                            pmodels = live
                    except Exception:
                        pass
                for m in pmodels:
                    mname = m.get('name', m.get('id', '')) if isinstance(m, dict) else str(m)
                    if mname:
                        mid = f"{pid}/{mname}"
                        all_models.append({'id': mid, 'name': f"{mid} (provider model)", 'type': 'provider'})
        except Exception:
            pass
    else:
        try:
            db = DatabaseRegistry.get_config_database()
            for rot in db.get_user_rotations(current_user_id):
                rid = rot['rotation_id']
                all_models.append({'id': rid, 'name': f'{rid} (rotation)', 'type': 'rotation'})
            for prov in db.get_user_providers(current_user_id):
                pid = prov['provider_id']
                pconfig = prov.get('config', prov)
                pmodels = pconfig.get('models', [])
                if not pmodels and refresh:
                    try:
                        live = await fetch_provider_models(pid, user_id=current_user_id)
                        if live:
                            pmodels = live
                    except Exception:
                        pass
                for m in pmodels:
                    mname = m.get('name', m.get('id', '')) if isinstance(m, dict) else str(m)
                    if mname:
                        mid = f"{pid}/{mname}"
                        all_models.append({'id': mid, 'name': f"{mid} (provider model)", 'type': 'provider'})
        except Exception:
            pass

    if query:
        q = query.lower()
        all_models = [m for m in all_models if q in m['id'].lower() or q in m['name'].lower()]

    return JSONResponse({"models": all_models[:300]})


@router.get("/dashboard/rotations", response_class=HTMLResponse)
async def dashboard_rotations(request: Request):
    """Edit rotations configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    if is_config_admin:
        # Config admin: load from JSON files
        config_path = Path.home() / '.aisbf' / 'rotations.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'rotations.json'
        
        with open(config_path) as f:
            rotations_data = json.load(f)
    else:
        # Database user: load from database
        db = DatabaseRegistry.get_config_database()
        user_rotations = db.get_user_rotations(current_user_id)

        # Apply stored sort order if any
        saved_order = db.get_sort_order(current_user_id, 'rotation')
        if saved_order:
            order_map = {k: i for i, k in enumerate(saved_order)}
            user_rotations = sorted(user_rotations, key=lambda r: order_map.get(r['rotation_id'], len(saved_order)))

        # Convert to the format expected by the frontend
        rotations_data = {"rotations": {}, "notifyerrors": False}
        for rotation in user_rotations:
            rotations_data["rotations"][rotation['rotation_id']] = rotation['config']
        for reference in _list_dashboard_market_references(db, current_user_id, 'rotation'):
            rotations_data["rotations"][reference['id']] = reference
    
    # Get available providers - user-specific for database users
    if is_config_admin:
        # Admin: use global providers
        available_providers = list(_config.providers.keys()) if _config else []
        providers_meta = {k: {"type": getattr(v, 'type', 'openai')} for k, v in (_config.providers.items() if _config else {}.items())}
    else:
        # Database user: use ONLY their own providers
        db = DatabaseRegistry.get_config_database()
        user_providers = db.get_user_providers(current_user_id)
        provider_references = _list_dashboard_market_references(db, current_user_id, 'provider')
        available_provider_rows = user_providers + [_market_reference_provider_choice(reference) for reference in provider_references]
        available_providers = [p['provider_id'] for p in available_provider_rows]
        providers_meta = {p['provider_id']: {"type": p['config'].get('type', 'openai')} for p in available_provider_rows}

    # Check for success parameter
    success = request.query_params.get('success')

    if is_config_admin:
        # Config admin: use admin template
        return _templates.TemplateResponse(
            request=request,
            name="dashboard/rotations.html",
            context={
            "request": request,
            "session": request.session,
            "rotations_json": json.dumps(rotations_data),
            "available_providers": json.dumps(available_providers),
            "providers_meta": json.dumps(providers_meta),
            "success": "Configuration saved successfully!" if success else None
        }
        )
    else:
        # Database user: use user template
        return _templates.TemplateResponse(
            request=request,
            name="dashboard/user_rotations.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "rotations_json": json.dumps(rotations_data),
            "available_providers": json.dumps(available_providers),
            "providers_meta": json.dumps(providers_meta),
            "success": "Configuration saved successfully!" if success else None
        }
        )

@router.post("/dashboard/rotations")
async def dashboard_rotations_save(request: Request, config: str = Form(...)):
    """Save rotations configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    try:
        rotations_data = json.loads(config)
        provider_source = getattr(_config, 'providers', {}) if is_config_admin else {row['provider_id']: row['config'] for row in DatabaseRegistry.get_config_database().get_user_providers(current_user_id)}
        provider_lookup = _provider_model_capability_lookup(provider_source)
        
        # Apply defaults: if condense_method is set but condense_context is not, default to 80
        if 'rotations' in rotations_data:
            for rotation_key, rotation in rotations_data['rotations'].items():
                if 'providers' in rotation and isinstance(rotation['providers'], list):
                    for provider in rotation['providers']:
                        if 'models' in provider and isinstance(provider['models'], list):
                            for model in provider['models']:
                                if 'condense_method' in model and model.get('condense_method'):
                                    if 'condense_context' not in model or model.get('condense_context') is None:
                                        model['condense_context'] = 80
                rotations_data['rotations'][rotation_key] = _rotation_inherited_capabilities(rotation, provider_lookup)
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'rotations.json'
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(rotations_data, f, indent=2)
            _reload_global_config()
        else:
            # Database user: save to database
            db = DatabaseRegistry.get_config_database()

            rotations = rotations_data.get('rotations', {})

            # Delete rotations that are no longer present
            existing_rotations = db.get_user_rotations(current_user_id)
            existing_rotation_keys = {r['rotation_id'] for r in existing_rotations}
            new_rotation_keys = set(rotations.keys())
            for rotation_key in existing_rotation_keys - new_rotation_keys:
                db.delete_user_rotation(current_user_id, rotation_key)

            # Save each rotation to database
            for rotation_key, rotation_config in rotations.items():
                db.save_user_rotation(current_user_id, rotation_key, rotation_config)

            logger.info(f"Saved {len(rotations)} rotation(s) to database for user {current_user_id}")
        
        if is_config_admin:
            # Get global config safely
            from aisbf.config import config as global_config
            available_providers = list(global_config.providers.keys()) if global_config else []
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "success": "Configuration saved successfully!"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_rotations = db.get_user_rotations(current_user_id)
            
            # For database users, get their own providers
            user_providers = db.get_user_providers(current_user_id)
            available_providers = [p['provider_id'] for p in user_providers]
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/user_rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "user_id": current_user_id,
                    "success": "Configuration saved successfully!"
                }
            )
    except json.JSONDecodeError as e:
        # Reload current config on error
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if is_config_admin:
            config_path = Path.home() / '.aisbf' / 'rotations.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'rotations.json'
            with open(config_path) as f:
                rotations_data = json.load(f)
        else:
            db = DatabaseRegistry.get_config_database()
            user_rotations = db.get_user_rotations(current_user_id)
            rotations_data = {"rotations": {}, "notifyerrors": False}
            for rotation in user_rotations:
                rotations_data["rotations"][rotation['rotation_id']] = rotation['config']
        
        if is_config_admin:
            available_providers = list(_config.providers.keys()) if _config else []
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            available_providers = [p['provider_id'] for p in user_providers]
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/user_rotations.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_rotations_json": json.dumps(rotations_data),
                    "available_providers": json.dumps(available_providers),
                    "user_id": current_user_id,
                    "error": f"Invalid JSON: {str(e)}"
                }
            )

@router.get("/dashboard/autoselect", response_class=HTMLResponse)
async def dashboard_autoselect(request: Request):
    """Edit autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    if is_config_admin:
        # Config admin: load from JSON files
        config_path = Path.home() / '.aisbf' / 'autoselect.json'
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'autoselect.json'
        
        with open(config_path) as f:
            autoselect_data = json.load(f)
    else:
        # Database user: load from database
        db = DatabaseRegistry.get_config_database()
        user_autoselects = db.get_user_autoselects(current_user_id)

        # Apply stored sort order if any
        saved_order = db.get_sort_order(current_user_id, 'autoselect')
        if saved_order:
            order_map = {k: i for i, k in enumerate(saved_order)}
            user_autoselects = sorted(user_autoselects, key=lambda a: order_map.get(a['autoselect_id'], len(saved_order)))

        # Convert to the format expected by the frontend
        autoselect_data = {}
        for autoselect in user_autoselects:
            autoselect_data[autoselect['autoselect_id']] = autoselect['config']
        for reference in _list_dashboard_market_references(db, current_user_id, 'autoselect'):
            autoselect_data[reference['id']] = reference
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    if is_config_admin:
        # Admin: use global rotations and providers
        available_rotations = list(_config.rotations.keys()) if _config else []
        available_models = []
        
        # Add global rotation IDs
        for rotation_id in available_rotations:
            available_models.append({
                'id': rotation_id,
                'name': f'{rotation_id} (rotation)',
                'type': 'rotation'
            })
        
        # Add global provider models
        providers_path = Path.home() / '.aisbf' / 'providers.json'
        if not providers_path.exists():
            providers_path = Path(__file__).parent / 'config' / 'providers.json'
        
        admin_providers_meta = {}
        if providers_path.exists():
            with open(providers_path) as f:
                providers_config = json.load(f)
                providers_data = providers_config.get('providers', {})

                for provider_id, provider in providers_data.items():
                    admin_providers_meta[provider_id] = {"type": provider.get('type', 'openai')}
                    if 'models' in provider and isinstance(provider['models'], list):
                        for model in provider['models']:
                            model_id = f"{provider_id}/{model['name']}"
                            available_models.append({
                                'id': model_id,
                                'name': f"{model_id} (provider model)",
                                'type': 'provider'
                            })

        # Config admin: use admin template
        return _templates.TemplateResponse(
            request=request,
            name="dashboard/autoselect.html",
            context={
            "request": request,
            "session": request.session,
            "autoselect_json": json.dumps(autoselect_data),
            "available_rotations": json.dumps(available_rotations),
            "available_models": json.dumps(available_models),
            "providers_meta": json.dumps(admin_providers_meta),
            "success": "Configuration saved successfully!" if success else None
        }
        )
    else:
        # Database user: use ONLY their own rotations and providers
        db = DatabaseRegistry.get_config_database()
        user_autoselects = db.get_user_autoselects(current_user_id)

        # Get only user's own rotations
        user_rotations = db.get_user_rotations(current_user_id)
        rotation_references = _list_dashboard_market_references(db, current_user_id, 'rotation')
        available_rotation_rows = user_rotations + [_market_reference_rotation_choice(reference) for reference in rotation_references]
        available_rotations = [rot['rotation_id'] if 'rotation_id' in rot else rot['id'] for rot in available_rotation_rows]

        # Get only user's own providers
        user_providers = db.get_user_providers(current_user_id)
        provider_references = _list_dashboard_market_references(db, current_user_id, 'provider')
        available_provider_rows = user_providers + [_market_reference_provider_choice(reference) for reference in provider_references]
        available_models = []
        user_providers_meta = {p['provider_id']: {"type": p['config'].get('type', 'openai')} for p in available_provider_rows}

        # Add user rotation IDs
        for rotation in available_rotation_rows:
            rotation_id = rotation['rotation_id'] if 'rotation_id' in rotation else rotation['id']
            rotation_name = rotation.get('name') or rotation_id
            available_models.append({
                'id': rotation_id,
                'name': f'{rotation_name} (rotation)',
                'type': 'rotation'
            })

        # Add user provider models
        for provider in user_providers:
            provider_config = provider['config']
            if 'models' in provider_config and isinstance(provider_config['models'], list):
                for model in provider_config['models']:
                    model_id = f"{provider['provider_id']}/{model['name']}"
                    available_models.append({
                        'id': model_id,
                        'name': f"{model_id} (provider model)",
                        'type': 'provider'
                    })

        # Database user: use user template
        return _templates.TemplateResponse(
            request=request,
            name="dashboard/user_autoselects.html",
            context={
            "request": request,
            "session": request.session,
            "__version__": __version__,
            "autoselect_json": json.dumps(autoselect_data),
            "available_rotations": json.dumps(available_rotations),
            "available_models": json.dumps(available_models),
            "providers_meta": json.dumps(user_providers_meta),
            "user_id": current_user_id,
            "success": "Configuration saved successfully!" if success else None
        }
        )

@router.post("/dashboard/autoselect")
async def dashboard_autoselect_save(request: Request, config: str = Form(...)):
    """Save autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    
    try:
        autoselect_data = json.loads(config)
        provider_source = getattr(_config, 'providers', {}) if is_config_admin else {row['provider_id']: row['config'] for row in DatabaseRegistry.get_config_database().get_user_providers(current_user_id)}
        provider_lookup = _provider_model_capability_lookup(provider_source)
        rotation_source = getattr(_config, 'rotations', {}) if is_config_admin else {row['rotation_id']: row['config'] for row in DatabaseRegistry.get_config_database().get_user_rotations(current_user_id)}

        # Sanitize every autoselect entry before saving
        for key, cfg in autoselect_data.items():
            # Strip available_models with empty model_id
            original = cfg.get('available_models', [])
            valid = [m for m in original if (m.get('model_id') or '').strip()]
            if len(valid) != len(original):
                logger.warning(f"dashboard_autoselect_save: stripped {len(original) - len(valid)} empty model_id entry(s) from '{key}'")
                cfg['available_models'] = valid
            # Default selection_model to "internal" when blank
            if not (cfg.get('selection_model') or '').strip():
                cfg['selection_model'] = 'internal'
            autoselect_data[key] = _autoselect_inherited_capabilities(cfg, provider_lookup, rotation_source)

        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'autoselect.json'
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(autoselect_data, f, indent=2)
            _reload_global_config()
        else:
            # Database user: save to database
            db = DatabaseRegistry.get_config_database()

            # Delete autoselects that are no longer present
            existing_autoselects = db.get_user_autoselects(current_user_id)
            existing_autoselect_keys = {a['autoselect_id'] for a in existing_autoselects}
            new_autoselect_keys = set(autoselect_data.keys())
            for autoselect_key in existing_autoselect_keys - new_autoselect_keys:
                db.delete_user_autoselect(current_user_id, autoselect_key)

            # Save each autoselect to database
            for autoselect_key, autoselect_config in autoselect_data.items():
                db.save_user_autoselect(current_user_id, autoselect_key, autoselect_config)

            logger.info(f"Saved {len(autoselect_data)} autoselect(s) to database for user {current_user_id}")
        
        if is_config_admin:
            # Get global config safely
            from aisbf.config import config as global_config
            available_rotations = list(global_config.rotations.keys()) if global_config else []
            
            # Get available provider models
            available_models = []
            
            # Add rotation IDs
            for rotation_id in available_rotations:
                available_models.append({
                    'id': rotation_id,
                    'name': f'{rotation_id} (rotation)',
                    'type': 'rotation'
                })
            
            # Add provider models
            providers_path = Path.home() / '.aisbf' / 'providers.json'
            if not providers_path.exists():
                providers_path = Path(__file__).parent / 'config' / 'providers.json'
            
            if providers_path.exists():
                with open(providers_path) as f:
                    providers_config = json.load(f)
                    providers_data = providers_config.get('providers', {})
                    
                    for provider_id, provider in providers_data.items():
                        if 'models' in provider and isinstance(provider['models'], list):
                            for model in provider['models']:
                                model_id = f"{provider_id}/{model['name']}"
                                available_models.append({
                                    'id': model_id,
                                    'name': f"{model_id} (provider model)",
                                    'type': 'provider'
                                })
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/autoselect.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "autoselect_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "success": "Configuration saved successfully!"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            user_autoselects = db.get_user_autoselects(current_user_id)
            
            # For database users, get available user rotations
            user_rotations = db.get_user_rotations(current_user_id)
            available_rotations = [rot['rotation_id'] for rot in user_rotations]
            
            # For database users, get available user providers
            user_providers = db.get_user_providers(current_user_id)
            available_models = []
            
            # Add user rotation IDs
            for rotation_id in available_rotations:
                available_models.append({
                    'id': rotation_id,
                    'name': f'{rotation_id} (rotation)',
                    'type': 'rotation'
                })
            
            # Add user provider models
            for provider in user_providers:
                provider_config = provider['config']
                if 'models' in provider_config and isinstance(provider_config['models'], list):
                    for model in provider_config['models']:
                        model_id = f"{provider['provider_id']}/{model['name']}"
                        available_models.append({
                            'id': model_id,
                            'name': f"{model_id} (provider model)",
                            'type': 'provider'
                        })
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/user_autoselects.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_autoselects_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "user_id": current_user_id,
                    "success": "Configuration saved successfully!"
                }
            )
    except json.JSONDecodeError as e:
        # Reload current config on error
        current_user_id = request.session.get('user_id')
        is_config_admin = current_user_id is None
        
        if is_config_admin:
            config_path = Path.home() / '.aisbf' / 'autoselect.json'
            if not config_path.exists():
                config_path = Path(__file__).parent / 'config' / 'autoselect.json'
            with open(config_path) as f:
                autoselect_data = json.load(f)
        else:
            db = DatabaseRegistry.get_config_database()
            user_autoselects = db.get_user_autoselects(current_user_id)
            autoselect_data = {}
            for autoselect in user_autoselects:
                autoselect_data[autoselect['autoselect_id']] = autoselect['config']
        
        if is_config_admin:
            available_rotations = list(_config.rotations.keys()) if _config else []
            
            # Get available provider models
            available_models = []
            
            # Add rotation IDs
            for rotation_id in available_rotations:
                available_models.append({
                    'id': rotation_id,
                    'name': f'{rotation_id} (rotation)',
                    'type': 'rotation'
                })
            
            # Add provider models
            providers_path = Path.home() / '.aisbf' / 'providers.json'
            if not providers_path.exists():
                providers_path = Path(__file__).parent / 'config' / 'providers.json'
            
            if providers_path.exists():
                with open(providers_path) as f:
                    providers_config = json.load(f)
                    providers_data = providers_config.get('providers', {})
                    
                    for provider_id, provider in providers_data.items():
                        if 'models' in provider and isinstance(provider['models'], list):
                            for model in provider['models']:
                                model_id = f"{provider_id}/{model['name']}"
                                available_models.append({
                                    'id': model_id,
                                    'name': f"{model_id} (provider model)",
                                    'type': 'provider'
                                })
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/autoselect.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "autoselect_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "error": f"Invalid JSON: {str(e)}"
                }
            )
        else:
            db = DatabaseRegistry.get_config_database()
            
            # For database users, get available user rotations
            user_rotations = db.get_user_rotations(current_user_id)
            available_rotations = [rot['rotation_id'] for rot in user_rotations]
            
            # For database users, get available user providers
            user_providers = db.get_user_providers(current_user_id)
            available_models = []
            
            # Add user rotation IDs
            for rotation_id in available_rotations:
                available_models.append({
                    'id': rotation_id,
                    'name': f'{rotation_id} (rotation)',
                    'type': 'rotation'
                })
            
            # Add user provider models
            for provider in user_providers:
                provider_config = provider['config']
                if 'models' in provider_config and isinstance(provider_config['models'], list):
                    for model in provider_config['models']:
                        model_id = f"{provider['provider_id']}/{model['name']}"
                        available_models.append({
                            'id': model_id,
                            'name': f"{model_id} (provider model)",
                            'type': 'provider'
                        })
            
            return _templates.TemplateResponse(
                request=request,
                name="dashboard/user_autoselects.html",
                context={
                    "request": request,
                    "session": request.session,
                    "__version__": __version__,
                    "user_autoselects_json": json.dumps(autoselect_data),
                    "available_rotations": json.dumps(available_rotations),
                    "available_models": json.dumps(available_models),
                    "user_id": current_user_id,
                    "error": f"Invalid JSON: {str(e)}"
                }
            )

# ---------------------------------------------------------------------------
# Granular CRUD endpoints — act on a single provider/rotation/autoselect
# and trigger hot-reload of the in-memory config so no restart is needed.
# ---------------------------------------------------------------------------

@router.post("/dashboard/api/provider")
async def api_provider_save(request: Request):
    """Create or update a single provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        body = await request.json()
        provider_id = body.get('provider_id')
        provider_config = body.get('config', {})

        if not provider_id:
            return JSONResponse({"success": False, "error": "provider_id required"}, status_code=400)

        _apply_condense_defaults_provider(provider_config)
        provider_config = _ensure_coderai_token(provider_config)
        _validate_coderai_provider_config(provider_id, provider_config)
        provider_config = _stamp_provider_models(provider_config)

        if is_config_admin:
            config_path = _providers_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            if 'providers' not in full_config or not isinstance(full_config['providers'], dict):
                full_config['providers'] = {}
            full_config['providers'][provider_id] = provider_config
            save_path = Path.home() / '.aisbf' / 'providers.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.save_user_provider(current_user_id, provider_id, provider_config)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_provider_save error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/dashboard/api/provider/{provider_id:path}/coderai-token")
async def api_provider_coderai_token_rotate(request: Request, provider_id: str):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        if is_config_admin:
            config_path = _providers_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            providers = full_config.get('providers', full_config)
            provider_config = providers.get(provider_id)
            if not isinstance(provider_config, dict) or provider_config.get('type') != 'coderai':
                return JSONResponse({"success": False, "error": "CoderAI provider not found"}, status_code=404)
            provider_config.setdefault('coderai_config', {})
            provider_config['coderai_config']['registration_token'] = secrets.token_urlsafe(32)
            providers[provider_id] = provider_config
            full_config['providers'] = providers
            save_path = Path.home() / '.aisbf' / 'providers.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            record = db.get_user_provider(current_user_id, provider_id)
            provider_config = record['config'] if record else None
            if not isinstance(provider_config, dict) or provider_config.get('type') != 'coderai':
                return JSONResponse({"success": False, "error": "CoderAI provider not found"}, status_code=404)
            provider_config.setdefault('coderai_config', {})
            provider_config['coderai_config']['registration_token'] = secrets.token_urlsafe(32)
            db.save_user_provider(current_user_id, provider_id, provider_config)

        token = provider_config['coderai_config']['registration_token']
        return JSONResponse({"success": True, "registration_token": token})
    except Exception as e:
        logger.error(f"api_provider_coderai_token_rotate error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/dashboard/api/coderai/broker/sessions")
async def api_coderai_broker_sessions(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    from aisbf.coderai_broker import broker

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None
    sessions = await broker.list_sessions()
    filtered = []
    for session in sessions:
        owner_user_id = ((session.get('metadata') or {}).get('owner_user_id'))
        if not is_config_admin and owner_user_id != current_user_id:
            continue
        filtered.append(session)
    return JSONResponse({"success": True, "sessions": filtered})


@router.delete("/dashboard/api/provider/{provider_id:path}")
async def api_provider_delete(request: Request, provider_id: str):
    """Delete a single provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        if is_config_admin:
            config_path = _providers_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            providers = full_config.get('providers', full_config)
            providers.pop(provider_id, None)
            save_path = Path.home() / '.aisbf' / 'providers.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.delete_user_provider(current_user_id, provider_id)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_provider_delete error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/dashboard/api/provider/{provider_id:path}/usage")
async def api_provider_usage(request: Request, provider_id: str):
    """Return cached usage data for a provider, refreshing from source if stale (>5 min)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    STALE_SECONDS = 300  # 5 minutes

    # Check DB cache
    cached = db.get_provider_usage(current_user_id, provider_id)
    now = __import__('datetime').datetime.utcnow()

    def _age_seconds(last_updated):
        if last_updated is None:
            return float('inf')
        if hasattr(last_updated, 'utcoffset'):
            import datetime as _dt
            last_updated = last_updated.replace(tzinfo=None)
        if isinstance(last_updated, str):
            import datetime as _dt
            try:
                last_updated = _dt.datetime.fromisoformat(last_updated)
            except Exception:
                return float('inf')
        return (now - last_updated).total_seconds()

    if cached and _age_seconds(cached.get('last_updated')) < STALE_SECONDS:
        return JSONResponse({"success": True, "supported": True, "usage": cached['usage_data']})

    # Fetch fresh data
    try:
        from aisbf.providers import get_provider_handler
        handler = get_provider_handler(provider_id, user_id=current_user_id)
        if not handler.supports_usage():
            return JSONResponse({"success": True, "supported": False})
        usage_data = await handler.get_usage()
        if usage_data is None:
            if cached:
                return JSONResponse({"success": True, "supported": True, "usage": cached['usage_data'], "stale": True})
            return JSONResponse({"success": True, "supported": True, "usage": None})
        usage_data = handler.normalize_usage_data(usage_data)
        db.save_provider_usage(current_user_id, provider_id, usage_data)
        _apply_usage_disable(db, current_user_id, provider_id, usage_data)
        return JSONResponse({"success": True, "supported": True, "usage": usage_data})
    except Exception as e:
        logger.warning(f"api_provider_usage error for {provider_id}: {e}")
        if cached:
            return JSONResponse({"success": True, "supported": True, "usage": cached['usage_data'], "stale": True})
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/dashboard/api/rotation")
async def api_rotation_save(request: Request):
    """Create or update a single rotation"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        body = await request.json()
        rotation_id = body.get('rotation_id')
        rotation_config = body.get('config', {})

        if not rotation_id:
            return JSONResponse({"success": False, "error": "rotation_id required"}, status_code=400)

        _apply_condense_defaults_rotation(rotation_config)

        if is_config_admin:
            config_path = _rotations_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            if 'rotations' not in full_config or not isinstance(full_config['rotations'], dict):
                full_config['rotations'] = {}
            full_config['rotations'][rotation_id] = rotation_config
            save_path = Path.home() / '.aisbf' / 'rotations.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.save_user_rotation(current_user_id, rotation_id, rotation_config)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_rotation_save error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.delete("/dashboard/api/rotation/{rotation_id:path}")
async def api_rotation_delete(request: Request, rotation_id: str):
    """Delete a single rotation"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        if is_config_admin:
            config_path = _rotations_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            full_config.get('rotations', {}).pop(rotation_id, None)
            save_path = Path.home() / '.aisbf' / 'rotations.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.delete_user_rotation(current_user_id, rotation_id)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_rotation_delete error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/dashboard/api/autoselect")
async def api_autoselect_save(request: Request):
    """Create or update a single autoselect entry"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        body = await request.json()
        autoselect_id = body.get('autoselect_id')
        autoselect_config = body.get('config', {})

        if not autoselect_id:
            return JSONResponse({"success": False, "error": "autoselect_id required"}, status_code=400)

        # Reject entries with empty model_id
        available_models = autoselect_config.get('available_models', [])
        invalid = [m for m in available_models if not (m.get('model_id') or '').strip()]
        if invalid:
            return JSONResponse(
                {"success": False, "error": f"{len(invalid)} model(s) have an empty model_id — please select a model for each entry before saving."},
                status_code=400
            )

        # Default selection_model to "internal" when blank
        if not (autoselect_config.get('selection_model') or '').strip():
            autoselect_config['selection_model'] = 'internal'

        if is_config_admin:
            config_path = _autoselect_json_path()
            save_path = Path.home() / '.aisbf' / 'autoselect.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            if config_path.exists():
                with open(config_path) as f:
                    full_config = json.load(f)
            else:
                full_config = {}
            full_config[autoselect_id] = autoselect_config
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.save_user_autoselect(current_user_id, autoselect_id, autoselect_config)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_autoselect_save error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.delete("/dashboard/api/autoselect/{autoselect_id:path}")
async def api_autoselect_delete(request: Request, autoselect_id: str):
    """Delete a single autoselect entry"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        if is_config_admin:
            config_path = _autoselect_json_path()
            save_path = Path.home() / '.aisbf' / 'autoselect.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            if config_path.exists():
                with open(config_path) as f:
                    full_config = json.load(f)
            else:
                full_config = {}
            full_config.pop(autoselect_id, None)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.delete_user_autoselect(current_user_id, autoselect_id)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_autoselect_delete error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


def _reorder_dict(d: dict, order: list) -> dict:
    """Return a new dict with keys in the given order (unknown keys appended at end)."""
    result = {k: d[k] for k in order if k in d}
    for k, v in d.items():
        if k not in result:
            result[k] = v
    return result


@router.get("/dashboard/analytics", response_class=HTMLResponse)
async def dashboard_analytics(
    request: Request,
    time_range: str = Query("24h"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    provider_filter: Optional[str] = Query(None),
    model_filter: Optional[str] = Query(None),
    rotation_filter: Optional[str] = Query(None),
    autoselect_filter: Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None),
    global_only: Optional[str] = Query(None)
):
    """Token usage analytics dashboard"""
    from decimal import Decimal
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    from aisbf.analytics import get_analytics

    db = DatabaseRegistry.get_config_database()
    analytics = get_analytics(db)

    from_datetime = None
    to_datetime = None

    if from_date:
        try:
            from_datetime = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        except ValueError:
            pass

    if to_date:
        try:
            to_datetime = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        except ValueError:
            pass

    if time_range == 'yesterday':
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        from_datetime = today - timedelta(days=1)
        to_datetime = today - timedelta(microseconds=1)
    elif time_range == '1h':
        from_datetime = datetime.now() - timedelta(hours=1)
        to_datetime = datetime.now()
    elif time_range == '6h':
        from_datetime = datetime.now() - timedelta(hours=6)
        to_datetime = datetime.now()
    elif time_range == '7d':
        from_datetime = datetime.now() - timedelta(days=7)
        to_datetime = datetime.now()
    elif time_range == '30d':
        from_datetime = datetime.now() - timedelta(days=30)
        to_datetime = datetime.now()
    elif time_range == '90d':
        from_datetime = datetime.now() - timedelta(days=90)
        to_datetime = datetime.now()
    elif time_range == 'custom':
        if not from_datetime or not to_datetime:
            time_range = '24h'

    if from_datetime and to_datetime and time_range not in ['yesterday']:
        time_range = 'custom'

    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')

    user_filter_int = None
    if user_filter:
        try:
            user_filter_int = int(user_filter)
        except (ValueError, TypeError):
            pass

    if global_only == '1':
        user_filter_int = -1

    if not is_admin and current_user_id is not None:
        user_filter_int = current_user_id

    raw_users = db.get_users() if db and is_admin else []
    all_users = [
        {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in u.items()}
        for u in raw_users
    ]

    available_providers = list(_config.providers.keys()) if _config else []
    available_rotations = list(_config.rotations.keys()) if _config else []
    available_autoselects = list(_config.autoselect.keys()) if _config else []

    available_models = []
    if _config and hasattr(_config, 'providers'):
        for provider_id, provider_config in _config.providers.items():
            if hasattr(provider_config, 'models') and provider_config.models:
                for model in provider_config.models:
                    available_models.append(f"{provider_id}/{model.name}")

    effective_provider_filter = provider_filter
    effective_model_filter = model_filter
    if model_filter and '/' in model_filter:
        _p, _m = model_filter.split('/', 1)
        effective_provider_filter = effective_provider_filter or _p
        effective_model_filter = _m

    provider_stats = analytics.get_all_providers_stats(
        from_datetime, to_datetime, user_filter=user_filter_int,
        provider_filter=effective_provider_filter, model_filter=effective_model_filter,
        rotation_filter=rotation_filter, autoselect_filter=autoselect_filter
    )
    token_over_time = analytics.get_token_usage_over_time(
        provider_id=effective_provider_filter, time_range=time_range,
        from_datetime=from_datetime, to_datetime=to_datetime,
        user_filter=user_filter_int, model_filter=effective_model_filter,
        rotation_filter=rotation_filter, autoselect_filter=autoselect_filter
    )
    model_performance = analytics.get_model_performance(
        provider_filter=effective_provider_filter, model_filter=effective_model_filter,
        rotation_filter=rotation_filter, autoselect_filter=autoselect_filter,
        user_filter=user_filter_int, from_datetime=from_datetime, to_datetime=to_datetime
    )
    cost_overview = analytics.get_cost_overview(
        from_datetime, to_datetime, user_filter=user_filter_int,
        provider_filter=effective_provider_filter, model_filter=effective_model_filter,
        rotation_filter=rotation_filter, autoselect_filter=autoselect_filter
    )
    optimization_savings = analytics.get_savings_overview(
        from_datetime,
        to_datetime,
        user_filter=user_filter_int,
        provider_filter=effective_provider_filter,
        model_filter=effective_model_filter,
        rotation_filter=rotation_filter,
        autoselect_filter=autoselect_filter
    )

    date_range_usage = None
    if from_datetime or to_datetime:
        start = from_datetime or (datetime.now() - timedelta(days=1))
        end = to_datetime or datetime.now()
        date_range_usage = analytics.get_token_usage_by_date_range(
            effective_provider_filter,
            start,
            end,
            user_filter=user_filter_int,
            model_filter=effective_model_filter,
            rotation_filter=rotation_filter,
            autoselect_filter=autoselect_filter
        )

    rotation_breakdown = analytics.get_rotation_breakdown(
        from_datetime,
        to_datetime,
        user_filter=user_filter_int,
        rotation_filter=rotation_filter,
        provider_filter=effective_provider_filter,
        model_filter=effective_model_filter,
        autoselect_filter=autoselect_filter
    )
    autoselect_breakdown = analytics.get_autoselect_breakdown(
        from_datetime,
        to_datetime,
        user_filter=user_filter_int,
        autoselect_filter=autoselect_filter,
        provider_filter=effective_provider_filter,
        model_filter=effective_model_filter,
        rotation_filter=rotation_filter
    )

    is_config_admin = is_admin and current_user_id is None

    def decimal_default(obj):
        if isinstance(obj, Decimal):
            return int(obj)
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/analytics.html",
        context={
            "request": request,
            "session": request.session,
            "is_admin": is_admin,
            "is_config_admin": is_config_admin,
            "provider_stats": provider_stats,
            "token_over_time": json.dumps(token_over_time, default=decimal_default),
            "model_performance": model_performance,
            "cost_overview": cost_overview,
            "recommendations": [],
            "optimization_savings": optimization_savings,
            "selected_time_range": time_range,
            "from_date": from_date,
            "to_date": to_date,
            "date_range_usage": date_range_usage,
            "available_providers": available_providers,
            "available_models": available_models,
            "available_rotations": available_rotations,
            "available_autoselects": available_autoselects,
            "available_users": all_users,
            "selected_provider": provider_filter,
            "selected_model": model_filter,
            "selected_rotation": rotation_filter,
            "selected_autoselect": autoselect_filter,
            "selected_user": user_filter,
            "global_only": global_only,
            "currency_symbol": db.get_currency_settings().get('currency_symbol', '$'),
            "rotation_breakdown": rotation_breakdown,
            "autoselect_breakdown": autoselect_breakdown,
        }
    )


@router.get("/dashboard/analytics/provider-quotas", response_class=HTMLResponse)
async def dashboard_analytics_provider_quotas(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    current_user_id = request.session.get('user_id')
    is_admin = request.session.get('role') == 'admin'

    provider_ids = []
    if _config and getattr(_config, 'providers', None):
        provider_ids.extend(list(_config.providers.keys()))

    if current_user_id is not None:
        try:
            for provider in db.get_user_providers(current_user_id):
                provider_id = provider.get('provider_id')
                if provider_id and provider_id not in provider_ids:
                    provider_ids.append(provider_id)
        except Exception:
            pass

    provider_rows = []
    analytics = None
    try:
        from aisbf.analytics import get_analytics
        analytics = get_analytics(db)
    except Exception:
        analytics = None

    for provider_id in sorted(set(provider_ids)):
        global_snapshot = _serialize_provider_usage_snapshot(db.get_provider_usage(None, provider_id)) if is_admin else None
        user_snapshot = _serialize_provider_usage_snapshot(db.get_provider_usage(current_user_id, provider_id)) if current_user_id is not None else None

        free_tier_info = analytics._get_provider_free_tier_info(provider_id) if analytics else None
        normalized_quota = None
        if analytics:
            source_usage = None
            if user_snapshot and user_snapshot.get('usage_data'):
                source_usage = user_snapshot['usage_data']
            elif global_snapshot and global_snapshot.get('usage_data'):
                source_usage = global_snapshot['usage_data']
            normalized_quota = analytics._derive_quota_from_usage(provider_id, source_usage)

        provider_rows.append({
            'provider_id': provider_id,
            'free_tier_info': free_tier_info,
            'normalized_quota': normalized_quota,
            'global_snapshot': global_snapshot,
            'user_snapshot': user_snapshot,
        })

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/provider_quotas.html",
        context={
            'request': request,
            'session': request.session,
            'is_admin': is_admin,
            'provider_rows': provider_rows,
        }
    )
