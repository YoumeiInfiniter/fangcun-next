"""Provisional same-batch context that never mutates formal continuity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import atomic_write_json, ensure_dir, now_iso, read_json, stable_hash
from .continuity_manager import extract_deterministic
from .state_store import (
    active_artifact_path,
    active_version_id,
    artifact_version_record,
    read_artifact_version,
)


DEFAULT_BATCH_SIZE = 3


def batch_dir(project_dir: Path) -> Path:
    return project_dir / "state" / "provisional_batches"


def batch_path(project_dir: Path, batch_id: str) -> Path:
    return batch_dir(project_dir) / f"{batch_id}.json"


def current_batch_pointer(project_dir: Path) -> Path:
    return batch_dir(project_dir) / "current.json"


def _write_batch(project_dir: Path, batch: dict) -> dict:
    ensure_dir(batch_dir(project_dir))
    batch["updated_at"] = now_iso()
    atomic_write_json(batch_path(project_dir, batch["batch_id"]), batch)
    atomic_write_json(current_batch_pointer(project_dir), {"batch_id": batch["batch_id"], "updated_at": batch["updated_at"]})
    return batch


def _read_current(project_dir: Path) -> dict | None:
    pointer = read_json(current_batch_pointer(project_dir))
    if not isinstance(pointer, dict) or not pointer.get("batch_id"):
        return None
    data = read_json(batch_path(project_dir, str(pointer["batch_id"])))
    return data if isinstance(data, dict) else None


def find_open_batch(project_dir: Path, episode: int | None = None) -> dict | None:
    batch = _read_current(project_dir)
    if not batch or batch.get("status") not in ("provisional", "confirmed"):
        return None
    episodes = set(int(value) for value in (batch.get("episodes") or []) if str(value).isdigit())
    if episode is not None and episode not in episodes:
        return None
    if batch.get("status") == "confirmed" and episode is not None:
        # A confirmed batch remains readable for audit, but is no longer a
        # source of new provisional context.
        return batch
    return batch


def start_provisional_batch(
    project_dir: Path,
    *,
    start_episode: int,
    size: int = DEFAULT_BATCH_SIZE,
    review_isolation: str = "isolated",
) -> dict:
    if start_episode < 1:
        raise ValueError("批次起始集数必须 >= 1")
    if size < 1:
        raise ValueError("批次大小必须 >= 1")
    if review_isolation not in ("isolated", "degraded"):
        raise ValueError("review_isolation 必须是 isolated 或 degraded")
    current = _read_current(project_dir)
    if current and current.get("status") == "provisional":
        raise ValueError(f"已有未确认临时批次 {current.get('batch_id')}，请先确认或结束")
    batch_id = f"PB-{start_episode:03d}-{size:02d}-{stable_hash({'start': start_episode, 'size': size, 'at': now_iso()})[:8]}"
    batch = {
        "batch_id": batch_id,
        "batch_version": "0.3.7",
        "start_episode": start_episode,
        "size": size,
        "episodes": list(range(start_episode, start_episode + size)),
        "status": "provisional",
        "review_isolation": review_isolation,
        "records": {},
        "confirmation_ref": None,
        "confirmation_operator": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    return _write_batch(project_dir, batch)


create_provisional_batch = start_provisional_batch


def _record(batch: dict, episode: int) -> dict:
    records = batch.setdefault("records", {})
    return records.setdefault(str(episode), {"episode": episode, "status": "empty", "unconfirmed": True})


def _invalidate_later(batch: dict, episode: int, reason: str) -> None:
    for value in (batch.get("episodes") or []):
        target = int(value)
        if target <= episode:
            continue
        item = _record(batch, target)
        if item.get("draft_hash") or item.get("review_hash") or item.get("temporary_continuity"):
            item["status"] = "stale"
            item["usable"] = False
            item["review_status"] = "stale"
            item["invalidated_by_episode"] = episode
            item["invalidation_reason"] = reason


def record_provisional_draft(
    project_dir: Path,
    *,
    episode: int,
    draft_version: str,
    draft_hash: str,
    draft_text: str,
    context_hash: str,
) -> dict | None:
    batch = find_open_batch(project_dir, episode)
    if not batch or batch.get("status") != "provisional":
        return None
    item = _record(batch, episode)
    previous_hash = item.get("draft_hash")
    if previous_hash and previous_hash != draft_hash:
        _invalidate_later(batch, episode, "前集草稿版本变化，后续临时上下文需要重建")
        # A review is bound to the old draft.  Do not let it survive a local
        # rewrite of the same episode.
        for key in ("review_version", "review_hash", "review_verdict", "review_status", "review_isolation", "reviewed_at"):
            item.pop(key, None)
    item.update(
        {
            "episode": episode,
            "draft_version": draft_version,
            "draft_hash": draft_hash,
            "draft_context_hash": context_hash,
            "draft_status": "unconfirmed",
            "status": "drafted",
            "usable": True,
            "unconfirmed": True,
            "temporary_continuity": {
                **extract_deterministic(episode, draft_text),
                "state": "unconfirmed",
                "source_draft_version": draft_version,
                "source_draft_hash": draft_hash,
            },
            "recorded_at": now_iso(),
        }
    )
    for key in ("invalidated_by_episode", "invalidation_reason"):
        item.pop(key, None)
    return _write_batch(project_dir, batch)


def record_provisional_review(
    project_dir: Path,
    *,
    episode: int,
    review_version: str,
    review_hash: str,
    verdict: str,
    review_isolation: str = "isolated",
) -> dict | None:
    batch = find_open_batch(project_dir, episode)
    if not batch or batch.get("status") != "provisional":
        return None
    item = _record(batch, episode)
    if not item.get("draft_hash") or item.get("status") == "stale" or item.get("usable") is False:
        raise ValueError(f"EP{episode:03d} 尚无可审核的当前草稿，不能记录临时审核")
    item.update(
        {
            "review_version": review_version,
            "review_hash": review_hash,
            "review_verdict": verdict,
            "review_status": "unconfirmed",
            "review_isolation": review_isolation,
            "review_draft_hash": item.get("draft_hash"),
            "unconfirmed": True,
            "reviewed_at": now_iso(),
        }
    )
    return _write_batch(project_dir, batch)


def provisional_batch_context(project_dir: Path, episode: int) -> dict | None:
    batch = find_open_batch(project_dir, episode)
    if not batch or batch.get("status") != "provisional":
        return None
    previous: list[dict] = []
    invalidated: list[dict] = []
    current_item = int(episode)
    for value in (batch.get("episodes") or []):
        ep = int(value)
        if ep >= current_item:
            continue
        item = dict(_record(batch, ep))
        if item.get("status") == "stale" or item.get("usable") is False:
            invalidated.append(item)
            continue
        # Text and report are fetched from immutable artifact versions only;
        # the batch file stores bindings, not a second mutable copy.
        if item.get("draft_version"):
            path = artifact_version_record(project_dir, "script_draft", ep, item["draft_version"])
            if path and path.get("content_hash") == item.get("draft_hash"):
                draft_path = active_artifact_path(project_dir, "script_draft", ep)
                # Resolve the exact immutable version instead of the active
                # pointer, which may already have moved.
                from .state_store import artifact_version_path

                exact = artifact_version_path(project_dir, "script_draft", ep, item["draft_version"])
                if exact and exact.exists():
                    item["draft_text"] = exact.read_text(encoding="utf-8")
        if item.get("review_version"):
            try:
                review = read_artifact_version(project_dir, "review", ep, item["review_version"])
                if isinstance(review, dict) and item.get("review_hash"):
                    item["review_summary"] = {
                        "verdict": review.get("verdict"),
                        "summary": review.get("summary"),
                        "review_hash": item.get("review_hash"),
                    }
            except (KeyError, ValueError):
                item["review_summary"] = None
        previous.append(item)
    return {
        "batch_id": batch.get("batch_id"),
        "batch_status": "provisional",
        "unconfirmed": True,
        "review_isolation": batch.get("review_isolation", "isolated"),
        "previous_episodes": previous,
        "invalidated_previous_episodes": invalidated,
        "rebuild_required": bool(invalidated),
        "rebuild_instruction": (
            "请先重新生成并审核被标 stale 的前集，然后再继续当前集；未重建前不得把临时内容当作连续性事实。"
            if invalidated
            else ""
        ),
        "instruction": "以下内容来自同批未确认草稿/审核，只可作临时上下文，不得当作正式连续性事实。",
    }


get_provisional_batch_context = provisional_batch_context


def confirm_provisional_batch(
    project_dir: Path,
    *,
    batch_id: str | None = None,
    operator: str,
    confirmation_ref: str,
) -> dict:
    batch = _read_current(project_dir)
    if not batch or (batch_id and batch.get("batch_id") != batch_id):
        raise ValueError("找不到待确认临时批次")
    if batch.get("status") != "provisional":
        raise ValueError("该批次已经确认或不可确认")
    if not str(operator or "").strip() or not str(confirmation_ref or "").strip():
        raise ValueError("确认临时批次必须提供 operator 和 confirmation_ref")
    confirmation_errors: list[str] = []
    records = batch.get("records") or {}
    for value in (batch.get("episodes") or []):
        episode = int(value)
        item = records.get(str(episode))
        if not isinstance(item, dict):
            confirmation_errors.append(f"EP{episode:03d} 缺少临时记录")
            continue
        if item.get("status") == "stale" or item.get("usable") is False:
            confirmation_errors.append(
                f"EP{episode:03d} 仍是 stale/unusable（{item.get('invalidation_reason') or '需要重建'}）"
            )
        draft_version = item.get("draft_version")
        draft_hash = item.get("draft_hash")
        draft_record = artifact_version_record(project_dir, "script_draft", episode, draft_version) if draft_version else None
        if not draft_record or not draft_hash or draft_record.get("content_hash") != draft_hash:
            confirmation_errors.append(f"EP{episode:03d} 缺少与当前记录匹配的草稿，请先重建草稿")
        review_version = item.get("review_version")
        review_hash = item.get("review_hash")
        review_record = artifact_version_record(project_dir, "review", episode, review_version) if review_version else None
        if not review_record or not review_hash or review_record.get("content_hash") != review_hash:
            confirmation_errors.append(f"EP{episode:03d} 缺少与当前草稿匹配的审核，请先完成审核")
            continue
        try:
            review = read_artifact_version(project_dir, "review", episode, review_version)
        except (KeyError, ValueError):
            review = None
        if not isinstance(review, dict):
            confirmation_errors.append(f"EP{episode:03d} 审核产物不可读，请重建审核")
        else:
            if review.get("draft_hash") != draft_hash or item.get("review_draft_hash") not in (None, draft_hash):
                confirmation_errors.append(f"EP{episode:03d} 审核不是当前草稿的审核，请重建审核")
            if review.get("verdict") == "blocked":
                confirmation_errors.append(f"EP{episode:03d} 审核仍为 blocked，请修复后重新审核")
    if confirmation_errors:
        raise ValueError("临时批次不能确认：\n" + "\n".join(f"- {item}" for item in confirmation_errors))
    batch["status"] = "confirmed"
    batch["confirmation_operator"] = operator.strip()
    batch["confirmation_ref"] = confirmation_ref.strip()
    batch["confirmed_at"] = now_iso()
    for item in (batch.get("records") or {}).values():
        item["batch_confirmation"] = "confirmed"
        item["formal_continuity_status"] = "pending_episode_approval"
    return _write_batch(project_dir, batch)


def batch_status(project_dir: Path) -> dict | None:
    return _read_current(project_dir)
