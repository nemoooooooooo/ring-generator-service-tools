from __future__ import annotations

import hashlib
import re
from pathlib import Path


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name: str, fallback: str = "file") -> str:
    value = _SAFE_NAME_RE.sub("_", (name or "").strip()).strip("._")
    return value or fallback
