import json
import os
from base64 import b64encode
from pathlib import Path

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from aisbf.routes.dashboard import settings as dashboard_settings
from aisbf.config import Config

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
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


def test_dashboard_settings_save_persists_feature_controls(tmp_path, monkeypatch):
    cfg_path = tmp_path / "aisbf.json"
    cfg_path.write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": 17765, "protocol": "http"},
        "auth": {"enabled": False, "tokens": []},
        "dashboard": {"username": "admin", "password": "hash"},
        "internal_model": {
            "condensation_model_id": "internal-condense",
            "autoselect_model_id": "internal-autoselect",
            "semantic_vectorization": "sentence-transformers/all-MiniLM-L6-v2",
        },
        "database": {"type": "sqlite", "sqlite_path": "~/.aisbf/aisbf.db", "mysql_host": "localhost", "mysql_port": 3306, "mysql_user": "aisbf", "mysql_password": "", "mysql_database": "aisbf"},
        "cache": {"type": "file", "redis_host": "localhost", "redis_port": 6379, "redis_db": 0, "redis_password": "", "redis_key_prefix": "aisbf:"},
        "response_cache": {"enabled": True, "backend": "memory", "ttl": 600, "max_memory_cache": 1000, "redis_host": "localhost", "redis_port": 6379, "redis_db": 0, "redis_password": "", "redis_key_prefix": "aisbf:response:", "sqlite_path": "~/.aisbf/response_cache.db", "mysql_host": "localhost", "mysql_port": 3306, "mysql_user": "aisbf", "mysql_password": "", "mysql_database": "aisbf_response_cache"},
        "mcp": {"enabled": False, "autoselect_tokens": [], "fullconfig_tokens": []},
        "tor": {"enabled": False, "control_port": 9051, "control_host": "127.0.0.1", "control_password": None, "hidden_service_dir": None, "hidden_service_port": 80, "socks_port": 9050, "socks_host": "127.0.0.1"},
        "signup": {"enabled": False, "require_email_verification": False, "verification_token_expiry_hours": 24},
        "smtp": {"enabled": False, "host": "", "port": 587, "username": "", "password": "", "use_tls": True, "use_ssl": False, "from_email": "", "from_name": "AISBF"},
        "oauth2": {"google": {"enabled": False, "client_id": "", "client_secret": ""}, "github": {"enabled": False, "client_id": "", "client_secret": ""}},
        "batching": {"enabled": False, "window_ms": 100, "max_batch_size": 8, "provider_settings": {"openai": {"enabled": False, "max_batch_size": 10}, "anthropic": {"enabled": False, "max_batch_size": 5}}},
        "adaptive_rate_limiting": {"enabled": False, "initial_rate_limit": 0, "learning_rate": 0.1, "headroom_percent": 10, "recovery_rate": 0.05, "max_rate_limit": 60, "min_rate_limit": 0.1, "backoff_base": 2, "jitter_factor": 0.25, "history_window": 3600, "consecutive_successes_for_recovery": 10},
        "client_rate_limiting": {"enabled": False, "api": {"requests_per_minute": 60, "requests_per_hour": 1000}, "general": {"requests_per_minute": 120, "requests_per_hour": 3000}},
    }))

    monkeypatch.setattr(dashboard_settings, "get_aisbf_config_path", lambda: cfg_path)
    monkeypatch.setattr(dashboard_settings, "_reload_global_config", lambda: None)

    class TemplateStub:
        def TemplateResponse(self, *args, **kwargs):
            from starlette.responses import Response
            return Response(status_code=200)

    monkeypatch.setattr(dashboard_settings, "_templates", TemplateStub())

    client = TestClient(app)
    _login_as_admin(client)

    response = client.post(
        "/dashboard/settings",
        data={
            "host": "127.0.0.1",
            "port": 17765,
            "protocol": "http",
            "auth_enabled": "",
            "auth_tokens": "",
            "dashboard_username": "admin",
            "condensation_model_id": "internal-condense",
            "autoselect_model_id": "internal-autoselect",
            "autoselect_max_tokens": 8000,
            "condensation_max_tokens": 1000,
            "autoselect_max_new_tokens": 100,
            "nsfw_classifier": "michelleli99/NSFW_text_classifier",
            "privacy_classifier": "iiiorg/piiranha-v1-detect-personal-information",
            "semantic_vectorization": "sentence-transformers/all-MiniLM-L6-v2",
            "feature_nsfw_classification_mode": "enabled",
            "feature_privacy_classification_mode": "disabled",
            "feature_context_condensation_mode": "enabled",
            "feature_response_cache_mode": "disabled",
            "feature_prompt_batching_mode": "enabled",
            "feature_prompt_security_mode": "enabled",
            "feature_context_lens_mode": "enabled",
            "feature_block_high_risk_prompts_mode": "disabled",
            "feature_persist_prompt_text_mode": "enabled",
            "feature_redact_before_persist_mode": "disabled",
            "feature_risk_threshold": "medium",
            "batching_window_ms": 100,
            "batching_max_batch_size": 8,
            "batching_openai_max_batch_size": 10,
            "batching_anthropic_max_batch_size": 5,
            "adaptive_initial_rate_limit": 0,
            "adaptive_learning_rate": 0.1,
            "adaptive_headroom_percent": 10,
            "adaptive_recovery_rate": 0.05,
            "adaptive_max_rate_limit": 60,
            "adaptive_min_rate_limit": 0.1,
            "adaptive_backoff_base": 2,
            "adaptive_jitter_factor": 0.25,
            "adaptive_history_window": 3600,
            "adaptive_consecutive_successes": 10,
            "active_tab": "classification",
            "database_type": "sqlite",
            "sqlite_path": "~/.aisbf/aisbf.db",
            "mysql_host": "localhost",
            "mysql_port": 3306,
            "mysql_user": "aisbf",
            "mysql_password": "",
            "mysql_database": "aisbf",
            "cache_type": "file",
            "redis_host": "localhost",
            "redis_port": 6379,
            "redis_db": 0,
            "redis_password": "",
            "redis_key_prefix": "aisbf:",
            "response_cache_backend": "memory",
            "response_cache_ttl": 600,
            "response_cache_max_memory": 1000,
            "response_cache_redis_host": "localhost",
            "response_cache_redis_port": 6379,
            "response_cache_redis_db": 0,
            "response_cache_redis_password": "",
            "response_cache_redis_key_prefix": "aisbf:response:",
            "response_cache_sqlite_path": "~/.aisbf/response_cache.db",
            "response_cache_mysql_host": "localhost",
            "response_cache_mysql_port": 3306,
            "response_cache_mysql_user": "aisbf",
            "response_cache_mysql_password": "",
            "response_cache_mysql_database": "aisbf_response_cache",
            "autoselect_tokens": "",
            "fullconfig_tokens": "",
            "tor_control_port": 9051,
            "tor_control_host": "127.0.0.1",
            "tor_control_password": "",
            "tor_hidden_service_dir": "",
            "tor_hidden_service_port": 80,
            "tor_socks_port": 9050,
            "tor_socks_host": "127.0.0.1",
            "verification_token_expiry": 24,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_username": "",
            "smtp_password": "",
            "smtp_from_email": "",
            "smtp_from_name": "AISBF",
            "oauth2_google_client_id": "",
            "oauth2_google_client_secret": "",
            "oauth2_github_client_id": "",
            "oauth2_github_client_secret": "",
            "dashboard_email": "",
            "new_admin_password": "",
            "confirm_admin_password": "",
            "client_rl_api_rpm": 60,
            "client_rl_api_rph": 1000,
            "client_rl_general_rpm": 120,
            "client_rl_general_rph": 3000,
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    saved = json.loads((Path.home() / '.aisbf' / 'aisbf.json').read_text())
    assert saved["feature_controls"]["nsfw_classification"]["mode"] == "enabled"
    assert saved["feature_controls"]["privacy_classification"]["mode"] == "disabled"
    assert saved["feature_controls"]["context_condensation"]["mode"] == "enabled"
    assert saved["feature_controls"]["response_cache"]["mode"] == "disabled"
    assert saved["feature_controls"]["prompt_batching"]["mode"] == "enabled"
    assert saved["feature_controls"]["prompt_security"]["security_scan"]["mode"] == "enabled"
    assert saved["feature_controls"]["prompt_security"]["context_lens"]["mode"] == "enabled"
    assert saved["feature_controls"]["prompt_security"]["block_high_risk_prompts"]["mode"] == "disabled"
    assert saved["feature_controls"]["prompt_security"]["persist_prompt_text"]["mode"] == "enabled"
    assert saved["feature_controls"]["prompt_security"]["redact_before_persist"]["mode"] == "disabled"
    assert saved["feature_controls"]["prompt_security"]["risk_threshold"] == "medium"


def test_dashboard_settings_save_writes_back_to_resolved_config_path(tmp_path, monkeypatch):
    resolved_cfg_path = tmp_path / "custom-location.json"
    resolved_cfg_path.write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": 17765, "protocol": "http"},
        "auth": {"enabled": False, "tokens": []},
        "dashboard": {"username": "admin", "password": "hash"},
        "internal_model": {
            "condensation_model_id": "internal-condense",
            "autoselect_model_id": "internal-autoselect",
            "semantic_vectorization": "sentence-transformers/all-MiniLM-L6-v2",
        },
        "database": {"type": "sqlite", "sqlite_path": "~/.aisbf/aisbf.db", "mysql_host": "localhost", "mysql_port": 3306, "mysql_user": "aisbf", "mysql_password": "", "mysql_database": "aisbf"},
        "cache": {"type": "file", "redis_host": "localhost", "redis_port": 6379, "redis_db": 0, "redis_password": "", "redis_key_prefix": "aisbf:"},
        "response_cache": {"enabled": True, "backend": "memory", "ttl": 600, "max_memory_cache": 1000, "redis_host": "localhost", "redis_port": 6379, "redis_db": 0, "redis_password": "", "redis_key_prefix": "aisbf:response:", "sqlite_path": "~/.aisbf/response_cache.db", "mysql_host": "localhost", "mysql_port": 3306, "mysql_user": "aisbf", "mysql_password": "", "mysql_database": "aisbf_response_cache"},
        "mcp": {"enabled": False, "autoselect_tokens": [], "fullconfig_tokens": []},
        "tor": {"enabled": False, "control_port": 9051, "control_host": "127.0.0.1", "control_password": None, "hidden_service_dir": None, "hidden_service_port": 80, "socks_port": 9050, "socks_host": "127.0.0.1"},
        "signup": {"enabled": False, "require_email_verification": False, "verification_token_expiry_hours": 24},
        "smtp": {"enabled": False, "host": "", "port": 587, "username": "", "password": "", "use_tls": True, "use_ssl": False, "from_email": "", "from_name": "AISBF"},
        "oauth2": {"google": {"enabled": False, "client_id": "", "client_secret": ""}, "github": {"enabled": False, "client_id": "", "client_secret": ""}},
        "batching": {"enabled": False, "window_ms": 100, "max_batch_size": 8, "provider_settings": {"openai": {"enabled": False, "max_batch_size": 10}, "anthropic": {"enabled": False, "max_batch_size": 5}}},
        "adaptive_rate_limiting": {"enabled": False, "initial_rate_limit": 0, "learning_rate": 0.1, "headroom_percent": 10, "recovery_rate": 0.05, "max_rate_limit": 60, "min_rate_limit": 0.1, "backoff_base": 2, "jitter_factor": 0.25, "history_window": 3600, "consecutive_successes_for_recovery": 10},
        "client_rate_limiting": {"enabled": False, "api": {"requests_per_minute": 60, "requests_per_hour": 1000}, "general": {"requests_per_minute": 120, "requests_per_hour": 3000}},
    }))

    home_cfg_path = Path.home() / ".aisbf" / "aisbf.json"
    original_home = home_cfg_path.read_text() if home_cfg_path.exists() else None

    monkeypatch.setattr(dashboard_settings, "get_aisbf_config_path", lambda: resolved_cfg_path)
    monkeypatch.setattr(dashboard_settings, "_reload_global_config", lambda: None)

    class TemplateStub:
        def TemplateResponse(self, *args, **kwargs):
            from starlette.responses import Response
            return Response(status_code=200)

    monkeypatch.setattr(dashboard_settings, "_templates", TemplateStub())

    client = TestClient(app)
    _login_as_admin(client)

    response = client.post(
        "/dashboard/settings",
        data={
            "host": "127.0.0.1",
            "port": 17765,
            "protocol": "http",
            "auth_enabled": "",
            "auth_tokens": "",
            "dashboard_username": "admin",
            "condensation_model_id": "internal-condense",
            "autoselect_model_id": "internal-autoselect",
            "autoselect_max_tokens": 8000,
            "condensation_max_tokens": 1000,
            "autoselect_max_new_tokens": 100,
            "nsfw_classifier": "michelleli99/NSFW_text_classifier",
            "privacy_classifier": "iiiorg/piiranha-v1-detect-personal-information",
            "semantic_vectorization": "sentence-transformers/all-MiniLM-L6-v2",
            "feature_nsfw_classification_mode": "enabled",
            "feature_privacy_classification_mode": "disabled",
            "feature_context_condensation_mode": "enabled",
            "feature_response_cache_mode": "disabled",
            "feature_prompt_batching_mode": "enabled",
            "feature_prompt_security_mode": "enabled",
            "feature_context_lens_mode": "enabled",
            "feature_block_high_risk_prompts_mode": "disabled",
            "feature_persist_prompt_text_mode": "enabled",
            "feature_redact_before_persist_mode": "disabled",
            "feature_risk_threshold": "medium",
            "batching_window_ms": 100,
            "batching_max_batch_size": 8,
            "batching_openai_max_batch_size": 10,
            "batching_anthropic_max_batch_size": 5,
            "adaptive_initial_rate_limit": 0,
            "adaptive_learning_rate": 0.1,
            "adaptive_headroom_percent": 10,
            "adaptive_recovery_rate": 0.05,
            "adaptive_max_rate_limit": 60,
            "adaptive_min_rate_limit": 0.1,
            "adaptive_backoff_base": 2,
            "adaptive_jitter_factor": 0.25,
            "adaptive_history_window": 3600,
            "adaptive_consecutive_successes": 10,
            "active_tab": "classification",
            "database_type": "sqlite",
            "sqlite_path": "~/.aisbf/aisbf.db",
            "mysql_host": "localhost",
            "mysql_port": 3306,
            "mysql_user": "aisbf",
            "mysql_password": "",
            "mysql_database": "aisbf",
            "cache_type": "file",
            "redis_host": "localhost",
            "redis_port": 6379,
            "redis_db": 0,
            "redis_password": "",
            "redis_key_prefix": "aisbf:",
            "response_cache_backend": "memory",
            "response_cache_ttl": 600,
            "response_cache_max_memory": 1000,
            "response_cache_redis_host": "localhost",
            "response_cache_redis_port": 6379,
            "response_cache_redis_db": 0,
            "response_cache_redis_password": "",
            "response_cache_redis_key_prefix": "aisbf:response:",
            "response_cache_sqlite_path": "~/.aisbf/response_cache.db",
            "response_cache_mysql_host": "localhost",
            "response_cache_mysql_port": 3306,
            "response_cache_mysql_user": "aisbf",
            "response_cache_mysql_password": "",
            "response_cache_mysql_database": "aisbf_response_cache",
            "autoselect_tokens": "",
            "fullconfig_tokens": "",
            "tor_control_port": 9051,
            "tor_control_host": "127.0.0.1",
            "tor_control_password": "",
            "tor_hidden_service_dir": "",
            "tor_hidden_service_port": 80,
            "tor_socks_port": 9050,
            "tor_socks_host": "127.0.0.1",
            "verification_token_expiry": 24,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_username": "",
            "smtp_password": "",
            "smtp_from_email": "",
            "smtp_from_name": "AISBF",
            "oauth2_google_client_id": "",
            "oauth2_google_client_secret": "",
            "oauth2_github_client_id": "",
            "oauth2_github_client_secret": "",
            "dashboard_email": "",
            "new_admin_password": "",
            "confirm_admin_password": "",
            "client_rl_api_rpm": 60,
            "client_rl_api_rph": 1000,
            "client_rl_general_rpm": 120,
            "client_rl_general_rph": 3000,
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    saved = json.loads(resolved_cfg_path.read_text())
    assert saved["feature_controls"]["prompt_security"]["security_scan"]["mode"] == "enabled"

    if original_home is None:
        if home_cfg_path.exists():
            home_cfg_path.unlink()
    else:
        home_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        home_cfg_path.write_text(original_home)


def test_config_reload_reads_feature_controls_from_resolved_config_path(tmp_path):
    custom_dir = tmp_path / "custom-config"
    custom_dir.mkdir()
    previous_config_dir = os.environ.get("AISBF_CONFIG_DIR")

    (custom_dir / "providers.json").write_text(json.dumps({"providers": {}}))
    (custom_dir / "rotations.json").write_text(json.dumps({"rotations": {}}))
    (custom_dir / "autoselect.json").write_text(json.dumps({}))
    (custom_dir / "aisbf.json").write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": 17765, "protocol": "http"},
        "auth": {"enabled": False, "tokens": []},
        "dashboard": {"username": "admin", "password": "hash"},
        "internal_model": {
            "condensation_model_id": "internal-condense",
            "autoselect_model_id": "internal-autoselect",
            "semantic_vectorization": "sentence-transformers/all-MiniLM-L6-v2"
        },
        "feature_controls": {
            "nsfw_classification": {"mode": "enabled"},
            "privacy_classification": {"mode": "disabled"},
            "context_condensation": {"mode": "enabled"},
            "response_cache": {"mode": "enabled"},
            "prompt_batching": {"mode": "enabled"},
            "prompt_security": {
                "security_scan": {"mode": "enabled"},
                "context_lens": {"mode": "enabled"},
                "block_high_risk_prompts": {"mode": "disabled"},
                "persist_prompt_text": {"mode": "enabled"},
                "redact_before_persist": {"mode": "disabled"},
                "risk_threshold": "medium"
            }
        },
        "response_cache": {"enabled": False, "backend": "memory", "ttl": 600, "max_memory_cache": 1000},
        "batching": {"enabled": False, "window_ms": 100, "max_batch_size": 8, "provider_settings": {}},
        "adaptive_rate_limiting": {"enabled": False},
        "client_rate_limiting": {"enabled": False, "api": {"requests_per_minute": 60, "requests_per_hour": 1000}, "general": {"requests_per_minute": 120, "requests_per_hour": 3000}}
    }))

    os.environ["AISBF_CONFIG_DIR"] = str(custom_dir)
    try:
        cfg = Config()

        assert cfg.resolve_feature_enabled("nsfw_classification") is True
        assert cfg.resolve_feature_enabled("privacy_classification") is False
        assert cfg.resolve_feature_enabled("context_condensation") is True
        assert cfg.resolve_feature_enabled("response_cache") is True
        assert cfg.resolve_feature_enabled("prompt_batching") is True
        assert cfg.resolve_feature_enabled("prompt_security") is True
        assert cfg.resolve_feature_enabled("context_lens") is True
        assert cfg.resolve_feature_enabled("block_high_risk_prompts") is False
    finally:
        if previous_config_dir is None:
            os.environ.pop("AISBF_CONFIG_DIR", None)
        else:
            os.environ["AISBF_CONFIG_DIR"] = previous_config_dir
