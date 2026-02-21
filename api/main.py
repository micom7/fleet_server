from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import close_pool, init_pool
from routes.auth import router as auth_router
from routes.vehicles import router as vehicles_router
from routes.admin import router as admin_router
from routes.ws_live import router as ws_router
from routes.web import router as web_router

STATIC_DIR = Path(__file__).parent.parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    yield
    close_pool()


app = FastAPI(
    title="Fleet Server API",
    version="1.0.0",
    description="Центральний сервер телеметрії автопарку",
    lifespan=lifespan,
)

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
