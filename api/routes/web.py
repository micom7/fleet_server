import datetime as dt
from pathlib import Path

import psycopg2.extras
from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from database import get_conn
from dependencies import AuthUser, _fetch_user

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def _user_from_cookie(access_token: str | None) -> AuthUser | None:
    if not access_token:
        return None
    try:
        payload = decode_token(access_token)
        if payload.get("type") != "access":
            return None
        user = _fetch_user(payload["sub"])
        return user if user and user.status == "active" else None
    except Exception:
        return None


def _set_auth_cookies(resp: RedirectResponse, user_id: str, role: str) -> None:
    access_token = create_access_token(user_id, role)
    refresh_token, _ = create_refresh_token(user_id)
    resp.set_cookie("access_token", access_token,
                    httponly=False, samesite="lax", max_age=900)
    resp.set_cookie("refresh_token", refresh_token,
                    httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_vehicles(user: AuthUser) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    with get_conn(str(user.id), user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user.role == "owner":
                cur.execute(
                    "SELECT v.id, v.name, host(v.vpn_ip) AS vpn_ip, v.api_port, "
                    "v.last_seen_at, v.sync_status "
                    "FROM vehicles v "
                    "JOIN vehicle_access va ON va.vehicle_id = v.id "
                    "WHERE va.user_id = %s "
                    "ORDER BY v.name",
                    (str(user.id),),
                )
            else:
                cur.execute(
                    "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, last_seen_at, sync_status "
                    "FROM vehicles ORDER BY name"
                )
            rows = cur.fetchall()
    result = []
    for r in rows:
        r = dict(r)
        last_seen = r["last_seen_at"]
        r["online"] = bool(last_seen and (now - last_seen).total_seconds() < 120)
        result.append(r)
    return result


def _get_vehicle(vehicle_id: str, user: AuthUser) -> dict | None:
    now = dt.datetime.now(dt.timezone.utc)
    with get_conn(str(user.id), user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user.role == "owner":
                cur.execute(
                    "SELECT v.id, v.name, host(v.vpn_ip) AS vpn_ip, v.api_port, "
                    "v.last_seen_at, v.sync_status "
                    "FROM vehicles v "
                    "JOIN vehicle_access va ON va.vehicle_id = v.id "
                    "WHERE v.id = %s AND va.user_id = %s",
                    (vehicle_id, str(user.id)),
                )
            else:
                cur.execute(
                    "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, last_seen_at, sync_status "
                    "FROM vehicles WHERE id = %s",
                    (vehicle_id,),
                )
            row = cur.fetchone()
    if not row:
        return None
    r = dict(row)
    last_seen = r["last_seen_at"]
    r["online"] = bool(last_seen and (now - last_seen).total_seconds() < 120)
    return r


def _get_alarms(vehicle_id: str, user: AuthUser) -> list[dict]:
    with get_conn(str(user.id), user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user.role == "owner":
                cur.execute(
                    "SELECT 1 FROM vehicle_access WHERE vehicle_id = %s AND user_id = %s",
                    (vehicle_id, str(user.id)),
                )
                if not cur.fetchone():
                    return []
            cur.execute(
                "SELECT id, alarm_id, severity, message, triggered_at "
                "FROM alarms_log WHERE vehicle_id = %s AND resolved_at IS NULL "
                "ORDER BY triggered_at DESC LIMIT 20",
                (vehicle_id,),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Public pages ──────────────────────────────────────────────────────────────

@router.get("/")
def index(access_token: str | None = Cookie(default=None)):
    return RedirectResponse(
        url="/fleet" if _user_from_cookie(access_token) else "/login",
        status_code=302,
    )


@router.get("/login")
def login_page(
    request: Request,
    error: str | None = None,
    msg: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if _user_from_cookie(access_token):
        return RedirectResponse(url="/fleet", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request, "user": None,
        "error": error, "msg": msg, "show_register": False, "show_demo": False,
    })


@router.post("/login")
def login_submit(
    email: str = Form(...),
    password: str = Form(...),
):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, password_hash, role, status FROM users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()

    if not user or not user["password_hash"] or not verify_password(password, user["password_hash"]):
        return RedirectResponse(url="/login?error=Невірний+email+або+пароль", status_code=302)
    if user["status"] == "blocked":
        return RedirectResponse(url="/login?error=Акаунт+заблоковано", status_code=302)
    if user["status"] == "pending":
        return RedirectResponse(
            url="/login?msg=Акаунт+очікує+підтвердження+адміністратора",
            status_code=302,
        )

    resp = RedirectResponse(url="/fleet", status_code=302)
    _set_auth_cookies(resp, str(user["id"]), user["role"])
    return resp


@router.get("/register")
def register_page(
    request: Request,
    error: str | None = None,
    msg: str | None = None,
):
    return templates.TemplateResponse("login.html", {
        "request": request, "user": None,
        "error": error, "msg": msg, "show_register": True, "show_demo": False,
    })


@router.post("/register")
def register_submit(
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(default=""),
):
    if len(password) < 8:
        return RedirectResponse(url="/register?error=Пароль+мінімум+8+символів", status_code=302)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
                if cur.fetchone():
                    return RedirectResponse(url="/register?error=Email+вже+зареєстровано", status_code=302)
                cur.execute(
                    "INSERT INTO users (email, password_hash, role, status, full_name) "
                    "VALUES (%s, %s, 'owner', 'pending', %s)",
                    (email, hash_password(password), full_name or None),
                )
    except Exception:
        return RedirectResponse(url="/register?error=Помилка+реєстрації", status_code=302)
    return RedirectResponse(
        url="/login?msg=Реєстрація+успішна.+Очікуйте+підтвердження.",
        status_code=302,
    )


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


@router.get("/demo-info")
def demo_info_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request, "user": None,
        "error": None, "msg": None, "show_register": False, "show_demo": True,
    })


@router.get("/demo")
def demo_login():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, role, status FROM users WHERE email = 'demo@example.com'",
            )
            user = cur.fetchone()
    if not user or user["status"] != "active":
        return RedirectResponse(url="/login?error=Demo+не+налаштовано", status_code=302)
    resp = RedirectResponse(url="/fleet", status_code=302)
    _set_auth_cookies(resp, str(user["id"]), user["role"])
    return resp


# ── Fleet ─────────────────────────────────────────────────────────────────────

@router.get("/fleet")
def fleet_page(request: Request, access_token: str | None = Cookie(default=None)):
    user = _user_from_cookie(access_token)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("fleet.html", {
        "request": request,
        "user": user,
        "vehicles": _get_vehicles(user),
        "active": "fleet",
    })


@router.get("/partials/fleet")
def fleet_partial(request: Request, access_token: str | None = Cookie(default=None)):
    user = _user_from_cookie(access_token)
    if not user:
        return HTMLResponse("")
    return templates.TemplateResponse("partials/fleet_cards.html", {
        "request": request,
        "vehicles": _get_vehicles(user),
    })


# ── Vehicle detail ────────────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}")
def vehicle_page(
    request: Request,
    vehicle_id: str,
    access_token: str | None = Cookie(default=None),
):
    user = _user_from_cookie(access_token)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    vehicle = _get_vehicle(vehicle_id, user)
    if not vehicle:
        return RedirectResponse(url="/fleet", status_code=302)
    return templates.TemplateResponse("vehicle.html", {
        "request": request,
        "user": user,
        "vehicle": vehicle,
        "alarms": _get_alarms(vehicle_id, user),
        "active": "fleet",
    })


@router.get("/partials/vehicles/{vehicle_id}/alarms")
def alarms_partial(
    request: Request,
    vehicle_id: str,
    access_token: str | None = Cookie(default=None),
):
    user = _user_from_cookie(access_token)
    if not user:
        return HTMLResponse("")
    return templates.TemplateResponse("partials/alarms.html", {
        "request": request,
        "alarms": _get_alarms(vehicle_id, user),
    })


# ── Admin ─────────────────────────────────────────────────────────────────────

@router.get("/admin")
def admin_page(
    request: Request,
    tab: str = "users",
    error: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    user = _user_from_cookie(access_token)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != "superuser":
        return RedirectResponse(url="/fleet", status_code=302)

    with get_conn(str(user.id), user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, role, status, full_name, created_at "
                "FROM users ORDER BY created_at DESC"
            )
            users = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, last_seen_at, sync_status "
                "FROM vehicles ORDER BY name"
            )
            vehicles = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT user_id::text, vehicle_id::text FROM vehicle_access")
            access_map: dict[str, list[str]] = {}
            for row in cur.fetchall():
                access_map.setdefault(str(row["vehicle_id"]), []).append(str(row["user_id"]))

    active_owners = [u for u in users if u["status"] == "active" and u["role"] == "owner"]

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "cu": user,
        "users": users,
        "vehicles": vehicles,
        "access_map": access_map,
        "active_owners": active_owners,
        "tab": tab,
        "error": error,
        "active": "admin",
    })


# ── Admin HTMX actions ────────────────────────────────────────────────────────

def _admin_update_user(user_id: str, new_status: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE users SET status = %s, updated_at = now() "
                "WHERE id = %s RETURNING id, email, role, status, full_name, created_at",
                (new_status, user_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


@router.post("/web/admin/users/{user_id}/approve")
def web_approve(
    request: Request, user_id: str,
    access_token: str | None = Cookie(default=None),
):
    cu = _user_from_cookie(access_token)
    if not cu or cu.role != "superuser":
        return HTMLResponse("")
    row = _admin_update_user(user_id, "active")
    if not row:
        return HTMLResponse("<span class='text-red-500 text-sm'>Помилка</span>")
    return templates.TemplateResponse("partials/user_row.html",
                                      {"request": request, "u": row, "cu": cu})


@router.post("/web/admin/users/{user_id}/block")
def web_block(
    request: Request, user_id: str,
    access_token: str | None = Cookie(default=None),
):
    cu = _user_from_cookie(access_token)
    if not cu or cu.role != "superuser" or str(cu.id) == user_id:
        return HTMLResponse("")
    row = _admin_update_user(user_id, "blocked")
    if not row:
        return HTMLResponse("<span class='text-red-500 text-sm'>Помилка</span>")
    return templates.TemplateResponse("partials/user_row.html",
                                      {"request": request, "u": row, "cu": cu})


@router.post("/web/admin/users/{user_id}/unblock")
def web_unblock(
    request: Request, user_id: str,
    access_token: str | None = Cookie(default=None),
):
    cu = _user_from_cookie(access_token)
    if not cu or cu.role != "superuser":
        return HTMLResponse("")
    row = _admin_update_user(user_id, "active")
    if not row:
        return HTMLResponse("<span class='text-red-500 text-sm'>Помилка</span>")
    return templates.TemplateResponse("partials/user_row.html",
                                      {"request": request, "u": row, "cu": cu})


def _vehicle_row_context(vehicle_id: str, user_id: str, user_role: str) -> dict:
    with get_conn(user_id, user_role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, sync_status "
                "FROM vehicles WHERE id = %s",
                (vehicle_id,),
            )
            v = dict(cur.fetchone())

            cur.execute(
                "SELECT user_id::text FROM vehicle_access WHERE vehicle_id = %s",
                (vehicle_id,),
            )
            owner_ids = [r["user_id"] for r in cur.fetchall()]

            cur.execute(
                "SELECT id, email FROM users WHERE status = 'active' AND role = 'owner'"
            )
            active_owners = [dict(r) for r in cur.fetchall()]

    access_map = {str(vehicle_id): owner_ids} if owner_ids else {}
    return {"v": v, "access_map": access_map, "active_owners": active_owners}


@router.post("/web/admin/vehicles/{vehicle_id}/assign")
def web_assign(
    request: Request,
    vehicle_id: str,
    user_id: str = Form(...),
    access_token: str | None = Cookie(default=None),
):
    cu = _user_from_cookie(access_token)
    if not cu or cu.role != "superuser":
        return HTMLResponse("")
    with get_conn(str(cu.id), cu.role) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO vehicle_access (user_id, vehicle_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, vehicle_id),
            )
    ctx = _vehicle_row_context(vehicle_id, str(cu.id), cu.role)
    return templates.TemplateResponse("partials/vehicle_row.html",
                                      {"request": request, **ctx})


@router.post("/web/admin/vehicles")
def web_add_vehicle(
    name: str = Form(...),
    vpn_ip: str = Form(...),
    api_port: int = Form(default=8080),
    access_token: str | None = Cookie(default=None),
):
    cu = _user_from_cookie(access_token)
    if not cu or cu.role != "superuser":
        return RedirectResponse(url="/login", status_code=302)
    try:
        with get_conn(str(cu.id), cu.role) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO vehicles (name, vpn_ip, api_port) "
                    "VALUES (%s, %s::inet, %s)",
                    (name.strip(), vpn_ip.strip(), api_port),
                )
    except Exception:
        return RedirectResponse(url="/admin?tab=vehicles&error=1", status_code=302)
    return RedirectResponse(url="/admin?tab=vehicles", status_code=302)


@router.delete("/web/admin/vehicles/{vehicle_id}/assign/{uid}")
def web_unassign(
    request: Request,
    vehicle_id: str, uid: str,
    access_token: str | None = Cookie(default=None),
):
    cu = _user_from_cookie(access_token)
    if not cu or cu.role != "superuser":
        return HTMLResponse("")
    with get_conn(str(cu.id), cu.role) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vehicle_access WHERE user_id = %s AND vehicle_id = %s",
                (uid, vehicle_id),
            )
    ctx = _vehicle_row_context(vehicle_id, str(cu.id), cu.role)
    return templates.TemplateResponse("partials/vehicle_row.html",
                                      {"request": request, **ctx})
