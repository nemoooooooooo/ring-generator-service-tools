"""
Artifact resolver for CAS (Content-Addressable Storage) references.

When running under the Temporal pipeline, large files (like GLBs) arrive as
artifact references with an ``azure://`` URI scheme:
  { "uri": "azure://agentic-artifacts/hashed/<sha256>", "sha256": "abc...", ... }

This module resolves them to local file paths, downloading + caching as needed.
It converts ``azure://`` URIs to signed HTTPS blob URLs for download.

When running standalone, plain file paths pass through unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_AZURE_ACCOUNT = os.getenv("AZURE_ACCOUNT_NAME", "snapwear")
_AZURE_KEY = os.getenv("AZURE_ACCOUNT_KEY", "")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_uri(uri: str) -> str:
    """
    Convert internal URI schemes to downloadable HTTPS URLs.

    azure://container/blob/path
      -> signed SAS URL if AZURE_ACCOUNT_KEY is available
      -> plain HTTPS URL otherwise (works for public containers)
    """
    if not uri.startswith("azure://"):
        return uri

    path_part = uri[len("azure://"):]
    parts = path_part.split("/", 1)
    container = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ""

    base_url = f"https://{_AZURE_ACCOUNT}.blob.core.windows.net/{container}/{blob_name}"

    if not _AZURE_KEY:
        logger.warning("No AZURE_ACCOUNT_KEY set; attempting unsigned download")
        return base_url

    try:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        sas_token = generate_blob_sas(
            account_name=_AZURE_ACCOUNT,
            container_name=container,
            blob_name=blob_name,
            account_key=_AZURE_KEY,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        return f"{base_url}?{sas_token}"
    except ImportError:
        import base64
        import hmac

        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=30)
        start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expiry_str = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")

        perms = "r"
        resource = "b"
        string_to_sign = (
            f"{perms}\n{start_str}\n{expiry_str}\n"
            f"/blob/{_AZURE_ACCOUNT}/{container}/{blob_name}\n"
            f"\n\nhttps\n2024-11-04\n{resource}\n\n\n\n\n\n\n"
        )
        key_bytes = base64.b64decode(_AZURE_KEY)
        sig = base64.b64encode(
            hmac.new(key_bytes, string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

        sas = (
            f"sv=2024-11-04&st={quote(start_str)}&se={quote(expiry_str)}"
            f"&sr={resource}&sp={perms}&sig={quote(sig)}"
        )
        return f"{base_url}?{sas}"


async def resolve_glb_path(
    glb_ref: Any,
    cache_dir: Path,
    http_timeout: float = 120.0,
) -> Path:
    """
    Resolve a GLB reference to a local file path.

    Accepts:
      - str: local file path (returned as-is if exists), or HTTP(S)/azure:// URL
      - dict with "uri" key: CAS artifact reference (downloaded + cached)
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(glb_ref, str):
        local = Path(glb_ref)
        if local.is_file():
            return local
        if glb_ref.startswith(("http://", "https://", "azure://")):
            download_url = _resolve_uri(glb_ref)
            return await _download_and_cache(download_url, None, cache_dir, http_timeout)
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

        download_url = _resolve_uri(uri)
        return await _download_and_cache(download_url, sha256, cache_dir, http_timeout)

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
