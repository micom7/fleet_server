"""
Headless симулятор телеметрії — для Docker / серверного запуску.

Що робить:
  • Ініціалізує channel_config та alarm_rules в telemetry DB (якщо порожні)
  • Генерує реалістичні вимірювання кожні WRITE_INTERVAL_SEC секунд (18 каналів)
  • Генерує/закриває тривоги при перевищенні порогів
  • Виводить статистику в лог кожні LOG_INTERVAL_SEC секунд

Відрізняється від test_server_minimal.py:
  • Без термінального UI
  • Не запускає Outbound API (запускається окремим сервісом у docker-compose)
  • Логування через logging (stdout → docker logs)

Env (з .env або docker-compose environment):
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  WRITE_INTERVAL_SEC  — інтервал запису (за замовч. 2)
  LOG_INTERVAL_SEC    — інтервал статистики в лог (за замовч. 60)
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    stream=sys.stdout,
)
log = logging.getLogger('simulator')

WRITE_INTERVAL_SEC = float(os.getenv('WRITE_INTERVAL_SEC', '2'))
LOG_INTERVAL_SEC   = float(os.getenv('LOG_INTERVAL_SEC', '60'))


# ── DSN ───────────────────────────────────────────────────────────────────────

def _dsn() -> str:
    return (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.getenv('DB_NAME', 'telemetry')} "
        f"user={os.getenv('DB_USER', 'telemetry')} "
        f"password={os.getenv('DB_PASSWORD', 'telemetry123')}"
    )


# ── КАНАЛИ ────────────────────────────────────────────────────────────────────

CHANNELS: list[tuple] = [
    (1,  'et7017_1', 0, 'analog_420', 'Temp Engine',    'C',     6400, 32000,   0.0, 150.0),
    (2,  'et7017_1', 1, 'analog_420', 'Temp Gearbox',   'C',     6400, 32000,   0.0, 120.0),
    (3,  'et7017_1', 2, 'analog_420', 'Oil Pressure',   'bar',   6400, 32000,   0.0,  10.0),
    (4,  'et7017_1', 3, 'analog_420', 'Fuel Pressure',  'bar',   6400, 32000,   0.0,   6.0),
    (5,  'et7017_1', 4, 'analog_420', 'Coolant Level',  '%',     6400, 32000,   0.0, 100.0),
    (6,  'et7017_1', 5, 'analog_420', 'Fuel Level',     '%',     6400, 32000,   0.0, 100.0),
    (7,  'et7017_1', 6, 'analog_420', 'Battery',        'V',     6400, 32000,  10.0,  16.0),
    (8,  'et7017_1', 7, 'analog_420', 'RPM Engine',     'rpm',   6400, 32000,   0.0, 3500.0),
    (9,  'et7017_2', 0, 'analog_420', 'Vibration X',    'mm/s',  6400, 32000,   0.0,  30.0),
    (10, 'et7017_2', 1, 'analog_420', 'Vibration Y',    'mm/s',  6400, 32000,   0.0,  30.0),
    (11, 'et7017_2', 2, 'analog_420', 'Vibration Gear', 'mm/s',  6400, 32000,   0.0,  30.0),
    (12, 'et7017_2', 3, 'analog_420', 'Hydraulic P',    'bar',   6400, 32000,   0.0, 250.0),
    (13, 'et7017_2', 4, 'analog_420', 'Hydraulic Temp', 'C',     6400, 32000,  20.0,  90.0),
    (14, 'et7017_2', 5, 'analog_420', 'Flow Rate',      'L/min', 6400, 32000,   0.0, 200.0),
    (15, 'et7017_2', 6, 'analog_420', 'Load Cell 1',    't',     6400, 32000,   0.0,  50.0),
    (16, 'et7017_2', 7, 'analog_420', 'Load Cell 2',    't',     6400, 32000,   0.0,  50.0),
    (17, 'et7284',   0, 'encoder_counter',   'Position', 'm',    0, 100000, 0.0, 1000.0),
    (18, 'et7284',   4, 'encoder_frequency', 'Speed',    'km/h', 0,   1000, 0.0,   50.0),
]

ALARM_RULES: list[tuple] = [
    (1,  'Engine overtemp',  'above', 130.0, 'critical'),
    (1,  'Engine high temp', 'above', 100.0, 'warning'),
    (3,  'Low oil pressure', 'below',   1.5, 'critical'),
    (6,  'Low fuel level',   'below',  20.0, 'warning'),
    (7,  'Low battery',      'below',  11.5, 'warning'),
    (12, 'Hydraulic overP',  'above', 220.0, 'critical'),
]


# ── СТАН ──────────────────────────────────────────────────────────────────────

class SimState:
    def __init__(self) -> None:
        self.sim_t:         float               = 0.0
        self.values:        dict[int, float]    = {}
        self.total_rows:    int                 = 0
        self.total_alarms:  int                 = 0
        self.active_alarms: dict[tuple, int]    = {}
        self.started_at:    float               = time.monotonic()


STATE = SimState()


# ── ГЕНЕРАЦІЯ ЗНАЧЕНЬ ─────────────────────────────────────────────────────────

def _sim(ch: int, t: float) -> float:
    S   = math.sin
    rng = random.gauss
    if ch == 1:  return 80  + 10 * S(t/120) + rng(0, 0.3)
    if ch == 2:  return 65  +  8 * S(t/150) + rng(0, 0.2)
    if ch == 3:  return 4.0 + 0.8 * S(t/30)  + rng(0, 0.05)
    if ch == 4:  return 3.5 + 0.3 * S(t/20)  + rng(0, 0.02)
    if ch == 5:  return 90  +  3 * S(t/200) + rng(0, 0.1)
    if ch == 6:  return max(5.0, 80 - (t / 3600) * 15) + rng(0, 0.1)
    if ch == 7:  return 13.8 + 0.3 * S(t/60)  + rng(0, 0.02)
    if ch == 8:  return 1500 + 80  * S(t/45)  + rng(0, 5)
    if ch in (9, 10):
        return max(0, 2.5 + 1.5 * abs(S(t/90)) + (5 if random.random() < 0.02 else 0) + rng(0, 0.1))
    if ch == 11: return max(0, 3.0 + 2.0 * abs(S(t/110)) + rng(0, 0.15))
    if ch == 12: return 165 + 15  * S(t/25)  + rng(0, 0.5)
    if ch == 13: return 55  +  8  * S(t/130) + rng(0, 0.2)
    if ch == 14: return 100 + 20  * S(t/35)  + rng(0, 0.5)
    if ch in (15, 16):
        return 20 + 8 * S(t/55 + (0 if ch == 15 else 1.2)) + rng(0, 0.1)
    if ch == 17: return (t * 0.5) % 1000
    if ch == 18: return max(0, 10 + 5 * S(t/40) + rng(0, 0.2))
    return 0.0


# ── ІНІЦІАЛІЗАЦІЯ БД ──────────────────────────────────────────────────────────

def db_init() -> None:
    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM channel_config')
            if cur.fetchone()[0] == 0:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO channel_config
                        (channel_id, module, channel_index, signal_type,
                         name, unit, raw_min, raw_max, phys_min, phys_max)
                    VALUES %s ON CONFLICT DO NOTHING
                """, [(c[0],c[1],c[2],c[3],c[4],c[5],c[6],c[7],c[8],c[9]) for c in CHANNELS])
                log.info('Inserted %d channels', len(CHANNELS))

            cur.execute('SELECT COUNT(*) FROM alarm_rules')
            if cur.fetchone()[0] == 0:
                for (ch, name, rtype, thr, sev) in ALARM_RULES:
                    cur.execute("""
                        INSERT INTO alarm_rules
                            (channel_id, name, rule_type, threshold, severity)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (ch, name, rtype, thr, sev))
                log.info('Inserted %d alarm rules', len(ALARM_RULES))
        conn.commit()
    finally:
        conn.close()


# ── ЗАПИС ВИМІРЮВАНЬ ──────────────────────────────────────────────────────────

def write_measurements(conn: psycopg2.extensions.connection) -> None:
    now  = datetime.now(timezone.utc)
    rows = []
    for c in CHANNELS:
        ch_id = c[0]
        val   = _sim(ch_id, STATE.sim_t)
        STATE.values[ch_id] = val
        rows.append((now, ch_id, val))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, 'INSERT INTO measurements (time, channel_id, value) VALUES %s', rows
        )
    conn.commit()
    STATE.total_rows += len(rows)


def check_alarms(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT id, channel_id, name, rule_type, threshold, severity '
                    'FROM alarm_rules WHERE enabled = TRUE')
        rules = cur.fetchall()

    now = datetime.now(timezone.utc)
    for r in rules:
        ch_id = r['channel_id']
        val   = STATE.values.get(ch_id)
        if val is None:
            continue
        key   = (r['id'], ch_id)
        fired = (
            (r['rule_type'] == 'above' and val > r['threshold']) or
            (r['rule_type'] == 'below' and val < r['threshold'])
        )
        if fired and key not in STATE.active_alarms:
            msg = (f"{r['name']}: {val:.2f} "
                   f"{'>' if r['rule_type']=='above' else '<'} {r['threshold']}")
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alarms_log
                        (rule_id, channel_id, triggered_at, value, message)
                    VALUES (%s,%s,%s,%s,%s) RETURNING id
                """, (r['id'], ch_id, now, val, msg))
                STATE.active_alarms[key] = cur.fetchone()[0]
            conn.commit()
            STATE.total_alarms += 1
            log.warning('ALARM triggered: %s', msg)

        elif not fired and key in STATE.active_alarms:
            alarm_id = STATE.active_alarms.pop(key)
            with conn.cursor() as cur:
                cur.execute('UPDATE alarms_log SET resolved_at=%s WHERE id=%s',
                            (now, alarm_id))
            conn.commit()
            log.info('Alarm #%d resolved (ch=%d)', alarm_id, ch_id)


# ── ASYNC TASKS ───────────────────────────────────────────────────────────────

async def data_loop(interval: float = WRITE_INTERVAL_SEC) -> None:
    conn = psycopg2.connect(_dsn())
    try:
        while True:
            t0 = asyncio.get_event_loop().time()
            write_measurements(conn)
            check_alarms(conn)
            STATE.sim_t += interval
            elapsed = asyncio.get_event_loop().time() - t0
            await asyncio.sleep(max(0.05, interval - elapsed))
    finally:
        conn.close()


async def stats_loop(interval: float = LOG_INTERVAL_SEC) -> None:
    while True:
        await asyncio.sleep(interval)
        up = int(time.monotonic() - STATE.started_at)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        log.info(
            'uptime=%02d:%02d:%02d  rows=%d  alarms_total=%d  alarms_active=%d',
            h, m, s, STATE.total_rows, STATE.total_alarms, len(STATE.active_alarms),
        )


async def async_main() -> None:
    tasks = [
        asyncio.create_task(data_loop()),
        asyncio.create_task(stats_loop()),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info('Auto Telemetry Headless Simulator starting')
    log.info('DB: %s', _dsn())

    # Чекаємо БД (корисно при старті Docker — postgres може ще ініціалізуватись)
    for attempt in range(30):
        try:
            conn = psycopg2.connect(_dsn())
            conn.close()
            log.info('DB connection OK')
            break
        except Exception as e:
            log.warning('DB not ready (attempt %d/30): %s', attempt + 1, e)
            time.sleep(2)
    else:
        log.error('DB connection failed after 30 attempts — exiting')
        sys.exit(1)

    log.info('Initializing channel config and alarm rules...')
    try:
        db_init()
    except Exception as e:
        log.error('DB init failed: %s', e)
        sys.exit(1)

    log.info(
        'Starting simulation: %d channels, interval=%.1fs, log_interval=%.0fs',
        len(CHANNELS), WRITE_INTERVAL_SEC, LOG_INTERVAL_SEC,
    )
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        log.info('Simulator stopped')


if __name__ == '__main__':
    main()
