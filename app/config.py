from pydantic import BaseSettings


class Config(BaseSettings):
    engine: str = "sqlite:///demo.db?check_same_thread=false"
    mongo_host: str = "mongodb://127.0.0.1:27017/demo"
    mongo_db: str = "demo"
    upload_dir: str = "/tmp/storage"
    secret: str = "123456789"


config = Config()
