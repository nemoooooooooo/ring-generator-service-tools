"""
Ring generation pipeline — orchestrates the full flow:

  1. Build prompt from user input
  2. Call LLM for code generation
  3. Run Blender with auto-retry (LLM-assisted error fixing)
  4. Return structured result with GLB, code, cost summary

This is the core logic that must remain 1:1 with the original
vibe-designing-3d /api/generate endpoint.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..schemas import CostSummary, GenerateRequest, GenerateResult, RetryEntry
from .blender_runner import BlenderResult, run_blender
from .code_processor import extract_modules
from .llm_client import LLMResponse, UsageInfo, call_llm
from .prompt_builder import build_fix_prompt, build_generation_prompt
from shared.artifact_uploader import upload_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cost aggregation
# ---------------------------------------------------------------------------

def _compute_cost_summary(usage_list: list[UsageInfo]) -> CostSummary:
    return CostSummary(
        total_input_tokens=sum(u.input_tokens for u in usage_list),
        total_output_tokens=sum(u.output_tokens for u in usage_list),
        total_usd=round(sum(u.cost_usd for u in usage_list), 4),
        calls=len(usage_list),
        details=[u.to_dict() for u in usage_list],
    )


# ---------------------------------------------------------------------------
# Retry loop — identical to original run_with_retry()
# ---------------------------------------------------------------------------

async def _run_with_retry(
    llm_name: str,
    initial_code: str,
    glb_path: str,
    system_prompt: str,
    blender_executable: str,
    blender_timeout: int,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    max_retries: int = 3,
    max_cost_usd: float = 5.0,
    spent_so_far: float = 0.0,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[str, BlenderResult, list[RetryEntry], list[UsageInfo]]:
    """
    Run Blender on code. On error, send code+error to LLM to fix.
    Up to max_retries. Enforces budget. Returns (code, result, retry_log, extra_usage).
    """
    retry_log: list[RetryEntry] = []
    extra_usage: list[UsageInfo] = []
    code = initial_code
    cumulative_cost = spent_so_far
    last_spatial_report: str | None = None

    for attempt in range(1, max_retries + 1):
        logger.info(
            "[ATTEMPT %d/%d] (budget: $%.3f / $%.1f)",
            attempt, max_retries, cumulative_cost, max_cost_usd,
        )
        if progress_callback:
            progress_callback("blender", attempt, max_retries)

        result = await run_blender(code, glb_path, blender_executable, blender_timeout)

        if result.spatial_report:
            last_spatial_report = result.spatial_report

        entry = RetryEntry(
            attempt=attempt,
            success=result.success,
            code_length=len(code),
            error_text="",
            timestamp=datetime.now().isoformat(),
        )

        if result.success:
            retry_log.append(entry)
            logger.info("[ATTEMPT %d] SUCCESS", attempt)
            return code, result, retry_log, extra_usage

        error_text = '\n'.join(result.error_lines[:20])
        stderr_tail = result.stderr[-1500:]
        if stderr_tail:
            error_text += '\n' + stderr_tail
        entry.error_text = error_text[:3000]
        retry_log.append(entry)

        if attempt < max_retries:
            if cumulative_cost >= max_cost_usd:
                logger.warning(
                    "[BUDGET] Cost $%.3f exceeds $%.1f limit — skipping retry",
                    cumulative_cost, max_cost_usd,
                )
                break

            logger.info("[ATTEMPT %d] FAILED — asking LLM to fix...", attempt)
            if progress_callback:
                progress_callback("fixing", attempt, max_retries)

            try:
                fix_prompt = build_fix_prompt(code, error_text[:2000], spatial_report=last_spatial_report)
                llm_resp = await call_llm(
                    llm_name,
                    system_prompt,
                    fix_prompt,
                    anthropic_api_key=anthropic_api_key,
                    gemini_api_key=gemini_api_key,
                    gemini_model=gemini_model,
                )
                code = llm_resp.code
                extra_usage.append(llm_resp.usage)
                cumulative_cost += llm_resp.usage.cost_usd
            except Exception as e:
                logger.error("LLM fix call failed: %s", e)
                break
        else:
            logger.info("[ATTEMPT %d] FAILED — no more retries", attempt)

    return code, result, retry_log, extra_usage


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def generate_ring(
    request: GenerateRequest,
    system_prompt: str,
    sessions_dir: Path,
    blender_executable: str,
    blender_timeout: int,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    max_retries: int = 3,
    max_cost_usd: float = 5.0,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> GenerateResult:
    """
    End-to-end ring generation: prompt → LLM → Blender → retry loop → GLB.
    """
    llm_name = request.llm_name
    prompt = request.prompt or ""
    session_id = request.request_id or f"s_{uuid.uuid4().hex[:10]}_{int(time.time())}"

    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    glb_path = str(session_dir / "model.glb")

    # Decode image if provided
    image_data: bytes | None = None
    image_mime: str | None = None
    if request.image_b64:
        image_data = base64.b64decode(request.image_b64)
        image_mime = request.image_mime or "image/jpeg"
        ext = image_mime.split("/")[-1] if image_mime else "jpg"
        img_path = session_dir / f"reference.{ext}"
        img_path.write_bytes(image_data)

    effective_retries = request.max_retries if request.max_retries is not None else max_retries
    effective_budget = request.max_cost_usd if request.max_cost_usd is not None else max_cost_usd

    # Step 1: Call LLM for code generation
    logger.info("[STEP 1] Calling %s for code generation...", llm_name.upper())
    if progress_callback:
        progress_callback("llm_started", 0, effective_retries)

    gen_prompt = build_generation_prompt(prompt) if prompt else "Generate a classic solitaire diamond ring."

    try:
        llm_resp = await call_llm(
            llm_name,
            system_prompt,
            gen_prompt,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            image_data=image_data,
            image_mime=image_mime,
        )
    except Exception as e:
        logger.error("[STEP 1] FAILED: %s", e)
        return GenerateResult(
            success=False,
            session_id=session_id,
            llm_used=llm_name,
            cost_summary=CostSummary(),
        )

    if progress_callback:
        progress_callback("llm_done", 0, effective_retries)

    initial_code = llm_resp.code
    total_usage: list[UsageInfo] = [llm_resp.usage]
    modules = extract_modules(initial_code)
    logger.info(
        "[STEP 1] Done. %d chars, %d lines, modules: %s",
        len(initial_code), initial_code.count('\n'), modules,
    )

    # Step 2: Run Blender with auto-retry
    logger.info("[STEP 2] Running Blender (with auto-retry)...")
    initial_cost = llm_resp.usage.cost_usd

    code, result, retry_log, retry_usage = await _run_with_retry(
        llm_name=llm_name,
        initial_code=initial_code,
        glb_path=glb_path,
        system_prompt=system_prompt,
        blender_executable=blender_executable,
        blender_timeout=blender_timeout,
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        max_retries=effective_retries,
        max_cost_usd=effective_budget,
        spent_so_far=initial_cost,
        progress_callback=progress_callback,
    )
    total_usage.extend(retry_usage)
    cost_summary = _compute_cost_summary(total_usage)
    modules = extract_modules(code)

    skip_validation = "opus" in llm_name.lower()

    # Save session state
    session_data = {
        "session_id": session_id,
        "prompt": prompt,
        "llm_name": llm_name,
        "code": code,
        "modules": modules,
        "version": 1,
        "current_version": 1,
        "edits": [],
        "version_history": [
            {
                "version": 1,
                "code": code,
                "modules": modules,
                "timestamp": datetime.now().isoformat(),
                "description": "Initial generation",
                "cost": cost_summary.total_usd,
            }
        ],
        "created": datetime.now().isoformat(),
        "retry_log": [e.model_dump() for e in retry_log],
        "cost": cost_summary.total_usd,
        "spatial_report": result.spatial_report,
        "skip_validation": skip_validation,
        "blender_result": {
            "success": result.success,
            "returncode": result.returncode,
            "glb_size": result.glb_size,
            "elapsed": result.elapsed,
            "pipeline_log": result.pipeline_log,
            "error_lines": result.error_lines,
        },
    }
    session_json = session_dir / "session.json"
    session_json.write_text(json.dumps(session_data, indent=2))

    if not result.success:
        logger.error("[STEP 2] FAILED after all retries")
        return GenerateResult(
            success=False,
            session_id=session_id,
            code=code,
            modules=modules,
            retry_log=retry_log,
            cost_summary=cost_summary,
            llm_used=llm_name,
            spatial_report=result.spatial_report,
        )

    logger.info(
        "=== GENERATE COMPLETE: %s | cost=$%.4f ===",
        session_id, cost_summary.total_usd,
    )

    glb_ref: Any = await upload_file(glb_path, mime="model/gltf-binary")
    if isinstance(glb_ref, dict):
        logger.info("GLB uploaded to CAS: %s", glb_ref.get("sha256", "")[:12])
    else:
        logger.debug("Azure not configured; glb_path remains local: %s", glb_ref)

    return GenerateResult(
        success=True,
        session_id=session_id,
        glb_path=glb_ref,
        code=code,
        modules=modules,
        spatial_report=result.spatial_report,
        retry_log=retry_log,
        cost_summary=cost_summary,
        needs_validation=not skip_validation,
        llm_used=llm_name,
        blender_elapsed=result.elapsed,
        glb_size=result.glb_size,
    )
