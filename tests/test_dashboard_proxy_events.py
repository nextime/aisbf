import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aisbf.handlers import RequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RequestStateStub:
    def __init__(self, user_id=17, token_id=23):
        self.user_id = user_id
        self.token_id = token_id


class RequestStub:
    def __init__(self):
        self.url = SimpleNamespace(path="/api/test-provider/chat/completions")
        self.method = "POST"
        self.session = {"username": "alice"}
        self.state = RequestStateStub()
        self.headers = {}


class ProviderHandlerStub:
    def __init__(self, response):
        self.response = response
        self.success_calls = 0
        self.failure_calls = 0

    def is_rate_limited(self):
        return False

    async def apply_rate_limit(self):
        return None

    async def handle_request(self, **kwargs):
        return self.response

    def record_success(self):
        self.success_calls += 1

    def record_failure(self):
        self.failure_calls += 1


class AnalyticsStub:
    def __init__(self):
        self.calls = []

    def record_request(self, **kwargs):
        self.calls.append(kwargs)

    def estimate_cost(self, provider_id, total_tokens, prompt_tokens, completion_tokens):
        return 0.0


class DbStub:
    def __init__(self):
        self.events = []
        self.prompt_runs = []
        self.prompt_findings = []

    def record_dashboard_event(self, **kwargs):
        self.events.append(kwargs)
        return len(self.events)

    def get_user_providers(self, user_id):
        return []

    def get_user_rotations(self, user_id):
        return []

    def get_user_autoselects(self, user_id):
        return []

    def record_prompt_analysis_run(self, **kwargs):
        self.prompt_runs.append(kwargs)
        return len(self.prompt_runs)

    def record_prompt_analysis_findings(self, run_id, findings):
        self.prompt_findings.append({"run_id": run_id, "findings": findings})


class MysqlCursorStub:
    def __init__(self, lastrowid=0, fallback_id=41):
        self.lastrowid = lastrowid
        self.fallback_id = fallback_id
        self.executed = []
        self._fetchone = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "SELECT LAST_INSERT_ID()" in sql:
            self._fetchone = (self.fallback_id,)
        else:
            self._fetchone = None

    def fetchone(self):
        return self._fetchone


class MysqlConnStub:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_calls += 1


class MysqlConnCtxStub:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class CacheStub:
    def __init__(self, cached_response=None):
        self.cached_response = cached_response
        self.get_calls = 0
        self.set_calls = 0

    def get(self, *args, **kwargs):
        self.get_calls += 1
        return self.cached_response

    def set(self, *args, **kwargs):
        self.set_calls += 1


class ConfigStub:
    def __init__(self, aisbf_config=None):
        self._aisbf_config = aisbf_config

    def get_aisbf_config(self):
        return self._aisbf_config

    def get_condensation(self):
        return None

    def resolve_feature_enabled(self, feature_name, **kwargs):
        if feature_name == "response_cache":
            return True
        if feature_name == "prompt_security":
            return True
        if feature_name == "context_lens":
            return True
        if feature_name == "block_high_risk_prompts":
            return False
        if feature_name == "context_condensation":
            return False
        return False


@pytest.mark.asyncio
async def test_handle_chat_completion_records_dashboard_proxy_event(monkeypatch):
    request = RequestStub()
    response = {
        "choices": [{"message": {"content": "Hello back"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    }
    provider_handler = ProviderHandlerStub(response)
    analytics = AnalyticsStub()
    db = DbStub()

    monkeypatch.setattr("aisbf.handlers.get_provider_handler", lambda provider_id, api_key, user_id=None: provider_handler)
    monkeypatch.setattr("aisbf.handlers.get_analytics", lambda: analytics)
    monkeypatch.setattr("aisbf.handlers.DatabaseRegistry.get_config_database", staticmethod(lambda: db))
    monkeypatch.setattr("aisbf.handlers.get_response_cache", lambda *args, **kwargs: type("CacheStub", (), {"get": lambda self, *a, **k: None, "set": lambda self, *a, **k: None})())
    monkeypatch.setattr("aisbf.handlers.count_messages_tokens", lambda messages, model: 12)
    monkeypatch.setattr("aisbf.handlers.get_context_config_for_model", lambda **kwargs: {})
    monkeypatch.setattr("aisbf.handlers.get_max_request_tokens_for_model", lambda **kwargs: None)
    monkeypatch.setattr(RequestHandler, "_settle_market_result", lambda *args, **kwargs: None)

    handler = RequestHandler(user_id=17)
    handler.config = ConfigStub(aisbf_config=SimpleNamespace(response_cache=SimpleNamespace(model_dump=lambda: {})))
    handler.user_providers = {
        "test-provider": {
            "type": "openai",
            "endpoint": "https://example.test/v1",
            "api_key_required": False,
        }
    }

    result = await handler.handle_chat_completion(
        request,
        "test-provider",
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        },
    )

    assert result == response
    assert provider_handler.success_calls == 1
    assert len(db.events) == 1
    event = db.events[0]
    assert event["event_type"] == "request_proxied"
    assert event["path"] == "/api/test-provider/chat/completions"
    assert event["user_id"] == 17
    assert event["username"] == "alice"
    assert event["provider_id"] == "test-provider"
    assert event["status_code"] == 200
    assert event["metadata"]["model_name"] == "test-model"
    assert event["metadata"]["prompt_tokens"] == 12
    assert event["metadata"]["completion_tokens"] == 5
    assert event["metadata"]["total_tokens"] == 17
    assert event["metadata"]["stream"] is False
    assert db.prompt_runs
    assert db.prompt_runs[0]["provider_id"] == "test-provider"
    assert db.prompt_findings


def test_record_dashboard_proxy_event_preserves_streaming_metadata(monkeypatch):
    request = RequestStub()
    db = DbStub()

    monkeypatch.setattr("aisbf.handlers.DatabaseRegistry.get_config_database", staticmethod(lambda: db))

    handler = RequestHandler()
    handler.config = ConfigStub()
    handler._record_dashboard_proxy_event(
        request,
        "test-provider",
        "stream-model",
        True,
        18.5,
        metadata={
            "prompt_tokens": 14,
            "completion_tokens": 9,
            "total_tokens": 23,
            "stream": True,
            "rotation_id": "rotation-a",
        },
    )

    assert len(db.events) == 1
    event = db.events[0]
    assert event["event_type"] == "request_proxied"
    assert event["provider_id"] == "test-provider"
    assert event["rotation_id"] == "rotation-a"
    assert event["status_code"] == 200
    assert event["metadata"]["model_name"] == "stream-model"
    assert event["metadata"]["prompt_tokens"] == 14
    assert event["metadata"]["completion_tokens"] == 9
    assert event["metadata"]["total_tokens"] == 23
    assert event["metadata"]["stream"] is True


@pytest.mark.asyncio
async def test_handle_chat_completion_records_autoselect_id_on_proxy_event(monkeypatch):
    request = RequestStub()
    response = {
        "choices": [{"message": {"content": "Selected response"}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    provider_handler = ProviderHandlerStub(response)
    analytics = AnalyticsStub()
    db = DbStub()

    monkeypatch.setattr("aisbf.handlers.get_provider_handler", lambda provider_id, api_key, user_id=None: provider_handler)
    monkeypatch.setattr("aisbf.handlers.get_analytics", lambda: analytics)
    monkeypatch.setattr("aisbf.handlers.DatabaseRegistry.get_config_database", staticmethod(lambda: db))
    monkeypatch.setattr("aisbf.handlers.get_response_cache", lambda *args, **kwargs: type("CacheStub", (), {"get": lambda self, *a, **k: None, "set": lambda self, *a, **k: None})())
    monkeypatch.setattr("aisbf.handlers.count_messages_tokens", lambda messages, model: 8)
    monkeypatch.setattr("aisbf.handlers.get_context_config_for_model", lambda **kwargs: {})
    monkeypatch.setattr("aisbf.handlers.get_max_request_tokens_for_model", lambda **kwargs: None)
    monkeypatch.setattr(RequestHandler, "_settle_market_result", lambda *args, **kwargs: None)

    handler = RequestHandler(user_id=17)
    handler.config = ConfigStub(aisbf_config=SimpleNamespace(response_cache=SimpleNamespace(model_dump=lambda: {})))
    handler.user_providers = {
        "test-provider": {
            "type": "openai",
            "endpoint": "https://example.test/v1",
            "api_key_required": False,
        }
    }

    await handler.handle_chat_completion(
        request,
        "test-provider",
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "_autoselect_id": "auto-main",
        },
    )

    assert len(db.events) == 1
    event = db.events[0]
    assert event["autoselect_id"] == "auto-main"
    assert event["metadata"]["autoselect_id"] == "auto-main"


def test_request_handler_resolves_provider_cache_override():
    handler = RequestHandler(user_id=17)

    class ConfigWithProviderOverride(ConfigStub):
        def resolve_feature_enabled(self, feature_name, **kwargs):
            if feature_name == "response_cache":
                provider_config = kwargs.get("provider_config") or {}
                return provider_config.get("enable_response_cache") is True
            return super().resolve_feature_enabled(feature_name, **kwargs)

    handler.config = ConfigWithProviderOverride(aisbf_config=SimpleNamespace(response_cache=SimpleNamespace(enabled=True, model_dump=lambda: {})))

    assert handler._should_cache_response(provider_config={"enable_response_cache": False}) is False
    assert handler._should_cache_response(provider_config={"enable_response_cache": True}) is True


def test_record_prompt_analysis_run_uses_mysql_last_insert_id_fallback():
    from aisbf.database import DatabaseManager

    manager = DatabaseManager.__new__(DatabaseManager)
    manager.db_type = "mysql"
    cursor = MysqlCursorStub(lastrowid=0, fallback_id=77)
    conn = MysqlConnStub(cursor)
    manager._get_connection = lambda: MysqlConnCtxStub(conn)

    run_id = manager.record_prompt_analysis_run(
        user_id=5,
        token_id=9,
        provider_id="provider-a",
        model_name="model-a",
        summary_json={"composition": {"has_tools": True}},
    )

    assert run_id == 77
    assert any("SELECT LAST_INSERT_ID()" in sql for sql, _ in cursor.executed)
    insert_sql, insert_params = cursor.executed[0]
    assert "INSERT INTO prompt_analysis_runs" in insert_sql
    assert '"has_tools": true' in insert_params[-1]


def test_prompt_analysis_details_mysql_json_extract_uses_text_column_directly():
    from aisbf.database import DatabaseManager

    class CursorStub:
        def __init__(self):
            self.executed = []
            self._fetchall_calls = 0

        def execute(self, sql, params=None):
            self.executed.append((sql, params))

        def fetchall(self):
            self._fetchall_calls += 1
            return []

        def fetchone(self):
            return (0, 0, 0, 0)

    class ConnStub:
        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self):
            return self._cursor

    manager = DatabaseManager.__new__(DatabaseManager)
    manager.db_type = "mysql"
    cursor = CursorStub()
    manager._get_connection = lambda: MysqlConnCtxStub(ConnStub(cursor))

    now = __import__("datetime").datetime.now()
    manager.get_prompt_analysis_details(start=now, end=now)

    executed_sql = "\n".join(sql for sql, _ in cursor.executed)
    assert "JSON_UNQUOTE(JSON_EXTRACT(summary_json, '$.composition.largest_segment_role'))" in executed_sql
    assert "CAST(summary_json AS JSON)" not in executed_sql


@pytest.mark.asyncio
async def test_handle_chat_completion_uses_cache_when_provider_override_enables_it(monkeypatch):
    request = RequestStub()
    cached_response = {
        "choices": [{"message": {"content": "Cached"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    provider_handler = ProviderHandlerStub({"choices": [{"message": {"content": "Live"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    analytics = AnalyticsStub()
    db = DbStub()
    cache = CacheStub(cached_response=cached_response)

    monkeypatch.setattr("aisbf.handlers.get_provider_handler", lambda provider_id, api_key, user_id=None: provider_handler)
    monkeypatch.setattr("aisbf.handlers.get_analytics", lambda: analytics)
    monkeypatch.setattr("aisbf.handlers.DatabaseRegistry.get_config_database", staticmethod(lambda: db))
    monkeypatch.setattr("aisbf.handlers.get_response_cache", lambda *args, **kwargs: cache)
    monkeypatch.setattr("aisbf.handlers.count_messages_tokens", lambda messages, model: 12)
    monkeypatch.setattr("aisbf.handlers.get_context_config_for_model", lambda **kwargs: {})
    monkeypatch.setattr("aisbf.handlers.get_max_request_tokens_for_model", lambda **kwargs: None)
    monkeypatch.setattr(RequestHandler, "_settle_market_result", lambda *args, **kwargs: None)

    handler = RequestHandler(user_id=17)
    handler.config = ConfigStub(aisbf_config=SimpleNamespace(response_cache=SimpleNamespace(enabled=True, model_dump=lambda: {})))
    handler.user_providers = {
        "test-provider": {
            "type": "openai",
            "endpoint": "https://example.test/v1",
            "api_key_required": False,
            "enable_response_cache": True,
        }
    }

    result = await handler.handle_chat_completion(
        request,
        "test-provider",
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        },
    )

    assert result == cached_response
    assert cache.get_calls == 1
    assert cache.set_calls == 0
    assert provider_handler.success_calls == 0
