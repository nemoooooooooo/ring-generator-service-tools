from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class EditRequest(BaseModel):
    """Input for the ring edit/regen/add-part pipeline."""

    # What operation to perform
    operation: Literal["edit", "regen-part", "add-part"]

    # The existing ring's data
    code: str                                    # Current Blender Python code
    modules: list[str] = Field(default_factory=list)  # Current module names
    user_prompt: str = ""                        # Original generation prompt (context)
    spatial_report: str = ""                     # Spatial report from the validated ring (geometry context for LLM)

    # The edit instruction
    edit_instruction: str = ""                   # For "edit": what to change
    target_module: str = ""                      # For "edit" (smart) or "regen-part": which build_* to target
    part_description: str = ""                   # For "add-part": what new part to add

    # LLM selection
    llm_name: str = "gemini"

    # Session tracking
    session_id: str | None = None
    current_version: int = 1

    # Pipeline config (overridable)
    max_retries: int | None = None
    max_cost_usd: float | None = None

    # Temporal compatibility
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _validate_operation(self) -> "EditRequest":
        if self.llm_name not in ("claude", "claude-sonnet", "claude-opus", "gemini"):
            raise ValueError("llm_name must be one of: claude, claude-sonnet, claude-opus, gemini")
        if not self.code:
            raise ValueError("code is required — provide the current ring's Blender Python code")
        if self.operation == "edit" and not self.edit_instruction:
            raise ValueError("edit_instruction is required for 'edit' operation")
        if self.operation == "regen-part" and not self.target_module:
            raise ValueError("target_module is required for 'regen-part' operation")
        if self.operation == "add-part" and not self.part_description:
            raise ValueError("part_description is required for 'add-part' operation")
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


class EditResult(BaseModel):
    success: bool = False
    session_id: str = ""

    # The output
    glb_path: Any = None                         # Local path or CAS artifact ref
    code: str = ""                               # New code after edit
    modules: list[str] = Field(default_factory=list)  # Updated module list

    # What happened
    operation: str = ""                          # "edit" | "regen-part" | "add-part"
    description: str = ""                        # Human-readable summary of change
    version: int = 1                             # New version number

    # Quality data
    spatial_report: str = ""
    retry_log: list[RetryEntry] = Field(default_factory=list)
    needs_validation: bool = True

    # Cost tracking
    cost_summary: CostSummary = Field(default_factory=CostSummary)
    llm_used: str = ""
    blender_elapsed: float = 0.0
    glb_size: int = 0


# ---------------------------------------------------------------------------
# Job views (for /jobs endpoints)
# ---------------------------------------------------------------------------

class JobRecordView(BaseModel):
    id: str
    status: EditJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    detail: str = ""

    request_summary: dict[str, Any] = Field(default_factory=dict)
    result: EditResult | None = None
    error: dict[str, Any] | None = None


class AsyncJobAccepted(BaseModel):
    job_id: str
    status: EditJobStatus = EditJobStatus.queued
    status_url: str
    result_url: str
