"""
Code preprocessing, extraction, and analysis utilities.

All functions here are pure/stateless and mirror the original vibe-designing-3d
logic byte-for-byte so generated rings are identical.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Safety injection — wraps bm.faces.new() with error-safe helper
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


def preprocess_code(code: str) -> str:
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


# ---------------------------------------------------------------------------
# Code extraction — pull Python from markdown fences or raw LLM output
# ---------------------------------------------------------------------------

def extract_code(raw: str) -> str:
    if "```python" in raw:
        code = raw.split("```python", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        code = raw.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        code = raw.strip()
    return code


# ---------------------------------------------------------------------------
# Module extraction — discover user-defined ring geometry functions
# ---------------------------------------------------------------------------

_SKIP_FUNCTIONS = frozenset({
    'nuke', 'build', 'mk', 'quad_bridge', 'make_circle_verts',
    'set_smooth', 'add_subsurf', 'add_bevel', 'add_solidify',
    'ngon', 'safe_set', '_safe_face',
})


def extract_modules(code: str) -> list[str]:
    """Pull function names from code, excluding known utility functions."""
    modules: list[str] = []
    for line in code.split('\n'):
        ls = line.strip()
        if ls.startswith('def ') and '(' in ls:
            fname = ls.split('def ')[1].split('(')[0]
            if fname not in _SKIP_FUNCTIONS:
                modules.append(fname)
    return modules


# ---------------------------------------------------------------------------
# Strip __name__ guard — build() is called by export wrapper
# ---------------------------------------------------------------------------

def strip_main_guard(code: str) -> str:
    return _MAIN_GUARD_RE.sub(
        '# (build call moved to auto-export section)',
        code,
    )
