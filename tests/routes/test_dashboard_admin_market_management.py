import json
import sys
from base64 import b64encode
from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from jinja2 import Environment, FileSystemLoader, select_autoescape

from aisbf.routes.dashboard import admin as dashboard_admin
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


class MarketAdminDbStub:
    def __init__(self):
        self.current_market_settings = {
            "enabled": True,
            "allow_user_publish": True,
            "allow_admin_publish": True,
            "allow_import": True,
        }
        self.last_paginated_call = None
        self.items = [
            {
                "id": 7,
                "title": "Alice Provider",
                "owner_username": "alice",
                "source_type": "provider",
                "source_id": "alice-provider",
                "provider_id": "alice-provider",
                "model_id": None,
                "price_per_million_tokens": 1.5,
                "price_per_1000_requests": 0.2,
                "stats": {"gross_revenue": 42.0, "total_requests": 12},
                "is_active": True,
                "metadata": {},
            }
        ]
        self.total = 1

    def get_market_settings(self):
        return dict(self.current_market_settings)

    def get_currency_settings(self):
        return {"currency_symbol": "$"}

    def list_market_listings_paginated(self, **kwargs):
        self.last_paginated_call = kwargs
        return {
            "items": list(self.items),
            "total": self.total,
        }

    def get_provider_disabled_until(self, owner_user_id, provider_id):
        return None

    def get_provider_usage(self, owner_user_id, provider_id):
        return {"usage_data": {"ok": True}}

    def get_user_by_id(self, user_id):
        return {"display_name": "Alice"}

    def get_market_vote_summary(self, listing_id):
        return {
            "listing": {"upvotes": 0, "downvotes": 0, "score": 0},
            "provider": {"upvotes": 0, "downvotes": 0, "score": 0},
            "model": {"upvotes": 0, "downvotes": 0, "score": 0},
            "user": {"upvotes": 0, "downvotes": 0, "score": 0},
        }

    def get_market_listing_stats(self, listing_id):
        return {"gross_revenue": 42.0, "total_requests": 12}


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


def _login_as_admin(client: TestClient) -> None:
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": "admin",
            "role": "admin",
            "user_id": None,
            "expires_at": 4102444800,
        },
    )


def test_payment_settings_shows_market_admin_link_not_embedded_table(monkeypatch):
    db = MarketAdminDbStub()
    templates = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_admin, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_admin, "_templates", templates)

    response = client.get("/dashboard/admin/payment-settings")

    assert response.status_code == 200
    assert templates.calls[-1]["name"] == "dashboard/admin_payment_settings.html"
    assert "Open Market Administration" in response.text
    assert "Review, search, filter, and moderate exported market listings" in response.text
    assert "<table style=\"width:100%; border-collapse: collapse;\">" not in response.text


def test_admin_market_page_supports_search_filters_and_pagination(monkeypatch):
    db = MarketAdminDbStub()
    db.total = 25
    templates = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_market, "_templates", templates)

    response = client.get(
        "/dashboard/admin/market",
        params={
            "q": "alice",
            "source_type": "provider",
            "active_filter": "active",
            "online_filter": "online",
            "owner_username": "alice",
            "page": 2,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert db.last_paginated_call == {
        "page": 2,
        "limit": 10,
        "search": "alice",
        "source_type": "provider",
        "active_filter": "active",
        "online_filter": "online",
        "owner_username": "alice",
    }
    assert templates.calls[-1]["name"] == "dashboard/admin_market.html"
    assert templates.calls[-1]["context"]["filters"] == {
        "q": "alice",
        "source_type": "provider",
        "active_filter": "active",
        "online_filter": "online",
        "owner_username": "alice",
        "page": 2,
        "limit": 10,
    }
    assert 'value="alice"' in response.text
    assert 'value="provider" selected' in response.text
    assert 'value="active" selected' in response.text
    assert 'value="online" selected' in response.text
    assert 'page=2' in response.text


def test_admin_market_page_clamps_page_to_last_result_page(monkeypatch):
    db = MarketAdminDbStub()
    db.items = []
    db.total = 1
    templates = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_market, "_templates", templates)

    response = client.get(
        "/dashboard/admin/market",
        params={
            "q": "missing",
            "page": 9,
            "limit": 1,
        },
    )

    assert response.status_code == 200
    assert templates.calls[-1]["context"]["pagination"]["page"] == 1
    assert templates.calls[-1]["context"]["pagination"]["total_pages"] == 1
    assert "No market listings match the current filters." in response.text
