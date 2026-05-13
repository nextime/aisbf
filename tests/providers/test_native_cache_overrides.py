from aisbf.providers.anthropic import AnthropicProviderHandler
from aisbf.providers.google import GoogleProviderHandler
from types import SimpleNamespace


def test_anthropic_native_cache_helper_respects_user_override(monkeypatch):
    handler = AnthropicProviderHandler(provider_id="anthropic-test", api_key="token", user_id=3)

    class DbStub:
        def get_user_cache_settings(self, user_id, provider_id, model_name):
            return {"cache_enabled": False}

    class RegistryStub:
        @staticmethod
        def get_config_database():
            return DbStub()

    monkeypatch.setattr("aisbf.providers.base.DatabaseRegistry", RegistryStub)

    assert handler._native_cache_user_allows("claude-model") is False


def test_google_native_cache_helper_defaults_true_without_user(monkeypatch):
    handler = GoogleProviderHandler(provider_id="google-test", api_key="token", user_id=9)

    class ExplodingRegistry:
        @staticmethod
        def get_config_database():
            raise AssertionError("should not be called")

    monkeypatch.setattr("aisbf.providers.base.DatabaseRegistry", ExplodingRegistry)

    assert handler._native_cache_user_allows("gemini-model") is True


def test_google_native_cache_helper_respects_user_override(monkeypatch):
    handler = GoogleProviderHandler(provider_id="google-test", api_key="token", user_id=9)

    class DbStub:
        def get_user_cache_settings(self, user_id, provider_id, model_name):
            return {"cache_enabled": False}

    class RegistryStub:
        @staticmethod
        def get_config_database():
            return DbStub()

    monkeypatch.setattr("aisbf.providers.base.DatabaseRegistry", RegistryStub)

    assert handler._native_cache_user_allows("gemini-model") is False


def test_anthropic_native_caching_adds_cache_control_markers(monkeypatch):
    handler = AnthropicProviderHandler(provider_id="anthropic-test", api_key="token", user_id=3)

    class MessagesStub:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(content=[SimpleNamespace(text="ok")], usage=SimpleNamespace(input_tokens=10, output_tokens=5), stop_reason="end_turn", model="claude-test")

    messages_api = MessagesStub()
    handler.client = SimpleNamespace(messages=messages_api)
    monkeypatch.setattr("aisbf.providers.anthropic.config.providers", {"anthropic-test": SimpleNamespace(enable_native_caching=True, min_cacheable_tokens=1)})
    monkeypatch.setattr("aisbf.providers.anthropic.count_messages_tokens", lambda messages, model: 10)
    monkeypatch.setattr(handler, "_native_cache_user_allows", lambda model_name=None: True)
    monkeypatch.setattr(handler, "record_success", lambda: None)

    result = __import__("asyncio").run(handler.handle_request(
        model="claude-test",
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
        stream=False,
    ))

    assert result["choices"][0]["message"]["content"] == "ok"
    api_params = messages_api.kwargs
    assert isinstance(api_params["system"], list)
    assert api_params["system"][0]["cache_control"]["type"] == "ephemeral"
    assert api_params["messages"][0]["content"][-1]["cache_control"]["type"] == "ephemeral"


def test_google_native_caching_sets_pending_cache_key_only_when_allowed(monkeypatch):
    handler = GoogleProviderHandler(provider_id="google-test", api_key="token", user_id=9)
    cache_key_calls = []

    class ModelsStub:
        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="ok")]), finish_reason="STOP")],
                usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, total_token_count=15),
            )

    models_api = ModelsStub()
    handler.client = SimpleNamespace(models=models_api)
    monkeypatch.setattr("aisbf.providers.google.config.providers", {"google-test": SimpleNamespace(enable_native_caching=True, cache_ttl=60, min_cacheable_tokens=1)})
    monkeypatch.setattr("aisbf.providers.google.count_messages_tokens", lambda messages, model: 10)
    monkeypatch.setattr(handler, "_generate_cache_key", lambda messages, model: cache_key_calls.append((messages, model)) or "cache-key")
    monkeypatch.setattr(handler, "_create_cached_content", lambda messages, model, ttl: None)
    monkeypatch.setattr(handler, "record_success", lambda: None)

    monkeypatch.setattr(handler, "_native_cache_user_allows", lambda model_name=None: False)
    __import__("asyncio").run(handler.handle_request(
        model="gemini-test",
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    ))
    assert handler._pending_cache_key is None
    assert cache_key_calls == []

    monkeypatch.setattr(handler, "_native_cache_user_allows", lambda model_name=None: True)
    __import__("asyncio").run(handler.handle_request(
        model="gemini-test",
        messages=[{"role": "user", "content": "hello again"}],
        stream=False,
    ))
    assert len(cache_key_calls) == 1
    assert models_api.kwargs["model"] == "gemini-test"
