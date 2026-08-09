"""Continuity management from approved scripts (spec §18, §22.2).

Deterministic extraction is always run. Model-assisted extraction is used
only when an API is configured; without one, extraction_mode is
"deterministic" and the runtime says so instead of pretending otherwise.
Continuity can always be rebuilt from all approved scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import now_iso, read_json, sha256_text, stable_hash
from .schema_validate import ensure_valid
from .script_validator import parse_script
from .state_store import (
    active_artifact_path,
    active_version_id,
    append_writer_override,
    artifact_version_record,
    commit_artifact,
    load_continuity,
    load_config,
    save_continuity,
    writer_overrides,
)


def _fresh_continuity() -> dict:
    """Create a brand-new continuity object; never share nested containers."""
    return {
        "version": 0,
        "updated_from_episode": None,
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
        "episode_extraction": {},
        "degraded_episodes": [],
    }


def extract_deterministic(episode: int, script_text: str) -> dict:
    """Deterministic pass over an approved script: speakers, locations, hook."""
    parsed = parse_script(script_text)
    scenes = parsed.get("scenes", [])
    locations: dict[str, int] = {}
    for scene in scenes:
        key = scene["location"]
        locations[key] = locations.get(key, 0) + 1
    speakers = list(dict.fromkeys(parsed.get("speakers", [])))
    last_content = None
    for scene in reversed(scenes):
        for block in reversed(scene.get("dialogues", []) + scene.get("actions", [])):
            last_content = block.get("text", "")
            break
        if last_content:
            break
    return {
        "extraction_mode": "deterministic",
        "episode": episode,
        "characters_seen": speakers,
        "locations": locations,
        "ending_hook_candidate": last_content,
        "scene_count": len(scenes),
    }


def extract_model_assisted(project_dir: Path, episode: int, script_text: str) -> dict | None:
    """Model-assisted fact/knowledge extraction. Returns None without API."""
    config = load_config(project_dir)
    model_config = config.get("model_config")
    if not model_config or not model_config.get("api_url"):
        return None
    try:
        from .model_adapter import call_generate
        from .prompt_router import _stage_prompt
        from .context_builder import build_episode_context
    except Exception:
        return None
    try:
        context = build_episode_context(project_dir, episode, role="continuity_extract", save=False)
        system = _stage_prompt("continuity_extract")
        payload = f"集数：{episode}\n\n剧本：\n{script_text}\n\n连续性快照摘要：\n{context.get('continuity_state', {})}"
        text = call_generate(
            stage="continuity_extract",
            system_prompt=system,
            user_context=payload,
            output_contract="continuity-state.schema.json 兼容 JSON",
            model_config=model_config,
            temperature=0.2,
            max_tokens=2048,
        )
        import json

        data = json.loads(text)
        if isinstance(data, dict):
            data["extraction_mode"] = "model_assisted"
            return data
    except Exception:
        return None
    return None


def _delta_dir(project_dir: Path) -> Path:
    return project_dir / "state" / "continuity_deltas"


def _delta_pointer_path(project_dir: Path, episode: int, script_hash: str) -> Path:
    return _delta_dir(project_dir) / f"current_EP{episode:03d}_{script_hash[:8]}.json"


def save_continuity_delta(
    project_dir: Path,
    *,
    episode: int,
    delta: dict,
    script_hash: str,
    draft_version: str,
) -> Path:
    """Persist a host-agent/model continuity delta (idempotent by content)."""
    from .schema_validate import ensure_valid
    from .common import sha256_text

    ensure_valid(delta, "continuity-delta.schema.json")
    delta_content = dict(delta)
    delta_content["episode"] = episode
    delta_content["draft_version"] = draft_version
    delta_content["script_hash"] = script_hash
    from .common import canonical_json

    content_hash = sha256_text(canonical_json(delta_content) + "\n")
    path = _delta_dir(project_dir) / f"delta_EP{episode:03d}_{script_hash[:8]}_{content_hash[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    from .common import atomic_write_json

    current = _load_delta(project_dir, episode, script_hash)
    if current is not None and current.get("_content_hash") == content_hash:
        return path
    atomic_write_json(path, delta_content)
    atomic_write_json(
        _delta_pointer_path(project_dir, episode, script_hash),
        {
            "episode": episode,
            "approved_version": draft_version,
            "script_hash": script_hash,
            "delta_path": path.name,
            "delta_content_hash": content_hash,
            "updated_at": now_iso(),
        },
    )
    return path


def _load_delta(project_dir: Path, episode: int, script_hash: str) -> dict | None:
    from .common import read_json
    from .common import canonical_json

    pointer = read_json(_delta_pointer_path(project_dir, episode, script_hash))
    if not isinstance(pointer, dict):
        return None
    path = _delta_dir(project_dir) / (pointer.get("delta_path") or "")
    if not path.exists():
        return None
    try:
        data = read_json(path)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["_content_hash"] = sha256_text(canonical_json(data) + "\n")
    if data["_content_hash"] != pointer.get("delta_content_hash"):
        return None
    return data


def _delta_complete(delta: dict) -> bool:
    return bool(
        delta.get("facts")
        or delta.get("character_knowledge")
        or delta.get("open_hooks")
        or delta.get("resolved_hooks")
        or delta.get("future_overrides")
    )


def _normalize_fact(fact: dict, episode: int, script_hash: str, draft_version: str, idx: int) -> dict:
    return {
        "fact_id": fact.get("fact_id") or f"F-{episode:03d}-{idx:03d}",
        "category": fact.get("category", "event"),
        "fact": str(fact.get("fact", "")),
        "episode": episode,
        "draft_version": draft_version,
        "script_hash": script_hash,
        "evidence_location": str(fact.get("evidence_location", "") or ""),
        "status": fact.get("status", "active"),
        "recorded_at": now_iso(),
    }


def _merge_continuity(base: dict, extracted: dict, episode: int) -> dict:
    characters = list(dict.fromkeys(base.get("character_states", {}).keys()))
    for name in extracted.get("characters_seen", []) or []:
        entry = base.get("character_states", {}).get(name)
        if entry is None:
            base.setdefault("character_states", {})[name] = {"first_seen": episode, "episodes_seen": [episode]}
        else:
            seen = list(entry.get("episodes_seen", []))
            if episode not in seen:
                seen.append(episode)
            entry["episodes_seen"] = seen
    for location, count in (extracted.get("locations", {}) or {}).items():
        base.setdefault("locations", {})[location] = {"episodes_seen": [episode], "scenes": count}
    hook = extracted.get("ending_hook_candidate")
    if hook:
        hook_key = stable_hash({"episode": episode, "hook": hook})[:10]
        if not any(h.get("id") == hook_key for h in base.get("open_hooks", []) or []):
            base.setdefault("open_hooks", []).append(
                {"id": hook_key, "hook": hook, "introduced_in": episode, "status": "open", "candidate": True}
            )
    return base


def refresh_continuity(project_dir: Path, up_to_episode: int | None = None) -> dict:
    """Rebuild continuity from all approved scripts (idempotent)."""
    continuity = _fresh_continuity()
    approved = []
    per_episode_extraction: dict[str, dict] = {}
    if up_to_episode is None:
        up_to_episode = 10_000
    for episode in range(1, up_to_episode + 1):
        path = active_artifact_path(project_dir, "approved_script", episode)
        if not path or not path.exists():
            continue
        approved.append(episode)
        script_text = path.read_text(encoding="utf-8")
        draft_version = active_version_id(project_dir, "approved_script", episode) or ""
        record = artifact_version_record(project_dir, "approved_script", episode, draft_version) or {}
        script_hash = record.get("content_hash") or sha256_text(script_text)
        deterministic = extract_deterministic(episode, script_text)
        delta = _load_delta(project_dir, episode, script_hash)
        if delta is None:
            model_result = extract_model_assisted(project_dir, episode, script_text)
            if model_result:
                try:
                    save_continuity_delta(
                        project_dir,
                        episode=episode,
                        delta=model_result,
                        script_hash=script_hash,
                        draft_version=draft_version,
                    )
                    delta = _load_delta(project_dir, episode, script_hash)
                except Exception:
                    delta = None
        if delta is not None:
            mode = delta.get("extraction_mode", "host_agent")
            complete = _delta_complete(delta)
            continuity = _merge_delta(continuity, delta, episode, script_hash, draft_version)
        else:
            mode = "deterministic"
            complete = False
            continuity = _merge_continuity(continuity, deterministic, episode)
        if mode not in ("deterministic", "host_agent", "model_assisted"):
            mode = "deterministic"
        per_episode_extraction[str(episode)] = {
            "mode": mode,
            "complete": complete,
            "script_hash": script_hash,
            "draft_version": draft_version,
        }

    continuity["approved_episodes"] = sorted(approved)
    continuity["updated_from_episode"] = max(approved) if approved else None
    continuity["version"] = (load_continuity(project_dir).get("version", 0) or 0) + 1
    continuity["episode_extraction"] = per_episode_extraction
    degraded = [
        ep
        for ep, info in per_episode_extraction.items()
        if info["mode"] == "deterministic" or not info["complete"]
    ]
    continuity["degraded_episodes"] = degraded
    modes = {info["mode"] for info in per_episode_extraction.values()}
    if not modes:
        continuity["extraction_mode"] = "deterministic"
    elif modes == {"deterministic"}:
        continuity["extraction_mode"] = "deterministic"
    elif modes == {"host_agent"}:
        continuity["extraction_mode"] = "host_agent"
    elif modes == {"model_assisted"}:
        continuity["extraction_mode"] = "model_assisted"
    else:
        continuity["extraction_mode"] = "mixed"
    continuity["writer_overrides"] = [
        {"revision_id": r.get("revision_id"), "instruction": r.get("instruction"), "episode": r.get("episode"), "status": r.get("status")}
        for r in writer_overrides(project_dir)
    ]
    continuity["updated_at"] = now_iso()
    if not continuity.get("episode_extraction"):
        continuity["episode_extraction"] = {}
    if not continuity.get("degraded_episodes"):
        continuity["degraded_episodes"] = []
    ensure_valid(continuity, "continuity-state.schema.json")
    save_continuity(project_dir, continuity)
    return continuity


def _merge_delta(
    continuity: dict,
    delta: dict,
    episode: int,
    script_hash: str,
    draft_version: str,
) -> dict:
    continuity = _merge_continuity(continuity, delta, episode)
    for idx, fact in enumerate(delta.get("facts", []) or [], start=1):
        normalized = _normalize_fact(fact, episode, script_hash, draft_version, idx)
        existing_ids = {f.get("fact_id") for f in continuity.get("facts", [])}
        existing_texts = {f.get("fact") for f in continuity.get("facts", [])}
        if normalized["fact_id"] not in existing_ids and normalized["fact"] not in existing_texts:
            continuity.setdefault("facts", []).append(normalized)
    for name, knowledge in (delta.get("character_knowledge", {}) or {}).items():
        known = continuity.setdefault("character_knowledge", {}).setdefault(name, [])
        for item in knowledge:
            if item not in known:
                known.append(item)
    for hook in delta.get("open_hooks", []) or []:
        if not any(h.get("hook") == hook.get("hook") for h in continuity.setdefault("open_hooks", [])):
            continuity["open_hooks"].append({**hook, "introduced_in": episode, "status": "open"})
    for hook in delta.get("resolved_hooks", []) or []:
        continuity.setdefault("resolved_hooks", []).append({**hook, "resolved_in": episode})
        continuity["open_hooks"] = [
            h
            for h in continuity.get("open_hooks", [])
            if h.get("hook") != hook.get("hook") and h.get("id") != hook.get("id")
        ]
    for override in delta.get("future_overrides", []) or []:
        continuity.setdefault("notes_for_future", []).append(
            f"EP{episode}: {override.get('instruction', '')}"
        )
    return continuity


def apply_approved_script(project_dir: Path, episode: int, script_text: str, source: str = "writer") -> Path:
    """Register an approved script and refresh continuity from all approvals."""
    from .script_validator import validate_script
    from .common import sha256_text
    from .format_renderer import business_format

    config = load_config(project_dir)
    if "<scriptItem" in script_text:
        script_text = business_format(script_text, "legacy-scriptitem")
    report = validate_script(script_text, format_profile="default-cn", expected_episode=episode)
    if not report["ok"]:
        raise ValueError("定稿格式未通过：" + report["errors"][0]["message"])
    script_hash = sha256_text(script_text)
    result = commit_artifact(
        project_dir,
        "approved_script",
        content=script_text,
        episode=episode,
        source=source,
        status="approved",
        ext="txt",
        meta={"script_hash": script_hash},
    )
    refresh_continuity(project_dir)
    return result["path"]
