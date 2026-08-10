"""Advisory duration estimation (spec §20).

Metrics are kept separate: dialogue chars, action/description chars, total
chars, and estimated on-screen seconds. Estimates are advisory only and can
never block production.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .script_validator import parse_script


DEFAULT_DIALOGUE_CPM = 150
DEFAULT_ACTION_SECONDS = 2.5
DEFAULT_REACTION_SECONDS = 0.8
DEFAULT_TRANSITION_SECONDS = 1.2
DEFAULT_DEVIATION_TOLERANCE_SECONDS = 10.0


def _dialogue_chars(parsed: dict) -> int:
    return sum(len(d["text"]) for scene in parsed.get("scenes", []) for d in scene.get("dialogues", []))


def _action_chars(parsed: dict) -> int:
    return sum(len(a["text"]) for scene in parsed.get("scenes", []) for a in scene.get("actions", []))


def _reaction_count(parsed: dict) -> int:
    count = 0
    for scene in parsed.get("scenes", []):
        for d in scene.get("dialogues", []):
            if d.get("delivery") in ("OS", "VO", "自言自语", "低声", "内心"):
                count += 1
    return count


def estimate_episode_seconds(
    content: str,
    *,
    dialogue_chars_per_minute: int | None = None,
    action_seconds: float = DEFAULT_ACTION_SECONDS,
    reaction_seconds: float = DEFAULT_REACTION_SECONDS,
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS,
) -> dict:
    """Estimate on-screen seconds per beat. Returns range, never blocks."""
    parsed = parse_script(content)
    cpm = dialogue_chars_per_minute or DEFAULT_DIALOGUE_CPM
    dialogue = _dialogue_chars(parsed)
    action_lines = sum(len(s.get("actions", [])) for s in parsed.get("scenes", []))
    reactions = _reaction_count(parsed)
    scenes = len(parsed.get("scenes", []))
    transitions = max(0, scenes - 1)
    base = (dialogue / cpm * 60) + action_lines * action_seconds + reactions * reaction_seconds + transitions * transition_seconds
    return {
        "dialogue_chars": dialogue,
        "action_chars": _action_chars(parsed),
        "action_lines": action_lines,
        "reaction_count": reactions,
        "scene_count": scenes,
        "estimated_seconds": round(base, 1),
        "estimated_range": [round(base * 0.9, 1), round(base * 1.15, 1)],
        "blocking": False,
    }


def _deviation(
    estimated_seconds: float,
    preferred_seconds: list | None,
    *,
    tolerance_seconds: float = DEFAULT_DEVIATION_TOLERANCE_SECONDS,
) -> str:
    """Deviation with a symmetric tolerance band.

    A few seconds of drift is inside estimator noise and must not trigger a
    rewrite suggestion (e.g. 152s against a 90-150s target is acceptable).
    """
    if isinstance(preferred_seconds, list) and len(preferred_seconds) == 2:
        low, high = preferred_seconds
        if estimated_seconds < low - tolerance_seconds:
            return "below"
        if estimated_seconds > high + tolerance_seconds:
            return "above"
        return "within"
    return "unknown"


def _compute_dialogue_budget(preferred_seconds: list | None) -> dict | None:
    """Dialogue char budget for a target duration window (150 cpm).

    Only dialogue chars drive spoken time, so this is the budget a writer must
    trim against. Action/description wording never enters the estimate.
    """
    if not isinstance(preferred_seconds, list) or len(preferred_seconds) != 2:
        return None
    low, high = preferred_seconds
    return {
        "min_chars": round(low / 60 * DEFAULT_DIALOGUE_CPM),
        "max_chars": round(high / 60 * DEFAULT_DIALOGUE_CPM),
        "basis": f"{DEFAULT_DIALOGUE_CPM} cpm",
    }


def compute_draft_metrics(
    content: str,
    *,
    episode: int,
    context_hash: str,
    draft_version: str,
    draft_hash: str,
    preferred_seconds: list | None = None,
    estimator_version: str = "v2",
) -> dict:
    """Deterministic per-draft metrics bound to context/draft version+hash."""
    estimate = estimate_episode_seconds(content)
    preferred_seconds = preferred_seconds if isinstance(preferred_seconds, list) else None
    return {
        "episode": episode,
        "context_hash": context_hash,
        "draft_version": draft_version,
        "draft_hash": draft_hash,
        "estimator_version": estimator_version,
        "dialogue_chars": estimate["dialogue_chars"],
        "action_chars": estimate["action_chars"],
        "action_lines": estimate["action_lines"],
        "reaction_count": estimate["reaction_count"],
        "scene_count": estimate["scene_count"],
        "estimated_seconds": estimate["estimated_seconds"],
        "estimated_range": estimate["estimated_range"],
        "preferred_seconds": preferred_seconds,
        "deviation": _deviation(estimate["estimated_seconds"], preferred_seconds),
        "blocking": False,
        "source": "system",
        "advisory_only": True,
        "dialogue_budget_chars": _compute_dialogue_budget(preferred_seconds),
        "tolerance_seconds": DEFAULT_DEVIATION_TOLERANCE_SECONDS,
        "duration_drivers": "台词字数、动作行数、反应次数、转场次数；动作/描写字数不计入时长",
        "measurement_basis": "台词朗读时间+动作行执行时间+反应停顿+转场；仅供编剧预期",
    }


def load_bound_draft_metrics(
    project_dir: Path,
    episode: int,
    draft_version: str,
    draft_hash: str,
) -> dict:
    """Return the deterministic metrics bound to one exact draft version."""
    from .state_store import artifact_versions, read_artifact_version

    for record in artifact_versions(project_dir, "draft_metrics", episode):
        data = read_artifact_version(project_dir, "draft_metrics", episode, record["version"])
        if (
            isinstance(data, dict)
            and data.get("draft_version") == draft_version
            and data.get("draft_hash") == draft_hash
        ):
            return data
    raise KeyError(f"第{episode}集草稿 {draft_version}/{draft_hash[:12]} 没有绑定 draft_metrics")


def forecast_duration(
    config: dict,
    scripts: list[tuple[int, str]],
    *,
    dialogue_chars_per_minute: int | None = None,
) -> dict:
    """Forecast per-episode and total duration; advisory only."""
    preferred = config.get("preferred_episode_seconds") or config.get("advisory_timing", {}).get("preferred_seconds")
    minimum = config.get("minimum_episode_seconds", 0)
    episodes = []
    total = 0.0
    for episode, content in scripts:
        estimate = estimate_episode_seconds(content, dialogue_chars_per_minute=dialogue_chars_per_minute)
        total += estimate["estimated_seconds"]
        below_minimum = bool(minimum) and estimate["estimated_seconds"] < minimum
        episodes.append(
            {
                "episode": episode,
                **estimate,
                "preferred_seconds": preferred,
                "below_minimum": below_minimum,
                "blocking": False,
            }
        )
    return {
        "per_episode": episodes,
        "total_estimated_seconds": round(total, 1),
        "total_range": [round(total * 0.9, 1), round(total * 1.15, 1)],
        "dialogue_chars_per_minute": dialogue_chars_per_minute or DEFAULT_DIALOGUE_CPM,
        "script_total_chars_per_minute_hint": config.get("advisory_timing", {}).get("script_total_chars_per_minute_hint"),
        "advisory_only": True,
    }


def render_duration_report(forecast: dict) -> str:
    lines = ["# 时长预估（仅提示，不阻断）", ""]
    for ep in forecast["per_episode"]:
        flags = []
        if ep["below_minimum"]:
            flags.append(f"低于平台下限 {ep['preferred_seconds'] and '（无单集下限配置时仅参考）' or ''}")
        lines.append(
            f"- 第{ep['episode']}集：约 {ep['estimated_seconds']} 秒 "
            f"（台词 {ep['dialogue_chars']} 字，动作 {ep['action_lines']} 行，建议 {ep['preferred_seconds'] or '未定'}）"
            + (" ⚠ " + "；".join(flags) if flags else "")
        )
    lines.append("")
    lines.append(f"全剧合计：约 {forecast['total_estimated_seconds']} 秒（{forecast['total_estimated_seconds'] / 60:.1f} 分钟）")
    lines.append("口径：台词朗读时间 + 动作执行时间 + 反应停顿 + 转场；仅提供预期，编剧可接受任何偏差。")
    return "\n".join(lines) + "\n"
