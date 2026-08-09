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

import uuid
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


class ArtifactStateError(RuntimeError):
    """Active artifact state is inconsistent, tampered, or out of bounds."""


def _default_manifest(project_id: str) -> dict:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "project_instance_id": uuid.uuid4().hex,
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
    if data.get("script_format") == "legacy-scriptitem":
        data["script_format"] = "default-cn"
        data["transport_format"] = "legacy-scriptitem"
        data["_format_migrated"] = True
    elif "transport_format" not in data:
        data["transport_format"] = "plain"
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
        has_manifest = manifest_path(project_dir).exists()
        has_active_versions = active_versions_path(project_dir).exists()
        if has_manifest and has_active_versions:
            manifest = load_manifest(project_dir)
            return {"config": existing, "manifest": manifest, "created": False}
        if has_manifest != has_active_versions:
            raise ValueError(
                "项目状态不完整：manifest.json 与 active_versions.json 必须同时存在。"
                "为避免覆盖已有状态，拒绝自动修复。"
            )
        payload_dirs = (project_dir / "artifacts", project_dir / "source", project_dir / "export")
        state_payload = state_dir(project_dir)
        has_payload = any(path.exists() and any(path.iterdir()) for path in payload_dirs if path.is_dir())
        has_payload = has_payload or (
            state_payload.is_dir() and any(state_payload.iterdir())
        )
        if has_payload:
            raise ValueError(
                "项目已有 config.json 和业务数据，但缺少初始化状态文件；"
                "请人工恢复 manifest/active_versions，拒绝静默重建。"
            )
        manifest = _default_manifest(existing.get("project_id", ""))
        atomic_write_json(manifest_path(project_dir), manifest)
        atomic_write_json(active_versions_path(project_dir), {})
        jsonl_append(
            state_dir(project_dir) / "config_history.jsonl",
            {
                "record_type": "config_adopted",
                "previous": existing,
                "current": existing,
                "source": source,
                "note": "init from preseeded config.json",
                "created_at": now_iso(),
            },
        )
        return {"config": existing, "manifest": manifest, "created": True}
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

    # Logical-version idempotency: identical content AND identical input
    # fingerprint / source / parent reuse the version; same content with a
    # different input creates a NEW logical version.
    meta = meta or {}
    input_fingerprint = meta.get("input_fingerprint") or meta.get("context_hash")
    for existing in entry["versions"]:
        existing_meta = existing.get("meta") or {}
        existing_input = existing_meta.get("input_fingerprint") or existing_meta.get("context_hash")
        same_input = (input_fingerprint is None) or (existing_input == input_fingerprint)
        same_source = existing.get("source") == source
        same_parent = (parent_version is None) or (existing.get("parent_version") == parent_version)
        if (
            existing.get("content_hash") == content_hash
            and same_input
            and same_source
            and same_parent
        ):
            entry["active_version"] = existing["version"]
            save_manifest(project_dir, manifest)
            versions = load_active_versions(project_dir)
            versions[key] = {"version": existing["version"], "path": existing["path"]}
            save_active_versions(project_dir, versions)
            return {
                "version": existing["version"],
                "path": project_dir / existing["path"],
                "content_hash": content_hash,
                "created": False,
            }

    used_numbers = []
    for record in entry["versions"]:
        raw = str(record.get("version", "v000"))[1:]
        if raw.isdigit():
            used_numbers.append(int(raw))
    next_number = max(used_numbers, default=0) + 1
    version = f"v{next_number:03d}"
    while any(r.get("version") == version for r in entry["versions"]):
        next_number += 1
        version = f"v{next_number:03d}"
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
    versions[key] = {"version": version, "path": record["path"]}
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
    result = resolve_active(project_dir, kind, episode)
    return result["path"] if result else None


def active_version_id(project_dir: Path, kind: str, episode: int | None = None) -> str | None:
    result = resolve_active(project_dir, kind, episode)
    return result["version"] if result else None


def resolve_active(
    project_dir: Path,
    kind: str,
    episode: int | None = None,
) -> dict | None:
    """Single trusted active-artifact resolver (R3-P0-1).

    Manifest is the single source of truth. active_versions is only a
    verifiable index: any contradiction blocks. The resolved path must stay
    inside project_dir and its content hash must match the version record.
    """
    key = artifact_key(kind, episode)
    manifest = load_manifest(project_dir)
    entry = manifest.get("artifacts", {}).get(key)
    if not entry or not entry.get("active_version"):
        return None
    version = entry["active_version"]
    record = next((r for r in entry.get("versions", []) if r.get("version") == version), None)
    if record is None:
        raise ArtifactStateError(f"{key}: manifest active_version {version} 没有对应版本记录")
    index = load_active_versions(project_dir).get(key)
    if index is not None:
        if isinstance(index, dict):
            index_version = index.get("version")
            index_path = index.get("path")
        else:
            index_version = None
            index_path = index
        if index_version is not None and index_version != version:
            raise ArtifactStateError(
                f"{key}: active_versions 索引版本 {index_version} 与 manifest 版本 {version} 不一致"
            )
        if index_path is not None and index_path != record.get("path"):
            raise ArtifactStateError(
                f"{key}: active_versions 索引路径与 manifest 版本记录不一致"
            )
    path = _validated_version_path(project_dir, record)
    return {"version": version, "path": path, "record": record}


def _validated_version_path(project_dir: Path, record: dict) -> Path:
    raw = str(record.get("path", ""))
    if not raw:
        raise ArtifactStateError("版本记录缺少 path")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ArtifactStateError(f"artifact 版本路径必须是项目内无 .. 的相对路径：{raw}")
    candidate = project_dir / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(project_dir.resolve())
    except (ValueError, OSError) as exc:
        raise ArtifactStateError(f"artifact 路径逃逸项目目录或非法：{raw}") from exc
    if not resolved.exists():
        raise ArtifactStateError(f"artifact 文件缺失：{raw}")
    try:
        if resolved.suffix == ".json":
            content = read_json(resolved)
            actual_hash = sha256_text(canonical_json(content) + "\n")
        else:
            actual_hash = sha256_text(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactStateError(f"artifact 文件不可读或损坏：{raw}") from exc
    if actual_hash != record.get("content_hash"):
        raise ArtifactStateError(f"artifact 文件哈希与版本记录不一致（可能被篡改）：{raw}")
    return resolved


def artifact_version_path(
    project_dir: Path,
    kind: str,
    episode: int | None,
    version: str,
) -> Path | None:
    key = artifact_key(kind, episode)
    for record in load_manifest(project_dir).get("artifacts", {}).get(key, {}).get("versions", []):
        if record.get("version") == version:
            return _validated_version_path(project_dir, record)
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


def activate_version(
    project_dir: Path,
    kind: str,
    version: str,
    *,
    episode: int | None = None,
    reason: str = "",
    operator: str = "cli",
) -> dict:
    """Deterministically restore a specific logical version as active."""
    key = artifact_key(kind, episode)
    record = artifact_version_record(project_dir, kind, episode, version)
    if record is None:
        raise KeyError(f"{key} 版本 {version} 不存在")
    path = _validated_version_path(project_dir, record)
    manifest = load_manifest(project_dir)
    entry = manifest["artifacts"].setdefault(key, {"active_version": None, "versions": []})
    previous = entry.get("active_version")
    entry["active_version"] = version
    save_manifest(project_dir, manifest)
    versions = load_active_versions(project_dir)
    versions[key] = {"version": version, "path": record["path"]}
    save_active_versions(project_dir, versions)
    history = state_dir(project_dir) / "activation_history.jsonl"
    jsonl_append(
        history,
        {
            "kind": kind,
            "episode": episode,
            "version": version,
            "previous_active": previous,
            "reason": reason,
            "operator": operator,
            "created_at": now_iso(),
        },
    )
    return {"kind": kind, "episode": episode, "version": version, "previous_active": previous}


def artifact_versions(project_dir: Path, kind: str, episode: int | None = None) -> list[dict]:
    key = artifact_key(kind, episode)
    return load_manifest(project_dir).get("artifacts", {}).get(key, {}).get("versions", [])


def update_artifact_status(
    project_dir: Path,
    kind: str,
    version: str,
    *,
    status: str,
    episode: int | None = None,
    operator: str,
    reason: str,
) -> dict:
    """Change workflow status without changing immutable artifact content."""
    allowed = {"draft", "needs_writer_confirmation", "approved", "rejected", "superseded"}
    if status not in allowed:
        raise ValueError(f"非法 artifact status：{status}")
    key = artifact_key(kind, episode)
    manifest = load_manifest(project_dir)
    entry = manifest.get("artifacts", {}).get(key)
    if not entry:
        raise KeyError(f"artifact 不存在：{key}")
    record = next((item for item in entry.get("versions", []) if item.get("version") == version), None)
    if not record:
        raise KeyError(f"artifact 版本不存在：{key}/{version}")
    previous = record.get("status")
    record["status"] = status
    record["status_updated_at"] = now_iso()
    record["status_operator"] = operator
    save_manifest(project_dir, manifest)
    jsonl_append(
        state_dir(project_dir) / "stage_status_history.jsonl",
        {
            "kind": kind,
            "episode": episode,
            "version": version,
            "previous_status": previous,
            "status": status,
            "operator": operator,
            "reason": reason,
            "created_at": now_iso(),
        },
    )
    return {"kind": kind, "episode": episode, "version": version, "previous_status": previous, "status": status}


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
