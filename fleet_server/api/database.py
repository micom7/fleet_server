from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
import psycopg2.pool

from config import settings

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pool
    psycopg2.extras.register_uuid()
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=20,
        dsn=settings.db_dsn,
    )


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


@contextmanager
def get_conn(
    user_id: str | None = None,
    user_role: str | None = None,
) -> Generator:
    """DB connection з опціональним RLS контекстом.

    Якщо передані user_id і user_role — встановлює app.user_id та app.user_role
    як transaction-local змінні (is_local=true), що активує RLS-політики.
    """
    conn = _pool.getconn()
    try:
        if user_id and user_role:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.user_id', %s, true),"
                    "       set_config('app.user_role', %s, true)",
                    (user_id, user_role),
                )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
