from typing import Optional

from pydantic import BaseSettings


class Config(BaseSettings):
    sqla_engine: str = "sqlite:///demo.db?check_same_thread=false"
    mongo_uri: str = "mongodb://127.0.0.1:27017/demo"
    mongo_host: str = "mongodb://127.0.0.1:27017/"
    mongo_db: str = "demo"
    upload_dir: str = "upload/"
    secret: str = "123456789"
    gtag: Optional[str] = None


config = Config()
