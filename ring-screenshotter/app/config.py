from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(SERVICE_ROOT / ".env", override=False)


def _default_concurrency() -> int:
    cpu = os.cpu_count() or 2
    return max(1, min(4, cpu // 2 if cpu > 2 else 1))


def _default_blender_executable() -> Path:
    candidates: list[str] = [
        os.getenv("RING_SS_BLENDER_EXECUTABLE", "").strip(),
        os.getenv("BLENDER_PATH", "").strip(),
        os.getenv("BLENDER_EXEC", "").strip(),
        shutil.which("blender") or "",
        "/home/nimra/blender/blender-5.0.0-linux-x64/blender",
        "/usr/bin/blender",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    return Path("/usr/bin/blender")


class ScreenshotterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RING_SS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "ring-screenshotter-service"
    host: str = "0.0.0.0"
    port: int = 8103
    log_level: str = "INFO"

    # Blender
    blender_executable: Path = Field(default_factory=_default_blender_executable)
    blender_timeout_seconds: int = Field(default=300, ge=10, le=600)

    # Render defaults (match original Three.js exactly)
    default_resolution: int = Field(default=1024, ge=128, le=4096)

    # Storage
    storage_dir: Path = Field(default_factory=lambda: SERVICE_ROOT / "data")
    renders_subdir: str = "renders"
    artifact_cache_subdir: str = "artifact_cache"

    # Concurrency
    max_concurrent_jobs: int = Field(default_factory=_default_concurrency, ge=1, le=32)
    max_queue_size: int = Field(default=64, ge=1, le=10000)
    sync_wait_timeout_seconds: int = Field(default=180, ge=30, le=600)

    # Job lifecycle
    finished_job_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3600)
    max_job_records: int = Field(default=2000, ge=100, le=200000)

    # Auth
    api_key: str | None = None

    @field_validator("blender_executable", mode="after")
    @classmethod
    def _resolve_blender(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @property
    def renders_dir(self) -> Path:
        return self.storage_dir / self.renders_subdir

    @property
    def artifact_cache_dir(self) -> Path:
        return self.storage_dir / self.artifact_cache_subdir


settings = ScreenshotterSettings()
