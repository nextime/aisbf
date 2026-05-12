import asyncio
import json
import sys
from base64 import b64encode
from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from jinja2 import Environment, FileSystemLoader, select_autoescape

from aisbf.routes.dashboard import market as dashboard_market
from aisbf.routes.dashboard import admin as dashboard_admin
from aisbf.routes.dashboard import settings as dashboard_settings
from aisbf.routes.dashboard.admin import api_save_market_settings
from aisbf.database import DatabaseRegistry

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


class DashboardUsersDbStub:
    def __init__(self):
        self.paginated_calls = []

    def get_users_paginated(self, **kwargs):
        self.paginated_calls.append(kwargs)
        return {
            "users": [{"id": 1, "username": "alice"}],
            "total": 1,
        }

    def get_all_tiers(self):
        return [{"id": 10, "name": "Pro"}]


class MarketSettingsDbStub:
    def __init__(self):
        self.current = {
            "enabled": True,
            "allow_user_publish": True,
            "allow_admin_publish": False,
            "allow_import": True,
            "market_export_filter": "all",
        }
        self.saved_payloads = []
        self.market_listings = [
            {
                "id": 7,
                "title": "Flux Dev Pack",
                "owner_username": "alice",
                "source_type": "provider",
                "source_id": "runpod-test",
                "online": True,
                "price_per_million_tokens": 1.5,
                "price_per_1000_requests": 0.2,
                "stats": {"gross_revenue": 42.0, "total_requests": 12},
                "is_active": True,
            }
        ]

    def get_market_settings(self):
        return dict(self.current)

    def save_market_settings(self, settings):
        self.saved_payloads.append(settings)
        self.current = dict(settings)
        return True

    def list_market_listings(self, active_only=False):
        return list(self.market_listings)

    def get_currency_settings(self):
        return {"currency_symbol": "$"}


class RegistryStub:
    def __init__(self, db):
        self._db = db

    def get_config_database(self):
        return self._db


class AsyncJsonRequest:
    def __init__(self, session, body):
        self.session = session
        self._body = body

    async def json(self):
        return self._body


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


def test_dashboard_users_passes_market_filters_and_preserves_markup_state(monkeypatch):
    db = DashboardUsersDbStub()
    templates = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_settings, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_settings, "_templates", templates)

    response = client.get(
        "/dashboard/users",
        params={
            "page": 2,
            "limit": 15,
            "search": "ali",
            "order_by": "username",
            "direction": "asc",
            "status_filter": "active",
            "role_filter": "user",
            "tier_filter": "10",
            "market_export_filter": "exporting",
        },
    )

    assert response.status_code == 200
    assert db.paginated_calls == [
        {
            "page": 2,
            "limit": 15,
            "search": "ali",
            "order_by": "username",
            "direction": "asc",
            "status_filter": "active",
            "role_filter": "user",
            "tier_filter": "10",
            "market_export_filter": "exporting",
        }
    ]
    assert templates.calls[-1]["name"] == "dashboard/users.html"
    assert templates.calls[-1]["context"]["filters"]["tier_filter"] == "10"
    assert templates.calls[-1]["context"]["filters"]["market_export_filter"] == "exporting"
    assert 'id="tier-filter"' in response.text
    assert 'id="tier-filter"' in response.text
    assert '<option value="10" selected' in response.text
    assert 'Pro' in response.text
    assert 'id="market-export-filter"' in response.text
    assert '<option value="exporting" selected' in response.text
    assert '<option value="not_exporting"' in response.text


def test_api_save_market_settings_merges_market_enabled_without_dropping_existing_flags(monkeypatch):
    db = MarketSettingsDbStub()
    monkeypatch.setattr(dashboard_admin, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_admin, "require_api_admin", lambda request: None)

    request = AsyncJsonRequest(
        session={"logged_in": True, "role": "admin", "user_id": None},
        body={"market_enabled": False},
    )

    response = asyncio.run(api_save_market_settings(request))

    assert response.status_code == 200
    assert db.saved_payloads == [
        {
            "enabled": False,
            "allow_user_publish": True,
            "allow_admin_publish": True,
            "allow_import": True,
        }
    ]


def test_ensure_market_enabled_respects_market_settings_enabled_contract(monkeypatch):
    db = MarketSettingsDbStub()
    db.current = {
        "enabled": False,
        "allow_user_publish": True,
        "allow_admin_publish": False,
        "allow_import": True,
        "market_export_filter": "all",
        "market_enabled": True,
    }
    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    request = type("RequestStub", (), {"session": {"role": "user"}})()

    response, settings = dashboard_market._ensure_market_enabled(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    assert json.loads(response.body) == {"error": "Market is disabled"}
    assert settings["enabled"] is False


def test_admin_payment_settings_embeds_market_admin_controls_and_listings(monkeypatch):
    db = MarketSettingsDbStub()
    templates = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_admin, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_admin, "_templates", templates)

    response = client.get("/dashboard/admin/payment-settings")

    assert response.status_code == 200
    assert templates.calls[-1]["name"] == "dashboard/admin_payment_settings.html"
    assert templates.calls[-1]["context"]["market_settings"]["enabled"] is True
    assert templates.calls[-1]["context"]["market_listings"][0]["title"] == "Flux Dev Pack"
    assert "Enable market" in response.text
    assert "Market Administration" in response.text
    assert "Flux Dev Pack" in response.text


def test_base_nav_hides_market_admin_link(monkeypatch):
    templates = TemplateCapture()
    request = type(
        "RequestStub",
        (),
        {
            "path": "/dashboard/settings",
            "scope": {"root_path": ""},
            "session": {
                "logged_in": True,
                "role": "admin",
                "user_id": None,
                "username": "admin",
            },
            "state": type(
                "StateStub",
                (),
                {
                    "welcome_modal_message": None,
                    "welcome_modal_source": None,
                    "show_footer_links": True,
                },
            )(),
        },
    )()

    html = templates._env.get_template("base.html").render(
        request=request,
        title="Settings",
        content="",
        show_upgrade_button=False,
        __version__="test",
    )

    assert "Market Admin" not in html


def test_base_nav_hides_market_link_when_market_disabled(monkeypatch):
    templates = TemplateCapture()
    request = type(
        "RequestStub",
        (),
        {
            "path": "/dashboard/settings",
            "scope": {"root_path": ""},
            "session": {
                "logged_in": True,
                "role": "admin",
                "user_id": None,
                "username": "admin",
            },
            "state": type(
                "StateStub",
                (),
                {
                    "welcome_modal_message": None,
                    "welcome_modal_source": None,
                    "show_footer_links": True,
                    "market_enabled": False,
                },
            )(),
        },
    )()

    html = templates._env.get_template("base.html").render(
        request=request,
        title="Settings",
        content="",
        show_upgrade_button=False,
        __version__="test",
    )

    assert ">Market</a>" not in html


def test_dashboard_context_middleware_hides_market_link_when_market_disabled(monkeypatch):
    original_instances = DatabaseRegistry._instances
    db = MarketSettingsDbStub()
    db.current["enabled"] = False
    DatabaseRegistry._instances = {"config": db}

    templates = TemplateCapture()
    monkeypatch.setattr(dashboard_settings, "_templates", templates)

    client = TestClient(app)
    _login_as_admin(client)

    try:
        response = client.get("/dashboard/settings")
    finally:
        DatabaseRegistry._instances = original_instances

    assert response.status_code == 200
    assert templates.calls[-1]["request"].state.market_enabled is False
    assert ">Market</a>" not in response.text
