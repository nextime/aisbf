from fastapi import APIRouter, Request, Form, Query, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response, StreamingResponse
from typing import Optional
import json, logging, os, time, re
from pathlib import Path
from datetime import datetime, timedelta
from aisbf.database import DatabaseRegistry
from aisbf import __version__
from aisbf.app.templates import url_for, get_base_url
from aisbf.app.startup import (_reload_global_config, _apply_condense_defaults_provider,
    _apply_condense_defaults_rotation, _providers_json_path, _rotations_json_path,
    _autoselect_json_path)
from aisbf.routes.auth import require_dashboard_auth, require_api_auth, require_api_admin, require_admin
import httpx
try:
    import markdown
except ImportError:
    markdown = None

router = APIRouter()
_config = None
_templates = None
_payment_service = None

logger = logging.getLogger(__name__)

def init(config, templates, payment_service=None):
    global _config, _templates, _payment_service
    _config = config
    _templates = templates
    _payment_service = payment_service


def set_payment_service(service):
    global _payment_service
    _payment_service = service


@router.get("/dashboard/billing/add-method", response_class=HTMLResponse)
async def dashboard_add_payment_method(request: Request):
    """Add payment method page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()

    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)

    stripe_publishable_key = ""
    if 'stripe' in gateways and gateways['stripe'].get('enabled'):
        stripe_publishable_key = gateways['stripe'].get('publishable_key', '')

    return _templates.TemplateResponse(
        request=request,
        name="dashboard/add_payment_method.html",
        context={
            "request": request,
            "session": request.session,
            "enabled_gateways": enabled_gateways,
            "stripe_publishable_key": stripe_publishable_key
        }
    )


@router.post("/dashboard/billing/add-method")
async def dashboard_add_payment_method_post(request: Request):
    """Handle crypto default setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    data = await request.json()
    user_id = request.session.get('user_id')
    payment_type = data.get('type')
    
    if payment_type in ['bitcoin', 'eth', 'usdt', 'usdc']:
        db = DatabaseRegistry.get_config_database()
        
        # Set as default payment method
        db.set_user_default_payment_method(user_id, payment_type)
        
        return JSONResponse({"success": True, "message": f"{payment_type.upper()} set as default payment method"})
    
    return JSONResponse({"success": False, "error": "Invalid payment type"}, status_code=400)

@router.post("/dashboard/billing/add-method/stripe")
async def dashboard_add_payment_method_stripe(request: Request):
    """Handle Stripe payment method addition"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    data = await request.json()
    user_id = request.session.get('user_id')
    payment_method_id = data.get('payment_method_id')

    if not payment_method_id:
        return JSONResponse({"success": False, "error": "Payment method ID required"}, status_code=400)

    db = DatabaseRegistry.get_config_database()

    try:
        # Attach the PM to the Stripe customer so it can be charged later
        if _payment_service and _payment_service.stripe_handler:
            customer_id = await _payment_service.stripe_handler._get_or_create_customer(user_id)
            import stripe as _stripe
            import asyncio as _asyncio
            try:
                await _asyncio.to_thread(
                    _stripe.PaymentMethod.attach,
                    payment_method_id,
                    customer=customer_id
                )
                await _asyncio.to_thread(
                    _stripe.Customer.modify,
                    customer_id,
                    invoice_settings={'default_payment_method': payment_method_id}
                )
            except _stripe.error.InvalidRequestError as e:
                if 'already been attached' not in str(e):
                    raise
        method_id = db.add_payment_method(user_id, 'stripe', payment_method_id, is_default=True, metadata={'stripe_payment_method_id': payment_method_id})
        return JSONResponse({"success": True, "message": "Credit card added successfully"})
    except Exception as e:
        logger.error(f"Error adding Stripe payment method: {e}")
        return JSONResponse({"success": False, "error": "Failed to add payment method"}, status_code=500)

@router.delete("/dashboard/billing/payment-methods/{method_id}")
async def dashboard_delete_payment_method(request: Request, method_id: int):
    """Delete a payment method"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    try:
        # Delete the payment method
        success = db.delete_payment_method(user_id, method_id)
        
        if success:
            logger.info(f"Payment method {method_id} deleted for user {user_id}")
            return JSONResponse({"success": True, "message": "Payment method deleted successfully"})
        else:
            return JSONResponse({"success": False, "error": "Payment method not found or already deleted"}, status_code=404)
    except Exception as e:
        logger.error(f"Error deleting payment method: {e}")
        return JSONResponse({"success": False, "error": "Failed to delete payment method"}, status_code=500)

@router.post("/dashboard/billing/payment-methods/{method_id}/set-default")
async def dashboard_set_default_payment_method(request: Request, method_id: int):
    """Set a payment method as default"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    try:
        # Get the payment method to verify it belongs to the user
        payment_methods = db.get_user_payment_methods(user_id)
        method_exists = any(m['id'] == method_id for m in payment_methods)
        
        if not method_exists:
            return JSONResponse({"success": False, "error": "Payment method not found"}, status_code=404)
        
        # Set as default by updating all methods for this user
        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            
            # Unset all defaults for this user
            cursor.execute(f'''
                UPDATE payment_methods SET is_default = 0
                WHERE user_id = {placeholder}
            ''', (user_id,))
            
            # Set the selected method as default
            cursor.execute(f'''
                UPDATE payment_methods SET is_default = 1
                WHERE id = {placeholder} AND user_id = {placeholder}
            ''', (method_id, user_id))
            
            conn.commit()
        
        logger.info(f"Payment method {method_id} set as default for user {user_id}")
        return JSONResponse({"success": True, "message": "Payment method set as default"})
    except Exception as e:
        logger.error(f"Error setting default payment method: {e}")
        return JSONResponse({"success": False, "error": "Failed to set default payment method"}, status_code=500)

@router.get("/dashboard/billing/add-method/paypal/oauth")
async def dashboard_add_payment_method_paypal_oauth(request: Request):
    """Initiate PayPal Vault setup flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    # Get PayPal settings
    gateways = db.get_payment_gateway_settings()
    paypal_settings = gateways.get('paypal', {})
    
    # Validate PayPal is enabled
    if not paypal_settings.get('enabled'):
        logger.warning(f"PayPal OAuth attempted but PayPal is not enabled (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not enabled",
            status_code=302
        )
    
    # Check if user already has PayPal as payment method
    existing_methods = db.get_user_payment_methods(user_id)
    for method in existing_methods:
        if method.get('type') == 'paypal':
            logger.info(f"User {user_id} already has PayPal payment method")
            return RedirectResponse(
                url="/dashboard/billing?error=PayPal is already added as a payment method",
                status_code=302
            )
    
    # Construct callback URLs
    base_url = get_base_url(request)
    return_url = f"{base_url}/dashboard/billing/add-method/paypal/callback"
    cancel_url = f"{base_url}/dashboard/billing?error=PayPal connection cancelled"
    
    # Create vault setup token using payment service
    result = await payment_service.initiate_paypal_vault_setup(user_id, return_url, cancel_url)
    
    if not result['success']:
        logger.error(f"Failed to create PayPal vault setup: {result.get('error')}")
        return RedirectResponse(
            url="/dashboard/billing?error=Failed to initialize PayPal connection",
            status_code=302
        )
    
    logger.info(f"Initiating PayPal vault setup for user {user_id}")
    
    return RedirectResponse(url=result['approval_url'], status_code=302)

@router.get("/dashboard/billing/add-method/paypal/callback")
async def dashboard_add_payment_method_paypal_callback(request: Request):
    """Handle PayPal vault setup callback"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    user_id = request.session.get('user_id')
    
    # Get query parameters
    token = request.query_params.get('token')
    error = request.query_params.get('error')
    
    # Handle user cancellation
    if error:
        logger.info(f"PayPal vault setup cancelled by user {user_id}: {error}")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal connection cancelled",
            status_code=302
        )
    
    # Validate setup token
    if not token:
        logger.error(f"PayPal callback missing setup token (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid PayPal response",
            status_code=302
        )
    
    try:
        # Complete vault setup using payment service
        result = await payment_service.complete_paypal_vault_setup(user_id, token)
        
        if not result['success']:
            logger.error(f"Failed to complete PayPal vault setup: {result.get('error')}")
            return RedirectResponse(
                url="/dashboard/billing?error=Failed to connect PayPal account",
                status_code=302
            )
        
        logger.info(f"PayPal payment method added for user {user_id} (payment_token={result['payment_token_id']})")
        
        return RedirectResponse(
            url="/dashboard/billing?success=PayPal account connected successfully",
            status_code=302
        )
            
    except Exception as e:
        logger.error(f"PayPal callback error (user_id={user_id}): {str(e)}")
        return RedirectResponse(
            url="/dashboard/billing?error=Failed to connect PayPal account",
            status_code=302
        )
            
    except Exception as e:
        logger.error(f"PayPal callback error (user_id={user_id}): {str(e)}")
        return RedirectResponse(
            url="/dashboard/billing?error=Failed to connect PayPal account",
            status_code=302
        )
    
    # Validate state token (CSRF protection)
    session_state = request.session.get('paypal_oauth_state')
    if not session_state:
        logger.warning(f"PayPal OAuth callback with no session state (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Session expired, please try again",
            status_code=302
        )
    
    if state != session_state:
        logger.warning(f"PayPal OAuth state mismatch (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid request (security check failed)",
            status_code=302
        )
    
    # Clear state token from session
    request.session.pop('paypal_oauth_state', None)
    
    # Validate authorization code
    if not code:
        logger.error(f"PayPal OAuth callback missing authorization code (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid PayPal response",
            status_code=302
        )
    
    # Get PayPal settings
    gateways = db.get_payment_gateway_settings()
    paypal_settings = gateways.get('paypal', {})
    
    client_id = paypal_settings.get('client_id', '').strip()
    client_secret = paypal_settings.get('client_secret', '').strip()
    is_sandbox = paypal_settings.get('sandbox', True)
    
    if not client_id or not client_secret:
        logger.error(f"PayPal OAuth callback but credentials not configured (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not properly configured",
            status_code=302
        )
    
    # Determine PayPal API URLs
    if is_sandbox:
        token_url = "https://api.sandbox.paypal.com/v1/oauth2/token"
        userinfo_url = "https://api.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=openid"
    else:
        token_url = "https://api.paypal.com/v1/oauth2/token"
        userinfo_url = "https://api.paypal.com/v1/identity/oauth2/userinfo?schema=openid"
    
    # Construct callback URL (must match what was sent to PayPal)
    base_url = get_base_url(request)
    redirect_uri = f"{base_url}/dashboard/billing/add-method/paypal/callback"
    
    try:
        # Exchange authorization code for access token
        import base64
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
        
        async with httpx.AsyncClient() as client:
            # Token exchange request
            token_response = await client.post(
                token_url,
                headers={
                    'Authorization': f'Basic {auth_b64}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri
                },
                timeout=30.0
            )
            
            if token_response.status_code != 200:
                logger.error(f"PayPal token exchange failed (user_id={user_id}): {token_response.status_code} {token_response.text}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to connect PayPal account",
                    status_code=302
                )
            
            token_data = token_response.json()
            access_token = token_data.get('access_token')
            
            if not access_token:
                logger.error(f"PayPal token response missing access_token (user_id={user_id})")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to connect PayPal account",
                    status_code=302
                )
            
            logger.info(f"PayPal access token obtained for user {user_id}")
            
            # Fetch user profile
            userinfo_response = await client.get(
                userinfo_url,
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                timeout=30.0
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"PayPal userinfo fetch failed (user_id={user_id}): {userinfo_response.status_code}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to retrieve PayPal account information",
                    status_code=302
                )
            
            userinfo = userinfo_response.json()
            paypal_user_id = userinfo.get('user_id')
            paypal_email = userinfo.get('email')
            paypal_name = userinfo.get('name', '')
            
            if not paypal_user_id or not paypal_email:
                logger.error(f"PayPal userinfo missing required fields (user_id={user_id})")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to retrieve PayPal account information",
                    status_code=302
                )
            
            logger.info(f"PayPal user profile retrieved for user {user_id}: {paypal_email}")
            
            # Check for duplicate PayPal account
            existing_methods = db.get_user_payment_methods(user_id)
            for method in existing_methods:
                if method.get('type') == 'paypal':
                    metadata = method.get('metadata', {})
                    if isinstance(metadata, str):
                        import json
                        metadata = json.loads(metadata)
                    
                    existing_email = metadata.get('paypal_email')
                    existing_user_id = metadata.get('paypal_user_id')
                    
                    if existing_email == paypal_email or existing_user_id == paypal_user_id:
                        logger.info(f"Duplicate PayPal account detected for user {user_id}")
                        return RedirectResponse(
                            url="/dashboard/billing?error=This PayPal account is already connected",
                            status_code=302
                        )
            
            # Store payment method
            is_default = len(existing_methods) == 0
            metadata = {
                'paypal_user_id': paypal_user_id,
                'paypal_email': paypal_email,
                'paypal_name': paypal_name,
                'access_token': access_token,
                'sandbox': is_sandbox
            }
            
            method_id = db.add_payment_method(
                user_id=user_id,
                method_type='paypal',
                identifier=paypal_email,
                is_default=is_default,
                metadata=metadata
            )
            
            if method_id:
                logger.info(f"PayPal payment method added for user {user_id} (method_id={method_id})")
                return RedirectResponse(
                    url="/dashboard/billing?success=PayPal account connected successfully",
                    status_code=302
                )
            else:
                logger.error(f"Failed to store PayPal payment method for user {user_id}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to save payment method",
                    status_code=302
                )
    
    except httpx.TimeoutException as e:
        logger.error(f"PayPal OAuth timeout (user_id={user_id}): {e}")
        return RedirectResponse(
            url="/dashboard/billing?error=Connection timeout, please try again",
            status_code=302
        )
    except httpx.HTTPError as e:
        logger.error(f"PayPal OAuth HTTP error (user_id={user_id}): {e}")
        return RedirectResponse(
            url="/dashboard/billing?error=Connection error, please try again",
            status_code=302
        )
    except Exception as e:
        logger.error(f"PayPal OAuth unexpected error (user_id={user_id}): {e}", exc_info=True)
        return RedirectResponse(
            url="/dashboard/billing?error=An error occurred while connecting PayPal",
            status_code=302
        )

@router.get("/dashboard/response-cache")
async def dashboard_response_cache(request: Request):
    """Response cache dashboard page"""
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
            
    except Exception as e:
        logger.error(f"Error getting response cache stats: {e}")
        stats = {
            'enabled': False,
            'hits': 0,
            'misses': 0,
            'hit_rate': 0.0,
            'size': 0,
            'evictions': 0,
            'backend': 'unknown',
            'error': str(e)
        }
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/response_cache.html",
        context={
        "request": request,
        "session": request.session,
        "stats": stats,
        "is_admin": is_admin
    }
    )

@router.get("/dashboard/rate-limits")
async def dashboard_rate_limits(request: Request):
    """Rate limits dashboard page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/rate_limits.html",
        context={
        "request": request,
        "session": request.session
    }
    )

@router.get("/dashboard/rate-limits/data")
async def dashboard_rate_limits_data(request: Request):
    """Get adaptive rate limit statistics"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.providers import get_all_adaptive_rate_limiters
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    try:
        if is_admin:
            # Admin sees all limiters
            limiters = get_all_adaptive_rate_limiters()
        else:
            # Regular user sees ONLY their own configured providers
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            user_provider_ids = [p['provider_id'] for p in user_providers]
            
            # Get all limiters for this user
            all_limiters = get_all_adaptive_rate_limiters(current_user_id)
            
            # Filter to only show providers the user has actually configured
            limiters = {}
            for provider_id, limiter in all_limiters.items():
                if provider_id in user_provider_ids:
                    limiters[provider_id] = limiter
            
        stats = {}
        for provider_id, limiter in limiters.items():
            stats[provider_id] = limiter.get_stats()
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Error getting rate limit stats: {e}")
        return JSONResponse({
            'error': str(e),
            'providers': {}
        })

@router.post("/dashboard/rate-limits/{provider_id}/reset")
async def dashboard_rate_limits_reset(request: Request, provider_id: str):
    """Reset adaptive rate limiter for a specific provider"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    current_user_id = request.session.get('user_id')
    
    from aisbf.providers import get_all_adaptive_rate_limiters, get_adaptive_rate_limiter
    
    try:
        if is_admin:
            # Admin can reset any limiter
            limiters = get_all_adaptive_rate_limiters()
            if provider_id in limiters:
                limiters[provider_id].reset()
                return JSONResponse({'success': True, 'message': f'Rate limiter for {provider_id} reset successfully'})
            else:
                return JSONResponse({'success': False, 'error': f'Provider {provider_id} not found'}, status_code=404)
        else:
            # Regular user can only reset limiters for providers THEY have configured
            db = DatabaseRegistry.get_config_database()
            user_providers = db.get_user_providers(current_user_id)
            user_provider_ids = [p['provider_id'] for p in user_providers]
            
            if provider_id not in user_provider_ids:
                return JSONResponse({'success': False, 'error': f'You do not have permission to reset rate limiters for {provider_id}'}, status_code=403)
            
            # Reset their user-specific limiter
            user_limiter_key = f"user:{current_user_id}:{provider_id}"
            limiters = get_all_adaptive_rate_limiters()
            if user_limiter_key in limiters:
                limiters[user_limiter_key].reset()
                return JSONResponse({'success': True, 'message': f'Rate limiter for {provider_id} reset successfully'})
            else:
                return JSONResponse({'success': False, 'error': f'Rate limiter for {provider_id} not found'}, status_code=404)
    except Exception as e:
        logger.error(f"Error resetting rate limiter: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@router.post("/dashboard/response-cache/clear")
async def dashboard_response_cache_clear(request: Request):
    """Clear response cache"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    is_admin = request.session.get('role') == 'admin'
    
    if not is_admin:
        return JSONResponse({'success': False, 'error': 'Clearing cache is only available to administrators'}, status_code=403)
    
    from aisbf.cache import get_response_cache
    
    try:
        cache = get_response_cache()
        cache.clear()
        return JSONResponse({'success': True, 'message': 'Response cache cleared'})
    except Exception as e:
        logger.error(f"Error clearing response cache: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@router.post("/dashboard/local-models/clear-cache")
async def dashboard_local_models_clear_cache(request: Request):
    """Delete one or all local HuggingFace model caches and unload in-memory models."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    if request.session.get('role') != 'admin':
        return JSONResponse({'success': False, 'error': 'Admin only'}, status_code=403)

    body = await request.json()
    model_id = body.get('model_id')   # None means "clear all configured models"
    model_type = body.get('model_type')  # 'autoselect', 'condensation', 'nsfw', 'privacy', 'semantic'

    from aisbf.config import config as cfg
    internal = cfg.aisbf.internal_model if (cfg.aisbf and cfg.aisbf.internal_model) else {}

    if model_id:
        model_ids_to_clear = [model_id]
    else:
        model_ids_to_clear = [v for v in [
            internal.get('autoselect_model_id'),
            internal.get('condensation_model_id'),
            internal.get('nsfw_classifier', 'michelleli99/NSFW_text_classifier'),
            internal.get('privacy_classifier', 'iiiorg/piiranha-v1-detect-personal-information'),
            internal.get('semantic_vectorization', 'sentence-transformers/all-MiniLM-L6-v2'),
        ] if v]

    cleared = []
    errors = []

    # 1. Remove disk cache via huggingface_hub
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id in model_ids_to_clear:
                commit_hashes = [rev.commit_hash for rev in repo.revisions]
                if commit_hashes:
                    delete_strategy = cache_info.delete_revisions(*commit_hashes)
                    delete_strategy.execute()
                    cleared.append(repo.repo_id)
    except Exception as e:
        errors.append(f"Cache deletion error: {e}")

    # 2. Unload in-memory models
    try:
        from aisbf.classifier import content_classifier, semantic_classifier
        should_reset_content = not model_id or model_type in ('nsfw', 'privacy')
        should_reset_semantic = not model_id or model_type == 'semantic'
        if should_reset_content:
            content_classifier.reset()
        if should_reset_semantic:
            semantic_classifier.reset()
    except Exception as e:
        errors.append(f"Classifier reset error: {e}")

    try:
        should_reset_autoselect = not model_id or model_type == 'autoselect'
        if should_reset_autoselect and autoselect_handler:
            autoselect_handler.reset_internal_model()
    except Exception as e:
        errors.append(f"Autoselect handler reset error: {e}")

    if errors:
        return JSONResponse({'success': len(cleared) > 0, 'cleared': cleared, 'errors': errors})
    return JSONResponse({'success': True, 'cleared': cleared, 'message': f'Cleared {len(cleared)} model(s) from cache'})

@router.get("/dashboard/docs", response_class=HTMLResponse)
async def dashboard_docs(request: Request):
    """Display documentation"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Try to find DOCUMENTATION.md in multiple locations
    search_paths = [
        Path.home() / '.aisbf' / 'DOCUMENTATION.md',
        Path.home() / '.local' / 'share' / 'aisbf' / 'DOCUMENTATION.md',
        Path('/usr/share/aisbf') / 'DOCUMENTATION.md',
        Path(__file__).parent / 'DOCUMENTATION.md',
    ]
    
    doc_path = None
    for path in search_paths:
        if path.exists():
            doc_path = path
            break
    
    if doc_path and doc_path.exists():
        with open(doc_path, encoding='utf-8') as f:
            markdown_content = f.read()
            # Convert markdown to HTML with extensions for better formatting
            html_content = markdown.markdown(
                markdown_content,
                extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'toc']
            )
    else:
        html_content = "<p>Documentation file not found.</p>"
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/docs.html",
        context={
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "Documentation"
    }
    )

@router.get("/dashboard/about", response_class=HTMLResponse)
async def dashboard_about(request: Request):
    """Display README/About"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Try to find README.md in multiple locations
    search_paths = [
        Path.home() / '.aisbf' / 'README.md',
        Path.home() / '.local' / 'share' / 'aisbf' / 'README.md',
        Path('/usr/share/aisbf') / 'README.md',
        Path(__file__).parent / 'README.md',
    ]
    
    readme_path = None
    for path in search_paths:
        if path.exists():
            readme_path = path
            break
    
    if readme_path and readme_path.exists():
        with open(readme_path, encoding='utf-8') as f:
            markdown_content = f.read()
            # Convert markdown to HTML with extensions for better formatting
            html_content = markdown.markdown(
                markdown_content,
                extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists']
            )
            # Rewrite DOCUMENTATION.md links (relative or absolute) to /dashboard/docs
            html_content = re.sub(
                r'href="(?:https?://[^"]*?/)?DOCUMENTATION\.md#([^"]*)"',
                r'href="/dashboard/docs#\1"',
                html_content
            )
            html_content = re.sub(
                r'href="(?:https?://[^"]*?/)?DOCUMENTATION\.md"',
                'href="/dashboard/docs"',
                html_content
            )
    else:
        html_content = "<p>README file not found.</p>"
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/docs.html",
        context={
        "request": request,
        "session": request.session,
        "content": html_content,
        "title": "About"
    }
    )

@router.get("/dashboard/license", response_class=HTMLResponse)
async def dashboard_license(request: Request):
    """Display License"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Try to find LICENSE.txt in multiple locations
    search_paths = [
        Path.home() / '.aisbf' / 'LICENSE.txt',
        Path.home() / '.local' / 'share' / 'aisbf' / 'LICENSE.txt',
        Path('/usr/share/aisbf') / 'LICENSE.txt',
        Path(__file__).parent / 'LICENSE.txt',
    ]
    
    license_path = None
    for path in search_paths:
        if path.exists():
            license_path = path
            break
    
    if license_path and license_path.exists():
        with open(license_path, encoding='utf-8') as f:
            content = f.read()
            # Convert to HTML with pre tags to preserve formatting
            html_content = f"<pre style='white-space: pre-wrap; word-wrap: break-word; background: #0f3460; padding: 20px; border-radius: 6px; color: #e0e0e0; font-family: inherit;'>{content}</pre>"
    else:
        html_content = "<p>License file not found.</p>"
    
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/docs.html",
        context={
            "request": request,
            "session": request.session,
            "content": html_content,
            "title": "License"
        }
    )


@router.get("/dashboard/blocked", response_class=HTMLResponse)
async def blocked_page(request: Request):
    """Display blocked access page."""
    return _templates.TemplateResponse(request=request, name="blocked.html", context={"request": request})


