from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolEnvelope(BaseModel):
    """
    Compatible with the Temporal pipeline payload envelope:
    { "data": { ...tool input... }, "meta": { ...context... } }
    """

    data: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


def unwrap_tool_payload(raw_body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """
    Returns:
      - tool data
      - metadata
      - whether request was envelope-wrapped
    """
    if isinstance(raw_body, dict) and "data" in raw_body and isinstance(raw_body.get("data"), dict):
        envelope = ToolEnvelope.model_validate(raw_body)
        return envelope.data, envelope.meta, True
    return raw_body, {}, False
