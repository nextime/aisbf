"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Shared fixtures for the dashboard route tests.

The dashboard auth middleware rejects any logged-in non-admin session whose
``user_id`` is not found in the config database, clearing the session and
redirecting to ``/dashboard/login?error=Account+deleted``.  The route tests set
a session cookie for a synthetic user (e.g. id 17) but only stub the database in
the route-handler modules, not the one the middleware consults
(``DatabaseRegistry.get_config_database()``).  Without this fixture every
user-scoped dashboard request bounces through that redirect until httpx raises
``TooManyRedirects``.

The autouse fixture below wraps ``DatabaseRegistry.get_config_database`` so the
middleware's ``get_user_by_id`` lookup always succeeds for the test session,
while every other database call is delegated to the real (test) database.  Tests
that install their own ``get_config_database`` stub still win, because their
``monkeypatch.setattr`` runs after this fixture.
"""

import inspect

import pytest

from aisbf.database import DatabaseRegistry


def _called_from_auth_middleware() -> bool:
    """True when the current call originates inside the dashboard auth middleware."""
    for frame in inspect.stack():
        if frame.function == "auth_middleware" and frame.filename.replace("\\", "/").endswith("app/middleware.py"):
            return True
    return False


class _AuthAwareConfigDb:
    """Proxy that makes ``get_user_by_id`` truthy for the dashboard auth check.

    The synthetic user is returned ONLY when the lookup comes from the auth
    middleware, so direct database assertions in other tests (e.g. the signup
    cleanup tests, which expect deleted users to read back as ``None``) still
    observe the real database.  Every other attribute is delegated unchanged.
    """

    def __init__(self, real):
        self._real = real

    def get_user_by_id(self, user_id):
        real_result = None
        if self._real is not None:
            try:
                real_result = self._real.get_user_by_id(user_id)
            except Exception:
                real_result = None
        if real_result:
            return real_result
        if _called_from_auth_middleware():
            # Synthesize a present, verified user so the auth middleware does not
            # treat the test session as a deleted account.
            return {
                "id": user_id,
                "username": f"user{user_id}",
                "role": "user",
                "email_verified": True,
            }
        return real_result

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture(autouse=True)
def honor_test_user_session(monkeypatch):
    original = DatabaseRegistry.get_config_database

    def patched(*args, **kwargs):
        real = original(*args, **kwargs)
        if isinstance(real, _AuthAwareConfigDb):
            return real
        return _AuthAwareConfigDb(real)

    monkeypatch.setattr(DatabaseRegistry, "get_config_database", staticmethod(patched))
    yield
