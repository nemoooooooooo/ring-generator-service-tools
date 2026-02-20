from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScreenshotJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class ScreenshotRequest(BaseModel):
    """Input for the GLB screenshot pipeline.

    ``glb_path`` can be either a local file path (string) or a CAS
    artifact reference (dict with ``uri`` / ``sha256`` fields) produced
    by the Temporal pipeline's normalise_payload.
    """

    glb_path: Any
    resolution: int = Field(default=1024, ge=128, le=4096)
    session_id: str | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _require_glb(self) -> "ScreenshotRequest":
        if not self.glb_path:
            raise ValueError("glb_path is required")
        return self


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

class ScreenshotImage(BaseModel):
    name: str
    data_uri: str


class ScreenshotResult(BaseModel):
    success: bool = True
    screenshots: list[ScreenshotImage] = Field(default_factory=list)
    num_angles: int = 0
    resolution: int = 1024
    render_elapsed: float = 0.0
    glb_path: str = ""


# ---------------------------------------------------------------------------
# Job views (for /jobs endpoints)
# ---------------------------------------------------------------------------

class JobRecordView(BaseModel):
    id: str
    status: ScreenshotJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""

    request_summary: dict[str, Any] = Field(default_factory=dict)
    result: ScreenshotResult | None = None
    error: dict[str, Any] | None = None


class AsyncJobAccepted(BaseModel):
    job_id: str
    status: ScreenshotJobStatus = ScreenshotJobStatus.queued
    status_url: str
    result_url: str
