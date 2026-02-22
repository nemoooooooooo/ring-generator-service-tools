"""
Ring Validator Microservice — FastAPI entry point.

Endpoints:
  POST /run          Temporal-compatible sync execution
  POST /jobs         Async job submission (GPU-style polling)
  GET  /jobs/{id}    Job status (for Temporal heartbeat polling)
  GET  /jobs/{id}/result   Final result
  DELETE /jobs/{id}  Cancel queued job
  GET  /health       Service health check
  GET  /tool/schema  Tool schema for registry
  GET  /test         Test console UI
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from shared.files import ensure_dir
from shared.logging import configure_logging
from shared.payloads import unwrap_tool_payload

from .config import settings
from .job_manager import ValidateJobManager
from .schemas import (
    AsyncJobAccepted,
    ValidateJobStatus,
    ValidateRequest,
    ValidateResult,
    JobRecordView,
)

configure_logging(settings.log_level)
logger = logging.getLogger("ring_val.main")


# ---------------------------------------------------------------------------
# Load master prompt at startup
# ---------------------------------------------------------------------------

if not settings.master_prompt_path.exists():
    raise FileNotFoundError(
        f"master_prompt.txt not found at {settings.master_prompt_path}. "
        "Copy it from vibe-designing-3d/master_prompt.txt into prompts/"
    )
MASTER_PROMPT = settings.master_prompt_path.read_text()
logger.info("Loaded master prompt: %d chars", len(MASTER_PROMPT))


# ---------------------------------------------------------------------------
# Job manager (singleton)
# ---------------------------------------------------------------------------

jobs = ValidateJobManager(settings, MASTER_PROMPT)


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
    ensure_dir(settings.artifact_cache_dir)
    await jobs.startup()
    yield
    await jobs.shutdown()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Ring Validator Tool Service",
    version="1.0.0",
    description=(
        "Standalone + orchestration-compatible ring validation microservice. "
        "Receives multi-angle screenshots and the Blender code that generated "
        "a ring, sends them to an LLM for structural geometry validation, and "
        "optionally re-renders corrected code if defects are found. Returns "
        "validation result with is_valid flag, optional corrected GLB path, "
        "and cost tracking."
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
            if x.status in {ValidateJobStatus.queued, ValidateJobStatus.running}
        ),
        "blender_exists": settings.blender_executable.exists(),
        "master_prompt_loaded": len(MASTER_PROMPT) > 0,
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
        "name": "ring-validate",
        "description": (
            "Validates a generated 3D ring by sending multi-angle screenshots "
            "and the Blender code to an LLM for structural geometry checking. "
            "If defects are found, re-renders with corrected code."
        ),
        "input_schema": ValidateRequest.model_json_schema(),
        "output_schema": ValidateResult.model_json_schema(),
    }


# ---------------------------------------------------------------------------
# POST /run — Temporal-compatible sync endpoint
# ---------------------------------------------------------------------------

@app.post("/run")
async def run_sync(request: Request, x_api_key: str | None = Header(default=None)):
    """
    Temporal-compatible sync endpoint.
    Accepts either:
      - plain ValidateRequest JSON
      - envelope shape: { "data": { ... }, "meta": { ... } }
    """
    _require_api_key(x_api_key)
    raw = await request.json()
    data, meta, wrapped = unwrap_tool_payload(raw)

    if "llm_name" in meta and "llm_name" not in data:
        data["llm_name"] = meta["llm_name"]

    val_request = ValidateRequest.model_validate(data)

    record = await jobs.submit(val_request)
    finished = await jobs.wait_for_completion(record.id, timeout_seconds=settings.sync_wait_timeout_seconds)

    if finished.status == ValidateJobStatus.succeeded and finished.result:
        result_dict = finished.result.model_dump()
        if wrapped:
            return {"result": result_dict}
        return result_dict

    if finished.status == ValidateJobStatus.cancelled:
        raise HTTPException(status_code=409, detail="Job cancelled")

    error = finished.error or {"message": "Unknown validation error", "status_code": 500}
    raise HTTPException(
        status_code=int(error.get("status_code", 500)),
        detail=error.get("message", "Validation failed"),
    )


# ---------------------------------------------------------------------------
# POST /jobs — Async job submission (GPU-style polling)
# ---------------------------------------------------------------------------

@app.post("/jobs", response_model=AsyncJobAccepted)
async def enqueue_job(request: Request, x_api_key: str | None = Header(default=None)):
    """
    Async endpoint for Temporal gpu_job_stream polling:
      POST /jobs  -> returns job_id
      GET /jobs/{job_id}  -> poll status
    """
    _require_api_key(x_api_key)
    raw = await request.json()
    data, meta, _ = unwrap_tool_payload(raw)

    if "llm_name" in meta and "llm_name" not in data:
        data["llm_name"] = meta["llm_name"]

    val_request = ValidateRequest.model_validate(data)
    record = await jobs.submit(val_request)

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

    if record.status == ValidateJobStatus.queued:
        return {"status": "queued", "progress": record.progress}
    if record.status == ValidateJobStatus.running:
        return {"status": "running", "progress": record.progress, "detail": record.detail}
    if record.status == ValidateJobStatus.cancelled:
        return {"status": "cancelled"}
    if record.status == ValidateJobStatus.failed:
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
# Static UI serving
# ---------------------------------------------------------------------------

SERVICE_ROOT = Path(__file__).resolve().parent.parent
_ui_dir = SERVICE_ROOT / "ui"
if _ui_dir.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_ui_dir)), name="ui")

    @app.get("/test", response_class=HTMLResponse)
    async def ui_redirect():
        return RedirectResponse(url="/ui/index.html", status_code=302)


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
