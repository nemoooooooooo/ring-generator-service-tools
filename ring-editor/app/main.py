"""
Ring Editor Microservice — FastAPI entry point.

Endpoints:
  POST /run          Temporal-compatible sync execution
  POST /jobs         Async job submission (GPU-style polling)
  GET  /jobs/{id}    Job status (for Temporal heartbeat polling)
  GET  /jobs/{id}/result   Final result
  DELETE /jobs/{id}  Cancel queued job
  GET  /health       Service health check
  GET  /tool/schema  Tool schema for registry
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError as PydanticValidationError

from shared.files import ensure_dir
from shared.logging import configure_logging
from shared.payloads import unwrap_tool_payload

from .config import settings
from .job_manager import EditJobManager
from .schemas import (
    AsyncJobAccepted,
    EditJobStatus,
    EditRequest,
    EditResult,
    JobRecordView,
)

configure_logging(settings.log_level)
logger = logging.getLogger("ring_edit.main")

# ---------------------------------------------------------------------------
# Load prompts at startup
# ---------------------------------------------------------------------------

if not settings.master_prompt_path.exists():
    raise FileNotFoundError(
        f"master_prompt.txt not found at {settings.master_prompt_path}. "
        "Copy it from vibe-designing-3d/master_prompt.txt into prompts/"
    )
SYSTEM_PROMPT = settings.master_prompt_path.read_text()
logger.info("Loaded master prompt: %d chars", len(SYSTEM_PROMPT))

PART_REGEN_TEMPLATE = ""
if settings.part_regen_prompt_path.exists():
    PART_REGEN_TEMPLATE = settings.part_regen_prompt_path.read_text()
    logger.info("Loaded part regen prompt: %d chars", len(PART_REGEN_TEMPLATE))
else:
    logger.warning("part_regen_prompt.txt not found at %s — regen-part will use basic prompt",
                    settings.part_regen_prompt_path)


# ---------------------------------------------------------------------------
# Job manager (singleton)
# ---------------------------------------------------------------------------

jobs = EditJobManager(settings, SYSTEM_PROMPT, PART_REGEN_TEMPLATE)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_api_key(x_api_key: str | None) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dir(settings.sessions_dir)
    await jobs.startup()
    yield
    await jobs.shutdown()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Ring Editor Tool Service",
    version="1.0.0",
    description=(
        "Standalone + orchestration-compatible ring editing microservice. "
        "Takes current Blender code + edit instruction (edit, regen-part, "
        "or add-part), generates modified code via LLM, re-renders via "
        "Blender with auto-retry, and returns an updated GLB file."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PydanticValidationError)
async def validation_exception_handler(request: Request, exc: PydanticValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": settings.service_name,
        "queue_size": jobs.queue.qsize(),
        "active_jobs": sum(
            1 for x in jobs.jobs.values()
            if x.status in {EditJobStatus.queued, EditJobStatus.running}
        ),
        "blender_exists": settings.blender_executable.exists(),
        "master_prompt_loaded": len(SYSTEM_PROMPT) > 0,
        "part_regen_prompt_loaded": len(PART_REGEN_TEMPLATE) > 0,
        "claude_available": settings.claude_available,
        "gemini_available": settings.gemini_available,
        "max_concurrent_jobs": settings.max_concurrent_jobs,
    }


# ---------------------------------------------------------------------------
# Tool schema (for temporal-agentic-pipeline registry)
# ---------------------------------------------------------------------------

@app.get("/tool/schema")
async def tool_schema():
    return {
        "name": "ring-edit",
        "description": (
            "Edits, rebuilds parts of, or adds new parts to an existing 3D ring. "
            "Takes current Blender code + edit instruction, generates modified "
            "code via LLM, re-renders via Blender with auto-retry, returns "
            "updated GLB."
        ),
        "input_schema": EditRequest.model_json_schema(),
        "output_schema": EditResult.model_json_schema(),
    }


# ---------------------------------------------------------------------------
# POST /run — Temporal-compatible sync endpoint
# ---------------------------------------------------------------------------

@app.post("/run")
async def run_sync(request: Request, x_api_key: str | None = Header(default=None)):
    """
    Temporal-compatible sync endpoint.
    Accepts either:
      - plain EditRequest JSON
      - envelope shape: { "data": { ... }, "meta": { ... } }
    """
    _require_api_key(x_api_key)
    raw = await request.json()
    data, meta, wrapped = unwrap_tool_payload(raw)

    # Allow meta overrides for llm_name
    if "llm_name" in meta and "llm_name" not in data:
        data["llm_name"] = meta["llm_name"]

    try:
        edit_request = EditRequest.model_validate(data)
    except PydanticValidationError as e:
        errors = [{"msg": err["msg"], "loc": err.get("loc", ()), "type": err["type"]} for err in e.errors()]
        raise HTTPException(status_code=422, detail=errors)

    record = await jobs.submit(edit_request)
    finished = await jobs.wait_for_completion(record.id, timeout_seconds=settings.sync_wait_timeout_seconds)

    if finished.status == EditJobStatus.succeeded and finished.result:
        result_dict = finished.result.model_dump()
        if wrapped:
            return {"result": result_dict}
        return result_dict

    if finished.status == EditJobStatus.cancelled:
        raise HTTPException(status_code=409, detail="Job cancelled")

    error = finished.error or {"message": "Unknown edit error", "status_code": 500}
    raise HTTPException(
        status_code=int(error.get("status_code", 500)),
        detail=error.get("message", "Edit failed"),
    )


# ---------------------------------------------------------------------------
# POST /jobs — Async job submission (GPU-style polling)
# ---------------------------------------------------------------------------

@app.post("/jobs", response_model=AsyncJobAccepted)
async def enqueue_job(request: Request, x_api_key: str | None = Header(default=None)):
    """
    Async endpoint for Temporal gpu_job_stream polling:
      POST /jobs  → returns job_id
      GET /jobs/{job_id}  → poll status
    """
    _require_api_key(x_api_key)
    raw = await request.json()
    data, meta, _ = unwrap_tool_payload(raw)

    if "llm_name" in meta and "llm_name" not in data:
        data["llm_name"] = meta["llm_name"]

    try:
        edit_request = EditRequest.model_validate(data)
    except PydanticValidationError as e:
        errors = [{"msg": err["msg"], "loc": err.get("loc", ()), "type": err["type"]} for err in e.errors()]
        raise HTTPException(status_code=422, detail=errors)
    record = await jobs.submit(edit_request)

    return AsyncJobAccepted(
        job_id=record.id,
        status=record.status,
        status_url=f"/jobs/{record.id}",
        result_url=f"/jobs/{record.id}/result",
    )


# ---------------------------------------------------------------------------
# GET /jobs/{job_id} — Job status (for Temporal heartbeat)
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}", response_model=JobRecordView)
async def get_job(job_id: str, x_api_key: str | None = Header(default=None)):
    _require_api_key(x_api_key)
    try:
        record = await jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return record.as_view()


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/result — Final result (Temporal polling endpoint)
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str, x_api_key: str | None = Header(default=None)):
    _require_api_key(x_api_key)
    try:
        record = await jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if record.status == EditJobStatus.queued:
        return {"status": "queued", "progress": record.progress}
    if record.status == EditJobStatus.running:
        return {"status": "running", "progress": record.progress, "detail": record.detail}
    if record.status == EditJobStatus.cancelled:
        return {"status": "cancelled"}
    if record.status == EditJobStatus.failed:
        return {
            "status": "failed",
            "error": (record.error or {}).get("message", "unknown error"),
            "result": record.result.model_dump() if record.result else None,
        }
    return {
        "status": "succeeded",
        "result": record.result.model_dump() if record.result else None,
    }


# ---------------------------------------------------------------------------
# DELETE /jobs/{job_id} — Cancel
# ---------------------------------------------------------------------------

@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, x_api_key: str | None = Header(default=None)):
    _require_api_key(x_api_key)
    try:
        record = await jobs.cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"success": True, "job_id": job_id, "status": record.status}


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}/model.glb — Serve generated GLB
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/model.glb")
async def serve_glb(session_id: str):
    glb_path = settings.sessions_dir / session_id / "model.glb"
    if not glb_path.exists():
        raise HTTPException(status_code=404, detail="GLB not found")
    return FileResponse(str(glb_path), media_type="model/gltf-binary")


# ---------------------------------------------------------------------------
# GET /sessions/{session_id} — Session metadata
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session_json = settings.sessions_dir / session_id / "session.json"
    if not session_json.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(content=json.loads(session_json.read_text()))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=bool(int(os.getenv("UVICORN_RELOAD", "0"))),
    )
