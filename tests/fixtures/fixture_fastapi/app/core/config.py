from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "E-Commerce API"
    DATABASE_URL: str = "postgresql://user:pass@localhost/db"
    SECRET_KEY: str = "super-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REDIS_URL: str = "redis://localhost:6379"

settings = Settings()
