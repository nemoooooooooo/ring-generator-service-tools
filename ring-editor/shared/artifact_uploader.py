"""
Artifact uploader for CAS (Content-Addressable Storage).

Uploads files to Azure Blob Storage using SHA-256 content-addressing,
producing CAS reference dicts compatible with the Temporal pipeline's
``normalise_payload`` / ``resolve_glb_path`` format:

    {"uri": "azure://<container>/hashed/<sha256>", "sha256": "...", "type": "...", "bytes": N}

When ``AZURE_ACCOUNT_KEY`` is not set the upload is skipped and the local
file path is returned as-is.  This keeps the tool functional both in
standalone mode (dev) and when orchestrated through Temporal (prod).

Upload uses httpx PUT against the Azure Blob REST API with a self-signed
SAS token — no ``azure-storage-blob`` SDK required (though it will be
used for SAS generation when available).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
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
_AZURE_CONTAINER = os.getenv("AZURE_CONTAINER_NAME", "agentic-artifacts")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _generate_write_sas(container: str, blob_name: str) -> str:
    """Generate a SAS token with create+write permissions for a blob."""
    try:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        return generate_blob_sas(
            account_name=_AZURE_ACCOUNT,
            container_name=container,
            blob_name=blob_name,
            account_key=_AZURE_KEY,
            permission=BlobSasPermissions(read=True, write=True, create=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    except ImportError:
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=30)
        start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expiry_str = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")

        perms = "rcw"
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

        return (
            f"sv=2024-11-04&st={quote(start_str)}&se={quote(expiry_str)}"
            f"&sr={resource}&sp={perms}&sig={quote(sig)}"
        )


async def upload_artifact(
    data: bytes,
    mime: str = "application/octet-stream",
    container: str | None = None,
    http_timeout: float = 120.0,
) -> dict[str, Any]:
    """
    Upload raw bytes to Azure Blob Storage using CAS addressing.

    Returns a reference dict compatible with the Temporal pipeline's
    Artifact format.
    """
    container = container or _AZURE_CONTAINER
    sha256 = _sha256_bytes(data)
    blob_name = f"hashed/{sha256}"

    url = (
        f"https://{_AZURE_ACCOUNT}.blob.core.windows.net"
        f"/{container}/{blob_name}"
    )
    sas = _generate_write_sas(container, blob_name)

    async with httpx.AsyncClient(timeout=httpx.Timeout(http_timeout)) as client:
        resp = await client.put(
            f"{url}?{sas}",
            content=data,
            headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": mime,
                "x-ms-version": "2024-11-04",
            },
        )
        resp.raise_for_status()

    ref: dict[str, Any] = {
        "uri": f"azure://{container}/{blob_name}",
        "sha256": sha256,
        "type": mime,
        "bytes": len(data),
    }
    logger.info("Uploaded CAS artifact: %s (%d bytes)", sha256[:12], len(data))
    return ref


async def upload_file(
    file_path: str | Path,
    mime: str = "application/octet-stream",
    container: str | None = None,
) -> dict[str, Any] | str:
    """
    Upload a local file to Azure CAS and return a reference dict.

    Falls back to returning the local path string when Azure credentials
    are not configured (standalone / dev mode).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not _AZURE_KEY:
        logger.debug("No AZURE_ACCOUNT_KEY configured; returning local path")
        return str(path)

    data = path.read_bytes()
    return await upload_artifact(data, mime=mime, container=container)
