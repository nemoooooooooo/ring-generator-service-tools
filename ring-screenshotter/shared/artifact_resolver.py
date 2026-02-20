"""
Artifact resolver for CAS (Content-Addressable Storage) references.

When running under the Temporal pipeline, large files (like GLBs) arrive as
artifact references: { "uri": "https://...", "sha256": "abc...", ... }
This module resolves them to local file paths, downloading + caching as needed.

When running standalone, plain file paths pass through unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def resolve_glb_path(
    glb_ref: Any,
    cache_dir: Path,
    http_timeout: float = 120.0,
) -> Path:
    """
    Resolve a GLB reference to a local file path.

    Accepts:
      - str: local file path (returned as-is if exists)
      - dict with "uri" key: CAS artifact reference (downloaded + cached)
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(glb_ref, str):
        local = Path(glb_ref)
        if local.is_file():
            return local
        if glb_ref.startswith(("http://", "https://")):
            return await _download_and_cache(glb_ref, None, cache_dir, http_timeout)
        raise FileNotFoundError(f"GLB file not found: {glb_ref}")

    if isinstance(glb_ref, dict):
        uri = glb_ref.get("uri", "")
        sha256 = glb_ref.get("sha256")

        if not uri:
            raise ValueError("Artifact reference missing 'uri' field")

        if sha256:
            cached = cache_dir / f"{sha256}.glb"
            if cached.is_file():
                logger.info("CAS cache hit: %s", sha256[:12])
                return cached

        return await _download_and_cache(uri, sha256, cache_dir, http_timeout)

    raise TypeError(f"Unsupported glb_path type: {type(glb_ref)}")


async def _download_and_cache(
    url: str,
    expected_sha256: str | None,
    cache_dir: Path,
    timeout: float,
) -> Path:
    logger.info("Downloading artifact: %s", url[:120])
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content

    actual_sha = _sha256_bytes(data)
    if expected_sha256 and actual_sha != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch: expected {expected_sha256[:16]}... got {actual_sha[:16]}..."
        )

    dest = cache_dir / f"{actual_sha}.glb"
    if not dest.exists():
        dest.write_bytes(data)
        logger.info("Cached artifact: %s (%d bytes)", actual_sha[:12], len(data))

    return dest
