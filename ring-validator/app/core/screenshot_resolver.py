"""
Screenshot artifact resolver.

When running through the Temporal pipeline, screenshot data URIs
(``data:image/png;base64,...``) get CAS-ified by ``normalise_payload``
into artifact references like::

    {
        "uri": "azure://agentic-artifacts/hashed/<sha256>",
        "sha256": "...",
        "type": "image/png",
        "bytes": 12345
    }

This module downloads those artifacts and reconstructs the original
``data:image/png;base64,...`` strings so the validation LLM receives
real images — exactly as the original vibe-designing-3d project did.

Supported input shapes (per screenshot element):

1. ``str`` starting with ``data:``  — pass-through (standalone mode)
2. ``dict`` with ``name`` + ``data_uri`` (str)  — extract ``data_uri``
3. ``dict`` with ``name`` + ``data_uri`` (CAS dict)  — download & encode
4. ``dict`` with ``uri`` key  — bare CAS reference, download & encode
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from shared.artifact_resolver import _resolve_uri

logger = logging.getLogger(__name__)


async def resolve_screenshots(
    raw_screenshots: list[Any],
    cache_dir: Path,
    http_timeout: float = 60.0,
) -> list[str]:
    """
    Normalise a heterogeneous list of screenshot references into
    a clean list of ``data:<mime>;base64,...`` strings.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    resolved: list[str] = []

    for idx, item in enumerate(raw_screenshots):
        try:
            data_uri = await _resolve_single(item, cache_dir, http_timeout)
            if data_uri:
                resolved.append(data_uri)
            else:
                logger.warning("Screenshot %d resolved to empty — skipping", idx)
        except Exception as exc:
            logger.error("Failed to resolve screenshot %d: %s", idx, exc)

    logger.info(
        "Resolved %d/%d screenshots to data URIs",
        len(resolved), len(raw_screenshots),
    )
    return resolved


async def _resolve_single(
    item: Any,
    cache_dir: Path,
    http_timeout: float,
) -> str | None:
    """Resolve one screenshot element to a data URI string."""

    # Shape 1: already a data URI string
    if isinstance(item, str):
        if item.startswith("data:"):
            return item
        if item.startswith(("http://", "https://", "azure://")):
            return await _download_as_data_uri(item, None, "image/png", cache_dir, http_timeout)
        return item

    if not isinstance(item, dict):
        logger.warning("Unexpected screenshot type: %s", type(item))
        return None

    # Shape 4: bare CAS reference {"uri": "azure://...", "sha256": "...", "type": "image/png"}
    if "uri" in item and "data_uri" not in item:
        mime = item.get("type", "image/png")
        sha256 = item.get("sha256")
        return await _download_as_data_uri(item["uri"], sha256, mime, cache_dir, http_timeout)

    # Shapes 2 & 3: screenshot object {"name": "...", "data_uri": ...}
    data_uri_field = item.get("data_uri")
    if data_uri_field is None:
        logger.warning("Screenshot dict missing 'data_uri': %s", list(item.keys()))
        return None

    # Shape 2: data_uri is already a data URI string
    if isinstance(data_uri_field, str):
        if data_uri_field.startswith("data:"):
            return data_uri_field
        if data_uri_field.startswith(("http://", "https://", "azure://")):
            return await _download_as_data_uri(
                data_uri_field, None, "image/png", cache_dir, http_timeout,
            )
        return data_uri_field

    # Shape 3: data_uri is a CAS artifact reference dict
    if isinstance(data_uri_field, dict) and "uri" in data_uri_field:
        mime = data_uri_field.get("type", "image/png")
        sha256 = data_uri_field.get("sha256")
        return await _download_as_data_uri(
            data_uri_field["uri"], sha256, mime, cache_dir, http_timeout,
        )

    logger.warning("Unrecognised data_uri format: %s", type(data_uri_field))
    return None


async def _download_as_data_uri(
    uri: str,
    expected_sha256: str | None,
    mime: str,
    cache_dir: Path,
    timeout: float,
) -> str:
    """Download an artifact and return it as a ``data:<mime>;base64,...`` string."""
    import hashlib

    download_url = _resolve_uri(uri)
    logger.info("Downloading screenshot artifact: %s", download_url[:120])

    # Check local cache first
    if expected_sha256:
        cached = cache_dir / f"{expected_sha256}.png"
        if cached.is_file():
            logger.info("Screenshot cache hit: %s", expected_sha256[:12])
            raw_bytes = cached.read_bytes()
            b64 = base64.b64encode(raw_bytes).decode("utf-8")
            return f"data:{mime};base64,{b64}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.get(download_url)
        resp.raise_for_status()
        raw_bytes = resp.content

    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha256 and actual_sha != expected_sha256:
        logger.warning(
            "Screenshot SHA-256 mismatch: expected %s got %s",
            expected_sha256[:16], actual_sha[:16],
        )

    # Cache for future use
    cache_path = cache_dir / f"{actual_sha}.png"
    if not cache_path.exists():
        cache_path.write_bytes(raw_bytes)

    b64 = base64.b64encode(raw_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"
