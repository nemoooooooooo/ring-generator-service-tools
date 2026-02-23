"""
Validation pipeline — orchestrates the full flow:

  1. Receive screenshots + code + user prompt
  2. Send to LLM for structural geometry validation
  3. If INVALID and corrected code returned → re-render via Blender
  4. Return structured result

This is a 1:1 port of the ``/api/validate-with-screenshots`` endpoint
from vibe-designing-3d/app.py (lines 1513-1610).
"""

from __future__ import annotations

import json
import logging
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..schemas import TokenUsage, ValidateRequest, ValidateResult
from .blender_runner import run_blender
from .llm_validator import resolve_model_name, validate_with_model
from .screenshot_resolver import resolve_screenshots

logger = logging.getLogger(__name__)


async def validate_ring(
    request: ValidateRequest,
    master_prompt: str,
    sessions_dir: Path,
    artifact_cache_dir: Path,
    blender_executable: str,
    blender_timeout: int,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
    progress_callback: Callable[[str, int], None] | None = None,
) -> ValidateResult:
    """
    End-to-end ring validation: screenshots → LLM check → optional Blender re-render.

    Mirrors the original ``api_validate_with_screenshots()`` exactly.
    """
    code = request.code
    user_prompt = request.user_prompt
    llm_name = request.llm_name
    session_id = request.session_id or request.request_id or f"val_{uuid.uuid4().hex[:10]}_{int(time.time())}"

    model_name = resolve_model_name(llm_name)

    logger.info(
        "[VALIDATION] %d screenshots for session %s, model=%s (from llm_name=%s)",
        len(request.screenshots), session_id, model_name, llm_name,
    )

    if progress_callback:
        progress_callback("Resolving screenshot artifacts...", 5)

    # Resolve CAS artifact references back to data:image/png;base64,... strings.
    # When running through Temporal, normalise_payload converts data URIs into
    # Azure CAS references. The LLM needs actual image bytes, not pointers.
    screenshots = await resolve_screenshots(
        raw_screenshots=request.screenshots,
        cache_dir=artifact_cache_dir,
    )

    if not screenshots:
        logger.warning("[VALIDATION] No screenshots resolved — skipping validation")
        return ValidateResult(
            is_valid=True,
            message="Validation skipped: no screenshots could be resolved",
            llm_used=model_name,
        )

    logger.info("[VALIDATION] Resolved %d screenshots to data URIs", len(screenshots))

    if progress_callback:
        progress_callback("Sending to LLM for validation...", 15)

    # Step 1: Validate with LLM
    llm_result = await validate_with_model(
        screenshots_b64=screenshots,
        code=code,
        user_prompt=user_prompt,
        master_prompt=master_prompt,
        model_name=model_name,
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
    )

    if progress_callback:
        progress_callback("LLM validation complete", 60)

    tokens = TokenUsage(input_tokens=llm_result.tokens_in, output_tokens=llm_result.tokens_out)

    # Load existing session data if available (for state persistence)
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / "session.json"
    session: dict[str, Any] = {}
    if session_path.exists():
        try:
            session = json.loads(session_path.read_text())
        except Exception:
            logger.warning("Could not load session.json for %s", session_id)

    # Store validation result in session (matches original)
    session["validation"] = {
        "result": {
            "is_valid": llm_result.is_valid,
            "message": llm_result.message,
            "cost": llm_result.cost,
            "tokens": {"input": llm_result.tokens_in, "output": llm_result.tokens_out},
        },
        "timestamp": datetime.now().isoformat(),
    }

    # Step 2: If invalid and corrected code returned, re-render
    if not llm_result.is_valid and llm_result.corrected_code:
        logger.info("[VALIDATION] Regenerating with corrected code...")
        if progress_callback:
            progress_callback("Regenerating with corrected code...", 70)

        glb_path = str(session_dir / "model.glb")

        blender_result = await run_blender(
            script_code=llm_result.corrected_code,
            glb_output_path=glb_path,
            blender_executable=blender_executable,
            timeout=blender_timeout,
        )

        if blender_result.success:
            logger.info("[VALIDATION] Corrected version succeeded!")
            if progress_callback:
                progress_callback("Corrected version rendered", 95)

            # Update session with corrected code and spatial report (matches original)
            session["code"] = llm_result.corrected_code
            session["version"] = session.get("version", 1) + 1
            session["cost"] = session.get("cost", 0) + llm_result.cost
            session["spatial_report"] = blender_result.spatial_report
            try:
                session_path.write_text(json.dumps(session, indent=2))
            except Exception:
                logger.warning("Could not persist session.json for %s", session_id)

            return ValidateResult(
                is_valid=llm_result.is_valid,
                message=llm_result.message,
                regenerated=True,
                corrected_code=llm_result.corrected_code,
                cost=llm_result.cost,
                tokens=tokens,
                glb_path=glb_path,
                llm_used=model_name,
            )
        else:
            logger.error("[VALIDATION] Corrected version FAILED")
            if progress_callback:
                progress_callback("Correction failed, using original", 95)

            return ValidateResult(
                is_valid=True,
                message="Validation corrections failed, using original design",
                regenerated=False,
                cost=llm_result.cost,
                tokens=tokens,
                llm_used=model_name,
            )

    # Step 3: Valid or no corrected code — persist cost and return
    session["cost"] = session.get("cost", 0) + llm_result.cost
    try:
        session_path.write_text(json.dumps(session, indent=2))
    except Exception:
        logger.warning("Could not persist session.json for %s", session_id)

    if progress_callback:
        progress_callback("Validation complete", 95)

    return ValidateResult(
        is_valid=llm_result.is_valid,
        message=llm_result.message,
        regenerated=False,
        cost=llm_result.cost,
        tokens=tokens,
        llm_used=model_name,
    )
