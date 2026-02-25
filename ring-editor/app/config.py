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
        os.getenv("RING_EDIT_BLENDER_EXECUTABLE", "").strip(),
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


class RingEditSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RING_EDIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "ring-editor-service"
    host: str = "0.0.0.0"
    port: int = 8004
    log_level: str = "INFO"

    # LLM API keys
    anthropic_api_key: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3-pro-preview"))

    # Blender
    blender_executable: Path = Field(default_factory=_default_blender_executable)
    blender_timeout_seconds: int = Field(default=300, ge=30, le=3600)

    # Pipeline defaults
    max_error_retries: int = Field(default=3, ge=1, le=10)
    max_cost_per_request_usd: float = Field(default=5.0, ge=0.1, le=100.0)

    # Prompts
    master_prompt_path: Path = Field(
        default_factory=lambda: SERVICE_ROOT / "prompts" / "master_prompt.txt"
    )
    part_regen_prompt_path: Path = Field(
        default_factory=lambda: SERVICE_ROOT / "prompts" / "part_regen_prompt.txt"
    )

    # Storage
    storage_dir: Path = Field(default_factory=lambda: SERVICE_ROOT / "data")
    sessions_subdir: str = "sessions"

    # Concurrency
    max_concurrent_jobs: int = Field(default_factory=_default_concurrency, ge=1, le=32)
    max_queue_size: int = Field(default=64, ge=1, le=10000)
    sync_wait_timeout_seconds: int = Field(default=600, ge=60, le=3600)

    # Job lifecycle
    finished_job_ttl_seconds: int = Field(default=3600, ge=60, le=172800)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3600)
    max_job_records: int = Field(default=2000, ge=100, le=200000)

    # Auth
    api_key: str | None = None

    @field_validator("blender_executable", mode="after")
    @classmethod
    def _resolve_blender(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @property
    def sessions_dir(self) -> Path:
        return self.storage_dir / self.sessions_subdir

    @property
    def claude_available(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def gemini_available(self) -> bool:
        return bool(self.gemini_api_key)


settings = RingEditSettings()
