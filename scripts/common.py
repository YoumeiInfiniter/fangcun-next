"""Shared deterministic runtime utilities for Fangcun Next.

This module owns path resolution, JSON I/O, hashing and timestamps so the
rest of the runtime never re-implements them inconsistently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent


def skill_root() -> Path:
    """Return the skill root (repo root when running from source)."""
    override = os.environ.get("FANGCUN_SKILL_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return SKILL_ROOT


def references_dir() -> Path:
    return skill_root() / "references"


def schemas_dir() -> Path:
    return references_dir() / "schemas"


def assets_dir() -> Path:
    return skill_root() / "assets"


def now_iso() -> str:
    """Local ISO timestamp with seconds precision (matches legacy style)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def utc_iso() -> str:
    return datetime.now().astimezone().utcnow().isoformat(timespec="seconds") + "Z"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def canonical_json(data: Any) -> str:
    """Stable canonical JSON used for hashing and idempotency."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, data: Any) -> Path:
    """Write JSON atomically so interrupted writes never corrupt state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def atomic_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def slugify(text: str, max_len: int = 64) -> str:
    """Safe directory slug for project ids/names."""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", str(text).strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return (cleaned or "project")[:max_len].rstrip("-")


def jsonl_append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def relpath_display(path: Path, base: Path) -> str:
    """Human-usable relative path for manifest pointers."""
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)
