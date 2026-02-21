import datetime as dt
from uuid import UUID

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException

from database import get_conn
from dependencies import AuthUser, get_current_user

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("")
def list_vehicles(current_user: AuthUser = Depends(get_current_user)) -> list:
    with get_conn(str(current_user.id), current_user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, last_seen_at, sync_status "
                "FROM vehicles ORDER BY name"
            )
            return [dict(r) for r in cur.fetchall()]


@router.get("/{vehicle_id}")
def get_vehicle(
    vehicle_id: UUID,
    current_user: AuthUser = Depends(get_current_user),
) -> dict:
    with get_conn(str(current_user.id), current_user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, host(vpn_ip) AS vpn_ip, api_port, last_seen_at, sync_status "
                "FROM vehicles WHERE id = %s",
                (str(vehicle_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Авто не знайдено")
    return dict(row)


@router.get("/{vehicle_id}/status")
def vehicle_status(
    vehicle_id: UUID,
    current_user: AuthUser = Depends(get_current_user),
) -> dict:
    with get_conn(str(current_user.id), current_user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, last_seen_at, sync_status FROM vehicles WHERE id = %s",
                (str(vehicle_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Авто не знайдено")

    now      = dt.datetime.now(dt.timezone.utc)
    last_seen = row["last_seen_at"]
    online   = bool(last_seen and (now - last_seen).total_seconds() < 120)

    return {
        "id":           str(row["id"]),
        "name":         row["name"],
        "online":       online,
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "sync_status":  row["sync_status"],
    }


@router.get("/{vehicle_id}/alarms")
def vehicle_alarms(
    vehicle_id: UUID,
    current_user: AuthUser = Depends(get_current_user),
) -> list:
    with get_conn(str(current_user.id), current_user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, alarm_id, channel_id, severity, message, triggered_at, resolved_at
                FROM alarms_log
                WHERE vehicle_id = %s AND resolved_at IS NULL
                ORDER BY triggered_at DESC
                """,
                (str(vehicle_id),),
            )
            return [dict(r) for r in cur.fetchall()]


@router.get("/{vehicle_id}/channels")
def vehicle_channels(
    vehicle_id: UUID,
    current_user: AuthUser = Depends(get_current_user),
) -> list:
    with get_conn(str(current_user.id), current_user.role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT channel_id, name, unit, min_value, max_value, synced_at
                FROM channel_config
                WHERE vehicle_id = %s
                ORDER BY channel_id
                """,
                (str(vehicle_id),),
            )
            return [dict(r) for r in cur.fetchall()]
