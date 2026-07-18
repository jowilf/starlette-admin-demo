import os

from sqlalchemy import create_engine
from starlette_admin.storage import LocalStorage

APP_ENV = os.getenv("APP_ENV", "DEV")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads/")
DATABASE_URL = os.getenv("ENGINE", "postgresql+psycopg://demo:demo@localhost:5433/demo")

_engine_kwargs = {
    "echo": APP_ENV != "PROD",
    # Discards connections the server silently dropped (e.g. past an idle timeout).
    "pool_pre_ping": True,
    "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
}
if not DATABASE_URL.startswith("sqlite"):
    # 8 fastapi workers (see Dockerfile) each get their own pool, so keep
    # per-worker limits modest to stay under Postgres's max_connections.
    _engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
    _engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    _engine_kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "30"))

engine = create_engine(DATABASE_URL, **_engine_kwargs)
avatars_storage = LocalStorage(base_dir=UPLOAD_DIR)

# Page-view analytics via self-hosted Umami
UMAMI_HOST = os.getenv("UMAMI_HOST")
UMAMI_WEBSITE_ID = os.getenv("UMAMI_WEBSITE_ID")
