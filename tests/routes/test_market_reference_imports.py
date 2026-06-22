import json
import re
import sys
from base64 import b64encode
from pathlib import Path
import pytest

from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from jinja2 import Environment, FileSystemLoader, select_autoescape
from aisbf.models import ChatCompletionRequest

from aisbf.routes.dashboard import market as dashboard_market
from aisbf.routes.dashboard import providers as dashboard_providers

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


class MarketReferenceImportDbStub:
    def __init__(self):
        self.market_settings = {
            "enabled": True,
            "allow_user_publish": True,
            "allow_admin_publish": True,
            "allow_import": True,
        }
        self.saved_user_providers = []
        self.saved_user_rotations = []
        self.saved_user_autoselects = []
        self.recorded_imports = []
        self.recorded_events = []
        self.created_references = []
        self.reference_rows = []
        self.user_providers = []
        self.user_rotations = []
        self.user_autoselects = []
        self.listing = {
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
            "metadata": {"provider_type": "openai"},
            "config_snapshot": {
                "type": "openai",
                "endpoint": "https://seller.example/v1",
                "api_key": "seller-secret-key",
                "models": [{"name": "seller-model", "api_key": "nested-secret"}],
            },
            "is_active": True,
        }
        self.rotation_listing = {
            "id": 56,
            "owner_user_id": 7,
            "owner_username": "seller",
            "source_scope": "user",
            "source_type": "rotation",
            "source_id": "seller-rotation",
            "listing_key": "rotation:seller-rotation",
            "title": "Seller Rotation",
            "description": "Shared rotation",
            "provider_id": None,
            "model_id": None,
            "endpoint": None,
            "price_per_million_tokens": 2.0,
            "price_per_1000_requests": 0.3,
            "provider_price_per_million_tokens": None,
            "provider_price_per_1000_requests": None,
            "currency_code": "USD",
            "metadata": {"provider_type": "rotation"},
            "config_snapshot": {
                "providers": ["seller-provider-a", "seller-provider-b"],
                "weights": {"seller-provider-a": 2, "seller-provider-b": 1},
                "api_key": "rotation-secret-key",
            },
            "is_active": True,
        }
        self.model_listing = {
            "id": 58,
            "owner_user_id": 7,
            "owner_username": "seller",
            "source_scope": "user",
            "source_type": "model",
            "source_id": "seller-provider/seller-model",
            "listing_key": "model:seller-provider/seller-model",
            "title": "Seller Model",
            "description": "Shared model",
            "provider_id": "seller-provider",
            "model_id": "seller-model",
            "endpoint": "https://seller.example/v1",
            "price_per_million_tokens": 1.7,
            "price_per_1000_requests": 0.25,
            "provider_price_per_million_tokens": 1.0,
            "provider_price_per_1000_requests": 0.2,
            "currency_code": "USD",
            "metadata": {"provider_type": "openai"},
            "config_snapshot": {
                "provider": {
                    "type": "openai",
                    "endpoint": "https://seller.example/v1",
                    "api_key": "model-provider-secret",
                },
                "model": {
                    "name": "seller-model",
                    "api_key": "model-secret-key",
                    "temperature": 0.2,
                },
            },
            "is_active": True,
        }
        self.autoselect_listing = {
            "id": 57,
            "owner_user_id": 7,
            "owner_username": "seller",
            "source_scope": "user",
            "source_type": "autoselect",
            "source_id": "seller-autoselect",
            "listing_key": "autoselect:seller-autoselect",
            "title": "Seller Autoselect",
            "description": "Shared autoselect",
            "provider_id": None,
            "model_id": None,
            "endpoint": None,
            "price_per_million_tokens": 3.0,
            "price_per_1000_requests": 0.4,
            "provider_price_per_million_tokens": None,
            "provider_price_per_1000_requests": None,
            "currency_code": "USD",
            "metadata": {"provider_type": "autoselect"},
            "config_snapshot": {
                "available_models": ["alpha", "beta"],
                "fallback": "seller-provider-a/model-a",
                "provider_token": "autoselect-secret-token",
            },
            "is_active": True,
        }

    def get_market_settings(self):
        return dict(self.market_settings)

    def get_user_by_id(self, user_id):
        if user_id == 11:
            return {"id": 11, "username": "buyer"}
        if user_id == 7:
            return {"id": 7, "username": "seller"}
        return None

    def get_market_listing(self, listing_id):
        listings = {
            self.listing["id"]: self.listing,
            self.rotation_listing["id"]: self.rotation_listing,
            self.model_listing["id"]: self.model_listing,
            self.autoselect_listing["id"]: self.autoselect_listing,
        }
        if listing_id in listings:
            return dict(listings[listing_id])
        return None

    def create_market_import_reference(self, **kwargs):
        self.created_references.append(kwargs)
        reference_id = len(self.created_references)
        row = {
            "id": reference_id,
            "user_id": kwargs["user_id"],
            "listing_id": kwargs["listing_id"],
            "reference_type": kwargs["reference_type"],
            "display_name": kwargs["display_name"],
            "owner_username": kwargs["owner_username"],
            "source_type": kwargs["source_type"],
            "source_id": kwargs["source_id"],
            "is_active": True,
        }
        self.reference_rows.append(row)
        return reference_id

    def get_market_import_reference(self, reference_id):
        for row in self.reference_rows:
            if row["id"] == reference_id:
                return dict(row)
        return None

    def list_market_import_references(self, user_id):
        return [dict(row) for row in self.reference_rows if row["user_id"] == user_id]

    def get_sort_order(self, user_id, resource_type):
        return None

    def save_user_provider(self, user_id, provider_name, config):
        self.saved_user_providers.append((user_id, provider_name, config))

    def save_user_rotation(self, user_id, rotation_name, config):
        self.saved_user_rotations.append((user_id, rotation_name, config))

    def save_user_autoselect(self, user_id, autoselect_name, config):
        self.saved_user_autoselects.append((user_id, autoselect_name, config))

    def record_market_import(self, user_id, listing_id, imported_config_type, imported_config_id):
        self.recorded_imports.append(
            {
                "user_id": user_id,
                "listing_id": listing_id,
                "imported_config_type": imported_config_type,
                "imported_config_id": imported_config_id,
            }
        )
        return len(self.recorded_imports)

    def record_dashboard_event(self, **kwargs):
        self.recorded_events.append(kwargs)
        return len(self.recorded_events)

    def get_user_providers(self, user_id):
        return [dict(row) for row in self.user_providers]

    def get_user_rotations(self, user_id):
        return [dict(row) for row in self.user_rotations]

    def get_user_autoselects(self, user_id):
        return [dict(row) for row in self.user_autoselects]


class RegistryStub:
    def __init__(self, db):
        self._db = db

    def get_config_database(self):
        return self._db


class RuntimeUserHandlerStub:
    def __init__(self):
        self.calls = []
        self.user_providers = {}
        self.rotations = {}
        self.autoselects = {}
        self.user_autoselects = {}

    async def handle_chat_completion(self, request, provider_id, body_dict):
        self.calls.append(("provider", provider_id, body_dict))
        return {"ok": True, "provider_id": provider_id, "model": body_dict.get("model")}

    async def handle_rotation_request(self, rotation_id, body_dict, user_id, token_id):
        self.calls.append(("rotation", rotation_id, body_dict, user_id, token_id))
        return {"ok": True, "rotation_id": rotation_id}

    async def handle_autoselect_request(self, autoselect_id, body_dict, user_id, token_id):
        self.calls.append(("autoselect", autoselect_id, body_dict, user_id, token_id))
        return {"ok": True, "autoselect_id": autoselect_id}


class MarketReferenceRuntimeDbStub(MarketReferenceImportDbStub):
    def admin_set_market_listing_active(self, listing_id, is_active):
        listing = self.get_market_listing(listing_id)
        if not listing:
            return False
        if listing_id == self.listing["id"]:
            self.listing["is_active"] = bool(is_active)
        elif listing_id == self.rotation_listing["id"]:
            self.rotation_listing["is_active"] = bool(is_active)
        elif listing_id == self.model_listing["id"]:
            self.model_listing["is_active"] = bool(is_active)
        elif listing_id == self.autoselect_listing["id"]:
            self.autoselect_listing["is_active"] = bool(is_active)
        return True


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


def _login_user_api_request(client: TestClient, username: str = "buyer", user_id: int = 11) -> None:
    _set_session_cookie(
        client,
        {
            "logged_in": True,
            "username": username,
            "role": "user",
            "user_id": user_id,
            "expires_at": 4102444800,
        },
    )


def _load_json_parse_bootstrap(response_text: str, marker: str):
    prefix = f"{marker} = JSON.parse("
    js_string_literal = response_text.split(prefix, 1)[1].split(");", 1)[0]
    return json.loads(json.loads(js_string_literal))


def test_json_parse_bootstrap_escapes_inline_script_sequences():
    from aisbf.routes.dashboard.providers import _json_parse_bootstrap

    payload = [{"config": {"name": 'Alice\'s "Provider" </script><script>alert(1)</script>'}}]
    bootstrap = _json_parse_bootstrap(payload)

    assert '</script><script>alert(1)</script>' not in bootstrap
    assert '\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e' in bootstrap
    assert json.loads(json.loads(bootstrap))[0]["config"]["name"] == 'Alice\'s "Provider" </script><script>alert(1)</script>'


@pytest.fixture
def runtime_fixture(monkeypatch):
    db = MarketReferenceRuntimeDbStub()
    reference_id = db.create_market_import_reference(
        user_id=11,
        listing_id=db.listing["id"],
        reference_type="provider",
        display_name=db.listing["title"],
        owner_username=db.listing["owner_username"],
        source_type=db.listing["source_type"],
        source_id=db.listing["source_id"],
    )
    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    return {
        "db": db,
        "handler": dashboard_market,
        "reference_id": reference_id,
        "buyer_user_id": 11,
        "listing_id": db.listing["id"],
        "seller_user_id": db.listing["owner_user_id"],
    }


@pytest.mark.asyncio
async def test_market_reference_resolves_to_source_listing_at_runtime(runtime_fixture):
    handler = runtime_fixture["handler"]

    resolved = await handler.resolve_market_reference(runtime_fixture["reference_id"], runtime_fixture["buyer_user_id"])

    assert resolved["listing_id"] == runtime_fixture["listing_id"]
    assert resolved["owner_user_id"] == runtime_fixture["seller_user_id"]
    assert resolved["source_id"] == "seller-provider"


@pytest.mark.asyncio
async def test_market_reference_rejects_disabled_listing(runtime_fixture):
    runtime_fixture["db"].admin_set_market_listing_active(runtime_fixture["listing_id"], False)
    handler = runtime_fixture["handler"]

    with pytest.raises(ValueError, match="unavailable"):
        await handler.resolve_market_reference(runtime_fixture["reference_id"], runtime_fixture["buyer_user_id"])


class DirectRequestStub:
    def __init__(self, user_id: int):
        self.state = type("State", (), {})()
        self.state.user_id = user_id
        self.state.is_admin = False
        self.state.is_global_token = False
        self.state.token_id = None


@pytest.mark.asyncio
async def test_user_provider_market_reference_executes_via_seller_handler(monkeypatch):
    db = MarketReferenceRuntimeDbStub()
    buyer_handler = RuntimeUserHandlerStub()
    seller_handler = RuntimeUserHandlerStub()

    reference_id = db.create_market_import_reference(
        user_id=11,
        listing_id=db.listing["id"],
        reference_type="provider",
        display_name=db.listing["title"],
        owner_username=db.listing["owner_username"],
        source_type=db.listing["source_type"],
        source_id=db.listing["source_id"],
    )

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes import user_api
    monkeypatch.setattr(user_api, "DatabaseRegistry", RegistryStub(db))

    def fake_get_user_handler(kind, user_id=None):
        if kind == "request" and user_id in (None, 11):
            buyer_handler.user_providers = {f"market-ref:{reference_id}": {"market_reference": True}}
            return buyer_handler
        if kind == "request" and user_id == 7:
            return seller_handler
        raise AssertionError((kind, user_id))

    monkeypatch.setattr(user_api, "_get_user_handler", fake_get_user_handler)

    result = await user_api.user_chat_completions(
        DirectRequestStub(11),
        "buyer",
        ChatCompletionRequest(model=f"user-provider/market-ref:{reference_id}", messages=[{"role": "user", "content": "hi"}]),
    )

    assert result["provider_id"] == "seller-provider"
    assert len(seller_handler.calls) == 1
    call_kind, provider_id, payload = seller_handler.calls[0]
    assert call_kind == "provider"
    assert provider_id == "seller-provider"
    assert payload["model"] == "seller-provider"
    assert payload["messages"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_user_provider_market_reference_rejects_unavailable_listing_at_runtime(monkeypatch):
    db = MarketReferenceRuntimeDbStub()
    buyer_handler = RuntimeUserHandlerStub()

    reference_id = db.create_market_import_reference(
        user_id=11,
        listing_id=db.listing["id"],
        reference_type="provider",
        display_name=db.listing["title"],
        owner_username=db.listing["owner_username"],
        source_type=db.listing["source_type"],
        source_id=db.listing["source_id"],
    )
    db.admin_set_market_listing_active(db.listing["id"], False)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes import user_api
    monkeypatch.setattr(user_api, "DatabaseRegistry", RegistryStub(db))

    def fake_get_user_handler(kind, user_id=None):
        if kind == "request" and user_id in (None, 11):
            buyer_handler.user_providers = {f"market-ref:{reference_id}": {"market_reference": True}}
            return buyer_handler
        raise AssertionError((kind, user_id))

    monkeypatch.setattr(user_api, "_get_user_handler", fake_get_user_handler)

    with pytest.raises(Exception) as exc_info:
        await user_api.user_chat_completions(
            DirectRequestStub(11),
            "buyer",
            ChatCompletionRequest(model=f"user-provider/market-ref:{reference_id}", messages=[{"role": "user", "content": "hi"}]),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Market reference unavailable"


def _seed_dashboard_market_reference_mix(db: MarketReferenceImportDbStub) -> None:
    provider_reference = {
        "id": 1,
        "user_id": 11,
        "listing_id": 55,
        "reference_type": "provider",
        "display_name": "Alice Provider",
        "owner_username": "alice",
        "source_type": "provider",
        "source_id": "alice-provider",
        "is_active": True,
    }
    rotation_reference = {
        "id": 2,
        "user_id": 11,
        "listing_id": 56,
        "reference_type": "rotation",
        "display_name": "Alice Rotation",
        "owner_username": "alice",
        "source_type": "rotation",
        "source_id": "alice-rotation",
        "is_active": True,
    }
    autoselect_reference = {
        "id": 3,
        "user_id": 11,
        "listing_id": 57,
        "reference_type": "autoselect",
        "display_name": "Alice Autoselect",
        "owner_username": "alice",
        "source_type": "autoselect",
        "source_id": "alice-autoselect",
        "is_active": True,
    }
    db.reference_rows = [provider_reference, rotation_reference, autoselect_reference]
    db.user_providers = [
        {
            "provider_id": "local-provider",
            "config": {"name": "Local Provider", "type": "openai", "models": []},
            "created_at": None,
            "updated_at": None,
        }
    ]
    db.user_rotations = [
        {
            "rotation_id": "local-rotation",
            "config": {"model_name": "Local Rotation", "providers": []},
        }
    ]
    db.user_autoselects = [
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


def test_dashboard_providers_renders_market_reference_alongside_local_provider(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/providers")

    assert response.status_code == 200
    assert "Local Provider" in response.text
    assert "Alice Provider" in response.text
    assert "Market-linked" in response.text
    assert "Read-only" in response.text


def test_market_references_do_not_render_local_edit_controls(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/providers")

    assert response.status_code == 200
    assert 'data-market-reference="true"' in response.text
    assert 'removeProvider(\'market-ref:1\')' not in response.text
    assert 'Edit Market Reference' not in response.text


def test_dashboard_providers_bootstrap_handles_quote_heavy_market_reference_data(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    db.reference_rows[0]["display_name"] = 'Alice\'s "Provider" </script><script>alert(1)</script>'
    db.reference_rows[0]["owner_username"] = "alice'broker</script>"
    db.reference_rows[0]["source_id"] = 'alice-provider\'x</script>'
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/providers")

    assert response.status_code == 200
    assert "let rawProviders = JSON.parse(" in response.text
    bootstrap_fragment = response.text.split("let rawProviders = JSON.parse(", 1)[1].split("\n", 1)[0]
    raw_providers = _load_json_parse_bootstrap(response.text, "let rawProviders")
    assert '</script><script>alert(1)</script>' not in bootstrap_fragment
    assert '\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e' in bootstrap_fragment
    assert raw_providers[1]["config"]["name"] == 'Alice\'s "Provider" </script><script>alert(1)</script>'
    assert raw_providers[1]["config"]["owner_username"] == "alice'broker</script>"
    assert raw_providers[1]["config"]["source_id"] == "alice-provider'x</script>"


def test_dashboard_admin_providers_bootstrap_uses_json_parse(monkeypatch):
    capture = TemplateCapture()

    providers_payload = {
        "danger-provider": {
            "name": 'Admin "Provider" </script><script>alert(2)</script>',
            "type": "openai",
            "endpoint": "https://danger.example/v1</script>",
            "models": [],
        }
    }
    request = type("Req", (), {"scope": {"root_path": ""}, "session": {}})()
    response = capture.TemplateResponse(
        request=request,
        name="dashboard/providers.html",
        context={
            "request": request,
            "session": {},
            "__version__": "test",
            "providers_data": providers_payload,
            # The page now bootstraps providers from a JSON <script> element built
            # by the route's escaping helper, not an inline JS object literal.
            "providers_bootstrap_json": dashboard_providers._json_parse_bootstrap(providers_payload),
            "studio_capability_choices": [],
            "studio_adapter_choices": [],
            "studio_adapter_profile_choices": [],
            "claude_cli_mode": False,
            "is_local_client": True,
            "success": None,
        },
    )

    response_text = response.body.decode()

    assert response.status_code == 200
    # Providers are parsed via JSON.parse of a dedicated <script> element rather
    # than being inlined as an executable JS object literal.
    assert "JSON.parse(document.getElementById('providers-bootstrap').textContent)" in response_text
    match = re.search(
        r'<script id="providers-bootstrap"[^>]*>(.*?)</script>',
        response_text,
        re.S,
    )
    assert match, "providers-bootstrap script element not found"
    bootstrap_fragment = match.group(1)
    # Dangerous markup must be escaped, never emitted raw (no </script> breakout).
    assert '</script><script>alert(2)</script>' not in bootstrap_fragment
    assert '\\u003c/script\\u003e\\u003cscript\\u003ealert(2)\\u003c/script\\u003e' in bootstrap_fragment
    # The fragment is a JSON-encoded string wrapping the JSON payload; decode twice.
    providers_bootstrap = json.loads(json.loads(bootstrap_fragment))
    assert providers_bootstrap["danger-provider"]["name"] == 'Admin "Provider" </script><script>alert(2)</script>'
    assert providers_bootstrap["danger-provider"]["endpoint"] == "https://danger.example/v1</script>"


def test_dashboard_rotations_renders_market_reference_alongside_local_rotation(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/rotations")

    assert response.status_code == 200
    assert "Local Rotation" in response.text
    assert "Alice Rotation" in response.text
    assert "Market-linked" in response.text
    assert "Read-only" in response.text
    assert 'copyRotation(\'market-ref:2\')' not in response.text


def test_dashboard_rotations_offers_market_provider_reference_in_provider_choices(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/rotations")

    assert response.status_code == 200
    context = capture.calls[-1]["context"]
    available_providers = json.loads(context["available_providers"])
    assert "local-provider" in available_providers
    assert "market-ref:1" in available_providers


def test_dashboard_autoselect_renders_market_reference_alongside_local_entry(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/autoselect")

    assert response.status_code == 200
    assert "Local Autoselect" in response.text
    assert "Alice Autoselect" in response.text
    assert "Market-linked" in response.text
    assert "Read-only" in response.text
    assert 'copyAutoselect(\'market-ref:3\')' not in response.text


def test_dashboard_autoselect_offers_market_rotation_reference_in_rotation_choices(monkeypatch):
    db = MarketReferenceImportDbStub()
    _seed_dashboard_market_reference_mix(db)
    capture = TemplateCapture()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))
    from aisbf.routes.dashboard import providers as dashboard_providers
    monkeypatch.setattr(dashboard_providers, "DatabaseRegistry", RegistryStub(db))
    monkeypatch.setattr(dashboard_providers, "_templates", capture)

    response = client.get("/dashboard/autoselect")

    assert response.status_code == 200
    context = capture.calls[-1]["context"]
    available_rotations = json.loads(context["available_rotations"])
    available_models = json.loads(context["available_models"])
    assert "local-rotation" in available_rotations
    assert "market-ref:2" in available_rotations
    assert {"id": "market-ref:2", "name": "Alice Rotation (rotation)", "type": "rotation"} in available_models


def test_import_market_listing_creates_market_reference_for_provider(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.listing['id']}/import", json={})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "imported_config_type": "market_reference",
        "imported_config_id": 1,
    }
    assert db.created_references == [
        {
            "user_id": 11,
            "listing_id": 55,
            "reference_type": "provider",
            "display_name": "Seller Provider",
            "owner_username": "seller",
            "source_type": "provider",
            "source_id": "seller-provider",
        }
    ]
    assert db.recorded_imports == [
        {
            "user_id": 11,
            "listing_id": 55,
            "imported_config_type": "market_reference",
            "imported_config_id": "1",
        }
    ]
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []


def test_import_market_listing_reference_path_does_not_expose_seller_secret_fields(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.listing['id']}/import", json={})

    assert response.status_code == 200
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []
    reference = db.get_market_import_reference(1)
    assert reference["listing_id"] == 55
    serialized_reference = json.dumps(reference)
    serialized_created_args = json.dumps(db.created_references[0])
    assert "seller-secret-key" not in serialized_reference
    assert "nested-secret" not in serialized_reference
    assert "api_key" not in serialized_reference
    assert "seller-secret-key" not in serialized_created_args
    assert "nested-secret" not in serialized_created_args
    assert "api_key" not in serialized_created_args


def test_import_market_listing_creates_market_reference_for_rotation(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.rotation_listing['id']}/import", json={})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "imported_config_type": "market_reference",
        "imported_config_id": 1,
    }
    assert db.created_references == [
        {
            "user_id": 11,
            "listing_id": 56,
            "reference_type": "rotation",
            "display_name": "Seller Rotation",
            "owner_username": "seller",
            "source_type": "rotation",
            "source_id": "seller-rotation",
        }
    ]
    assert db.recorded_imports == [
        {
            "user_id": 11,
            "listing_id": 56,
            "imported_config_type": "market_reference",
            "imported_config_id": "1",
        }
    ]
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []


def test_rotation_import_reference_path_does_not_expose_seller_secret_fields(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.rotation_listing['id']}/import", json={})

    assert response.status_code == 200
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []
    reference = db.get_market_import_reference(1)
    assert reference["listing_id"] == 56
    serialized_reference = json.dumps(reference)
    serialized_created_args = json.dumps(db.created_references[0])
    assert "rotation-secret-key" not in serialized_reference
    assert "seller-provider-a" not in serialized_reference
    assert "seller-provider-b" not in serialized_reference
    assert "providers" not in serialized_reference
    assert "weights" not in serialized_reference
    assert "rotation-secret-key" not in serialized_created_args
    assert "seller-provider-a" not in serialized_created_args
    assert "seller-provider-b" not in serialized_created_args
    assert "providers" not in serialized_created_args
    assert "weights" not in serialized_created_args


def test_import_market_listing_creates_market_reference_for_model(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.model_listing['id']}/import", json={})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "imported_config_type": "market_reference",
        "imported_config_id": 1,
    }
    assert db.created_references == [
        {
            "user_id": 11,
            "listing_id": 58,
            "reference_type": "model",
            "display_name": "Seller Model",
            "owner_username": "seller",
            "source_type": "model",
            "source_id": "seller-provider/seller-model",
        }
    ]
    assert db.recorded_imports == [
        {
            "user_id": 11,
            "listing_id": 58,
            "imported_config_type": "market_reference",
            "imported_config_id": "1",
        }
    ]
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []


def test_model_import_reference_path_does_not_expose_seller_secret_fields(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.model_listing['id']}/import", json={})

    assert response.status_code == 200
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []
    reference = db.get_market_import_reference(1)
    assert reference["listing_id"] == 58
    serialized_reference = json.dumps(reference)
    serialized_created_args = json.dumps(db.created_references[0])
    assert "model-provider-secret" not in serialized_reference
    assert "model-secret-key" not in serialized_reference
    assert "api_key" not in serialized_reference
    assert "temperature" not in serialized_reference
    assert "model-provider-secret" not in serialized_created_args
    assert "model-secret-key" not in serialized_created_args
    assert "api_key" not in serialized_created_args
    assert "temperature" not in serialized_created_args


def test_import_market_listing_creates_market_reference_for_autoselect(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.autoselect_listing['id']}/import", json={})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "imported_config_type": "market_reference",
        "imported_config_id": 1,
    }
    assert db.created_references == [
        {
            "user_id": 11,
            "listing_id": 57,
            "reference_type": "autoselect",
            "display_name": "Seller Autoselect",
            "owner_username": "seller",
            "source_type": "autoselect",
            "source_id": "seller-autoselect",
        }
    ]
    assert db.recorded_imports == [
        {
            "user_id": 11,
            "listing_id": 57,
            "imported_config_type": "market_reference",
            "imported_config_id": "1",
        }
    ]
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []


def test_autoselect_import_reference_path_does_not_expose_seller_secret_fields(monkeypatch):
    db = MarketReferenceImportDbStub()
    client = TestClient(app)
    _login_as_user(client)

    monkeypatch.setattr(dashboard_market, "DatabaseRegistry", RegistryStub(db))

    response = client.post(f"/api/market/listings/{db.autoselect_listing['id']}/import", json={})

    assert response.status_code == 200
    assert db.saved_user_providers == []
    assert db.saved_user_rotations == []
    assert db.saved_user_autoselects == []
    reference = db.get_market_import_reference(1)
    assert reference["listing_id"] == 57
    serialized_reference = json.dumps(reference)
    serialized_created_args = json.dumps(db.created_references[0])
    assert "autoselect-secret-token" not in serialized_reference
    assert "seller-provider-a/model-a" not in serialized_reference
    assert "available_models" not in serialized_reference
    assert "fallback" not in serialized_reference
    assert "autoselect-secret-token" not in serialized_created_args
    assert "seller-provider-a/model-a" not in serialized_created_args
    assert "available_models" not in serialized_created_args
    assert "fallback" not in serialized_created_args
