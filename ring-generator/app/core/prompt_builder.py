"""
Prompt templates for ring generation and error-fixing.

These are exact replicas of the original vibe-designing-3d prompt builders
to ensure identical LLM behaviour and output quality.
"""

from __future__ import annotations


def build_generation_prompt(user_prompt: str) -> str:
    return f"""{user_prompt}

REMINDERS:
- The head/setting grows directly from the band's top — they are ONE connected piece.
- Gems sit INSIDE their settings, not floating. Prongs grip the gem, not pass through it.
- All build_* functions share the same dimension variables so parts line up.
- Use modifiers generously (Bevel, Subsurf, etc.) for quality.
- No materials, no cameras, no lights. Output ONLY geometry code."""


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
