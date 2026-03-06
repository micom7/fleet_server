"""T1 — Smoke tests: auth (login / logout / refresh / статуси)"""
from conftest import api_login, db_create_user, db_delete_user, rand_email


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_success(client, active_owner):
    r = client.post("/auth/login", json={
        "email": active_owner["email"],
        "password": active_owner["password"],
    })
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password(client, active_owner):
    r = client.post("/auth/login", json={
        "email": active_owner["email"],
        "password": "WrongPassword!",
    })
    assert r.status_code == 401


def test_login_unknown_email(client):
    r = client.post("/auth/login", json={
        "email": rand_email(),
        "password": "SomePass1!",
    })
    assert r.status_code == 401


def test_login_blocked_user(client, blocked_user):
    r = client.post("/auth/login", json={
        "email": blocked_user["email"],
        "password": blocked_user["password"],
    })
    assert r.status_code == 403


# ── Статус pending/blocked при доступі до захищених маршрутів ─────────────────

def test_pending_user_cannot_access_vehicles(client, pending_user):
    token = api_login(client, pending_user["email"], pending_user["password"])
    r = client.get("/api/vehicles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_active_user_can_access_vehicles(client, active_owner):
    token = api_login(client, active_owner["email"], active_owner["password"])
    r = client.get("/api/vehicles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_no_token_returns_401(client):
    r = client.get("/api/vehicles")
    assert r.status_code == 401


# ── Refresh ────────────────────────────────────────────────────────────────────

def test_refresh_returns_new_access_token(client, active_owner):
    # login — отримуємо access + refresh cookie
    login_r = client.post("/auth/login", json={
        "email": active_owner["email"],
        "password": active_owner["password"],
    })
    assert login_r.status_code == 200
    assert "refresh_token" in login_r.cookies

    # використовуємо refresh cookie
    refresh_r = client.post("/auth/refresh", cookies=login_r.cookies)
    assert refresh_r.status_code == 200
    assert "access_token" in refresh_r.json()


def test_refresh_without_cookie_returns_401(client):
    r = client.post("/auth/refresh")
    assert r.status_code == 401


# ── Logout + revocation ────────────────────────────────────────────────────────

def test_logout_revokes_refresh_token(client, active_owner):
    # Один login — access + refresh в одній сесії
    login_r = client.post("/auth/login", json={
        "email": active_owner["email"],
        "password": active_owner["password"],
    })
    assert login_r.status_code == 200
    token = login_r.json()["access_token"]
    # Зберігаємо значення refresh_token до logout (потім буде видалено з client.cookies)
    refresh_value = client.cookies.get("refresh_token")

    # logout — JTI потрапляє в revoked_tokens, cookie видаляється
    logout_r = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_r.status_code == 200

    # Відновлюємо анульований токен і перевіряємо що /refresh його відхиляє
    client.cookies.set("refresh_token", refresh_value)
    refresh_r = client.post("/auth/refresh")
    assert refresh_r.status_code == 401

    # Прибираємо тестовий cookie зі сесії
    client.cookies.delete("refresh_token")


# ── /auth/me ───────────────────────────────────────────────────────────────────

def test_me_returns_current_user(client, active_owner):
    token = api_login(client, active_owner["email"], active_owner["password"])
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == active_owner["email"]
    assert data["role"] == "owner"
    assert data["status"] == "active"
