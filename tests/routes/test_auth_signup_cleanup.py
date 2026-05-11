from datetime import datetime, timedelta
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from base64 import b64encode
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aisbf.database import DatabaseRegistry
from main import app


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


def test_login_cleanup_removes_self_registered_users_without_login_after_14_days():
    client = TestClient(app)
    db = DatabaseRegistry.get_config_database()
    token = uuid4().hex

    stale_user_id = db.create_user(
        username=f"stale-signup-{token}",
        email=f"stale-signup-{token}@example.com",
        password_hash="hash",
        role="user",
        email_verified=False,
    )
    active_user_id = db.create_user(
        username=f"active-signup-{token}",
        email=f"active-signup-{token}@example.com",
        password_hash="hash",
        role="user",
        email_verified=False,
    )

    with db._get_connection() as conn:
        cursor = conn.cursor()
        placeholder = '?' if db.db_type == 'sqlite' else '%s'
        cursor.execute(
            f"UPDATE users SET created_at = {placeholder}, last_login = NULL, email_verified = 0, created_by = NULL WHERE id = {placeholder}",
            ((datetime.now() - timedelta(days=15)).isoformat(sep=" "), stale_user_id),
        )
        cursor.execute(
            f"UPDATE users SET created_at = {placeholder}, last_login = NULL, email_verified = 0, created_by = NULL WHERE id = {placeholder}",
            ((datetime.now() - timedelta(days=13)).isoformat(sep=" "), active_user_id),
        )
        conn.commit()

    response = client.post(
        "/dashboard/login",
        data={"username": "definitely-not-a-user", "password": "wrong-password"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db.get_user_by_id(stale_user_id) is None
    assert db.get_user_by_id(active_user_id) is not None


def test_admin_created_users_are_not_removed_by_signup_cleanup():
    db = DatabaseRegistry.get_config_database()
    token = uuid4().hex

    invited_user_id = db.create_user(
        username=f"invited-stale-{token}",
        email=f"invited-stale-{token}@example.com",
        password_hash="hash",
        role="user",
        created_by="admin",
        email_verified=False,
    )

    with db._get_connection() as conn:
        cursor = conn.cursor()
        placeholder = '?' if db.db_type == 'sqlite' else '%s'
        cursor.execute(
            f"UPDATE users SET created_at = {placeholder}, last_login = NULL, email_verified = 0, created_by = {placeholder} WHERE id = {placeholder}",
            ((datetime.now() - timedelta(days=30)).isoformat(sep=" "), "admin", invited_user_id),
        )
        conn.commit()

    response = db.delete_stale_unverified_signup_users(inactivity_days=14)

    assert response == 0
    assert db.get_user_by_id(invited_user_id) is not None
