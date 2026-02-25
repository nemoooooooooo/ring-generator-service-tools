"""
Prompt templates for ring editing, part regeneration, and new part addition.

Ported from the vibe-designing-3d monolith (app.py prompt builders)
and adapted for the ring-editor microservice.

Also includes the fix prompt (identical to ring-generator) for the
Blender auto-retry loop.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Edit prompts
# ---------------------------------------------------------------------------

def _spatial_context_block(spatial_report: str | None) -> str:
    """Build a spatial context block if a spatial report is available."""
    if not spatial_report:
        return ""
    return f"""
SPATIAL CONTEXT (current ring geometry):
{spatial_report[:3000]}

Use this spatial data to understand existing mesh positions, bounding boxes, and how parts connect.
"""


def build_edit_prompt(current_code: str, edit_instruction: str, spatial_report: str | None = None) -> str:
    """Full-ring edit: LLM receives entire code + edit instruction."""
    return f"""Here is the COMPLETE current ring script:

```python
{current_code}
```
{_spatial_context_block(spatial_report)}
The user wants this change: "{edit_instruction}"

CRITICAL RULES:
1. Return the COMPLETE updated script — every function, every import, every line.
2. Change ONLY what the user requested. Everything else must be BYTE-FOR-BYTE IDENTICAL.
3. Do NOT rename functions, reorder code, change comments, or "improve" unrelated parts.
4. Keep ALL engineering rules: bmesh only, no bpy.ops.mesh, no materials, nuke+build pattern.
5. ZERO materials, ZERO lighting, ZERO export code.
6. USE modifiers (BEVEL, SUBSURF) for metal quality.
7. Return ONLY Python code. No explanations. No markdown fences."""


def build_smart_edit_prompt(
    full_code: str,
    edit_instruction: str,
    target_module: str,
    spatial_report: str | None = None,
) -> str:
    """Module-targeted edit: LLM focuses on one function but returns full code."""
    return f"""Here is the COMPLETE ring script. The user wants to modify ONLY the function `{target_module}`.

```python
{full_code}
```
{_spatial_context_block(spatial_report)}
User's edit request: "{edit_instruction}"

CRITICAL RULES:
1. Return the COMPLETE script — ALL functions, ALL imports, ALL code.
2. Modify ONLY the function `{target_module}`. Every other function, variable, import, and line of code must remain BYTE-FOR-BYTE IDENTICAL.
3. Keep the same function signature: def {target_module}(...)
4. The modified function must still work with all other functions (shared constants, same return type).
5. Use ONLY bmesh (no bpy.ops.mesh, no bpy.ops.transform). NO materials, NO lighting.
6. Return ONLY Python code. No explanations. No markdown fences."""


# ---------------------------------------------------------------------------
# Part regeneration prompt
# ---------------------------------------------------------------------------

def build_part_regen_prompt(
    current_code: str,
    part_type: str,
    user_description: str,
    part_regen_template: str,
    spatial_report: str | None = None,
) -> str:
    """Regen part: completely rebuild one part using part_regen_prompt.txt template."""
    return f"""Here is the COMPLETE existing ring script:

```python
{current_code}
```
{_spatial_context_block(spatial_report)}
The user wants to REGENERATE the "{part_type}" part of this ring.
User's description: "{user_description}"

{part_regen_template}

CRITICAL:
1. Return the COMPLETE script with the {part_type} function(s) COMPLETELY REWRITTEN.
2. ALL OTHER functions must remain BYTE-FOR-BYTE IDENTICAL.
3. The new {part_type} must use the SAME shared dimension variables.
4. The new {part_type} must connect properly to adjacent parts.
5. Make the new {part_type} aesthetically superior and structurally perfect.
6. ONLY bmesh geometry. NO materials, NO lighting.
7. Return ONLY Python code. No explanations. No markdown fences."""


# ---------------------------------------------------------------------------
# Add new part prompt
# ---------------------------------------------------------------------------

def build_add_part_prompt(current_code: str, part_description: str, spatial_report: str | None = None) -> str:
    """Add a brand-new build_* function to the existing ring code."""
    return f"""Here is the COMPLETE existing ring script:

```python
{current_code}
```
{_spatial_context_block(spatial_report)}
The user wants to ADD A NEW PART to this ring:
"{part_description}"

INSTRUCTIONS:
1. Return the COMPLETE script with a NEW function added for this part.
2. ALL EXISTING functions must remain BYTE-FOR-BYTE IDENTICAL — do NOT touch them.
3. Add a new function (e.g. create_new_part()) that creates the requested geometry.
4. Call your new function from main() BEFORE the final export/join step.
5. The new part must integrate spatially with the existing ring dimensions (use the same shared variables).
6. ONLY bmesh geometry. NO materials, NO lighting.
7. Return ONLY Python code. No explanations. No markdown fences."""


# ---------------------------------------------------------------------------
# Fix prompt (for Blender auto-retry — same as ring-generator)
# ---------------------------------------------------------------------------

def build_fix_prompt(
    code: str,
    error_text: str,
    spatial_report: str | None = None,
) -> str:
    base_prompt = f"""This Blender Python script crashed. Your job: find the ROOT CAUSE and fix it in ONE attempt.

SCRIPT:
```python
{code}
```

ERROR:
{error_text}
"""

    if spatial_report:
        base_prompt += f"""
SPATIAL CONTEXT (from previous attempt):
{spatial_report[:3000]}

This spatial data shows the mesh positions, bounds, and geometry from the last attempt.
Use this to understand where meshes are positioned and how they relate to each other.
"""

    base_prompt += """
DIAGNOSIS STEPS:
1. Read the error traceback — identify the exact line and function that failed.
2. Classify the error:
   - SYNTAX: missing colon, unmatched parenthesis, indentation error → fix the syntax
   - GEOMETRY: face creation failed, empty mesh, degenerate face → fix vertex positions or face winding
   - API: attribute not found, deprecated method → use correct Blender 5.0 API
   - TOPOLOGY: index out of range, bmesh freed → fix vert/face references, add ensure_lookup_table()
   - LOGIC: division by zero, wrong variable, missing import → fix the computation or add import

FIX RULES:
1. Fix ONLY the specific error. Change the MINIMUM number of lines to resolve it.
2. Keep ALL function signatures identical. Keep ALL other functions unchanged.
2.1 keep every other thing line of code 100% same
3. Preserve the exact same ring geometry — only fix what's broken.
4. ONLY bmesh geometry (no bpy.ops.mesh, no bpy.ops.transform).
5. NO materials, NO lighting, NO scene setup.
6. Verify your fix: mentally trace the execution to confirm the error is resolved.
7. Return ONLY Python code. No explanations. No markdown fences."""

    return base_prompt
