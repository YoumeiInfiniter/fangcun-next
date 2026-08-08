"""Revision request normalization, impact analysis and writer overrides.

All writer feedback — chat, comments, uploaded files or direct statements —
becomes a structured revision_request (spec §18). Local edits are applied by
the writer and approved via `approve`; this module records the intent and
propagates only overrides explicitly marked as affecting future episodes.
"""

from __future__ import annotations

import re
from pathlib import Path

from .common import now_iso, read_jsonl
from .schema_validate import ensure_valid
from .state_store import append_writer_override, writer_overrides


FUTURE_MARKERS = ["下一集", "后续", "以后", "未来", "伏笔", "人物认知", "规则", "下集"]
LOCAL_MARKERS = ["台词", "动作", "表演", "时长", "删", "改", "保留", "加"]
PROJECT_MARKERS = ["主线", "结局", "重做", "整体", "集数", "从头", "重来"]


def next_revision_id(project_dir: Path, episode: int) -> str:
    count = sum(1 for r in _revisions(project_dir) if r.get("episode") == episode)
    return f"REV-EP{episode:03d}-{count + 1:03d}"


def analyze_impact(instruction: str) -> dict:
    text = str(instruction)
    affects_future = any(marker in text for marker in FUTURE_MARKERS)
    is_project = any(marker in text for marker in PROJECT_MARKERS)
    if is_project:
        scope = "project_wide"
    elif affects_future:
        scope = "character_knowledge" if any(m in text for m in ("人物认知", "规则")) else "future_episodes"
    else:
        scope = "local_episode"
    return {
        "affects_future": affects_future,
        "scope": scope,
        "matched_future_markers": [m for m in FUTURE_MARKERS if m in text],
        "matched_project_markers": [m for m in PROJECT_MARKERS if m in text],
        "advisory_only": True,
    }


def create_revision(
    project_dir: Path,
    *,
    episode: int,
    instruction: str,
    source: str = "cli",
    requested_by: str = "writer",
    affects_future: bool | None = None,
    scope: str | None = None,
) -> dict:
    impact = analyze_impact(instruction)
    record = {
        "revision_id": next_revision_id(project_dir, episode),
        "episode": episode,
        "source": source,
        "requested_by": requested_by,
        "instruction": instruction.strip(),
        "scope": scope or impact["scope"],
        "affects_future": impact["affects_future"] if affects_future is None else affects_future,
        "impact_analysis": impact,
        "status": "pending",
        "created_at": now_iso(),
    }
    ensure_valid(record, "revision-request.schema.json")
    _append_revision(project_dir, record)
    return record


def _revisions(project_dir: Path) -> list[dict]:
    return read_jsonl(project_dir / "state" / "revisions.jsonl")


def _append_revision(project_dir: Path, record: dict) -> None:
    path = project_dir / "state" / "revisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(__import__("json").dumps(record, ensure_ascii=False) + "\n")


def _update_status(project_dir: Path, revision_id: str, status: str) -> dict | None:
    path = project_dir / "state" / "revisions.jsonl"
    records = _revisions(project_dir)
    target = None
    for record in records:
        if record.get("revision_id") == revision_id:
            record["status"] = status
            record["updated_at"] = now_iso()
            target = record
            break
    if target is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(__import__("json").dumps(record, ensure_ascii=False) + "\n")
    if status == "approved" and target.get("episode"):
        append_writer_override(
            project_dir,
            {
                "revision_id": target["revision_id"],
                "episode": target["episode"],
                "source": target["source"],
                "requested_by": target["requested_by"],
                "instruction": target["instruction"],
                "scope": target["scope"],
                "affects_future": target["affects_future"],
                "status": "approved",
                "created_at": target["created_at"],
            },
        )
    return target


def approve_revision(project_dir: Path, revision_id: str) -> dict | None:
    return _update_status(project_dir, revision_id, "approved")


def reject_revision(project_dir: Path, revision_id: str) -> dict | None:
    return _update_status(project_dir, revision_id, "rejected")


def list_revisions(project_dir: Path, episode: int | None = None) -> list[dict]:
    records = _revisions(project_dir)
    if episode is not None:
        records = [r for r in records if r.get("episode") == episode]
    return records
