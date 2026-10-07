from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    # Çalışma dizininden bağımsız: backend/.env okunur
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # Yerel geliştirme için SQLite; üretimde PostgreSQL (postgresql+psycopg://...)
    database_url: str = f"sqlite:///{(DATA_DIR / 'aidat.db').as_posix()}"
    secret_key: str = "dev-secret-change-me-in-production-0000"
    access_token_expire_minutes: int = 60 * 12
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # İlk çalıştırmada oluşturulacak yönetici (kullanıcı tablosu boşsa)
    initial_admin_email: str = "admin@ortabahce.local"
    initial_admin_password: str = "admin123"

    # Eşleştirme
    auto_match_threshold: float = 0.90

    # OpenRouter (opsiyonel, site bazında ayrıca açılmalı)
    openrouter_api_key: str | None = None
    # OpenRouter model kimliği; https://openrouter.ai/models listesinden doğrulanmalı
    openrouter_model: str = "anthropic/claude-opus-5.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
