"""
Shared Blender subprocess execution helper.

Runs a Python script in headless Blender and returns structured output.
Designed to be reused across any tool that needs Blender headless rendering.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BlenderExecResult:
    success: bool
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    elapsed: float = 0.0
    script_path: str = ""


def run_blender_script_sync(
    script_path: str,
    blender_executable: str,
    timeout: int = 120,
) -> BlenderExecResult:
    """Execute an arbitrary Python script in headless Blender."""
    logger.info("Blender exec: %s", script_path)
    t0 = time.time()

    try:
        result = subprocess.run(
            [blender_executable, "-b", "--python", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - t0

        return BlenderExecResult(
            success=result.returncode == 0,
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            elapsed=elapsed,
            script_path=script_path,
        )

    except subprocess.TimeoutExpired:
        logger.error("Blender TIMEOUT (%ds)", timeout)
        return BlenderExecResult(
            success=False,
            elapsed=time.time() - t0,
            script_path=script_path,
        )
    except Exception as e:
        logger.error("Blender EXCEPTION: %s", e)
        return BlenderExecResult(
            success=False,
            elapsed=time.time() - t0,
            script_path=script_path,
        )


async def run_blender_script(
    script_path: str,
    blender_executable: str,
    timeout: int = 120,
) -> BlenderExecResult:
    """Async wrapper — offloads blocking subprocess to thread-pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        run_blender_script_sync,
        script_path,
        blender_executable,
        timeout,
    )
