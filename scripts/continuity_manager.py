"""Continuity management from approved scripts (spec §18, §22.2).

Deterministic extraction is always run. Model-assisted extraction is used
only when an API is configured; without one, extraction_mode is
"deterministic" and the runtime says so instead of pretending otherwise.
Continuity can always be rebuilt from all approved scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import now_iso, read_json, stable_hash
from .schema_validate import ensure_valid
from .script_validator import parse_script
from .state_store import (
    active_artifact_path,
    append_writer_override,
    load_continuity,
    load_config,
    save_continuity,
    writer_overrides,
)


DEFAULT_CONTINUITY = {
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
    continuity = DEFAULT_CONTINUITY.copy()
    approved = []
    if up_to_episode is None:
        up_to_episode = 10_000
    for episode in range(1, up_to_episode + 1):
        path = active_artifact_path(project_dir, "approved_script", episode)
        if not path or not path.exists():
            continue
        approved.append(episode)
        script_text = path.read_text(encoding="utf-8")
        deterministic = extract_deterministic(episode, script_text)
        model_result = extract_model_assisted(project_dir, episode, script_text)
        continuity = _merge_continuity(continuity, model_result or deterministic, episode)
        if model_result:
            for fact in model_result.get("facts", []) or []:
                if fact not in continuity.setdefault("facts", []):
                    continuity["facts"].append(fact)
            for name, knowledge in (model_result.get("character_knowledge", {}) or {}).items():
                known = continuity.setdefault("character_knowledge", {}).setdefault(name, [])
                for item in knowledge:
                    if item not in known:
                        known.append(item)
            for hook in model_result.get("open_hooks", []) or []:
                if not any(h.get("hook") == hook.get("hook") for h in continuity.setdefault("open_hooks", [])):
                    continuity["open_hooks"].append({**hook, "introduced_in": episode, "status": "open"})
            for hook in model_result.get("resolved_hooks", []) or []:
                continuity.setdefault("resolved_hooks", []).append({**hook, "resolved_in": episode})
                continuity["open_hooks"] = [
                    h for h in continuity.get("open_hooks", [])
                    if h.get("hook") != hook.get("hook") and h.get("id") != hook.get("id")
                ]
        continuity["extraction_mode"] = "model_assisted" if model_result else "deterministic"

    continuity["approved_episodes"] = sorted(approved)
    continuity["updated_from_episode"] = max(approved) if approved else None
    continuity["version"] = (load_continuity(project_dir).get("version", 0) or 0) + 1
    continuity["writer_overrides"] = [
        {"revision_id": r.get("revision_id"), "instruction": r.get("instruction"), "episode": r.get("episode"), "status": r.get("status")}
        for r in writer_overrides(project_dir)
    ]
    continuity["updated_at"] = now_iso()
    ensure_valid(continuity, "continuity-state.schema.json")
    save_continuity(project_dir, continuity)
    return continuity


def apply_approved_script(project_dir: Path, episode: int, script_text: str, source: str = "writer") -> Path:
    """Register an approved script and refresh continuity from all approvals."""
    from .script_validator import validate_script
    from .state_store import record_artifact

    config = load_config(project_dir)
    format_profile = config.get("script_format", "default-cn")
    report = validate_script(script_text, format_profile=format_profile, expected_episode=episode)
    if not report["ok"]:
        raise ValueError("定稿格式未通过：" + report["errors"][0]["message"])
    path = project_dir / "artifacts" / "approved_scripts" / f"ep{episode:03d}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script_text, encoding="utf-8")
    record_artifact(project_dir, "approved_script", path, episode=episode, source=source, status="approved")
    refresh_continuity(project_dir)
    return path
