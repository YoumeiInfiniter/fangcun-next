"""Completeness checks for v0.3.7 semantic review reports."""

from __future__ import annotations

import re
from typing import Any


CORE_DIMENSIONS = (
    "source_fidelity",
    "character_knowledge",
    "dialogue_pairing",
    "shootability",
    "narration_substitution",
    "previous_episode_bridge",
    "ending_hook",
    "continuity",
)
BEAT_STATUSES = {"dramatized", "summarized", "missing", "not_applicable"}
SEVERITIES = {"error", "warning", "suggestion", "none"}


def core_beats_for_context(context: dict) -> list[dict]:
    outline = context.get("episode_outline") or {}
    beats: list[dict] = []
    seen: set[str] = set()
    for item in outline.get("required_story_beats", []) or []:
        if not isinstance(item, dict):
            continue
        beat_id = str(item.get("id") or f"required-beat-{len(beats) + 1:03d}")
        if beat_id in seen:
            continue
        seen.add(beat_id)
        beats.append({"beat_id": beat_id, "source": "required_story_beats", **item})
    for item in outline.get("beat_plan", []) or []:
        if not isinstance(item, dict) or item.get("priority") == "optional":
            continue
        beat_id = str(item.get("beat_id") or f"planned-beat-{len(beats) + 1:03d}")
        if beat_id in seen:
            continue
        seen.add(beat_id)
        beats.append({"beat_id": beat_id, "source": "beat_plan", **item})
    return beats


def system_risk_ids(draft_quality: dict | None) -> list[str]:
    return [
        str(item.get("risk_id"))
        for item in (draft_quality or {}).get("risk_signals", []) or []
        if isinstance(item, dict) and item.get("risk_id")
    ]


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _evidence_error(evidence: Any, draft_text: str, *, required: bool = True) -> str | None:
    if not isinstance(evidence, dict):
        return "缺少 draft_evidence 对象" if required else None
    start = evidence.get("line_start")
    end = evidence.get("line_end")
    quote = str(evidence.get("artifact_quote") or "")
    lines = draft_text.splitlines()
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
        return "draft_evidence 行号不在绑定草稿范围内"
    if not quote:
        return "draft_evidence 缺少 artifact_quote"
    excerpt = "\n".join(lines[start - 1 : end])
    if _norm(quote) not in _norm(excerpt):
        return "draft_evidence.artifact_quote 不在声明行号范围内"
    return None


def _beat_error(item: dict, *, required_visuals_expected: bool = True) -> str | None:
    status = item.get("status")
    if status not in BEAT_STATUSES:
        return f"status 非法：{status!r}"
    for key in ("causality_complete", "dialogue_chain_complete", "visible_reaction_present", "required_visuals_present"):
        if not isinstance(item.get(key), bool):
            return f"{key} 必须是 boolean"
    severity = item.get("severity")
    if severity not in SEVERITIES:
        return f"severity 非法：{severity!r}"
    if not isinstance(item.get("fix", ""), str):
        return "fix 必须是字符串"
    checks = ("causality_complete", "dialogue_chain_complete", "visible_reaction_present")
    if required_visuals_expected:
        checks = checks + ("required_visuals_present",)
    if status in {"summarized", "missing"} or not all(item.get(key) for key in checks):
        if severity != "error":
            return "核心 beat 只剩总结/缺失或关键检查失败时必须为 error"
    return None


def _dimension_entries(report: dict) -> list[dict]:
    entries = report.get("dimension_checks")
    if isinstance(entries, dict):
        return [{"dimension": key, **(value if isinstance(value, dict) else {"status": value})} for key, value in entries.items()]
    return [item for item in (entries or []) if isinstance(item, dict)]


def _risk_entries(report: dict) -> list[dict]:
    entries = report.get("risk_signal_checks")
    if isinstance(entries, dict):
        return [{"risk_id": key, **(value if isinstance(value, dict) else {"status": value})} for key, value in entries.items()]
    return [item for item in (entries or []) if isinstance(item, dict)]


def validate_review_completeness(
    report: dict,
    context: dict,
    draft_text: str,
    draft_quality: dict | None = None,
) -> list[str]:
    """Validate semantic coverage without deciding whether writing is good."""
    errors: list[str] = []
    beats = core_beats_for_context(context)
    strict = bool(beats) or any(
        (item.get("mode") or item.get("quote_mode")) in ("exact", "semantic")
        for item in ((context.get("episode_outline") or {}).get("required_quotes", []) or [])
        if isinstance(item, dict)
    )
    beat_entries = report.get("beat_checks")
    if isinstance(beat_entries, dict):
        beat_entries = [{"beat_id": key, **(value if isinstance(value, dict) else {})} for key, value in beat_entries.items()]
    beat_entries = [item for item in (beat_entries or []) if isinstance(item, dict)]
    expected_ids = [str(item["beat_id"]) for item in beats]
    actual_ids = [str(item.get("beat_id")) for item in beat_entries]
    if strict:
        missing = [item for item in expected_ids if actual_ids.count(item) == 0]
        duplicate = [item for item in expected_ids if actual_ids.count(item) > 1]
        unknown = [item for item in actual_ids if item not in expected_ids]
        if missing:
            errors.append("缺少 core beat 检查：" + ", ".join(missing))
        if duplicate:
            errors.append("core beat 重复检查：" + ", ".join(duplicate))
        if unknown:
            errors.append("审核报告包含未知 core beat：" + ", ".join(unknown))
        for item in beat_entries:
            if str(item.get("beat_id")) not in expected_ids:
                continue
            source_beat = next(beat for beat in beats if str(beat["beat_id"]) == str(item.get("beat_id")))
            expected_visuals = bool(
                source_beat.get("required_visual_beats")
                or source_beat.get("required_visuals")
                or source_beat.get("visual_beats")
            )
            beat_error = _beat_error(item, required_visuals_expected=expected_visuals)
            if beat_error:
                errors.append(f"beat {item.get('beat_id')}: {beat_error}")
            evidence_error = _evidence_error(item.get("draft_evidence"), draft_text)
            if evidence_error:
                errors.append(f"beat {item.get('beat_id')}: {evidence_error}")
    elif beat_entries:
        for item in beat_entries:
            beat_error = _beat_error(item)
            if beat_error:
                errors.append(f"beat {item.get('beat_id')}: {beat_error}")

    dimensions = _dimension_entries(report)
    dimension_ids = [str(item.get("dimension")) for item in dimensions]
    if strict:
        missing_dimensions = [item for item in CORE_DIMENSIONS if dimension_ids.count(item) == 0]
        duplicate_dimensions = [item for item in CORE_DIMENSIONS if dimension_ids.count(item) > 1]
        unknown_dimensions = [item for item in dimension_ids if item not in CORE_DIMENSIONS]
        if missing_dimensions:
            errors.append("缺少审核维度：" + ", ".join(missing_dimensions))
        if duplicate_dimensions:
            errors.append("审核维度重复：" + ", ".join(duplicate_dimensions))
        if unknown_dimensions:
            errors.append("审核报告包含未知维度：" + ", ".join(unknown_dimensions))
        for item in dimensions:
            if item.get("dimension") not in CORE_DIMENSIONS:
                continue
            if item.get("status") not in ("pass", "warning", "error", "not_applicable"):
                errors.append(f"维度 {item.get('dimension')} status 非法")
            if item.get("severity") not in SEVERITIES:
                errors.append(f"维度 {item.get('dimension')} severity 非法")
            if item.get("severity") == "error":
                evidence_error = _evidence_error(item.get("draft_evidence"), draft_text)
                if evidence_error:
                    errors.append(f"维度 {item.get('dimension')}: {evidence_error}")

    expected_risks = system_risk_ids(draft_quality)
    risk_entries = _risk_entries(report)
    risk_ids = [str(item.get("risk_id") or item.get("signal_id")) for item in risk_entries]
    if strict and expected_risks:
        missing_risks = [item for item in expected_risks if risk_ids.count(item) == 0]
        duplicate_risks = [item for item in expected_risks if risk_ids.count(item) > 1]
        unknown_risks = [item for item in risk_ids if item not in expected_risks]
        if missing_risks:
            errors.append("缺少系统 risk signal 检查：" + ", ".join(missing_risks))
        if duplicate_risks:
            errors.append("系统 risk signal 重复检查：" + ", ".join(duplicate_risks))
        if unknown_risks:
            errors.append("审核报告包含未知 risk signal：" + ", ".join(unknown_risks))
        for item in risk_entries:
            risk_id = str(item.get("risk_id") or item.get("signal_id"))
            if risk_id not in expected_risks:
                continue
            if item.get("status") not in ("confirmed", "rebutted", "not_applicable", "accepted"):
                errors.append(f"risk signal {risk_id} status 非法")
            if not str(item.get("assessment") or item.get("note") or "").strip():
                errors.append(f"risk signal {risk_id} 缺少 assessment")
    return list(dict.fromkeys(errors))


validate_review_report_completeness = validate_review_completeness
