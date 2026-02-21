from dataclasses import dataclass
from uuid import UUID

import psycopg2.extras
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from auth import decode_token
from database import get_conn

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    id:        UUID
    email:     str
    role:      str
    status:    str
    full_name: str | None


def _fetch_user(user_id: str) -> AuthUser | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, role, status, full_name FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return AuthUser(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        status=row["status"],
        full_name=row["full_name"],
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не авторизовано",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not creds:
        raise exc
    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise exc

    if payload.get("type") != "access":
        raise exc

    user = _fetch_user(payload["sub"])
    if not user:
        raise exc

    if user.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Акаунт заблоковано",
        )
    if user.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Акаунт очікує підтвердження адміністратора",
        )
    return user


def require_superuser(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if current_user.role != "superuser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ тільки для адміністраторів",
        )
    return current_user
