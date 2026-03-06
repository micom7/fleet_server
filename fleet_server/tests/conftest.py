"""
Smoke tests — Fleet Server API

Запуск (з fleet_server/):
    pip install -r tests/requirements-test.txt
    pytest tests/ -v

Потребує запущеного PostgreSQL з ініціалізованою БД fleet.
Змінні середовища читаються з fleet_server/.env (або ENV).
"""
import os
import sys
import uuid

# Додаємо api/ і sync/ до шляху пошуку модулів
# _BASE = fleet_server/ (локально) або /app (в контейнері де api/* лежить прямо в _BASE)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_API  = os.path.join(_BASE, "api")
_SYNC = os.path.join(_BASE, "sync")

# api/ — найвищий пріоритет (щоб main.py звідси, а не з sync/)
sys.path.insert(0, _SYNC)
sys.path.insert(0, _API)
sys.path.insert(0, _BASE)  # для контейнера де api-файли лежать прямо в /app

# Для тестів вимикаємо secure cookies (немає HTTPS локально)
os.environ["COOKIE_SECURE"] = "false"
# JWT_SECRET для тестів — якщо не задано у .env
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production-only")

import pytest
from fastapi.testclient import TestClient

# Імпорт після маніпуляцій із sys.path та os.environ
from auth import hash_password
from database import get_conn
from main import app


# ── Скидаємо in-memory rate limiter перед кожним тестом ──────────────────────
@pytest.fixture(autouse=True)
def clear_rate_limiter():
    from routes.auth import _login_attempts
    _login_attempts.clear()


# ── TestClient (сесійний, запускає lifespan → init_pool) ─────────────────────

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────

def rand_email() -> str:
    return f"test_{uuid.uuid4().hex[:10]}@test.local"


def db_create_user(email: str, password: str, role: str, status: str) -> str:
    """Вставляє юзера напряму в БД. Повертає id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, role, status, full_name) "
                "VALUES (%s, %s, %s, %s, 'Test User') RETURNING id",
                (email, hash_password(password), role, status),
            )
            return str(cur.fetchone()[0])


def db_delete_user(user_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


def db_create_vehicle(name: str, vpn_ip: str) -> str:
    """Вставляє авто через RLS-контекст superuser. Повертає id."""
    with get_conn(user_id="00000000-0000-0000-0000-000000000001", user_role="superuser") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO vehicles (name, vpn_ip, api_port) "
                "VALUES (%s, %s::inet, 8001) RETURNING id",
                (name, vpn_ip),
            )
            return str(cur.fetchone()[0])


def db_delete_vehicle(vehicle_id: str) -> None:
    with get_conn(user_id="00000000-0000-0000-0000-000000000001", user_role="superuser") as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vehicles WHERE id = %s", (vehicle_id,))


def db_assign_vehicle(user_id: str, vehicle_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO vehicle_access (user_id, vehicle_id) VALUES (%s, %s)",
                (user_id, vehicle_id),
            )


def api_login(client: TestClient, email: str, password: str) -> str:
    """Логінимось і повертаємо access_token."""
    r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def active_owner(client):
    email, pw = rand_email(), "TestPass1!"
    uid = db_create_user(email, pw, "owner", "active")
    yield {"email": email, "password": pw, "id": uid}
    db_delete_user(uid)


@pytest.fixture
def active_superuser(client):
    email, pw = rand_email(), "TestPass1!"
    uid = db_create_user(email, pw, "superuser", "active")
    yield {"email": email, "password": pw, "id": uid}
    db_delete_user(uid)


@pytest.fixture
def pending_user(client):
    email, pw = rand_email(), "TestPass1!"
    uid = db_create_user(email, pw, "owner", "pending")
    yield {"email": email, "password": pw, "id": uid}
    db_delete_user(uid)


@pytest.fixture
def blocked_user(client):
    email, pw = rand_email(), "TestPass1!"
    uid = db_create_user(email, pw, "owner", "blocked")
    yield {"email": email, "password": pw, "id": uid}
    db_delete_user(uid)
