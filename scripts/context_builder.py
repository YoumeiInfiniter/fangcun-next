"""Single-episode context builder (deterministic, spec §12).

Produces an immutable episode_context snapshot that Writer, Reviewer and
Rewriter all consume. The context_hash binds the snapshot; any consumer
must verify the hash before trusting the contents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import atomic_write_json, ensure_dir, stable_hash, sha256_file
from .source_retriever import retrieve_source_evidence, source_evidence_complete
from .state_store import (
    active_artifact_path,
    artifact_versions,
    load_continuity,
    load_config,
    writer_overrides,
)
from .prompt_router import select_craft_modules


class ContextIncompleteError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def context_dir(project_dir: Path) -> Path:
    return project_dir / "state" / "episode_contexts"


def context_path(project_dir: Path, episode: int) -> Path:
    return context_dir(project_dir) / f"episode_context_EP{episode:03d}.json"


def previous_hook_from_continuity(continuity: dict, episode: int) -> str | None:
    for hook in continuity.get("open_hooks", []) or []:
        if hook.get("introduced_in") == episode - 1 and hook.get("status", "open") == "open":
            return str(hook.get("hook", "")) or None
    return None


def _applicable_overrides(project_dir: Path, episode: int) -> list[dict]:
    records = writer_overrides(project_dir)
    applicable = []
    for record in records:
        if record.get("status") in ("pending", "rejected"):
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


def _must_keep_evidence_check(outline: dict, evidence: dict) -> list[str]:
    """Each must_keep needs at least a source or adaptation basis."""
    warnings: list[str] = []
    all_text = "\n".join(ex.get("text", "") for ex in evidence.get("raw_excerpts", []) or [])

    def _event_parts(event: dict) -> list[str]:
        parts = [str(event.get("event", "")), str(event.get("result", ""))]
        actions = event.get("actions")
        if isinstance(actions, list):
            parts.extend(str(a) for a in actions)
        return parts

    event_text = "\n".join(" ".join(_event_parts(e)) for e in evidence.get("events", []) or [])
    adaptation_basis = outline.get("adaptation_basis", []) or []
    for item in outline.get("must_keep", []) or []:
        if not item:
            continue
        has_source = item in all_text or item in event_text
        has_basis = any(item in str(b) for b in adaptation_basis)
        if not has_source and not has_basis:
            warnings.append(f"must_keep「{item}」未找到原文依据或改编依据")
    return warnings


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
    if evidence_problems and not adaptation_basis:
        raise ContextIncompleteError(evidence_problems)

    continuity = load_continuity(project_dir)
    previous_script = None
    previous_path = active_artifact_path(project_dir, "approved_script", episode - 1) if episode > 1 else None
    if previous_path and previous_path.exists():
        previous_script = previous_path.read_text(encoding="utf-8")

    overrides = _applicable_overrides(project_dir, episode)
    craft_modules = select_craft_modules(config, outline, craft_operation)

    advisory = {
        "minimum_seconds": config.get("minimum_episode_seconds", 0),
        "preferred_seconds": config.get("preferred_episode_seconds"),
        "outline_suggested_seconds": outline.get("suggested_seconds"),
    }

    body = {
        "episode": episode,
        "project_brief": config,
        "adaptation_summary": _load_summary(project_dir, "adaptation_strategy"),
        "story_summary": _load_summary(project_dir, "story_outline"),
        "episode_outline": outline,
        "source_evidence": evidence,
        "previous_approved_script": previous_script,
        "previous_episode_hook": previous_hook_from_continuity(continuity, episode),
        "continuity_state": continuity,
        "writer_overrides": overrides,
        "selected_craft_modules": craft_modules,
        "format_profile": config.get("script_format", "default-cn"),
        "advisory_timing": advisory,
    }
    context = {**body, "context_hash": stable_hash(body)}
    context["role"] = role
    context["completeness"] = {
        "problems": [],
        "warnings": _must_keep_evidence_check(outline, evidence),
        "evidence_problems": evidence_problems,
    }
    if save:
        path = context_path(project_dir, episode)
        ensure_dir(path.parent)
        atomic_write_json(path, context)
        context["context_file"] = str(path)
        (path.parent / f"episode_context_EP{episode:03d}.sha256").write_text(
            sha256_file(path) + "  " + path.name + "\n", encoding="utf-8"
        )
    return context


def verify_context_hash(context: dict) -> tuple[bool, str]:
    """Recompute the hash over all fields except context_hash."""
    expected = context.get("context_hash", "")
    body = {
        k: v
        for k, v in context.items()
        if k not in ("context_hash", "context_file", "completeness", "role")
    }
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
