"""
Jinja2 template setup, proxy-aware URL helpers, and ProxyHeadersMiddleware.
Extracted from main.py.
"""
import hashlib
import logging
from pathlib import Path
from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """Handle X-Forwarded-* proxy headers."""

    async def dispatch(self, request: Request, call_next):
        forwarded_proto = request.headers.get("X-Forwarded-Proto")
        forwarded_host = request.headers.get("X-Forwarded-Host")
        forwarded_port = request.headers.get("X-Forwarded-Port")
        forwarded_prefix = request.headers.get("X-Forwarded-Prefix") or request.headers.get("X-Script-Name")
        forwarded_for = request.headers.get("X-Forwarded-For")

        if forwarded_proto or forwarded_host or forwarded_prefix:
            logger.debug(f"Proxy headers detected - Proto: {forwarded_proto}, Host: {forwarded_host}, Prefix: {forwarded_prefix}")

        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto

        if forwarded_host:
            if ":" in forwarded_host and not forwarded_port:
                host_parts = forwarded_host.split(":", 1)
                request.scope["server"] = (host_parts[0], int(host_parts[1]))
            else:
                port = int(forwarded_port) if forwarded_port else (443 if forwarded_proto == "https" else 80)
                request.scope["server"] = (forwarded_host, port)
        elif forwarded_port:
            current_host = request.scope.get("server", ("localhost", 80))[0]
            request.scope["server"] = (current_host, int(forwarded_port))

        if forwarded_prefix:
            forwarded_prefix = forwarded_prefix.rstrip("/")
            request.scope["root_path"] = forwarded_prefix
            original_path = request.scope.get("path", "")
            if original_path.startswith(forwarded_prefix):
                request.scope["path"] = original_path[len(forwarded_prefix):] or "/"

        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            request.scope["client"] = (client_ip, request.scope.get("client", ("", 0))[1])

        return await call_next(request)


def get_base_url(request: Request) -> str:
    scheme = request.scope.get("scheme", "http")
    server = request.scope.get("server", ("localhost", 80))
    host, port = server[0], server[1]
    root_path = request.scope.get("root_path", "")
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return f"{scheme}://{host}{root_path}"
    return f"{scheme}://{host}:{port}{root_path}"


def url_for(request: Request, path: str) -> str:
    root_path = request.scope.get("root_path", "")
    if not path.startswith("/"):
        path = "/" + path
    is_behind_proxy = "x-forwarded-host" in request.headers or "x-forwarded-proto" in request.headers
    if is_behind_proxy:
        return (root_path + path) if (root_path and root_path != "/") else path
    return f"{get_base_url(request)}{path}"


def create_templates(template_dir: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=template_dir)
    templates.env.loader.searchpath.insert(0, template_dir)
    return templates


def setup_template_globals(templates: Jinja2Templates, version: str):
    from aisbf import __version__

    def md5_filter(s):
        if not s:
            return hashlib.md5(b'').hexdigest().lower()
        return hashlib.md5(s.encode('utf-8')).hexdigest().lower()

    templates.env.filters['md5'] = md5_filter
    templates.env.globals['url_for'] = url_for
    templates.env.globals['get_base_url'] = get_base_url
    templates.env.globals['__version__'] = version
    templates.env.cache.clear()


def patch_template_response(templates: Jinja2Templates):
    """Inject is_aisbf_cloud / welcome_shown into every TemplateResponse automatically."""
    original = templates.TemplateResponse

    def patched(*args, **kwargs):
        if 'context' in kwargs and 'request' in kwargs['context']:
            req = kwargs['context']['request']
            if hasattr(req.state, 'is_aisbf_cloud'):
                kwargs['context']['is_aisbf_cloud'] = req.state.is_aisbf_cloud
            if hasattr(req.state, 'welcome_shown'):
                kwargs['context']['welcome_shown'] = req.state.welcome_shown
        return original(*args, **kwargs)

    templates.TemplateResponse = patched
