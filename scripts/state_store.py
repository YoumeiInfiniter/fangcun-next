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
    jsonl_append,
    now_iso,
    read_json,
    read_jsonl,
    relpath_display,
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
    """Register a new version and point active_versions at it."""
    key = artifact_key(kind, episode)
    version = version or f"v{len(load_manifest(project_dir).get('artifacts', {}).get(key, {}).get('versions', [])) + 1:03d}"
    record = {
        "version": version,
        "path": relpath_display(path, project_dir),
        "status": status,
        "source": source,
        "note": note,
        "created_at": now_iso(),
    }
    manifest = load_manifest(project_dir)
    entry = manifest["artifacts"].setdefault(
        key, {"active_version": None, "versions": []}
    )
    entry["versions"].append(record)
    entry["active_version"] = version
    save_manifest(project_dir, manifest)

    versions = load_active_versions(project_dir)
    versions[key] = record["path"]
    save_active_versions(project_dir, versions)
    return version


def active_artifact_path(project_dir: Path, kind: str, episode: int | None = None) -> Path | None:
    key = artifact_key(kind, episode)
    versions = load_active_versions(project_dir)
    value = versions.get(key)
    return (project_dir / value).resolve() if value else None


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
