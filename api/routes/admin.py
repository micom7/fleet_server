import psycopg2
import psycopg2.extras
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from uuid import UUID

from database import get_conn
from dependencies import AuthUser, require_superuser
from mailer import send_email
from models.vehicle import AssignVehicleBody, VehicleCreate

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(superuser: AuthUser = Depends(require_superuser)) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, role, status, full_name, created_at "
                "FROM users ORDER BY created_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]


@router.get("/users/pending")
def list_pending_users(superuser: AuthUser = Depends(require_superuser)) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, role, status, full_name, created_at "
                "FROM users WHERE status = 'pending' ORDER BY created_at"
            )
            return [dict(r) for r in cur.fetchall()]


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: UUID,
    background_tasks: BackgroundTasks,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE users SET status = 'active', updated_at = now() "
                "WHERE id = %s AND status = 'pending' RETURNING email",
                (str(user_id),),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Користувача не знайдено або статус не 'pending'",
        )

    background_tasks.add_task(
        send_email,
        row["email"],
        "Fleet: акаунт підтверджено",
        "<p>Вітаємо! Ваш акаунт Fleet активовано. Тепер ви можете увійти.</p>",
    )
    return {"message": "Акаунт активовано"}


@router.post("/users/{user_id}/reject")
def reject_user(
    user_id: UUID,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM users WHERE id = %s AND status = 'pending'",
                (str(user_id),),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Користувача не знайдено або статус не 'pending'",
                )
    return {"message": "Реєстрацію відхилено"}


@router.post("/users/{user_id}/block")
def block_user(
    user_id: UUID,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    if str(user_id) == str(superuser.id):
        raise HTTPException(status_code=400, detail="Не можна заблокувати себе")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET status = 'blocked', updated_at = now() WHERE id = %s",
                (str(user_id),),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Користувача не знайдено")
    return {"message": "Користувача заблоковано"}


@router.post("/users/{user_id}/unblock")
def unblock_user(
    user_id: UUID,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET status = 'active', updated_at = now() "
                "WHERE id = %s AND status = 'blocked'",
                (str(user_id),),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Користувача не знайдено або не заблоковано",
                )
    return {"message": "Блокування знято"}


# ── Vehicles ──────────────────────────────────────────────────────────────────

@router.get("/vehicles")
def list_all_vehicles(superuser: AuthUser = Depends(require_superuser)) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, "
                "       last_seen_at, sync_status, created_at "
                "FROM vehicles ORDER BY name"
            )
            return [dict(r) for r in cur.fetchall()]


@router.post("/vehicles", status_code=status.HTTP_201_CREATED)
def create_vehicle(
    body: VehicleCreate,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(
                    "INSERT INTO vehicles (name, vpn_ip, api_port) "
                    "VALUES (%s, %s::inet, %s) RETURNING id",
                    (body.name, body.vpn_ip, body.api_port),
                )
            except psycopg2.Error as e:
                raise HTTPException(status_code=400, detail=str(e.pgerror))
            row = cur.fetchone()

    return {"id": str(row["id"]), "message": "Авто додано"}


@router.post("/vehicles/{vehicle_id}/assign")
def assign_vehicle(
    vehicle_id: UUID,
    body: AssignVehicleBody,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM vehicles WHERE id = %s", (str(vehicle_id),))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Авто не знайдено")

            cur.execute(
                "SELECT 1 FROM users WHERE id = %s AND status = 'active'",
                (str(body.user_id),),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=404,
                    detail="Користувача не знайдено або не активний",
                )

            cur.execute(
                "INSERT INTO vehicle_access (user_id, vehicle_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (str(body.user_id), str(vehicle_id)),
            )
    return {"message": "Авто призначено"}


@router.delete("/vehicles/{vehicle_id}/assign/{user_id}")
def unassign_vehicle(
    vehicle_id: UUID,
    user_id: UUID,
    superuser: AuthUser = Depends(require_superuser),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vehicle_access WHERE user_id = %s AND vehicle_id = %s",
                (str(user_id), str(vehicle_id)),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Прив'язку не знайдено")
    return {"message": "Прив'язку видалено"}
