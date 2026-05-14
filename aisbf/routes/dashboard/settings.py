from fastapi import APIRouter, Request, Form, Query, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response, StreamingResponse
from typing import Optional
import json, logging, os, time, re
from pathlib import Path
from datetime import datetime, timedelta
from aisbf.database import DatabaseRegistry
from aisbf.database import _hash_password as _db_hash_password
from aisbf import __version__
from aisbf.app.templates import url_for, get_base_url
from aisbf.app.startup import (_reload_global_config, _apply_condense_defaults_provider,
    _apply_condense_defaults_rotation, _providers_json_path, _rotations_json_path,
    _autoselect_json_path, get_aisbf_config_path, _user_handlers_cache, get_user_handler)
from aisbf.routes.auth import require_dashboard_auth, require_api_auth, require_api_admin, require_admin

router = APIRouter()
_config = None
_templates = None

logger = logging.getLogger(__name__)


def _feature_mode_payload(mode: str) -> dict:
    return {'mode': mode}


def _set_feature_control(feature_controls: dict, key: str, mode: str) -> None:
    feature_controls[key] = _feature_mode_payload(mode)


def _set_prompt_security_control(feature_controls: dict, key: str, mode: str) -> None:
    prompt_security = feature_controls.setdefault('prompt_security', {})
    prompt_security[key] = _feature_mode_payload(mode)


def _set_prompt_security_threshold(feature_controls: dict, threshold: str) -> None:
    prompt_security = feature_controls.setdefault('prompt_security', {})
    normalized = str(threshold or 'high').strip().lower()
    if normalized not in {'low', 'medium', 'high'}:
        normalized = 'high'
    prompt_security['risk_threshold'] = normalized


def _record_dashboard_admin_event(request: Request, event_type: str, **kwargs) -> None:
    try:
        db = DatabaseRegistry.get_config_database()
        db.record_dashboard_event(
            event_type=event_type,
            path=request.url.path,
            user_id=request.session.get('user_id'),
            username=request.session.get('username'),
            method=request.method,
            **kwargs,
        )
    except Exception:
        logger.debug("Failed to record dashboard admin event %s", event_type, exc_info=True)


def _reorder_dict(d: dict, order: list) -> dict:
    """Return a new dict with keys in the given order (unknown keys appended at end)."""
    result = {k: d[k] for k in order if k in d}
    for k, v in d.items():
        if k not in result:
            result[k] = v
    return result


def init(config, templates):
    global _config, _templates
    _config = config
    _templates = templates


@router.post("/dashboard/api/provider/reorder")
async def api_provider_reorder(request: Request):
    """Persist a new display order for providers."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        body = await request.json()
        order = body.get('order', [])
        if not isinstance(order, list):
            return JSONResponse({"success": False, "error": "order must be a list"}, status_code=400)

        if is_config_admin:
            config_path = _providers_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            providers = full_config.get('providers', full_config)
            full_config['providers'] = _reorder_dict(providers, order)
            save_path = Path.home() / '.aisbf' / 'providers.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.set_sort_order(current_user_id, 'provider', order)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_provider_reorder error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/dashboard/api/rotation/reorder")
async def api_rotation_reorder(request: Request):
    """Persist a new display order for rotations."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        body = await request.json()
        order = body.get('order', [])
        if not isinstance(order, list):
            return JSONResponse({"success": False, "error": "order must be a list"}, status_code=400)

        if is_config_admin:
            config_path = _rotations_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            rotations = full_config.get('rotations', full_config)
            full_config['rotations'] = _reorder_dict(rotations, order)
            save_path = Path.home() / '.aisbf' / 'rotations.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.set_sort_order(current_user_id, 'rotation', order)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_rotation_reorder error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/dashboard/api/autoselect/reorder")
async def api_autoselect_reorder(request: Request):
    """Persist a new display order for autoselects."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        body = await request.json()
        order = body.get('order', [])
        if not isinstance(order, list):
            return JSONResponse({"success": False, "error": "order must be a list"}, status_code=400)

        if is_config_admin:
            config_path = _autoselect_json_path()
            with open(config_path) as f:
                full_config = json.load(f)
            full_config = _reorder_dict(full_config, order)
            save_path = Path.home() / '.aisbf' / 'autoselect.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            _reload_global_config()
        else:
            db = DatabaseRegistry.get_config_database()
            db.set_sort_order(current_user_id, 'autoselect', order)

        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"api_autoselect_reorder error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/dashboard/prompts", response_class=HTMLResponse)
async def dashboard_prompts(request: Request):
    """Edit prompt _templates"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    user_id = request.session.get('user_id')
    
    # Define available prompts
    prompt_files = [
        {'key': 'condensation_conversational', 'name': 'Condensation - Conversational', 'filename': 'condensation_conversational.md'},
        {'key': 'condensation_semantic', 'name': 'Condensation - Semantic', 'filename': 'condensation_semantic.md'},
        {'key': 'autoselect', 'name': 'Autoselect - Model Selection', 'filename': 'autoselect.md'},
        {'key': 'studio_system', 'name': 'Studio - System Prompt', 'filename': 'STUDIO_SYSTEM.md'},
    ]
    
    prompts_data = []
    db = DatabaseRegistry.get_config_database()
    
    for prompt_file in prompt_files:
        content = None
        
        # Check if regular user has saved override
        if user_id:
            content = db.get_user_prompt(user_id, prompt_file['key'])
        
        # If no user override or admin, load default from filesystem
        if content is None:
            # Check user config first
            config_path = Path.home() / '.aisbf' / prompt_file['filename']
            
            if not config_path.exists():
                # Try installed locations
                installed_dirs = [
                    Path.home() / '.local' / 'share' / 'aisbf',
                    Path('/usr/share/aisbf'),
                    Path(__file__).parent,  # For source tree
                ]
                
                source_path = None
                for installed_dir in installed_dirs:
                    test_path = installed_dir / prompt_file['filename']
                    if test_path.exists():
                        source_path = test_path
                        break
                    # Also check config subdirectory
                    test_path = installed_dir / 'config' / prompt_file['filename']
                    if test_path.exists():
                        source_path = test_path
                        break
                
                if source_path:
                    # Copy to user config directory
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(source_path, config_path)
                    logger.info(f"Copied prompt from {source_path} to {config_path}")
            
            if config_path.exists():
                with open(config_path) as f:
                    content = f.read()
            else:
                # Add empty prompt if file not found
                content = f'# {prompt_file["name"]}\n\nPrompt template not found. Please add your prompt here.'
        
        prompts_data.append({
            'key': prompt_file['key'],
            'name': prompt_file['name'],
            'filename': prompt_file['filename'],
            'content': content
        })
    
    # Check for success parameter
    success = request.query_params.get('success')
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/prompts.html",
        context={
        "request": request,
        "session": request.session,
        "prompts": prompt_files,
        "prompts_data": json.dumps(prompts_data),
        "is_admin": is_admin,
        "success": "Prompt saved successfully!" if success else None
    }
    )

@router.post("/dashboard/prompts")
async def dashboard_prompts_save(request: Request, prompt_key: str = Form(...), prompt_content: str = Form(...)):
    """Save prompt template"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    user_id = request.session.get('user_id')
    
    # Map prompt keys to filenames
    prompt_map = {
        'condensation_conversational': 'condensation_conversational.md',
        'condensation_semantic': 'condensation_semantic.md',
        'autoselect': 'autoselect.md',
        'studio_system': 'STUDIO_SYSTEM.md',
    }
    
    if prompt_key not in prompt_map:
        return _templates.TemplateResponse(
        request=request,
        name="dashboard/prompts.html",
        context={
            "request": request,
            "session": request.session,
            "prompts": [],
            "prompts_data": "[]",
            "error": "Invalid prompt key"
        }
    )
    
    if is_admin:
        # Admin saves to filesystem
        filename = prompt_map[prompt_key]
        config_path = Path.home() / '.aisbf' / filename
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w') as f:
            f.write(prompt_content)
    else:
        # Regular user saves to database
        db = DatabaseRegistry.get_config_database()
        db.save_user_prompt(user_id, prompt_key, prompt_content)
    
    return RedirectResponse(url=url_for(request, "/dashboard/prompts?success=1"), status_code=303)

@router.post("/dashboard/prompts/reset/{prompt_key}")
async def dashboard_prompts_reset(request: Request, prompt_key: str):
    """Reset prompt to default for user"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)
    
    db = DatabaseRegistry.get_config_database()
    db.delete_user_prompt(user_id, prompt_key)
    
    return JSONResponse({"success": True})


@router.get("/dashboard/condensation", response_class=HTMLResponse)
async def dashboard_condensation(request: Request):
    """Redirect to prompts page for backward compatibility"""
    return RedirectResponse(url=url_for(request, "/dashboard/prompts"), status_code=303)

@router.post("/dashboard/condensation")
async def dashboard_condensation_save(request: Request, config: str = Form(...)):
    """Save condensation prompts - backward compatibility"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    config_path = Path.home() / '.aisbf' / 'condensation_conversational.md'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        f.write(config)
    
    return RedirectResponse(url=url_for(request, "/dashboard/prompts?success=1"), status_code=303)

@router.get("/dashboard/settings", response_class=HTMLResponse)
async def dashboard_settings(request: Request):
    """Edit server settings"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    config_path = get_aisbf_config_path()
    
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="Configuration file not found")
    
    with open(config_path) as f:
        aisbf_config = json.load(f)
    
    # Ensure MCP config exists with defaults
    if 'mcp' not in aisbf_config:
        aisbf_config['mcp'] = {
            'enabled': False,
            'autoselect_tokens': [],
            'fullconfig_tokens': []
        }
    
    warning = request.query_params.get('warning')
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/settings.html",
        context={
        "request": request,
        "session": request.session,
        "__version__": __version__,
        "config": aisbf_config,
        "os": os,
        "warning": warning,
    }
    )

@router.post("/dashboard/settings")
async def dashboard_settings_save(
   request: Request,
   host: str = Form(...),
   port: int = Form(...),
   protocol: str = Form(...),
   auth_enabled: bool = Form(False),
   auth_tokens: str = Form(""),
   dashboard_username: str = Form(...),
   condensation_model_id: str = Form(...),
   autoselect_model_id: str = Form(...),
   autoselect_max_tokens: int = Form(8000),
   condensation_max_tokens: int = Form(1000),
   autoselect_max_new_tokens: int = Form(100),
   nsfw_classifier: str = Form("michelleli99/NSFW_text_classifier"),
   privacy_classifier: str = Form("iiiorg/piiranha-v1-detect-personal-information"),
   semantic_vectorization: str = Form("sentence-transformers/all-MiniLM-L6-v2"),
   classify_nsfw: bool = Form(False),
   classify_privacy: bool = Form(False),
   classify_semantic: bool = Form(False),
   feature_nsfw_classification_mode: str = Form("inherit"),
   feature_privacy_classification_mode: str = Form("inherit"),
   feature_context_condensation_mode: str = Form("inherit"),
   feature_response_cache_mode: str = Form("inherit"),
    feature_prompt_batching_mode: str = Form("inherit"),
    feature_prompt_security_mode: str = Form("inherit"),
    feature_context_lens_mode: str = Form("inherit"),
    feature_block_high_risk_prompts_mode: str = Form("inherit"),
    feature_persist_prompt_text_mode: str = Form("inherit"),
    feature_redact_before_persist_mode: str = Form("inherit"),
    feature_risk_threshold: str = Form("high"),
    batching_enabled: bool = Form(False),
   batching_window_ms: int = Form(100),
   batching_max_batch_size: int = Form(8),
   batching_openai_enabled: bool = Form(False),
   batching_openai_max_batch_size: int = Form(10),
   batching_anthropic_enabled: bool = Form(False),
   batching_anthropic_max_batch_size: int = Form(5),
   adaptive_rate_limiting_enabled: bool = Form(False),
   adaptive_initial_rate_limit: float = Form(0),
   adaptive_learning_rate: float = Form(0.1),
   adaptive_headroom_percent: float = Form(10),
   adaptive_recovery_rate: float = Form(0.05),
   adaptive_max_rate_limit: float = Form(60),
   adaptive_min_rate_limit: float = Form(0.1),
   adaptive_backoff_base: float = Form(2),
   adaptive_jitter_factor: float = Form(0.25),
   adaptive_history_window: int = Form(3600),
   adaptive_consecutive_successes: int = Form(10),
   active_tab: str = Form("server"),
   database_type: str = Form("sqlite"),
   sqlite_path: str = Form("~/.aisbf/aisbf.db"),
   mysql_host: str = Form("localhost"),
   mysql_port: int = Form(3306),
   mysql_user: str = Form("aisbf"),
   mysql_password: str = Form(""),
   mysql_database: str = Form("aisbf"),
   cache_type: str = Form("file"),
   redis_host: str = Form("localhost"),
   redis_port: int = Form(6379),
   redis_db: int = Form(0),
   redis_password: str = Form(""),
   redis_key_prefix: str = Form("aisbf:"),
   response_cache_enabled: bool = Form(False),
   response_cache_backend: str = Form("memory"),
   response_cache_ttl: int = Form(600),
   response_cache_max_memory: int = Form(1000),
   response_cache_redis_host: str = Form("localhost"),
   response_cache_redis_port: int = Form(6379),
   response_cache_redis_db: int = Form(0),
   response_cache_redis_password: str = Form(""),
   response_cache_redis_key_prefix: str = Form("aisbf:response:"),
   response_cache_sqlite_path: str = Form("~/.aisbf/response_cache.db"),
   response_cache_mysql_host: str = Form("localhost"),
   response_cache_mysql_port: int = Form(3306),
   response_cache_mysql_user: str = Form("aisbf"),
   response_cache_mysql_password: str = Form(""),
   response_cache_mysql_database: str = Form("aisbf_response_cache"),
   mcp_enabled: bool = Form(False),
   autoselect_tokens: str = Form(""),
   fullconfig_tokens: str = Form(""),
   tor_enabled: bool = Form(False),
   tor_control_port: int = Form(9051),
   tor_control_host: str = Form("127.0.0.1"),
   tor_control_password: str = Form(""),
   tor_hidden_service_dir: str = Form(""),
   tor_hidden_service_port: int = Form(80),
   tor_socks_port: int = Form(9050),
   tor_socks_host: str = Form("127.0.0.1"),
   signup_enabled: bool = Form(False),
   signup_require_verification: bool = Form(False),
   verification_token_expiry: int = Form(24),
   smtp_host: str = Form(""),
   smtp_port: int = Form(587),
   smtp_username: str = Form(""),
   smtp_password: str = Form(""),
   smtp_use_tls: bool = Form(True),
   smtp_use_ssl: bool = Form(False),
   smtp_from_email: str = Form(""),
   smtp_from_name: str = Form(""),
   oauth2_google_enabled: bool = Form(False),
   oauth2_google_client_id: str = Form(""),
   oauth2_google_client_secret: str = Form(""),
   oauth2_github_enabled: bool = Form(False),
   oauth2_github_client_id: str = Form(""),
   oauth2_github_client_secret: str = Form(""),
   smtp_enabled: bool = Form(False),
   dashboard_email: str = Form(""),
   admin_notify_new_user_signup: bool = Form(False),
   admin_notify_payment_received: bool = Form(False),
   admin_notify_tier_upgrade: bool = Form(False),
   admin_notify_tier_downgrade: bool = Form(False),
   admin_notify_subscription_expired: bool = Form(False),
   admin_notify_subscription_renewed: bool = Form(False),
   admin_notify_wallet_topup: bool = Form(False),
   admin_notify_user_deleted_account: bool = Form(False),
   new_admin_password: str = Form(""),
   confirm_admin_password: str = Form(""),
   client_rl_enabled: bool = Form(False),
   client_rl_api_rpm: int = Form(60),
   client_rl_api_rph: int = Form(1000),
   client_rl_general_rpm: int = Form(120),
   client_rl_general_rph: int = Form(3000)
):
    """Save server settings"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    # Load current config
    config_path = get_aisbf_config_path()
    if not config_path.exists():
        config_path = Path(__file__).parent / 'config' / 'aisbf.json'
    
    with open(config_path) as f:
        aisbf_config = json.load(f)
    
    # Update config
    aisbf_config['server']['host'] = host
    aisbf_config['server']['port'] = port
    aisbf_config['server']['protocol'] = protocol
    aisbf_config['auth']['enabled'] = auth_enabled
    aisbf_config['auth']['tokens'] = [t.strip() for t in auth_tokens.split('\n') if t.strip()]
    aisbf_config['dashboard']['username'] = dashboard_username
    aisbf_config['internal_model']['condensation_model_id'] = condensation_model_id
    aisbf_config['internal_model']['autoselect_model_id'] = autoselect_model_id
    aisbf_config['internal_model']['autoselect_max_tokens'] = max(256, autoselect_max_tokens)
    aisbf_config['internal_model']['condensation_max_tokens'] = max(64, condensation_max_tokens)
    aisbf_config['internal_model']['autoselect_max_new_tokens'] = max(16, autoselect_max_new_tokens)

    # Update database config
    if 'database' not in aisbf_config:
        aisbf_config['database'] = {}
    aisbf_config['database']['type'] = database_type
    aisbf_config['database']['sqlite_path'] = sqlite_path
    aisbf_config['database']['mysql_host'] = mysql_host
    aisbf_config['database']['mysql_port'] = mysql_port
    aisbf_config['database']['mysql_user'] = mysql_user
    if mysql_password:  # Only update if provided
        aisbf_config['database']['mysql_password'] = mysql_password
    aisbf_config['database']['mysql_database'] = mysql_database

    # Update cache config
    if 'cache' not in aisbf_config:
        aisbf_config['cache'] = {}
    aisbf_config['cache']['type'] = cache_type
    aisbf_config['cache']['redis_host'] = redis_host
    aisbf_config['cache']['redis_port'] = redis_port
    aisbf_config['cache']['redis_db'] = redis_db
    if redis_password:  # Only update if provided
        aisbf_config['cache']['redis_password'] = redis_password
    aisbf_config['cache']['redis_key_prefix'] = redis_key_prefix

    # Update response cache config
    if 'response_cache' not in aisbf_config:
        aisbf_config['response_cache'] = {}
    aisbf_config['response_cache']['enabled'] = response_cache_enabled
    aisbf_config['response_cache']['backend'] = response_cache_backend
    aisbf_config['response_cache']['ttl'] = response_cache_ttl
    aisbf_config['response_cache']['max_memory_cache'] = response_cache_max_memory
    
    # Response cache Redis settings
    aisbf_config['response_cache']['redis_host'] = response_cache_redis_host
    aisbf_config['response_cache']['redis_port'] = response_cache_redis_port
    aisbf_config['response_cache']['redis_db'] = response_cache_redis_db
    if response_cache_redis_password:  # Only update if provided
        aisbf_config['response_cache']['redis_password'] = response_cache_redis_password
    aisbf_config['response_cache']['redis_key_prefix'] = response_cache_redis_key_prefix
    
    # Response cache SQLite settings
    aisbf_config['response_cache']['sqlite_path'] = response_cache_sqlite_path
    
    # Response cache MySQL settings
    aisbf_config['response_cache']['mysql_host'] = response_cache_mysql_host
    aisbf_config['response_cache']['mysql_port'] = response_cache_mysql_port
    aisbf_config['response_cache']['mysql_user'] = response_cache_mysql_user
    if response_cache_mysql_password:  # Only update if provided
        aisbf_config['response_cache']['mysql_password'] = response_cache_mysql_password
    aisbf_config['response_cache']['mysql_database'] = response_cache_mysql_database

    # Update MCP config
    if 'mcp' not in aisbf_config:
        aisbf_config['mcp'] = {}
    aisbf_config['mcp']['enabled'] = mcp_enabled
    aisbf_config['mcp']['autoselect_tokens'] = [t.strip() for t in autoselect_tokens.split('\n') if t.strip()]
    aisbf_config['mcp']['fullconfig_tokens'] = [t.strip() for t in fullconfig_tokens.split('\n') if t.strip()]
    
    # Update TOR config
    if 'tor' not in aisbf_config:
        aisbf_config['tor'] = {}
    aisbf_config['tor']['enabled'] = tor_enabled
    aisbf_config['tor']['control_port'] = tor_control_port
    aisbf_config['tor']['control_host'] = tor_control_host
    aisbf_config['tor']['control_password'] = tor_control_password if tor_control_password else None
    aisbf_config['tor']['hidden_service_dir'] = tor_hidden_service_dir if tor_hidden_service_dir else None
    aisbf_config['tor']['hidden_service_port'] = tor_hidden_service_port
    aisbf_config['tor']['socks_port'] = tor_socks_port
    aisbf_config['tor']['socks_host'] = tor_socks_host
    
    # Update Signup config
    if 'signup' not in aisbf_config:
        aisbf_config['signup'] = {}
    aisbf_config['signup']['enabled'] = signup_enabled
    aisbf_config['signup']['require_email_verification'] = signup_require_verification
    aisbf_config['signup']['verification_token_expiry_hours'] = verification_token_expiry
    
    # Update SMTP config
    if 'smtp' not in aisbf_config:
        aisbf_config['smtp'] = {}
    aisbf_config['smtp']['enabled'] = smtp_enabled
    aisbf_config['smtp']['host'] = smtp_host
    aisbf_config['smtp']['port'] = smtp_port
    aisbf_config['smtp']['username'] = smtp_username
    # Preserve existing password if submitted field is empty
    if smtp_password:
        aisbf_config['smtp']['password'] = smtp_password
    elif 'password' not in aisbf_config['smtp']:
        # Initialize as empty if not exists
        aisbf_config['smtp']['password'] = ""
    aisbf_config['smtp']['use_tls'] = smtp_use_tls
    aisbf_config['smtp']['use_ssl'] = smtp_use_ssl
    aisbf_config['smtp']['from_email'] = smtp_from_email
    aisbf_config['smtp']['from_name'] = smtp_from_name
    
    # Update OAuth2 config
    if 'oauth2' not in aisbf_config:
        aisbf_config['oauth2'] = {}
    
    # Google OAuth2
    if 'google' not in aisbf_config['oauth2']:
        aisbf_config['oauth2']['google'] = {}
    aisbf_config['oauth2']['google']['enabled'] = oauth2_google_enabled
    aisbf_config['oauth2']['google']['client_id'] = oauth2_google_client_id
    # Preserve existing client_secret if submitted field is empty
    if oauth2_google_client_secret:
        aisbf_config['oauth2']['google']['client_secret'] = oauth2_google_client_secret
    elif 'client_secret' not in aisbf_config['oauth2']['google']:
        aisbf_config['oauth2']['google']['client_secret'] = ""
    aisbf_config['oauth2']['google']['scopes'] = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ]
    
    # GitHub OAuth2
    if 'github' not in aisbf_config['oauth2']:
        aisbf_config['oauth2']['github'] = {}
    aisbf_config['oauth2']['github']['enabled'] = oauth2_github_enabled
    aisbf_config['oauth2']['github']['client_id'] = oauth2_github_client_id
    # Preserve existing client_secret if submitted field is empty
    if oauth2_github_client_secret:
        aisbf_config['oauth2']['github']['client_secret'] = oauth2_github_client_secret
    elif 'client_secret' not in aisbf_config['oauth2']['github']:
        aisbf_config['oauth2']['github']['client_secret'] = ""
    aisbf_config['oauth2']['github']['scopes'] = ["user:email", "read:user"]

    # Update admin email and notification preferences
    if 'dashboard' not in aisbf_config:
        aisbf_config['dashboard'] = {}
    if dashboard_email:
        aisbf_config['dashboard']['email'] = dashboard_email
    elif 'email' not in aisbf_config['dashboard']:
        aisbf_config['dashboard']['email'] = ""
    if 'notifications' not in aisbf_config['dashboard']:
        aisbf_config['dashboard']['notifications'] = {}
    aisbf_config['dashboard']['notifications']['new_user_signup'] = admin_notify_new_user_signup
    aisbf_config['dashboard']['notifications']['payment_received'] = admin_notify_payment_received
    aisbf_config['dashboard']['notifications']['tier_upgrade'] = admin_notify_tier_upgrade
    aisbf_config['dashboard']['notifications']['tier_downgrade'] = admin_notify_tier_downgrade
    aisbf_config['dashboard']['notifications']['subscription_expired'] = admin_notify_subscription_expired
    aisbf_config['dashboard']['notifications']['subscription_renewed'] = admin_notify_subscription_renewed
    aisbf_config['dashboard']['notifications']['wallet_topup'] = admin_notify_wallet_topup
    aisbf_config['dashboard']['notifications']['user_deleted_account'] = admin_notify_user_deleted_account

    if new_admin_password:
        if new_admin_password == confirm_admin_password:
            aisbf_config['dashboard']['password'] = _db_hash_password(new_admin_password)
            request.session.pop('must_change_password', None)

    # Update classification config
    aisbf_config['classify_nsfw'] = classify_nsfw
    aisbf_config['classify_privacy'] = classify_privacy
    aisbf_config['classify_semantic'] = classify_semantic

    if 'feature_controls' not in aisbf_config or not isinstance(aisbf_config['feature_controls'], dict):
        aisbf_config['feature_controls'] = {}
    feature_controls = aisbf_config['feature_controls']
    _set_feature_control(feature_controls, 'nsfw_classification', feature_nsfw_classification_mode)
    _set_feature_control(feature_controls, 'privacy_classification', feature_privacy_classification_mode)
    _set_feature_control(feature_controls, 'context_condensation', feature_context_condensation_mode)
    _set_feature_control(feature_controls, 'response_cache', feature_response_cache_mode)
    _set_feature_control(feature_controls, 'prompt_batching', feature_prompt_batching_mode)
    _set_prompt_security_control(feature_controls, 'security_scan', feature_prompt_security_mode)
    _set_prompt_security_control(feature_controls, 'context_lens', feature_context_lens_mode)
    _set_prompt_security_control(feature_controls, 'block_high_risk_prompts', feature_block_high_risk_prompts_mode)
    _set_prompt_security_control(feature_controls, 'persist_prompt_text', feature_persist_prompt_text_mode)
    _set_prompt_security_control(feature_controls, 'redact_before_persist', feature_redact_before_persist_mode)
    _set_prompt_security_threshold(feature_controls, feature_risk_threshold)

    # Update internal model classifiers
    if 'internal_model' not in aisbf_config:
        aisbf_config['internal_model'] = {}
    aisbf_config['internal_model']['nsfw_classifier'] = nsfw_classifier
    aisbf_config['internal_model']['privacy_classifier'] = privacy_classifier
    aisbf_config['internal_model']['semantic_vectorization'] = semantic_vectorization

    # Update batching config
    if 'batching' not in aisbf_config:
        aisbf_config['batching'] = {}
    aisbf_config['batching']['enabled'] = batching_enabled
    aisbf_config['batching']['window_ms'] = batching_window_ms
    aisbf_config['batching']['max_batch_size'] = batching_max_batch_size
    if 'provider_settings' not in aisbf_config['batching']:
        aisbf_config['batching']['provider_settings'] = {}
    if 'openai' not in aisbf_config['batching']['provider_settings']:
        aisbf_config['batching']['provider_settings']['openai'] = {}
    aisbf_config['batching']['provider_settings']['openai']['enabled'] = batching_openai_enabled
    aisbf_config['batching']['provider_settings']['openai']['max_batch_size'] = batching_openai_max_batch_size
    if 'anthropic' not in aisbf_config['batching']['provider_settings']:
        aisbf_config['batching']['provider_settings']['anthropic'] = {}
    aisbf_config['batching']['provider_settings']['anthropic']['enabled'] = batching_anthropic_enabled
    aisbf_config['batching']['provider_settings']['anthropic']['max_batch_size'] = batching_anthropic_max_batch_size

    # Update adaptive rate limiting config
    if 'adaptive_rate_limiting' not in aisbf_config:
        aisbf_config['adaptive_rate_limiting'] = {}
    aisbf_config['adaptive_rate_limiting']['enabled'] = adaptive_rate_limiting_enabled
    aisbf_config['adaptive_rate_limiting']['initial_rate_limit'] = adaptive_initial_rate_limit
    aisbf_config['adaptive_rate_limiting']['learning_rate'] = adaptive_learning_rate
    aisbf_config['adaptive_rate_limiting']['headroom_percent'] = adaptive_headroom_percent
    aisbf_config['adaptive_rate_limiting']['recovery_rate'] = adaptive_recovery_rate
    aisbf_config['adaptive_rate_limiting']['max_rate_limit'] = adaptive_max_rate_limit
    aisbf_config['adaptive_rate_limiting']['min_rate_limit'] = adaptive_min_rate_limit
    aisbf_config['adaptive_rate_limiting']['backoff_base'] = adaptive_backoff_base
    aisbf_config['adaptive_rate_limiting']['jitter_factor'] = adaptive_jitter_factor
    aisbf_config['adaptive_rate_limiting']['history_window'] = adaptive_history_window
    aisbf_config['adaptive_rate_limiting']['consecutive_successes_for_recovery'] = adaptive_consecutive_successes

    # Update client rate limiting config
    if 'client_rate_limiting' not in aisbf_config:
        aisbf_config['client_rate_limiting'] = {}
    aisbf_config['client_rate_limiting']['enabled'] = client_rl_enabled
    aisbf_config['client_rate_limiting']['api'] = {
        'requests_per_minute': max(0, client_rl_api_rpm),
        'requests_per_hour': max(0, client_rl_api_rph)
    }
    aisbf_config['client_rate_limiting']['general'] = {
        'requests_per_minute': max(0, client_rl_general_rpm),
        'requests_per_hour': max(0, client_rl_general_rph)
    }

    # Save config back to the same resolved path we loaded from
    config_path = get_aisbf_config_path()
    if not config_path.exists():
        config_path = Path.home() / '.aisbf' / 'aisbf.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(aisbf_config, f, indent=2)

    # Reload dashboard credentials in memory so the new username/password takes effect immediately
    if _config is not None and hasattr(_config, 'aisbf'):
        try:
            _config.reload()
        except Exception:
            logger.debug("Config reload after settings save failed", exc_info=True)

    # Hot-reload global config so changes take effect without restart
    _reload_global_config()

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/settings.html",
        context={
        "request": request,
        "session": request.session,
        "config": aisbf_config,
        "os": os,
        "active_tab": active_tab,
        "success": "Settings saved and reloaded successfully."
    }
    )

@router.post("/dashboard/test-smtp")
async def dashboard_test_smtp(request: Request):
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    try:
        body = await request.json()
        from aisbf.email_utils import send_test_email
        
        # Send test email to specified recipient
        test_recipient = body.get('test_recipient')
        
        if not test_recipient:
            return JSONResponse({"success": False, "error": "Test recipient email is required"})
        
        # Load the actual saved SMTP config from aisbf.json
        config_path = get_aisbf_config_path()
        if not config_path.exists():
            config_path = Path(__file__).parent / 'config' / 'aisbf.json'
        
        with open(config_path) as f:
            aisbf_config = json.load(f)
        
        smtp_config = aisbf_config.get('smtp', {})
        
        result = send_test_email(test_recipient, smtp_config)
        
        if result:
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"success": False, "error": "Failed to send test email"})
    except Exception as e:
        logger.error(f"Error testing SMTP: {e}")
        return JSONResponse({"success": False, "error": str(e)})

# Admin user management routes
@router.get("/dashboard/users", response_class=HTMLResponse)
async def dashboard_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    search: str = Query(None, max_length=100),
    order_by: str = Query('created_at', pattern='^(username|last_login|created_at|tier_name)$'),
    direction: str = Query('desc', pattern='^(asc|desc)$'),
    status_filter: str = Query(None, pattern='^(active|inactive)$'),
    role_filter: str = Query(None, pattern='^(admin|user)$'),
    tier_filter: str = Query(None),
    market_export_filter: str = Query(None, pattern='^(exporting|not_exporting)$')
): 
    """Admin user management page"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    # Get paginated users
    result = db.get_users_paginated(
        page=page,
        limit=limit,
        search=search,
        order_by=order_by,
        direction=direction,
        status_filter=status_filter,
        role_filter=role_filter,
        tier_filter=tier_filter,
        market_export_filter=market_export_filter,
    )
    
    users = result['users']
    total_users = result['total']
    
    # Calculate pagination metadata
    total_pages = (total_users + limit - 1) // limit  # Ceiling division
    current_page = min(page, total_pages) if total_pages > 0 else 1
    start_item = (current_page - 1) * limit + 1
    end_item = min(current_page * limit, total_users)
    
    # Get all tiers for assignment dropdown
    tiers = db.get_all_tiers()
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
            "request": request,
            "session": request.session,
            "users": users,
            "tiers": tiers,
            "pagination": {
                "current_page": current_page,
                "total_pages": total_pages,
                "total_users": total_users,
                "start_item": start_item,
                "end_item": end_item,
                "limit": limit,
                "has_prev": current_page > 1,
                "has_next": current_page < total_pages
            },
            "filters": {
                "search": search or "",
                "order_by": order_by,
                "direction": direction,
                "status_filter": status_filter,
                "role_filter": role_filter,
                "tier_filter": tier_filter,
                "market_export_filter": market_export_filter,
            }
        }
    )

@router.post("/dashboard/users/add")
async def dashboard_users_add(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("user")):
    """Add a new user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    password_hash = _db_hash_password(password)

    try:
        # Get current admin username
        admin_username = request.session.get('username', 'admin')
        # Create user with display_name defaulting to username
        user_id = db.create_user(username, password_hash, role, admin_username, None, False, username)
        _record_dashboard_admin_event(request, 'user_registered', target_user_id=user_id, metadata={'role': role, 'created_by': admin_username})
        return RedirectResponse(url=url_for(request, "/dashboard/users"), status_code=303)
    except Exception as e:
        users = db.get_users()
        return _templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
            "request": request,
            "session": request.session,
            "users": users,
            "error": f"Failed to create user: {str(e)}"
        }
    )

@router.post("/dashboard/users/{user_id}/edit")
async def dashboard_users_edit(request: Request, user_id: int, username: str = Form(...), password: str = Form(""), role: str = Form("user"), is_active: bool = Form(True)):
    """Edit an existing user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        # Update user (only if password is provided)
        if password:
            password_hash = _db_hash_password(password)
            db.update_user(user_id, username, password_hash, role, is_active, username)
        else:
            db.update_user(user_id, username, None, role, is_active, username)
        return RedirectResponse(url=url_for(request, "/dashboard/users"), status_code=303)
    except Exception as e:
        users = db.get_users()
        return _templates.TemplateResponse(
        request=request,
        name="dashboard/users.html",
        context={
            "request": request,
            "session": request.session,
            "users": users,
            "error": f"Failed to update user: {str(e)}"
        }
    )

@router.post("/dashboard/users/{user_id}/toggle")
async def dashboard_users_toggle(request: Request, user_id: int):
    """Toggle user active status"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        users = db.get_users()
        for user in users:
            if user['id'] == user_id:
                new_status = not user['is_active']
                db.update_user(user_id, user['username'], None, user['role'], new_status)
                return JSONResponse({"success": True})
        return JSONResponse({"success": False, "error": "User not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.post("/dashboard/users/{user_id}/delete")
async def dashboard_users_delete(request: Request, user_id: int):
    """Delete a user"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        db.delete_user(user_id)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.post("/dashboard/users/{user_id}/impersonate")
async def dashboard_users_impersonate(request: Request, user_id: int):
    """Impersonate a user (admin only). Saves admin session and switches to target user."""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    if not user:
        return JSONResponse({"success": False, "error": "User not found"}, status_code=404)

    # Save current admin session so we can restore it on logout
    request.session['impersonating_as'] = user_id
    request.session['admin_session'] = {
        'logged_in': request.session.get('logged_in'),
        'username': request.session.get('username'),
        'display_name': request.session.get('display_name'),
        'email': request.session.get('email'),
        'role': request.session.get('role'),
        'user_id': request.session.get('user_id'),
        'has_profile_pic': request.session.get('has_profile_pic'),
        'remember_me': request.session.get('remember_me'),
        'expires_at': request.session.get('expires_at'),
        'email_verified': request.session.get('email_verified'),
    }

    # Switch session to target user
    request.session['logged_in'] = True
    request.session['username'] = user['username']
    request.session['display_name'] = user.get('display_name') or ''
    request.session['email'] = user.get('email') or ''
    request.session['role'] = user['role']
    request.session['user_id'] = user['id']
    request.session['has_profile_pic'] = bool(user.get('profile_pic'))
    request.session['email_verified'] = user.get('email_verified', False)
    request.session['must_change_password'] = False

    return JSONResponse({"success": True, "redirect": url_for(request, "/dashboard")})


@router.post("/dashboard/users/{user_id}/tier")
async def dashboard_users_update_tier(request: Request, user_id: int):
    """Update user tier assignment"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    
    try:
        body = await request.json()
        tier_id = body.get('tier_id')
        
        if not tier_id:
            return JSONResponse({"success": False, "error": "tier_id is required"}, status_code=400)
        
        # Verify tier exists
        tier = db.get_tier_by_id(tier_id)
        if not tier:
            return JSONResponse({"success": False, "error": "Tier not found"}, status_code=404)
        
        # Update user tier
        success = db.set_user_tier(user_id, tier_id)
        
        if success:
            _record_dashboard_admin_event(request, 'tier_upgraded', target_user_id=user_id, metadata={'tier_id': tier_id, 'source': 'admin-users'})
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"success": False, "error": "Failed to update user tier"}, status_code=500)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.post("/dashboard/users/bulk")
async def dashboard_users_bulk(request: Request):
    """Handle bulk user operations"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()

    try:
        body = await request.json()
        action = body.get('action')
        user_ids = body.get('user_ids', [])
        extra_data = body.get('extra_data')

        if not action or not user_ids:
            return JSONResponse({"success": False, "error": "Action and user_ids required"}, status_code=400)

        # Validate user_ids
        if not isinstance(user_ids, list) or not all(isinstance(uid, int) for uid in user_ids):
            return JSONResponse({"success": False, "error": "user_ids must be a list of integers"}, status_code=400)

        if action == 'enable':
            success_count = 0
            for user_id in user_ids:
                if db.update_user(user_id, None, None, None, True):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Enabled {success_count} of {len(user_ids)} users"})

        elif action == 'disable':
            success_count = 0
            for user_id in user_ids:
                if db.update_user(user_id, None, None, None, False):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Disabled {success_count} of {len(user_ids)} users"})

        elif action == 'delete':
            success_count = 0
            for user_id in user_ids:
                try:
                    db.delete_user(user_id)
                    success_count += 1
                except Exception:
                    pass  # Continue with other deletions
            return JSONResponse({"success": True, "message": f"Deleted {success_count} of {len(user_ids)} users"})

        elif action == 'tier':
            tier_id = extra_data
            if not tier_id:
                return JSONResponse({"success": False, "error": "tier_id required for tier action"}, status_code=400)

            # Verify tier exists
            tier = db.get_tier_by_id(tier_id)
            if not tier:
                return JSONResponse({"success": False, "error": "Tier not found"}, status_code=404)

            success_count = 0
            for user_id in user_ids:
                if db.set_user_tier(user_id, tier_id):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Changed tier for {success_count} of {len(user_ids)} users"})

        else:
            return JSONResponse({"success": False, "error": "Invalid action"}, status_code=400)

    except Exception as e:
        logger.error(f"Bulk operation error: {e}")
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)

@router.post("/dashboard/api/admin/notifications/send")
async def admin_send_notification(request: Request):
    """Admin sends an in-app notification to selected users."""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check
    db = DatabaseRegistry.get_config_database()
    try:
        body = await request.json()
        user_ids = body.get('user_ids', [])
        title = (body.get('title') or '').strip()
        message = (body.get('message') or '').strip()
        if not user_ids or not title or not message:
            return JSONResponse({"success": False, "error": "user_ids, title and message are required"}, status_code=400)
        if not isinstance(user_ids, list) or not all(isinstance(uid, int) for uid in user_ids):
            return JSONResponse({"success": False, "error": "user_ids must be a list of integers"}, status_code=400)
        sent = 0
        for uid in user_ids:
            try:
                db.create_notification(uid, title, message, 'admin_message')
                sent += 1
            except Exception:
                pass
        return JSONResponse({"success": True, "sent": sent})
    except Exception as e:
        logger.error(f"admin_send_notification: {e}")
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)


@router.get("/dashboard/api/notifications")
async def get_notifications(request: Request):
    """Return in-app notifications for the current user."""
    if not request.session.get('logged_in') or not request.session.get('user_id'):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    user_id = request.session['user_id']
    db = DatabaseRegistry.get_config_database()
    notifications = db.get_user_notifications(user_id, limit=50)
    return JSONResponse({"notifications": notifications})


@router.get("/dashboard/api/notifications/count")
async def get_notification_count(request: Request):
    """Return unread notification count for the current user."""
    if not request.session.get('logged_in') or not request.session.get('user_id'):
        return JSONResponse({"count": 0})
    user_id = request.session['user_id']
    db = DatabaseRegistry.get_config_database()
    count = db.get_unread_notification_count(user_id)
    return JSONResponse({"count": count})


@router.post("/dashboard/api/notifications/{notification_id}/read")
async def mark_notification_read(request: Request, notification_id: int):
    """Mark a single notification as read."""
    if not request.session.get('logged_in') or not request.session.get('user_id'):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    user_id = request.session['user_id']
    db = DatabaseRegistry.get_config_database()
    db.mark_notification_read(notification_id, user_id)
    return JSONResponse({"success": True})


@router.post("/dashboard/api/notifications/read-all")
async def mark_all_notifications_read(request: Request):
    """Mark all notifications as read for the current user."""
    if not request.session.get('logged_in') or not request.session.get('user_id'):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    user_id = request.session['user_id']
    db = DatabaseRegistry.get_config_database()
    db.mark_all_notifications_read(user_id)
    return JSONResponse({"success": True})


@router.delete("/dashboard/api/notifications/{notification_id}")
async def delete_notification(request: Request, notification_id: int):
    """Delete a notification for the current user."""
    if not request.session.get('logged_in') or not request.session.get('user_id'):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    user_id = request.session['user_id']
    db = DatabaseRegistry.get_config_database()
    db.delete_notification(notification_id, user_id)
    return JSONResponse({"success": True})


@router.post("/dashboard/restart")
async def dashboard_restart(request: Request):
    """Reload configuration from disk"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    logger.info("Configuration reload requested from dashboard")

    try:
        # Reload configuration
        from aisbf.config import config
        config.reload()

        # Re-initialize database if _config changed
        db_config = config.aisbf.database if _config.aisbf and config.aisbf.database else None
        if db_config:
            from aisbf.database import DatabaseRegistry
            DatabaseRegistry.get_config_database(db_config)

        # Re-initialize cache if _config changed
        cache_config = config.aisbf.cache if _config.aisbf and config.aisbf.cache else None
        if cache_config:
            from aisbf.cache import initialize_cache
            initialize_cache(cache_config)

        # Re-initialize response cache if _config changed
        response_cache_config = config.aisbf.response_cache if _config.aisbf and config.aisbf.response_cache else None
        if response_cache_config:
            from aisbf.cache import initialize_response_cache
            initialize_response_cache(response_cache_config.model_dump() if hasattr(response_cache_config, 'model_dump') else response_cache_config)

        logger.info("Configuration reloaded successfully")

        return JSONResponse({"message": "Configuration reloaded successfully. All changes have been applied."})

    except Exception as e:
        logger.error(f"Error reloading configuration: {e}")
        return JSONResponse({"error": f"Failed to reload configuration: {str(e)}"}, status_code=500)

# User-specific configuration management routes
    db = DatabaseRegistry.get_config_database()

    try:
        file_info = db.get_user_auth_file(user_id, provider_name, file_type)
        if file_info:
            # Delete file from disk
            file_path = Path(file_info['file_path'])
            if file_path.exists():
                file_path.unlink()
            
            # Delete from database
            db.delete_user_auth_file(user_id, provider_name, file_type)
        
        return JSONResponse({"message": "File deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Admin authentication file management routes
def get_admin_auth_files_dir() -> Path:
    """Get the directory for admin authentication files"""
    auth_files_dir = Path.home() / '.aisbf' / 'admin_auth_files'
    auth_files_dir.mkdir(parents=True, exist_ok=True)
    return auth_files_dir


@router.post("/dashboard/providers/{provider_name}/upload")
async def dashboard_provider_upload(
    request: Request,
    provider_name: str,
    file_type: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload authentication file for a provider. Config admin saves to files, other users save to database."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    # Check if current user is config admin (from aisbf.json)
    is_config_admin = request.session.get('user_id') is None
    logger.info(f"🔍 UPLOAD HANDLER DEBUG: session.user_id = {request.session.get('user_id')}, is_config_admin = {is_config_admin}")

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file', 'cli_credentials']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        # Read file content
        content = await file.read()
        logger.info(f"🔍 UPLOAD HANDLER: Received file {file.filename}, size: {len(content)} bytes")

        if is_config_admin:
            # Config admin: save to files
            auth_files_dir = get_admin_auth_files_dir()
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_name}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            logger.info(f"Config admin uploaded auth file: {file_path}")

            # Update providers.json with full path to the uploaded file
            try:
                config_path = Path.home() / '.aisbf' / 'providers.json'
                if not config_path.exists():
                    config_path = Path(__file__).parent / 'config' / 'providers.json'
                
                with open(config_path) as f:
                    full_config = json.load(f)
                
                # Navigate to the provider config
                if 'providers' in full_config and isinstance(full_config['providers'], dict):
                    providers = full_config['providers']
                else:
                    providers = full_config
                
                # Update the file path in provider config
                if provider_name in providers:
                    # Convert absolute path to ~/... format
                    relative_path = str(file_path).replace(str(Path.home()), '~')
                    
                    # Update the correct location based on provider type
                    provider_type = providers[provider_name].get('type', '')
                    
                    # For Kiro, update kiro_config.sqlite_db or kiro_config.creds_file
                    if provider_type == 'kiro' and file_type in ['sqlite_db', 'creds_file']:
                        if 'kiro_config' not in providers[provider_name]:
                            providers[provider_name]['kiro_config'] = {}
                        providers[provider_name]['kiro_config'][file_type] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.kiro_config.{file_type} = {relative_path}")
                    
                    # For Claude, update claude_config.credentials_file
                    elif provider_type == 'claude' and file_type in ['credentials_file', 'claude_credentials']:
                        if 'claude_config' not in providers[provider_name]:
                            providers[provider_name]['claude_config'] = {}
                        providers[provider_name]['claude_config']['credentials_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.claude_config.credentials_file = {relative_path}")
                    
                    # For Kilo, update kilo_config.creds_file
                    elif provider_type in ['kilo', 'kilocode'] and file_type in ['credentials_file', 'creds_file']:
                        if 'kilo_config' not in providers[provider_name]:
                            providers[provider_name]['kilo_config'] = {}
                        providers[provider_name]['kilo_config']['creds_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.kilo_config.creds_file = {relative_path}")
                    
                    # For Qwen, update qwen_config.credentials_file
                    elif provider_type == 'qwen' and file_type in ['credentials_file']:
                        if 'qwen_config' not in providers[provider_name]:
                            providers[provider_name]['qwen_config'] = {}
                        providers[provider_name]['qwen_config']['credentials_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.qwen_config.credentials_file = {relative_path}")
                    
                    # For Codex, update codex_config.credentials_file
                    elif provider_type == 'codex' and file_type in ['credentials_file', 'creds_file']:
                        if 'codex_config' not in providers[provider_name]:
                            providers[provider_name]['codex_config'] = {}
                        providers[provider_name]['codex_config']['credentials_file'] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.codex_config.credentials_file = {relative_path}")
                    
                    # Fallback: update top-level field
                    else:
                        providers[provider_name][file_type] = relative_path
                        logger.info(f"Updated providers.json: {provider_name}.{file_type} = {relative_path}")
                    
                    # Save updated config
                    save_path = Path.home() / '.aisbf' / 'providers.json'
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, 'w') as f:
                        json.dump(full_config, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to update providers.json: {e}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
        else:
            # Database user: save to database
            db = DatabaseRegistry.get_config_database()

            # Get user auth files directory
            auth_files_dir = get_user_auth_files_dir(current_user_id)
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_name}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            # Save metadata to database
            file_id = db.save_user_auth_file(
                user_id=current_user_id,
                provider_id=provider_name,
                file_type=file_type,
                original_filename=file.filename or stored_filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=len(content),
                mime_type=file.content_type
            )

            logger.info(f"User {current_user_id} uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_id": file_id,
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/dashboard/providers/upload-auth-file")
async def dashboard_provider_upload_form(
    request: Request,
    provider_key: str = Form(...),
    file_type: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload authentication file for a provider (form variant used by frontend)."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    # Check if current user is config admin (from aisbf.json)
    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file', 'cli_credentials']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        # Read file content
        content = await file.read()

        if is_config_admin:
            # Config admin: save to files
            auth_files_dir = get_admin_auth_files_dir()
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_key}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            logger.info(f"Config admin uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
        else:
            # Database user: save to database
            db = DatabaseRegistry.get_config_database()

            # Get user auth files directory
            auth_files_dir = get_user_auth_files_dir(current_user_id)
            
            # Generate unique filename
            import uuid
            file_ext = Path(file.filename).suffix if file.filename else '.json'
            stored_filename = f"{provider_key}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = auth_files_dir / stored_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(content)

            # Save metadata to database
            file_id = db.save_user_auth_file(
                user_id=current_user_id,
                provider_id=provider_key,
                file_type=file_type,
                original_filename=file.filename or stored_filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=len(content),
                mime_type=file.content_type
            )

            logger.info(f"User {current_user_id} uploaded auth file: {file_path}")

            return JSONResponse({
                "success": True,
                "message": "File uploaded successfully",
                "file_id": file_id,
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/dashboard/providers/upload-auth-file/chunk")
async def dashboard_provider_upload_chunk(
    request: Request,
    provider_key: str = Form(...),
    file_type: str = Form(...),
    file_name: str = Form(...),
    chunk_number: int = Form(...),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
    file: UploadFile = File(...)
):
    """Chunked file upload endpoint - handles very large files behind proxies."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    current_user_id = request.session.get('user_id')
    is_config_admin = current_user_id is None

    try:
        # Validate file type
        allowed_types = ['credentials', 'database', 'config', 'kiro_credentials', 'claude_credentials', 'sqlite_db', 'creds_file', 'cli_credentials']
        if file_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Invalid file type. Allowed: {', '.join(allowed_types)}"}
            )

        import uuid
        import hashlib

        # Generate unique upload ID
        upload_id = hashlib.sha256(f"{current_user_id}:{provider_key}:{file_name}:{total_size}".encode()).hexdigest()[:16]
        file_ext = Path(file_name).suffix if file_name else '.bin'

        # Create temporary upload directory in user's home
        if is_config_admin:
            # Config admin: use their home directory
            temp_dir = Path.home() / '.aisbf' / 'temp_uploads'
        else:
            # Database user: use their auth files directory
            temp_dir = get_user_auth_files_dir(current_user_id) / 'temp_uploads'
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Save chunk
        chunk_path = temp_dir / f"{upload_id}.part{chunk_number}"
        content = await file.read()
        with open(chunk_path, 'wb') as f:
            f.write(content)

        # Check if all chunks are received
        received_chunks = list(temp_dir.glob(f"{upload_id}.part*"))
        if len(received_chunks) == total_chunks:
            # Assemble final file
            import uuid
            stored_filename = f"{provider_key}_{file_type}_{uuid.uuid4().hex[:8]}{file_ext}"

            if is_config_admin:
                auth_files_dir = get_admin_auth_files_dir()
            else:
                auth_files_dir = get_user_auth_files_dir(current_user_id)

            file_path = auth_files_dir / stored_filename

            # Combine chunks
            with open(file_path, 'wb') as outfile:
                for i in range(1, total_chunks + 1):
                    chunk_path = temp_dir / f"{upload_id}.part{i}"
                    with open(chunk_path, 'rb') as infile:
                        outfile.write(infile.read())
                    chunk_path.unlink()

            # Save metadata to database if not admin
            if not is_config_admin:
                db = DatabaseRegistry.get_config_database()

                # CLI credentials for claude providers go directly into
                # user_oauth2_credentials so the provider handler can read them
                # without touching the filesystem at request time.
                if file_type == 'cli_credentials':
                    try:
                        with open(file_path, 'r') as fh:
                            cli_creds_content = json.load(fh)
                        db.save_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_key,
                            auth_type='claude_cli_credentials',
                            credentials={'credentials': cli_creds_content},
                        )
                        file_path.unlink(missing_ok=True)
                        logger.info(
                            f"Stored CLI credentials for user {current_user_id} "
                            f"provider {provider_key} in user_oauth2_credentials"
                        )
                    except Exception as exc:
                        logger.error(f"Failed to save CLI credentials to DB: {exc}")
                else:
                    db.save_user_auth_file(
                        user_id=current_user_id,
                        provider_id=provider_key,
                        file_type=file_type,
                        original_filename=file_name,
                        stored_filename=stored_filename,
                        file_path=str(file_path),
                        file_size=total_size,
                        mime_type=file.content_type
                    )
            else:
                # Config admin: update providers.json with full path
                try:
                    config_path = Path.home() / '.aisbf' / 'providers.json'
                    if not config_path.exists():
                        config_path = Path(__file__).parent / 'config' / 'providers.json'
                    
                    with open(config_path) as f:
                        full_config = json.load(f)
                    
                    # Navigate to the provider config
                    if 'providers' in full_config and isinstance(full_config['providers'], dict):
                        providers = full_config['providers']
                    else:
                        providers = full_config
                    
                    # Update the file path in provider config
                    if provider_key in providers:
                        # Convert absolute path to ~/... format
                        relative_path = str(file_path).replace(str(Path.home()), '~')
                        
                        # Update the correct location based on provider type
                        provider_type = providers[provider_key].get('type', '')
                        
                        # For Kiro, update kiro_config.sqlite_db or kiro_config.creds_file
                        if provider_type == 'kiro' and file_type in ['sqlite_db', 'creds_file']:
                            if 'kiro_config' not in providers[provider_key]:
                                providers[provider_key]['kiro_config'] = {}
                            providers[provider_key]['kiro_config'][file_type] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.kiro_config.{file_type} = {relative_path}")
                        
                        # For Claude, update claude_config.credentials_file
                        elif provider_type == 'claude' and file_type in ['credentials_file', 'claude_credentials']:
                            if 'claude_config' not in providers[provider_key]:
                                providers[provider_key]['claude_config'] = {}
                            providers[provider_key]['claude_config']['credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.claude_config.credentials_file = {relative_path}")
                        
                        # For Kilo, update kilo_config.creds_file
                        elif provider_type in ['kilo', 'kilocode'] and file_type in ['credentials_file', 'creds_file']:
                            if 'kilo_config' not in providers[provider_key]:
                                providers[provider_key]['kilo_config'] = {}
                            providers[provider_key]['kilo_config']['creds_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.kilo_config.creds_file = {relative_path}")
                        
                        # For Qwen, update qwen_config.credentials_file
                        elif provider_type == 'qwen' and file_type in ['credentials_file']:
                            if 'qwen_config' not in providers[provider_key]:
                                providers[provider_key]['qwen_config'] = {}
                            providers[provider_key]['qwen_config']['credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.qwen_config.credentials_file = {relative_path}")
                        
                        # For Codex, update codex_config.credentials_file
                        elif provider_type == 'codex' and file_type in ['credentials_file', 'creds_file']:
                            if 'codex_config' not in providers[provider_key]:
                                providers[provider_key]['codex_config'] = {}
                            providers[provider_key]['codex_config']['credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.codex_config.credentials_file = {relative_path}")

                        # For Claude CLI credentials – store path in claude_config.cli_credentials_file
                        elif provider_type == 'claude' and file_type == 'cli_credentials':
                            if 'claude_config' not in providers[provider_key]:
                                providers[provider_key]['claude_config'] = {}
                            providers[provider_key]['claude_config']['cli_credentials_file'] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.claude_config.cli_credentials_file = {relative_path}")

                        # Fallback: update top-level field
                        else:
                            providers[provider_key][file_type] = relative_path
                            logger.info(f"Updated providers.json: {provider_key}.{file_type} = {relative_path}")
                        
                        # Save updated config
                        save_path = Path.home() / '.aisbf' / 'providers.json'
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(save_path, 'w') as f:
                            json.dump(full_config, f, indent=2)
                except Exception as e:
                    logger.error(f"Failed to update providers.json: {e}")

            logger.info(f"Upload complete: {file_path} ({total_size} bytes, {total_chunks} chunks)")

            return JSONResponse({
                "success": True,
                "complete": True,
                "message": "File uploaded successfully",
                "file_path": str(file_path),
                "stored_filename": stored_filename
            })

        return JSONResponse({
            "success": True,
            "complete": False,
            "received_chunks": len(received_chunks),
            "total_chunks": total_chunks
        })

    except Exception as e:
        logger.error(f"Chunk upload error: {e}")
        # Cleanup failed upload
        try:
            for chunk_path in temp_dir.glob(f"{upload_id}.part*"):
                chunk_path.unlink()
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/dashboard/providers/{provider_name}/files")
async def dashboard_provider_files(request: Request, provider_name: str):
    """Get all authentication files for a global provider (admin only)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    try:
        auth_files_dir = get_admin_auth_files_dir()
        files = []
        
        for file_path in auth_files_dir.glob(f"{provider_name}_*"):
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "filename": file_path.name,
                    "file_path": str(file_path),
                    "file_size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return JSONResponse({"files": files})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/dashboard/providers/{provider_name}/files/{filename}/download")
async def dashboard_provider_file_download(
    request: Request,
    provider_name: str,
    filename: str
):
    """Download an authentication file for a global provider (admin only)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    try:
        auth_files_dir = get_admin_auth_files_dir()
        file_path = auth_files_dir / filename
        
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse(status_code=404, content={"error": "File not found"})
        
        # Security check: ensure file belongs to this provider
        if not filename.startswith(f"{provider_name}_"):
            return JSONResponse(status_code=403, content={"error": "Access denied"})
        
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type='application/octet-stream'
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.delete("/dashboard/providers/{provider_name}/files/{filename}")
async def dashboard_provider_file_delete(
    request: Request,
    provider_name: str,
    filename: str
):
    """Delete an authentication file for a global provider (admin only)"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    try:
        auth_files_dir = get_admin_auth_files_dir()
        file_path = auth_files_dir / filename
        
        if not file_path.exists():
            return JSONResponse(status_code=404, content={"error": "File not found"})
        
        # Security check: ensure file belongs to this provider
        if not filename.startswith(f"{provider_name}_"):
            return JSONResponse(status_code=403, content={"error": "Access denied"})
        
        file_path.unlink()
        
        return JSONResponse({"message": "File deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# OAuth authentication check endpoints for providers
@router.get("/dashboard/providers/{provider_name}/auth/check")
async def dashboard_provider_auth_check(request: Request, provider_name: str):
    """Check OAuth authentication status for a provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    try:
        # Get user ID from session
        current_user_id = request.session.get('user_id')
        
        # Load provider configuration
        provider_config = None
        
        if current_user_id is None:
            # Admin: check global config
            provider_config = _config.providers.get(provider_name)
        else:
            # Regular user: get from user providers
            from aisbf.database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            user_provider = db.get_user_provider(current_user_id, provider_name)
            if user_provider:
                provider_config = user_provider['config']

        if not provider_config:
            return JSONResponse(
                status_code=404,
                content={"authenticated": False, "error": f"Provider '{provider_name}' not found"}
            )

        # Handle both dict (user providers) and object (global providers)
        if isinstance(provider_config, dict):
            provider_type = provider_config.get('type')
        else:
            provider_type = provider_config.type

        if provider_type == 'claude':
            from aisbf.auth.claude import ClaudeAuth
            # Handle dict vs object
            if isinstance(provider_config, dict):
                claude_config = provider_config.get('claude_config', {})
            else:
                claude_config = provider_config.claude_config or {}

            if current_user_id is None:
                # Admin user: load from file (ClaudeAuth saves back to file automatically)
                auth = ClaudeAuth(credentials_file=claude_config.get('credentials_file', '~/.claude_credentials.json'))
            else:
                # Regular user: load from database; wire up a save-callback so any
                # token refresh is persisted back to the database immediately.
                db = DatabaseRegistry.get_config_database()
                def _save_claude_to_db(creds):
                    try:
                        db.save_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='claude_oauth2',
                            credentials=creds,
                        )
                    except Exception as _e:
                        logger.warning(f"Failed to save refreshed Claude credentials to database: {_e}")

                auth = ClaudeAuth(
                    credentials_file=claude_config.get('credentials_file', '~/.claude_credentials.json'),
                    skip_initial_load=True,
                    save_callback=_save_claude_to_db,
                )
                try:
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='claude_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.tokens = db_creds['credentials'].get('tokens', {})
                            if auth.tokens and 'expires_at' not in auth.tokens and 'expires_in' in auth.tokens:
                                auth.tokens['expires_at'] = time.time() + auth.tokens.get('expires_in', 3600)
                except Exception as e:
                    logger.warning(f"Failed to load Claude credentials from database: {e}")

            if not auth.is_authenticated():
                return JSONResponse({"authenticated": False})

            # Auto-refresh if expired (or expiring within 5 minutes)
            expires_at = auth.tokens.get('expires_at', 0)
            if time.time() >= (expires_at - 300):
                logger.info(f"Claude token expired/expiring for provider {provider_name}, attempting refresh")
                refreshed = await auth.refresh_token()
                if not refreshed:
                    logger.warning(f"Claude token refresh failed for provider {provider_name}")
                    return JSONResponse({"authenticated": False, "error": "Token expired and refresh failed. Please re-authenticate."})
                logger.info(f"Claude token refreshed successfully for provider {provider_name}")

            return JSONResponse({
                "authenticated": True,
                "expires_at": auth.tokens.get('expires_at', 0),
            })

        elif provider_type == 'kilocode':
            from aisbf.auth.kilo import KiloOAuth2
            # Handle dict vs object
            if isinstance(provider_config, dict):
                kilo_config = provider_config.get('kilo_config', {})
            else:
                kilo_config = provider_config.kilo_config or {}
            
            if current_user_id is None:
                # Admin user: load from file
                auth = KiloOAuth2(credentials_file=kilo_config.get('credentials_file', '~/.kilo_credentials.json'))
            else:
                # Regular user: load from database
                auth = KiloOAuth2(
                    credentials_file=kilo_config.get('credentials_file', '~/.kilo_credentials.json'),
                    skip_initial_load=True
                )
                # Load credentials from database
                try:
                    db = DatabaseRegistry.get_config_database()
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='kilo_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.credentials = db_creds['credentials']
                except Exception as e:
                    logger.warning(f"Failed to load Kilo credentials from database: {e}")
            
            is_auth = auth.is_authenticated()
            result = {"authenticated": is_auth}
            if is_auth and auth.credentials:
                expires = auth.credentials.get('expires', 0)
                if expires:
                    result["expires_at"] = expires
            return JSONResponse(result)

        elif provider_type == 'qwen':
            from aisbf.auth.qwen import QwenOAuth2
            # Handle dict vs object
            if isinstance(provider_config, dict):
                qwen_config = provider_config.get('qwen_config', {})
            else:
                qwen_config = provider_config.qwen_config or {}

            if current_user_id is None:
                # Admin user: load from file
                auth = QwenOAuth2(credentials_file=qwen_config.get('credentials_file', '~/.aisbf/qwen_credentials.json'))
            else:
                # Regular user: load from database with save_callback so refreshed tokens persist
                db = DatabaseRegistry.get_config_database()
                def _save_qwen_to_db(creds):
                    try:
                        if db:
                            db.save_user_oauth2_credentials(
                                user_id=current_user_id,
                                provider_id=provider_name,
                                auth_type='qwen_oauth2',
                                credentials=creds
                            )
                    except Exception as _e:
                        logger.warning(f"Failed to save refreshed Qwen credentials to database: {_e}")
                auth = QwenOAuth2(
                    credentials_file=qwen_config.get('credentials_file', '~/.aisbf/qwen_credentials.json'),
                    skip_initial_load=True,
                    save_callback=_save_qwen_to_db
                )
                # Load credentials from database
                try:
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='qwen_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.credentials = db_creds['credentials']
                except Exception as e:
                    logger.warning(f"Failed to load Qwen credentials from database: {e}")

            is_auth = auth.is_authenticated()
            if not is_auth and auth.credentials and auth.credentials.get('refresh_token'):
                refreshed = await auth.refresh_tokens()
                if refreshed:
                    is_auth = True
                else:
                    return JSONResponse({"authenticated": False, "error": "Token expired and refresh failed. Please re-authenticate."})
            result = {"authenticated": is_auth}
            if is_auth and auth.credentials:
                expiry_date = auth.credentials.get('expiry_date', 0)
                if expiry_date:
                    # Convert from milliseconds to seconds
                    result["expires_at"] = expiry_date / 1000
            return JSONResponse(result)

        elif provider_type == 'codex':
            from aisbf.auth.codex import CodexOAuth2
            # Handle dict vs object
            if isinstance(provider_config, dict):
                codex_config = provider_config.get('codex_config', {})
            else:
                codex_config = provider_config.codex_config or {}

            if current_user_id is None:
                # Admin user: load from file
                auth = CodexOAuth2(credentials_file=codex_config.get('credentials_file', '~/.aisbf/codex_credentials.json'))
            else:
                # Regular user: load from database with save_callback so refreshed tokens persist
                db = DatabaseRegistry.get_config_database()
                def _save_codex_to_db(creds):
                    try:
                        if db:
                            db.save_user_oauth2_credentials(
                                user_id=current_user_id,
                                provider_id=provider_name,
                                auth_type='codex_oauth2',
                                credentials=creds
                            )
                    except Exception as _e:
                        logger.warning(f"Failed to save refreshed Codex credentials to database: {_e}")
                auth = CodexOAuth2(
                    credentials_file=codex_config.get('credentials_file', '~/.aisbf/codex_credentials.json'),
                    skip_initial_load=True,
                    save_callback=_save_codex_to_db
                )
                # Load credentials from database
                try:
                    if db:
                        db_creds = db.get_user_oauth2_credentials(
                            user_id=current_user_id,
                            provider_id=provider_name,
                            auth_type='codex_oauth2'
                        )
                        if db_creds and db_creds.get('credentials'):
                            auth.credentials = db_creds['credentials']
                except Exception as e:
                    logger.warning(f"Failed to load Codex credentials from database: {e}")

            # get_valid_token_with_refresh handles expiry check and refresh atomically
            token = await auth.get_valid_token_with_refresh()
            if not token:
                if auth.credentials:
                    return JSONResponse({"authenticated": False, "error": "Token expired and refresh failed. Please re-authenticate."})
                return JSONResponse({"authenticated": False})
            result = {"authenticated": True}
            if auth.credentials:
                expires = auth.credentials.get('expires', 0)
                if expires:
                    result["expires_at"] = expires
            return JSONResponse(result)

        elif provider_type == 'coderai':
            from aisbf.providers.coderai import CoderAIProviderHandler

            handler = CoderAIProviderHandler(provider_name, provider_config=provider_config, user_id=current_user_id)
            result = {"authenticated": True, "transport": handler._transport}
            try:
                capabilities = await handler.discover_capabilities()
                if capabilities:
                    result["capabilities"] = capabilities
            except Exception as e:
                result["authenticated"] = False
                result["error"] = str(e)
            return JSONResponse(result)

        else:
            return JSONResponse(
                status_code=400,
                content={"authenticated": False, "error": f"Provider type '{provider_type}' does not support OAuth authentication checks"}
            )

    except Exception as e:
        logger.error(f"Error checking auth for provider {provider_name}: {e}")
        return JSONResponse(
            status_code=500,
            content={"authenticated": False, "error": str(e)}
        )


# User-specific rotation management routes
@router.get("/dashboard/user/rotations", response_class=HTMLResponse)
async def dashboard_user_rotations(request: Request):
    """Redirect to unified rotations endpoint"""
    return RedirectResponse(url=url_for(request, "/dashboard/rotations"), status_code=301)

@router.post("/dashboard/user/rotations")
async def dashboard_user_rotations_save(request: Request, config: str = Form(...)):
    """Redirect to unified rotations save endpoint"""
    return await dashboard_rotations_save(request, config)

@router.delete("/dashboard/user/rotations/{rotation_name}")
async def dashboard_user_rotations_delete(request: Request, rotation_name: str):
    """Delete user-specific rotation configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    db = DatabaseRegistry.get_config_database()

    try:
        db.delete_user_rotation(user_id, rotation_name)
        return JSONResponse({"message": "Rotation deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# User-specific autoselect management routes
@router.get("/dashboard/user/autoselects", response_class=HTMLResponse)
async def dashboard_user_autoselects(request: Request):
    """Redirect to unified autoselect endpoint"""
    return RedirectResponse(url=url_for(request, "/dashboard/autoselect"), status_code=301)

@router.post("/dashboard/user/autoselects")
async def dashboard_user_autoselects_save(request: Request, config: str = Form(...)):
    """Redirect to unified autoselect save endpoint"""
    return await dashboard_autoselect_save(request, config)

@router.delete("/dashboard/user/autoselects/{autoselect_name}")
async def dashboard_user_autoselects_delete(request: Request, autoselect_name: str):
    """Delete user-specific autoselect configuration"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    db = DatabaseRegistry.get_config_database()

    try:
        db.delete_user_autoselect(user_id, autoselect_name)
        return JSONResponse({"message": "Autoselect deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/dashboard/user/reload-config")
async def dashboard_user_reload_config(request: Request):
    """Reload user configuration from database"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    user_id = request.session.get('user_id')
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    try:
        global _user_handlers_cache
        
        # Clear all cached handler instances for this user
        cache_keys_to_remove = [
            key for key in _user_handlers_cache.keys()
            if key.endswith(f"_{user_id}")
        ]
        
        for key in cache_keys_to_remove:
            del _user_handlers_cache[key]
        
        logger.info(f"Cleared {len(cache_keys_to_remove)} cached handler(s) for user {user_id}")
        
        # Force create new handler instances to verify reload works
        get_user_handler('request', user_id)
        get_user_handler('rotation', user_id)
        get_user_handler('autoselect', user_id)
        
        logger.info(f"User {user_id} configuration reloaded successfully from database")
        
        return JSONResponse({
            "message": "Configuration reloaded successfully. All changes have been applied immediately.",
            "handlers_cleared": len(cache_keys_to_remove)
        })

    except Exception as e:
        logger.error(f"Error reloading user configuration: {e}")
        return JSONResponse({"error": f"Failed to reload configuration: {str(e)}"}, status_code=500)

# User API token management routes
