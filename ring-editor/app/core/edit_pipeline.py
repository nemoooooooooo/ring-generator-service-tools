"""
Ring edit pipeline — orchestrates the full edit/regen/add-part flow:

  1. Route by operation type (edit, regen-part, add-part)
  2. Build appropriate prompt
  3. Call LLM for code modification
  4. Run Blender with auto-retry (LLM-assisted error fixing)
  5. Save session state with version history
  6. Upload GLB to Azure CAS
  7. Return structured EditResult

This is the core logic ported from the vibe-designing-3d /api/edit,
/api/regen-part, and /api/generate-new-part endpoints.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..schemas import CostSummary, EditRequest, EditResult, RetryEntry
from .blender_runner import BlenderResult, run_blender
from .code_processor import extract_modules
from .llm_client import LLMResponse, UsageInfo, call_llm
from .prompt_builder import (
    build_add_part_prompt,
    build_edit_prompt,
    build_fix_prompt,
    build_part_regen_prompt,
    build_smart_edit_prompt,
)
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
# Retry loop — identical to ring-generator's _run_with_retry()
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
# Operation handlers
# ---------------------------------------------------------------------------

async def _handle_edit(
    request: EditRequest,
    system_prompt: str,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[str, list[UsageInfo], str]:
    """Handle 'edit' operation. Returns (new_code, usage_list, description)."""
    llm_name = request.llm_name

    sr = request.spatial_report or None
    if request.target_module:
        prompt = build_smart_edit_prompt(
            request.code, request.edit_instruction, request.target_module,
            spatial_report=sr,
        )
        desc = f"Edit: {request.edit_instruction[:80]} (target: {request.target_module})"
    else:
        prompt = build_edit_prompt(request.code, request.edit_instruction, spatial_report=sr)
        desc = f"Edit: {request.edit_instruction[:80]}"

    if progress_callback:
        progress_callback("llm_started", 0, 0)

    llm_resp = await call_llm(
        llm_name, system_prompt, prompt,
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )

    if progress_callback:
        progress_callback("llm_done", 0, 0)

    return llm_resp.code, [llm_resp.usage], desc


async def _handle_regen_part(
    request: EditRequest,
    system_prompt: str,
    part_regen_template: str,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[str, list[UsageInfo], str]:
    """Handle 'regen-part' operation. Returns (new_code, usage_list, description)."""
    llm_name = request.llm_name
    user_desc = (
        request.part_description
        if request.part_description
        else f"Regenerate the {request.target_module} with better aesthetics and integration"
    )
    sr = request.spatial_report or None
    prompt = build_part_regen_prompt(
        request.code, request.target_module, user_desc, part_regen_template,
        spatial_report=sr,
    )
    desc = f"Regen part: {request.target_module} — {user_desc[:60]}"

    if progress_callback:
        progress_callback("llm_started", 0, 0)

    llm_resp = await call_llm(
        llm_name, system_prompt, prompt,
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )

    if progress_callback:
        progress_callback("llm_done", 0, 0)

    return llm_resp.code, [llm_resp.usage], desc


async def _handle_add_part(
    request: EditRequest,
    system_prompt: str,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[str, list[UsageInfo], str]:
    """Handle 'add-part' operation. Returns (new_code, usage_list, description)."""
    llm_name = request.llm_name
    sr = request.spatial_report or None
    prompt = build_add_part_prompt(request.code, request.part_description, spatial_report=sr)
    desc = f"Add part: {request.part_description[:80]}"

    if progress_callback:
        progress_callback("llm_started", 0, 0)

    llm_resp = await call_llm(
        llm_name, system_prompt, prompt,
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )

    if progress_callback:
        progress_callback("llm_done", 0, 0)

    return llm_resp.code, [llm_resp.usage], desc


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def edit_ring(
    request: EditRequest,
    system_prompt: str,
    part_regen_template: str,
    sessions_dir: Path,
    blender_executable: str,
    blender_timeout: int,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    max_retries: int = 3,
    max_cost_usd: float = 5.0,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> EditResult:
    """
    End-to-end ring edit pipeline: route → prompt → LLM → Blender → retry → result.
    """
    llm_name = request.llm_name
    operation = request.operation
    session_id = request.session_id or request.request_id or f"s_{uuid.uuid4().hex[:10]}_{int(time.time())}"
    new_version = request.current_version + 1

    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    glb_path = str(session_dir / "model.glb")

    effective_retries = request.max_retries if request.max_retries is not None else max_retries
    effective_budget = request.max_cost_usd if request.max_cost_usd is not None else max_cost_usd

    # Step 1: Route to operation handler and get modified code
    logger.info("[STEP 1] %s operation on session %s (v%d → v%d)...",
                operation.upper(), session_id, request.current_version, new_version)

    try:
        if operation == "edit":
            new_code, usage_list, description = await _handle_edit(
                request, system_prompt,
                anthropic_api_key, gemini_api_key, gemini_model,
                progress_callback,
            )
        elif operation == "regen-part":
            new_code, usage_list, description = await _handle_regen_part(
                request, system_prompt, part_regen_template,
                anthropic_api_key, gemini_api_key, gemini_model,
                progress_callback,
            )
        elif operation == "add-part":
            new_code, usage_list, description = await _handle_add_part(
                request, system_prompt,
                anthropic_api_key, gemini_api_key, gemini_model,
                progress_callback,
            )
        else:
            raise ValueError(f"Unknown operation: {operation}")
    except Exception as e:
        logger.error("[STEP 1] FAILED: %s", e)
        return EditResult(
            success=False,
            session_id=session_id,
            operation=operation,
            llm_used=llm_name,
            cost_summary=CostSummary(),
        )

    logger.info("[STEP 1] Done. %d chars, modules: %s",
                len(new_code), extract_modules(new_code))

    # Step 2: Run Blender with auto-retry
    logger.info("[STEP 2] Running Blender (with auto-retry)...")
    initial_cost = sum(u.cost_usd for u in usage_list)

    code, result, retry_log, retry_usage = await _run_with_retry(
        llm_name=llm_name,
        initial_code=new_code,
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
    usage_list.extend(retry_usage)
    cost_summary = _compute_cost_summary(usage_list)
    modules = extract_modules(code)

    skip_validation = "opus" in llm_name.lower()

    # Step 3: Save session state
    session_data = {
        "session_id": session_id,
        "prompt": request.user_prompt,
        "llm_name": llm_name,
        "code": code,
        "modules": modules,
        "version": new_version,
        "current_version": new_version,
        "edits": [
            {
                "request": description,
                "operation": operation,
                "target_module": request.target_module or "",
                "llm": llm_name,
                "timestamp": datetime.now().isoformat(),
                "version": new_version,
            }
        ],
        "version_history": [
            {
                "version": new_version,
                "code": code,
                "modules": modules,
                "timestamp": datetime.now().isoformat(),
                "description": description,
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
        return EditResult(
            success=False,
            session_id=session_id,
            code=code,
            modules=modules,
            operation=operation,
            description=description,
            version=new_version,
            retry_log=retry_log,
            cost_summary=cost_summary,
            llm_used=llm_name,
            spatial_report=result.spatial_report,
        )

    logger.info(
        "=== %s COMPLETE: %s v%d | cost=$%.4f ===",
        operation.upper(), session_id, new_version, cost_summary.total_usd,
    )

    # Step 4: Upload GLB to Azure CAS
    glb_ref: Any = await upload_file(glb_path, mime="model/gltf-binary")
    if isinstance(glb_ref, dict):
        logger.info("GLB uploaded to CAS: %s", glb_ref.get("sha256", "")[:12])
    else:
        logger.debug("Azure not configured; glb_path remains local: %s", glb_ref)

    return EditResult(
        success=True,
        session_id=session_id,
        glb_path=glb_ref,
        code=code,
        modules=modules,
        operation=operation,
        description=description,
        version=new_version,
        spatial_report=result.spatial_report,
        retry_log=retry_log,
        cost_summary=cost_summary,
        needs_validation=not skip_validation,
        llm_used=llm_name,
        blender_elapsed=result.elapsed,
        glb_size=result.glb_size,
    )
