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
    artifact_versions,
    commit_artifact,
    load_config,
    load_manifest,
    resolve_active,
    update_artifact_meta,
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


def _binding_unchanged(binding: dict, current: dict) -> bool:
    """绑定是否"实质未变"（P1）。

    上游 content_hash 双方都有且相同 → 视为未变，即使 version 号变化（例如
    事件资产仅做 span 聚焦修正时，下游改编指引/大纲内容一字未变，不应重签）。
    任一侧缺少 content_hash（旧产物）→ 退回严格的 version 校验，避免误放行。
    """
    expected_hash = binding.get("content_hash")
    current_hash = current["record"].get("content_hash")
    if expected_hash and current_hash:
        return expected_hash == current_hash
    return current["version"] == binding.get("version")


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
        if not _binding_unchanged(binding, current):
            problems.append(
                f"上游 {binding.get('kind')} 已从 {binding.get('version')} 变化为 {current['version']}"
                f"（content_hash 不同）"
            )
    plan_binding = meta.get("capacity_plan_binding")
    if plan_binding:
        current_plan = resolve_active(project_dir, "capacity_plan")
        if not current_plan:
            problems.append("capacity_plan 已不存在")
        else:
            current_record = current_plan.get("record", {})
            if plan_binding.get("content_hash") and current_record.get("content_hash") != plan_binding.get("content_hash"):
                problems.append("capacity_plan 已变化")
            elif plan_binding.get("version") and current_plan.get("version") != plan_binding.get("version"):
                problems.append("capacity_plan 版本已变化")
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
    if stage == "episode_outline":
        plan_binding = _binding(project_dir, "capacity_plan")
        if plan_binding:
            bindings.append(plan_binding)
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
    result = commit_artifact(
        project_dir,
        STAGE_KINDS[stage],
        content=content,
        source=source,
        status="needs_writer_confirmation",
        ext=ext,
        meta=meta,
    )
    carried = _carry_forward_confirmation(
        project_dir, STAGE_KINDS[stage], result["version"], result["content_hash"]
    )
    if carried:
        result["carried_forward"] = True
        result["carried_from"] = carried["carried_from"]
    return result


def _carry_forward_confirmation(
    project_dir: Path, kind: str, version: str, content_hash: str
) -> dict | None:
    """P1：重绑产物 content_hash 与已确认旧版完全相同 → 自动沿用旧确认。

    上游 content_hash 真变仍会触发完整重绑（防过期底线），但重绑后若内容
    一字未变，编剧不应再确认一次。沿用旧确认的 operator 与确认信息，并在
    新版本 meta 中记录 carried_from 供审计。
    """
    for record in artifact_versions(project_dir, kind):
        if record.get("version") == version:
            continue
        if record.get("status") != "approved":
            continue
        if record.get("content_hash") != content_hash:
            continue
        operator = (record.get("meta") or {}).get("confirmation_operator")
        operator = operator or record.get("status_operator") or "writer"
        reason_note = (record.get("meta") or {}).get("confirmation_reason") or record.get("reason") or ""
        update_artifact_status(
            project_dir,
            kind,
            version,
            status="approved",
            operator=operator,
            reason=(
                f"沿用已确认版本 {record['version']} 的确认"
                f"（content_hash 完全相同，P1 免重签）"
            ),
        )
        update_artifact_meta(
            project_dir,
            kind,
            version,
            update={
                "carried_from": record["version"],
                "carried_forward": True,
                "carried_at": now_iso(),
                "confirmation_operator": operator,
                "confirmation_reason": reason_note,
            },
        )
        if kind == "episode_outline":
            # P2-2：carried 集纲把旧版本容量决定回填到新版本，保证按
            # (新版本, 新 hash) 审计可追溯，不再落空。
            old_decision = capacity_decision_for(
                project_dir,
                outline_version=record["version"],
                outline_hash=record.get("content_hash") or "",
            )
            if old_decision:
                jsonl_append(
                    capacity_decisions_path(project_dir),
                    {
                        "outline_version": version,
                        "outline_hash": content_hash,
                        "decision": old_decision.get("decision"),
                        "operator": operator,
                        "confirmation_ref": old_decision.get("confirmation_ref") or "",
                        "aggregate_summary": old_decision.get("aggregate_summary"),
                        "carried_from_version": record["version"],
                        "created_at": now_iso(),
                    },
                )
        return {"carried_from": record["version"], "operator": operator}
    return None


def _stage_review_ok(project_dir: Path, stage: str, version: str, record: dict) -> bool:
    """当前阶段版本是否有同源绑定且通过的阶段审核。"""
    review = resolve_active(project_dir, f"stage_review_{stage}")
    if not review:
        return False
    meta = review["record"].get("meta") or {}
    return (
        meta.get("stage") == stage
        and meta.get("artifact_version") == version
        and meta.get("artifact_hash") == record.get("content_hash")
        and meta.get("verdict") in ("pass", "warning")
    )


def _capacity_gate_for(
    project_dir: Path,
    record: dict,
    capacity_decision: str | None,
    capacity_plan_version: str | None = None,
) -> tuple[dict, str, dict | None]:
    """集纲容量门禁（P2-1 共用）：校验并推导容量决定，不写入。

    返回 (aggregate, legacy_decision, capacity_plan)；medium/high 风险必须
    绑定当前容量预估与集纲哈希一致的已确认计划。旧项目仍可读取旧决定记录，
    但新项目的旧 ``accept_current_plan`` 不再是放行路径。
    confirm_stage 与 confirm_stages 预检共用同一逻辑，避免两处规则漂移，
    并让批量确认在预检阶段就整体拒绝，不产生"前面已确认、后面失败"的部分提交。
    """
    meta = record.get("meta") or {}
    reports = meta.get("density_reports", []) or []
    aggregate = aggregate_density_reports(reports)
    decision = str(capacity_decision or "").strip()
    plan = None
    if aggregate["high_episodes"] or aggregate["medium_episodes"]:
        from .capacity_plan import load_active_capacity_plan

        try:
            plan = load_active_capacity_plan(project_dir, require_approved=True)
        except ValueError as exc:
            raise ValueError(f"容量计划校验失败：{exc}") from exc
        runtime_version = load_manifest(project_dir).get("runtime_version")
        if plan:
            outline_hash = record.get("content_hash")
            if plan.get("outline_hash") != outline_hash:
                raise ValueError("capacity_plan 未绑定当前 episode_outline content_hash")
            if capacity_plan_version and capacity_plan_version != plan.get("plan_version"):
                # The artifact version is authoritative when a plan was loaded
                # from disk and did not carry its derived plan_version field.
                active_plan_version = resolve_active(project_dir, "capacity_plan")
                if not active_plan_version or capacity_plan_version != active_plan_version.get("version"):
                    raise ValueError("提供的 capacity_plan_version 不是当前活动计划")
        elif (
            (runtime_version != "0.3.7" or not meta.get("outline_contract_version"))
            and decision in ("accept_current_plan", "changes_recorded")
        ):
            # Read-only compatibility for projects created before v0.3.7.
            return aggregate, decision, None
        else:
            raise ValueError(
                "集纲存在 medium/high 容量风险，但未绑定已确认 capacity_plan；"
                "请先选择具体集数、时长和事件取舍后保存计划。"
            )
    else:
        decision = "not_applicable"
    return aggregate, decision, plan


def confirm_stage(
    project_dir: Path,
    *,
    stage: str,
    version: str,
    operator: str,
    confirmation_ref: str,
    review_override_reason: str | None = None,
    capacity_decision: str | None = None,
    capacity_plan_version: str | None = None,
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
    meta = record.get("meta") or {}
    if record.get("status") == "approved" and meta.get("carried_forward"):
        # P1：该版本已由保存时自动沿用旧确认，确认命令幂等返回。
        result = {"version": version, "status": "approved", "carried_forward": True}
        if meta.get("carried_from"):
            result["carried_from"] = meta["carried_from"]
        if stage == "episode_outline":
            result["capacity_decision"] = capacity_decision_for(
                project_dir,
                outline_version=version,
                outline_hash=record.get("content_hash") or "",
            )
        return result
    stale = _record_is_stale(project_dir, record)
    if stale:
        raise ValueError("不能确认已过期产物：" + "；".join(stale))
    if not _stage_review_ok(project_dir, stage, version, record) and not str(
        review_override_reason or ""
    ).strip():
        raise ValueError("缺少与当前版本同源绑定且通过的阶段审核；如人工完整审核，请提供 override reason")
    capacity_payload = None
    if stage == "episode_outline":
        aggregate, decision, capacity_plan = _capacity_gate_for(
            project_dir, record, capacity_decision, capacity_plan_version
        )
        capacity_payload = {
            "aggregate": aggregate,
            "decision": decision,
            "outline_hash": record.get("content_hash", ""),
            "capacity_plan": capacity_plan,
        }
        if capacity_plan:
            active_plan = resolve_active(project_dir, "capacity_plan")
            update_artifact_meta(
                project_dir,
                kind,
                version,
                update={
                    "capacity_plan_binding": {
                        "version": (active_plan or {}).get("version") or capacity_plan.get("plan_version"),
                        "content_hash": (active_plan or {}).get("record", {}).get("content_hash"),
                        "forecast_hash": capacity_plan.get("forecast_hash"),
                        "outline_hash": capacity_plan.get("outline_hash"),
                    }
                },
            )
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
        if capacity_payload.get("capacity_plan"):
            result["capacity_plan"] = capacity_payload["capacity_plan"]
        else:
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


def confirm_stages(
    project_dir: Path,
    *,
    stages: list[str],
    operator: str,
    confirmation_ref: str,
    review_override_reason: str | None = None,
    capacity_decisions: dict | None = None,
    capacity_plan_versions: dict | None = None,
) -> dict:
    """P1：多阶段重绑合并为一次批量确认。

    先对全部阶段做统一预检（版本存在、未过期、审核通过/override），全部通过
    后再逐个确认，避免半途失败造成部分已确认、部分未确认的不一致状态。
    """
    if not stages:
        raise ValueError("批量确认至少需要一个阶段")
    unknown = [s for s in stages if s not in STAGE_KINDS]
    if unknown:
        raise ValueError(f"未知阶段：{', '.join(unknown)}")
    capacity_decisions = capacity_decisions or {}
    capacity_plan_versions = capacity_plan_versions or {}
    if not str(operator or "").strip():
        raise ValueError("确认阶段必须记录实际确认人 operator")
    if not str(confirmation_ref or "").strip():
        raise ValueError("确认阶段必须提供用户明确确认的 confirmation_ref")
    preflight: list[tuple[str, str, dict]] = []
    for stage in stages:
        kind = STAGE_KINDS[stage]
        resolved = resolve_active(project_dir, kind)
        if not resolved:
            raise ValueError(f"缺少 {stage} 产物")
        record = resolved["record"]
        stale = _record_is_stale(project_dir, record)
        if stale:
            raise ValueError(f"不能确认已过期产物：{stage}：" + "；".join(stale))
        if record.get("status") == "approved" and (record.get("meta") or {}).get("carried_forward"):
            continue  # 已自动沿用旧确认，无需再确认
        if not _stage_review_ok(project_dir, stage, resolved["version"], record) and not str(
            review_override_reason or ""
        ).strip():
            raise ValueError(
                f"缺少 {stage} 与当前版本同源绑定且通过的阶段审核；"
                "如人工完整审核，请提供 override reason"
            )
        if stage == "episode_outline":
            # P2-1：容量门禁并入预检——缺/非法容量决定在预检阶段整体拒绝，
            # 不会在确认循环中途失败留下"前面已确认、后面失败"的部分提交。
            _capacity_gate_for(
                project_dir,
                record,
                capacity_decisions.get(stage),
                capacity_plan_versions.get(stage),
            )
        preflight.append((stage, resolved["version"], record))
    results = []
    for stage, version, _record in preflight:
        results.append(
            confirm_stage(
                project_dir,
                stage=stage,
                version=version,
                operator=operator,
                confirmation_ref=confirmation_ref,
                review_override_reason=review_override_reason,
                capacity_decision=capacity_decisions.get(stage),
                capacity_plan_version=capacity_plan_versions.get(stage),
            )
        )
    return {"stages": results, "carried_forward_skipped": len(stages) - len(preflight)}


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
