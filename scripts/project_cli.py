#!/usr/bin/env python3
"""Fangcun Next project CLI (deterministic entry point).

Every command works through files and a shared project directory, so it can
be driven by any Agent platform (Codex, Claude Code, Cursor, OpenClaw) or by
the bundled console script. Host Agent Mode prints prompt bundles for the
agent to consume; API Mode calls the configured model with the same
episode_context.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .common import atomic_write_json, ensure_dir, now_iso, read_json, slugify
from .schema_validate import SchemaValidationError, ensure_valid
from .state_store import (
    active_artifact_path,
    init_project,
    load_config,
    load_continuity,
    project_status,
    record_artifact,
    save_config,
)


class CliError(Exception):
    """Expected command failure with a user-facing message."""


def _project_dir(args) -> Path:
    value = getattr(args, "dir", None) or os.environ.get("FANGCUN_PROJECT_DIR", "")
    if not value:
        raise CliError("缺少 --dir 参数（或设置 FANGCUN_PROJECT_DIR）")
    return Path(value).expanduser().resolve()


def _print_bundle(path: Path) -> None:
    print(f"上下文包已写入：{path}")
    print("---BEGIN BUNDLE---")
    print(path.read_text(encoding="utf-8"))
    print("---END BUNDLE---")


def _load_json_file(path: Path, label: str) -> Any:
    if not path.exists():
        raise CliError(f"{label}不存在：{path}")
    try:
        return read_json(path)
    except json.JSONDecodeError as exc:
        raise CliError(f"{label}不是合法 JSON：{path}（{exc}）")


def cmd_init(args) -> int:
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    if config_path:
        config = _load_json_file(config_path, "配置文件")
    else:
        config = {
            "project_id": slugify(args.project_id or "project"),
            "novel_name": args.novel_name or "未命名小说",
            "drama_name": args.drama_name or "未命名短剧",
            "platform": args.platform or "竖屏短剧",
            "aspect_ratio": args.aspect_ratio or "9:16",
            "genre": [g for g in (args.genre or "").split(",") if g.strip()] or ["未指定"],
            "initial_episode_count": args.episodes,
            "minimum_episode_seconds": args.minimum_episode_seconds,
            "writer_has_final_authority": True,
        }
    config = {k: v for k, v in config.items() if v is not None}
    try:
        ensure_valid(config, "project-config.schema.json")
    except SchemaValidationError as exc:
        raise CliError("项目配置未通过 Schema 校验：\n" + "\n".join(exc.messages))

    project_dir = _project_dir(args) if args.dir else Path(args.projects or "projects") / config["project_id"]
    result = init_project(project_dir, config, source="cli")
    if args.brief:
        brief_path = project_dir / "state" / "project_brief_input.md"
        ensure_dir(brief_path.parent)
        brief_path.write_text(str(args.brief) + "\n", encoding="utf-8")
    print(f"{'复用' if not result['created'] else '创建'}项目：{project_dir}")
    print(f"配置：{project_dir / 'config.json'}")
    if args.brief:
        print(f"编剧需求原文：{brief_path}（下一步：generate-requirements 整理为结构化需求）")
    return 0


def cmd_generate_requirements(args) -> int:
    project_dir = _project_dir(args)
    config = load_config(project_dir)
    from .prompt_router import render_prompt_bundle

    brief_input = project_dir / "state" / "project_brief_input.md"
    input_text = brief_input.read_text(encoding="utf-8") if brief_input.exists() else "（未提供原始需求，请与编剧确认）"
    context = {
        "episode": 0,
        "context_hash": "project-requirements",
        "project_brief": config,
        "episode_outline": {},
        "source_evidence": {"chapter_ids": [], "events": [], "quotes": [], "raw_excerpts": []},
        "continuity_state": {},
        "previous_approved_script": None,
        "writer_overrides": [],
        "selected_craft_modules": [],
        "format_profile": config.get("script_format", "default-cn"),
        "advisory_timing": {},
    }
    bundle = render_prompt_bundle(context, role="requirements", config=config)
    bundle += f"\n\n## 编剧原始需求\n{input_text}\n"
    path = project_dir / "state" / "prompt_bundles" / "stage_requirements.md"
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    _print_bundle(path)
    return 0


def cmd_save_requirements(args) -> int:
    project_dir = _project_dir(args)
    config = _load_json_file(Path(args.file), "需求 JSON")
    ensure_valid(config, "project-config.schema.json")
    save_config(project_dir, config, source="writer", note="requirements confirmed")
    from .format_renderer import render_project_brief_markdown

    md_path = project_dir / "artifacts" / "project_brief" / "brief.md"
    ensure_dir(md_path.parent)
    md_path.write_text(render_project_brief_markdown(config), encoding="utf-8")
    record_artifact(project_dir, "project_brief", md_path, source="writer", status="approved")
    print(f"需求已保存：{md_path}")
    return 0


def cmd_ingest_source(args) -> int:
    project_dir = _project_dir(args)
    from .source_ingest import ingest_novel

    result = ingest_novel(project_dir, Path(args.file).expanduser().resolve(), overwrite=args.overwrite)
    print(f"原文归档：{result['created'] and '新建' or '复用'}，共 {result['chapters']} 个章节单元")
    print(f"章节索引：{project_dir / 'source' / 'index.json'}")
    return 0


def cmd_save_events(args) -> int:
    project_dir = _project_dir(args)
    data = _load_json_file(Path(args.file), "事件资产")
    events = data.get("events", data) if isinstance(data, dict) else data
    if not isinstance(events, list):
        raise CliError("事件资产必须是数组或含 events 数组的对象")
    for event in events:
        try:
            ensure_valid(event, "source-event.schema.json")
        except SchemaValidationError as exc:
            raise CliError(f"事件 {event.get('event_id', '?')} 未通过 Schema：\n" + "\n".join(exc.messages))
    target = project_dir / "artifacts" / "source_events" / "events.json"
    ensure_dir(target.parent)
    atomic_write_json(target, events)
    record_artifact(project_dir, "source_events", target, source="ai", status="approved")
    print(f"事件资产已保存：{target}（{len(events)} 个事件）")
    return 0


def cmd_estimate_capacity(args) -> int:
    project_dir = _project_dir(args)
    from .capacity_estimator import save_forecast

    forecast = save_forecast(project_dir)
    print(json.dumps(forecast, ensure_ascii=False, indent=2))
    return 0


def _stage_bundle(project_dir: Path, role: str, extra: str = "") -> Path:
    from .prompt_router import render_prompt_bundle

    config = load_config(project_dir)
    context = {
        "episode": 0,
        "context_hash": f"stage:{role}",
        "project_brief": config,
        "episode_outline": {},
        "source_evidence": {"chapter_ids": [], "events": [], "quotes": [], "raw_excerpts": []},
        "continuity_state": load_continuity(project_dir),
        "previous_approved_script": None,
        "writer_overrides": [],
        "selected_craft_modules": [],
        "format_profile": config.get("script_format", "default-cn"),
        "advisory_timing": {},
    }
    bundle = render_prompt_bundle(context, role=role, config=config)
    if extra:
        bundle += "\n\n## 上游产物\n" + extra
    path = project_dir / "state" / "prompt_bundles" / f"stage_{role}.md"
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    return path


def _require_artifact_text(project_dir: Path, kind: str, label: str) -> str:
    path = active_artifact_path(project_dir, kind)
    if not path or not path.exists():
        raise CliError(f"缺少前置产物：{label}（未找到 {kind}）")
    return path.read_text(encoding="utf-8")


def cmd_generate_adaptation(args) -> int:
    project_dir = _project_dir(args)
    events = _require_artifact_text(project_dir, "source_events", "原文事件资产")
    forecast_path = active_artifact_path(project_dir, "capacity_forecast")
    extra = f"事件资产：\n{events}"
    if forecast_path and forecast_path.exists():
        extra += f"\n\n容量预估：\n{forecast_path.read_text(encoding='utf-8')}"
    _print_bundle(_stage_bundle(project_dir, "adaptation", extra))
    return 0


def cmd_generate_story_outline(args) -> int:
    project_dir = _project_dir(args)
    adaptation = _require_artifact_text(project_dir, "adaptation_strategy", "改编指引")
    events = _require_artifact_text(project_dir, "source_events", "原文事件资产")
    _print_bundle(_stage_bundle(project_dir, "story_outline", f"改编指引：\n{adaptation}\n\n事件资产：\n{events}"))
    return 0


def cmd_generate_episode_outline(args) -> int:
    project_dir = _project_dir(args)
    outline_text = _require_artifact_text(project_dir, "story_outline", "故事大纲")
    events = _require_artifact_text(project_dir, "source_events", "原文事件资产")
    _print_bundle(_stage_bundle(project_dir, "episode_outline", f"故事大纲：\n{outline_text}\n\n事件资产：\n{events}"))
    return 0


def _save_stage_text(project_dir: Path, kind: str, file: Path, summary_file: str | None, summary_schema: str) -> None:
    file = Path(file).expanduser().resolve()
    if not file.exists():
        raise CliError(f"产物文件不存在：{file}")
    target_dir = project_dir / "artifacts" / kind
    ensure_dir(target_dir)
    target = target_dir / file.name
    target.write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
    record_artifact(project_dir, kind, target, source="ai", status="approved")
    if summary_file:
        summary = _load_json_file(Path(summary_file), "结构化摘要")
        if summary_schema:
            ensure_valid(summary, summary_schema)
        summary_target = target_dir / f"{target.stem}.summary.json"
        atomic_write_json(summary_target, summary)
        record_artifact(project_dir, kind, summary_target, source="ai", status="approved")
    print(f"{kind} 已保存：{target}")


def cmd_save_adaptation(args) -> int:
    project_dir = _project_dir(args)
    _save_stage_text(project_dir, "adaptation_strategy", Path(args.file), args.summary_file, None)
    return 0


def cmd_save_story_outline(args) -> int:
    project_dir = _project_dir(args)
    _save_stage_text(project_dir, "story_outline", Path(args.file), args.summary_file, None)
    return 0


def cmd_save_episode_outline(args) -> int:
    project_dir = _project_dir(args)
    data = _load_json_file(Path(args.outline_json), "集纲 JSON")
    if isinstance(data, dict) and "episode" in data and "episodes" not in data:
        episodes = [data]
    else:
        episodes = data.get("episodes", data) if isinstance(data, dict) else data
    if not isinstance(episodes, list) or not episodes:
        raise CliError("集纲必须是数组或含 episodes 数组的对象")
    seen: set[int] = set()
    for outline in episodes:
        ep = outline.get("episode")
        if ep in seen:
            raise CliError(f"集数重复：第{ep}集")
        seen.add(ep)
        try:
            ensure_valid(outline, "episode-outline.schema.json")
        except SchemaValidationError as exc:
            raise CliError(f"第{ep}集未通过 Schema：\n" + "\n".join(exc.messages))
    target = project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
    ensure_dir(target.parent)
    atomic_write_json(target, {"episodes": episodes})
    record_artifact(project_dir, "episode_outline", target, source="ai", status="approved")
    if args.outline_md:
        md_path = Path(args.outline_md).expanduser().resolve()
        if md_path.exists():
            md_target = project_dir / "artifacts" / "episode_outline" / "episode_outline.md"
            md_target.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"集纲已保存：{target}（{len(episodes)} 集）")
    return 0


def cmd_get_episode_context(args) -> int:
    project_dir = _project_dir(args)
    from .context_builder import build_episode_context
    from .prompt_router import render_prompt_bundle

    role = args.role
    context = build_episode_context(
        project_dir,
        args.episode,
        role=role,
        max_source_chars=args.max_source_chars,
        per_chapter_budget=args.per_chapter_budget,
    )
    context["context_file"] = str(context.get("context_file", project_dir / "state" / "episode_contexts" / f"episode_context_EP{args.episode:03d}.json"))
    bundle = render_prompt_bundle(context, role=role, config=context["project_brief"])
    path = project_dir / "state" / "prompt_bundles" / f"ep{args.episode:03d}_{role}.md"
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    print(f"episode_context：{context['context_file']}")
    print(f"context_hash：{context['context_hash']}")
    print(f"Prompt 包：{path}")
    print(f"Craft 模块：{context['selected_craft_modules']}")
    if context["completeness"]["warnings"]:
        for warning in context["completeness"]["warnings"]:
            print(f"警告：{warning}")
    return 0


def cmd_save_draft(args) -> int:
    project_dir = _project_dir(args)
    from .script_validator import validate_script

    config = load_config(project_dir)
    content = Path(args.file).expanduser().resolve()
    if not content.exists():
        raise CliError(f"草稿文件不存在：{content}")
    text = content.read_text(encoding="utf-8")
    report = validate_script(text, format_profile=config.get("script_format", "default-cn"), expected_episode=args.episode)
    if not report["ok"]:
        raise CliError("草稿格式未通过：\n" + "\n".join(f"- {e['message']}" for e in report["errors"][:10]))
    versions_dir = project_dir / "artifacts" / "script_drafts" / f"ep{args.episode:03d}"
    ensure_dir(versions_dir)
    count = len(list(versions_dir.glob("*.txt"))) + 1
    target = versions_dir / f"ep{args.episode:03d}_v{count:03d}.txt"
    target.write_text(text, encoding="utf-8")
    record_artifact(project_dir, "script_draft", target, episode=args.episode, source="ai", status="draft")
    print(f"草稿已保存：{target}")
    print(f"下一步：review --episode {args.episode}")
    return 0


def _review_bundle_path(project_dir: Path, episode: int) -> Path:
    return project_dir / "state" / "prompt_bundles" / f"ep{episode:03d}_reviewer.md"


def _load_context_snapshot(project_dir: Path, episode: int) -> dict:
    from .context_builder import context_path, verify_context_hash

    path = context_path(project_dir, episode)
    if not path.exists():
        raise CliError(f"缺少 episode_context 快照：{path}。请先运行 get-episode-context --episode {episode}")
    context = _load_json_file(path, "episode_context")
    ok, _ = verify_context_hash(context)
    if not ok:
        raise CliError(f"episode_context 哈希校验失败，拒绝使用：{path}")
    return context


def cmd_review(args) -> int:
    project_dir = _project_dir(args)
    from .prompt_router import render_prompt_bundle
    from .script_validator import validate_script

    config = load_config(project_dir)
    draft = active_artifact_path(project_dir, "script_draft", args.episode)
    if not draft or not draft.exists():
        raise CliError(f"第{args.episode}集没有草稿，请先 save-draft")
    draft_text = draft.read_text(encoding="utf-8")
    report = validate_script(draft_text, format_profile=config.get("script_format", "default-cn"), expected_episode=args.episode)
    if not report["ok"]:
        raise CliError("草稿格式未通过，请先修复：\n" + "\n".join(f"- {e['message']}" for e in report["errors"][:10]))

    context = _load_context_snapshot(project_dir, args.episode)
    review_context = {**context, "script_draft": draft_text}
    bundle = render_prompt_bundle(review_context, role="reviewer", config=config)
    bundle += f"\n\n## 待审草稿\n{draft_text}\n"
    path = _review_bundle_path(project_dir, args.episode)
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    print(f"审核上下文包已写入：{path}（context_hash={context['context_hash']}）")
    if args.api:
        from .model_adapter import call_generate
        from .model_adapter import parse_json_response
        from .schema_validate import validate

        text = call_generate(
            stage="review",
            system_prompt=path.read_text(encoding="utf-8"),
            user_context="请按 review-report.schema.json 输出审核 JSON。",
            output_contract="review-report.schema.json",
            model_config=config.get("model_config"),
            temperature=0.2,
        )
        report_data = _normalize_review_report(parse_json_response(text))
        ok, errors = validate(report_data, "review-report.schema.json")
        if not ok:
            raise CliError("模型审核输出未通过 Schema：" + "; ".join(errors))
        _save_review(project_dir, args.episode, report_data, context["context_hash"])
    else:
        print("Host Agent Mode：请阅读该上下文包，按 review-report.schema.json 输出审核 JSON，然后用 save-review 保存。")
    return 0


def _save_review(project_dir: Path, episode: int, report_data: dict, context_hash: str) -> None:
    report_data = _normalize_review_report(report_data)
    report_data["episode"] = episode
    report_data["context_hash"] = context_hash
    ensure_valid(report_data, "review-report.schema.json")
    for issue in report_data.get("issues", []) or []:
        if issue.get("severity") == "error" and not (issue.get("source_evidence") or issue.get("adaptation_basis")):
            raise CliError(f"error 问题 {issue.get('id')} 缺少 source_evidence 或 adaptation_basis，拒绝保存")
    target_dir = project_dir / "artifacts" / "reviews"
    ensure_dir(target_dir)
    target = target_dir / f"ep{episode:03d}_review.json"
    atomic_write_json(target, report_data)
    record_artifact(project_dir, "review", target, episode=episode, source="ai", status="approved")
    print(f"审核报告已保存：{target}")
    print(f"结论：{report_data.get('verdict')} | {report_data.get('summary')}")
    print(f"问题数：{len(report_data.get('issues', []))}")


def _normalize_verdict(verdict: Any, issues: list[dict] | None) -> str:
    """Map model verdicts onto review-report schema; infer from severity."""
    mapping = {
        "pass": "pass",
        "通过": "pass",
        "ok": "pass",
        "warning": "warning",
        "警告": "warning",
        "blocked": "blocked",
        "阻塞": "blocked",
        "needs_revision": "blocked",
        "revision": "blocked",
        "block": "blocked",
    }
    raw = str(verdict or "").strip().lower()
    if raw in mapping:
        return mapping[raw]
    severities = [str(i.get("severity", "")).lower() for i in (issues or [])]
    if "error" in severities:
        return "blocked"
    if "warning" in severities:
        return "warning"
    return "pass"


VALID_REVIEW_CATEGORIES = {
    "source_fidelity",
    "outline_adherence",
    "causality",
    "character_knowledge",
    "dialogue_pairing",
    "character_voice",
    "previous_episode_bridge",
    "ending_hook",
    "continuity",
    "shootability",
    "timing",
    "format",
    "other",
}

REVIEW_CATEGORY_ALIASES = {
    "causal-chain": "causality",
    "causal_chain": "causality",
    "causality": "causality",
    "dialogue-connection": "dialogue_pairing",
    "dialogue_connection": "dialogue_pairing",
    "dialogue-pairing": "dialogue_pairing",
    "dialogue_anchor": "dialogue_pairing",
    "dialogue-anchor": "dialogue_pairing",
    "dialogue": "dialogue_pairing",
    "character-knowledge": "character_knowledge",
    "knowledge": "character_knowledge",
    "continuity": "continuity",
    "duration": "timing",
    "timing": "timing",
    "format": "format",
    "format-check": "format",
    "format_check": "format",
    "fidelity": "source_fidelity",
    "source-fidelity": "source_fidelity",
    "source": "source_fidelity",
    "outline-adherence": "outline_adherence",
    "outline": "outline_adherence",
    "episode-goal": "outline_adherence",
    "voice": "character_voice",
    "character-voice": "character_voice",
    "bridge": "previous_episode_bridge",
    "previous-episode-bridge": "previous_episode_bridge",
    "hook": "ending_hook",
    "ending-hook": "ending_hook",
    "ending_hook": "ending_hook",
    "shootability": "shootability",
}


def _normalize_review_report(data: dict) -> dict:
    """Unwrap wrappers, map categories/verdicts, enforce evidence rules."""
    if isinstance(data.get("review_report"), dict):
        data = data["review_report"]
    issues = data.get("issues") or []
    normalized: list[dict] = []
    for idx, issue in enumerate(issues, start=1):
        if not isinstance(issue, dict):
            continue
        raw_category = str(issue.get("category") or "other").strip().lower().replace(" ", "-")
        category = REVIEW_CATEGORY_ALIASES.get(raw_category, raw_category)
        if category not in VALID_REVIEW_CATEGORIES:
            category = "other"
        severity = str(issue.get("severity") or "warning").strip().lower()
        if severity not in ("error", "warning", "suggestion"):
            severity = "warning"
        item = {
            "id": str(issue.get("id") or f"REVIEW-{idx:03d}"),
            "severity": severity,
            "category": category,
            "problem": str(issue.get("problem") or issue.get("detail") or "").strip(),
        }
        for key in ("location", "source_evidence", "adaptation_basis", "fix"):
            value = issue.get(key)
            if value not in (None, ""):
                item[key] = value
        if item["severity"] == "error" and not (item.get("source_evidence") or item.get("adaptation_basis")):
            item["severity"] = "warning"
            item["problem"] = item["problem"] + "（原 error 缺少证据，自动降级为 warning）"
        if item["problem"]:
            normalized.append(item)
    data["issues"] = normalized
    data["verdict"] = _normalize_verdict(data.get("verdict"), normalized)
    if not str(data.get("summary") or "").strip():
        data["summary"] = "模型未提供摘要，请以问题清单为准。"
    return data


def cmd_save_review(args) -> int:
    project_dir = _project_dir(args)
    report_data = _load_json_file(Path(args.file), "审核报告")
    context = _load_context_snapshot(project_dir, args.episode)
    if report_data.get("context_hash") and report_data["context_hash"] != context["context_hash"]:
        raise CliError("审核报告 context_hash 与当前 episode_context 不一致，拒绝保存")
    _save_review(project_dir, args.episode, report_data, context["context_hash"])
    return 0


def cmd_rewrite(args) -> int:
    project_dir = _project_dir(args)
    from .prompt_router import render_prompt_bundle

    config = load_config(project_dir)
    review = active_artifact_path(project_dir, "review", args.episode)
    if not review or not review.exists():
        raise CliError(f"第{args.episode}集没有审核报告，请先 review/save-review")
    review_data = _load_json_file(review, "审核报告")
    context = _load_context_snapshot(project_dir, args.episode)
    if review_data.get("context_hash") and review_data["context_hash"] != context["context_hash"]:
        raise CliError("审核报告 context_hash 与当前 episode_context 不一致，拒绝重写")
    draft = active_artifact_path(project_dir, "script_draft", args.episode)
    draft_text = draft.read_text(encoding="utf-8") if draft and draft.exists() else ""
    rewrite_context = {**context, "script_draft": draft_text, "review_report": review_data}
    bundle = render_prompt_bundle(rewrite_context, role="rewriter", config=config)
    bundle += f"\n\n## 当前草稿\n{draft_text}\n\n## 审核报告\n{json.dumps(review_data, ensure_ascii=False, indent=2)}\n"
    path = project_dir / "state" / "prompt_bundles" / f"ep{args.episode:03d}_rewriter.md"
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    print(f"重写上下文包已写入：{path}（context_hash={context['context_hash']}）")
    if args.api:
        from .model_adapter import call_generate
        from .common import strip_code_fence

        text = call_generate(
            stage="rewrite",
            system_prompt=path.read_text(encoding="utf-8"),
            user_context="只输出重写后的业务剧本正文。",
            model_config=config.get("model_config"),
            temperature=0.4,
        )
        text = strip_code_fence(text)
        temp_draft = project_dir / "state" / f"rewrite_ep{args.episode:03d}.txt"
        temp_draft.write_text(text, encoding="utf-8")
        cmd_save_draft(argparse.Namespace(dir=str(project_dir), episode=args.episode, file=str(temp_draft)))
        if args.draft_out:
            out = Path(args.draft_out).expanduser().resolve()
            ensure_dir(out.parent)
            out.write_text(text, encoding="utf-8")
        print("API 重写完成，草稿已保存。请再次 review 同一问题。")
    else:
        print("Host Agent Mode：请阅读该上下文包，定向修复后保存草稿，再重新审核。")
    return 0


def cmd_approve(args) -> int:
    project_dir = _project_dir(args)
    from .continuity_manager import apply_approved_script

    text = Path(args.file).expanduser().resolve()
    if not text.exists():
        raise CliError(f"定稿文件不存在：{text}")
    path = apply_approved_script(project_dir, args.episode, text.read_text(encoding="utf-8"), source=args.source)
    continuity = load_continuity(project_dir)
    print(f"定稿已保存：{path}")
    print(f"连续性已更新（version={continuity.get('version')}，extraction_mode={continuity.get('extraction_mode')}）")
    return 0


def cmd_apply_revision(args) -> int:
    project_dir = _project_dir(args)
    from .revision_manager import approve_revision, create_revision

    record = create_revision(
        project_dir,
        episode=args.episode,
        instruction=args.instruction,
        source=args.source,
        requested_by=args.requested_by,
        affects_future=args.affects_future,
    )
    if args.auto_approve:
        approve_revision(project_dir, record["revision_id"])
        record["status"] = "approved"
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_refresh_continuity(args) -> int:
    project_dir = _project_dir(args)
    from .continuity_manager import refresh_continuity

    continuity = refresh_continuity(project_dir, up_to_episode=args.up_to)
    print(f"连续性已重建：version={continuity['version']}，已确认集={continuity['approved_episodes']}，extraction_mode={continuity.get('extraction_mode')}")
    return 0


def cmd_forecast_duration(args) -> int:
    project_dir = _project_dir(args)
    from .duration_estimator import forecast_duration, render_duration_report

    config = load_config(project_dir)
    scripts = []
    for episode in range(1, args.up_to + 1):
        approved = active_artifact_path(project_dir, "approved_script", episode)
        draft = active_artifact_path(project_dir, "script_draft", episode)
        path = approved or draft
        if path and path.exists():
            scripts.append((episode, path.read_text(encoding="utf-8")))
    forecast = forecast_duration(
        config,
        scripts,
        dialogue_chars_per_minute=(config.get("advisory_timing") or {}).get("dialogue_chars_per_minute"),
    )
    target_dir = project_dir / "artifacts" / "duration_forecast"
    ensure_dir(target_dir)
    atomic_write_json(target_dir / "forecast.json", forecast)
    (target_dir / "forecast.md").write_text(render_duration_report(forecast), encoding="utf-8")
    print(render_duration_report(forecast))
    return 0


def cmd_check_api(args) -> int:
    """Verify the configured model endpoint with a minimal call."""
    project_dir = _project_dir(args)
    config = load_config(project_dir)
    model_config = config.get("model_config") or {}
    if not model_config.get("api_url"):
        raise CliError(
            "未配置 model_config.api_url。请把 DeepSeek 配置写入项目目录的 "
            "config.local.json（参考仓库根 config.local.example.json）。"
        )
    from .model_adapter import call_generate, resolve_api_key

    resolve_api_key(model_config)
    text = call_generate(
        stage="api_check",
        system_prompt="你是 Fangcun Next 的 API 连通性验证助手。",
        user_context="只回复两个字：OK",
        model_config=model_config,
        temperature=0,
        max_tokens=256,
    )
    print(f"API 连通成功：{model_config.get('api_url')} | 模型 {model_config.get('model')} | 响应：{text.strip()[:120]}")
    return 0


def cmd_status(args) -> int:
    project_dir = _project_dir(args)
    status = project_status(project_dir)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args) -> int:
    project_dir = _project_dir(args)
    from .format_renderer import render_export

    config = load_config(project_dir)
    scripts = []
    for episode in range(1, args.up_to + 1):
        approved = active_artifact_path(project_dir, "approved_script", episode)
        draft = active_artifact_path(project_dir, "script_draft", episode)
        path = approved or draft
        if path and path.exists():
            scripts.append((episode, path.read_text(encoding="utf-8")))
    if not scripts:
        raise CliError("没有可导出的剧本")
    out = Path(args.out).expanduser().resolve() if args.out else project_dir / "export" / "export.txt"
    ensure_dir(out.parent)
    out.write_text(
        render_export(
            project_dir,
            scripts,
            format_profile=config.get("script_format", "default-cn"),
            xml=args.xml,
        ),
        encoding="utf-8",
    )
    print(f"导出完成：{out}")
    return 0


def cmd_migrate(args) -> int:
    from .migration import migrate_all, migrate_project

    out_dir = Path(args.out_dir).expanduser().resolve()
    if args.legacy_config:
        report = migrate_project(Path(args.legacy_config).expanduser().resolve(), out_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        reports = migrate_all(Path(args.legacy_projects).expanduser().resolve(), out_dir)
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


def cmd_build_package(args) -> int:
    from .release_builder import build_package

    out = Path(args.out).expanduser().resolve() if args.out else Path("dist") / f"fangcun-next-{args.version}.zip"
    path = build_package(out, version=args.version)
    print(f"发布包已生成：{path}")
    print(f"清单：{path.parent / 'release_manifest.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fangcun", description="Fangcun Next 小说转短剧 Skill 运行时")
    parser.add_argument("--version", action="version", version=f"fangcun-next {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="初始化项目")
    p.add_argument("--dir")
    p.add_argument("--projects", default="projects")
    p.add_argument("--config")
    p.add_argument("--brief")
    p.add_argument("--project-id")
    p.add_argument("--novel-name")
    p.add_argument("--drama-name")
    p.add_argument("--platform")
    p.add_argument("--aspect-ratio")
    p.add_argument("--genre")
    p.add_argument("--episodes", type=int)
    p.add_argument("--minimum-episode-seconds", type=int, default=60)
    p.set_defaults(func=cmd_init)

    for name in ("generate-requirements", "generate-adaptation", "generate-story-outline", "generate-episode-outline"):
        p = sub.add_parser(name, help=f"生成 {name} 阶段 Prompt 包")
        p.add_argument("--dir", required=True)
        p.set_defaults(func={
            "generate-requirements": cmd_generate_requirements,
            "generate-adaptation": cmd_generate_adaptation,
            "generate-story-outline": cmd_generate_story_outline,
            "generate-episode-outline": cmd_generate_episode_outline,
        }[name])

    p = sub.add_parser("save-requirements")
    p.add_argument("--dir", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_save_requirements)

    p = sub.add_parser("ingest-source")
    p.add_argument("--dir", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_ingest_source)

    p = sub.add_parser("save-events")
    p.add_argument("--dir", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_save_events)

    p = sub.add_parser("estimate-capacity")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_estimate_capacity)

    p = sub.add_parser("save-adaptation")
    p.add_argument("--dir", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--summary-file")
    p.set_defaults(func=cmd_save_adaptation)

    p = sub.add_parser("save-story-outline")
    p.add_argument("--dir", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--summary-file")
    p.set_defaults(func=cmd_save_story_outline)

    p = sub.add_parser("save-episode-outline")
    p.add_argument("--dir", required=True)
    p.add_argument("--outline-json", required=True)
    p.add_argument("--outline-md")
    p.set_defaults(func=cmd_save_episode_outline)

    p = sub.add_parser("get-episode-context")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--role", default="writer", choices=["writer", "reviewer", "rewriter"])
    p.add_argument("--max-source-chars", type=int, default=6000)
    p.add_argument("--per-chapter-budget", type=int, default=2000)
    p.set_defaults(func=cmd_get_episode_context)

    p = sub.add_parser("save-draft")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_save_draft)

    p = sub.add_parser("review")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--api", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("save-review")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_save_review)

    p = sub.add_parser("rewrite")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--api", action="store_true")
    p.add_argument("--draft-out")
    p.set_defaults(func=cmd_rewrite)

    p = sub.add_parser("approve")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--source", default="writer")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("apply-revision")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--instruction", required=True)
    p.add_argument("--source", default="cli")
    p.add_argument("--requested-by", default="writer")
    p.add_argument("--affects-future", dest="affects_future", action="store_true", default=None)
    p.add_argument("--auto-approve", action="store_true")
    p.set_defaults(func=cmd_apply_revision)

    p = sub.add_parser("refresh-continuity")
    p.add_argument("--dir", required=True)
    p.add_argument("--up-to", type=int, default=10_000)
    p.set_defaults(func=cmd_refresh_continuity)

    p = sub.add_parser("forecast-duration")
    p.add_argument("--dir", required=True)
    p.add_argument("--up-to", type=int, default=10_000)
    p.set_defaults(func=cmd_forecast_duration)

    p = sub.add_parser("status")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("check-api")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_check_api)

    p = sub.add_parser("export")
    p.add_argument("--dir", required=True)
    p.add_argument("--out")
    p.add_argument("--up-to", type=int, default=10_000)
    p.add_argument("--xml", action="store_true")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("migrate")
    p.add_argument("--legacy-config")
    p.add_argument("--legacy-projects")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("build-package")
    p.add_argument("--out")
    p.add_argument("--version", default=__version__)
    p.set_defaults(func=cmd_build_package)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        raise exc
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
