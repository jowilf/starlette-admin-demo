import os

from sqlalchemy import create_engine
from starlette_admin.storage import LocalStorage

APP_ENV = os.getenv("APP_ENV", "DEV")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads/")
DATABASE_URL = os.getenv("ENGINE", "sqlite:///demo.db?check_same_thread=false")

_engine_kwargs = {
    "echo": APP_ENV != "PROD",
    # Detect and discard connections MySQL has silently dropped (e.g. past
    # wait_timeout) before handing them to a request.
    "pool_pre_ping": True,
    # Recycle connections before they hit MySQL's default wait_timeout (8h),
    # so idle workers don't hand out connections the server already closed.
    "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
}
if not DATABASE_URL.startswith("sqlite"):
    # Each of the app's 8 fastapi workers (see Dockerfile) gets its own pool,
    # so keep per-worker limits modest to stay under MySQL's max_connections.
    _engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
    _engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    _engine_kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "30"))

engine = create_engine(DATABASE_URL, **_engine_kwargs)
avatars_storage = LocalStorage(base_dir=UPLOAD_DIR)

# Page-view analytics via self-hosted Umami
UMAMI_HOST = os.getenv("UMAMI_HOST")
UMAMI_WEBSITE_ID = os.getenv("UMAMI_WEBSITE_ID")
