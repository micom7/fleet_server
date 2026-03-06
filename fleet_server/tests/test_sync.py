"""T3 — Smoke tests: sync writer (без HTTP, напряму через pool)"""
import pytest
from datetime import datetime, timezone, timedelta

from conftest import db_create_vehicle, db_delete_vehicle

# sync/writer.py
from writer import (
    write_measurements,
    upsert_channels,
    upsert_alarms,
    update_vehicle_seen,
    update_last_sync_at,
    write_journal,
)


def _pool():
    """Повертає DB pool з API (вже ініціалізований через lifespan TestClient)."""
    from database import _pool as p
    return p


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def test_vehicle(client):
    vid = db_create_vehicle("SyncTestVehicle", "10.99.0.200")
    yield vid
    db_delete_vehicle(vid)


# ── write_measurements ─────────────────────────────────────────────────────────

def test_write_measurements_inserts_rows(client, test_vehicle):
    pool = _pool()
    ts = now_utc().replace(microsecond=0)
    rows = [
        {"channel_id": 1, "value": 42.0, "time": ts.isoformat()},
        {"channel_id": 2, "value": 99.5, "time": ts.isoformat()},
    ]
    written = write_measurements(pool, test_vehicle, rows)
    assert written == 2


def test_write_measurements_deduplication(client, test_vehicle):
    pool = _pool()
    ts = now_utc().replace(microsecond=0)
    row = [{"channel_id": 3, "value": 10.0, "time": ts.isoformat()}]

    first = write_measurements(pool, test_vehicle, row)
    second = write_measurements(pool, test_vehicle, row)  # той самий timestamp

    assert first == 1
    assert second == 1  # функція рахує відправлені, ON CONFLICT DO NOTHING в БД


def test_write_measurements_skips_null_values(client, test_vehicle):
    pool = _pool()
    ts = now_utc().replace(microsecond=0)
    rows = [
        {"channel_id": 4, "value": None, "time": ts.isoformat()},
        {"channel_id": 5, "value": 7.7,  "time": ts.isoformat()},
    ]
    written = write_measurements(pool, test_vehicle, rows)
    assert written == 1  # null пропущено


# ── upsert_channels ────────────────────────────────────────────────────────────

def test_upsert_channels_creates_and_updates(client, test_vehicle):
    pool = _pool()
    channels = [
        {"channel_id": 1, "name": "RPM",   "unit": "rpm", "phys_min": 0, "phys_max": 8000},
        {"channel_id": 2, "name": "Speed",  "unit": "km/h"},
    ]
    upsert_channels(pool, test_vehicle, channels)

    # Оновлення назви
    channels[0]["name"] = "Engine RPM"
    upsert_channels(pool, test_vehicle, channels)

    from database import get_conn
    with get_conn(user_id="00000000-0000-0000-0000-000000000001", user_role="superuser") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM channel_config WHERE vehicle_id = %s AND channel_id = 1",
                (test_vehicle,),
            )
            row = cur.fetchone()
    assert row is not None
    assert row[0] == "Engine RPM"


# ── update_vehicle_seen / update_last_sync_at ──────────────────────────────────

def test_update_vehicle_seen_sets_sync_status_ok(client, test_vehicle):
    pool = _pool()
    ts = now_utc()
    update_vehicle_seen(pool, test_vehicle, ts, software_version="1.2.3")

    from database import get_conn
    with get_conn(user_id="00000000-0000-0000-0000-000000000001", user_role="superuser") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sync_status, software_version FROM vehicles WHERE id = %s",
                (test_vehicle,),
            )
            row = cur.fetchone()
    assert row[0] == "ok"
    assert row[1] == "1.2.3"


def test_update_last_sync_at(client, test_vehicle):
    pool = _pool()
    ts = now_utc()
    update_last_sync_at(pool, test_vehicle, ts)

    from database import get_conn
    with get_conn(user_id="00000000-0000-0000-0000-000000000001", user_role="superuser") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_sync_at FROM vehicles WHERE id = %s",
                (test_vehicle,),
            )
            row = cur.fetchone()
    assert row[0] is not None
    assert abs((row[0] - ts).total_seconds()) < 1


# ── write_journal ──────────────────────────────────────────────────────────────

def test_write_journal_records_cycle(client, test_vehicle):
    pool = _pool()
    started = now_utc()
    finished = started + timedelta(seconds=2)
    write_journal(pool, test_vehicle, started, finished, "ok", rows_written=5, error_msg=None)

    from database import get_conn
    with get_conn(user_id="00000000-0000-0000-0000-000000000001", user_role="superuser") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, rows_written FROM sync_journal "
                "WHERE vehicle_id = %s ORDER BY started_at DESC LIMIT 1",
                (test_vehicle,),
            )
            row = cur.fetchone()
    assert row[0] == "ok"
    assert row[1] == 5
