from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from aisbf.routes.auth import require_dashboard_auth, require_api_auth, require_admin
from aisbf.database import DatabaseRegistry
from aisbf.analytics import get_analytics
import json
import logging

router = APIRouter()
_templates = None
_config = None
logger = logging.getLogger(__name__)


def init(config, templates):
    global _config, _templates
    _config = config
    _templates = templates


def _ensure_market_enabled(request: Request, require_admin_override: bool = False):
    db = DatabaseRegistry.get_config_database()
    settings = db.get_market_settings()
    if settings.get('enabled'):
        return None, settings
    if require_admin_override and request.session.get('role') == 'admin':
        return None, settings
    return JSONResponse({'error': 'Market is disabled'}, status_code=403), settings


def _safe_provider_config(config_obj):
    if hasattr(config_obj, 'model_dump'):
        data = config_obj.model_dump()
    elif isinstance(config_obj, dict):
        data = dict(config_obj)
    else:
        data = vars(config_obj)
    return DatabaseRegistry.get_config_database()._sanitize_market_config(data)


def _safe_config(config_obj):
    return _safe_provider_config(config_obj)


def _listing_capabilities(listing: dict) -> list[str]:
    metadata = listing.get('metadata') or {}
    values = []
    for key in ('capabilities', 'partial_capabilities'):
        raw = metadata.get(key)
        if isinstance(raw, list):
            values.extend(str(item).strip().lower() for item in raw if str(item).strip())
    model_meta = metadata.get('model') or {}
    if isinstance(model_meta, dict):
        for key in ('capabilities', 'partial_capabilities'):
            raw = model_meta.get(key)
            if isinstance(raw, list):
                values.extend(str(item).strip().lower() for item in raw if str(item).strip())
    return sorted(set(values))


def _listing_size_value(listing: dict):
    metadata = listing.get('metadata') or {}
    model_meta = metadata.get('model') or {}
    for candidate in (
        model_meta.get('size'),
        model_meta.get('parameter_size'),
        model_meta.get('model_size'),
        metadata.get('size'),
        metadata.get('parameter_size'),
        metadata.get('model_size'),
    ):
        if candidate not in (None, ''):
            return str(candidate).strip().lower()
    return ''


def _listing_model_type(listing: dict):
    metadata = listing.get('metadata') or {}
    model_meta = metadata.get('model') or {}
    for candidate in (
        model_meta.get('type'),
        model_meta.get('family'),
        metadata.get('provider_type'),
        metadata.get('type'),
    ):
        if candidate not in (None, ''):
            return str(candidate).strip().lower()
    return ''


def _build_model_listing_payload(owner_user_id: int, owner_username: str, provider_id: str, provider_config: dict, model_config: dict, source_scope: str, form: dict):
    safe_provider = _safe_config(provider_config)
    safe_model = _safe_config(model_config)
    model_name = safe_model.get('name')
    provider_price_tokens = float(form.get('provider_price_per_million_tokens') or form.get('price_per_million_tokens') or 0)
    provider_price_requests = float(form.get('provider_price_per_1000_requests') or form.get('price_per_1000_requests') or 0)
    model_price_tokens = float(form.get('price_per_million_tokens') or provider_price_tokens)
    model_price_requests = float(form.get('price_per_1000_requests') or provider_price_requests)
    return {
        'owner_user_id': owner_user_id,
        'owner_username': owner_username,
        'source_scope': source_scope,
        'source_type': 'model',
        'source_id': f'{provider_id}/{model_name}',
        'listing_key': f'model:{provider_id}/{model_name}',
        'title': form.get('title') or f'{provider_id}/{model_name}',
        'description': form.get('description') or safe_model.get('description') or f'Market model share for {provider_id}/{model_name}',
        'provider_id': provider_id,
        'model_id': model_name,
        'endpoint': safe_provider.get('endpoint'),
        'currency_code': form.get('currency_code', 'USD'),
        'price_per_million_tokens': model_price_tokens,
        'price_per_1000_requests': model_price_requests,
        'provider_price_per_million_tokens': provider_price_tokens,
        'provider_price_per_1000_requests': provider_price_requests,
        'metadata': {
            'provider_type': safe_provider.get('type'),
            'model': safe_model,
            'source_scope': source_scope,
        },
        'config_snapshot': {
            'provider': safe_provider,
            'model': safe_model,
        },
        'is_active': True,
    }


def _build_rotation_listing_payload(owner_user_id: int, owner_username: str, rotation_id: str, rotation_config: dict, source_scope: str, form: dict):
    safe_rotation = _safe_config(rotation_config)
    return {
        'owner_user_id': owner_user_id,
        'owner_username': owner_username,
        'source_scope': source_scope,
        'source_type': 'rotation',
        'source_id': rotation_id,
        'listing_key': f'rotation:{rotation_id}',
        'title': form.get('title') or rotation_id,
        'description': form.get('description') or f'Market rotation share for {rotation_id}',
        'provider_id': None,
        'model_id': rotation_id,
        'endpoint': None,
        'currency_code': form.get('currency_code', 'USD'),
        'price_per_million_tokens': float(form.get('price_per_million_tokens') or 0),
        'price_per_1000_requests': float(form.get('price_per_1000_requests') or 0),
        'provider_price_per_million_tokens': None,
        'provider_price_per_1000_requests': None,
        'metadata': {
            'providers': safe_rotation.get('providers', []),
            'model_name': safe_rotation.get('model_name', rotation_id),
            'source_scope': source_scope,
        },
        'config_snapshot': safe_rotation,
        'is_active': True,
    }


def _build_autoselect_listing_payload(owner_user_id: int, owner_username: str, autoselect_id: str, autoselect_config: dict, source_scope: str, form: dict):
    safe_autoselect = _safe_config(autoselect_config)
    return {
        'owner_user_id': owner_user_id,
        'owner_username': owner_username,
        'source_scope': source_scope,
        'source_type': 'autoselect',
        'source_id': autoselect_id,
        'listing_key': f'autoselect:{autoselect_id}',
        'title': form.get('title') or autoselect_id,
        'description': form.get('description') or safe_autoselect.get('description') or f'Market autoselect share for {autoselect_id}',
        'provider_id': None,
        'model_id': autoselect_id,
        'endpoint': None,
        'currency_code': form.get('currency_code', 'USD'),
        'price_per_million_tokens': float(form.get('price_per_million_tokens') or 0),
        'price_per_1000_requests': float(form.get('price_per_1000_requests') or 0),
        'provider_price_per_million_tokens': None,
        'provider_price_per_1000_requests': None,
        'metadata': {
            'fallback': safe_autoselect.get('fallback'),
            'available_models': safe_autoselect.get('available_models', []),
            'source_scope': source_scope,
        },
        'config_snapshot': safe_autoselect,
        'is_active': True,
    }


def _attach_analytics_snapshot(listing: dict):
    analytics = get_analytics()
    source_type = listing.get('source_type')
    source_id = listing.get('source_id')
    snapshot = {'request_count': 0, 'avg_latency_ms': 0.0, 'error_rate': 0.0, 'total_tokens': 0}
    try:
        if source_type == 'provider' and listing.get('provider_id'):
            stats = analytics.get_provider_stats(listing.get('provider_id'))
            snapshot = {
                'request_count': (stats.get('requests') or {}).get('total', 0),
                'avg_latency_ms': stats.get('avg_latency_ms', 0.0),
                'error_rate': stats.get('error_rate', 0.0),
                'total_tokens': (stats.get('tokens') or {}).get('total', 0),
            }
        elif source_type == 'rotation':
            rows = analytics.get_rotation_provider_breakdown()
            entries = next((row.get('entries', []) for row in rows if row.get('rotation_id') == source_id), [])
            if entries:
                snapshot = {
                    'request_count': sum(int(item.get('requests', 0) or 0) for item in entries),
                    'avg_latency_ms': sum(float(item.get('avg_latency_ms', 0) or 0) for item in entries) / max(len(entries), 1),
                    'error_rate': 0.0,
                    'total_tokens': sum(int(item.get('tokens', 0) or 0) for item in entries),
                }
        elif source_type == 'autoselect':
            rows = analytics.get_autoselect_selection_breakdown()
            entries = next((row.get('entries', []) for row in rows if row.get('autoselect_id') == source_id), [])
            if entries:
                snapshot = {
                    'request_count': sum(int(item.get('requests', 0) or 0) for item in entries),
                    'avg_latency_ms': sum(float(item.get('avg_latency_ms', 0) or 0) for item in entries) / max(len(entries), 1),
                    'error_rate': 0.0,
                    'total_tokens': sum(int(item.get('tokens', 0) or 0) for item in entries),
                }
    except Exception as exc:
        logger.debug(f"Could not attach analytics snapshot for listing {listing.get('id')}: {exc}")
    listing['analytics'] = snapshot
    return listing


def _apply_listing_derived_fields(listing: dict, db):
    listing['votes'] = db.get_market_vote_summary(listing['id'])
    listing['stats'] = db.get_market_listing_stats(listing['id'])
    listing['capabilities'] = _listing_capabilities(listing)
    listing['model_type_label'] = _listing_model_type(listing)
    listing['size_label'] = _listing_size_value(listing)
    listing['online'] = False
    return _attach_analytics_snapshot(listing)


async def _build_provider_listing_payload(provider_id: str, provider_config, owner_user_id: int, owner_username: str, source_scope: str, form: dict):
    safe_config = _safe_provider_config(provider_config)
    models = []
    configured_models = safe_config.get('models', []) or []
    provider_price_tokens = float(form.get('price_per_million_tokens') or 0)
    provider_price_requests = float(form.get('price_per_1000_requests') or 0)

    for model in configured_models:
        model_name = model.get('name') if isinstance(model, dict) else getattr(model, 'name', None)
        if not model_name:
            continue
        model_prices = (form.get('model_prices') or {}).get(model_name, {})
        model_token_price = model_prices.get('price_per_million_tokens')
        model_request_price = model_prices.get('price_per_1000_requests')
        models.append({
            'name': model_name,
            'price_per_million_tokens': float(model_token_price) if model_token_price not in (None, '') else provider_price_tokens,
            'price_per_1000_requests': float(model_request_price) if model_request_price not in (None, '') else provider_price_requests,
        })

    return {
        'owner_user_id': owner_user_id,
        'owner_username': owner_username,
        'source_scope': source_scope,
        'source_type': 'provider',
        'source_id': provider_id,
        'listing_key': f'provider:{provider_id}',
        'title': form.get('title') or provider_id,
        'description': form.get('description') or f'Market provider share for {provider_id}',
        'provider_id': provider_id,
        'model_id': None,
        'endpoint': safe_config.get('endpoint'),
        'currency_code': form.get('currency_code', 'USD'),
        'price_per_million_tokens': provider_price_tokens,
        'price_per_1000_requests': provider_price_requests,
        'provider_price_per_million_tokens': provider_price_tokens,
        'provider_price_per_1000_requests': provider_price_requests,
        'metadata': {
            'provider_type': safe_config.get('type'),
            'models': models,
            'source_scope': source_scope,
        },
        'config_snapshot': safe_config,
        'is_active': True,
    }


@router.get('/dashboard/market', response_class=HTMLResponse)
async def dashboard_market(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    market_check, market_settings = _ensure_market_enabled(request)
    if market_check:
        return market_check

    db = DatabaseRegistry.get_config_database()
    listings = db.list_market_listings(active_only=True)

    def _listing_online(listing):
        provider_id = listing.get('provider_id')
        owner_user_id = listing.get('owner_user_id') if listing.get('source_scope') == 'user' else None
        if not provider_id:
            return True
        if db.get_provider_disabled_until(owner_user_id, provider_id):
            return False
        usage = db.get_provider_usage(owner_user_id, provider_id)
        return bool(usage and usage.get('usage_data') is not None)

    enriched = []
    current_user_id = request.session.get('user_id')
    for listing in listings:
        listing_copy = dict(listing)
        _apply_listing_derived_fields(listing_copy, db)
        listing_copy['online'] = _listing_online(listing_copy)
        owner = db.get_user_by_id(listing['owner_user_id']) if listing.get('owner_user_id') else None
        listing_copy['owner_display_name'] = (owner or {}).get('display_name') or listing.get('owner_username')
        enriched.append(listing_copy)

    return _templates.TemplateResponse(
        request=request,
        name='dashboard/market.html',
        context={
            'request': request,
            'session': request.session,
            'market_listings_json': json.dumps(enriched),
            'currency_symbol': db.get_currency_settings().get('currency_symbol', '$'),
            'current_user_id': current_user_id,
            'market_settings_json': json.dumps(market_settings),
        },
    )


@router.get('/api/market/listings')
async def api_market_listings(request: Request):
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    market_check, _ = _ensure_market_enabled(request)
    if market_check:
        return market_check
    db = DatabaseRegistry.get_config_database()
    listings = db.list_market_listings(active_only=request.query_params.get('include_inactive') != '1')
    query = (request.query_params.get('q') or '').strip().lower()
    source_type = (request.query_params.get('source_type') or '').strip().lower()
    capabilities = [item.strip().lower() for item in (request.query_params.get('capabilities') or '').split(',') if item.strip()]
    model_type = (request.query_params.get('model_type') or '').strip().lower()
    model_name = (request.query_params.get('model_name') or '').strip().lower()
    size = (request.query_params.get('size') or '').strip().lower()
    online_only = request.query_params.get('online_only') == '1'
    sort_by = (request.query_params.get('sort_by') or 'newest').strip().lower()

    def _listing_online(listing):
        provider_id = listing.get('provider_id')
        owner_user_id = listing.get('owner_user_id') if listing.get('source_scope') == 'user' else None
        if not provider_id:
            return True
        if db.get_provider_disabled_until(owner_user_id, provider_id):
            return False
        usage = db.get_provider_usage(owner_user_id, provider_id)
        return bool(usage and usage.get('usage_data') is not None)

    filtered = []
    for listing in listings:
        listing = _apply_listing_derived_fields(dict(listing), db)
        metadata = listing.get('metadata') or {}
        capability_values = listing.get('capabilities') or []
        listing_model_name = str(listing.get('model_id') or metadata.get('model_name') or (metadata.get('model') or {}).get('name') or '').lower()
        listing_model_type = listing.get('model_type_label') or ''
        listing_size = listing.get('size_label') or ''
        haystack = ' '.join([
            str(listing.get('title') or ''), str(listing.get('description') or ''),
            str(listing.get('provider_id') or ''), str(listing.get('model_id') or ''),
            str(metadata.get('provider_type') or ''), str(metadata.get('model_name') or ''),
            listing_model_type, listing_size, ' '.join(capability_values),
        ]).lower()
        if query and query not in haystack:
            continue
        if source_type and listing.get('source_type', '').lower() != source_type:
            continue
        if capabilities and not all(cap in capability_values or cap in haystack for cap in capabilities):
            continue
        if model_type and model_type not in listing_model_type and model_type not in haystack:
            continue
        if model_name and model_name not in listing_model_name and model_name not in haystack:
            continue
        if size and size not in listing_size and size not in haystack:
            continue
        listing['online'] = _listing_online(listing)
        if online_only and not listing['online']:
            continue
        filtered.append(listing)

    if sort_by == 'price_asc':
        filtered.sort(key=lambda item: (item.get('price_per_million_tokens') or 0, item.get('price_per_1000_requests') or 0, -(item.get('votes', {}).get('listing', {}).get('score', 0))))
    elif sort_by == 'price_desc':
        filtered.sort(key=lambda item: (-(item.get('price_per_million_tokens') or 0), -(item.get('price_per_1000_requests') or 0)))
    elif sort_by == 'upvotes':
        filtered.sort(key=lambda item: (-(item.get('votes', {}).get('listing', {}).get('score', 0)), -(item.get('votes', {}).get('user', {}).get('score', 0))))
    elif sort_by == 'performance':
        filtered.sort(key=lambda item: ((item.get('analytics', {}).get('avg_latency_ms') or 10**9), -(item.get('analytics', {}).get('request_count') or 0)))
    elif sort_by == 'requests':
        filtered.sort(key=lambda item: (-(item.get('stats', {}).get('total_requests') or 0), -(item.get('analytics', {}).get('request_count') or 0)))
    elif sort_by == 'revenue':
        filtered.sort(key=lambda item: (-(item.get('stats', {}).get('gross_revenue') or 0), -(item.get('stats', {}).get('provider_revenue') or 0)))
    else:
        filtered.sort(key=lambda item: str(item.get('created_at') or ''), reverse=True)

    return JSONResponse({'listings': filtered})


@router.post('/api/market/listings')
async def api_publish_market_listing(request: Request):
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    market_check, market_settings = _ensure_market_enabled(request, require_admin_override=True)
    if market_check:
        return market_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    is_admin = request.session.get('role') == 'admin'
    if not user_id and not is_admin:
        return JSONResponse({'error': 'Only authenticated configurations can be published to market'}, status_code=400)
    if user_id:
        if not market_settings.get('allow_user_publish', True):
            return JSONResponse({'error': 'User publishing is disabled'}, status_code=403)
        user = db.get_user_by_id(user_id)
        owner_user_id = user_id
        owner_username = user['username']
        source_scope = 'user'
    else:
        if not market_settings.get('allow_admin_publish', True):
            return JSONResponse({'error': 'Admin publishing is disabled'}, status_code=403)
        user = {'username': 'admin'}
        owner_user_id = 0
        owner_username = 'admin'
        source_scope = 'global'
    body = await request.json()
    source_type = body.get('source_type')
    source_id = body.get('source_id')
    if source_type == 'provider':
        if source_scope == 'user':
            user_provider = db.get_user_provider(user_id, source_id)
            if not user_provider:
                return JSONResponse({'error': 'Provider not found'}, status_code=404)
            provider_config = user_provider['config']
        else:
            provider_obj = _config.get_provider(source_id)
            if not provider_obj:
                return JSONResponse({'error': 'Provider not found'}, status_code=404)
            provider_config = provider_obj.model_dump() if hasattr(provider_obj, 'model_dump') else vars(provider_obj)
        payload = await _build_provider_listing_payload(
            source_id,
            provider_config,
            owner_user_id,
            owner_username,
            source_scope,
            body,
        )
    elif source_type == 'model':
        provider_id = body.get('provider_id')
        if source_scope == 'user':
            user_provider = db.get_user_provider(user_id, provider_id)
            if not user_provider:
                return JSONResponse({'error': 'Provider not found'}, status_code=404)
            provider_config = user_provider['config']
        else:
            provider_obj = _config.get_provider(provider_id)
            if not provider_obj:
                return JSONResponse({'error': 'Provider not found'}, status_code=404)
            provider_config = provider_obj.model_dump() if hasattr(provider_obj, 'model_dump') else vars(provider_obj)
        model_name = body.get('model_id')
        model_config = next(
            (
                m for m in (provider_config.get('models') or [])
                if ((m.get('name') if isinstance(m, dict) else getattr(m, 'name', None)) == model_name)
            ),
            None,
        )
        if not model_config:
            return JSONResponse({'error': 'Model not found'}, status_code=404)
        payload = _build_model_listing_payload(owner_user_id, owner_username, provider_id, provider_config, model_config, source_scope, body)
    elif source_type == 'rotation':
        if source_scope == 'user':
            rotation = db.get_user_rotation(user_id, source_id)
            if not rotation:
                return JSONResponse({'error': 'Rotation not found'}, status_code=404)
            rotation_config = rotation['config']
        else:
            rotation_obj = _config.get_rotation(source_id)
            if not rotation_obj:
                return JSONResponse({'error': 'Rotation not found'}, status_code=404)
            rotation_config = rotation_obj.model_dump() if hasattr(rotation_obj, 'model_dump') else vars(rotation_obj)
        payload = _build_rotation_listing_payload(owner_user_id, owner_username, source_id, rotation_config, source_scope, body)
    elif source_type == 'autoselect':
        if source_scope == 'user':
            autoselect = db.get_user_autoselect(user_id, source_id)
            if not autoselect:
                return JSONResponse({'error': 'Autoselect not found'}, status_code=404)
            autoselect_config = autoselect['config']
        else:
            autoselect_obj = _config.get_autoselect(source_id)
            if not autoselect_obj:
                return JSONResponse({'error': 'Autoselect not found'}, status_code=404)
            autoselect_config = autoselect_obj.model_dump() if hasattr(autoselect_obj, 'model_dump') else vars(autoselect_obj)
        payload = _build_autoselect_listing_payload(owner_user_id, owner_username, source_id, autoselect_config, source_scope, body)
    else:
        return JSONResponse({'error': 'Unsupported source_type'}, status_code=400)

    listing_id = db.upsert_market_listing(owner_user_id, owner_username, payload)
    return JSONResponse({'success': True, 'listing_id': listing_id})


@router.post('/api/market/listings/{listing_id}/import')
async def api_import_market_listing(request: Request, listing_id: int):
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    market_check, market_settings = _ensure_market_enabled(request)
    if market_check:
        return market_check
    if not market_settings.get('allow_import', True):
        return JSONResponse({'error': 'Market imports are disabled'}, status_code=403)
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse({'error': 'User account required'}, status_code=400)

    db = DatabaseRegistry.get_config_database()
    listing = db.get_market_listing(listing_id)
    if not listing or not listing.get('is_active'):
        return JSONResponse({'error': 'Listing not found'}, status_code=404)

    snapshot = listing.get('config_snapshot') or {}
    source_type = listing.get('source_type')
    source_id = listing.get('source_id')
    owner_username = listing.get('owner_username')
    import_id = f'market/{owner_username}/{source_id}'

    if source_type == 'provider':
        imported_config = dict(snapshot)
        imported_config['market_source'] = {
            'listing_id': listing_id,
            'owner_user_id': listing['owner_user_id'],
            'owner_username': owner_username,
            'provider_id': listing.get('provider_id'),
            'model_id': listing.get('model_id'),
            'source_type': source_type,
        }
        db.save_user_provider(user_id, import_id, imported_config)
        db.record_market_import(user_id, listing_id, 'provider', import_id)
        return JSONResponse({'success': True, 'imported_config_type': 'provider', 'imported_config_id': import_id})

    if source_type == 'model':
        provider_snapshot = dict((snapshot.get('provider') or {}))
        model_snapshot = dict((snapshot.get('model') or {}))
        provider_snapshot['models'] = [model_snapshot]
        provider_snapshot['market_source'] = {
            'listing_id': listing_id,
            'owner_user_id': listing['owner_user_id'],
            'owner_username': owner_username,
            'provider_id': listing.get('provider_id'),
            'model_id': listing.get('model_id'),
            'source_type': source_type,
        }
        model_import_id = f"market/{owner_username}/{listing.get('provider_id')}/{listing.get('model_id')}"
        db.save_user_provider(user_id, model_import_id, provider_snapshot)
        db.record_market_import(user_id, listing_id, 'provider', model_import_id)
        return JSONResponse({'success': True, 'imported_config_type': 'provider', 'imported_config_id': model_import_id})

    if source_type == 'rotation':
        imported_rotation_id = f'market/{owner_username}/{source_id}'
        imported_rotation = dict(snapshot)
        imported_rotation['market_source'] = {
            'listing_id': listing_id,
            'owner_user_id': listing['owner_user_id'],
            'owner_username': owner_username,
            'source_type': source_type,
        }
        db.save_user_rotation(user_id, imported_rotation_id, imported_rotation)
        db.record_market_import(user_id, listing_id, 'rotation', imported_rotation_id)
        return JSONResponse({'success': True, 'imported_config_type': 'rotation', 'imported_config_id': imported_rotation_id})

    if source_type == 'autoselect':
        imported_autoselect_id = f'market/{owner_username}/{source_id}'
        imported_autoselect = dict(snapshot)
        imported_autoselect['market_source'] = {
            'listing_id': listing_id,
            'owner_user_id': listing['owner_user_id'],
            'owner_username': owner_username,
            'source_type': source_type,
        }
        db.save_user_autoselect(user_id, imported_autoselect_id, imported_autoselect)
        db.record_market_import(user_id, listing_id, 'autoselect', imported_autoselect_id)
        return JSONResponse({'success': True, 'imported_config_type': 'autoselect', 'imported_config_id': imported_autoselect_id})

    return JSONResponse({'error': 'Unsupported listing type'}, status_code=400)


@router.post('/api/market/listings/{listing_id}/vote')
async def api_vote_market_listing(request: Request, listing_id: int):
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    market_check, _ = _ensure_market_enabled(request)
    if market_check:
        return market_check
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse({'error': 'User account required'}, status_code=400)
    body = await request.json()
    vote = int(body.get('vote', 0))
    target_type = body.get('target_type', 'listing')

    db = DatabaseRegistry.get_config_database()
    listing = db.get_market_listing(listing_id)
    if not listing:
        return JSONResponse({'error': 'Listing not found'}, status_code=404)

    target_map = {
        'listing': listing.get('listing_key'),
        'provider': listing.get('provider_id') or listing.get('listing_key'),
        'model': listing.get('model_id') or listing.get('listing_key'),
        'user': listing.get('owner_username'),
    }
    if target_type not in target_map:
        return JSONResponse({'error': 'Invalid vote target'}, status_code=400)

    db.upsert_market_vote(listing_id, user_id, target_type, target_map[target_type], vote)
    return JSONResponse({'success': True, 'votes': db.get_market_vote_summary(listing_id)})


@router.get('/api/market/me/exports')
async def api_my_market_exports(request: Request):
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    market_check, _ = _ensure_market_enabled(request, require_admin_override=True)
    if market_check:
        return market_check
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse({'exports': []})
    db = DatabaseRegistry.get_config_database()
    listings = [listing for listing in db.list_market_listings(active_only=False) if listing.get('owner_user_id') == user_id]
    return JSONResponse({'exports': listings})


@router.post('/api/market/listings/{listing_id}/toggle')
async def api_toggle_market_listing(request: Request, listing_id: int):
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    market_check, _ = _ensure_market_enabled(request, require_admin_override=True)
    if market_check:
        return market_check
    user_id = request.session.get('user_id')
    body = await request.json()
    db = DatabaseRegistry.get_config_database()
    if request.session.get('role') == 'admin' and (user_id is None or body.get('admin_override')):
        success = db.admin_set_market_listing_active(listing_id, bool(body.get('is_active', True)))
    else:
        success = db.set_market_listing_active(listing_id, user_id, bool(body.get('is_active', True)))
    if not success:
        return JSONResponse({'error': 'Listing not found or not owned by user'}, status_code=404)
    return JSONResponse({'success': True})


@router.get('/dashboard/admin/market', response_class=HTMLResponse)
async def dashboard_admin_market(request: Request):
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    db = DatabaseRegistry.get_config_database()
    listings = db.list_market_listings(active_only=False)
    enriched_listings = []
    for listing in listings:
        listing_copy = dict(listing)
        _apply_listing_derived_fields(listing_copy, db)
        enriched_listings.append(listing_copy)
    return _templates.TemplateResponse(
        request=request,
        name='dashboard/admin_market.html',
        context={
            'request': request,
            'session': request.session,
            'market_listings': enriched_listings,
        },
    )
