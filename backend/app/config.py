from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")
    env: str = "development"
    database_url: str = "sqlite:///./data/attendance.db"
    redis_url: str = ""
    storage_dir: Path = Path("./data/photos")
    secret_key: str = "development-only-change-before-deploy"
    cookie_secure: bool = False
    session_hours: int = 8
    max_upload_bytes: int = 5 * 1024 * 1024
    max_image_pixels: int = 16_000_000
    max_users: int = 10
    rate_limit_enabled: bool = True

    @model_validator(mode="after")
    def production_requirements(self):
        if self.env == "production":
            if len(self.secret_key) < 32 or self.secret_key.startswith(
                ("development-", "replace-")
            ):
                raise ValueError("Production requires a random APP_SECRET_KEY of at least 32 chars")
            if not self.cookie_secure:
                raise ValueError("Production requires HTTPS and APP_COOKIE_SECURE=true")
            if not self.redis_url or not self.database_url.startswith("mysql"):
                raise ValueError("Production requires MySQL and Redis")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
