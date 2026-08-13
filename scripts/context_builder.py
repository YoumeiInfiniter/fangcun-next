"""Single-episode context builder (deterministic, spec §12).

Produces an immutable episode_context snapshot that Writer, Reviewer and
Rewriter all consume. The context_hash binds the snapshot; any consumer
must verify the hash before trusting the contents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import atomic_write_json, canonical_json, ensure_dir, stable_hash
from .source_retriever import retrieve_source_evidence, source_evidence_complete
from .state_store import (
    active_artifact_path,
    active_version_id,
    artifact_versions,
    load_continuity,
    load_config,
    resolve_active,
    writer_overrides,
    load_manifest,
)
from .prompt_router import select_craft_modules
from .stage_lifecycle import episode_density_report
from .capacity_plan import capacity_plan_for
from .execution_brief import build_episode_execution_brief
from .batch_context import provisional_batch_context


class ContextIncompleteError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def context_dir(project_dir: Path) -> Path:
    return project_dir / "state" / "episode_contexts"


def snapshot_path(project_dir: Path, episode: int, context_hash: str) -> Path:
    return context_dir(project_dir) / f"episode_context_EP{episode:03d}_{context_hash}.json"


def current_pointer_path(project_dir: Path, episode: int) -> Path:
    return context_dir(project_dir) / f"current_EP{episode:03d}.json"


def current_context_path(project_dir: Path, episode: int) -> Path | None:
    """Read the current snapshot pointer; None when missing."""
    from .common import read_json

    pointer = read_json(current_pointer_path(project_dir, episode))
    if not isinstance(pointer, dict):
        return None
    path = context_dir(project_dir) / (pointer.get("path") or "")
    return path if path.exists() else None


def find_context_snapshot(project_dir: Path, episode: int, context_hash: str) -> Path | None:
    """Locate an immutable snapshot by its hash (survives pointer changes)."""
    expected = snapshot_path(project_dir, episode, context_hash)
    if expected.exists():
        return expected
    # Legacy 8-char-prefix snapshots from round 1.
    matches = sorted(context_dir(project_dir).glob(f"episode_context_EP{episode:03d}_*.json"))
    for path in matches:
        from .common import read_json

        data = read_json(path)
        if isinstance(data, dict) and data.get("context_hash") == context_hash:
            return path
    return None


def previous_hook_from_continuity(continuity: dict, episode: int) -> str | None:
    for hook in continuity.get("open_hooks", []) or []:
        if hook.get("introduced_in") == episode - 1 and hook.get("status", "open") == "open":
            return str(hook.get("hook", "")) or None
    return None


def _applicable_overrides(project_dir: Path, episode: int) -> list[dict]:
    from .revision_manager import list_revisions

    # Single source of truth: current state projected from the revision log.
    records = list_revisions(project_dir)
    applicable = []
    for record in records:
        if record.get("status") in ("pending", "rejected", "revoked"):
            continue
        target = record.get("episode")
        propagates = record.get("scope") in ("future_episodes", "project_wide") or bool(record.get("affects_future"))
        if isinstance(target, int) and target == episode:
            applicable.append(record)
        elif isinstance(target, int) and target < episode and propagates:
            applicable.append(record)
        elif not isinstance(target, int) and propagates:
            applicable.append(record)
    return applicable


def _contract_problems_from_coverage(evidence: dict) -> list[str]:
    """must_keep / required_story_beats / required_quotes traceability."""
    anchor_types = {"must_keep", "required_story_beat", "required_quote"}
    return [
        f"must_keep「{item.get('anchor_id')}」未找到原文依据或改编依据"
        for item in evidence.get("coverage", []) or []
        if item.get("anchor_type") in anchor_types and item.get("omitted")
    ]


def pending_revisions(project_dir: Path, episode: int) -> list[dict]:
    """Pending revisions relevant to this episode, including future-scoped ones."""
    from .revision_manager import list_revisions

    records = list_revisions(project_dir)
    pending = []
    for r in records:
        if r.get("status") != "pending":
            continue
        target = r.get("episode")
        propagates = r.get("scope") in ("future_episodes", "project_wide") or bool(r.get("affects_future"))
        if target == episode or (isinstance(target, int) and target < episode and propagates) or propagates:
            pending.append(r)
    return pending


def build_episode_context(
    project_dir: Path,
    episode: int,
    *,
    role: str = "writer",
    max_source_chars: int = 6000,
    per_chapter_budget: int = 2000,
    craft_operation: str | None = None,
    save: bool = True,
) -> dict:
    """Build the immutable context snapshot for one episode."""
    config = load_config(project_dir)
    outlines = _load_episode_outlines(project_dir)
    outline = outlines.get(episode)
    if not outline:
        raise ContextIncompleteError([f"第{episode}集没有任何集纲或编剧指令"])

    events = _load_events(project_dir)
    evidence = retrieve_source_evidence(
        project_dir,
        outline,
        events,
        max_chars=max_source_chars,
        per_chapter_budget=per_chapter_budget,
    )
    evidence_problems = source_evidence_complete(evidence)
    adaptation_basis = outline.get("adaptation_basis", []) or []
    has_source_request = bool(
        outline.get("source_event_ids")
        or outline.get("source_chapters")
        or outline.get("dialogue_anchors")
        or outline.get("required_story_beats")
        or outline.get("required_quotes")
        or outline.get("beat_plan")
    )
    must_keep_problems = _contract_problems_from_coverage(evidence)
    # A genuinely adaptation-only episode may have no source request, but its
    # must_keep items must still bind to explicit adaptation decision IDs.
    all_problems = (
        evidence_problems if has_source_request or not adaptation_basis else []
    ) + must_keep_problems
    # Adaptation decisions are valid only for the must_keep item explicitly
    # bound to that decision.  They can never waive an unrelated missing
    # source event, chapter, dialogue quote or setup/payoff pair.
    if all_problems:
        raise ContextIncompleteError(list(dict.fromkeys(all_problems)))

    continuity = load_continuity(project_dir)
    previous_script = None
    previous_path = active_artifact_path(project_dir, "approved_script", episode - 1) if episode > 1 else None
    if previous_path and previous_path.exists():
        previous_script = previous_path.read_text(encoding="utf-8")
    current_approved_script = None
    current_approved_path = active_artifact_path(project_dir, "approved_script", episode)
    if current_approved_path and current_approved_path.exists():
        current_approved_script = current_approved_path.read_text(encoding="utf-8")

    overrides = _applicable_overrides(project_dir, episode)
    craft_modules = select_craft_modules(config, outline, craft_operation)
    from .common import read_json

    events_data = read_json(active_artifact_path(project_dir, "source_events")) if active_artifact_path(project_dir, "source_events") else {}
    events_list = events_data.get("events", events_data) if isinstance(events_data, dict) else events_data
    events_by_id = {
        str(item.get("event_id")): item
        for item in (events_list or [])
        if isinstance(item, dict) and item.get("event_id")
    }
    density_report = episode_density_report(
        outline,
        events_by_id,
        outline_version=active_version_id(project_dir, "episode_outline"),
        outline_hash=(
            (resolve_active(project_dir, "episode_outline") or {}).get("record", {}).get("content_hash")
        ),
    )

    outline_resolved = resolve_active(project_dir, "episode_outline")
    outline_hash = (outline_resolved or {}).get("record", {}).get("content_hash")
    capacity_plan = capacity_plan_for(project_dir, outline_hash=outline_hash)
    runtime_version = load_manifest(project_dir).get("runtime_version")
    outline_record_meta = (outline_resolved or {}).get("record", {}).get("meta") or {}
    legacy_outline = (
        not outline_record_meta.get("outline_contract_version")
        and not outline_record_meta.get("stage_context_hash")
        and not outline_record_meta.get("capacity_plan_binding")
    )
    if density_report.get("pressure") in ("medium", "high") and runtime_version == "0.3.7" and not legacy_outline:
        if not capacity_plan or capacity_plan.get("status") != "approved":
            raise ContextIncompleteError(
                [
                    "当前集纲存在 medium/high 容量风险，但没有绑定当前 forecast/outline hash 的已确认 capacity_plan；"
                    "先生成方案并由编剧选择具体集数、时长与事件取舍。"
                ]
            )

    provisional = provisional_batch_context(project_dir, episode)
    if provisional and provisional.get("invalidated_previous_episodes"):
        stale = provisional["invalidated_previous_episodes"]
        labels = ", ".join(f"EP{int(item.get('episode', 0)):03d}" for item in stale)
        raise ContextIncompleteError(
            [
                f"当前要继续 EP{episode:03d}，但同批前集 {labels} 仍为 stale/unusable；"
                "请先重新生成并审核这些前集，再重新获取当前集上下文。"
            ]
        )
    execution_brief = build_episode_execution_brief(
        outline,
        evidence,
        continuity,
        capacity_plan,
        provisional,
    )

    advisory = {
        "minimum_seconds": config.get("minimum_episode_seconds", 0),
        "preferred_seconds": config.get("preferred_episode_seconds"),
        "outline_suggested_seconds": outline.get("suggested_seconds"),
        "density_report": density_report,
    }

    body = {
        "episode": episode,
        "project_brief": config,
        "adaptation_summary": _load_summary(project_dir, "adaptation_strategy"),
        "story_summary": _load_summary(project_dir, "story_outline"),
        "episode_outline": outline,
        "context_versions": {
            "episode_outline_version": active_version_id(project_dir, "episode_outline"),
            "source_events_version": active_version_id(project_dir, "source_events"),
            "adaptation_strategy": _active_binding(project_dir, "adaptation_strategy"),
            "story_outline": _active_binding(project_dir, "story_outline"),
            "episode_outline": _active_binding(project_dir, "episode_outline"),
        },
        "source_evidence": evidence,
        "previous_approved_script": previous_script,
        "current_approved_script": current_approved_script,
        "previous_episode_hook": previous_hook_from_continuity(continuity, episode),
        "continuity_state": continuity,
        "writer_overrides": overrides,
        "pending_revisions": pending_revisions(project_dir, episode),
        "selected_craft_modules": craft_modules,
        "format_profile": config.get("script_format", "default-cn"),
        "advisory_timing": advisory,
        "capacity_plan": capacity_plan,
        "provisional_batch_context": provisional,
        "episode_execution_brief": execution_brief,
    }
    context = {**body, "context_hash": stable_hash(body)}
    # The nested brief is derived from this context.  Its own hash is stable
    # over the brief fields, while this binding makes the relationship
    # explicit without creating a circular context hash.
    execution_brief["context_hash"] = context["context_hash"]
    context["role"] = role
    context["completeness"] = {
        "problems": [],
        "warnings": [],
        "evidence_problems": evidence_problems,
        "must_keep_problems": must_keep_problems,
    }
    if save:
        path = snapshot_path(project_dir, episode, context["context_hash"])
        ensure_dir(path.parent)
        snapshot_content = {**body, "context_hash": context["context_hash"]}
        if path.exists():
            existing = __import__("json").loads(path.read_text(encoding="utf-8"))
            if canonical_json(existing) != canonical_json(snapshot_content):
                raise ContextIncompleteError(
                    [f"context hash 路径碰撞或快照被篡改：{path}；拒绝覆盖不可变快照"]
                )
        else:
            atomic_write_json(path, snapshot_content)
        context["context_file"] = str(path)
        atomic_write_json(
            current_pointer_path(project_dir, episode),
            {
                "context_hash": context["context_hash"],
                "path": path.name,
                "episode_outline_version": body["context_versions"]["episode_outline_version"],
                "source_events_version": body["context_versions"]["source_events_version"],
                "created_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
        )
    return context


def verify_context_hash(context: dict) -> tuple[bool, str]:
    """Recompute the hash over every semantic field (immutable snapshot)."""
    expected = context.get("context_hash", "")
    body = {
        k: v
        for k, v in context.items()
        if k not in ("context_hash", "context_file", "completeness", "role")
    }
    brief = body.get("episode_execution_brief")
    if isinstance(brief, dict) and "context_hash" in brief:
        brief = dict(brief)
        brief.pop("context_hash", None)
        body["episode_execution_brief"] = brief
    actual = stable_hash(body)
    return actual == expected, expected


def _load_episode_outlines(project_dir: Path) -> dict[int, dict]:
    path = active_artifact_path(project_dir, "episode_outline")
    if not path or not path.exists():
        return {}
    from .common import read_json

    data = read_json(path)
    if isinstance(data, dict) and "episodes" in data:
        return {int(e.get("episode")): e for e in data.get("episodes", [])}
    if isinstance(data, dict) and "episode" in data:
        return {int(data["episode"]): data}
    if isinstance(data, list):
        return {int(e.get("episode")): e for e in data if isinstance(e, dict)}
    return {}


def _load_events(project_dir: Path) -> list[dict]:
    from .common import read_json

    path = active_artifact_path(project_dir, "source_events")
    if not path or not path.exists():
        return []
    data = read_json(path)
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict) and "events" in data:
        return [e for e in data["events"] if isinstance(e, dict)]
    return []


def _load_summary(project_dir: Path, kind: str) -> dict:
    from .common import read_json

    summary_kind = {
        "adaptation_strategy": "adaptation_summary",
        "story_outline": "story_outline_summary",
    }.get(kind)
    if summary_kind:
        summary_path = active_artifact_path(project_dir, summary_kind)
        if summary_path and summary_path.exists():
            summary_resolved = resolve_active(project_dir, summary_kind)
            stage_resolved = resolve_active(project_dir, kind)
            summary_meta = (summary_resolved or {}).get("record", {}).get("meta") or {}
            if stage_resolved and summary_meta.get("parent_stage_version") == stage_resolved.get("version"):
                data = read_json(summary_path)
                return data if isinstance(data, dict) else {}
    path = active_artifact_path(project_dir, kind)
    if not path or not path.exists():
        return {}
    if path.suffix == ".json":
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    # Markdown artifacts are summarized by their title/first heading at save
    # time; the machine-readable summary lives in the same artifact folder.
    summary_path = path.parent / f"{path.stem}.summary.json"
    if summary_path.exists():
        data = read_json(summary_path)
        return data if isinstance(data, dict) else {}
    return {"source_file": str(path)}


def _active_binding(project_dir: Path, kind: str) -> dict | None:
    resolved = resolve_active(project_dir, kind)
    if not resolved:
        return None
    return {
        "version": resolved["version"],
        "content_hash": resolved["record"].get("content_hash"),
        "status": resolved["record"].get("status"),
    }
