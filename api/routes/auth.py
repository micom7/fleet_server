import secrets
from collections import defaultdict
from datetime import datetime, timedelta

import psycopg2.extras
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError

from auth import (
    create_access_token, create_refresh_token, decode_token,
    google_auth_url, google_exchange_code,
    hash_password, verify_password,
)
from config import settings
from database import get_conn
from dependencies import AuthUser, get_current_user
from mailer import send_email
from models.user import TokenOut, UserLogin, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Rate limiter для login (in-memory, per IP) ────────────────────────────────
_login_attempts: dict[str, list[datetime]] = defaultdict(list)


def _check_rate_limit(ip: str, max_attempts: int = 5, window: int = 60) -> None:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=window)
    recent = [t for t in _login_attempts[ip] if t > cutoff]
    _login_attempts[ip] = recent
    if len(recent) >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Забагато спроб входу. Спробуйте за хвилину.",
        )
    _login_attempts[ip].append(now)


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: UserRegister, background_tasks: BackgroundTasks) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email вже зареєстровано",
                )
            cur.execute(
                """
                INSERT INTO users (email, password_hash, role, status, full_name)
                VALUES (%s, %s, 'owner', 'pending', %s)
                RETURNING id
                """,
                (body.email, hash_password(body.password), body.full_name),
            )
            user_id = str(cur.fetchone()["id"])

            # Збираємо email'и superuser'ів для сповіщення
            cur.execute(
                "SELECT email FROM users WHERE role = 'superuser' AND status = 'active'"
            )
            superuser_emails = [r["email"] for r in cur.fetchall()]

    for email_addr in superuser_emails:
        background_tasks.add_task(
            send_email,
            email_addr,
            "Fleet: нова реєстрація",
            f"<p>Новий користувач <b>{body.email}</b> очікує підтвердження.</p>",
        )

    return {
        "message": "Реєстрація успішна. Очікуйте підтвердження адміністратора.",
        "user_id": user_id,
    }


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login")
def login(body: UserLogin, request: Request, response: Response) -> TokenOut:
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, password_hash, role, status FROM users WHERE email = %s",
                (body.email,),
            )
            user = cur.fetchone()

    if not user or not user["password_hash"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невірний email або пароль",
        )
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невірний email або пароль",
        )
    if user["status"] == "blocked":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Акаунт заблоковано")

    access_token = create_access_token(str(user["id"]), user["role"])
    refresh_token, _ = create_refresh_token(str(user["id"]))

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,   # True в продакшні
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/auth/refresh",
    )
    return TokenOut(access_token=access_token)


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh")
def refresh(response: Response, refresh_token: str | None = Cookie(default=None)) -> TokenOut:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невірний токен")
    if not refresh_token:
        raise exc
    try:
        payload = decode_token(refresh_token)
    except JWTError:
        raise exc

    if payload.get("type") != "refresh":
        raise exc

    jti     = payload.get("jti")
    user_id = payload.get("sub")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM revoked_tokens WHERE jti = %s", (jti,))
            if cur.fetchone():
                raise exc
            cur.execute("SELECT id, role, status FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()

    if not user or user["status"] != "active":
        raise exc

    return TokenOut(access_token=create_access_token(str(user["id"]), user["role"]))


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout")
def logout(
    response: Response,
    current_user: AuthUser = Depends(get_current_user),
    refresh_token: str | None = Cookie(default=None),
) -> dict:
    if refresh_token:
        try:
            payload = decode_token(refresh_token)
            jti = payload.get("jti")
            exp = datetime.utcfromtimestamp(payload["exp"])
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO revoked_tokens (jti, user_id, expires_at) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (jti, str(current_user.id), exp),
                    )
        except Exception:
            pass  # Не падаємо — просто видаляємо cookie

    response.delete_cookie(key="refresh_token", path="/auth/refresh")
    return {"message": "Вихід виконано"}


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me")
def me(current_user: AuthUser = Depends(get_current_user)) -> dict:
    return {
        "id":        str(current_user.id),
        "email":     current_user.email,
        "role":      current_user.role,
        "status":    current_user.status,
        "full_name": current_user.full_name,
    }


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/google")
def google_login(response: Response) -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth не налаштовано")
    state = secrets.token_urlsafe(16)
    response.set_cookie("oauth_state", state, httponly=True, secure=False, max_age=300)
    return RedirectResponse(url=google_auth_url(state))


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    response: Response,
    oauth_state: str | None = Cookie(default=None),
) -> TokenOut:
    if not oauth_state or oauth_state != state:
        raise HTTPException(status_code=400, detail="Невірний state параметр")
    response.delete_cookie("oauth_state")

    try:
        user_info = await google_exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="Помилка авторизації через Google")

    google_sub = user_info["sub"]
    email      = user_info["email"]
    full_name  = user_info.get("name")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Шукаємо існуючий OAuth зв'язок
            cur.execute(
                """
                SELECT u.id, u.role, u.status
                FROM oauth_accounts oa
                JOIN users u ON u.id = oa.user_id
                WHERE oa.provider = 'google' AND oa.provider_uid = %s
                """,
                (google_sub,),
            )
            user = cur.fetchone()

            if not user:
                # Перевіряємо чи існує email (зв'язуємо акаунти)
                cur.execute("SELECT id, role, status FROM users WHERE email = %s", (email,))
                user = cur.fetchone()
                if user:
                    cur.execute(
                        "INSERT INTO oauth_accounts (user_id, provider, provider_uid) "
                        "VALUES (%s, 'google', %s)",
                        (str(user["id"]), google_sub),
                    )
                else:
                    # Новий користувач
                    cur.execute(
                        """
                        INSERT INTO users (email, role, status, full_name)
                        VALUES (%s, 'owner', 'pending', %s)
                        RETURNING id, role, status
                        """,
                        (email, full_name),
                    )
                    user = cur.fetchone()
                    cur.execute(
                        "INSERT INTO oauth_accounts (user_id, provider, provider_uid) "
                        "VALUES (%s, 'google', %s)",
                        (str(user["id"]), google_sub),
                    )

    if user["status"] == "blocked":
        raise HTTPException(status_code=403, detail="Акаунт заблоковано")

    access_token   = create_access_token(str(user["id"]), user["role"])
    refresh_token_val, _ = create_refresh_token(str(user["id"]))

    response.set_cookie(
        key="refresh_token",
        value=refresh_token_val,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/auth/refresh",
    )
    return TokenOut(access_token=access_token)
