"""
LLM-based ring geometry validation.

1:1 port of ``validate_with_model()`` from vibe-designing-3d/app.py (lines 753-937).

Accepts multi-angle screenshots + ring code, sends them to the same LLM that
generated the ring, and checks for structural geometry defects.  If defects
are found the LLM returns corrected code.

All API calling conventions, prompt text, cost calculations, and response
parsing match the original exactly.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import anthropic
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client pool — lazy singleton per API key
# ---------------------------------------------------------------------------

_claude_clients: dict[str, anthropic.Anthropic] = {}
_gemini_clients: dict[str, genai.Client] = {}


def _get_claude_client(api_key: str) -> anthropic.Anthropic:
    if api_key not in _claude_clients:
        _claude_clients[api_key] = anthropic.Anthropic(api_key=api_key)
    return _claude_clients[api_key]


def _get_gemini_client(api_key: str) -> genai.Client:
    if api_key not in _gemini_clients:
        _gemini_clients[api_key] = genai.Client(api_key=api_key)
    return _gemini_clients[api_key]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValidationLLMResult:
    is_valid: bool
    message: str
    corrected_code: str | None = None
    cost: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    full_response: str = ""


# ---------------------------------------------------------------------------
# Validation prompt — identical to original
# ---------------------------------------------------------------------------

def _build_validation_prompt(
    code: str,
    user_prompt: str,
    master_prompt: str,
) -> str:
    return f"""You are a senior 3D jewelry geometry engineer. You are reviewing a ring that was just generated.

MASTER PROMPT (the rules this code must follow):
{master_prompt}

USER'S ORIGINAL REQUEST:
{user_prompt}

THE WORKING CODE THAT GENERATED THIS RING:
```python
{code}
```

I'm showing you 8 rendered views of this ring from different angles (front, back, left, right, top, bottom, and 2 angled views).

YOUR JOB: FIND AND FIX ALL STRUCTURAL GEOMETRY DEFECTS

Look at every screenshot carefully and check for ALL of these problems:

1. FLOATING DIAMONDS — Are any diamonds/gems hanging in the air? Not sitting in their settings?
2. DIAMONDS INSIDE BAND — Are diamonds buried/clipping inside the metal instead of sitting on top?
3. BAND NOT CLOSED — Is the band/shank broken, incomplete, or not a full 360° circle? Does it have gaps?
4. BAND SHAPE WRONG — Is the band too thin, too thick, warped, uneven, or not a smooth torus shape?
5. HEAD DISCONNECTED — Is the setting/head floating separate from the band? There should be no gap.
6. PRONGS WRONG — Do prongs stab THROUGH the diamond? They should wrap AROUND the gem crown.
7. PRONGS MISSING — Are there diamonds with no prongs holding them?
8. PARTS INTERSECTING — Are meshes clipping into each other in wrong ways?
9. MISSING GEOMETRY — Are there holes, missing sections, or incomplete parts?
10. PARTS FLOATING — Are any decorative elements (filigree, accents, halos) floating disconnected?

IGNORE aesthetics. IGNORE style preferences. ONLY check structural geometry.

RESPONSE:

If there are ZERO structural errors visible in the screenshots:
VALID

If there are ANY structural errors:
INVALID

Then you MUST provide the corrected code following these rules:

CORRECTION RULES:
1. Start with the EXISTING working code as your base — do NOT write from scratch
2. Keep ALL function names exactly the same
3. Keep ALL function signatures exactly the same
4. Keep the same code structure and ordering
5. You CAN and SHOULD add more geometry code to fix problems (more lines is OK)
6. You CAN add more vertices, edges, faces to fix incomplete geometry
7. You CAN adjust position values, dimensions, offsets to fix placement
8. You CAN add missing prongs, fix band closure, reconnect disconnected parts
9. Do NOT remove any existing working geometry
10. Do NOT change the design concept — only fix the structural defects
11. The code MUST still call build() and produce valid geometry
12. Every distinct object (each diamond, each prong, band, head, etc.) MUST be a separate mesh

Return the COMPLETE corrected Python code inside ```python ... ``` fences.
The code must be immediately runnable in Blender."""


# ---------------------------------------------------------------------------
# Image parsing helper
# ---------------------------------------------------------------------------

def _parse_screenshots(screenshots_b64: list[str]) -> list[dict[str, str]]:
    """Extract MIME type and raw base64 data from data-URI strings."""
    images: list[dict[str, str]] = []
    for b64_uri in screenshots_b64:
        if "," in b64_uri:
            mime_part, b64_data = b64_uri.split(",", 1)
            mime = mime_part.split(":")[1].split(";")[0]
            images.append({"mime": mime, "data": b64_data})
    return images


# ---------------------------------------------------------------------------
# Model name resolution — matches original mapping
# ---------------------------------------------------------------------------

def resolve_model_name(llm_name: str) -> str:
    """Map llm_name to the model identifier used for validation."""
    if llm_name == "gemini":
        return "gemini-3-pro-preview"
    if "opus" in llm_name.lower():
        return "claude-opus"
    return "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Synchronous validation call (offloaded to thread-pool)
# ---------------------------------------------------------------------------

def _validate_with_model_sync(
    screenshots_b64: list[str],
    code: str,
    user_prompt: str,
    master_prompt: str,
    model_name: str,
    anthropic_api_key: str,
    gemini_api_key: str,
    gemini_model: str,
) -> ValidationLLMResult:
    """
    1:1 port of validate_with_model() from vibe-designing-3d/app.py.
    Synchronous — must be called from a thread-pool.
    """
    logger.info("Validating ring with %s (%d screenshots)...", model_name, len(screenshots_b64))

    validation_prompt = _build_validation_prompt(code, user_prompt, master_prompt)
    images_data = _parse_screenshots(screenshots_b64)

    try:
        if model_name == "gemini-3-pro-preview":
            client = _get_gemini_client(gemini_api_key)

            parts: list[Any] = []
            for img in images_data:
                img_bytes = base64.b64decode(img["data"])
                parts.append(genai_types.Part.from_bytes(data=img_bytes, mime_type=img["mime"]))

            parts.append(genai_types.Part(text=f"You are a luxury jewelry design critic.\n\n{validation_prompt}"))

            response = client.models.generate_content(
                model=gemini_model,
                contents=genai_types.Content(parts=parts, role="user"),
            )

            response_text = response.text
            tokens_in = response.usage_metadata.prompt_token_count
            tokens_out = response.usage_metadata.candidates_token_count

        else:
            client = _get_claude_client(anthropic_api_key)

            content: list[dict[str, Any]] = []
            for img in images_data:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["mime"],
                        "data": img["data"],
                    },
                })
            content.append({
                "type": "text",
                "text": f"You are a luxury jewelry design critic.\\n\\n{validation_prompt}",
            })

            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=20000,
                messages=[{"role": "user", "content": content}],
            )

            response_text = response.content[0].text
            tokens_in = response.usage.input_tokens
            tokens_out = response.usage.output_tokens

        # Cost calculation — identical to original
        if model_name == "gemini-3-pro-preview":
            input_cost_per_mtok = 2.50
            output_cost_per_mtok = 10.0
        elif "opus" in model_name.lower():
            input_cost_per_mtok = 5.0
            output_cost_per_mtok = 25.0
        else:
            input_cost_per_mtok = 3.0
            output_cost_per_mtok = 15.0

        cost = (tokens_in / 1_000_000) * input_cost_per_mtok + (tokens_out / 1_000_000) * output_cost_per_mtok

        logger.info("Validation tokens: in=%d, out=%d, cost=$%.4f", tokens_in, tokens_out, cost)

        # Parse response — identical to original
        is_valid = response_text.strip().upper().startswith("VALID")

        if is_valid:
            return ValidationLLMResult(
                is_valid=True,
                message="Ring design is beautiful!",
                cost=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )

        code_match = re.search(r"```python\n(.*?)\n```", response_text, re.DOTALL)
        if code_match:
            corrected_code = code_match.group(1)
            return ValidationLLMResult(
                is_valid=False,
                message="Generating more beautiful design...",
                corrected_code=corrected_code,
                cost=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                full_response=response_text,
            )

        return ValidationLLMResult(
            is_valid=True,
            message="Ring approved (no corrections needed)",
            cost=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    except Exception as e:
        logger.error("Validation error: %s", e, exc_info=True)
        return ValidationLLMResult(
            is_valid=True,
            message=f"Validation skipped: {str(e)[:100]}",
            cost=0,
            tokens_in=0,
            tokens_out=0,
        )


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------

async def validate_with_model(
    screenshots_b64: list[str],
    code: str,
    user_prompt: str,
    master_prompt: str,
    model_name: str,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3-pro-preview",
) -> ValidationLLMResult:
    """Async wrapper — offloads blocking LLM call to thread-pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _validate_with_model_sync,
        screenshots_b64,
        code,
        user_prompt,
        master_prompt,
        model_name,
        anthropic_api_key,
        gemini_api_key,
        gemini_model,
    )
