from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerateJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Input for the ring generation pipeline."""

    prompt: str | None = None
    image_b64: str | None = None
    image_mime: str | None = None

    llm_name: str = "claude"
    max_retries: int | None = None
    max_cost_usd: float | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _require_input(self) -> "GenerateRequest":
        if not self.prompt and not self.image_b64:
            raise ValueError("Provide a text prompt or a base64-encoded reference image.")
        if self.llm_name not in ("claude", "claude-sonnet", "claude-opus", "gemini"):
            raise ValueError("llm_name must be one of: claude, claude-sonnet, claude-opus, gemini")
        return self


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

class RetryEntry(BaseModel):
    attempt: int
    success: bool
    code_length: int
    error_text: str = ""
    timestamp: str = ""


class CostSummary(BaseModel):
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_usd: float = 0.0
    calls: int = 0
    details: list[dict[str, Any]] = Field(default_factory=list)


class GenerateResult(BaseModel):
    success: bool = True
    session_id: str = ""
    glb_path: str = ""
    code: str = ""
    modules: list[str] = Field(default_factory=list)
    spatial_report: str = ""
    retry_log: list[RetryEntry] = Field(default_factory=list)
    cost_summary: CostSummary = Field(default_factory=CostSummary)
    needs_validation: bool = True
    llm_used: str = ""
    blender_elapsed: float = 0.0
    glb_size: int = 0


# ---------------------------------------------------------------------------
# Job views (for /jobs endpoints)
# ---------------------------------------------------------------------------

class JobRecordView(BaseModel):
    id: str
    status: GenerateJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""

    request_summary: dict[str, Any] = Field(default_factory=dict)
    result: GenerateResult | None = None
    error: dict[str, Any] | None = None


class AsyncJobAccepted(BaseModel):
    job_id: str
    status: GenerateJobStatus = GenerateJobStatus.queued
    status_url: str
    result_url: str
