"""Deterministic, draft-bound quality gates and advisory risk signals."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import sha256_text, stable_hash
from .duration_estimator import compute_draft_metrics
from .script_validator import parse_script
from .state_store import artifact_versions, read_artifact_version


RULESET_VERSION = "0.3.7"


def quality_config_hash(config: dict | None = None) -> str:
    return stable_hash({"ruleset_version": RULESET_VERSION, "config": config or {}})


def _norm_quote(value: str) -> str:
    # Exact means exact characters after the explicitly permitted whitespace
    # normalization.  Punctuation and wording remain significant.
    return re.sub(r"\s+", "", str(value or "")).replace("\r", "").replace("\n", "")


def _required_quotes(context: dict) -> list[dict]:
    brief = context.get("episode_execution_brief") or {}
    quotes = brief.get("required_quotes")
    if isinstance(quotes, list):
        return [q for q in quotes if isinstance(q, dict) and q.get("quote")]
    outline = context.get("episode_outline") or {}
    return [
        item
        for item in (outline.get("required_quotes", []) or [])
        if isinstance(item, dict) and item.get("quote")
    ]


def _hard_error(code: str, message: str, **extra: Any) -> dict:
    item = {"code": code, "message": message}
    item.update({key: value for key, value in extra.items() if value is not None})
    return item


def _risk(risk_id: str, label: str, observed: Any, evidence: list[str] | None = None) -> dict:
    return {
        "risk_id": risk_id,
        "label": label,
        "observed": observed,
        "evidence": evidence or [],
        "advisory_only": True,
    }


def _line_texts(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _planning_labels(context: dict) -> set[str]:
    labels = {"拦路审判", "胜负已定"}
    outline = context.get("episode_outline") or {}
    for item in outline.get("required_story_beats", []) or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("text") or "")
        if "：" in raw:
            labels.add(raw.split("：", 1)[0].strip())
        elif ":" in raw:
            labels.add(raw.split(":", 1)[0].strip())
    for item in outline.get("beat_plan", []) or []:
        if isinstance(item, dict) and item.get("function"):
            labels.add(str(item["function"]).strip())
    return {label for label in labels if label}


def _label_leakage(text: str, context: dict) -> list[dict]:
    errors: list[dict] = []
    labels = _planning_labels(context)
    for line_no, line in enumerate(text.splitlines(), start=1):
        if re.search(r"\bEP\d{3}\s*[-_]\s*[BO]\d+\b", line, re.IGNORECASE):
            errors.append(_hard_error("planning_label_leakage", "正文泄漏内部 Beat/Outcome ID", line=line_no))
        if re.search(r"付费点\s*\d*|paywall\s*\d*", line, re.IGNORECASE):
            errors.append(_hard_error("planning_label_leakage", "正文泄漏内部付费点标签", line=line_no))
        if line.lstrip().startswith("△") and ("：" in line or ":" in line):
            prefix = re.split(r"[：:]", line.lstrip()[1:], maxsplit=1)[0].strip()
            if prefix in labels:
                errors.append(
                    _hard_error(
                        "planning_label_leakage",
                        f"正文把内部规划标签“{prefix}”当作动作标题",
                        line=line_no,
                    )
                )
    return errors


def _risk_signals(text: str, parsed: dict, metrics: dict | None = None) -> list[dict]:
    lines = _line_texts(text)
    dialogues = [d for scene in parsed.get("scenes", []) for d in scene.get("dialogues", [])]
    actions = [a for scene in parsed.get("scenes", []) for a in scene.get("actions", [])]
    dialogue_count = len(dialogues)
    os_count = sum(1 for item in dialogues if item.get("delivery") in ("OS", "VO", "内心", "自言自语"))
    short_count = sum(1 for item in dialogues if len(str(item.get("text") or "")) <= 6)
    question_lines = [item for item in dialogues if str(item.get("text") or "").rstrip().endswith(("？", "?"))]
    question_without_response: list[str] = []
    for question in question_lines:
        later = [d for d in dialogues if d.get("line", 0) > question.get("line", 0)]
        if not any(d.get("speaker") != question.get("speaker") for d in later[:2]):
            question_without_response.append(f"line {question.get('line')}")
    summary_markers = ("随后", "后来", "之后", "一转眼", "数日后", "很快", "众人得知", "事情就这样")
    summary_lines = [f"line {item.get('line')}" for item in actions if any(token in item.get("text", "") for token in summary_markers)]
    telegraphic = [f"line {item.get('line')}" for item in dialogues if 0 < len(str(item.get("text") or "")) <= 3]
    missing_reaction = [
        f"scene {scene.get('episode')}-{scene.get('scene_no')}"
        for scene in parsed.get("scenes", [])
        if scene.get("dialogues") and not scene.get("actions")
    ]
    signals = [
        _risk("os_ratio", "OS/旁白比例", round(os_count / max(1, dialogue_count), 3), [f"{os_count}/{dialogue_count}"]),
        _risk("short_sentence_ratio", "短句比例", round(short_count / max(1, dialogue_count), 3), [f"{short_count}/{dialogue_count}"]),
        _risk("question_without_response", "疑似问句无回应", len(question_without_response), question_without_response),
        _risk("summary_action", "疑似概述动作", len(summary_lines), summary_lines),
        _risk("telegraphic_dialogue", "疑似电报式对话", len(telegraphic), telegraphic),
        _risk("missing_visible_reaction", "疑似缺少人物反应", len(missing_reaction), missing_reaction),
    ]
    if metrics:
        signals.append(
            _risk(
                "duration_deviation",
                "时长偏差",
                metrics.get("deviation"),
                [f"estimated_seconds={metrics.get('estimated_seconds')}", f"preferred={metrics.get('preferred_seconds')}"],
            )
        )
    return signals


def compute_draft_quality(
    draft_text: str,
    context: dict,
    *,
    draft_version: str,
    draft_hash: str | None = None,
    config: dict | None = None,
    format_report: dict | None = None,
    draft_metrics: dict | None = None,
) -> dict:
    """Calculate hard gates and non-blocking signals for one exact draft."""
    draft_hash = draft_hash or sha256_text(draft_text)
    format_report = format_report or {}
    context_hash = str(context.get("context_hash") or "")
    hard_errors: list[dict] = []
    if not context_hash:
        hard_errors.append(_hard_error("context_hash_missing", "草稿质量缺少 context_hash"))
    if not draft_version:
        hard_errors.append(_hard_error("draft_version_missing", "草稿质量缺少 draft_version"))
    if not draft_hash:
        hard_errors.append(_hard_error("draft_hash_missing", "草稿质量缺少 draft_hash"))
    if format_report.get("errors"):
        for item in format_report.get("errors", []) or []:
            hard_errors.append(
                _hard_error(
                    "format_error",
                    str(item.get("message") or item),
                    line=item.get("line") if isinstance(item, dict) else None,
                )
            )
    parsed = format_report.get("parsed") if isinstance(format_report.get("parsed"), dict) else parse_script(draft_text)
    if not parsed.get("scenes"):
        hard_errors.append(_hard_error("no_scenes", "剧本没有可执行场次"))
    for scene in parsed.get("scenes", []) or []:
        if not scene.get("actions") and not scene.get("dialogues"):
            hard_errors.append(_hard_error("empty_scene", "存在空场次", line=scene.get("line")))
    for quote in _required_quotes(context):
        mode = quote.get("mode") or quote.get("quote_mode") or "legacy_unspecified"
        if mode == "exact" and _norm_quote(str(quote.get("quote"))) not in _norm_quote(draft_text):
            hard_errors.append(
                _hard_error(
                    "exact_quote_missing",
                    f"缺少 exact required quote：{quote.get('quote')}",
                    quote=quote.get("quote"),
                )
            )
    hard_errors.extend(_label_leakage(draft_text, context))
    if draft_metrics is None:
        outline = context.get("episode_outline", {}) or {}
        draft_metrics = compute_draft_metrics(
            draft_text,
            episode=int(context.get("episode") or outline.get("episode") or 1),
            context_hash=context_hash,
            draft_version=draft_version,
            draft_hash=draft_hash,
            preferred_seconds=outline.get("suggested_seconds"),
        )
    return {
        "quality_version": RULESET_VERSION,
        "episode": context.get("episode"),
        "context_hash": context_hash,
        "draft_version": draft_version,
        "draft_hash": draft_hash,
        "ruleset_version": RULESET_VERSION,
        "quality_config_hash": quality_config_hash(config),
        "format_ok": not bool(format_report.get("errors")),
        "hard_errors": hard_errors,
        "risk_signals": _risk_signals(draft_text, parsed, draft_metrics),
        "advisory_only": False,
        "draft_metrics_hash": stable_hash(draft_metrics),
    }


def load_bound_draft_quality(project_dir: Path, episode: int, draft_version: str, draft_hash: str) -> dict:
    for record in artifact_versions(project_dir, "draft_quality", episode):
        data = read_artifact_version(project_dir, "draft_quality", episode, record["version"])
        if isinstance(data, dict) and data.get("draft_version") == draft_version and data.get("draft_hash") == draft_hash:
            return data
    raise KeyError(f"第{episode}集草稿 {draft_version}/{draft_hash[:12]} 没有绑定 draft_quality")


def quality_is_blocked(quality: dict) -> bool:
    return bool(quality.get("hard_errors"))
