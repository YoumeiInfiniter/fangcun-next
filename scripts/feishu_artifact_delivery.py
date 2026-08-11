#!/usr/bin/env python3
"""Fangcun Feishu artifact delivery runner.

This module is deliberately split into two halves:

1. Deterministic local planning: decide whether a saved Fangcun artifact should
   be mirrored to Feishu, compute the next document version, persist a pending
   sync event, and print a machine-readable event for the host Agent.
2. Deterministic local recording: after the host Agent has used first-class
   ``feishu_doc`` tools to create/write/read a document, register the verified
   document in ``memory/feishu-artifact-sync.json``.

It does NOT call Feishu APIs directly.  OpenClaw/Agent owns network writes via
first-class tools; this runner gives that layer a stable trigger and a stable
record command instead of relying on the Agent to remember prose instructions.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

try:  # package import
    from .common import atomic_write_json, ensure_dir, now_iso, read_json, relpath_display, sha256_text
    from .state_store import load_config
    from .artifact_sync_registry import artifact_id, load_registry, sha256_file
    from .artifact_sync_registry import cmd_record as registry_cmd_record
except ImportError:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.common import atomic_write_json, ensure_dir, now_iso, read_json, relpath_display, sha256_text
    from scripts.state_store import load_config
    from scripts.artifact_sync_registry import artifact_id, load_registry, sha256_file
    from scripts.artifact_sync_registry import cmd_record as registry_cmd_record


EVENT_PREFIX = "FANGCUN_FEISHU_SYNC_EVENT:"
EVENT_SCHEMA = "fangcun.feishu_artifact_sync_event.v1"
DEFAULT_REGISTRY = "memory/feishu-artifact-sync.json"
PROJECT_OUTPUT_CONFIG = ".feishu-output.json"
WORKSPACE_OUTPUT_CONFIG = "memory/feishu-artifact-sync.config.json"

# User-facing Markdown/TXT artifacts that are worth sending to the writer for
# acceptance.  JSON state and internal metrics stay local unless a future
# command renders them into Markdown/TXT first.
DELIVERABLE_KINDS: dict[str, dict[str, str]] = {
    "project_brief": {"stage": "项目需求确认", "label": "验收版"},
    "adaptation_strategy": {"stage": "改编指引", "label": "验收版"},
    "story_outline": {"stage": "故事大纲", "label": "验收版"},
    "episode_outline_md": {"stage": "分集集纲", "label": "验收版"},
    "script_draft": {"stage": "剧本草稿", "label": "验收版"},
    "stage_review_md": {"stage": "阶段审核报告", "label": "审核版"},
    "review_md": {"stage": "单集审核报告", "label": "审核版"},
}
TEXT_SUFFIXES = {".md", ".txt", ".markdown"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _workspace_root(project_dir: Path) -> Path:
    """Best-effort workspace root for registry/config paths.

    In OpenClaw this is normally the current working directory.  For standalone
    tests/projects, falling back to cwd keeps behavior predictable and avoids
    writing outside the caller's workspace.
    """
    override = os.environ.get("FANGCUN_WORKSPACE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    try:
        cwd = Path.cwd().resolve()
        project_dir.resolve().relative_to(cwd)
        return cwd
    except ValueError:
        return Path.cwd().resolve()


def _read_optional_json(path: Path) -> dict[str, Any]:
    data = read_json(path, default={}) if path.exists() else {}
    return data if isinstance(data, dict) else {}


def load_output_config(project_dir: Path) -> dict[str, Any]:
    """Load workspace defaults, then project overrides from .feishu-output.json."""
    workspace = _workspace_root(project_dir)
    config: dict[str, Any] = {}
    config.update(_read_optional_json(workspace / WORKSPACE_OUTPUT_CONFIG))
    config.update(_read_optional_json(project_dir / PROJECT_OUTPUT_CONFIG))
    config.setdefault("enabled", True)
    config.setdefault("mode", "versioned_doc")
    config.setdefault("auto_sync_on_group", True)
    config.setdefault("stop_for_confirmation", True)
    config.setdefault("registry", DEFAULT_REGISTRY)
    return config


def _current_channel() -> str:
    for name in ("OPENCLAW_CHANNEL", "OPENCLAW_SURFACE", "FANGCUN_CHANNEL", "CHANNEL"):
        if os.environ.get(name):
            return str(os.environ[name]).lower()
    return ""


def _current_chat_type() -> str:
    for name in ("OPENCLAW_CHAT_TYPE", "FANGCUN_CHAT_TYPE", "CHAT_TYPE"):
        if os.environ.get(name):
            return str(os.environ[name]).lower()
    return ""


def is_feishu_group_context(config: dict[str, Any]) -> bool:
    """Return true when automatic Feishu group delivery should be activated."""
    forced = os.environ.get("FANGCUN_FEISHU_SYNC")
    if forced is not None:
        return _truthy(forced)
    if not _truthy(config.get("enabled", True)):
        return False
    if not _truthy(config.get("auto_sync_on_group", True)):
        return False
    config_channel = str(config.get("channel") or config.get("surface") or "").lower()
    config_chat_type = str(config.get("chat_type") or "").lower()
    channel = _current_channel() or config_channel
    chat_type = _current_chat_type() or config_chat_type
    return channel == "feishu" and chat_type == "group"


def _registry_path(project_dir: Path, config: dict[str, Any]) -> Path:
    raw = str(config.get("registry") or DEFAULT_REGISTRY)
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return _workspace_root(project_dir) / path


def _project_name(project_dir: Path) -> str:
    try:
        config = load_config(project_dir)
    except Exception:
        config = {}
    return str(
        config.get("drama_name")
        or config.get("project")
        or config.get("project_id")
        or project_dir.name
    )


def _stage_for(kind: str, episode: int | None = None) -> tuple[str, str]:
    item = DELIVERABLE_KINDS[kind]
    stage = item["stage"]
    if kind == "script_draft" and episode is not None:
        stage = f"第{episode}集剧本草稿"
    if kind == "review_md" and episode is not None:
        stage = f"第{episode}集审核报告"
    return stage, item["label"]


def _stage_config(config: dict[str, Any], stage: str) -> dict[str, Any]:
    stages = config.get("stages") if isinstance(config.get("stages"), dict) else {}
    item = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    return item


def _title_template(config: dict[str, Any], stage: str) -> str:
    item = _stage_config(config, stage)
    return str(
        item.get("title_template")
        or config.get("title_template")
        or "《{project}》{stage} {version}｜{label}"
    )


def _folder_token(config: dict[str, Any], stage: str) -> str | None:
    item = _stage_config(config, stage)
    value = item.get("folder_token") or config.get("default_folder_token") or config.get("folder_token")
    return str(value) if value else None


def _relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return relpath_display(path.resolve(), base.resolve())
    except Exception:
        return str(path)


def build_sync_event(
    project_dir: Path,
    *,
    kind: str,
    local_path: Path,
    episode: int | None = None,
    artifact_version: str | None = None,
    artifact_content_hash: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a pending sync event, or None when the artifact is not deliverable."""
    project_dir = project_dir.expanduser().resolve()
    local_path = local_path.expanduser().resolve()
    if kind not in DELIVERABLE_KINDS:
        return None
    if local_path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    if not local_path.exists():
        raise FileNotFoundError(f"artifact not found: {local_path}")
    config = dict(config or load_output_config(project_dir))
    if not is_feishu_group_context(config):
        return None

    project = _project_name(project_dir)
    stage, label = _stage_for(kind, episode=episode)
    registry = _registry_path(project_dir, config)
    local_for_registry = _relative_or_absolute(local_path, _workspace_root(project_dir))
    data = load_registry(registry)
    aid = artifact_id(project, stage, local_for_registry)
    existing = next((item for item in data.get("artifacts", []) if item.get("artifact_id") == aid), None)
    version = f"v{len(existing.get('versions', [])) + 1:03d}" if existing else "v001"
    title = _title_template(config, stage).format(
        project=project,
        stage=stage,
        version=version,
        label=label,
        kind=kind,
        episode=episode or "",
    )
    folder_token = _folder_token(config, stage)
    pending_dir = project_dir / "state" / "feishu_delivery" / "pending"
    ensure_dir(pending_dir)
    event_id = f"{aid}-{version}"
    event_file = pending_dir / f"{event_id}.json"
    script_path = Path(__file__).resolve()
    record_command = " ".join(
        shlex.quote(part)
        for part in (
            sys.executable,
            str(script_path),
            "record",
            "--event-file",
            str(event_file),
            "--doc-token",
            "<doc_token>",
            "--url",
            "<url>",
            "--readback-ok",
        )
    )
    event = {
        "schema": EVENT_SCHEMA,
        "event_id": event_id,
        "created_at": now_iso(),
        "action": "create_feishu_doc_and_record",
        "project_dir": str(project_dir),
        "project": project,
        "kind": kind,
        "stage": stage,
        "label": label,
        "episode": episode,
        "artifact_version": artifact_version,
        "artifact_content_hash": artifact_content_hash,
        "artifact_id": aid,
        "sync_version": version,
        "title": title,
        "local_path": str(local_path),
        "local_path_for_registry": local_for_registry,
        "local_sha256": sha256_file(local_path),
        "local_bytes": local_path.stat().st_size,
        "registry": str(registry),
        "folder_token": folder_token,
        "mode": config.get("mode") or "versioned_doc",
        "stop_for_confirmation": _truthy(config.get("stop_for_confirmation", True)),
        "event_file": str(event_file),
        "record_command": record_command,
        "instructions": [
            "Read local_path as UTF-8 text.",
            "Create a new Feishu docx with title; pass folder_token only when non-null.",
            "Do not rely on feishu_doc create content; write the full text after create.",
            "Read the document back and verify it is non-empty and contains representative local content.",
            "If create/write/readback fails, report failure and do not run record_command.",
            "After verified success, run record_command with the real doc_token/url.",
            "Reply with the Feishu link and then stop for writer confirmation.",
        ],
    }
    if folder_token is None:
        event["notice"] = "未指定输出文件夹，创建时请使用 bot 默认空间，并在回复中说明。"
    return event


def persist_and_print_event(event: dict[str, Any]) -> None:
    atomic_write_json(Path(event["event_file"]), event)
    print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, sort_keys=True))


def maybe_emit_sync_event(
    project_dir: Path,
    *,
    kind: str,
    result: dict[str, Any],
    episode: int | None = None,
    only_when_created: bool = True,
) -> dict[str, Any] | None:
    """Build, persist and print a sync event for a freshly saved artifact."""
    if only_when_created and not result.get("created", True):
        return None
    local_path = Path(result["path"])
    event = build_sync_event(
        project_dir,
        kind=kind,
        local_path=local_path,
        episode=episode,
        artifact_version=result.get("version"),
        artifact_content_hash=result.get("content_hash"),
    )
    if event is None:
        return None
    persist_and_print_event(event)
    return event


def cmd_plan(args: argparse.Namespace) -> int:
    event = build_sync_event(
        Path(args.project_dir),
        kind=args.kind,
        local_path=Path(args.local_path),
        episode=args.episode,
        artifact_version=args.artifact_version,
        artifact_content_hash=args.artifact_content_hash,
    )
    if event is None:
        print(json.dumps({"eligible": False}, ensure_ascii=False, indent=2))
        return 0
    persist_and_print_event(event)
    print(json.dumps({"eligible": True, "event_file": event["event_file"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    event = read_json(Path(args.event_file))
    if not isinstance(event, dict) or event.get("schema") != EVENT_SCHEMA:
        raise SystemExit(f"invalid event file: {args.event_file}")
    if not args.readback_ok:
        raise SystemExit("refusing to record unverified Feishu document; pass --readback-ok after successful readback validation")
    local = Path(event["local_path"])
    if not local.exists():
        raise SystemExit(f"local_path not found: {local}")
    if sha256_file(local) != event.get("local_sha256"):
        raise SystemExit("local file sha256 changed after sync event; re-plan before recording")
    ns = argparse.Namespace(
        registry=event["registry"],
        local_path=event["local_path"],
        project=event["project"],
        stage=event["stage"],
        label=event["label"],
        artifact_id=event["artifact_id"],
        version=event["sync_version"],
        doc_token=args.doc_token,
        url=args.url,
        title=event["title"],
    )
    registry_cmd_record(ns)
    done_dir = Path(event["project_dir"]) / "state" / "feishu_delivery" / "recorded"
    ensure_dir(done_dir)
    done_path = done_dir / (Path(args.event_file).name)
    atomic_write_json(done_path, {**event, "doc_token": args.doc_token, "url": args.url, "recorded_at": now_iso()})
    print(json.dumps({"recorded": True, "event_id": event["event_id"], "done_file": str(done_path)}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Plan/record Fangcun Feishu artifact deliveries")
    sub = p.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--project-dir", required=True)
    plan.add_argument("--kind", required=True, choices=sorted(DELIVERABLE_KINDS))
    plan.add_argument("--local-path", required=True)
    plan.add_argument("--episode", type=int)
    plan.add_argument("--artifact-version")
    plan.add_argument("--artifact-content-hash")
    plan.set_defaults(func=cmd_plan)

    record = sub.add_parser("record")
    record.add_argument("--event-file", required=True)
    record.add_argument("--doc-token", required=True)
    record.add_argument("--url", required=True)
    record.add_argument("--readback-ok", action="store_true")
    record.set_defaults(func=cmd_record)

    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
