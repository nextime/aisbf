import json
import sys
from base64 import b64encode
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from jinja2 import Environment, FileSystemLoader, select_autoescape

from aisbf.routes.dashboard import market as dashboard_market
from aisbf.routes.dashboard import admin as dashboard_admin
from aisbf.routes.dashboard import providers as dashboard_providers
from aisbf.routes.dashboard import settings as dashboard_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from main import app
from aisbf.database import DatabaseManager


class TemplateCapture:
    def __init__(self):
        self.calls = []
        self._env = Environment(
            loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "templates")),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._env.globals["url_for"] = lambda request, path, **kwargs: f"{request.scope.get('root_path', '')}{path}"

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
        self.recorded_events = []

        self.dashboard_event_summary = {
            "total_events": 4,
            "unique_ips": 2,
            "unique_visitors": 2,
            "unique_sessions": 3,
            "by_type": [
                {"event_type": "provider_removed", "count": 1},
                {"event_type": "rotation_saved_updated", "count": 1},
                {"event_type": "autoselect_saved_created", "count": 1},
                {"event_type": "request_proxied", "count": 1},
            ],
            "pages": [{"path": "/dashboard/providers", "count": 2}],
            "countries": [{"country_code": "IT", "count": 2}],
            "users": [{"username": "admin", "user_id": None, "count": 4}],
        }
        self.dashboard_event_series = [
            {"bucket": "2026-05-12 10:00:00", "events": 4, "unique_ips": 2, "unique_visitors": 2}
        ]
        self.dashboard_event_rows = [
            {"event_type": "provider_removed", "path": "/dashboard/api/provider/demo", "metadata": {"source": "api"}},
            {"event_type": "rotation_saved_updated", "path": "/dashboard/rotations", "metadata": {"source": "bulk"}},
            {"event_type": "autoselect_saved_created", "path": "/dashboard/autoselect", "metadata": {"source": "bulk"}},
        ]
        self.summary_calls = []
        self.series_calls = []
        self.events_calls = []
        self.prompt_summary_calls = []
        self.prompt_series_calls = []

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

    def get_all_user_cache_settings(self, user_id):
        return []

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

    def record_dashboard_event(self, **kwargs):
        self.recorded_events.append(kwargs)
        return len(self.recorded_events)

    def get_dashboard_event_summary(self, *args, **kwargs):
        self.summary_calls.append(kwargs)
        return dict(self.dashboard_event_summary)

    def get_dashboard_event_series(self, *args, **kwargs):
        self.series_calls.append(kwargs)
        return [dict(row) for row in self.dashboard_event_series]

    def get_dashboard_events(self, *args, **kwargs):
        self.events_calls.append(kwargs)
        return [dict(row) for row in self.dashboard_event_rows]

    def get_users(self):
        return [
            {"id": 1, "username": "alice", "display_name": "Alice", "role": "user"},
            {"id": 2, "username": "bob", "display_name": "Bob", "role": "user"},
        ]

    def get_prompt_analysis_summary(self, *args, **kwargs):
        self.prompt_summary_calls.append(kwargs)
        return {
            "total_runs": 3,
            "blocked_runs": 1,
            "high_risk_runs": 1,
            "avg_prompt_tokens": 120.0,
            "avg_effective_context": 180.0,
            "findings": [{"category": "role_hijack_ignore", "severity": "high", "count": 1}],
        }

    def get_prompt_analysis_series(self, *args, **kwargs):
        self.prompt_series_calls.append(kwargs)
        return [{"bucket": "2026-05-12 10:00:00", "runs": 3, "high_risk": 1, "blocked": 1}]

    def get_prompt_analysis_details(self, *args, **kwargs):
        return {
            "provider_breakdown": [
                {"provider_id": "provider-a", "runs": 2, "blocked": 1, "high_risk": 1, "avg_prompt_tokens": 120.0, "avg_effective_context": 180.0}
            ],
            "model_breakdown": [
                {"model_name": "model-a", "runs": 2, "blocked": 1, "high_risk": 1}
            ],
            "risk_breakdown": [
                {"risk_level": "high", "count": 1},
                {"risk_level": "none", "count": 2},
            ],
            "segment_breakdown": [
                {"role": "user", "count": 2},
                {"role": "system", "count": 1},
            ],
            "shape_breakdown": [
                {"prompt_shape": "assistant+system+user", "count": 2}
            ],
            "recent_runs": [
                {
                    "id": 1,
                    "created_at": "2026-05-12 10:00:00",
                    "user_id": 1,
                    "provider_id": "provider-a",
                    "model_name": "model-a",
                    "rotation_id": "rotation-a",
                    "autoselect_id": "auto-a",
                    "blocked": True,
                    "risk_level": "high",
                    "risk_score": 90,
                    "prompt_tokens": 120,
                    "effective_context": 180,
                    "findings_count": 1,
                    "prompt_shape": "assistant+system+user",
                    "largest_segment_role": "user",
                    "has_tools": True,
                    "has_system_prompt": True,
                    "high_count": 1,
                    "medium_count": 0,
                    "info_count": 0,
                    "findings": [{"category": "role_hijack_ignore", "severity": "high", "count": 1}],
                }
            ],
            "posture": {
                "runs_with_tools": 1,
                "runs_with_system_prompt": 2,
                "avg_findings_count": 0.3,
                "avg_risk_score": 30.0,
            },
        }


class RegistryStub:
    def __init__(self, db):
        self._db = db

    def get_config_database(self):
        return self._db


class DashboardUsersDbStub:
    def __init__(self):
        self.paginated_calls = []

    def get_users_paginated(self, **kwargs):
        self.paginated_calls.append(kwargs)
        return {
            "users": [{"id": 1, "username": "alice", "display_name": "alice", "email": "alice@example.test", "role": "user", "tier_id": 10, "created_by": "admin", "created_at": "2026-01-01", "last_login": None, "is_active": True}],
            "total": 1,
        }

    def get_all_tiers(self):
        return [{"id": 10, "name": "Pro", "is_visible": True}]


class DashboardSettingsRegistryStub(RegistryStub):
    pass


class AnalyticsStub:
    def get_all_providers_stats(self, *args, **kwargs):
        return []

    def get_token_usage_over_time(self, *args, **kwargs):
        return []

    def get_model_performance(self, *args, **kwargs):
        return []

    def get_cost_overview(self, *args, **kwargs):
        return {"total_estimated_cost_today": 0, "date_range": None, "providers": []}

    def get_savings_overview(self, *args, **kwargs):
        return None

    def get_token_usage_by_date_range(self, *args, **kwargs):
        return None

    def get_rotation_breakdown(self, *args, **kwargs):
        return []

    def get_autoselect_breakdown(self, *args, **kwargs):
        return []


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
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/providers", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert 'const BASE_PATH = "/proxy/app"' in response.text
    assert 'window.location.href = `${BASE_PATH}/dashboard/providers?success=1`;' in response.text
    assert "window.location.href = '/dashboard/providers?success=1'" not in response.text


def test_admin_providers_template_uses_single_proxy_aware_base_path(monkeypatch):
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/providers", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert capture.calls[-1]["name"] == "dashboard/providers.html"
    assert response.text.count('const BASE_PATH = "/proxy/app";') == 1
    assert 'window.location.href = `${BASE_PATH}/dashboard/providers?success=1`;' in response.text
    assert "`${BASE_PATH}/dashboard/api/provider`" in response.text
    assert "apiCall('DELETE', `${BASE_PATH}/dashboard/api/provider/${encodeURIComponent(key)}`)" in response.text
    assert "apiCall('POST', '/dashboard/api/provider'" not in response.text
    assert "apiCall('DELETE', '/dashboard/api/provider/" not in response.text


def test_user_rotations_page_uses_proxy_aware_search_urls(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/rotations", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert 'const BASE_PATH = "/proxy/app"' in response.text
    assert "fetch(`${BASE_PATH}/dashboard/providers/" in response.text
    assert "`${BASE_PATH}/dashboard/api/rotation`" in response.text
    assert "`${BASE_PATH}/dashboard/api/rotation/${encodeURIComponent(key)}`" in response.text
    assert "fetch('/dashboard/providers/" not in response.text
    assert "apiCall('POST', '/dashboard/api/rotation'" not in response.text
    assert "apiCall('DELETE', '/dashboard/api/rotation/" not in response.text


def test_admin_autoselect_template_uses_proxy_aware_cancel_link():
    capture = TemplateCapture()
    request = type("Req", (), {"scope": {"root_path": "/proxy/app"}, "session": {}})()
    response = capture.TemplateResponse(
        request=request,
        name="dashboard/autoselect.html",
        context={
            "request": request,
            "session": {},
            "autoselect_json": "{}",
            "available_rotations": "[]",
            "available_models": "[]",
            "providers_meta": "{}",
            "success": None,
            "error": None,
        },
    )

    response_text = response.body.decode()

    assert '<a href="/dashboard" class="btn btn-secondary">Cancel</a>' not in response_text
    assert '<a href="/proxy/app/dashboard" class="btn btn-secondary">Cancel</a>' in response_text
    assert "`${BASE_PATH}/dashboard/api/autoselect`" in response_text
    assert "`${BASE_PATH}/dashboard/api/autoselect/${encodeURIComponent(key)}`" in response_text
    assert "apiCall('POST', '/dashboard/api/autoselect'" not in response_text
    assert "apiCall('DELETE', '/dashboard/api/autoselect/" not in response_text


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


def test_dashboard_users_page_uses_proxy_aware_bulk_and_notification_urls(monkeypatch):
    db = DashboardUsersDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_settings, "DatabaseRegistry", DashboardSettingsRegistryStub(db))
    monkeypatch.setattr(dashboard_settings, "_templates", capture)

    response = client.get("/dashboard/users", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert capture.calls[-1]["name"] == "dashboard/users.html"
    assert 'const BASE_PATH = "/proxy/app"' in response.text
    assert "fetch(`${BASE_PATH}/dashboard/users/bulk`" in response.text
    assert "fetch(`${BASE_PATH}/dashboard/api/admin/notifications/send`" in response.text
    assert "fetch('/dashboard/users/bulk'" not in response.text
    assert "fetch('/dashboard/api/admin/notifications/send'" not in response.text


def test_analytics_page_uses_proxy_aware_search_delete_and_back_urls(monkeypatch):
    capture = TemplateCapture()
    request = type("Req", (), {"scope": {"root_path": "/proxy/app"}, "session": {}})()
    response = capture.TemplateResponse(
        request=request,
        name="dashboard/analytics.html",
        context={
            "request": request,
            "selected_time_range": "24h",
            "from_date": None,
            "to_date": None,
            "date_range_usage": None,
            "currency_symbol": "$",
            "available_providers": [],
            "available_models": [],
            "available_rotations": [],
            "available_autoselects": [],
            "available_users": [
                {"id": idx, "username": f"user{idx}", "role": "user"}
                for idx in range(1, 26)
            ],
            "selected_provider": None,
            "selected_model": None,
            "selected_rotation": None,
            "selected_autoselect": None,
            "selected_user": None,
            "global_only": "",
            "is_admin": True,
            "is_config_admin": True,
            "provider_stats": [],
            "cost_overview": {"total_estimated_cost_today": 0, "date_range": None, "providers": []},
            "optimization_savings": None,
            "model_performance": [],
            "token_over_time": "[]",
            "rotation_breakdown": [],
            "autoselect_breakdown": [],
            "dashboard_visit_overview": None,
            "dashboard_visit_series": "[]",
            "dashboard_visit_pages": [],
            "dashboard_visit_countries": [],
            "dashboard_visit_users": [],
            "dashboard_visit_events": [],
            "prompt_analysis_overview": None,
            "prompt_analysis_series": "[]",
        },
    )

    response_text = response.body.decode()

    assert 'const BASE_PATH = "/proxy/app"' in response_text
    assert "fetch(`${BASE_PATH}/api/users/search?q=${encodeURIComponent(query)}`)" in response_text
    assert "fetch(`${BASE_PATH}/api/admin/analytics/delete-${scope}`, {method: 'POST'})" in response_text
    assert '<a href="/proxy/app/dashboard" class="btn btn-secondary" data-i18n="analytics_page.back">Back to Dashboard</a>' in response_text
    assert '<a href="/proxy/app/dashboard/prompt-analytics" class="btn btn-secondary" style="text-decoration: none;">' in response_text
    assert '<a href="/proxy/app/dashboard/traffic-visits" class="btn btn-secondary" style="text-decoration: none;">' in response_text
    assert "fetch(`/api/users/search?q=${encodeURIComponent(query)}`)" not in response_text
    assert "fetch('/api/admin/analytics/delete-' + scope" not in response_text
    assert '<a href="/dashboard" class="btn btn-secondary" data-i18n="analytics_page.back">Back to Dashboard</a>' not in response_text


def test_bulk_global_saves_record_expected_dashboard_events(monkeypatch):
    events = []
    request = type(
        "Req",
        (),
        {"url": type("URL", (), {"path": "/dashboard/test"})(), "session": {"user_id": None, "username": "admin"}, "method": "POST"},
    )()

    dashboard_providers._record_dashboard_event = lambda request, event_type, **kwargs: events.append({"event_type": event_type, **kwargs})

    existing_providers = {"legacy": {"type": "openai"}, "shared": {"type": "openai", "name": "Before"}}
    new_providers = {"shared": {"type": "openai", "name": "After"}, "fresh": {"type": "openai", "name": "Fresh"}}
    for provider_key in set(existing_providers.keys()) - set(new_providers.keys()):
        dashboard_providers._record_dashboard_event(request, "provider_removed", provider_id=provider_key, metadata={"scope": "global", "source": "bulk"})
    for provider_key, provider_config in new_providers.items():
        event_type = dashboard_providers._resource_change_event(existing_providers.get(provider_key), provider_config, "provider_saved", "provider_removed")
        dashboard_providers._record_dashboard_event(request, event_type, provider_id=provider_key, metadata={"scope": "global", "provider_type": provider_config.get("type"), "source": "bulk"})

    existing_rotations = {"old-rot": {"providers": []}, "keep-rot": {"providers": []}}
    new_rotations = {"keep-rot": {"providers": [{"provider_id": "shared", "models": [], "weight": 1}]}, "new-rot": {"providers": []}}
    for rotation_key in set(existing_rotations.keys()) - set(new_rotations.keys()):
        dashboard_providers._record_dashboard_event(request, "rotation_removed", rotation_id=rotation_key, metadata={"scope": "global", "source": "bulk"})
    for rotation_key, rotation_config in new_rotations.items():
        event_type = dashboard_providers._resource_change_event(existing_rotations.get(rotation_key), rotation_config, "rotation_saved", "rotation_removed")
        dashboard_providers._record_dashboard_event(request, event_type, rotation_id=rotation_key, metadata={"scope": "global", "source": "bulk"})

    existing_autoselects = {"old-auto": {"selection_model": "internal", "available_models": []}, "keep-auto": {"selection_model": "internal", "available_models": []}}
    new_autoselects = {
        "keep-auto": {"selection_model": "internal", "available_models": [{"model_id": "shared/model", "priority": 1, "description": "Updated"}]},
        "new-auto": {"selection_model": "internal", "available_models": [{"model_id": "fresh/model", "priority": 1, "description": "Created"}]},
    }
    for autoselect_key in set(existing_autoselects.keys()) - set(new_autoselects.keys()):
        dashboard_providers._record_dashboard_event(request, "autoselect_removed", autoselect_id=autoselect_key, metadata={"scope": "global", "source": "bulk"})
    for autoselect_key, autoselect_config in new_autoselects.items():
        event_type = dashboard_providers._resource_change_event(existing_autoselects.get(autoselect_key), autoselect_config, "autoselect_saved", "autoselect_removed")
        dashboard_providers._record_dashboard_event(request, event_type, autoselect_id=autoselect_key, metadata={"scope": "global", "source": "bulk"})

    event_types = [event["event_type"] for event in events]
    assert "provider_removed" in event_types
    assert "provider_saved_updated" in event_types
    assert "provider_saved_created" in event_types
    assert "rotation_removed" in event_types
    assert "rotation_saved_updated" in event_types
    assert "rotation_saved_created" in event_types
    assert "autoselect_removed" in event_types
    assert "autoselect_saved_updated" in event_types
    assert "autoselect_saved_created" in event_types


def test_admin_analytics_page_renders_corrected_dashboard_event_types(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/analytics")

    assert response.status_code == 200
    context = capture.calls[-1]["context"]
    assert context["dashboard_visit_overview"]["by_type"][0]["event_type"] == "provider_removed"
    assert any(row["event_type"] == "rotation_saved_updated" for row in context["dashboard_visit_overview"]["by_type"])
    assert any(row["event_type"] == "autoselect_saved_created" for row in context["dashboard_visit_overview"]["by_type"])
    assert context["dashboard_visit_events"][0]["event_type"] == "provider_removed"
    assert "Prompt Analytics" in response.text
    assert "Traffic &amp; Visits" in response.text
    assert "provider_removed" not in response.text


def test_user_analytics_page_hides_admin_only_visitor_activity_sections(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/analytics")

    assert response.status_code == 200
    context = capture.calls[-1]["context"]
    assert context["is_config_admin"] is False
    assert context["dashboard_visit_overview"] is None
    assert context["dashboard_visit_events"] == []
    assert "Prompt Analytics" in response.text
    assert "Traffic &amp; Visits" not in response.text
    assert "Dashboard Visitor & Activity Tracking" not in response.text
    assert "Visitor & Dashboard Activity Overview" not in response.text


def test_admin_analytics_page_forwards_activity_filters_to_dashboard_queries(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get(
        "/dashboard/analytics",
        params={
            "activity_event_filter": "provider_removed",
            "activity_path_filter": "/dashboard/api/provider/demo",
            "activity_country_filter": "IT",
            "provider_filter": "provider-a",
            "rotation_filter": "rotation-a",
            "autoselect_filter": "auto-a",
            "user_filter": "11",
        },
    )

    assert response.status_code == 200
    assert db.summary_calls
    assert db.series_calls
    assert db.events_calls
    summary_call = db.summary_calls[-1]
    events_call = db.events_calls[-1]
    assert summary_call["event_types"] == ["provider_removed"]
    assert summary_call["provider_filter"] == "provider-a"
    assert summary_call["rotation_filter"] == "rotation-a"
    assert summary_call["autoselect_filter"] == "auto-a"
    assert summary_call["path_filter"] == "/dashboard/api/provider/demo"
    assert summary_call["country_filter"] == "IT"
    assert summary_call["user_id"] == 11
    assert events_call["event_types"] == ["provider_removed"]
    context = capture.calls[-1]["context"]
    assert context["activity_event_filter"] == "provider_removed"
    assert context["activity_path_filter"] == "/dashboard/api/provider/demo"
    assert context["activity_country_filter"] == "IT"


def test_analytics_page_renders_prompt_analysis_sections_for_user_scope(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/prompt-analytics")

    assert response.status_code == 200
    assert capture.calls[-1]["name"] == "dashboard/prompt_analytics.html"
    context = capture.calls[-1]["context"]
    assert context["prompt_analysis_overview"]["total_runs"] == 3
    assert context["prompt_analysis_details"]["provider_breakdown"][0]["provider_id"] == "provider-a"
    assert db.prompt_summary_calls
    assert db.prompt_series_calls
    assert "Prompt Analytics" in response.text
    assert "Top Prompt Findings" in response.text
    assert "Recent Prompt Analysis Runs" in response.text
    assert "Providers Under Prompt Pressure" in response.text


def test_admin_analytics_page_renders_tabbed_prompt_and_traffic_sections(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/traffic-visits")

    assert response.status_code == 200
    assert "Traffic &amp; Visits" in response.text
    assert "Prompt Analytics" in response.text
    assert "Visitor &amp; Dashboard Activity Overview" in response.text


def test_user_cache_settings_page_labels_native_legacy_scope(monkeypatch):
    db = DashboardProxyDbStub()
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_admin, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_admin, "_templates", capture)

    response = client.get("/dashboard/cache-settings", headers=_forwarded_prefix_headers())

    assert response.status_code == 200
    assert capture.calls[-1]["name"] == "dashboard/cache_settings.html"
    assert "Native Prompt Cache Settings" in response.text
    assert "legacy user-specific native prompt-caching overrides" in response.text
    assert "The newer request-time response-cache policy now lives in the dashboard feature overrides" in response.text
    assert "Enable Native Prompt Caching" in response.text


def test_admin_analytics_page_with_real_db_events_and_global_only_filter(monkeypatch, tmp_path):
    db = DatabaseManager({
        "type": "sqlite",
        "sqlite_path": str(tmp_path / "analytics-route.db"),
    })
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_admin(client)

    user_id = db.create_user("alice", "hash", role="user", email="alice@example.test", display_name="Alice")
    now = datetime.now()

    with db._get_connection() as conn:
        cursor = conn.cursor()
        rows = [
            (
                "request_proxied",
                "/api/provider-a/chat/completions",
                user_id,
                "alice",
                "sess-user",
                "1.1.1.1",
                "IT",
                "POST",
                200,
                "provider-a",
                "rotation-a",
                "auto-a",
                None,
                None,
                "{}",
                db._format_dt_db(now - timedelta(minutes=30)),
            ),
            (
                "provider_removed",
                "/dashboard/api/provider/demo",
                None,
                "admin",
                "sess-admin",
                "2.2.2.2",
                "US",
                "DELETE",
                200,
                "provider-b",
                None,
                None,
                None,
                None,
                "{}",
                db._format_dt_db(now - timedelta(minutes=10)),
            ),
        ]
        for row in rows:
            cursor.execute(
                """
                INSERT INTO dashboard_events (
                    event_type, path, user_id, username, session_id, ip_address, country_code,
                    method, status_code, provider_id, rotation_id, autoselect_id, listing_id,
                    target_user_id, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()

    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)
    monkeypatch.setattr("aisbf.analytics.get_analytics", lambda db_instance=None: AnalyticsStub())

    response = client.get("/dashboard/traffic-visits", params={"global_only": "1", "activity_event_filter": "provider_removed"})

    assert response.status_code == 200
    context = capture.calls[-1]["context"]
    assert context["is_config_admin"] is True
    assert context["global_only"] == "1"
    assert context["dashboard_visit_overview"]["total_events"] == 1
    assert context["dashboard_visit_overview"]["users"][0]["username"] == "admin"
    assert context["dashboard_visit_events"][0]["event_type"] == "provider_removed"
    assert "provider_removed" in response.text
    assert "request_proxied" not in response.text
