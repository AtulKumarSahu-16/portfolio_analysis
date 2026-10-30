from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://portfolio:portfolio@localhost:5432/portfolio_intelligence"
    indianapi_api_key: str = ""
    indianapi_base_url: str = "https://stock.indianapi.in"
    mfnav_base_url: str = "https://mfnav.in"
    backend_cors_origins: str = "http://localhost:5173"
    jwt_secret_key: str = ""
    access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)
    auth_cookie_secure: bool = False
    cache_ttl_stock_seconds: int = Field(default=60, ge=0, le=86400)
    cache_ttl_nav_seconds: int = Field(default=3600, ge=0, le=604800)
    cache_ttl_history_seconds: int = Field(default=3600, ge=0, le=604800)
    http_timeout_seconds: float = Field(default=10, gt=0, le=120)
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
