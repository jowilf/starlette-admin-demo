import os

from sqlalchemy import create_engine
from starlette_admin.storage import LocalStorage

APP_ENV = os.getenv("APP_ENV", "DEV")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads/")
DATABASE_URL = os.getenv("ENGINE", "sqlite:///demo.db?check_same_thread=false")

engine = create_engine(DATABASE_URL, echo=APP_ENV != "PROD")
avatars_storage = LocalStorage(base_dir=UPLOAD_DIR)
