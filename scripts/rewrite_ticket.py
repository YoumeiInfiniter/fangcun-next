"""System-issued one-time rewrite provenance tickets (R2-S0-3).

A rewrite ticket binds episode / context_hash / review version+hash /
source draft version+hash. API Mode and Host Agent Mode both consume the
same ticket; a ticket can be consumed exactly once, and a consumed ticket's
draft is marked as automatic rewrite so it cannot be auto-rewritten again.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from .common import jsonl_append, now_iso, read_jsonl


def _ticket_path(project_dir: Path) -> Path:
    return project_dir / "state" / "rewrite_tickets.jsonl"


def ticket_state(project_dir: Path, ticket_id: str) -> dict | None:
    records = [r for r in read_jsonl(_ticket_path(project_dir)) if r.get("ticket_id") == ticket_id]
    return records[-1] if records else None


def issue_rewrite_ticket(
    project_dir: Path,
    *,
    episode: int,
    context_hash: str,
    review_version: str,
    review_hash: str,
    source_draft_version: str,
    source_draft_hash: str,
) -> dict:
    existing = _find_issued_by_binding(
        project_dir,
        episode=episode,
        context_hash=context_hash,
        review_version=review_version,
        review_hash=review_hash,
        source_draft_version=source_draft_version,
        source_draft_hash=source_draft_hash,
    )
    if existing is not None:
        return existing
    ticket = {
        "ticket_id": f"TKT-{episode:03d}-{uuid.uuid4().hex[:12]}",
        "episode": episode,
        "context_hash": context_hash,
        "review_version": review_version,
        "review_hash": review_hash,
        "source_draft_version": source_draft_version,
        "source_draft_hash": source_draft_hash,
        "status": "issued",
        "created_at": now_iso(),
    }
    jsonl_append(_ticket_path(project_dir), ticket)
    return ticket


def _find_issued_by_binding(
    project_dir: Path,
    *,
    episode: int,
    context_hash: str,
    review_version: str,
    review_hash: str,
    source_draft_version: str,
    source_draft_hash: str,
) -> dict | None:
    records = read_jsonl(_ticket_path(project_dir))
    latest_by_id: dict[str, dict] = {}
    for record in records:
        latest_by_id[record.get("ticket_id")] = record
    for record in latest_by_id.values():
        if record.get("status") != "issued":
            continue
        bindings = {
            "episode": episode,
            "context_hash": context_hash,
            "review_version": review_version,
            "review_hash": review_hash,
            "source_draft_version": source_draft_version,
            "source_draft_hash": source_draft_hash,
        }
        if all(record.get(key) == value for key, value in bindings.items()):
            return record
    return None


def cancel_rewrite_ticket(
    project_dir: Path,
    ticket_id: str,
    *,
    reason: str = "",
    operator: str = "cli",
) -> dict:
    current = ticket_state(project_dir, ticket_id)
    if current is None:
        raise ValueError(f"rewrite ticket 不存在：{ticket_id}")
    if current.get("status") == "consumed":
        raise ValueError(f"rewrite ticket {ticket_id} 已消费，不能取消")
    cancelled = {**current, "status": "cancelled", "cancelled_at": now_iso(), "reason": reason, "operator": operator}
    jsonl_append(_ticket_path(project_dir), cancelled)
    return cancelled


def cancel_issued_tickets_for_binding(
    project_dir: Path,
    *,
    episode: int,
    context_hash: str,
    reason: str,
    operator: str = "cli",
) -> int:
    """Cancel all issued tickets for an episode+context binding (manual-edit path)."""
    cancelled = 0
    records = read_jsonl(_ticket_path(project_dir))
    latest_by_id: dict[str, dict] = {}
    for record in records:
        latest_by_id[record.get("ticket_id")] = record
    for record in latest_by_id.values():
        if (
            record.get("status") == "issued"
            and record.get("episode") == episode
            and record.get("context_hash") == context_hash
        ):
            cancel_rewrite_ticket(project_dir, record["ticket_id"], reason=reason, operator=operator)
            cancelled += 1
    return cancelled


def consume_rewrite_ticket(
    project_dir: Path,
    ticket_id: str,
    *,
    episode: int,
    context_hash: str,
    review_version: str,
    review_hash: str,
    source_draft_version: str,
    source_draft_hash: str,
) -> dict:
    current = ticket_state(project_dir, ticket_id)
    if current is None:
        raise ValueError(f"rewrite ticket 不存在：{ticket_id}")
    if current.get("status") != "issued":
        raise ValueError(f"rewrite ticket {ticket_id} 状态为 {current.get('status')}，不能重复消费")
    bindings = {
        "episode": current.get("episode"),
        "context_hash": current.get("context_hash"),
        "review_version": current.get("review_version"),
        "review_hash": current.get("review_hash"),
        "source_draft_version": current.get("source_draft_version"),
        "source_draft_hash": current.get("source_draft_hash"),
    }
    provided = {
        "episode": episode,
        "context_hash": context_hash,
        "review_version": review_version,
        "review_hash": review_hash,
        "source_draft_version": source_draft_version,
        "source_draft_hash": source_draft_hash,
    }
    for key, expected in bindings.items():
        if provided[key] != expected:
            raise ValueError(f"rewrite ticket {ticket_id} 绑定 {key} 不一致，拒绝消费")
    consumed = {**current, "status": "consumed", "consumed_at": now_iso()}
    jsonl_append(_ticket_path(project_dir), consumed)
    return consumed


def latest_issued_ticket(project_dir: Path, episode: int) -> dict | None:
    """Return the most recent issued ticket for an episode (if any)."""
    latest_by_id: dict[str, dict] = {}
    for record in read_jsonl(_ticket_path(project_dir)):
        if record.get("episode") == episode:
            latest_by_id[record.get("ticket_id")] = record
    for record in latest_by_id.values():
        if record.get("status") == "issued":
            return record
    return None
