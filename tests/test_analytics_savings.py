from datetime import datetime, timedelta
import aisbf.analytics as analytics_module
from aisbf.analytics import Analytics
from aisbf.database import DatabaseManager


class _UsageDb(DatabaseManager):
    def get_provider_usage(self, user_id, provider_id):
        return {
            "usage_data": {
                "free_tier": {
                    "limit_type": "requests",
                    "limit": 1,
                    "period": "week",
                    "used": 200_000_000,
                    "source": "provider",
                }
            }
        }


def _make_db(tmp_path):
    db_path = tmp_path / "analytics-savings.db"
    return _UsageDb({
        "type": "sqlite",
        "sqlite_path": str(db_path),
    })


def _seed_token_usage(db: DatabaseManager, rows: list[dict]):
    with db._get_connection() as conn:
        cursor = conn.cursor()
        for row in rows:
            cursor.execute(
                """
                INSERT INTO token_usage (
                    user_id, provider_id, model_name, tokens_used, prompt_tokens, completion_tokens,
                    actual_cost, success, latency_ms, error_type, token_id, rotation_id,
                    autoselect_id, analytics_kind, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("user_id"),
                    row["provider_id"],
                    row["model_name"],
                    row["tokens_used"],
                    row.get("prompt_tokens"),
                    row.get("completion_tokens"),
                    row.get("actual_cost"),
                    row.get("success", 1),
                    row.get("latency_ms", 100),
                    row.get("error_type"),
                    row.get("token_id"),
                    row.get("rotation_id"),
                    row.get("autoselect_id"),
                    row.get("analytics_kind", "execution"),
                    db._format_dt_db(row["timestamp"]),
                ),
            )
        conn.commit()


class _CacheStub:
    def get_stats(self):
        return {"hits": 0}

    def get_user_stats(self, user_id):
        return {"hits": 0}


class _BatcherStub:
    def get_stats(self):
        return {"batches_formed": 0, "requests_batched": 0}


class _ConfigStub:
    def get_provider(self, provider_id, warn=False):
        return None


def test_savings_overview_caps_single_provider_subscription_savings_by_estimated_cost(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    now = datetime.now()
    _seed_token_usage(db, [
        {
            "provider_id": "codex-free",
            "model_name": "gpt-5-mini",
            "tokens_used": 200_000_000,
            "prompt_tokens": 100_000_000,
            "completion_tokens": 100_000_000,
            "timestamp": now - timedelta(hours=1),
        }
    ])

    monkeypatch.setattr("aisbf.analytics.get_response_cache", lambda: _CacheStub(), raising=False)
    monkeypatch.setattr("aisbf.cache.get_response_cache", lambda: _CacheStub())
    monkeypatch.setattr("aisbf.batching.get_request_batcher", lambda: _BatcherStub())
    monkeypatch.setattr(analytics_module, "config", _ConfigStub(), raising=False)

    analytics = Analytics(db)
    overview = analytics.get_savings_overview(
        from_datetime=now - timedelta(days=1),
        to_datetime=now,
        provider_filter="codex-free",
        model_filter="gpt-5-mini",
    )

    assert overview is not None
    assert overview["provider_equivalents"] == []
    assert overview["total_cost_saved"] == 0
    assert overview["direct_feature_savings"]["cost_saved"] == 0
    assert overview["free_tier_equivalent_savings"]["cost_saved"] == 0


def test_savings_overview_caps_multi_provider_free_tier_equivalent_by_estimated_cost(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    now = datetime.now()
    _seed_token_usage(db, [
        {
            "provider_id": "codex-free",
            "model_name": "gpt-5-mini",
            "tokens_used": 200_000_000,
            "prompt_tokens": 100_000_000,
            "completion_tokens": 100_000_000,
            "timestamp": now - timedelta(hours=1),
        }
    ])

    monkeypatch.setattr("aisbf.analytics.get_response_cache", lambda: _CacheStub(), raising=False)
    monkeypatch.setattr("aisbf.cache.get_response_cache", lambda: _CacheStub())
    monkeypatch.setattr("aisbf.batching.get_request_batcher", lambda: _BatcherStub())
    monkeypatch.setattr(analytics_module, "config", _ConfigStub(), raising=False)

    analytics = Analytics(db)
    overview = analytics.get_savings_overview(
        from_datetime=now - timedelta(days=1),
        to_datetime=now,
    )

    assert overview is not None
    assert len(overview["provider_equivalents"]) == 1
    provider_equivalent = overview["provider_equivalents"][0]
    assert provider_equivalent["estimated_payg_cost"] > 0
    assert provider_equivalent["covered_usage_amount"] == 1
    assert provider_equivalent["coverage_ratio"] == 1
    assert provider_equivalent["equivalent_saved_cost"] < provider_equivalent["estimated_payg_cost"]
    assert provider_equivalent["equivalent_saved_cost"] <= provider_equivalent["premium_reference_monthly_cost"]
    assert overview["total_cost_saved"] == provider_equivalent["equivalent_saved_cost"]
    assert overview["free_tier_equivalent_savings"]["cost_saved"] == provider_equivalent["equivalent_saved_cost"]
    assert overview["direct_feature_savings"]["cost_saved"] == 0
