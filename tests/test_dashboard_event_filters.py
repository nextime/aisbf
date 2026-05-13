from datetime import datetime, timedelta

from aisbf.database import DatabaseManager


def _make_db(tmp_path):
    db_path = tmp_path / "dashboard-events.db"
    return DatabaseManager({
        "type": "sqlite",
        "sqlite_path": str(db_path),
    })


def _seed_events(db: DatabaseManager):
    now = datetime.now()
    rows = [
        {
            "event_type": "request_proxied",
            "path": "/api/provider-a/chat/completions",
            "user_id": 11,
            "username": "alice",
            "session_id": "sess-a",
            "ip_address": "1.1.1.1",
            "country_code": "IT",
            "method": "POST",
            "status_code": 200,
            "provider_id": "provider-a",
            "rotation_id": "rotation-a",
            "autoselect_id": "auto-a",
            "metadata": {"kind": "success"},
            "created_at": now - timedelta(hours=1),
        },
        {
            "event_type": "provider_removed",
            "path": "/dashboard/api/provider/provider-b",
            "user_id": None,
            "username": "admin",
            "session_id": "sess-admin",
            "ip_address": "2.2.2.2",
            "country_code": "US",
            "method": "DELETE",
            "status_code": 200,
            "provider_id": "provider-b",
            "rotation_id": None,
            "autoselect_id": None,
            "metadata": {"source": "api"},
            "created_at": now - timedelta(minutes=30),
        },
        {
            "event_type": "rotation_saved_updated",
            "path": "/dashboard/rotations",
            "user_id": 12,
            "username": "bob",
            "session_id": "sess-b",
            "ip_address": "3.3.3.3",
            "country_code": "IT",
            "method": "POST",
            "status_code": 200,
            "provider_id": "provider-c",
            "rotation_id": "rotation-b",
            "autoselect_id": None,
            "metadata": {"source": "bulk"},
            "created_at": now - timedelta(minutes=10),
        },
        {
            "event_type": "autoselect_saved_created",
            "path": "/dashboard/autoselect",
            "user_id": 11,
            "username": "alice",
            "session_id": "sess-a",
            "ip_address": "1.1.1.1",
            "country_code": "DE",
            "method": "POST",
            "status_code": 200,
            "provider_id": None,
            "rotation_id": None,
            "autoselect_id": "auto-b",
            "metadata": {"source": "bulk"},
            "created_at": now - timedelta(minutes=5),
        },
    ]

    with db._get_connection() as conn:
        cursor = conn.cursor()
        for row in rows:
            cursor.execute(
                """
                INSERT INTO dashboard_events (
                    event_type, path, user_id, username, session_id, ip_address, country_code,
                    method, status_code, provider_id, rotation_id, autoselect_id, listing_id,
                    target_user_id, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["event_type"],
                    row["path"],
                    row["user_id"],
                    row["username"],
                    row["session_id"],
                    row["ip_address"],
                    row["country_code"],
                    row["method"],
                    row["status_code"],
                    row["provider_id"],
                    row["rotation_id"],
                    row["autoselect_id"],
                    None,
                    None,
                    "{}",
                    db._format_dt_db(row["created_at"]),
                ),
            )
        conn.commit()

    return now


def test_dashboard_event_summary_filters_by_provider_rotation_autoselect_and_country(tmp_path):
    db = _make_db(tmp_path)
    now = _seed_events(db)
    start = now - timedelta(hours=2)
    end = now + timedelta(minutes=1)

    provider_summary = db.get_dashboard_event_summary(start, end, provider_filter="provider-a")
    assert provider_summary["total_events"] == 1
    assert provider_summary["by_type"][0]["event_type"] == "request_proxied"

    rotation_summary = db.get_dashboard_event_summary(start, end, rotation_filter="rotation-b")
    assert rotation_summary["total_events"] == 1
    assert rotation_summary["users"][0]["username"] == "bob"

    autoselect_summary = db.get_dashboard_event_summary(start, end, autoselect_filter="auto-b")
    assert autoselect_summary["total_events"] == 1
    assert autoselect_summary["countries"][0]["country_code"] == "DE"

    country_summary = db.get_dashboard_event_summary(start, end, country_filter="IT")
    assert country_summary["total_events"] == 2
    assert {row["event_type"] for row in country_summary["by_type"]} == {"request_proxied", "rotation_saved_updated"}


def test_dashboard_events_filters_return_only_matching_rows(tmp_path):
    db = _make_db(tmp_path)
    now = _seed_events(db)
    start = now - timedelta(hours=2)
    end = now + timedelta(minutes=1)

    provider_rows = db.get_dashboard_events(start, end, event_types=["request_proxied"], user_id=11, limit=20)
    assert len(provider_rows) == 1
    assert provider_rows[0]["provider_id"] == "provider-a"
    assert provider_rows[0]["autoselect_id"] == "auto-a"

    guest_summary = db.get_dashboard_event_summary(start, end, user_id=-1)
    assert guest_summary["total_events"] == 1
    assert guest_summary["users"][0]["username"] == "admin"


def test_dashboard_event_series_buckets_by_hour_and_day(tmp_path):
    db = _make_db(tmp_path)
    now = _seed_events(db)
    start = now - timedelta(days=2)
    end = now + timedelta(minutes=1)

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO dashboard_events (
                event_type, path, user_id, username, session_id, ip_address, country_code,
                method, status_code, provider_id, rotation_id, autoselect_id, listing_id,
                target_user_id, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "request_proxied",
                "/api/provider-a/chat/completions",
                11,
                "alice",
                "sess-old",
                "1.1.1.1",
                "IT",
                "POST",
                200,
                "provider-a",
                None,
                None,
                None,
                None,
                "{}",
                db._format_dt_db(now - timedelta(days=1, hours=2)),
            ),
        )
        conn.commit()

    hourly = db.get_dashboard_event_series(start, end, bucket="hour")
    daily = db.get_dashboard_event_series(start, end, bucket="day")

    assert len(hourly) >= 2
    assert sum(bucket["events"] for bucket in hourly) == 5
    assert len(daily) >= 2
    assert sum(bucket["events"] for bucket in daily) == 5
    assert any(bucket["events"] >= 4 for bucket in daily)
