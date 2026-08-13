"""Deterministic completeness and gate checks for v0.3.7 review reports.

The model supplies the semantic judgement, but the runtime owns the report
shape, coverage accounting and the final verdict.  In particular, a report
cannot turn a failed beat/dimension/required quote into ``pass`` merely by
leaving ``issues`` empty.
"""

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
QUOTE_MODES = {"exact", "semantic", "legacy_unspecified"}
QUOTE_STATUSES = {
    "present",
    "exact_match",
    "semantic_match",
    "semantic_mismatch",
    "missing",
    "not_applicable",
}


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


def required_quotes_for_context(context: dict) -> list[dict]:
    """Return stable quote obligations, including legacy dialogue anchors."""
    outline = context.get("episode_outline") or {}
    brief = context.get("episode_execution_brief") or {}
    raw_quotes = brief.get("required_quotes")
    if not isinstance(raw_quotes, list):
        raw_quotes = outline.get("required_quotes", []) or []
    quotes: list[dict] = []
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()

    def add(item: dict, *, default_mode: str = "legacy_unspecified") -> None:
        quote = str(item.get("quote") or "").strip()
        if not quote:
            return
        mode = str(item.get("mode") or item.get("quote_mode") or default_mode)
        if mode not in QUOTE_MODES:
            mode = "legacy_unspecified"
        quote_id = str(item.get("quote_id") or item.get("id") or f"required-quote-{len(quotes) + 1:03d}")
        if quote_id in seen_ids:
            quote_id = f"required-quote-{len(quotes) + 1:03d}"
        if quote_id in seen_ids or quote in seen_texts:
            return
        seen_ids.add(quote_id)
        seen_texts.add(quote)
        quotes.append(
            {
                "quote_id": quote_id,
                "quote": quote,
                "mode": mode,
                **({"source_event_id": item.get("source_event_id")} if item.get("source_event_id") else {}),
                **({"pair_id": item.get("pair_id")} if item.get("pair_id") else {}),
            }
        )

    for item in raw_quotes:
        if isinstance(item, dict):
            add(item)
    for item in outline.get("dialogue_anchors", []) or []:
        if isinstance(item, dict) and item.get("type") == "quote":
            add(item)
    return quotes


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
        return [
            {"dimension": key, **(value if isinstance(value, dict) else {"status": value})}
            for key, value in entries.items()
        ]
    return [item for item in (entries or []) if isinstance(item, dict)]


def _risk_entries(report: dict) -> list[dict]:
    entries = report.get("risk_signal_checks")
    if isinstance(entries, dict):
        return [
            {"risk_id": key, **(value if isinstance(value, dict) else {"status": value})}
            for key, value in entries.items()
        ]
    return [item for item in (entries or []) if isinstance(item, dict)]


def _quote_entries(report: dict) -> list[dict]:
    entries = report.get("required_quote_checks")
    if isinstance(entries, dict):
        return [
            {"quote_id": key, **(value if isinstance(value, dict) else {"status": value})}
            for key, value in entries.items()
        ]
    return [item for item in (entries or []) if isinstance(item, dict)]


def _quote_key(item: dict) -> str:
    return str(item.get("quote_id") or item.get("id") or "")


def _quote_error(item: dict, expected: dict, draft_text: str) -> str | None:
    quote_id = _quote_key(item)
    if not quote_id:
        return "缺少 quote_id"
    if item.get("mode") not in QUOTE_MODES:
        return f"quote {quote_id} mode 非法"
    if item.get("mode") != expected.get("mode"):
        return f"quote {quote_id} mode 与上下文不一致"
    if str(item.get("quote") or "").strip() != str(expected.get("quote") or "").strip():
        return f"quote {quote_id} 文本与上下文不一致"
    if item.get("status") not in QUOTE_STATUSES:
        return f"quote {quote_id} status 非法"
    if item.get("severity") not in SEVERITIES:
        return f"quote {quote_id} severity 非法"
    if not isinstance(item.get("fix", ""), str):
        return f"quote {quote_id} fix 必须是字符串"
    mode = expected.get("mode")
    evidence_required = mode == "semantic" or item.get("status") in {
        "present",
        "exact_match",
        "semantic_match",
        "semantic_mismatch",
    }
    evidence_error = _evidence_error(item.get("draft_evidence"), draft_text, required=evidence_required)
    if evidence_error:
        return f"quote {quote_id}: {evidence_error}"
    return None


def validate_review_completeness(
    report: dict,
    context: dict,
    draft_text: str,
    draft_quality: dict | None = None,
) -> list[str]:
    """Validate report structure and exact coverage, without judging quality."""
    errors: list[str] = []
    beats = core_beats_for_context(context)
    expected_quotes = required_quotes_for_context(context)
    contract_version = str(report.get("review_contract_version") or "")
    strict = bool(beats) or any(item.get("mode") in ("exact", "semantic") for item in expected_quotes)
    strict = strict or contract_version == "0.3.7"

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
            # A missing core beat may have no matching excerpt.  Its status is
            # itself the blocking evidence; a supplied excerpt is still
            # checked deterministically.
            evidence_error = _evidence_error(
                item.get("draft_evidence"),
                draft_text,
                required=item.get("status") not in {"missing", "not_applicable"},
            )
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

    quotes = _quote_entries(report)
    expected_quote_ids = [str(item["quote_id"]) for item in expected_quotes]
    actual_quote_ids = [_quote_key(item) for item in quotes]
    if strict:
        missing_quotes = [item for item in expected_quote_ids if actual_quote_ids.count(item) == 0]
        duplicate_quotes = [item for item in expected_quote_ids if actual_quote_ids.count(item) > 1]
        unknown_quotes = [item for item in actual_quote_ids if item not in expected_quote_ids]
        if missing_quotes:
            errors.append("缺少 required quote 检查：" + ", ".join(missing_quotes))
        if duplicate_quotes:
            errors.append("required quote 重复检查：" + ", ".join(duplicate_quotes))
        if unknown_quotes:
            errors.append("审核报告包含未知 required quote：" + ", ".join(unknown_quotes))
        for item in quotes:
            quote_id = _quote_key(item)
            if quote_id not in expected_quote_ids:
                continue
            expected = next(quote for quote in expected_quotes if quote["quote_id"] == quote_id)
            quote_error = _quote_error(item, expected, draft_text)
            if quote_error:
                errors.append(quote_error)

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


def _gate_issue(
    issue_id: str,
    severity: str,
    category: str,
    problem: str,
    fix: str = "",
) -> dict:
    return {
        "id": issue_id,
        "severity": severity,
        "category": category,
        "problem": problem,
        "fix": fix,
        "system_gate": True,
        "system_gate_key": issue_id,
    }


def review_gate_issues(
    report: dict,
    context: dict | None = None,
    draft_text: str = "",
    draft_quality: dict | None = None,
) -> list[dict]:
    """Synthesize deterministic issues from semantic checks and hard signals."""
    context = context or {}
    generated: list[dict] = []
    beats = core_beats_for_context(context)
    beat_entries = report.get("beat_checks")
    if isinstance(beat_entries, dict):
        beat_entries = [{"beat_id": key, **(value if isinstance(value, dict) else {})} for key, value in beat_entries.items()]
    beat_by_id = {str(item.get("beat_id")): item for item in (beat_entries or []) if isinstance(item, dict)}
    for expected in beats:
        beat_id = str(expected["beat_id"])
        item = beat_by_id.get(beat_id)
        if not item:
            continue  # structural completeness reports this separately
        required_visuals_expected = bool(
            expected.get("required_visual_beats")
            or expected.get("required_visuals")
            or expected.get("visual_beats")
        )
        failed_checks = [
            item.get(key) is False
            for key in ("causality_complete", "dialogue_chain_complete", "visible_reaction_present")
        ]
        if required_visuals_expected:
            failed_checks.append(item.get("required_visuals_present") is False)
        failed = (
            item.get("status") in {"summarized", "missing", "not_applicable"}
            or any(failed_checks)
            or item.get("severity") == "error"
        )
        if failed:
            generated.append(
                _gate_issue(
                    f"BEAT-{beat_id}",
                    "error",
                    "outline_adherence" if item.get("status") in {"summarized", "missing", "not_applicable"} else "shootability",
                    f"核心 beat {beat_id} 未被完整落实：status={item.get('status')!r}，逐项检查存在失败或 error 标记。",
                    str(item.get("fix") or "补齐该 beat 的因果、对白连接、可见反应和必需画面。"),
                )
            )

    for item in _dimension_entries(report):
        dimension = str(item.get("dimension") or "")
        if dimension not in CORE_DIMENSIONS:
            continue
        status = item.get("status")
        severity = item.get("severity")
        if status == "error" or severity == "error":
            generated.append(
                _gate_issue(
                    f"DIMENSION-{dimension}",
                    "error",
                    dimension if dimension in {
                        "source_fidelity", "character_knowledge", "dialogue_pairing", "continuity", "shootability", "ending_hook", "previous_episode_bridge"
                    } else "other",
                    f"审核维度 {dimension} 标记为 error，不能由空 issues 覆盖。",
                    str(item.get("fix") or "按该维度的 draft_evidence 修复后重新审核。"),
                )
            )
        elif status == "warning" or severity == "warning":
            generated.append(
                _gate_issue(
                    f"DIMENSION-{dimension}",
                    "warning",
                    dimension if dimension in {
                        "source_fidelity", "character_knowledge", "dialogue_pairing", "continuity", "shootability", "ending_hook", "previous_episode_bridge"
                    } else "other",
                    f"审核维度 {dimension} 存在 warning，需要编剧判断。",
                    str(item.get("fix") or "由编剧决定是否调整。"),
                )
            )

    expected_quotes = required_quotes_for_context(context)
    quote_by_id = {_quote_key(item): item for item in _quote_entries(report)}
    for expected in expected_quotes:
        quote_id = str(expected["quote_id"])
        item = quote_by_id.get(quote_id)
        if not item:
            continue
        mode = expected.get("mode")
        status = item.get("status")
        failed = False
        severity = "error"
        if mode == "exact":
            failed = _norm(expected.get("quote", "")) not in _norm(draft_text) or status not in {"present", "exact_match"}
        elif mode == "semantic":
            failed = status in {"missing", "semantic_mismatch", "not_applicable"} or item.get("severity") == "error"
        else:
            failed = status in {"missing", "not_applicable"} or item.get("severity") == "error"
            severity = "warning" if item.get("severity") != "error" else "error"
        if failed:
            generated.append(
                _gate_issue(
                    f"QUOTE-{quote_id}",
                    severity,
                    "dialogue_pairing",
                    f"required quote {quote_id}（{mode}）未满足：status={status!r}。",
                    str(item.get("fix") or "按上下文逐条恢复或明确处理该台词义务。"),
                )
            )

    for item in (draft_quality or {}).get("hard_errors", []) or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "hard_error")
        generated.append(
            _gate_issue(
                f"SYSTEM-{code}",
                "error",
                "format" if "format" in code else "other",
                str(item.get("message") or f"确定性质量门禁 {code} 未通过。"),
                "先修复确定性质量错误，再重新审核草稿。",
            )
        )
    return generated


def derive_review_verdict(
    report: dict,
    context: dict | None = None,
    draft_text: str = "",
    draft_quality: dict | None = None,
) -> str:
    """Derive verdict from model issues plus deterministic gate issues."""
    issues = [item for item in (report.get("issues") or []) if isinstance(item, dict)]
    effective = issues + review_gate_issues(report, context, draft_text, draft_quality)
    severities = [str(item.get("severity", "")).lower() for item in effective]
    if "error" in severities:
        return "blocked"
    if "warning" in severities:
        return "warning"
    return "pass"


validate_review_report_completeness = validate_review_completeness
