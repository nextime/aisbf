from fastapi import APIRouter, Request, Form, Query, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from typing import Optional
import time, logging, secrets, hashlib, os, re, hmac
from pathlib import Path
from datetime import datetime, timedelta
from aisbf.database import DatabaseRegistry
from aisbf.database import _hash_password as _db_hash_password, _verify_password as _db_verify_password
from aisbf.app.startup import _login_rate_limit_check, _login_record_failure, _login_clear_failures, _send_admin_notification_email
from aisbf.app.templates import url_for, get_base_url

router = APIRouter()
_config = None
_templates = None
_server_config = None

_DEFAULT_ADMIN_SHA256 = '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'
_MUST_CHANGE_PASSWORD_WHITELIST = (
    '/dashboard/settings', '/dashboard/logout', '/api/admin/settings/',
    '/dashboard/tor/status', '/dashboard/response-cache/stats',
    '/dashboard/response-cache/clear', '/dashboard/local-models/clear-cache',
    '/dashboard/test-smtp', '/dashboard/restart',
)

def init(config, templates, server_config):
    global _config, _templates, _server_config
    _config = config
    _templates = templates
    _server_config = server_config

logger = logging.getLogger(__name__)


@router.get("/dashboard/profile-pic")
async def dashboard_profile_pic(request: Request):
    """Serve the logged-in user's profile picture from the database."""
    user_id = request.session.get('user_id')
    if not user_id:
        return Response(status_code=404)
    try:
        db = DatabaseRegistry.get_config_database()
        user = db.get_user_by_id(user_id)
        pic = user.get('profile_pic') if user else None
        if not pic:
            return Response(status_code=404)
        if pic.startswith('data:'):
            header, b64data = pic.split(',', 1)
            mime = header.split(':')[1].split(';')[0]
            import base64
            img_bytes = base64.b64decode(b64data)
            return Response(content=img_bytes, media_type=mime,
                            headers={"Cache-Control": "private, max-age=3600"})
        return RedirectResponse(url=pic)
    except Exception:
        return Response(status_code=404)


@router.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page(request: Request):
    """Show dashboard login page"""
    try:
        signup_enabled = False
        if _config and hasattr(_config, 'aisbf') and _config.aisbf:
            signup_enabled = getattr(_config.aisbf.signup, 'enabled', False) if _config.aisbf.signup else False

        smtp_enabled = False
        if _config and hasattr(_config, 'aisbf') and _config.aisbf and hasattr(_config.aisbf, 'smtp') and _config.aisbf.smtp:
            smtp_enabled = getattr(_config.aisbf.smtp, 'enabled', False)

        show_verify_email = request.query_params.get('signup') == 'success' and smtp_enabled
        error_message = request.query_params.get('error')
        success_message = request.query_params.get('success')

        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        template = _templates.get_template("dashboard/login.html")
        html_content = template.render(
            request=request,
            signup_enabled=signup_enabled,
            smtp_enabled=smtp_enabled,
            show_verify_email=show_verify_email,
            error=error_message,
            success=success_message,
            config=_config.aisbf if _config and _config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True
        )
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering login page: {e}", exc_info=True)
        raise


@router.get("/auth/logincheck")
async def auth_logincheck(request: Request):
    """Serve JavaScript that redirects to dashboard if user is logged in"""
    is_logged_in = request.session.get('logged_in', False)
    if is_logged_in:
        expires_at = request.session.get('expires_at')
        if expires_at and int(time.time()) > expires_at:
            is_logged_in = False

    if is_logged_in:
        root_path = request.scope.get("root_path", "")
        dashboard_path = f"{root_path}/dashboard"
        js_content = f"""
(function() {{
    if (window.location.pathname !== '{dashboard_path}') {{
        window.location.href = '{dashboard_path}';
    }}
}})();
"""
    else:
        js_content = """
(function() {
    // User not logged in, do nothing
})();
"""
    return Response(
        content=js_content,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )


@router.post("/dashboard/login")
async def dashboard_login(request: Request, username: str = Form(...), password: str = Form(...), remember_me: bool = Form(False)):
    """Handle dashboard login"""
    client_ip = request.client.host if request.client else "unknown"

    if _login_rate_limit_check(client_ip, username):
        return RedirectResponse(
            url=url_for(request, "/dashboard/login") + "?error=Too+many+failed+attempts.+Please+wait+and+try+again.",
            status_code=303
        )

    db = DatabaseRegistry.get_config_database()
    user = db.authenticate_user(username, password)

    if user:
        logger.info(f"User authenticated: username={username}, email={user.get('email')}, user_id={user['id']}")
        request.session['logged_in'] = True
        _login_clear_failures(client_ip, username)
        request.session['username'] = username
        request.session['display_name'] = user.get('display_name') or ''
        request.session['email'] = user.get('email') or ''
        request.session['role'] = user['role']
        request.session['user_id'] = user['id']
        request.session['has_profile_pic'] = bool(user.get('profile_pic'))
        request.session['remember_me'] = remember_me
        request.session['email_verified'] = user['email_verified']
        if remember_me:
            request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
        else:
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

        with db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if db.db_type == 'sqlite' else '%s'
            cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (user['id'],))
            conn.commit()

        if not user['email_verified']:
            if user['created_at']:
                if isinstance(user['created_at'], str):
                    created_at = datetime.fromisoformat(user['created_at'])
                else:
                    created_at = user['created_at']
            else:
                created_at = datetime.now()
            if datetime.now() - created_at > timedelta(hours=24):
                db.delete_user(user['id'])
                return _templates.TemplateResponse(
                    request=request,
                    name="dashboard/login.html",
                    context={
                        "request": request,
                        "error": "Your account verification has expired. Please sign up again.",
                        "config": _config.aisbf if _config and _config.aisbf else {}
                    }
                )
            else:
                return RedirectResponse(url=url_for(request, "/dashboard/verify"), status_code=303)

        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    dashboard_config = _server_config.get('dashboard_config', {}) if _server_config else {}
    stored_username = dashboard_config.get('username', 'admin')
    stored_password_hash = dashboard_config.get('password', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918')

    if username == stored_username and _db_verify_password(password, stored_password_hash):
        _login_clear_failures(client_ip, username)
        request.session['logged_in'] = True
        request.session['username'] = username
        request.session['role'] = 'admin'
        request.session['user_id'] = None
        request.session['remember_me'] = remember_me
        request.session['must_change_password'] = (stored_password_hash == _DEFAULT_ADMIN_SHA256)
        if remember_me:
            request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
        else:
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
        if request.session['must_change_password']:
            return RedirectResponse(
                url=url_for(request, "/dashboard/settings") + "?warning=default_password",
                status_code=303
            )
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    _login_record_failure(client_ip, username)
    return RedirectResponse(url=url_for(request, "/dashboard/login") + "?error=Invalid username or password", status_code=303)


@router.get("/dashboard/signup", response_class=HTMLResponse)
async def dashboard_signup_page(request: Request):
    """Show dashboard signup page"""
    try:
        signup_enabled = False
        if _config and hasattr(_config, 'aisbf') and _config.aisbf:
            signup_enabled = getattr(_config.aisbf.signup, 'enabled', False) if _config.aisbf.signup else False

        if not signup_enabled:
            return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        template = _templates.get_template("dashboard/signup.html")
        html_content = template.render(
            request=request,
            config=_config.aisbf if _config and _config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True
        )
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering signup page: {e}", exc_info=True)
        raise


@router.post("/dashboard/signup")
async def dashboard_signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle user signup"""
    from aisbf.email_utils import hash_password, generate_verification_token, send_verification_email

    signup_enabled = False
    if _config and hasattr(_config, 'aisbf') and _config.aisbf:
        signup_enabled = getattr(_config.aisbf.signup, 'enabled', False) if _config.aisbf.signup else False

    if not signup_enabled:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    if not re.match(r"^[a-zA-Z0-9_.-]+$", username):
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "Username can only contain letters, numbers, underscores, hyphens, and dots",
                     "config": _config.aisbf if _config and _config.aisbf else {}})

    if len(username) < 3 or len(username) > 50:
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "Username must be between 3 and 50 characters",
                     "config": _config.aisbf if _config and _config.aisbf else {}})

    if password != confirm_password:
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "Passwords do not match",
                     "config": _config.aisbf if _config and _config.aisbf else {}})

    if len(password) < 8:
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "Password must be at least 8 characters long",
                     "config": _config.aisbf if _config and _config.aisbf else {}})

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "Invalid email address",
                     "config": _config.aisbf if _config and _config.aisbf else {}})

    try:
        db = DatabaseRegistry.get_config_database()
        existing_user_by_username = db.get_user_by_username(username)
        if existing_user_by_username:
            return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
                context={"request": request, "error": "This username is already taken. Please choose a different one.",
                         "config": _config.aisbf if _config and _config.aisbf else {}})
    except Exception as e:
        logger.error(f"Error checking username uniqueness: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "An error occurred during signup. Please try again.",
                     "config": _config.aisbf if _config and _config.aisbf else {}})

    try:
        db = DatabaseRegistry.get_config_database()
        existing_user = db.get_user_by_email(email)
        if existing_user:
            if existing_user['email_verified']:
                return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
                    context={"request": request, "error": "An account with this email already exists",
                             "config": _config.aisbf if _config and _config.aisbf else {}})
            else:
                verification_token = generate_verification_token()
                expires_at = datetime.now() + timedelta(hours=24)
                db.set_verification_token(existing_user['id'], verification_token, expires_at)
                db.update_last_verification_email_sent(existing_user['id'], datetime.now())
                try:
                    base_url = get_base_url(request)
                    send_verification_email(email, email, verification_token, base_url, _config.aisbf.smtp if _config.aisbf.smtp else None)
                    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)
                except Exception as e:
                    logger.error(f"Failed to send verification email: {e}")
                    return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
                        context={"request": request, "message": "Account already exists but not verified. A new verification email has been sent.",
                                 "config": _config.aisbf if _config and _config.aisbf else {}})

        password_hash = hash_password(password)
        verification_token = generate_verification_token()
        user_id = db.create_user(username=username, password_hash=password_hash, role='user', email=email, email_verified=False)

        _send_admin_notification_email(
            _config,
            'new_user_signup',
            f"New user signup: {username}",
            f"<h2>New User Signup</h2><p>A new user has registered on your AISBF instance.</p>"
            f"<ul><li><b>Username:</b> {username}</li><li><b>Email:</b> {email or '(none)'}</li></ul>"
        )

        expires_at = datetime.now() + timedelta(hours=24)
        db.set_verification_token(user_id, verification_token, expires_at)
        db.update_last_verification_email_sent(user_id, datetime.now())

        try:
            base_url = get_base_url(request)
            send_verification_email(email, email, verification_token, base_url, _config.aisbf.smtp if _config.aisbf.smtp else None)
            return RedirectResponse(url=url_for(request, "/dashboard/login") + "?signup=success", status_code=303)
        except Exception as e:
            logger.error(f"Failed to send verification email: {e}")
            return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
                context={"request": request, "message": "Account created successfully! However, there was an issue sending the verification email. Please contact an administrator.",
                         "config": _config.aisbf if _config and _config.aisbf else {}})

    except Exception as e:
        logger.error(f"Error during signup: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/signup.html",
            context={"request": request, "error": "An error occurred during signup. Please try again.",
                     "config": _config.aisbf if _config and _config.aisbf else {}})


@router.get("/dashboard/verify")
async def verify_email_page(request: Request):
    """Show email verification page"""
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    if not user or user['email_verified']:
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    can_resend = True
    if user.get('last_verification_email_sent'):
        if isinstance(user['last_verification_email_sent'], str):
            last_sent = datetime.fromisoformat(user['last_verification_email_sent'])
        else:
            last_sent = user['last_verification_email_sent']
        if datetime.now() - last_sent < timedelta(minutes=10):
            can_resend = False

    return _templates.TemplateResponse(request=request, name="dashboard/verify.html",
        context={"request": request, "user": user, "can_resend": can_resend,
                 "config": _config.aisbf if _config and _config.aisbf else {}})


@router.post("/dashboard/resend-verification")
async def resend_verification(request: Request):
    """Resend verification email"""
    from aisbf.email_utils import send_verification_email, generate_verification_token

    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    db = DatabaseRegistry.get_config_database()
    user = db.get_user_by_id(user_id)
    if not user or user['email_verified']:
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    if user.get('last_verification_email_sent'):
        if isinstance(user['last_verification_email_sent'], str):
            last_sent = datetime.fromisoformat(user['last_verification_email_sent'])
        else:
            last_sent = user['last_verification_email_sent']
        if datetime.now() - last_sent < timedelta(minutes=10):
            return _templates.TemplateResponse(request=request, name="dashboard/verify.html",
                context={"request": request, "user": user, "can_resend": False,
                         "error": "Please wait 10 minutes before requesting another verification email.",
                         "config": _config.aisbf if _config and _config.aisbf else {}})

    verification_token = generate_verification_token()
    expires_at = datetime.now() + timedelta(hours=24)
    db.set_verification_token(user_id, verification_token, expires_at)
    db.update_last_verification_email_sent(user_id, datetime.now())

    try:
        base_url = get_base_url(request)
        send_verification_email(user['email'], user['username'], verification_token, base_url, _config.aisbf.smtp if _config.aisbf.smtp else None)
        message = "Verification email sent successfully!"
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        message = "Failed to send verification email. Please try again later."

    return _templates.TemplateResponse(request=request, name="dashboard/verify.html",
        context={"request": request, "user": user, "can_resend": False, "message": message,
                 "config": _config.aisbf if _config and _config.aisbf else {}})


@router.get("/dashboard/verify-email")
async def verify_email(request: Request, token: str, email: str):
    """Handle email verification"""
    try:
        db = DatabaseRegistry.get_config_database()
        if db.verify_email_token(email, token):
            db.verify_email(email)
            if request.session.get('logged_in'):
                request.session['email_verified'] = True
            return RedirectResponse(url=url_for(request, "/dashboard/login") + "?success=Email verified successfully! You can now log in.", status_code=303)
        else:
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "error": "Invalid or expired verification token",
                         "config": _config.aisbf if _config and _config.aisbf else {}})
    except Exception as e:
        logger.error(f"Error during email verification: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/login.html",
            context={"request": request, "error": "An error occurred during email verification",
                     "config": _config.aisbf if _config and _config.aisbf else {}})


@router.get("/dashboard/forgot-password", response_class=HTMLResponse)
async def dashboard_forgot_password_page(request: Request):
    """Show forgot password page"""
    try:
        smtp_enabled = False
        if _config and hasattr(_config, 'aisbf') and _config.aisbf and hasattr(_config.aisbf, 'smtp'):
            smtp_enabled = getattr(_config.aisbf.smtp, 'enabled', False)

        if not smtp_enabled:
            return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        template = _templates.get_template("dashboard/forgot_password.html")
        html_content = template.render(
            request=request,
            config=_config.aisbf if _config and _config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True
        )
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering forgot password page: {e}", exc_info=True)
        raise


@router.post("/dashboard/forgot-password")
async def dashboard_forgot_password(request: Request, email: str = Form(...)):
    """Handle forgot password request"""
    from aisbf.email_utils import generate_password_reset_token, send_password_reset_email

    smtp_enabled = False
    if _config and hasattr(_config, 'aisbf') and _config.aisbf and hasattr(_config.aisbf, 'smtp'):
        smtp_enabled = getattr(_config.aisbf.smtp, 'enabled', False)

    if not smtp_enabled:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        db = DatabaseRegistry.get_config_database()
        user = db.get_user_by_email(email)
        if user and user['email_verified']:
            reset_token = generate_password_reset_token()
            expires_at = datetime.now() + timedelta(hours=1)
            db.set_password_reset_token(user['id'], reset_token, expires_at)
            try:
                base_url = get_base_url(request)
                success = send_password_reset_email(
                    to_email=email,
                    username=user.get('username', email),
                    reset_token=reset_token,
                    base_url=base_url,
                    smtp_config=_config.aisbf.smtp
                )
                if not success:
                    logger.error(f"Failed to send password reset email to {email}")
            except Exception as e:
                logger.error(f"Failed to send password reset email: {e}")

        return _templates.TemplateResponse(request=request, name="dashboard/forgot_password.html",
            context={"request": request, "success": True,
                     "message": "If an account exists with that email address, we have sent a password reset link.",
                     "message_type": "success"})
    except Exception as e:
        logger.error(f"Error processing forgot password request: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/forgot_password.html",
            context={"request": request, "error": "An error occurred processing your request. Please try again later.",
                     "config": _config.aisbf if _config and _config.aisbf else {}})


@router.get("/dashboard/reset-password", response_class=HTMLResponse)
async def dashboard_reset_password_page(request: Request, token: str = Query(...), email: str = Query(...)):
    """Show password reset page"""
    try:
        db = DatabaseRegistry.get_config_database()
        token_valid = db.validate_password_reset_token(email, token)
        if not token_valid:
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "error": "Invalid or expired password reset token. Please request a new one.",
                         "config": _config.aisbf if _config and _config.aisbf else {}})

        is_cloud = request.url.hostname == 'aisbf.cloud' or request.url.hostname.endswith('.aisbf.cloud')
        is_onion = request.url.hostname == 'aisbfity4ud6nsht53tsh2iauaur2e4dah2gplcprnikyjpkg72vfjad.onion'
        is_aisbf_cloud = is_cloud or is_onion

        template = _templates.get_template("dashboard/reset_password.html")
        html_content = template.render(
            request=request,
            email=email,
            token=token,
            config=_config.aisbf if _config and _config.aisbf else {},
            is_aisbf_cloud=is_aisbf_cloud,
            welcome_shown=True
        )
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error rendering reset password page: {e}", exc_info=True)
        raise


@router.post("/dashboard/reset-password")
async def dashboard_reset_password(
    request: Request,
    email: str = Form(...),
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle password reset confirmation"""
    from aisbf.email_utils import hash_password

    try:
        db = DatabaseRegistry.get_config_database()
        reset_user = db.get_user_by_reset_token(token)
        if not reset_user or reset_user.get('email', '').lower() != email.lower():
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "error": "Invalid or expired password reset token. Please request a new one.",
                         "config": _config.aisbf if _config and _config.aisbf else {}})

        if password != confirm_password:
            return _templates.TemplateResponse(request=request, name="dashboard/reset_password.html",
                context={"request": request, "email": email, "token": token, "error": "Passwords do not match",
                         "config": _config.aisbf if _config and _config.aisbf else {}})

        if len(password) < 8:
            return _templates.TemplateResponse(request=request, name="dashboard/reset_password.html",
                context={"request": request, "email": email, "token": token,
                         "error": "Password must be at least 8 characters long",
                         "config": _config.aisbf if _config and _config.aisbf else {}})

        password_hash = hash_password(password)
        user_id = reset_user['id']
        db.update_user_password(user_id, password_hash)
        db.clear_password_reset_token(user_id)
        logger.info(f"Password successfully reset for user {email}")

        return _templates.TemplateResponse(request=request, name="dashboard/login.html",
            context={"request": request,
                     "message": "Password has been reset successfully. You can now login with your new password.",
                     "config": _config.aisbf if _config and _config.aisbf else {}})
    except Exception as e:
        logger.error(f"Error processing password reset: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/reset_password.html",
            context={"request": request, "email": email, "token": token,
                     "error": "An error occurred resetting your password. Please try again later.",
                     "config": _config.aisbf if _config and _config.aisbf else {}})


@router.get("/dashboard/logout")
async def dashboard_logout(request: Request):
    """Handle dashboard logout"""
    admin_session = request.session.get('admin_session')
    if admin_session:
        # Restore admin session after impersonation
        request.session.clear()
        for k, v in admin_session.items():
            request.session[k] = v
        return RedirectResponse(url=url_for(request, "/dashboard/users"), status_code=303)
    request.session.clear()
    return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)


@router.get("/dashboard/profile", response_class=HTMLResponse)
async def dashboard_profile(request: Request):
    """User profile page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    user = db.get_user_by_id(user_id)

    return _templates.TemplateResponse(request=request, name="dashboard/profile.html",
        context={"session": request.session, "user": user,
                 "success": request.query_params.get('success'),
                 "error": request.query_params.get('error')})


@router.post("/dashboard/profile")
async def dashboard_profile_save(request: Request, username: str = Form(...), display_name: str = Form("")):
    """Save user profile changes"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    try:
        db.update_user_profile(user_id, username, None, display_name if display_name else None, None)
        request.session['username'] = username
        request.session['display_name'] = display_name or ''
        return RedirectResponse(url=url_for(request, "/dashboard/profile?success=Profile updated successfully"), status_code=303)
    except Exception as e:
        return RedirectResponse(url=url_for(request, f"/dashboard/profile?error=Failed to update profile: {str(e)}"), status_code=303)


_PROFILE_PIC_MAX_BYTES = 5 * 1024 * 1024  # 5 MB assembled limit

@router.post("/dashboard/profile/upload-pic/chunk")
async def dashboard_profile_pic_chunk(
    request: Request,
    file_name: str = Form(...),
    chunk_number: int = Form(...),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
    file: UploadFile = File(...)
):
    """Chunked profile picture upload."""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    user_id = request.session.get('user_id')

    if total_size > _PROFILE_PIC_MAX_BYTES:
        return JSONResponse({"success": False, "error": "Image too large. Maximum size is 5 MB."}, status_code=400)

    content_type = file.content_type or ''
    if not content_type.startswith('image/'):
        ext = Path(file_name).suffix.lower()
        ext_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                   '.gif': 'image/gif', '.webp': 'image/webp'}
        content_type = ext_map.get(ext, '')
        if not content_type:
            return JSONResponse({"success": False, "error": "Invalid file type. Upload JPG, PNG, GIF or WebP."}, status_code=400)

    import hashlib as _hl
    upload_id = _hl.sha256(f"{user_id}:{file_name}:{total_size}".encode()).hexdigest()[:16]
    temp_dir = Path.home() / '.aisbf' / 'temp_uploads' / 'profile_pics'
    temp_dir.mkdir(parents=True, exist_ok=True)

    chunk_data = await file.read()
    chunk_path = temp_dir / f"{upload_id}.part{chunk_number}"
    with open(chunk_path, 'wb') as f:
        f.write(chunk_data)

    received = list(temp_dir.glob(f"{upload_id}.part*"))
    if len(received) < total_chunks:
        return JSONResponse({"success": True, "complete": False, "chunk": chunk_number})

    try:
        assembled = bytearray()
        for i in range(1, total_chunks + 1):
            part = temp_dir / f"{upload_id}.part{i}"
            assembled.extend(part.read_bytes())
            part.unlink()

        if len(assembled) > _PROFILE_PIC_MAX_BYTES:
            return JSONResponse({"success": False, "error": "Assembled image exceeds 5 MB limit."}, status_code=400)

        import base64 as _b64
        data_url = f"data:{content_type};base64,{_b64.b64encode(bytes(assembled)).decode()}"

        db = DatabaseRegistry.get_config_database()
        db.update_user_profile(user_id, request.session.get('username', ''), None, None, data_url)
        request.session['has_profile_pic'] = True

        return JSONResponse({"success": True, "complete": True})
    except Exception as e:
        logger.error(f"Profile pic assembly error for user {user_id}: {e}")
        for part in temp_dir.glob(f"{upload_id}.part*"):
            try:
                part.unlink()
            except Exception:
                pass
        return JSONResponse({"success": False, "error": "Upload failed. Please try again."}, status_code=500)


@router.get("/dashboard/change-password", response_class=HTMLResponse)
async def dashboard_change_password(request: Request):
    """Change user password page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    return _templates.TemplateResponse(request=request, name="dashboard/change_password.html",
        context={"session": request.session,
                 "success": request.query_params.get('success'),
                 "error": request.query_params.get('error')})


@router.post("/dashboard/change-password")
async def dashboard_change_password_save(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    """Save password change"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    if new_password != confirm_password:
        return RedirectResponse(url=url_for(request, "/dashboard/change-password?error=New passwords do not match"), status_code=303)

    if len(new_password) < 6:
        return RedirectResponse(url=url_for(request, "/dashboard/change-password?error=New password must be at least 6 characters"), status_code=303)

    try:
        if not db.verify_user_password(user_id, current_password):
            return RedirectResponse(url=url_for(request, "/dashboard/change-password?error=Current password is incorrect"), status_code=303)
        db.update_user_password(user_id, _db_hash_password(new_password))
        return RedirectResponse(url=url_for(request, "/dashboard/change-password?success=Password changed successfully"), status_code=303)
    except Exception as e:
        return RedirectResponse(url=url_for(request, f"/dashboard/change-password?error=Failed to change password: {str(e)}"), status_code=303)


@router.get("/dashboard/change-email", response_class=HTMLResponse)
async def dashboard_change_email(request: Request):
    """Change email page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    return _templates.TemplateResponse(request=request, name="dashboard/change_email.html",
        context={"session": request.session,
                 "success": request.query_params.get('success'),
                 "error": request.query_params.get('error')})


@router.post("/dashboard/change-email")
async def dashboard_change_email_save(request: Request, new_email: str = Form(...), password: str = Form(...)):
    """Process email change request"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    from aisbf.email_utils import send_email_verification, hash_password

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    try:
        if not db.verify_user_password(user_id, password):
            return RedirectResponse(url=url_for(request, "/dashboard/change-email?error=Incorrect password"), status_code=303)

        existing_user = db.get_user_by_email(new_email)
        if existing_user and existing_user['id'] != user_id:
            return RedirectResponse(url=url_for(request, "/dashboard/change-email?error=Email address already in use"), status_code=303)

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=24)

        request.session['pending_email_change'] = {
            'new_email': new_email,
            'token': token,
            'expires_at': expires_at.isoformat()
        }

        base_url = get_base_url(request)
        if _config and _config.aisbf and _config.aisbf.smtp and _config.aisbf.smtp.enabled:
            send_email_verification(new_email, f"{base_url}/dashboard/verify-email-change?token={token}&email={new_email}", _config.aisbf.smtp)
            return RedirectResponse(
                url=url_for(request, "/dashboard/change-email?success=Verification email sent to new address. Please check your inbox."),
                status_code=303
            )
        else:
            return RedirectResponse(
                url=url_for(request, "/dashboard/change-email?error=Email service not configured. Please contact administrator."),
                status_code=303
            )
    except Exception as e:
        logger.error(f"Email change error: {e}")
        return RedirectResponse(url=url_for(request, f"/dashboard/change-email?error=Failed to process email change: {str(e)}"), status_code=303)


@router.get("/dashboard/verify-email-change")
async def verify_email_change(request: Request, token: str = Query(...), email: str = Query(...)):
    """Verify new email address"""
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')

    if not user_id:
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        pending = request.session.get('pending_email_change', {})

        if not pending or pending.get('token') != token or pending.get('new_email') != email:
            return _templates.TemplateResponse(request=request, name="dashboard/change_email.html",
                context={"session": request.session, "error": "Invalid or expired verification link"})

        expires_at = datetime.fromisoformat(pending['expires_at'])
        if datetime.now() > expires_at:
            return _templates.TemplateResponse(request=request, name="dashboard/change_email.html",
                context={"session": request.session, "error": "Verification link has expired"})

        db.update_user_email(user_id, email)
        request.session['email'] = email
        request.session.pop('pending_email_change', None)

        return RedirectResponse(url=url_for(request, "/dashboard/profile?success=Email address updated successfully"), status_code=303)
    except Exception as e:
        logger.error(f"Email verification error: {e}")
        return _templates.TemplateResponse(request=request, name="dashboard/change_email.html",
            context={"session": request.session, "error": f"Failed to verify email: {str(e)}"})


@router.get("/dashboard/delete-account", response_class=HTMLResponse)
async def dashboard_delete_account(request: Request):
    """Delete account confirmation page"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    subscription = db.get_user_subscription(user_id)
    has_subscription = subscription is not None and subscription.get('status') == 'active'
    subscription_tier = subscription.get('tier_name', '') if subscription else ''

    return _templates.TemplateResponse(request=request, name="dashboard/delete_account.html",
        context={"session": request.session, "error": request.query_params.get('error'),
                 "has_subscription": has_subscription, "subscription_tier": subscription_tier})


@router.post("/dashboard/delete-account")
async def dashboard_delete_account_confirm(request: Request, password: str = Form(...), confirmation: str = Form(...)):
    """Process account deletion"""
    auth_check = require_dashboard_auth(request)
    if isinstance(auth_check, RedirectResponse):
        return auth_check

    user_id = request.session.get('user_id')
    db = DatabaseRegistry.get_config_database()

    try:
        if confirmation != "DELETE":
            return RedirectResponse(url=url_for(request, "/dashboard/delete-account?error=Please type DELETE to confirm"), status_code=303)

        if not db.verify_user_password(user_id, password):
            return RedirectResponse(url=url_for(request, "/dashboard/delete-account?error=Incorrect password"), status_code=303)

        username = request.session.get('username', f'user #{user_id}')
        db.delete_user(user_id)

        _send_admin_notification_email(
            _config,
            'user_deleted_account',
            f"User deleted account: {username}",
            f"<h2>User Deleted Account</h2><p>User <b>{username}</b> (ID {user_id}) has deleted their account.</p>"
        )

        request.session.clear()
        return RedirectResponse(url=url_for(request, "/dashboard/login?message=Account deleted successfully"), status_code=303)
    except Exception as e:
        logger.error(f"Account deletion error: {e}")
        return RedirectResponse(url=url_for(request, f"/dashboard/delete-account?error=Failed to delete account: {str(e)}"), status_code=303)


# ==============================================
# OAuth2 Authentication Endpoints (Google + GitHub)
# ==============================================

_oauth2_instances = {}

@router.get("/auth/oauth2/google")
async def oauth2_google_initiate(request: Request):
    """Initiate Google OAuth2 authentication flow"""
    if not (_config and _config.aisbf and _config.aisbf.oauth2 and
            _config.aisbf.oauth2.google and _config.aisbf.oauth2.google.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        from aisbf.auth.google import GoogleOAuth2

        client_id = _config.aisbf.oauth2.google.client_id
        client_secret = _config.aisbf.oauth2.google.client_secret
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/google/callback"

        oauth = GoogleOAuth2(client_id, client_secret, redirect_uri)
        auth_url = oauth.get_authorization_url(_config.aisbf.oauth2.google.scopes)

        request.session['oauth2_google'] = {
            'state': oauth._state,
            'code_verifier': oauth._code_verifier
        }

        referer = request.headers.get('Referer', '')
        is_popup = 'popup=1' in referer or request.query_params.get('popup') == '1'
        if is_popup:
            request.session['oauth2_popup'] = True
            request.session['oauth2_popup_mode'] = True

        return RedirectResponse(url=auth_url, status_code=303)
    except Exception as e:
        logger.error(f"Google OAuth2 initiation failed: {e}")
        return _templates.TemplateResponse(request=request, name="dashboard/login.html",
            context={"request": request, "error": "Google authentication service is temporarily unavailable"})


@router.get("/auth/oauth2/google/callback")
async def oauth2_google_callback(request: Request, code: str = Query(...), state: str = Query(...)):
    """Handle Google OAuth2 callback"""
    if not (_config and _config.aisbf and _config.aisbf.oauth2 and
            _config.aisbf.oauth2.google and _config.aisbf.oauth2.google.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        from aisbf.auth.google import GoogleOAuth2

        client_id = _config.aisbf.oauth2.google.client_id
        client_secret = _config.aisbf.oauth2.google.client_secret
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/google/callback"

        session_state = request.session.get('oauth2_google', {}).get('state')
        if not hmac.compare_digest(state, session_state or ''):
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "config": _config, "error": "Invalid authentication state"})

        oauth = GoogleOAuth2(client_id, client_secret, redirect_uri)
        oauth._state = session_state
        oauth._code_verifier = request.session.get('oauth2_google', {}).get('code_verifier')

        tokens = await oauth.exchange_code_for_tokens(code, state)
        if not tokens:
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "config": _config, "error": "Failed to authenticate with Google"})

        user_info = await oauth.get_user_info(tokens.get('access_token'))
        if not user_info or not user_info.get('email'):
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "config": _config, "error": "Could not retrieve your profile from Google"})

        email = user_info.get('email')
        email_verified = user_info.get('email_verified', False)
        display_name = user_info.get('name', '')

        db = DatabaseRegistry.get_config_database()
        existing_user = db.get_user_by_email(email)

        if existing_user:
            request.session['logged_in'] = True
            request.session['username'] = existing_user['username']
            request.session['email'] = existing_user.get('email', '')
            request.session['role'] = existing_user['role']
            request.session['user_id'] = existing_user['id']
            request.session['has_profile_pic'] = bool(existing_user.get('profile_pic'))
            request.session['email_verified'] = True
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (existing_user['id'],))
                conn.commit()
        else:
            if not email_verified:
                return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                    context={"request": request, "config": _config, "error": "Google email must be verified to create an account"})

            random_password = secrets.token_urlsafe(32)
            password_hash = _db_hash_password(random_password)
            google_username = db.generate_username_from_display_name(display_name, email)
            final_username = db.find_unique_username(google_username)
            user_id = db.create_user(final_username, password_hash, 'user', None, email, True, display_name)

            request.session['logged_in'] = True
            request.session['username'] = final_username
            request.session['email'] = email
            request.session['role'] = 'user'
            request.session['user_id'] = user_id
            request.session['email_verified'] = True
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (user_id,))
                conn.commit()

        is_popup = request.session.pop('oauth2_popup', False) or request.session.pop('oauth2_popup_mode', False)
        request.session.pop('oauth2_google', None)
        if is_popup:
            return HTMLResponse(content=f'''
                <!DOCTYPE html><html><head><title>Authentication Complete</title></head><body>
                <script>
                    var msg = {{ type: 'oauth2_complete', redirect_url: '{url_for(request, "/dashboard")}' }};
                    try {{ var bc = new BroadcastChannel('oauth2_result'); bc.postMessage(msg); bc.close(); }} catch(e) {{}}
                    try {{ if (window.opener) window.opener.postMessage(msg, '*'); }} catch(e) {{}}
                    window.close();
                </script></body></html>
            ''')
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    except Exception as e:
        logger.error(f"Error during Google OAuth2 callback: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/login.html",
            context={"request": request, "config": _config, "error": "An error occurred during email verification"})


@router.get("/auth/oauth2/github")
async def oauth2_github_initiate(request: Request):
    """Initiate GitHub OAuth2 authentication flow"""
    if not (_config and _config.aisbf and _config.aisbf.oauth2 and
            _config.aisbf.oauth2.github and _config.aisbf.oauth2.github.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        from aisbf.auth.github import GitHubOAuth2

        client_id = _config.aisbf.oauth2.github.client_id
        client_secret = _config.aisbf.oauth2.github.client_secret
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/github/callback"

        oauth = GitHubOAuth2(client_id, client_secret, redirect_uri)
        auth_url = oauth.get_authorization_url(_config.aisbf.oauth2.github.scopes)

        request.session['oauth2_github'] = {'state': oauth._state}

        referer = request.headers.get('Referer', '')
        is_popup = 'popup=1' in referer or request.query_params.get('popup') == '1'
        if is_popup:
            request.session['oauth2_popup'] = True
            request.session['oauth2_popup_mode'] = True

        return RedirectResponse(url=auth_url, status_code=303)
    except Exception as e:
        logger.error(f"GitHub OAuth2 initiation failed: {e}")
        return _templates.TemplateResponse(request=request, name="dashboard/login.html",
            context={"request": request, "error": "GitHub authentication service is temporarily unavailable"})


@router.get("/auth/oauth2/github/callback")
async def oauth2_github_callback(request: Request, code: str = Query(...), state: str = Query(...)):
    """Handle GitHub OAuth2 callback"""
    if not (_config and _config.aisbf and _config.aisbf.oauth2 and
            _config.aisbf.oauth2.github and _config.aisbf.oauth2.github.enabled):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    try:
        from aisbf.auth.github import GitHubOAuth2

        client_id = _config.aisbf.oauth2.github.client_id
        client_secret = _config.aisbf.oauth2.github.client_secret
        base_url = get_base_url(request)
        redirect_uri = f"{base_url}/auth/oauth2/github/callback"

        session_state = request.session.get('oauth2_github', {}).get('state')
        if not hmac.compare_digest(state, session_state or ''):
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "config": _config, "error": "Invalid authentication state"})

        oauth = GitHubOAuth2(client_id, client_secret, redirect_uri)
        oauth._state = session_state

        tokens = await oauth.exchange_code_for_tokens(code, state)
        if not tokens:
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "config": _config, "error": "Failed to authenticate with GitHub"})

        user_info = await oauth.get_user_info(tokens.get('access_token'))
        if not user_info or not user_info.get('email'):
            return _templates.TemplateResponse(request=request, name="dashboard/login.html",
                context={"request": request, "config": _config, "error": "Could not retrieve your profile from GitHub. Please ensure your email is public."})

        email = user_info.get('email')
        display_name = user_info.get('name', '') or user_info.get('login', '')

        db = DatabaseRegistry.get_config_database()
        existing_user = db.get_user_by_email(email)

        if existing_user:
            request.session['logged_in'] = True
            request.session['username'] = existing_user['username']
            request.session['email'] = existing_user.get('email', '')
            request.session['role'] = existing_user['role']
            request.session['user_id'] = existing_user['id']
            request.session['has_profile_pic'] = bool(existing_user.get('profile_pic'))
            request.session['email_verified'] = True
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (existing_user['id'],))
                conn.commit()
        else:
            random_password = secrets.token_urlsafe(32)
            password_hash = _db_hash_password(random_password)
            github_username = db.generate_username_from_display_name(display_name, email)
            final_username = db.find_unique_username(github_username)
            user_id = db.create_user(final_username, password_hash, 'user', None, email, True, display_name)

            request.session['logged_in'] = True
            request.session['username'] = final_username
            request.session['email'] = email
            request.session['role'] = 'user'
            request.session['user_id'] = user_id
            request.session['email_verified'] = True
            request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60
            with db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if db.db_type == 'sqlite' else '%s'
                cursor.execute(f'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = {placeholder}', (user_id,))
                conn.commit()

        is_popup = request.session.pop('oauth2_popup', False) or request.session.pop('oauth2_popup_mode', False)
        request.session.pop('oauth2_github', None)
        if is_popup:
            return HTMLResponse(content=f'''
                <!DOCTYPE html><html><head><title>Authentication Complete</title></head><body>
                <script>
                    var msg = {{ type: 'oauth2_complete', redirect_url: '{url_for(request, "/dashboard")}' }};
                    try {{ var bc = new BroadcastChannel('oauth2_result'); bc.postMessage(msg); bc.close(); }} catch(e) {{}}
                    try {{ if (window.opener) window.opener.postMessage(msg, '*'); }} catch(e) {{}}
                    window.close();
                </script></body></html>
            ''')
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)

    except Exception as e:
        logger.error(f"GitHub OAuth2 callback failed: {e}", exc_info=True)
        return _templates.TemplateResponse(request=request, name="dashboard/login.html",
            context={"request": request, "config": _config, "error": "Authentication failed. Please try again."})


def require_dashboard_auth(request: Request):
    """Check if user is logged in to dashboard"""
    if not request.session.get('logged_in'):
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    expires_at = request.session.get('expires_at')
    if expires_at and int(time.time()) > expires_at:
        request.session.clear()
        return RedirectResponse(url=url_for(request, "/dashboard/login"), status_code=303)

    if request.session.get('remember_me'):
        request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
    elif expires_at:
        request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

    if request.session.get('must_change_password'):
        path = request.url.path
        if not any(path.startswith(p) for p in _MUST_CHANGE_PASSWORD_WHITELIST):
            return RedirectResponse(
                url=url_for(request, "/dashboard/settings") + "?warning=default_password",
                status_code=303
            )

    return None


def require_api_auth(request: Request):
    """Check if user is logged in to dashboard (API version - returns JSON)"""
    if not request.session.get('logged_in'):
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    expires_at = request.session.get('expires_at')
    if expires_at and int(time.time()) > expires_at:
        request.session.clear()
        return JSONResponse(status_code=401, content={"error": "Session expired"})

    if request.session.get('remember_me'):
        request.session['expires_at'] = int(time.time()) + 30 * 24 * 60 * 60
    elif expires_at:
        request.session['expires_at'] = int(time.time()) + 14 * 24 * 60 * 60

    if request.session.get('must_change_password'):
        path = request.url.path
        if not any(path.startswith(p) for p in _MUST_CHANGE_PASSWORD_WHITELIST):
            return JSONResponse(
                status_code=403,
                content={"error": "Default password must be changed before using the API",
                         "redirect": "/dashboard/settings?warning=default_password"}
            )

    return None


def require_api_admin(request: Request):
    """Check if user is admin (API version - returns JSON)"""
    auth_check = require_api_auth(request)
    if auth_check:
        return auth_check
    if request.session.get('role') != 'admin':
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    return None


def require_admin(request: Request):
    """Check if user is admin (dashboard version - returns redirects)"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    if request.session.get('role') != 'admin':
        return RedirectResponse(url=url_for(request, "/dashboard"), status_code=303)
    return None
