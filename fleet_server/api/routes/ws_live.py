import asyncio
from datetime import datetime, timezone
from uuid import UUID

import httpx
import psycopg2.extras
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from auth import decode_token
from config import settings
from database import get_conn

router = APIRouter(tags=["websocket"])

POLL_INTERVAL = 2.0  # секунди між опитуваннями авто


def _data_status(rows: list) -> str:
    """'online' якщо є свіжі дані, 'stale' якщо дані застарілі."""
    if not rows:
        return "stale"
    now = datetime.now(timezone.utc)
    latest = max(
        (r.get("time") for r in rows if r.get("time")),
        default=None,
    )
    if latest is None:
        return "stale"
    ts = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    age = (now - ts).total_seconds()
    return "online" if age <= settings.live_stale_threshold_sec else "stale"


def _check_access(user_id: str, user_role: str, vehicle_id: str) -> bool:
    """Перевіряє доступ user до vehicle. Superuser бачить все."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if user_role == "superuser":
                cur.execute("SELECT 1 FROM vehicles WHERE id = %s", (vehicle_id,))
            else:
                cur.execute(
                    "SELECT 1 FROM vehicle_access "
                    "WHERE user_id = %s AND vehicle_id = %s",
                    (user_id, vehicle_id),
                )
            return cur.fetchone() is not None


def _get_vehicle_addr(vehicle_id: str, user_id: str, user_role: str) -> dict | None:
    """Повертає {vpn_ip, api_port, api_key} або None якщо не знайдено."""
    with get_conn(user_id, user_role) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT host(vpn_ip) AS vpn_ip, api_port, api_key FROM vehicles WHERE id = %s",
                (vehicle_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


@router.websocket("/ws/vehicles/{vehicle_id}/live")
async def ws_live(
    websocket: WebSocket,
    vehicle_id: UUID,
    token: str | None = None,
) -> None:
    # Аутентифікація через query param (WebSocket не підтримує кастомні headers)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("not access token")
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id   = payload["sub"]
    user_role = payload.get("role", "owner")

    has_access = await asyncio.to_thread(
        _check_access, user_id, user_role, str(vehicle_id)
    )
    if not has_access:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    vehicle = await asyncio.to_thread(
        _get_vehicle_addr, str(vehicle_id), user_id, user_role
    )
    if not vehicle:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    await websocket.accept()

    vehicle_url = f"http://{vehicle['vpn_ip']}:{vehicle['api_port']}/data/latest"
    headers = {"X-Api-Key": vehicle["api_key"]} if vehicle.get("api_key") else {}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                try:
                    resp = await client.get(vehicle_url, headers=headers)
                    resp.raise_for_status()
                    rows = resp.json()
                    data = {"status": _data_status(rows), "data": rows}
                except (httpx.RequestError, httpx.HTTPStatusError):
                    data = {"status": "offline", "data": None}

                try:
                    await websocket.send_json(data)
                except Exception:
                    break  # клієнт відключився

                await asyncio.sleep(POLL_INTERVAL)
    except WebSocketDisconnect:
        pass
