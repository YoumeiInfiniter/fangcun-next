"""Project state, manifest and active-version management.

Layout (spec §22):
    <project_dir>/
      config.json
      source/
      artifacts/<stage>/...
      state/manifest.json
      state/active_versions.json
      state/continuity.json
      state/writer_overrides.jsonl
      export/

Every mutation is recorded; nothing is silently overwritten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    atomic_write_json,
    atomic_write_text,
    jsonl_append,
    now_iso,
    read_json,
    read_jsonl,
    relpath_display,
    sha256_text,
    ensure_dir,
    canonical_json,
)


MANIFEST_SCHEMA = "project-manifest.schema.json"


def _default_manifest(project_id: str) -> dict:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "artifacts": {},
    }


def project_dir_from_config(config_path: Path) -> Path:
    return config_path.parent


def state_dir(project_dir: Path) -> Path:
    return project_dir / "state"


def config_path(project_dir: Path) -> Path:
    return project_dir / "config.json"


def manifest_path(project_dir: Path) -> Path:
    return state_dir(project_dir) / "manifest.json"


def active_versions_path(project_dir: Path) -> Path:
    return state_dir(project_dir) / "active_versions.json"


def continuity_path(project_dir: Path) -> Path:
    return state_dir(project_dir) / "continuity.json"


def overrides_path(project_dir: Path) -> Path:
    return state_dir(project_dir) / "writer_overrides.jsonl"


def load_config(project_dir: Path) -> dict:
    path = config_path(project_dir)
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"config.json 缺失或损坏: {path}")
    local_path = project_dir / "config.local.json"
    if local_path.exists():
        local = read_json(local_path)
        if isinstance(local, dict) and isinstance(local.get("model_config"), dict):
            merged = dict(data.get("model_config") or {})
            merged.update(local["model_config"])
            data["model_config"] = merged
            data["_local_overrides"] = {"model_config": True}
    return data


def save_config(project_dir: Path, config: dict, source: str = "cli", note: str = "") -> Path:
    path = config_path(project_dir)
    previous = read_json(path)
    atomic_write_json(path, config)
    history = state_dir(project_dir) / "config_history.jsonl"
    jsonl_append(
        history,
        {
            "record_type": "config_update",
            "previous": previous,
            "current": config,
            "source": source,
            "note": note,
            "created_at": now_iso(),
        },
    )
    return path


def init_project(project_dir: Path, config: dict, source: str = "cli") -> dict:
    """Create a project idempotently. Existing approved data is never touched."""
    project_dir.mkdir(parents=True, exist_ok=True)
    if config_path(project_dir).exists():
        existing = load_config(project_dir)
        if existing.get("project_id") != config.get("project_id"):
            raise ValueError(
                "项目目录已存在且 project_id 不一致，禁止覆盖已有项目。"
                "如需新建项目请使用新的 project_dir。"
            )
        manifest = load_manifest(project_dir)
        return {"config": existing, "manifest": manifest, "created": False}
    save_config(project_dir, config, source=source, note="init")
    manifest = _default_manifest(config.get("project_id", ""))
    atomic_write_json(manifest_path(project_dir), manifest)
    atomic_write_json(active_versions_path(project_dir), {})
    return {"config": config, "manifest": manifest, "created": True}


def load_manifest(project_dir: Path) -> dict:
    data = read_json(manifest_path(project_dir))
    if not isinstance(data, dict):
        raise ValueError(f"manifest.json 缺失或损坏: {manifest_path(project_dir)}")
    data.setdefault("artifacts", {})
    return data


def save_manifest(project_dir: Path, manifest: dict) -> Path:
    manifest["updated_at"] = now_iso()
    return atomic_write_json(manifest_path(project_dir), manifest)


def load_active_versions(project_dir: Path) -> dict:
    data = read_json(active_versions_path(project_dir), {})
    return data if isinstance(data, dict) else {}


def save_active_versions(project_dir: Path, versions: dict) -> Path:
    return atomic_write_json(active_versions_path(project_dir), versions)


def artifact_key(kind: str, episode: int | None = None) -> str:
    return f"{kind}:{episode}" if episode is not None else kind


def commit_artifact(
    project_dir: Path,
    kind: str,
    *,
    content,
    episode: int | None = None,
    source: str = "ai",
    status: str = "draft",
    ext: str | None = None,
    meta: dict | None = None,
    note: str = "",
    parent_version: str | None = None,
) -> dict:
    """Persist one immutable artifact version (idempotent by content hash).

    Every version is written to a dedicated immutable file under
    artifacts/<kind>/versions/. active_versions.json only stores the current
    pointer. Identical content never creates a duplicate version.
    """
    if isinstance(content, (dict, list)):
        text = canonical_json(content) + "\n"
        ext = ext or "json"
    elif isinstance(content, str):
        text = content
        ext = ext or "txt"
    else:
        raise TypeError(f"artifact content 必须是 str/dict/list，收到 {type(content).__name__}")
    content_hash = sha256_text(text)

    manifest = load_manifest(project_dir)
    key = artifact_key(kind, episode)
    entry = manifest["artifacts"].setdefault(key, {"active_version": None, "versions": []})

    # Idempotency: identical content reuses the existing version.
    for existing in entry["versions"]:
        if existing.get("content_hash") == content_hash:
            entry["active_version"] = existing["version"]
            save_manifest(project_dir, manifest)
            versions = load_active_versions(project_dir)
            versions[key] = existing["path"]
            save_active_versions(project_dir, versions)
            return {
                "version": existing["version"],
                "path": project_dir / existing["path"],
                "content_hash": content_hash,
                "created": False,
            }

    version = f"v{len(entry['versions']) + 1:03d}"
    versions_dir = project_dir / "artifacts" / kind / "versions"
    if episode is not None:
        versions_dir = versions_dir / f"ep{episode:03d}"
    ensure_dir(versions_dir)
    filename = f"{kind}_{version}_{content_hash[:8]}.{ext}"
    path = versions_dir / filename
    if ext == "json":
        data = content if isinstance(content, (dict, list)) else text
        atomic_write_json(path, data)
    else:
        atomic_write_text(path, text)

    previous_active = entry.get("active_version")
    record = {
        "version": version,
        "path": relpath_display(path, project_dir),
        "content_hash": content_hash,
        "status": status,
        "source": source,
        "note": note,
        "created_at": now_iso(),
        "parent_version": parent_version or previous_active,
        "supersedes": previous_active,
    }
    if meta:
        record["meta"] = meta
    entry["versions"].append(record)
    entry["active_version"] = version
    save_manifest(project_dir, manifest)

    versions = load_active_versions(project_dir)
    versions[key] = record["path"]
    save_active_versions(project_dir, versions)
    return {
        "version": version,
        "path": path,
        "content_hash": content_hash,
        "created": True,
    }


def record_artifact(
    project_dir: Path,
    kind: str,
    path: Path,
    *,
    episode: int | None = None,
    source: str = "ai",
    status: str = "draft",
    version: str | None = None,
    note: str = "",
) -> str:
    """Backwards-compatible wrapper: register an existing file's content."""
    if not path.exists():
        raise FileNotFoundError(f"artifact 文件不存在: {path}")
    ext = path.suffix.lstrip(".")
    if ext == "json":
        content = read_json(path)
    else:
        content = path.read_text(encoding="utf-8")
    result = commit_artifact(
        project_dir,
        kind,
        content=content,
        episode=episode,
        source=source,
        status=status,
        ext=ext,
        note=note,
    )
    return result["version"]


def active_artifact_path(project_dir: Path, kind: str, episode: int | None = None) -> Path | None:
    key = artifact_key(kind, episode)
    versions = load_active_versions(project_dir)
    value = versions.get(key)
    return (project_dir / value).resolve() if value else None


def active_version_id(project_dir: Path, kind: str, episode: int | None = None) -> str | None:
    key = artifact_key(kind, episode)
    return load_manifest(project_dir).get("artifacts", {}).get(key, {}).get("active_version")


def artifact_version_path(
    project_dir: Path,
    kind: str,
    episode: int | None,
    version: str,
) -> Path | None:
    key = artifact_key(kind, episode)
    for record in load_manifest(project_dir).get("artifacts", {}).get(key, {}).get("versions", []):
        if record.get("version") == version:
            path = project_dir / record["path"]
            return path if path.exists() else None
    return None


def artifact_version_record(
    project_dir: Path,
    kind: str,
    episode: int | None,
    version: str,
) -> dict | None:
    key = artifact_key(kind, episode)
    for record in load_manifest(project_dir).get("artifacts", {}).get(key, {}).get("versions", []):
        if record.get("version") == version:
            return record
    return None


def read_artifact_version(
    project_dir: Path,
    kind: str,
    episode: int | None,
    version: str,
):
    """Read the immutable content of a specific version (json → dict)."""
    path = artifact_version_path(project_dir, kind, episode, version)
    if not path:
        raise KeyError(f"{kind}:{episode} 版本 {version} 不存在")
    if path.suffix == ".json":
        return read_json(path)
    return path.read_text(encoding="utf-8")


def draft_meta_record(project_dir: Path, episode: int, version: str) -> dict | None:
    record = artifact_version_record(project_dir, "script_draft", episode, version)
    return (record or {}).get("meta")


def artifact_versions(project_dir: Path, kind: str, episode: int | None = None) -> list[dict]:
    key = artifact_key(kind, episode)
    return load_manifest(project_dir).get("artifacts", {}).get(key, {}).get("versions", [])


def is_approved(project_dir: Path, episode: int) -> bool:
    return active_artifact_path(project_dir, "approved_script", episode) is not None


def writer_overrides(project_dir: Path) -> list[dict]:
    return read_jsonl(overrides_path(project_dir))


def append_writer_override(project_dir: Path, override: dict) -> None:
    jsonl_append(overrides_path(project_dir), override)


def load_continuity(project_dir: Path) -> dict:
    data = read_json(continuity_path(project_dir))
    if isinstance(data, dict):
        return data
    return {
        "version": 0,
        "approved_episodes": [],
        "facts": [],
        "character_knowledge": {},
        "character_states": {},
        "relationship_states": {},
        "open_hooks": [],
        "resolved_hooks": [],
        "props": {},
        "locations": {},
        "writer_overrides": [],
        "notes_for_future": [],
    }


def save_continuity(project_dir: Path, continuity: dict) -> Path:
    return atomic_write_json(continuity_path(project_dir), continuity)


def project_status(project_dir: Path) -> dict:
    manifest = load_manifest(project_dir)
    versions = load_active_versions(project_dir)
    continuity = load_continuity(project_dir)
    approved = sorted(
        int(key.split(":", 1)[1])
        for key in versions
        if key.startswith("approved_script:")
        and key.split(":", 1)[1].isdigit()
    )
    return {
        "project_id": load_config(project_dir).get("project_id"),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
        "approved_episodes": approved,
        "next_episode": max(approved) + 1 if approved else 1,
        "active_versions": versions,
        "continuity_version": continuity.get("version", 0),
    }
