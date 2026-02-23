"""
Fleet Server — Sync Service

Pull-цикл: кожні SYNC_INTERVAL_SEC секунд опитує всі авто паралельно.

Запуск локально (з fleet_server/sync/):
    pip install -r requirements.txt
    python main.py

Запуск у Docker: автоматично через docker-compose (сервіс 'sync').
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows: ProactorEventLoop (дефолт в Python 3.8+) має баги з concurrent
# httpx-з'єднаннями до недосяжних IP — перемикаємось на SelectorEventLoop.
# У Docker (Linux) цей блок не виконується.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import anyio
import httpx
import psycopg2
import psycopg2.pool
from dotenv import load_dotenv

# Завантажити .env з fleet_server/ (для локальної розробки)
# У Docker env-змінні вже є в оточенні через env_file у docker-compose
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from puller import VehiclePuller
from writer import (
    get_all_vehicles,
    update_vehicle_seen,
    update_vehicle_error,
    update_last_sync_at,
    upsert_channels,
    write_measurements,
    upsert_alarms,
    write_journal,
)

# ── Логування ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger('sync')

# ── Конфігурація ──────────────────────────────────────────────────────────────

SYNC_INTERVAL_SEC = int(os.getenv('SYNC_INTERVAL_SEC', '30'))
PULL_TIMEOUT_SEC  = float(os.getenv('PULL_TIMEOUT_SEC', '10'))
PULL_WINDOW_SEC   = int(os.getenv('PULL_WINDOW_SEC', '60'))
DEFAULT_API_KEY   = os.getenv('VEHICLE_DEFAULT_API_KEY', '')

_DB_DSN = (
    f"host={os.getenv('DB_HOST', 'localhost')} "
    f"port={os.getenv('DB_PORT', '5432')} "
    f"dbname={os.getenv('DB_NAME', 'fleet')} "
    f"user={os.getenv('DB_USER', 'fleet_app')} "
    f"password={os.getenv('DB_PASSWORD', '')}"
)


def _build_pool() -> psycopg2.pool.ThreadedConnectionPool:
    return psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=20, dsn=_DB_DSN)


# ── Sync для одного авто ──────────────────────────────────────────────────────

async def sync_vehicle(
    vehicle: dict,
    pool: psycopg2.pool.ThreadedConnectionPool,
) -> None:
    """Повний цикл синхронізації одного авто.

    Порядок кроків відповідає DATA_CONTRACT.md § «Цикл синхронізації».
    """
    vid    = str(vehicle['id'])
    vname  = vehicle.get('name', vid)
    api_key = vehicle.get('api_key') or DEFAULT_API_KEY

    started   = datetime.now(timezone.utc)
    rows_done = 0

    async with VehiclePuller(vehicle, api_key, PULL_TIMEOUT_SEC) as puller:

        # ── 1. GET /status ─────────────────────────────────────────────────────
        try:
            status_data = await puller.pull_status()
        except httpx.TimeoutException:
            log.warning('[%s] timeout on /status', vname)
            await asyncio.to_thread(update_vehicle_error, pool, vid, 'timeout')
            await asyncio.to_thread(
                write_journal, pool, vid,
                started, datetime.now(timezone.utc),
                'timeout', 0, 'Request timed out',
            )
            return
        except Exception as exc:
            log.error('[%s] error on /status: %s', vname, exc)
            await asyncio.to_thread(update_vehicle_error, pool, vid, 'error')
            await asyncio.to_thread(
                write_journal, pool, vid,
                started, datetime.now(timezone.utc),
                'error', 0, str(exc),
            )
            return

        now = datetime.now(timezone.utc)
        sw_ver = status_data.get('software_version')
        await asyncio.to_thread(update_vehicle_seen, pool, vid, now, sw_ver)
        log.info('[%s] online  sw=%s  db_ok=%s', vname, sw_ver, status_data.get('db_ok'))

        # ── 2. GET /channels (некритично) ──────────────────────────────────────
        try:
            channels = await puller.pull_channels()
            await asyncio.to_thread(upsert_channels, pool, vid, channels)
            log.debug('[%s] channels synced (%d)', vname, len(channels))
        except Exception as exc:
            log.warning('[%s] channels sync failed: %s', vname, exc)

        # ── 3. Визначити вікно pull ────────────────────────────────────────────
        # last_sync_at — timezone-aware datetime з DB або None
        last_sync: datetime | None = vehicle.get('last_sync_at')
        from_ = last_sync if last_sync else now - timedelta(seconds=PULL_WINDOW_SEC)
        to    = now

        # ── 4. GET /data ───────────────────────────────────────────────────────
        try:
            rows = await puller.pull_data(from_, to)
            if rows:
                rows_done = await asyncio.to_thread(write_measurements, pool, vid, rows)
                log.info(
                    '[%s] wrote %d measurements  window=%.0fs',
                    vname, rows_done, (to - from_).total_seconds(),
                )
            # Оновити last_sync_at навіть якщо рядків не було —
            # щоб наступний цикл не повторював те ж саме вікно
            await asyncio.to_thread(update_last_sync_at, pool, vid, to)
        except Exception as exc:
            log.error('[%s] data sync failed: %s', vname, exc)
            # Не оновлюємо last_sync_at — при наступному циклі gap заповниться

        # ── 5. GET /alarms (некритично) ────────────────────────────────────────
        try:
            alarms = await puller.pull_alarms(from_, to)
            if alarms:
                await asyncio.to_thread(upsert_alarms, pool, vid, alarms)
                log.info('[%s] upserted %d alarms', vname, len(alarms))
        except Exception as exc:
            log.warning('[%s] alarms sync failed: %s', vname, exc)

        # ── 6. sync_journal ────────────────────────────────────────────────────
        await asyncio.to_thread(
            write_journal, pool, vid,
            started, datetime.now(timezone.utc),
            'ok', rows_done, None,
        )


# ── Головний цикл ─────────────────────────────────────────────────────────────

async def _run_vehicle_safe(
    vehicle: dict,
    pool: psycopg2.pool.ThreadedConnectionPool,
) -> None:
    """Wrapper для anyio TaskGroup — поглинає виняток щоб не скасувати групу."""
    try:
        await sync_vehicle(vehicle, pool)
    except Exception as exc:
        log.error(
            '[%s] unhandled exception: %s',
            vehicle.get('name', vehicle.get('id', '?')),
            exc,
        )


async def sync_once(pool: psycopg2.pool.ThreadedConnectionPool) -> None:
    """Один прохід: читаємо всі авто з DB і синхронізуємо паралельно."""
    try:
        vehicles = await asyncio.to_thread(get_all_vehicles, pool)
    except Exception as exc:
        log.error('Failed to read vehicles from DB: %s', exc)
        return

    if not vehicles:
        log.info('No vehicles in DB — skipping cycle.')
        return

    log.info('Starting sync cycle for %d vehicle(s)…', len(vehicles))
    # anyio.create_task_group замість asyncio.gather —
    # httpcore обирає anyio-бекенд якщо anyio встановлений;
    # asyncio.gather не ініціалізує anyio-контекст → TCP-з'єднання падають.
    async with anyio.create_task_group() as tg:
        for v in vehicles:
            tg.start_soon(_run_vehicle_safe, v, pool)


async def main() -> None:
    log.info(
        'Sync service starting  interval=%ds  timeout=%gs  window=%ds',
        SYNC_INTERVAL_SEC, PULL_TIMEOUT_SEC, PULL_WINDOW_SEC,
    )
    if not DEFAULT_API_KEY:
        log.warning('VEHICLE_DEFAULT_API_KEY is not set — vehicles without api_key will get 401')

    pool = _build_pool()
    try:
        while True:
            t0 = asyncio.get_event_loop().time()
            await sync_once(pool)
            elapsed = asyncio.get_event_loop().time() - t0
            wait = max(0.0, SYNC_INTERVAL_SEC - elapsed)
            log.info('Cycle done in %.1fs — sleeping %.1fs', elapsed, wait)
            await asyncio.sleep(wait)
    finally:
        pool.closeall()


if __name__ == '__main__':
    # httpcore автоматично обирає AnyIOBackend коли anyio встановлений.
    # anyio.run() ініціалізує потрібний контекст; asyncio.run() — ні.
    # Якщо anyio не встановлений (Docker без uvicorn) — fallback на asyncio.
    try:
        import anyio
        anyio.run(main)
    except ImportError:
        asyncio.run(main())
