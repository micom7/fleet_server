import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── PostgreSQL ───────────────────────────────────────────────────
    db_host:     str = os.getenv("DB_HOST", "localhost")
    db_port:     int = int(os.getenv("DB_PORT", "5432"))
    db_name:     str = os.getenv("DB_NAME", "fleet")
    db_user:     str = os.getenv("DB_USER", "fleet_app")
    db_password: str = os.getenv("DB_PASSWORD", "")

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} "
            f"dbname={self.db_name} user={self.db_user} password={self.db_password}"
        )

    # ── JWT ──────────────────────────────────────────────────────────
    jwt_secret:              str = os.getenv("JWT_SECRET", "")
    jwt_algorithm:           str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_expire_min:   int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    jwt_refresh_expire_days: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30"))

    # ── Google OAuth ─────────────────────────────────────────────────
    google_client_id:     str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri:  str = os.getenv("GOOGLE_REDIRECT_URI", "")

    # ── App ──────────────────────────────────────────────────────────
    base_url: str = os.getenv("BASE_URL", "http://localhost:8000")

    # ── SMTP ─────────────────────────────────────────────────────────
    smtp_host:     str = os.getenv("SMTP_HOST", "")
    smtp_port:     int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user:     str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from:     str = os.getenv("SMTP_FROM", "")


settings = Settings()
