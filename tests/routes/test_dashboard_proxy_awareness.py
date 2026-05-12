import json
import sys
from base64 import b64encode
from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from jinja2 import Environment, FileSystemLoader, select_autoescape

from aisbf.routes.dashboard import market as dashboard_market

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from main import app


class TemplateCapture:
    def __init__(self):
        self.calls = []
        self._env = Environment(
            loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "templates")),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._env.globals["url_for"] = lambda request, path, **kwargs: path

    def TemplateResponse(self, *args, **kwargs):
        request = kwargs["request"]
        name = kwargs["name"]
        context = kwargs["context"]
        self.calls.append({"request": request, "name": name, "context": context})
        template = self._env.get_template(name)
        return HTMLResponse(template.render(**context))


class DashboardProxyDbStub:
    def __init__(self):
        self.market_settings = {
            "enabled": True,
            "allow_user_publish": True,
            "allow_admin_publish": True,
            "allow_import": True,
        }
        self.reference_rows = []
        self.user_providers = [
            {
                "provider_id": "local-provider",
                "config": {"name": "Local Provider", "type": "openai", "models": []},
                "created_at": None,
                "updated_at": None,
            }
        ]
        self.user_rotations = [
            {
                "rotation_id": "local-rotation",
                "config": {"model_name": "Local Rotation", "providers": []},
            }
        ]
        self.user_autoselects = [
            {
                "autoselect_id": "local-autoselect",
                "config": {
                    "model_name": "Local Autoselect",
                    "description": "Local chooser",
                    "selection_model": "internal",
                    "fallback": "",
                    "available_models": [],
                },
            }
        ]
        self.market_listings = [
            {
                "id": 55,
                "owner_user_id": 7,
                "owner_username": "seller",
                "source_scope": "user",
                "source_type": "provider",
                "source_id": "seller-provider",
                "listing_key": "provider:seller-provider",
                "title": "Seller Provider",
                "description": "Shared provider",
                "provider_id": "seller-provider",
                "model_id": None,
                "endpoint": "https://seller.example/v1",
                "price_per_million_tokens": 1.0,
                "price_per_1000_requests": 0.2,
                "provider_price_per_million_tokens": 1.0,
                "provider_price_per_1000_requests": 0.2,
                "currency_code": "USD",
                "metadata": {"provider_type": "openai", "capabilities": ["chat"]},
                "stats": {"usage_events": 1, "total_requests": 2, "total_tokens": 3, "avg_tokens_per_request": 1.5, "gross_revenue": 4.0, "provider_revenue": 2.0},
                "analytics": {"request_count": 2, "avg_latency_ms": 123.0, "error_rate": 0.0, "total_tokens": 3},
                "is_active": True,
            }
        ]

    def get_market_settings(self):
        return dict(self.market_settings)

    def list_market_import_references(self, user_id):
        return [dict(row) for row in self.reference_rows if row["user_id"] == user_id]

    def get_sort_order(self, user_id, resource_type):
        return None

    def get_user_providers(self, user_id):
        return [dict(row) for row in self.user_providers]

    def get_user_rotations(self, user_id):
        return [dict(row) for row in self.user_rotations]

    def get_user_autoselects(self, user_id):
        return [dict(row) for row in self.user_autoselects]

    def list_market_listings(self, active_only=False):
        return [dict(row) for row in self.market_listings]

    def get_provider_disabled_until(self, owner_user_id, provider_id):
        return None

    def get_provider_usage(self, owner_user_id, provider_id):
        return {"usage_data": {"ok": True}}

    def get_user_by_id(self, user_id):
        if user_id == 7:
            return {"id": 7, "username": "seller", "display_name": "Seller"}
        if user_id == 11:
            return {"id": 11, "username": "buyer", "display_name": "Buyer"}
        return None

    def get_currency_settings(self):
        return {"currency_symbol": "$"}

    def get_market_vote_summary(self, listing_id):
        return {
            "listing": {"upvotes": 0, "downvotes": 0, "score": 0},
            "provider": {"upvotes": 0, "downvotes": 0, "score": 0},
            "model": {"upvotes": 0, "downvotes": 0, "score": 0},
            "user": {"upvotes": 0, "downvotes": 0, "score": 0},
        }

    def get_market_listing_stats(self, listing_id):
        return {"gross_revenue": 4.0, "total_requests": 2}


class RegistryStub:
    def __init__(self, db):
        self._db = db

    def get_config_database(self):
        return self._db


def _find_session_secret() -> str:
    for middleware in app.user_middleware:
        kwargs = getattr(middleware, "kwargs", {})
        secret_key = kwargs.get("secret_key")
        if secret_key:
            return secret_key
    raise AssertionError("Session middleware secret key not found")


def _set_session_cookie(client: TestClient, data: dict) -> None:
    signer = TimestampSigner(_find_session_secret())
    serialized = b64encode(json.dumps(data).encode("utf-8"))
    signed = signer.sign(serialized).decode("utf-8")
    client.cookies.set("session", signed)


def _login_as_user(client: TestClient, user_id: int = 11) -> None:
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": "buyer",
            "role": "user",
            "user_id": user_id,
            "expires_at": 4102444800,
        },
    )


def _forwarded_prefix_headers():
    return {
        "X-Forwarded-Prefix": "/proxy/app",
        "X-Forwarded-Host": "example.test",
        "X-Forwarded-Proto": "https",
    }


def test_user_providers_page_uses_proxy_aware_bootstrap_paths(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/providers", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert 'const BASE_PATH = "/proxy/app"' in response.text
    assert 'window.location.href = `${BASE_PATH}/dashboard/providers?success=1`;' in response.text
    assert "window.location.href = '/dashboard/providers?success=1'" not in response.text


def test_user_rotations_page_uses_proxy_aware_search_urls(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/rotations", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert 'const BASE_PATH = "/proxy/app"' in response.text
    assert "fetch(`${BASE_PATH}/dashboard/providers/" in response.text
    assert "fetch('/dashboard/providers/" not in response.text


def test_market_page_uses_proxy_aware_market_api_urls(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_market, "_templates", capture)

    response = client.get("/dashboard/market", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert 'const BASE_PATH = "/proxy/app"' in response.text
    assert "fetch(`${BASE_PATH}/api/market/listings`" in response.text
    assert "fetch('/api/market/listings'" not in response.text
