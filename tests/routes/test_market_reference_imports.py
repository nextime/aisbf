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
        self.created_references = []
        self.reference_rows = []
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

    def get_market_settings(self):
        return dict(self.market_settings)

    def get_market_listing(self, listing_id):
        if listing_id == self.listing["id"]:
            return dict(self.listing)
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

    def get_user_providers(self, user_id):
        return []

    def get_user_rotations(self, user_id):
        return []

    def get_user_autoselects(self, user_id):
        return []


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
