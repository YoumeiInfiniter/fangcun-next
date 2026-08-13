"""Versioned, writer-confirmed capacity decisions for v0.3.7.

``capacity_forecast`` remains an estimate.  A ``capacity_plan`` is the
explicit, executable choice that tells the runtime what to preserve, defer,
compress, or leave outside the current adaptation.  It is deliberately
separate from the historical ``capacity_decisions.jsonl`` records so an old
acceptance cannot masquerade as a new plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import canonical_json, now_iso, stable_hash
from .schema_validate import ensure_valid
from .state_store import (
    active_artifact_path,
    active_version_id,
    artifact_versions,
    commit_artifact,
    read_artifact_version,
    resolve_active,
)


PLAN_SCHEMA_VERSION = "0.3.7"
PRIORITY_MODES = {"quality_first", "fixed_episode_count", "fixed_episode_duration"}
COVERAGE_MODES = {"mainline", "balanced", "full"}
PRESENTATION_ACTIONS = {"full", "compress", "defer", "accept_overflow", "omit"}


def _active_data(project_dir: Path, kind: str) -> tuple[Any, str | None, str | None]:
    resolved = resolve_active(project_dir, kind)
    if not resolved:
        return None, None, None
    return (
        read_artifact_version(project_dir, kind, None, resolved["version"]),
        resolved["version"],
        resolved["record"].get("content_hash"),
    )


def _events(project_dir: Path) -> list[dict]:
    data, _, _ = _active_data(project_dir, "source_events")
    if isinstance(data, dict):
        data = data.get("events", [])
    return [item for item in (data or []) if isinstance(item, dict) and item.get("event_id")]


def _outline_binding(project_dir: Path) -> dict:
    resolved = resolve_active(project_dir, "episode_outline")
    if not resolved:
        return {"version": None, "hash": None}
    return {
        "version": resolved["version"],
        "hash": resolved["record"].get("content_hash"),
    }


def _forecast_binding(project_dir: Path) -> tuple[dict | None, str | None, str | None]:
    data, version, content_hash = _active_data(project_dir, "capacity_forecast")
    return (data if isinstance(data, dict) else None, version, content_hash)


def _ordered_events(events: list[dict], coverage_mode: str) -> list[dict]:
    """Keep source/dependency order while applying only a coverage filter."""
    if coverage_mode == "mainline":
        selected = [e for e in events if e.get("importance", "mainline") == "mainline"]
        return selected or list(events)
    if coverage_mode == "balanced":
        return list(events)
    return list(events)


def _event_seconds(event: dict) -> int:
    value = event.get("preferred_screen_seconds")
    if not isinstance(value, int) or value < 0:
        value = event.get("minimum_screen_seconds")
    return value if isinstance(value, int) and value >= 0 else 20


def _partition_events(
    events: list[dict],
    *,
    episode_count: int,
    seconds_window: list[int] | None,
    overflow_action: str,
) -> tuple[dict[str, list[str]], list[str], list[str], list[str]]:
    """Partition in source order with explicit overflow/defer bookkeeping.

    This is a routing aid, not an automatic story cut.  Dependencies are not
    rewritten and the plan records every event not assigned to a full slot so
    the writer can review the choice.
    """
    episode_count = max(1, int(episode_count))
    low, high = (seconds_window or [0, 0])[:2]
    high = int(high or 0)
    partitions = {f"EP{i:03d}": [] for i in range(1, episode_count + 1)}
    compressible: list[str] = []
    deferred: list[str] = []
    omitted: list[str] = []
    current = 1
    used = 0
    for event in events:
        event_id = str(event["event_id"])
        duration = _event_seconds(event)
        if current <= episode_count and (not high or used == 0 or used + duration <= high):
            partitions[f"EP{current:03d}"].append(event_id)
            used += duration
            continue
        if current < episode_count:
            current += 1
            used = 0
            partitions[f"EP{current:03d}"].append(event_id)
            used = duration
            continue
        if overflow_action == "compress":
            compressible.append(event_id)
        elif overflow_action == "defer":
            deferred.append(event_id)
        elif overflow_action == "omit":
            omitted.append(event_id)
        else:
            partitions[f"EP{episode_count:03d}"].append(event_id)
    return partitions, compressible, deferred, omitted


def _base_option(
    *,
    option_id: str,
    title: str,
    priority_mode: str,
    coverage_mode: str,
    episode_count: int,
    episode_seconds: list[int] | None,
    events: list[dict],
    overflow_action: str,
    rationale: str,
) -> dict:
    selected = _ordered_events(events, coverage_mode)
    partitions, compressible, deferred, omitted = _partition_events(
        selected,
        episode_count=episode_count,
        seconds_window=episode_seconds,
        overflow_action=overflow_action,
    )
    selected_ids = {str(e["event_id"]) for e in selected}
    all_ids = {str(e["event_id"]) for e in events}
    if coverage_mode == "mainline":
        if overflow_action == "omit":
            omitted.extend(sorted(all_ids - selected_ids))
        else:
            deferred.extend(sorted(all_ids - selected_ids))
    return {
        "plan_id": f"CP-{option_id}",
        "plan_version": "proposed",
        "option_id": option_id,
        "title": title,
        "priority_mode": priority_mode,
        "coverage_mode": coverage_mode,
        "episode_count": int(episode_count),
        "episode_seconds": episode_seconds,
        "selected_episode_count": int(episode_count),
        "selected_episode_seconds": episode_seconds,
        "coverage_policy": coverage_mode,
        "event_partition": partitions,
        "kept_event_ids": [event_id for values in partitions.values() for event_id in values],
        "compressible_event_ids": list(dict.fromkeys(compressible)),
        "compressed_event_ids": list(dict.fromkeys(compressible)),
        "deferred_event_ids": list(dict.fromkeys(deferred)),
        "omitted_event_ids": list(dict.fromkeys(omitted)),
        "accepted_overflow_episodes": list(range(1, int(episode_count) + 1))
        if overflow_action == "accept_overflow"
        else [],
        "overflow_action": overflow_action,
        "rationale": rationale,
        "writer_confirmation_ref": "pending",
    }


def suggest_capacity_plans(
    project_dir: Path,
    *,
    forecast: dict | None = None,
    minimum_options: int = 3,
) -> dict:
    """Return executable plan options bound to the current forecast.

    The returned object is a proposal package.  It is not an approved plan
    until a writer saves one option with an explicit confirmation reference.
    """
    forecast = forecast or _forecast_binding(project_dir)[0]
    forecast = forecast or {}
    requested = forecast.get("requested", {}) or {}
    config_episodes = requested.get("episodes") or 1
    preferred = requested.get("preferred_episode_seconds")
    if not isinstance(preferred, list) or len(preferred) != 2:
        minimum = requested.get("minimum_episode_seconds") or 60
        preferred = [int(minimum), int(minimum)]
    events = _events(project_dir)
    mainline_range = (forecast.get("scenario_metrics", {}) or {}).get(
        "mainline_episode_range_at_preferred_length"
    )
    full_range = (forecast.get("scenario_metrics", {}) or {}).get(
        "full_episode_range_at_preferred_length"
    )
    quality_count = int((mainline_range or [config_episodes, config_episodes])[0] or config_episodes)
    full_count = int((full_range or [config_episodes, config_episodes])[1] or config_episodes)
    options = [
        _base_option(
            option_id="quality_first_mainline",
            title="质量优先保主线",
            priority_mode="quality_first",
            coverage_mode="mainline",
            episode_count=max(config_episodes, quality_count),
            episode_seconds=preferred,
            events=events,
            overflow_action="defer",
            rationale="优先保留主线因果与关键依赖；非主线事件显式延期，不由系统静默删除。",
        ),
        _base_option(
            option_id="fixed_count_explicit_overflow",
            title="维持既定集数并记录压缩/溢出",
            priority_mode="fixed_episode_count",
            coverage_mode="balanced",
            episode_count=int(config_episodes),
            episode_seconds=preferred,
            events=events,
            overflow_action="compress",
            rationale="维持项目集数；超出容量的事件进入 compressible 清单，编剧仍需决定是否压缩。",
        ),
        _base_option(
            option_id="explicit_mainline_reduction",
            title="固定集数并明确删减非主线",
            priority_mode="fixed_episode_count",
            coverage_mode="mainline",
            episode_count=int(config_episodes),
            episode_seconds=preferred,
            events=events,
            overflow_action="omit",
            rationale="维持既定集数并明确省略非主线事件；删减清单绑定到计划，不能静默丢失。",
        ),
        _base_option(
            option_id="full_coverage_deferred",
            title="尽量覆盖完整内容",
            priority_mode="fixed_episode_duration",
            coverage_mode="full",
            episode_count=max(config_episodes, full_count),
            episode_seconds=preferred,
            events=events,
            overflow_action="defer",
            rationale="保持单集时长预期并增加集数；不能在当前批次容纳的内容显式延期。",
        ),
        _base_option(
            option_id="accept_duration_overflow",
            title="接受时长溢出并由编剧标注",
            priority_mode="fixed_episode_duration",
            coverage_mode="full",
            episode_count=int(config_episodes),
            episode_seconds=preferred,
            events=events,
            overflow_action="accept_overflow",
            rationale="维持既定集数并接受容量溢出；超出时长由编剧逐集确认，不由系统静默截断。",
        ),
    ]
    while len(options) < max(3, minimum_options):
        options.append(
            _base_option(
                option_id=f"writer_variant_{len(options) + 1}",
                title="编剧自定义取舍",
                priority_mode="quality_first",
                coverage_mode="balanced",
                episode_count=int(config_episodes),
                episode_seconds=preferred,
                events=events,
                overflow_action="accept_overflow",
                rationale="由编剧自行填写事件分配和取舍；系统只校验绑定与可追溯性。",
            )
        )
    _, forecast_version, forecast_hash = _forecast_binding(project_dir)
    outline_binding = _outline_binding(project_dir)
    return {
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "forecast_version": forecast_version,
        "forecast_hash": forecast_hash,
        "outline_version": outline_binding["version"],
        "outline_hash": outline_binding["hash"],
        "options": options,
        "generated_at": now_iso(),
        "advisory_only": True,
    }


generate_capacity_plan_options = suggest_capacity_plans


def _normalize_event_partition(plan: dict) -> set[str]:
    partition = plan.get("event_partition") or {}
    ids: set[str] = set()
    if isinstance(partition, dict):
        for values in partition.values():
            if isinstance(values, list):
                ids.update(str(value) for value in values)
    return ids


def validate_capacity_plan(
    plan: dict,
    project_dir: Path | None = None,
    *,
    require_approved: bool = False,
) -> list[str]:
    """Return deterministic plan errors; no model judgement is involved."""
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["capacity_plan 必须是 JSON 对象"]
    try:
        ensure_valid(plan, "capacity-plan.schema.json")
    except Exception as exc:  # schema validator exposes useful Chinese errors
        errors.append(str(exc))
    if plan.get("priority_mode") not in PRIORITY_MODES:
        errors.append("priority_mode 不属于允许的容量取舍模式")
    if plan.get("coverage_mode") not in COVERAGE_MODES:
        errors.append("coverage_mode 不属于允许的内容覆盖模式")
    if require_approved and plan.get("status") != "approved":
        errors.append("capacity_plan 尚未由编剧确认")
    known_ids: set[str] = set()
    if project_dir is not None:
        events = _events(project_dir)
        known_ids = {str(item["event_id"]) for item in events}
        forecast, forecast_version, forecast_hash = _forecast_binding(project_dir)
        if forecast_hash and plan.get("forecast_hash") != forecast_hash:
            errors.append("capacity_plan 的 forecast_hash 与当前容量预估不一致")
        if forecast_version and plan.get("forecast_version") != forecast_version:
            errors.append("capacity_plan 的 forecast_version 与当前容量预估不一致")
        outline = _outline_binding(project_dir)
        if plan.get("outline_hash") and outline["hash"] and plan.get("outline_hash") != outline["hash"]:
            errors.append("capacity_plan 的 outline_hash 与当前集纲不一致")
    assigned = _normalize_event_partition(plan)
    listed = set(str(x) for key in ("compressible_event_ids", "deferred_event_ids", "omitted_event_ids") for x in (plan.get(key) or []))
    if assigned & listed:
        errors.append("同一事件不能同时出现在 event_partition 与压缩/延期/省略清单")
    if known_ids:
        unknown = sorted((assigned | listed) - known_ids)
        if unknown:
            errors.append("capacity_plan 引用了不存在的事件：" + ", ".join(unknown[:10]))
    return list(dict.fromkeys(errors))


def save_capacity_plan(
    project_dir: Path,
    plan: dict,
    *,
    source: str = "writer",
    operator: str = "writer",
    confirmation_ref: str = "",
) -> dict:
    """Save a writer-confirmed plan as an immutable, forecast-bound artifact."""
    plan = dict(plan)
    # Accept the public contract field names as input while storing one
    # canonical representation.  Hand-authored plans remain portable.
    if "episode_count" not in plan and plan.get("selected_episode_count") is not None:
        plan["episode_count"] = plan["selected_episode_count"]
    if "episode_seconds" not in plan and plan.get("selected_episode_seconds") is not None:
        plan["episode_seconds"] = plan["selected_episode_seconds"]
    if "coverage_mode" not in plan and plan.get("coverage_policy"):
        plan["coverage_mode"] = plan["coverage_policy"]
    if "compressible_event_ids" not in plan and plan.get("compressed_event_ids") is not None:
        plan["compressible_event_ids"] = plan.get("compressed_event_ids") or []
    plan.setdefault("compressible_event_ids", [])
    plan.setdefault("deferred_event_ids", [])
    plan.setdefault("omitted_event_ids", [])
    plan.setdefault("event_partition", {})
    if not plan["event_partition"]:
        plan["event_partition"] = {"EP001": list(plan.get("kept_event_ids") or [])}
    plan.setdefault("kept_event_ids", [event_id for values in plan["event_partition"].values() for event_id in values])
    plan.setdefault("selected_episode_count", plan.get("episode_count"))
    plan.setdefault("selected_episode_seconds", plan.get("episode_seconds"))
    plan.setdefault("coverage_policy", plan.get("coverage_mode"))
    plan.setdefault("compressed_event_ids", plan.get("compressible_event_ids") or [])
    plan.setdefault("accepted_overflow_episodes", [])
    forecast, forecast_version, forecast_hash = _forecast_binding(project_dir)
    outline = _outline_binding(project_dir)
    plan.setdefault("plan_schema_version", PLAN_SCHEMA_VERSION)
    # The artifact version is assigned by commit_artifact.  Do not persist the
    # proposal sentinel as if it were the immutable version; readers derive
    # the authoritative vNNN from the active artifact record.
    plan.pop("plan_version", None)
    if not plan.get("forecast_version"):
        plan["forecast_version"] = forecast_version
    if not plan.get("forecast_hash"):
        plan["forecast_hash"] = forecast_hash
    if not plan.get("outline_version"):
        plan["outline_version"] = outline["version"]
    if not plan.get("outline_hash"):
        plan["outline_hash"] = outline["hash"]
    plan["status"] = "approved"
    plan["writer_confirmation_ref"] = str(confirmation_ref or plan.get("writer_confirmation_ref") or "").strip()
    plan["confirmation_operator"] = str(operator or "").strip()
    plan.setdefault("created_at", now_iso())
    plan["updated_at"] = now_iso()
    if not plan["writer_confirmation_ref"]:
        raise ValueError("保存 capacity_plan 必须提供编剧明确确认的 confirmation_ref")
    if not plan["confirmation_operator"]:
        raise ValueError("保存 capacity_plan 必须记录实际确认人 operator")
    errors = validate_capacity_plan(plan, project_dir, require_approved=True)
    if errors:
        raise ValueError("capacity_plan 未通过绑定校验：" + "；".join(errors))
    result = commit_artifact(
        project_dir,
        "capacity_plan",
        content=plan,
        source=source,
        status="approved",
        ext="json",
        meta={
            "forecast_version": plan.get("forecast_version"),
            "forecast_hash": plan.get("forecast_hash"),
            "outline_version": plan.get("outline_version"),
            "outline_hash": plan.get("outline_hash"),
            "confirmation_operator": plan.get("confirmation_operator"),
            "confirmation_ref": plan.get("writer_confirmation_ref"),
        },
    )
    md = commit_artifact(
        project_dir,
        "capacity_plan_md",
        content=render_capacity_plan_markdown(plan),
        source="system",
        status="approved",
        ext="md",
        meta={"json_plan_version": result["version"], "json_plan_hash": result["content_hash"]},
    )
    result["markdown"] = md
    return result


def load_active_capacity_plan(project_dir: Path, *, require_approved: bool = False) -> dict | None:
    resolved = resolve_active(project_dir, "capacity_plan")
    if not resolved:
        return None
    plan = read_artifact_version(project_dir, "capacity_plan", None, resolved["version"])
    if isinstance(plan, dict):
        plan["plan_version"] = resolved["version"]
    errors = validate_capacity_plan(plan, project_dir, require_approved=require_approved)
    if errors:
        raise ValueError("活动 capacity_plan 无效：" + "；".join(errors))
    return plan


def capacity_plan_for(project_dir: Path, *, outline_hash: str | None = None) -> dict | None:
    plan = load_active_capacity_plan(project_dir, require_approved=False)
    if not plan:
        return None
    if outline_hash and plan.get("outline_hash") not in (None, outline_hash):
        return None
    return plan


def render_capacity_plan_markdown(plan: dict) -> str:
    lines = [
        "# 容量取舍计划（capacity_plan）",
        "",
        f"- 计划状态：{plan.get('status')}",
        f"- 取舍模式：{plan.get('priority_mode')}",
        f"- 覆盖范围：{plan.get('coverage_mode')}",
        f"- 集数：{plan.get('episode_count')}",
        f"- 单集时长窗口：{plan.get('episode_seconds')}",
        f"- 绑定容量预估：{plan.get('forecast_version')} / {str(plan.get('forecast_hash') or '')[:12]}",
        f"- 绑定集纲：{plan.get('outline_version')} / {str(plan.get('outline_hash') or '')[:12]}",
        f"- 编剧确认：{plan.get('confirmation_operator', '')} / {plan.get('writer_confirmation_ref', '')}",
        "",
        "## 每集事件分配",
    ]
    for episode, event_ids in (plan.get("event_partition") or {}).items():
        lines.append(f"- {episode}：" + ("、".join(event_ids) if event_ids else "（未分配）"))
    for label, key in (("可压缩", "compressible_event_ids"), ("延期", "deferred_event_ids"), ("省略", "omitted_event_ids")):
        lines.extend(["", f"## {label}", "、".join(plan.get(key) or []) or "（无）"])
    lines.extend(["", "## 编剧说明", str(plan.get("rationale") or ""), ""])
    return "\n".join(lines)
