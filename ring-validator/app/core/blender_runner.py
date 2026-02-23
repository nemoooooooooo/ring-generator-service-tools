"""
Blender headless execution for re-rendering corrected code.

Identical to ring-generator's blender_runner — scene clear, safety
preprocessing, auto build() + export, spatial report, GLB export.

Used when the validation LLM returns corrected code that needs to be
compiled into a new GLB.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BlenderResult:
    success: bool
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    pipeline_log: list[str] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    glb_exists: bool = False
    glb_size: int = 0
    elapsed: float = 0.0
    script_path: str = ""
    spatial_report: str = ""


# ---------------------------------------------------------------------------
# Code preprocessing — identical to original
# ---------------------------------------------------------------------------

_SAFE_HELPER = '''
# ===== AUTO-INJECTED SAFETY =====
def _safe_face(_bm_arg, _verts_arg):
    try:
        if len(_verts_arg) < 3:
            return None
        if len(set(id(v) for v in _verts_arg)) != len(_verts_arg):
            return None
        return _bm_arg.faces.new(_verts_arg)
    except (ValueError, IndexError, TypeError):
        return None
# ===== END SAFETY =====
'''

_FACES_NEW_RE = re.compile(r'(\w+)\.faces\.new\((\[.*?\])\)')
_MAIN_GUARD_RE = re.compile(
    r'if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*\n\s*build\(\)'
)


def _preprocess_code(code: str) -> str:
    """Inject _safe_face helper and wrap bm.faces.new([...]) calls."""
    lines = code.split('\n')
    last_import = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            last_import = i
    lines.insert(last_import + 1, _SAFE_HELPER)
    code = '\n'.join(lines)
    code = _FACES_NEW_RE.sub(r'_safe_face(\1, \2)', code)
    return code


def _strip_main_guard(code: str) -> str:
    return _MAIN_GUARD_RE.sub(
        '# (build call moved to auto-export section)',
        code,
    )


# ---------------------------------------------------------------------------
# Scene clear — prepended to every script
# ---------------------------------------------------------------------------

_SCENE_CLEAR = """
# ========================= AUTO SCENE CLEAR =========================
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
for m in list(bpy.data.meshes):
    bpy.data.meshes.remove(m)
for mat in list(bpy.data.materials):
    bpy.data.materials.remove(mat)
print("[PIPELINE] Scene cleared")
# ========================= END SCENE CLEAR =========================

"""


def _build_export_code(glb_output_path: str) -> str:
    return f"""

# ========================= AUTO BUILD + EXPORT =========================
import bpy, os, traceback as _tb
from mathutils import Vector

_output = r"{glb_output_path}"
os.makedirs(os.path.dirname(_output), exist_ok=True)

print("[PIPELINE] Running build()...")
try:
    build()
    print("[PIPELINE] build() completed")
except Exception as _be:
    print(f"[PIPELINE] build() error: {{_be}}")
    _tb.print_exc()
    print("[PIPELINE] Attempting partial export...")

_obj_count = len([o for o in bpy.data.objects if o.type == 'MESH'])
print(f"[PIPELINE] Scene has {{_obj_count}} mesh objects")

# ========================= SPATIAL REPORT GENERATION =========================
print("===SPATIAL_REPORT_START===")
try:
    for _obj in bpy.data.objects:
        if _obj.type == 'MESH':
            _mesh = _obj.data
            _loc = _obj.location
            _rot = _obj.rotation_euler
            _scale = _obj.scale

            _verts = len(_mesh.vertices)
            _edges = len(_mesh.edges)
            _faces = len(_mesh.polygons)

            _bbox = [_obj.matrix_world @ Vector(v) for v in _obj.bound_box]
            _bbox_min = Vector((min([v.x for v in _bbox]), min([v.y for v in _bbox]), min([v.z for v in _bbox])))
            _bbox_max = Vector((max([v.x for v in _bbox]), max([v.y for v in _bbox]), max([v.z for v in _bbox])))

            _parent = _obj.parent.name if _obj.parent else "None"
            _mods = [m.type for m in _obj.modifiers]

            print(f"MESH: {{_obj.name}}")
            print(f"  Location: {{_loc.x:.4f}}, {{_loc.y:.4f}}, {{_loc.z:.4f}}")
            print(f"  Rotation: {{_rot.x:.4f}}, {{_rot.y:.4f}}, {{_rot.z:.4f}}")
            print(f"  Scale: {{_scale.x:.4f}}, {{_scale.y:.4f}}, {{_scale.z:.4f}}")
            print(f"  Geometry: {{_verts}} verts, {{_edges}} edges, {{_faces}} faces")
            print(f"  BBox Min: {{_bbox_min.x:.4f}}, {{_bbox_min.y:.4f}}, {{_bbox_min.z:.4f}}")
            print(f"  BBox Max: {{_bbox_max.x:.4f}}, {{_bbox_max.y:.4f}}, {{_bbox_max.z:.4f}}")
            print(f"  Parent: {{_parent}}")
            print(f"  Modifiers: {{_mods}}")
            print("---")
except Exception as _spatial_err:
    print(f"Spatial report generation failed: {{_spatial_err}}")
print("===SPATIAL_REPORT_END===")
# ========================= END SPATIAL REPORT =========================

if _obj_count == 0:
    print("[PIPELINE] No mesh objects to export!")
else:
    bpy.ops.object.select_all(action='SELECT')
    print(f"[PIPELINE] Exporting GLB to: {{_output}}")
    try:
        bpy.ops.export_scene.gltf(
            filepath=_output,
            export_format='GLB',
            use_selection=True,
            export_apply=True,
            export_animations=False,
            export_cameras=False,
            export_lights=False
        )
        _size = os.path.getsize(_output)
        print(f"[PIPELINE] GLB exported: {{_size}} bytes")
    except Exception as _e:
        print(f"[PIPELINE] Export FAILED: {{_e}}")
        _tb.print_exc()
"""


def _extract_spatial_report(stdout: str) -> str:
    if "===SPATIAL_REPORT_START===" in stdout and "===SPATIAL_REPORT_END===" in stdout:
        return stdout.split("===SPATIAL_REPORT_START===")[1].split("===SPATIAL_REPORT_END===")[0].strip()
    return ""


# ---------------------------------------------------------------------------
# Synchronous runner (offloaded to thread-pool by caller)
# ---------------------------------------------------------------------------

def run_blender_sync(
    script_code: str,
    glb_output_path: str,
    blender_executable: str,
    timeout: int = 300,
) -> BlenderResult:
    """Execute a Blender script headlessly. Returns structured result."""
    import subprocess

    session_dir = os.path.dirname(glb_output_path)
    script_path = os.path.join(session_dir, "ring_script.py")

    script_code = _preprocess_code(script_code)
    script_code = _strip_main_guard(script_code)

    full_script = _SCENE_CLEAR + script_code + _build_export_code(glb_output_path)

    os.makedirs(session_dir, exist_ok=True)
    with open(script_path, "w") as f:
        f.write(full_script)

    cmd = [blender_executable, "-b", "--python", script_path]
    logger.info("Running Blender: %s", script_path)
    t0 = time.time()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - t0

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        pipeline_lines = [l for l in stdout.split("\n") if "[PIPELINE]" in l]
        error_lines = [
            l for l in (stdout + "\n" + stderr).split("\n")
            if "Error" in l or "Traceback" in l or "error" in l.lower()
        ]

        spatial_report = _extract_spatial_report(stdout)

        glb_exists = os.path.isfile(glb_output_path)
        glb_size = os.path.getsize(glb_output_path) if glb_exists else 0

        # GLB must be at least 1KB to have real geometry (172 bytes = empty)
        success = glb_exists and glb_size > 1024

        return BlenderResult(
            success=success,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
            pipeline_log=pipeline_lines,
            error_lines=error_lines,
            glb_exists=glb_exists,
            glb_size=glb_size,
            elapsed=elapsed,
            script_path=script_path,
            spatial_report=spatial_report,
        )

    except subprocess.TimeoutExpired:
        logger.error("Blender TIMEOUT (%ds)", timeout)
        return BlenderResult(
            success=False,
            error_lines=["TimeoutExpired"],
            elapsed=time.time() - t0,
        )
    except Exception as e:
        logger.error("Blender EXCEPTION: %s", e)
        return BlenderResult(
            success=False,
            error_lines=[str(e)],
            elapsed=time.time() - t0,
        )


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------

async def run_blender(
    script_code: str,
    glb_output_path: str,
    blender_executable: str,
    timeout: int = 300,
) -> BlenderResult:
    """Async wrapper — offloads blocking subprocess to thread-pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        run_blender_sync,
        script_code,
        glb_output_path,
        blender_executable,
        timeout,
    )
