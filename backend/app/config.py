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
    model_dir: Path = Path("./models")
    opencv_threads: int = 2
    match_threshold: float = 0.50
    match_margin: float = 0.08
    detection_threshold: float = 0.90
    min_face_size: int = 60
    min_blur_score: float = 25.0
    queue_capacity: int = 32
    queue_timeout_seconds: int = 120
    worker_lease_seconds: int = 60
    max_job_attempts: int = 3
    # Only unit tests bypass readiness; production always requires a loaded worker.
    require_worker_ready: bool = True

    @model_validator(mode="after")
    def production_requirements(self):
        if not (0 < self.match_threshold < 1 and 0 <= self.match_margin < 1):
            raise ValueError("Invalid matching thresholds")
        if self.queue_capacity < 1 or self.opencv_threads < 1:
            raise ValueError("Queue capacity and CPU thread count must be positive")
        if self.env == "production":
            if len(self.secret_key) < 32 or self.secret_key.startswith(
                ("development-", "replace-")
            ):
                raise ValueError("Production requires a random APP_SECRET_KEY of at least 32 chars")
            if not self.cookie_secure:
                raise ValueError("Production requires HTTPS and APP_COOKIE_SECURE=true")
            if not self.redis_url or not self.database_url.startswith("mysql"):
                raise ValueError("Production requires MySQL and Redis")
            if not self.require_worker_ready:
                raise ValueError("Production requires model worker readiness")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
