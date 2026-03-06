import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import close_pool, get_conn, init_pool
from routes.auth import router as auth_router
from routes.vehicles import router as vehicles_router
from routes.admin import router as admin_router
from routes.ws_live import router as ws_router
from routes.web import router as web_router

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "web" / "static"
CLEANUP_INTERVAL_SEC = 3600  # раз на годину


def _ensure_partitions() -> None:
    """Створює партиції measurements на поточний і наступний місяць якщо їх немає."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DO $$
                DECLARE
                    m      DATE;
                    m_next DATE;
                    tname  TEXT;
                BEGIN
                    FOR offset IN 0..1 LOOP
                        m      := date_trunc('month', now() + (offset || ' months')::INTERVAL)::DATE;
                        m_next := (m + INTERVAL '1 month')::DATE;
                        tname  := 'measurements_' || to_char(m, 'YYYY_MM');
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_class WHERE relname = tname
                        ) THEN
                            EXECUTE format(
                                'CREATE TABLE %I PARTITION OF measurements
                                 FOR VALUES FROM (%L) TO (%L)',
                                tname, m, m_next
                            );
                        END IF;
                    END LOOP;
                END $$
            """)


def _run_cleanup() -> tuple[int, int]:
    _ensure_partitions()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM revoked_tokens WHERE expires_at < now()")
            tokens_deleted = cur.rowcount
            cur.execute("DELETE FROM sync_journal WHERE started_at < now() - INTERVAL '30 days'")
            journal_deleted = cur.rowcount
    return tokens_deleted, journal_deleted


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SEC)
        try:
            tokens, journal = await asyncio.to_thread(_run_cleanup)
            if tokens or journal:
                logger.info("Cleanup: revoked_tokens=%d, sync_journal=%d", tokens, journal)
        except Exception:
            logger.exception("Cleanup task failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    close_pool()


app = FastAPI(
    title="Fleet Server API",
    version="1.0.0",
    description="Центральний сервер телеметрії автопарку",
    lifespan=lifespan,
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/static") and path != "/health":
        ms = (time.monotonic() - start) * 1000
        logger.info("%s %s %d %.0fms", request.method, path, response.status_code, ms)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: в продакшні замінити на конкретний домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(vehicles_router)
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(web_router)

# Static files (CSS, JS, images)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
