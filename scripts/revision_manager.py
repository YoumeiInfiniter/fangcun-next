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
    direct_writer_instruction: bool = False,
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
        "status": "approved" if direct_writer_instruction else "pending",
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
    return transition_revision(project_dir, revision_id, "approved", reason="writer approved", operator="cli")


def reject_revision(project_dir: Path, revision_id: str) -> dict | None:
    return transition_revision(project_dir, revision_id, "rejected", reason="writer rejected", operator="cli")


def revoke_revision(project_dir: Path, revision_id: str, reason: str = "") -> dict | None:
    return transition_revision(project_dir, revision_id, "revoked", reason=reason or "writer revoked", operator="cli")


def list_revisions(project_dir: Path, episode: int | None = None) -> list[dict]:
    """Current-state projection of the revision event log (single source of truth)."""
    records = _revisions(project_dir)
    latest_by_id: dict[str, dict] = {}
    for record in records:
        latest_by_id[record.get("revision_id")] = record
    records = list(latest_by_id.values())
    if episode is not None:
        records = [r for r in records if r.get("episode") == episode]
    return records


def transition_revision(
    project_dir: Path,
    revision_id: str,
    new_status: str,
    *,
    reason: str = "",
    operator: str = "cli",
) -> dict | None:
    """Append a state-transition event; current state is the last event."""
    current = _revision_state(project_dir, revision_id)
    if current is None:
        return None
    record = {
        "revision_id": revision_id,
        "episode": current.get("episode"),
        "source": current.get("source"),
        "requested_by": current.get("requested_by", "writer"),
        "instruction": current.get("instruction"),
        "scope": current.get("scope", "local_episode"),
        "affects_future": current.get("affects_future", False),
        "status": new_status,
        "previous_status": current.get("status"),
        "reason": reason,
        "operator": operator,
        "applied_to": current.get("applied_to"),
        "created_at": current.get("created_at"),
        "updated_at": now_iso(),
    }
    _append_revision(project_dir, record)
    # Derived override stream (never the source of truth for context).
    append_writer_override(
        project_dir,
        {
            "revision_id": revision_id,
            "episode": record["episode"],
            "source": record["source"],
            "requested_by": record["requested_by"],
            "instruction": record["instruction"],
            "scope": record["scope"],
            "affects_future": record["affects_future"],
            "status": new_status,
            "applied_to": record.get("applied_to"),
            "created_at": record["created_at"],
        },
    )
    return record


def _revision_state(project_dir: Path, revision_id: str) -> dict | None:
    records = [r for r in _revisions(project_dir) if r.get("revision_id") == revision_id]
    return records[-1] if records else None


def mark_revisions_applied(
    project_dir: Path,
    *,
    episode: int,
    revision_ids: list[str],
    applied_to_kind: str,
    applied_to_version: str,
) -> int:
    """Bind ONLY explicitly listed approved revisions to a concrete version."""
    changed = 0
    for revision_id in revision_ids:
        state = _revision_state(project_dir, revision_id)
        if state is None or state.get("episode") != episode:
            continue
        if state.get("status") != "approved":
            continue
        transition_revision(
            project_dir,
            revision_id,
            "applied",
            reason=f"bound to {applied_to_kind} {applied_to_version}",
            operator="cli",
        )
        # Preserve the applied_to binding on the applied event.
        records = _revisions(project_dir)
        records[-1]["applied_to"] = {"kind": applied_to_kind, "version": applied_to_version}
        path = project_dir / "state" / "revisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(__import__("json").dumps(record, ensure_ascii=False) + "\n")
        changed += 1
    return changed
