from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValidateJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    """Input for the ring validation pipeline.

    ``screenshots`` accepts multiple shapes — all are resolved to
    ``data:<mime>;base64,...`` strings in the pipeline before the LLM call:

      - ``str``: bare data-URI  (standalone / direct calls)
      - ``dict`` with ``data_uri`` (str): screenshot object from tool 2
      - ``dict`` with ``data_uri`` (CAS dict): after Temporal normalise_payload
      - ``dict`` with ``uri``: bare CAS artifact reference

    ``code`` is the Blender Python code that generated the ring.
    ``user_prompt`` is the original user description.
    ``llm_name`` selects the LLM for validation (same one that generated the ring).
    ``glb_path`` is optional (not used by the pipeline; kept for DAG passthrough).
    """

    screenshots: list[Any]
    code: str
    user_prompt: str = ""
    llm_name: str = "gemini"
    glb_path: Any = None
    session_id: str | None = None

    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _require_inputs(self) -> "ValidateRequest":
        if not self.screenshots:
            raise ValueError("At least one screenshot is required")
        if not self.code:
            raise ValueError("code is required for validation")
        return self


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ValidateResult(BaseModel):
    is_valid: bool = True
    message: str = ""
    regenerated: bool = False
    corrected_code: str | None = None
    cost: float = 0.0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    glb_path: str | None = None
    llm_used: str = ""


# ---------------------------------------------------------------------------
# Job views (for /jobs endpoints)
# ---------------------------------------------------------------------------

class JobRecordView(BaseModel):
    id: str
    status: ValidateJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""

    request_summary: dict[str, Any] = Field(default_factory=dict)
    result: ValidateResult | None = None
    error: dict[str, Any] | None = None


class AsyncJobAccepted(BaseModel):
    job_id: str
    status: ValidateJobStatus = ValidateJobStatus.queued
    status_url: str
    result_url: str
