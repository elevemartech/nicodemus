from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Eleve API
    eleve_api_url: str = "http://localhost:8000"

    # OpenAI
    openai_api_key: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"

    # Redis
    redis_url: str = "redis://localhost:6379/1"

    # Banco de dados
    database_url: str = "postgresql+asyncpg://nicodemus:nicodemus@localhost:5432/nicodemus_db"

    # File storage
    file_storage_ttl: int = 900          # 15 min em segundos
    file_storage_dir: str = "/tmp"

    # App
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


settings = Settings()
