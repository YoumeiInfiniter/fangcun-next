"""Draft-first script workflow helpers for fangcun-drama."""

import json
import shutil
from pathlib import Path


def ensure_script_scene_keys(content: str, *, label: str = "script") -> None:
    """Hard gate: adjacent scene headings with same scene key must be merged."""
    try:
        from story_structure_guardrails import validate_script_scene_keys
    except Exception:
        try:
            from .story_structure_guardrails import validate_script_scene_keys
        except Exception as exc:
            raise RuntimeError(f"scene key 分场校验器加载失败，禁止处理 {label}：{exc}") from exc
    report = validate_script_scene_keys(content)
    if report.get("ok") is False:
        messages = []
        for item in report.get("issues", []):
            messages.append(
                f"{label}: {item.get('previous_scene')}→{item.get('current_scene')} "
                f"scene_key={item.get('scene_key')} line {item.get('previous_line')}->{item.get('current_line')}"
            )
        raise ValueError("剧本分场 scene key 门禁未通过，禁止推进：" + "；".join(messages))


def get_drafts_dir(output_dir: str) -> Path:
    return Path(output_dir) / "drafts"


def format_batch_id(batch_num: int) -> str:
    return f"batch_{batch_num:03d}"


def get_batch_dir(output_dir: str, batch_id: str) -> Path:
    return get_drafts_dir(output_dir) / batch_id


def get_draft_path(output_dir: str, batch_id: str, episode_num: int) -> Path:
    return get_batch_dir(output_dir, batch_id) / f"ep_{episode_num:03d}.txt"


def save_draft(output_dir: str, batch_id: str, episode_num: int, content: str) -> Path:
    ensure_script_scene_keys(content, label=f"draft {batch_id}/EP{episode_num:03d}")
    path = get_draft_path(output_dir, batch_id, episode_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def load_draft(output_dir: str, batch_id: str, episode_num: int) -> str:
    path = get_draft_path(output_dir, batch_id, episode_num)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _review_paths(output_dir: str, batch_id: str, episode_num: int) -> tuple[Path, Path]:
    base = get_batch_dir(output_dir, batch_id) / "reviews"
    return base / f"ep_{episode_num:03d}_review.json", base / f"ep_{episode_num:03d}_review.md"


def _as_non_empty_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    try:
        items = list(value)
    except TypeError:
        items = [str(value)]
    return [str(item).strip() for item in items if str(item).strip()]


def _has_concrete_review_reason(normalized: dict) -> bool:
    """Return True when a review report contains reasons beyond a bare rating.

    Requirement 0002:评级只能作为入口，审核有效性必须看具体原因。
    A report that only says pass/warning/blocked, A/B/C/D, or leaves every issue
    bucket empty is not enough for regression judgment or rewrite decisions.
    """
    reason_fields = (
        "severe_issues",
        "non_blocking_issues",
        "continuity_issues",
        "format_issues",
        "rewrite_instructions",
    )
    if any(normalized.get(field) for field in reason_fields):
        return True
    summary = str(normalized.get("summary", "")).strip()
    if not summary:
        return False
    rating_only = {"a", "b", "c", "d", "pass", "passed", "warning", "blocked", "通过", "警告", "阻塞"}
    return summary.lower() not in rating_only and len(summary) >= 8


def normalize_review_report(report: dict) -> dict:
    normalized = {
        "verdict": report.get("verdict", "warning"),
        "severe_issues": _as_non_empty_text_list(report.get("severe_issues", [])),
        "non_blocking_issues": _as_non_empty_text_list(report.get("non_blocking_issues", [])),
        "continuity_issues": _as_non_empty_text_list(report.get("continuity_issues", [])),
        "format_issues": _as_non_empty_text_list(report.get("format_issues", [])),
        "rewrite_instructions": _as_non_empty_text_list(report.get("rewrite_instructions", [])),
        "summary": str(report.get("summary", "")).strip(),
    }
    if not _has_concrete_review_reason(normalized):
        normalized["verdict"] = "blocked"
        normalized["severe_issues"].append("审核报告缺少具体原因：不能只给评级/结论，必须说明扣分原因、阻塞项或修改建议。")
        normalized["rewrite_instructions"].append("重新审核本集，补充至少三条具体原因，并说明是否阻塞交付。")
        if not normalized["summary"]:
            normalized["summary"] = "审核无效：缺少具体原因。"
    return normalized


def _issue_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- None"]


def review_report_to_markdown(episode_num: int, report: dict) -> str:
    r = normalize_review_report(report)
    lines = [
        f"# EP{episode_num:03d} AI Review",
        "",
        f"- Verdict: {r['verdict']}",
        f"- Summary: {r['summary']}",
        "",
        "## Severe Issues",
        *_issue_lines(r["severe_issues"]),
        "",
        "## Non-Blocking Issues",
        *_issue_lines(r["non_blocking_issues"]),
        "",
        "## Continuity Issues",
        *_issue_lines(r["continuity_issues"]),
        "",
        "## Format Issues",
        *_issue_lines(r["format_issues"]),
        "",
        "## Rewrite Instructions",
        *_issue_lines(r["rewrite_instructions"]),
        "",
    ]
    return "\n".join(lines)


def save_review_report(output_dir: str, batch_id: str, episode_num: int, report: dict) -> tuple[Path, Path]:
    normalized = normalize_review_report(report)
    json_path, md_path = _review_paths(output_dir, batch_id, episode_num)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(review_report_to_markdown(episode_num, normalized), encoding="utf-8")
    return json_path, md_path


def load_review_report(output_dir: str, batch_id: str, episode_num: int) -> dict:
    json_path, _ = _review_paths(output_dir, batch_id, episode_num)
    if not json_path.exists():
        return normalize_review_report({})
    return normalize_review_report(json.loads(json_path.read_text(encoding="utf-8")))


def is_review_blocked(report: dict) -> bool:
    normalized = normalize_review_report(report)
    return normalized["verdict"] == "blocked" or bool(normalized["severe_issues"])


def get_pass_marker_path(output_dir: str, batch_id: str, episode_num: int) -> Path:
    """Path to the .pass marker file for a reviewed episode."""
    return get_batch_dir(output_dir, batch_id) / "reviews" / f"ep_{episode_num:03d}.pass"


def is_episode_passed(output_dir: str, batch_id: str, episode_num: int) -> bool:
    """Check if an episode has a .pass marker (review already passed)."""
    return get_pass_marker_path(output_dir, batch_id, episode_num).exists()


def mark_episode_passed(output_dir: str, batch_id: str, episode_num: int):
    """Write .pass marker after successful review."""
    p = get_pass_marker_path(output_dir, batch_id, episode_num)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("pass", encoding="utf-8")


def clear_episode_passed(output_dir: str, batch_id: str, episode_num: int):
    """Remove .pass marker (e.g. after manual edit requiring re-review)."""
    p = get_pass_marker_path(output_dir, batch_id, episode_num)
    if p.exists():
        p.unlink()


def get_batch_pending_path(output_dir: str, batch_id: str) -> Path:
    """Path to the .pending lock file for a batch awaiting human confirmation."""
    return get_batch_dir(output_dir, batch_id) / f"{batch_id}.pending"


def is_batch_pending_confirmation(output_dir: str, batch_id: str) -> bool:
    """Check if a batch is waiting for human confirmation."""
    return get_batch_pending_path(output_dir, batch_id).exists()


def mark_batch_pending(output_dir: str, batch_id: str):
    """Write .pending lock after batch completes."""
    p = get_batch_pending_path(output_dir, batch_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("pending human confirmation", encoding="utf-8")


def clear_batch_pending(output_dir: str, batch_id: str):
    """Remove .pending lock after human confirms."""
    p = get_batch_pending_path(output_dir, batch_id)
    if p.exists():
        p.unlink()


def save_rewrite_attempt(output_dir: str, batch_id: str, episode_num: int, attempt_num: int, content: str) -> Path:
    path = get_batch_dir(output_dir, batch_id) / "rewrites" / f"ep_{episode_num:03d}_attempt_{attempt_num:02d}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _continuity_path(output_dir: str, batch_id: str | None = None) -> Path:
    if batch_id:
        return get_batch_dir(output_dir, batch_id) / "continuity_state.json"
    return Path(output_dir) / "continuity_state.json"


def load_continuity_state(output_dir: str, batch_id: str | None = None) -> dict:
    path = _continuity_path(output_dir, batch_id)
    if not path.exists():
        return {"version": 1, "episodes": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_continuity_state(output_dir: str, state: dict, batch_id: str | None = None) -> Path:
    path = _continuity_path(output_dir, batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_batch_summary(output_dir: str, batch_id: str, episodes: list[int], review_reports: dict[int, dict]) -> Path:
    path = get_batch_dir(output_dir, batch_id) / "batch_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Draft Batch {batch_id}",
        "",
        "## Episodes",
    ]
    for ep in episodes:
        raw_report = review_reports.get(ep, {})
        if not raw_report and is_episode_passed(output_dir, batch_id, ep):
            raw_report = {
                "verdict": "passed",
                "summary": "本集已通过本地格式校验并写入 pass 标记；本批次跳过 AI 复审。",
                "non_blocking_issues": ["跳过 AI 复审时仅代表本地格式/门禁通过，仍需编剧人工确认内容质量。"],
            }
        report = normalize_review_report(raw_report)
        lines.append(f"- ep_{ep:03d}.txt: {report['verdict']}")
        for issue in report["severe_issues"] + report["non_blocking_issues"]:
            lines.append(f"  - {issue}")
    lines.extend([
        "",
        "## Writer Actions",
        "- Confirm: `python tools/pipeline.py --config {config} --confirm-draft-batch`",
        "- Rewrite one episode: `python tools/pipeline.py --config {config} --rewrite-draft --episode N`",
        "- Review edited draft: `python tools/pipeline.py --config {config} --review-draft --episode N`",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def promote_batch_to_scripts(output_dir: str, batch_id: str, episodes: list[int]) -> list[Path]:
    scripts_dir = Path(output_dir) / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    promoted = []
    for episode_num in episodes:
        source = get_draft_path(output_dir, batch_id, episode_num)
        ensure_script_scene_keys(source.read_text(encoding="utf-8"), label=f"draft {batch_id}/EP{episode_num:03d}")
        target = scripts_dir / f"ep_{episode_num:03d}.txt"
        shutil.copyfile(source, target)
        promoted.append(target)
    return promoted
