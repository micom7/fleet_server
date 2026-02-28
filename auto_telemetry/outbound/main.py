"""
Outbound API — інтерфейс для Fleet Server (pull-модель).

Порт: 8001
Запуск:
    python -m uvicorn outbound.main:app --host 0.0.0.0 --port 8001

Контракт: DATA_CONTRACT.md (корінь монорепо)
"""

import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / '.env')

app = FastAPI(title="Auto Telemetry Outbound API", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=500)

_START = time.monotonic()

# ── Конфігурація ─────────────────────────────────────────────────────────────

API_KEY         = os.getenv('OUTBOUND_API_KEY', '')
VEHICLE_ID_HINT = os.getenv('VEHICLE_ID_HINT', 'unknown')

# Порт ZeroMQ PUB колектора — якщо щось слухає, колектор запущений
_zmq_pub       = os.getenv('ZMQ_COLLECTOR_PUB', 'tcp://127.0.0.1:5555')
_COLLECTOR_PORT = int(_zmq_pub.rsplit(':', 1)[-1])
_AGENT_PORT     = 9876


# ── Утиліти ──────────────────────────────────────────────────────────────────

def _check_key(x_api_key: str = Header(...)) -> None:
    """Перевірка API-ключа. 401 якщо відсутній або невірний."""
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


AUTH = Depends(_check_key)


def _dsn() -> str:
    return (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.getenv('DB_NAME', 'telemetry')} "
        f"user={os.getenv('DB_USER', 'telemetry')} "
        f"password={os.getenv('DB_PASSWORD', '')}"
    )


def _conn():
    """Відкриває з'єднання з БД. 503 якщо недоступна."""
    try:
        return psycopg2.connect(_dsn())
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


def _port_listening(port: int) -> bool:
    """Повертає True якщо на localhost:port щось слухає."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _read_version() -> str:
    try:
        return (_ROOT / 'version.txt').read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return 'unknown'


def _fmt(dt: datetime | None) -> str | None:
    """datetime → ISO8601 UTC рядок з міліскундами, або None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


# ── Ендпоінти ─────────────────────────────────────────────────────────────────

@app.get('/status')
def status(_: None = AUTH):
    """Стан машини та мета-інформація."""
    db_ok = True
    last_measurement_at = None
    try:
        conn = psycopg2.connect(_dsn())
        with conn.cursor() as cur:
            cur.execute('SELECT MAX(time) FROM measurements')
            last_measurement_at = cur.fetchone()[0]
        conn.close()
    except Exception:
        db_ok = False

    return {
        'vehicle_id_hint':    VEHICLE_ID_HINT,
        'software_version':   _read_version(),
        'uptime_sec':         int(time.monotonic() - _START),
        'collector_running':  _port_listening(_COLLECTOR_PORT),
        'agent_running':      _port_listening(_AGENT_PORT),
        'db_ok':              db_ok,
        'last_measurement_at': _fmt(last_measurement_at),
    }


@app.get('/channels')
def channels(_: None = AUTH):
    """Конфігурація каналів."""
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT channel_id, name, unit,
                       raw_min, raw_max, phys_min, phys_max,
                       signal_type, enabled, updated_at
                FROM channel_config
                ORDER BY channel_id
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            'channel_id':  r['channel_id'],
            'name':        r['name'],
            'unit':        r['unit'],
            'raw_min':     r['raw_min'],
            'raw_max':     r['raw_max'],
            'phys_min':    r['phys_min'],
            'phys_max':    r['phys_max'],
            'signal_type': r['signal_type'],
            'enabled':     r['enabled'],
            'updated_at':  _fmt(r['updated_at']),
        }
        for r in rows
    ]


@app.get('/data/latest')
def data_latest(_: None = AUTH):
    """Останнє значення по кожному каналу."""
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT ON (channel_id)
                    channel_id, value, time
                FROM measurements
                ORDER BY channel_id, time DESC
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            'channel_id': r['channel_id'],
            'value':      r['value'],
            'time':       _fmt(r['time']),
        }
        for r in rows
    ]


@app.get('/data')
def data(
    from_:      datetime   = Query(..., alias='from'),
    to:         datetime   = Query(...),
    channel_id: int | None = Query(None),
    limit:      int        = Query(10000, le=50000),
    _:          None       = AUTH,
):
    """Вимірювання за часовим діапазоном."""
    if from_ >= to:
        raise HTTPException(
            status_code=400,
            detail={'error': 'invalid_params', 'detail': 'from must be before to'},
        )

    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params: dict = {'from_': from_, 'to': to, 'limit': limit + 1}
            ch_filter = ''
            if channel_id is not None:
                ch_filter = 'AND channel_id = %(channel_id)s'
                params['channel_id'] = channel_id

            cur.execute(f"""
                SELECT channel_id, value, time
                FROM measurements
                WHERE time >= %(from_)s AND time < %(to)s
                {ch_filter}
                ORDER BY time ASC
                LIMIT %(limit)s
            """, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return {
        'from':      _fmt(from_),
        'to':        _fmt(to),
        'count':     len(rows),
        'truncated': truncated,
        'rows': [
            {
                'channel_id': r['channel_id'],
                'value':      r['value'],
                'time':       _fmt(r['time']),
            }
            for r in rows
        ],
    }


@app.get('/alarms')
def alarms(
    from_:           datetime = Query(..., alias='from'),
    to:              datetime = Query(...),
    unresolved_only: bool     = Query(False),
    _:               None     = AUTH,
):
    """Тривоги за часовим діапазоном."""
    if from_ >= to:
        raise HTTPException(
            status_code=400,
            detail={'error': 'invalid_params', 'detail': 'from must be before to'},
        )

    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            extra = 'AND al.resolved_at IS NULL' if unresolved_only else ''
            cur.execute(f"""
                SELECT
                    al.id          AS alarm_id,
                    al.channel_id,
                    ar.severity,
                    al.message,
                    al.triggered_at,
                    al.resolved_at
                FROM alarms_log al
                LEFT JOIN alarm_rules ar ON ar.id = al.rule_id
                WHERE (
                    al.triggered_at >= %(from_)s AND al.triggered_at < %(to)s
                    OR al.resolved_at >= %(from_)s AND al.resolved_at < %(to)s
                )
                {extra}
                ORDER BY al.triggered_at ASC
            """, {'from_': from_, 'to': to})
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            'alarm_id':    r['alarm_id'],
            'channel_id':  r['channel_id'],
            'severity':    r['severity'],
            'message':     r['message'],
            'triggered_at': _fmt(r['triggered_at']),
            'resolved_at':  _fmt(r['resolved_at']),
        }
        for r in rows
    ]
