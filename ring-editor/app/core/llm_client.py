"""
LLM client abstraction for Claude and Gemini.

Preserves the exact calling conventions, streaming, retry-on-overload,
and cost tracking from the original vibe-designing-3d pipeline.
Runs LLM calls in a thread-pool so the async event loop stays free.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic
from google import genai
from google.genai import types as genai_types

from .code_processor import extract_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageInfo:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "input_cost_per_mtok": self.input_cost_per_mtok,
            "output_cost_per_mtok": self.output_cost_per_mtok,
            "cost_usd": self.cost_usd,
        }


@dataclass
class LLMResponse:
    code: str
    usage: UsageInfo
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Client pool — lazy singleton per API key to avoid re-creating on every call
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
# Claude (sync, runs in thread-pool)
# ---------------------------------------------------------------------------

def _call_claude_sync(
    api_key: str,
    system: str,
    prompt: str,
    image_data: bytes | None = None,
    image_mime: str | None = None,
    model: str = "claude-opus-4-6",
    max_tokens: int = 20000,
) -> LLMResponse:
    client = _get_claude_client(api_key)
    logger.info("Calling Claude (%s, image=%s)...", model, "yes" if image_data else "no")
    t0 = time.time()

    raw_prompt = f"{system}\n\n---\n\nUser Request: {prompt}"

    if image_data and image_mime:
        b64 = base64.b64encode(image_data).decode("utf-8")
        user_content: Any = [
            {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": b64}},
            {"type": "text", "text": raw_prompt},
        ]
    else:
        user_content = raw_prompt

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            raw = ""
            usage_info = UsageInfo(model=model)
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                for text in stream.text_stream:
                    raw += text
                final = stream.get_final_message()
                if final and hasattr(final, 'usage') and final.usage:
                    if "sonnet" in model:
                        in_cost, out_cost = 3.0, 15.0
                    else:
                        in_cost, out_cost = 15.0, 75.0
                    cost = round(
                        final.usage.input_tokens / 1_000_000 * in_cost
                        + final.usage.output_tokens / 1_000_000 * out_cost,
                        4,
                    )
                    usage_info = UsageInfo(
                        model=model,
                        input_tokens=final.usage.input_tokens,
                        output_tokens=final.usage.output_tokens,
                        input_cost_per_mtok=in_cost,
                        output_cost_per_mtok=out_cost,
                        cost_usd=cost,
                    )
                    logger.info(
                        "Claude (%s) tokens: in=%d, out=%d, cost=$%.4f",
                        model, usage_info.input_tokens, usage_info.output_tokens, cost,
                    )

            elapsed = time.time() - t0
            logger.info("Claude responded: %.1fs, %d chars", elapsed, len(raw))
            return LLMResponse(code=extract_code(raw), usage=usage_info, elapsed_seconds=elapsed)

        except Exception as e:
            err_str = str(e).lower()
            err_repr = repr(e).lower()
            is_overloaded = (
                'overloaded' in err_str
                or 'overloaded' in err_repr
                or '529' in err_str
                or getattr(e, 'status_code', None) == 529
                or (isinstance(e, anthropic.APIStatusError) and getattr(e, 'status_code', 0) == 529)
            )
            if is_overloaded and attempt < max_retries:
                wait = attempt * 15
                logger.warning("Claude overloaded (attempt %d/%d), retrying in %ds...", attempt, max_retries, wait)
                time.sleep(wait)
                continue
            raise


# ---------------------------------------------------------------------------
# Gemini (sync, runs in thread-pool)
# ---------------------------------------------------------------------------

def _call_gemini_sync(
    api_key: str,
    gemini_model: str,
    system: str,
    prompt: str,
    image_data: bytes | None = None,
    image_mime: str | None = None,
) -> LLMResponse:
    client = _get_gemini_client(api_key)
    logger.info("Calling Gemini (%s, image=%s)...", gemini_model, "yes" if image_data else "no")
    t0 = time.time()

    raw_prompt = f"{system}\n\n---\n\nUser Request: {prompt}"

    if image_data and image_mime:
        contents: Any = [
            genai_types.Part.from_bytes(data=image_data, mime_type=image_mime),
            raw_prompt,
        ]
    else:
        contents = raw_prompt

    config = genai_types.GenerateContentConfig(
        maxOutputTokens=65536,
        temperature=1.0,
        topP=0.95,
        thinkingConfig=genai_types.ThinkingConfig(thinkingBudget=10000),
    )

    response = client.models.generate_content(
        model=gemini_model,
        contents=contents,
        config=config,
    )
    raw = response.text

    usage_info = UsageInfo(model=gemini_model)
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        um = response.usage_metadata
        input_tok = getattr(um, 'prompt_token_count', 0) or 0
        output_tok = getattr(um, 'candidates_token_count', 0) or 0
        cost = round(input_tok / 1_000_000 * 1.25 + output_tok / 1_000_000 * 10.0, 4)
        usage_info = UsageInfo(
            model=gemini_model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            input_cost_per_mtok=1.25,
            output_cost_per_mtok=10.0,
            cost_usd=cost,
        )
        logger.info("Gemini tokens: in=%d, out=%d, cost=$%.4f", input_tok, output_tok, cost)

    elapsed = time.time() - t0
    logger.info("Gemini responded: %.1fs, %d chars", elapsed, len(raw))
    return LLMResponse(code=extract_code(raw), usage=usage_info, elapsed_seconds=elapsed)


# ---------------------------------------------------------------------------
# Unified async interface
# ---------------------------------------------------------------------------

async def call_llm(
    llm_name: str,
    system_prompt: str,
    user_prompt: str,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3-pro-preview",
    image_data: bytes | None = None,
    image_mime: str | None = None,
) -> LLMResponse:
    """
    Async wrapper that offloads the blocking LLM call to a thread-pool.
    Returns (code, usage_info) exactly like the original call_llm().
    """
    loop = asyncio.get_running_loop()

    if llm_name == "gemini":
        if not gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        return await loop.run_in_executor(
            None,
            _call_gemini_sync,
            gemini_api_key,
            gemini_model,
            system_prompt,
            user_prompt,
            image_data,
            image_mime,
        )
    else:
        if not anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        if llm_name == "claude-sonnet":
            model = "claude-sonnet-4-6"
        else:
            model = "claude-opus-4-6"
        return await loop.run_in_executor(
            None,
            _call_claude_sync,
            anthropic_api_key,
            system_prompt,
            user_prompt,
            image_data,
            image_mime,
            model,
        )
