import secrets

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    sqla_engine: str = "sqlite:///demo.db?check_same_thread=false"
    mongo_uri: str = "mongodb://127.0.0.1:27017/demo"
    mongo_host: str = "mongodb://127.0.0.1:27017/"
    mongo_db: str = "demo"
    upload_dir: str = "upload/"
    secret: str = secrets.token_urlsafe(32)
    gtag: str = "G-VHZ5PF37EK"


config = Config()
