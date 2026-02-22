"""
Portal — операторський інтерфейс.

Запуск: uvicorn portal.main:app --reload --port 8100
"""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg2
import zmq.asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv()

CONFIG_PIN = os.getenv("CONFIG_PIN", "1234")

# ── In-memory стан ─────────────────────────────────────────────────────────────

current_values: dict[int, dict] = {}   # channel_id → {value, time}
channel_meta: dict[int, dict] = {}     # channel_id → {name, unit}
sse_clients: list[asyncio.Queue] = []


# ── DB ─────────────────────────────────────────────────────────────────────────

def _dsn() -> str:
    return (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.getenv('DB_NAME', 'telemetry')} "
        f"user={os.getenv('DB_USER', 'telemetry')} "
        f"password={os.getenv('DB_PASSWORD', '')}"
    )


def load_channel_meta() -> None:
    """Завантажує назви та одиниці каналів з БД."""
    try:
        conn = psycopg2.connect(_dsn())
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_id, name, unit FROM channel_config "
            "WHERE enabled ORDER BY channel_id"
        )
        for channel_id, name, unit in cur.fetchall():
            channel_meta[channel_id] = {"name": name, "unit": unit or ""}
        conn.close()
    except Exception as e:
        print(f"[portal] DB помилка при завантаженні каналів: {e}")


# ── ZeroMQ listener ────────────────────────────────────────────────────────────

def _build_snapshot() -> str:
    rows = []
    for cid in sorted(current_values):
        meta = channel_meta.get(cid, {"name": f"CH{cid}", "unit": ""})
        v = current_values[cid]
        val = v["value"]
        rows.append({
            "channel_id": cid,
            "name": meta["name"],
            "value": round(val, 3) if val is not None else None,
            "unit": meta["unit"],
            "time": v["time"],
        })
    return json.dumps(rows)


async def zmq_listener() -> None:
    """Фонова задача: ZeroMQ SUB → current_values → SSE клієнти."""
    zmq_addr = os.getenv("ZMQ_COLLECTOR_PUB", "tcp://127.0.0.1:5555")
    ctx = zmq.asyncio.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.connect(zmq_addr)
    sock.setsockopt(zmq.SUBSCRIBE, b"data")
    print(f"[portal] ZeroMQ SUB підключено до {zmq_addr}")

    while True:
        try:
            parts = await sock.recv_multipart()
            payload = json.loads(parts[1])
            for r in payload["readings"]:
                current_values[r["channel_id"]] = {
                    "value": r["value"],
                    "time": payload["cycle_time"],
                }
            snapshot = _build_snapshot()
            for q in sse_clients:
                await q.put(snapshot)
        except Exception as e:
            print(f"[portal] ZeroMQ помилка: {e}")
            await asyncio.sleep(1)


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_channel_meta()
    asyncio.create_task(zmq_listener())
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="portal/templates")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Configs API ────────────────────────────────────────────────────────────────

class ChannelUpdate(BaseModel):
    name: str
    unit: str
    raw_min: float
    raw_max: float
    phys_min: float
    phys_max: float
    enabled: bool
    pin: str


@app.get("/api/channels")
async def get_channels():
    try:
        conn = psycopg2.connect(_dsn())
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_id, module, channel_index, signal_type, name, unit, "
            "raw_min, raw_max, phys_min, phys_max, enabled "
            "FROM channel_config ORDER BY channel_id"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/channels/{channel_id}")
async def update_channel(channel_id: int, update: ChannelUpdate):
    if update.pin != CONFIG_PIN:
        raise HTTPException(status_code=403, detail="Невірний PIN")
    if update.raw_max == update.raw_min:
        raise HTTPException(status_code=422, detail="raw_max не може дорівнювати raw_min")
    try:
        conn = psycopg2.connect(_dsn())
        cur = conn.cursor()
        cur.execute(
            "UPDATE channel_config SET name=%s, unit=%s, raw_min=%s, raw_max=%s, "
            "phys_min=%s, phys_max=%s, enabled=%s WHERE channel_id=%s",
            (update.name, update.unit, update.raw_min, update.raw_max,
             update.phys_min, update.phys_max, update.enabled, channel_id)
        )
        conn.commit()
        conn.close()
        channel_meta[channel_id] = {"name": update.name, "unit": update.unit or ""}
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stream")
async def stream(request: Request):
    """SSE endpoint — пуш поточних значень у браузер."""
    q: asyncio.Queue = asyncio.Queue()
    sse_clients.append(q)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=5.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            sse_clients.remove(q)

    return StreamingResponse(generator(), media_type="text/event-stream")
