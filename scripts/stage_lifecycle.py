"""Deterministic lifecycle for the three creative planning stages.

The model may propose content, but it cannot approve its own result.  Every
saved artifact is bound to an immutable stage context and remains pending
until a writer explicitly confirms a reviewed version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    atomic_write_json,
    canonical_json,
    ensure_dir,
    jsonl_append,
    now_iso,
    read_jsonl,
    stable_hash,
)
from .state_store import (
    commit_artifact,
    load_config,
    load_manifest,
    resolve_active,
    update_artifact_status,
)


STAGE_KINDS = {
    "adaptation": "adaptation_strategy",
    "story_outline": "story_outline",
    "episode_outline": "episode_outline",
}

CREATIVE_UPSTREAMS = {
    "adaptation": (),
    "story_outline": ("adaptation",),
    "episode_outline": ("adaptation", "story_outline"),
}

AUXILIARY_UPSTREAM_KINDS = ("project_brief", "source_events", "capacity_forecast")


def _semantic_context_body(context: dict) -> dict:
    return {k: v for k, v in context.items() if k not in ("context_hash", "context_file", "created_at")}


def verify_stage_context(context: dict) -> bool:
    expected = str(context.get("context_hash") or "")
    return len(expected) == 64 and stable_hash(_semantic_context_body(context)) == expected


def _binding(project_dir: Path, kind: str, *, required: bool = False) -> dict | None:
    resolved = resolve_active(project_dir, kind)
    if not resolved:
        if required:
            raise ValueError(f"缺少前置产物：{kind}")
        return None
    record = resolved["record"]
    return {
        "kind": kind,
        "version": resolved["version"],
        "content_hash": record.get("content_hash"),
        "status": record.get("status"),
    }


def _record_is_stale(project_dir: Path, record: dict) -> list[str]:
    problems: list[str] = []
    meta = record.get("meta") or {}
    if meta.get("config_hash") and meta.get("config_hash") != stable_hash(load_config(project_dir)):
        problems.append("项目配置已变化")
    if meta.get("project_instance_id") and meta.get("project_instance_id") != load_manifest(project_dir).get("project_instance_id"):
        problems.append("产物不属于当前项目实例")
    for binding in meta.get("upstream_bindings", []) or []:
        current = resolve_active(project_dir, str(binding.get("kind") or ""))
        if not current:
            problems.append(f"上游 {binding.get('kind')} 已不存在")
            continue
        current_record = current["record"]
        if current["version"] != binding.get("version") or current_record.get("content_hash") != binding.get("content_hash"):
            problems.append(
                f"上游 {binding.get('kind')} 已从 {binding.get('version')} 变化为 {current['version']}"
            )
    return problems


def assert_stage_ready(project_dir: Path, stage: str) -> None:
    if stage not in STAGE_KINDS:
        raise ValueError(f"未知阶段：{stage}")
    problems: list[str] = []
    for upstream_stage in CREATIVE_UPSTREAMS[stage]:
        kind = STAGE_KINDS[upstream_stage]
        resolved = resolve_active(project_dir, kind)
        if not resolved:
            problems.append(f"缺少已确认的{upstream_stage}产物")
            continue
        record = resolved["record"]
        meta = record.get("meta") or {}
        if not meta.get("stage_context_hash") and not meta.get("manual_import"):
            problems.append(f"{upstream_stage} {resolved['version']} 是未绑定输入的旧 AI 产物，必须重新生成或由编剧显式人工导入")
        if record.get("status") != "approved":
            problems.append(
                f"{upstream_stage} {resolved['version']} 状态为 {record.get('status')}，尚未由编剧确认"
            )
        problems.extend(f"{upstream_stage}已过期：{item}" for item in _record_is_stale(project_dir, record))
    if problems:
        raise ValueError("；".join(problems))


def assert_stage_artifact_confirmed(project_dir: Path, stage: str) -> None:
    """Require the current artifact of ``stage`` to be writer-confirmed and fresh."""
    kind = STAGE_KINDS.get(stage)
    if not kind:
        raise ValueError(f"未知阶段：{stage}")
    resolved = resolve_active(project_dir, kind)
    if not resolved:
        raise ValueError(f"缺少 {stage} 产物")
    record = resolved["record"]
    meta = record.get("meta") or {}
    if not meta.get("stage_context_hash") and not meta.get("manual_import"):
        raise ValueError(f"{stage} {resolved['version']} 是未绑定输入的旧 AI 产物，不能进入下一阶段")
    if record.get("status") != "approved":
        raise ValueError(f"{stage} {resolved['version']} 尚未由编剧确认")
    stale = _record_is_stale(project_dir, record)
    if stale:
        raise ValueError(f"{stage} 已过期：" + "；".join(stale))


def build_stage_context(project_dir: Path, stage: str, *, save: bool = True) -> dict:
    """Build a hash-bound snapshot of the exact inputs for one stage."""
    assert_stage_ready(project_dir, stage)
    config = load_config(project_dir)
    bindings: list[dict] = []
    for kind in AUXILIARY_UPSTREAM_KINDS:
        item = _binding(project_dir, kind)
        if item:
            bindings.append(item)
    for upstream_stage in CREATIVE_UPSTREAMS[stage]:
        item = _binding(project_dir, STAGE_KINDS[upstream_stage], required=True)
        if item:
            bindings.append(item)
    body = {
        "stage": stage,
        "project_id": config.get("project_id"),
        "project_instance_id": load_manifest(project_dir).get("project_instance_id"),
        "config_hash": stable_hash(config),
        "upstream_bindings": bindings,
    }
    context = {**body, "context_hash": stable_hash(body)}
    if save:
        directory = project_dir / "state" / "stage_contexts"
        ensure_dir(directory)
        path = directory / f"{stage}_{context['context_hash']}.json"
        if path.exists():
            import json

            existing = json.loads(path.read_text(encoding="utf-8"))
            if canonical_json(existing) != canonical_json(context):
                raise ValueError(f"stage context hash 路径碰撞或快照被篡改：{path}")
        else:
            atomic_write_json(path, context)
        atomic_write_json(
            directory / f"current_{stage}.json",
            {"context_hash": context["context_hash"], "path": path.name, "created_at": now_iso()},
        )
        context["context_file"] = str(path)
    return context


def load_stage_context(project_dir: Path, stage: str, context_hash: str) -> dict:
    path = project_dir / "state" / "stage_contexts" / f"{stage}_{context_hash}.json"
    if not path.exists():
        raise ValueError(f"找不到 stage_context：{stage}/{context_hash}")
    import json

    context = json.loads(path.read_text(encoding="utf-8"))
    if context.get("stage") != stage or context.get("context_hash") != context_hash or not verify_stage_context(context):
        raise ValueError("stage_context 绑定或哈希校验失败")
    return context


def save_stage_artifact(
    project_dir: Path,
    *,
    stage: str,
    content: Any,
    stage_context: dict,
    source: str = "ai",
    ext: str | None = None,
    extra_meta: dict | None = None,
) -> dict:
    if stage not in STAGE_KINDS:
        raise ValueError(f"未知阶段：{stage}")
    if stage_context.get("stage") != stage or not verify_stage_context(stage_context):
        raise ValueError("stage_context 与阶段不一致或 context_hash 无效")
    current_config = load_config(project_dir)
    current_manifest = load_manifest(project_dir)
    if stage_context.get("config_hash") != stable_hash(current_config):
        raise ValueError("stage_context 生成后项目配置已变化，拒绝保存旧输入产物")
    if stage_context.get("project_instance_id") != current_manifest.get("project_instance_id"):
        raise ValueError("stage_context 不属于当前项目实例")
    # Recheck current state at consumption time.  A bundle that was generated
    # before an upstream change must not be silently accepted.
    assert_stage_ready(project_dir, stage)
    expected_context = build_stage_context(project_dir, stage, save=False)
    if expected_context.get("context_hash") != stage_context.get("context_hash"):
        raise ValueError("stage_context 未完整绑定当前阶段所需全部输入，或已经过期")
    for expected in stage_context.get("upstream_bindings", []) or []:
        current = resolve_active(project_dir, expected["kind"])
        if not current or current["version"] != expected.get("version") or current["record"].get("content_hash") != expected.get("content_hash"):
            raise ValueError(f"stage_context 上游绑定已变化：{expected.get('kind')}")
    meta = {
        "stage": stage,
        "stage_context_hash": stage_context["context_hash"],
        "context_hash": stage_context["context_hash"],
        "input_fingerprint": stage_context["context_hash"],
        "config_hash": stage_context.get("config_hash"),
        "project_instance_id": stage_context.get("project_instance_id"),
        "upstream_bindings": stage_context.get("upstream_bindings", []),
    }
    meta.update(extra_meta or {})
    return commit_artifact(
        project_dir,
        STAGE_KINDS[stage],
        content=content,
        source=source,
        status="needs_writer_confirmation",
        ext=ext,
        meta=meta,
    )


def confirm_stage(
    project_dir: Path,
    *,
    stage: str,
    version: str,
    operator: str,
    confirmation_ref: str,
    review_override_reason: str | None = None,
    capacity_decision: str | None = None,
) -> dict:
    if stage not in STAGE_KINDS:
        raise ValueError(f"未知阶段：{stage}")
    if not str(operator or "").strip():
        raise ValueError("确认阶段必须记录实际确认人 operator")
    if not str(confirmation_ref or "").strip():
        raise ValueError("确认阶段必须提供用户明确确认的 confirmation_ref")
    kind = STAGE_KINDS[stage]
    resolved = resolve_active(project_dir, kind)
    if not resolved or resolved["version"] != version:
        raise ValueError(f"只能确认当前活动版本：{kind}/{version}")
    record = resolved["record"]
    stale = _record_is_stale(project_dir, record)
    if stale:
        raise ValueError("不能确认已过期产物：" + "；".join(stale))
    review = resolve_active(project_dir, f"stage_review_{stage}")
    review_ok = False
    if review:
        meta = review["record"].get("meta") or {}
        review_ok = (
            meta.get("stage") == stage
            and meta.get("artifact_version") == version
            and meta.get("artifact_hash") == record.get("content_hash")
            and meta.get("verdict") in ("pass", "warning")
        )
    if not review_ok and not str(review_override_reason or "").strip():
        raise ValueError("缺少与当前版本同源绑定且通过的阶段审核；如人工完整审核，请提供 override reason")
    capacity_payload = None
    if stage == "episode_outline":
        meta = record.get("meta") or {}
        reports = meta.get("density_reports", []) or []
        aggregate = aggregate_density_reports(reports)
        decision = str(capacity_decision or "").strip()
        if aggregate["high_episodes"] or aggregate["medium_episodes"]:
            if decision not in ("accept_current_plan", "changes_recorded"):
                raise ValueError(
                    "集纲存在 medium/high 容量风险，编剧必须一次性确认或记录调整。\n"
                    + aggregate["summary"]
                    + "\n请使用 --capacity-decision accept_current_plan（接受当前规划）"
                    "或 changes_recorded（已记录调整后重新保存集纲）。"
                )
        else:
            decision = "not_applicable"
        capacity_payload = {
            "aggregate": aggregate,
            "decision": decision,
            "outline_hash": record.get("content_hash", ""),
        }
    result = update_artifact_status(
        project_dir,
        kind,
        version,
        status="approved",
        operator=operator,
        reason=(
            (review_override_reason or "writer confirmed after bound stage review")
            + f"; confirmation_ref={confirmation_ref.strip()}"
        ),
    )
    if stage == "episode_outline":
        decision_record = record_capacity_decision(
            project_dir,
            outline_version=version,
            outline_hash=capacity_payload["outline_hash"],
            decision=capacity_payload["decision"],
            operator=operator,
            confirmation_ref=confirmation_ref,
            aggregate=capacity_payload["aggregate"],
        )
        result["capacity_decision"] = decision_record
    return result


def compact_event_catalog(events: list[dict], *, text_limit: int = 96) -> list[dict]:
    """Small routing catalog; full actions/quotes are loaded only on demand."""
    keys = (
        "event_id",
        "chapter_id",
        "importance",
        "characters",
        "dependencies",
        "minimum_screen_seconds",
        "preferred_screen_seconds",
    )
    result: list[dict] = []
    for event in events:
        item = {key: event[key] for key in keys if key in event}
        for key in ("event", "result"):
            if event.get(key):
                text = str(event[key])
                item[key] = text if len(text) <= text_limit else text[: text_limit - 1] + "…"
        result.append(item)
    return result


def episode_density_report(
    outline: dict,
    events_by_id: dict[str, dict],
    *,
    outline_version: str | None = None,
    outline_hash: str | None = None,
) -> dict:
    event_ids: list[str] = []
    for eid in outline.get("source_event_ids", []) or []:
        if eid not in event_ids:
            event_ids.append(eid)
    for beat in outline.get("required_story_beats", []) or []:
        for eid in beat.get("event_ids", []) or []:
            if eid not in event_ids:
                event_ids.append(eid)
    for beat in outline.get("beat_plan", []) or []:
        for eid in beat.get("event_ids", []) or []:
            if eid not in event_ids:
                event_ids.append(eid)
    selected = [events_by_id[eid] for eid in event_ids if eid in events_by_id]
    minimum = sum(int(e.get("minimum_screen_seconds") or 0) for e in selected)
    preferred = sum(int(e.get("preferred_screen_seconds") or e.get("minimum_screen_seconds") or 0) for e in selected)
    suggested = outline.get("suggested_seconds") or []
    upper = max(suggested) if isinstance(suggested, list) and suggested else None
    missing_seconds = [
        eid
        for eid in event_ids
        if eid not in events_by_id
        or events_by_id[eid].get("minimum_screen_seconds") is None
        or events_by_id[eid].get("preferred_screen_seconds") is None
    ]
    if upper is not None and minimum > upper:
        pressure = "high"
    elif upper is not None and preferred > upper:
        pressure = "medium"
    else:
        pressure = "low"
    return {
        "event_ids": event_ids,
        "minimum_event_seconds": minimum,
        "preferred_event_seconds": preferred,
        "suggested_seconds": suggested,
        "pressure": pressure,
        "confidence": "low" if missing_seconds else "high",
        "calculation_basis": [
            "事件最低/理想时长来自 source_events（缺失时不计入并降低置信度）",
            "对比本集 suggested_seconds 上限判断压力等级",
            "只用于编剧决策，不是创作硬门禁",
        ],
        "binding": {
            "outline_version": outline_version,
            "outline_hash": outline_hash,
        },
        "advisory_only": True,
        "note": "容量仅供编剧判断；剧本阶段可按实际创作调整，不自动回滚上游。",
    }


def aggregate_density_reports(reports: list[dict]) -> dict:
    """One-shot aggregate for writer-facing risk summaries (not all details)."""
    reports = reports or []
    high = [int(r.get("episode")) for r in reports if r.get("pressure") == "high"]
    medium = [int(r.get("episode")) for r in reports if r.get("pressure") == "medium"]
    low = [int(r.get("episode")) for r in reports if r.get("pressure") == "low"]
    parts = []
    if high:
        parts.append(f"high {len(high)} 集（EP{','.join(str(x) for x in high)}）")
    if medium:
        parts.append(f"medium {len(medium)} 集（EP{','.join(str(x) for x in medium)}）")
    if not parts:
        parts.append("无 medium/high 风险集")
    return {
        "high_episodes": high,
        "medium_episodes": medium,
        "low_count": len(low),
        "summary": "集纲容量风险：" + "，".join(parts) + "；仅提示，编剧可一次接受或要求调整。",
        "advisory_only": True,
    }


def render_density_summary(report: dict) -> str:
    report = report or {}
    suggested = report.get("suggested_seconds") or "未定"
    return (
        f"本集容量压力：{report.get('pressure')}（事件最低 {report.get('minimum_event_seconds')} 秒，"
        f"偏好 {report.get('preferred_event_seconds')} 秒，建议 {suggested}；仅提示，不阻断）"
    )


def capacity_decisions_path(project_dir: Path) -> Path:
    return project_dir / "state" / "capacity_decisions.jsonl"


def record_capacity_decision(
    project_dir: Path,
    *,
    outline_version: str,
    outline_hash: str,
    decision: str,
    operator: str,
    confirmation_ref: str,
    aggregate: dict,
) -> dict:
    allowed = {"accept_current_plan", "changes_recorded", "not_applicable"}
    if decision not in allowed:
        raise ValueError(f"非法集纲容量决定：{decision}")
    record = {
        "outline_version": outline_version,
        "outline_hash": outline_hash,
        "decision": decision,
        "operator": operator,
        "confirmation_ref": confirmation_ref,
        "aggregate_summary": aggregate.get("summary"),
        "created_at": now_iso(),
    }
    jsonl_append(capacity_decisions_path(project_dir), record)
    return record


def capacity_decision_for(
    project_dir: Path,
    *,
    outline_version: str,
    outline_hash: str,
) -> dict | None:
    records = read_jsonl(capacity_decisions_path(project_dir))
    for record in reversed(records):
        if (
            record.get("outline_version") == outline_version
            and record.get("outline_hash") == outline_hash
        ):
            return record
    return None
