"""
Синхронні DB-операції для Sync Service.

Кожна функція отримує pool та самостійно бере/повертає з'єднання.
RLS обходиться встановленням app.user_role='superuser' на початку транзакції.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

import psycopg2
import psycopg2.extras
import psycopg2.pool
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

Pool = psycopg2.pool.ThreadedConnectionPool


def _parse_dt(s: str | None) -> datetime | None:
    """ISO8601 UTC рядок → timezone-aware datetime, або None."""
    if s is None:
        return None
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


@contextmanager
def _conn(pool: Pool) -> Generator:
    """Контекст-менеджер: взяти з'єднання, встановити superuser RLS, commit/rollback."""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            # transaction-local: скидається при rollback, але ми все одно
            # ставимо на кожній транзакції — безпечно з пулом
            cur.execute("SELECT set_config('app.user_role', 'superuser', true)")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Читання ───────────────────────────────────────────────────────────────────

def get_all_vehicles(pool: Pool) -> list[dict]:
    """Всі авто з полями, потрібними для sync."""
    with _conn(pool) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, host(vpn_ip) AS vpn_ip,
                       api_port, api_key, last_sync_at
                FROM vehicles
                ORDER BY name
            """)
            return [dict(r) for r in cur.fetchall()]


# ── Оновлення vehicles ────────────────────────────────────────────────────────

def update_vehicle_seen(
    pool: Pool,
    vehicle_id: str,
    last_seen_at: datetime,
    software_version: str | None,
) -> None:
    """Оновити last_seen_at, sync_status='ok', software_version."""
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE vehicles
                SET last_seen_at     = %s,
                    sync_status      = 'ok',
                    software_version = COALESCE(%s, software_version)
                WHERE id = %s
            """, (last_seen_at, software_version, vehicle_id))


def update_vehicle_error(pool: Pool, vehicle_id: str, sync_status: str) -> None:
    """Оновити sync_status на 'timeout' або 'error'."""
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vehicles SET sync_status = %s WHERE id = %s",
                (sync_status, vehicle_id),
            )


def update_last_sync_at(pool: Pool, vehicle_id: str, ts: datetime) -> None:
    """Зберегти позначку успішного pull (використовується для gap-filling)."""
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vehicles SET last_sync_at = %s WHERE id = %s",
                (ts, vehicle_id),
            )


# ── Запис даних ───────────────────────────────────────────────────────────────

def upsert_channels(pool: Pool, vehicle_id: str, channels: list[dict]) -> None:
    """INSERT / UPDATE channel_config."""
    if not channels:
        return
    now = datetime.now(timezone.utc)
    data = [
        (
            vehicle_id,
            c['channel_id'],
            c['name'],
            c.get('unit'),
            c.get('phys_min'),   # контракт: phys_min → min_value у fleet DB
            c.get('phys_max'),   # контракт: phys_max → max_value у fleet DB
            now,
        )
        for c in channels
    ]
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO channel_config
                    (vehicle_id, channel_id, name, unit, min_value, max_value, synced_at)
                VALUES %s
                ON CONFLICT (vehicle_id, channel_id) DO UPDATE
                    SET name      = EXCLUDED.name,
                        unit      = EXCLUDED.unit,
                        min_value = EXCLUDED.min_value,
                        max_value = EXCLUDED.max_value,
                        synced_at = EXCLUDED.synced_at
            """, data)


def write_measurements(pool: Pool, vehicle_id: str, rows: list[dict]) -> int:
    """Batch-insert вимірювань. Повертає кількість відправлених рядків.

    Рядки з value=null пропускаються (NOT NULL в schema).
    ON CONFLICT (vehicle_id, channel_id, time) DO NOTHING — safe для gap-filling.
    """
    data = [
        (vehicle_id, r['channel_id'], r['value'], _parse_dt(r['time']))
        for r in rows
        if r.get('value') is not None
    ]
    if not data:
        return 0
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO measurements (vehicle_id, channel_id, value, time)
                VALUES %s
                ON CONFLICT (vehicle_id, channel_id, time) DO NOTHING
            """, data)
    return len(data)


def upsert_alarms(pool: Pool, vehicle_id: str, alarms: list[dict]) -> None:
    """INSERT / UPDATE alarms_log. При повторному отриманні — оновлює resolved_at."""
    if not alarms:
        return
    data = [
        (
            vehicle_id,
            a['alarm_id'],
            a.get('channel_id'),
            a.get('severity'),
            a.get('message', ''),
            _parse_dt(a['triggered_at']),
            _parse_dt(a.get('resolved_at')),
        )
        for a in alarms
    ]
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO alarms_log
                    (vehicle_id, alarm_id, channel_id, severity,
                     message, triggered_at, resolved_at)
                VALUES %s
                ON CONFLICT (vehicle_id, alarm_id) DO UPDATE
                    SET resolved_at = EXCLUDED.resolved_at
            """, data)


def write_journal(
    pool: Pool,
    vehicle_id: str,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    rows_written: int,
    error_msg: str | None,
) -> None:
    """Записати результат одного sync-циклу в sync_journal."""
    with _conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sync_journal
                    (vehicle_id, started_at, finished_at, status, rows_written, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (vehicle_id, started_at, finished_at, status, rows_written, error_msg))
