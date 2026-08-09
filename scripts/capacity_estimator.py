"""Advisory content capacity estimation (spec §15).

The forecast answers "how much runtime does this adaptation need" with
ranges, assumptions and confidence. It is never a production gate.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .common import atomic_write_json, ensure_dir, now_iso
from .schema_validate import ensure_valid
from .state_store import active_artifact_path, commit_artifact, load_config


IMPORTANCE_DEFAULTS = {
    "mainline": {"minimum": 20, "preferred": 35},
    "subline": {"minimum": 12, "preferred": 22},
    "transition": {"minimum": 6, "preferred": 12},
}


def event_seconds(event: dict) -> tuple[int, int]:
    """Return (minimum, preferred) seconds for one event with fallbacks."""
    importance = event.get("importance", "mainline")
    defaults = IMPORTANCE_DEFAULTS.get(importance, IMPORTANCE_DEFAULTS["mainline"])
    minimum = event.get("minimum_screen_seconds")
    preferred = event.get("preferred_screen_seconds")
    minimum = minimum if isinstance(minimum, int) and minimum >= 0 else defaults["minimum"]
    preferred = preferred if isinstance(preferred, int) and preferred >= 0 else defaults["preferred"]
    if preferred < minimum:
        preferred = minimum
    return minimum, preferred


def compute_forecast(config: dict, events: list[dict]) -> dict:
    """Compute the capacity forecast from config and event assets."""
    events = [e for e in events if isinstance(e, dict)]
    mainline_min = 0
    full_min = 0
    full_pref = 0
    missing_preferred = 0
    for event in events:
        minimum, preferred = event_seconds(event)
        if event.get("importance") == "mainline":
            mainline_min += minimum
        full_min += minimum
        full_pref += preferred
        if not isinstance(event.get("preferred_screen_seconds"), int):
            missing_preferred += 1

    episodes = config.get("initial_episode_count")
    minimum_episode = config.get("minimum_episode_seconds", 0) or 0
    minimum_total = config.get("minimum_total_seconds") or 0
    preferred_episode = config.get("preferred_episode_seconds") or []
    preferred_low = preferred_episode[0] if len(preferred_episode) == 2 else None
    preferred_high = preferred_episode[1] if len(preferred_episode) == 2 else None
    requested_minimum_total = max((episodes or 0) * minimum_episode, minimum_total)
    requested_preferred_total = (
        [(episodes or 0) * preferred_low, (episodes or 0) * preferred_high]
        if episodes and preferred_low is not None and preferred_high is not None
        else None
    )
    # Preferred upper bound is the useful comparison when supplied.  If the
    # writer gave only a minimum, the minimum is merely a baseline: the report
    # explicitly says longer episodes remain available.
    comparison_capacity = (
        requested_preferred_total[1]
        if requested_preferred_total
        else requested_minimum_total
    )

    pressure_value = (mainline_min / comparison_capacity) if comparison_capacity else 99
    if pressure_value > 1.2:
        pressure = "high"
    elif pressure_value > 0.9:
        pressure = "medium"
    else:
        pressure = "low"

    if events and missing_preferred / len(events) > 0.3:
        confidence = "low"
    elif len(events) >= 30:
        confidence = "high"
    else:
        confidence = "medium"

    requested_episodes = episodes or 30
    mainline_average = math.ceil(mainline_min / requested_episodes) if requested_episodes else mainline_min
    full_average = math.ceil(full_pref / requested_episodes) if requested_episodes else full_pref
    if preferred_low and preferred_high:
        full_episode_range = [
            max(1, math.ceil(full_min / preferred_high)),
            max(1, math.ceil(full_pref / preferred_low)),
        ]
        mainline_episode_range = [
            max(1, math.ceil(mainline_min / preferred_high)),
            max(1, math.ceil(mainline_min / preferred_low)),
        ]
    else:
        full_episode_range = None
        mainline_episode_range = None

    options = [
        f"维持 {requested_episodes} 集：主线最低平均约 {mainline_average} 秒/集，完整内容理想平均约 {full_average} 秒/集",
        "维持单集偏好区间：优先保留主线与依赖链，明确删除/合并支线事件",
    ]
    if full_episode_range:
        options.append(
            f"偏完整改编：按当前事件时长约需 {full_episode_range[0]}–{full_episode_range[1]} 集"
        )
    else:
        options.append("增加单集时长或集数：当前只给了时长下限，需由编剧选择可接受上限后再算集数")
    if not config.get("reach_original_ending"):
        options.append("阶段性覆盖：由编剧选择本季截止章节或剧情节点，不强行抵达原著结局")
    recommended = options[0] if pressure == "low" else options[1]

    assumptions = [
        "事件时长来自 source_events 的 minimum/preferred_screen_seconds，缺失时按主线/支线/过渡默认值估算",
        "只保留主线时按主线事件 minimum 之和估算",
        "完整改编按全部事件 preferred 之和估算",
        "所有数值为区间与预期，编剧可接受或忽略",
        "集纲和剧本批次完成后应重新估算",
    ]
    if minimum_total:
        assumptions.append(f"编剧声明总时长下限 {minimum_total} 秒，仅作参考")

    forecast = {
        "requested": {
            "episodes": episodes,
            "minimum_episode_seconds": minimum_episode,
            "minimum_total_seconds": minimum_total,
            "preferred_episode_seconds": preferred_episode or None,
            "minimum_total_capacity_seconds": requested_minimum_total,
            "preferred_total_capacity_seconds": requested_preferred_total,
            "episode_timing_overrides": config.get("episode_timing_overrides", []),
            "planning_checkpoints": config.get("planning_checkpoints", []),
        },
        "forecast": {
            "mainline_minimum_seconds": [round(mainline_min * 0.9), round(mainline_min * 1.1)],
            "full_adaptation_seconds": [round(full_pref * 0.85), round(full_pref * 1.15)],
            "confidence": confidence,
            "assumptions": assumptions,
        },
        "pressure": pressure,
        "scenario_metrics": {
            "comparison_capacity_seconds": comparison_capacity,
            "pressure_ratio": round(pressure_value, 3),
            "requested_episode_mainline_average_seconds": mainline_average,
            "requested_episode_full_average_seconds": full_average,
            "mainline_episode_range_at_preferred_length": mainline_episode_range,
            "full_episode_range_at_preferred_length": full_episode_range,
            "requires_writer_choice": pressure != "low" or not preferred_episode,
        },
        "options": options,
        "recommended": recommended,
        "advisory_only": True,
        "computed_at": now_iso(),
    }
    ensure_valid(forecast, "capacity-forecast.schema.json")
    return forecast


def save_forecast(project_dir: Path, forecast: dict | None = None, *, source: str = "cli") -> dict:
    """Compute and persist the forecast as an artifact (idempotent by content)."""
    config = load_config(project_dir)
    events = _load_events(project_dir)
    forecast = forecast or compute_forecast(config, events)
    result = commit_artifact(
        project_dir,
        "capacity_forecast",
        content=forecast,
        source=source,
        status="approved",
        ext="json",
        note="advisory only",
    )
    md_result = commit_artifact(
        project_dir,
        "capacity_forecast_md",
        content=render_forecast_markdown(forecast),
        source=source,
        status="approved",
        ext="md",
    )
    if md_result["created"]:
        print(f"容量预估 Markdown：{md_result['path']}")
    return forecast


def _load_events(project_dir: Path) -> list[dict]:
    from .common import read_json

    path = active_artifact_path(project_dir, "source_events")
    if not path or not path.exists():
        return []
    data = read_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "events" in data:
        return data["events"]
    return []


def render_forecast_markdown(forecast: dict) -> str:
    requested = forecast.get("requested", {})
    fc = forecast.get("forecast", {})
    lines = [
        "# 内容容量预估（仅参考，不阻断）",
        "",
        f"- 初始集数：{requested.get('episodes')}",
        f"- 单集最低时长：{requested.get('minimum_episode_seconds')} 秒",
        f"- 总时长下限：{requested.get('minimum_total_seconds')} 秒",
        "",
        f"- 主线最低预估：{fc.get('mainline_minimum_seconds')} 秒",
        f"- 完整改编预估：{fc.get('full_adaptation_seconds')} 秒",
        f"- 置信度：{fc.get('confidence')}",
        f"- 容量压力：{forecast.get('pressure')}",
        "",
        "可选方案：",
        *[f"- {o}" for o in forecast.get("options", [])],
        "",
        f"推荐：{forecast.get('recommended')}",
        "",
        "假设：",
        *[f"- {a}" for a in fc.get("assumptions", [])],
        "",
        "编剧可以接受或忽略以上任何推荐；超出预期时仅提示，不自动回退。",
        "具体事件如何分配到每集由改编指引/故事设计阶段按原文顺序、依赖和编剧选择完成，估算器不机械平均切章。",
    ]
    return "\n".join(lines) + "\n"
