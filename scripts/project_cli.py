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
from .common import sha256_text
from .schema_validate import SchemaValidationError, ensure_valid
from .state_store import (
    active_artifact_path,
    init_project,
    load_config,
    load_continuity,
    project_status,
    commit_artifact,
    active_version_id,
    artifact_version_path,
    artifact_version_record,
    record_artifact,
    save_config,
    draft_meta_record,
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

    result = commit_artifact(
        project_dir,
        "project_brief",
        content=render_project_brief_markdown(config),
        source="writer",
        status="approved",
        ext="md",
    )
    print(f"需求已保存：{result['path']}（{result['version']}）")
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
    result = commit_artifact(
        project_dir,
        "source_events",
        content=events,
        source="ai",
        status="approved",
        ext="json",
    )
    print(f"事件资产已保存：{result['path']}（{result['version']}，{len(events)} 个事件）")
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
    result = commit_artifact(
        project_dir,
        kind,
        content=file.read_text(encoding="utf-8"),
        source="ai",
        status="approved",
        ext=file.suffix.lstrip(".") or "md",
    )
    print(f"{kind} 已保存：{result['path']}（{result['version']}）")
    if summary_file:
        summary = _load_json_file(Path(summary_file), "结构化摘要")
        if summary_schema:
            ensure_valid(summary, summary_schema)
        summary_kind = {
            "adaptation_strategy": "adaptation_summary",
            "story_outline": "story_outline_summary",
        }.get(kind, f"{kind}_summary")
        summary_result = commit_artifact(
            project_dir,
            summary_kind,
            content=summary,
            source="ai",
            status="approved",
            ext="json",
        )
        print(f"{kind} 摘要已保存：{summary_result['path']}（{summary_result['version']}）")


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
    from .common import canonical_json

    existing_path = active_artifact_path(project_dir, "episode_outline")
    existing: dict[int, dict] = {}
    if existing_path and existing_path.exists():
        existing_data = _load_json_file(existing_path, "当前集纲")
        existing_list = (
            existing_data.get("episodes", existing_data)
            if isinstance(existing_data, dict)
            else existing_data
        )
        if isinstance(existing_list, list):
            existing = {int(e.get("episode")): e for e in existing_list if isinstance(e, dict)}
    incoming = {int(o["episode"]): o for o in episodes}

    if args.replace:
        merged = dict(incoming)
        deleted = sorted(set(existing) - set(incoming))
    else:
        merged = dict(existing)
        merged.update(incoming)
        deleted = []
    added = sorted(set(incoming) - set(existing))
    modified = sorted(
        ep for ep in incoming
        if ep in existing and canonical_json(incoming[ep]) != canonical_json(existing[ep])
    )
    unchanged = sorted(ep for ep in incoming if ep in existing and ep not in modified)
    merge_report = {
        "mode": "replace" if args.replace else "upsert",
        "added": added,
        "modified": modified,
        "unchanged": unchanged,
        "deleted": deleted,
        "total_episodes": len(merged),
    }
    ordered = [merged[ep] for ep in sorted(merged)]
    result = commit_artifact(
        project_dir,
        "episode_outline",
        content={"episodes": ordered},
        source="ai",
        status="approved",
        ext="json",
        meta={"merge_report": merge_report},
    )
    if args.outline_md:
        md_path = Path(args.outline_md).expanduser().resolve()
        if md_path.exists():
            commit_artifact(
                project_dir,
                "episode_outline_md",
                content=md_path.read_text(encoding="utf-8"),
                source="ai",
                status="approved",
                ext="md",
            )
    print(f"集纲已保存：{result['path']}（{result['version']}，共 {len(merged)} 集）")
    print(f"合并报告：{json.dumps(merge_report, ensure_ascii=False)}")
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
    _print_pending_revisions(project_dir, args.episode)
    if context["completeness"]["warnings"]:
        for warning in context["completeness"]["warnings"]:
            print(f"警告：{warning}")
    return 0


def _print_pending_revisions(project_dir: Path, episode: int) -> None:
    from .context_builder import pending_revisions

    pending = pending_revisions(project_dir, episode)
    if pending:
        print(f"⚠ 第{episode}集存在 {len(pending)} 条待编剧确认的修改意见（含未来作用域）：")
        for record in pending:
            print(f"  - {record.get('revision_id')}：{str(record.get('instruction'))[:60]}")
        print("  继续创作前请先 approve-revision / reject-revision 处理。")


def cmd_save_draft(args) -> int:
    project_dir = _project_dir(args)
    from .script_validator import validate_script

    config = load_config(project_dir)
    content = Path(args.file).expanduser().resolve()
    if not content.exists():
        raise CliError(f"草稿文件不存在：{content}")
    text = content.read_text(encoding="utf-8")
    from .format_renderer import business_format

    if "<scriptItem" in text:
        text = business_format(text, "legacy-scriptitem")
    report = validate_script(text, format_profile="default-cn", expected_episode=args.episode)
    if not report["ok"]:
        raise CliError("草稿格式未通过：\n" + "\n".join(f"- {e['message']}" for e in report["errors"][:10]))
    context_hash = getattr(args, "context_hash", None) or None
    if context_hash:
        _load_context_snapshot_by_hash(project_dir, args.episode, context_hash)
    else:
        context = _load_context_snapshot(project_dir, args.episode)
        context_hash = context["context_hash"]
    draft_hash = sha256_text(text)
    ticket_id = getattr(args, "rewrite_ticket", None) or None
    origin = "manual"
    ticket_bindings = {}
    if ticket_id:
        from .rewrite_ticket import consume_rewrite_ticket, ticket_state

        ticket = ticket_state(project_dir, ticket_id)
        if not ticket:
            raise CliError(f"rewrite ticket 不存在：{ticket_id}")
        if ticket.get("episode") != args.episode:
            raise CliError("rewrite ticket 属于其他集，拒绝消费")
        if ticket.get("context_hash") != context_hash:
            raise CliError("rewrite ticket 绑定的 context_hash 与草稿上下文不一致，拒绝消费")
        consume_rewrite_ticket(
            project_dir,
            ticket_id,
            episode=ticket["episode"],
            context_hash=ticket["context_hash"],
            review_version=ticket["review_version"],
            review_hash=ticket["review_hash"],
            source_draft_version=ticket["source_draft_version"],
            source_draft_hash=ticket["source_draft_hash"],
        )
        origin = "automatic_rewrite"
        ticket_bindings = {
            "rewrite_ticket_id": ticket_id,
            "review_version": ticket.get("review_version"),
            "review_hash": ticket.get("review_hash"),
            "source_draft_version": ticket.get("source_draft_version"),
            "source_draft_hash": ticket.get("source_draft_hash"),
        }
    meta = {
        "context_hash": context_hash,
        "draft_hash": draft_hash,
        "episode_outline_version": None,
        "source_events_version": None,
        "origin": origin,
        **ticket_bindings,
    }
    context_snapshot = _load_context_snapshot_by_hash(project_dir, args.episode, context_hash)
    meta["episode_outline_version"] = context_snapshot.get("context_versions", {}).get("episode_outline_version")
    meta["source_events_version"] = context_snapshot.get("context_versions", {}).get("source_events_version")
    result = commit_artifact(
        project_dir,
        "script_draft",
        content=text,
        episode=args.episode,
        source="model_rewrite" if origin == "automatic_rewrite" else "ai",
        status="draft",
        ext="txt",
        meta=meta,
    )
    _print_pending_revisions(project_dir, args.episode)
    print(f"草稿已保存：{result['path']}（{result['version']}，draft_hash={draft_hash[:12]}，context_hash={context_hash[:12]}）")
    revision_ids = list(getattr(args, "apply_revision", None) or [])
    if revision_ids:
        from .revision_manager import mark_revisions_applied

        if result["created"]:
            applied = mark_revisions_applied(
                project_dir,
                episode=args.episode,
                revision_ids=revision_ids,
                applied_to_kind="script_draft",
                applied_to_version=result["version"],
            )
            print(f"已绑定 applied 的修改意见：{applied} 条")
        else:
            print("内容未变化（幂等复用旧版本），不绑定 applied；请先实际修改再保存。")
    print(f"下一步：review --episode {args.episode}")
    return 0


def _review_bundle_path(project_dir: Path, episode: int) -> Path:
    return project_dir / "state" / "prompt_bundles" / f"ep{episode:03d}_reviewer.md"


def _load_context_snapshot(project_dir: Path, episode: int) -> dict:
    from .context_builder import current_context_path, verify_context_hash

    path = current_context_path(project_dir, episode)
    if not path or not path.exists():
        raise CliError(f"缺少当前 episode_context 快照：{path}。请先运行 get-episode-context --episode {episode}")
    context = _load_json_file(path, "episode_context")
    ok, _ = verify_context_hash(context)
    if not ok:
        raise CliError(f"episode_context 哈希校验失败，拒绝使用：{path}")
    return context


def _load_context_snapshot_by_hash(project_dir: Path, episode: int, context_hash: str) -> dict:
    from .context_builder import find_context_snapshot, verify_context_hash

    if not context_hash:
        raise CliError("缺少 context_hash，拒绝使用上下文")
    path = find_context_snapshot(project_dir, episode, context_hash)
    if not path:
        raise CliError(f"找不到 context_hash={context_hash[:12]} 的不可变上下文快照，拒绝继续")
    context = _load_json_file(path, "episode_context")
    ok, _ = verify_context_hash(context)
    if not ok:
        raise CliError(f"episode_context 哈希校验失败，拒绝使用：{path}")
    return context


def _strip_evidence_prefix(value: str) -> str:
    text = str(value).strip()
    for prefix in ("原文：", "原文:", "source_evidence：", "source_evidence:", "source：", "source:", "证据：", "证据:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text


def _normalize_issue_evidence(issue: dict) -> None:
    """Convert legacy string evidence fields to structured evidence."""
    evidence = issue.get("evidence")
    if isinstance(evidence, dict):
        evidence_type = str(evidence.get("evidence_type") or "").strip().lower()
        if evidence_type not in ("source", "adaptation"):
            if evidence.get("quote"):
                evidence["evidence_type"] = "source"
            elif evidence.get("adaptation_decision_id"):
                evidence["evidence_type"] = "adaptation"
        return
    if evidence is not None:
        return
    if issue.get("source_evidence"):
        issue["evidence"] = {
            "evidence_type": "source",
            "quote": _strip_evidence_prefix(issue["source_evidence"]),
        }
    elif issue.get("adaptation_basis"):
        issue["evidence"] = {
            "evidence_type": "adaptation",
            "adaptation_decision_id": str(issue["adaptation_basis"]),
        }


def _validate_issue_evidence(issue: dict, context: dict) -> list[str]:
    """All provided evidence fields must resolve to ONE consistent excerpt."""
    if issue.get("severity") != "error":
        return []
    evidence = issue.get("evidence")
    if not isinstance(evidence, dict):
        return ["error 问题缺少结构化 evidence，拒绝保存"]
    errors: list[str] = []
    evidence_type = evidence.get("evidence_type")
    excerpts = context.get("source_evidence", {}).get("raw_excerpts", []) or []
    if evidence_type == "source":
        quote = str(evidence.get("quote") or "").strip()
        event_ids = {e.get("event_id") for e in context.get("source_evidence", {}).get("events", []) or []}
        event_id = evidence.get("event_id")
        chapter_id = evidence.get("chapter_id")
        span = evidence.get("source_span")
        excerpt_hash = evidence.get("excerpt_hash")
        if event_id and event_id not in event_ids:
            errors.append(f"证据 event_id {event_id} 不存在于当前上下文")
        if isinstance(span, dict):
            start = span.get("start")
            end = span.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end):
                errors.append(f"证据 source_span 必须满足 0 <= start < end（收到 {span}）")
        elif span is not None:
            errors.append("证据 source_span 必须是对象")
        if not quote and not event_id and not chapter_id and not isinstance(span, dict):
            errors.append("证据没有任何可验证维度（quote/event_id/chapter/span 至少一项）")
        candidates = excerpts
        if event_id:
            event_excerpts = [ex for ex in excerpts if ex.get("reason") == f"event:{event_id}"]
            if not event_excerpts:
                errors.append(f"事件 {event_id} 没有可定位摘录，不能作为证据主键")
            candidates = event_excerpts or excerpts
        matching = []
        for ex in candidates:
            ok = True
            if chapter_id is not None and ex.get("chapter_id") != chapter_id:
                ok = False
            if isinstance(span, dict) and not (
                ex.get("source_span", {}).get("start", -1) <= span.get("start", -1)
                and span.get("end", -1) <= ex.get("source_span", {}).get("end", -2)
            ):
                ok = False
            if quote and quote not in str(ex.get("text", "")):
                ok = False
            if excerpt_hash and excerpt_hash != ex.get("excerpt_hash"):
                ok = False
            if ok:
                matching.append(ex)
        if not matching:
            errors.append("证据 quote/span/excerpt_hash/chapter 无法指向同一个摘录")
        if event_id and chapter_id is not None:
            event = next(
                (e for e in context.get("source_evidence", {}).get("events", []) or [] if e.get("event_id") == event_id),
                None,
            )
            if event is not None and event.get("chapter_id") not in (None, chapter_id):
                errors.append(f"证据 event_id {event_id} 的章节与 chapter_id {chapter_id} 冲突")
    elif evidence_type == "adaptation":
        decision_id = evidence.get("adaptation_decision_id")
        decisions = (context.get("adaptation_summary") or {}).get("decisions") or []
        if not decision_id or not any(d.get("id") == decision_id for d in decisions):
            errors.append(f"adaptation decision {decision_id!r} 不属于当前有效改编决策")
    else:
        errors.append("evidence_type 必须是 source 或 adaptation")
    return errors


def cmd_review(args) -> int:
    project_dir = _project_dir(args)
    from .prompt_router import render_prompt_bundle
    from .script_validator import validate_script

    config = load_config(project_dir)
    draft = active_artifact_path(project_dir, "script_draft", args.episode)
    if not draft or not draft.exists():
        raise CliError(f"第{args.episode}集没有草稿，请先 save-draft")
    draft_version = active_version_id(project_dir, "script_draft", args.episode)
    if not draft_version:
        raise CliError("草稿缺少版本登记，拒绝审核")
    draft_text = draft.read_text(encoding="utf-8")
    draft_meta = draft_meta_record(project_dir, args.episode, draft_version) or {}
    if not draft_meta.get("draft_hash"):
        raise CliError("草稿缺少 draft_hash 元数据，拒绝审核")
    if sha256_text(draft_text) != draft_meta["draft_hash"]:
        raise CliError("草稿内容与登记 draft_hash 不一致，拒绝审核")
    report = validate_script(draft_text, format_profile="default-cn", expected_episode=args.episode)
    if not report["ok"]:
        raise CliError("草稿格式未通过，请先修复：\n" + "\n".join(f"- {e['message']}" for e in report["errors"][:10]))

    context = _load_context_snapshot(project_dir, args.episode)
    if draft_meta.get("context_hash") != context["context_hash"]:
        raise CliError(
            "草稿绑定的 context_hash 与当前上下文不一致，拒绝审核。"
            "请先重新生成与草稿一致的上下文，或从不可变快照中选择正确版本。"
        )
    review_context = {
        **context,
        "script_draft": draft_text,
        "draft_hash": draft_meta["draft_hash"],
        "draft_version": draft_version,
    }
    bundle = render_prompt_bundle(review_context, role="reviewer", config=config)
    bundle += (
        f"\n\n## 审核绑定（必须原样输出到审核 JSON）\n"
        f"context_hash: {context['context_hash']}\n"
        f"draft_hash: {draft_meta['draft_hash']}\n"
        f"draft_version: {draft_version}\n\n"
        f"## 待审草稿\n{draft_text}\n"
    )
    path = _review_bundle_path(project_dir, args.episode)
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    print(f"审核上下文包已写入：{path}（context_hash={context['context_hash']}）")
    _print_pending_revisions(project_dir, args.episode)
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
        report_data, normalize_errors = _normalize_review_report(parse_json_response(text))
        if normalize_errors:
            raise CliError("模型审核输出存在非法内容，拒绝保存：\n" + "\n".join(f"- {e}" for e in normalize_errors))
        ok, errors = validate(report_data, "review-report.schema.json")
        if not ok:
            raise CliError("模型审核输出未通过 Schema：" + "; ".join(errors))
        _save_review(
            project_dir,
            args.episode,
            report_data,
            expected_context_hash=context["context_hash"],
            expected_draft_version=draft_version,
            expected_draft_hash=draft_meta["draft_hash"],
        )
    else:
        print(
            "Host Agent Mode：请阅读该上下文包，按 review-report.schema.json 输出审核 JSON，"
            "并原样携带 context_hash/draft_hash/draft_version，然后用 save-review 保存。"
        )
    return 0


def _save_review(
    project_dir: Path,
    episode: int,
    report_data: dict,
    *,
    expected_context_hash: str,
    expected_draft_version: str,
    expected_draft_hash: str,
) -> None:
    report_data, normalize_errors = _normalize_review_report(report_data)
    if normalize_errors:
        raise CliError("审核报告存在非法内容，拒绝保存：\n" + "\n".join(f"- {e}" for e in normalize_errors))
    report_data["episode"] = episode
    for key in ("context_hash", "draft_hash", "draft_version"):
        if not report_data.get(key):
            raise CliError(f"审核报告缺少 {key}，拒绝保存（不允许自动补齐）")
    if report_data["context_hash"] != expected_context_hash:
        raise CliError("审核报告 context_hash 与草稿绑定的上下文不一致，拒绝保存")
    if report_data["draft_hash"] != expected_draft_hash:
        raise CliError("审核报告 draft_hash 与草稿登记哈希不一致，拒绝保存")
    if report_data["draft_version"] != expected_draft_version:
        raise CliError("审核报告 draft_version 与草稿版本不一致，拒绝保存")
    context = _load_context_snapshot_by_hash(project_dir, episode, expected_context_hash)
    report_data["verdict"] = _derive_verdict(report_data.get("issues"))
    ensure_valid(report_data, "review-report.schema.json")
    for issue in report_data.get("issues", []) or []:
        evidence_errors = _validate_issue_evidence(issue, context)
        if evidence_errors:
            raise CliError(f"error 问题 {issue.get('id')} 证据未通过验证：\n" + "\n".join(f"- {e}" for e in evidence_errors))
    result = commit_artifact(
        project_dir,
        "review",
        content=report_data,
        episode=episode,
        source="ai",
        status="approved",
        ext="json",
        meta={
            "context_hash": expected_context_hash,
            "draft_hash": expected_draft_hash,
            "draft_version": expected_draft_version,
        },
    )
    print(f"审核报告已保存：{result['path']}（{result['version']}）")
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
    """Unwrap wrappers and normalize issues. Returns (data, errors)."""
    return _normalize_review_report_v2(data)


def _derive_verdict(issues: list[dict] | None) -> str:
    """Verdict is ALWAYS derived from normalized effective issues."""
    severities = [str(i.get("severity", "")).lower() for i in (issues or [])]
    if "error" in severities:
        return "blocked"
    if "warning" in severities:
        return "warning"
    return "pass"


def _normalize_review_report_v2(data: dict) -> tuple[dict, list[str]]:
    """Unwrap wrappers, map categories, reject invalid issues. Verdict derived later."""
    errors: list[str] = []
    if isinstance(data.get("review_report"), dict):
        data = data["review_report"]
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        return data, ["issues 必须是数组"]
    model_verdict = data.get("verdict")
    normalized: list[dict] = []
    for idx, issue in enumerate(issues, start=1):
        if not isinstance(issue, dict):
            errors.append(f"issues[{idx}] 不是对象")
            continue
        raw_category = str(issue.get("category") or "other").strip().lower().replace(" ", "-")
        category = REVIEW_CATEGORY_ALIASES.get(raw_category, raw_category)
        if category not in VALID_REVIEW_CATEGORIES:
            category = "other"
        severity = str(issue.get("severity") or "warning").strip().lower()
        if severity not in ("error", "warning", "suggestion"):
            errors.append(f"issue {issue.get('id', idx)} severity 非法：{severity!r}")
            continue
        problem = str(issue.get("problem") or issue.get("detail") or "").strip()
        if not problem:
            errors.append(f"issue {issue.get('id', idx)} 缺少有效 problem")
            continue
        item = {
            "id": str(issue.get("id") or f"REVIEW-{idx:03d}"),
            "severity": severity,
            "category": category,
            "problem": problem,
        }
        for key in ("location", "source_evidence", "adaptation_basis", "fix", "evidence"):
            value = issue.get(key)
            if value not in (None, ""):
                item[key] = value
        _normalize_issue_evidence(item)
        if item["severity"] == "error" and item.get("evidence") is None:
            errors.append(f"error 问题 {item['id']} 缺少 evidence")
            continue
        normalized.append(item)
    data["issues"] = normalized
    if model_verdict is not None:
        data["model_verdict"] = model_verdict
    data.pop("verdict", None)
    if not str(data.get("summary") or "").strip():
        errors.append("缺少 summary")
    return data, errors


def cmd_save_review(args) -> int:
    project_dir = _project_dir(args)
    report_data = _load_json_file(Path(args.file), "审核报告")
    draft_version = active_version_id(project_dir, "script_draft", args.episode)
    if not draft_version:
        raise CliError("草稿缺少版本登记，拒绝保存审核")
    draft_meta = draft_meta_record(project_dir, args.episode, draft_version) or {}
    if not draft_meta.get("draft_hash") or not draft_meta.get("context_hash"):
        raise CliError("草稿缺少 draft_hash/context_hash 元数据，拒绝保存审核")
    _save_review(
        project_dir,
        args.episode,
        report_data,
        expected_context_hash=draft_meta["context_hash"],
        expected_draft_version=draft_version,
        expected_draft_hash=draft_meta["draft_hash"],
    )
    return 0


def _validate_review_for_consumption(project_dir: Path, episode: int, review_data: dict) -> list[str]:
    """Re-validate a review before consuming it (hash, schema, bindings, evidence, verdict)."""
    errors: list[str] = []
    from .common import canonical_json
    from .schema_validate import validate as schema_validate

    review_version = active_version_id(project_dir, "review", episode)
    record = artifact_version_record(project_dir, "review", episode, review_version) if review_version else None
    if not record:
        errors.append("审核 manifest 逻辑版本记录缺失")
    else:
        actual_hash = sha256_text(canonical_json(review_data) + "\n")
        if actual_hash != record.get("content_hash"):
            errors.append("审核文件内容与 manifest content_hash 不一致（文件可能被篡改）")
    ok, schema_errors = schema_validate(review_data, "review-report.schema.json")
    if not ok:
        errors.append("审核报告未通过 Schema：" + "; ".join(schema_errors[:3]))
    for key in ("context_hash", "draft_hash", "draft_version"):
        if not review_data.get(key):
            errors.append(f"审核报告缺少 {key}")
    try:
        context = _load_context_snapshot_by_hash(project_dir, episode, review_data.get("context_hash", ""))
    except CliError as exc:
        return errors + [str(exc)]
    draft_path = artifact_version_path(project_dir, "script_draft", episode, review_data.get("draft_version", ""))
    if not draft_path:
        errors.append("审核绑定的草稿版本不存在")
    else:
        if sha256_text(draft_path.read_text(encoding="utf-8")) != review_data.get("draft_hash"):
            errors.append("审核绑定的草稿哈希与文件不一致")
    for issue in review_data.get("issues", []) or []:
        evidence_errors = _validate_issue_evidence(issue, context)
        if evidence_errors:
            errors.extend(f"issue {issue.get('id', '?')}: {e}" for e in evidence_errors)
    derived = _derive_verdict(review_data.get("issues"))
    if review_data.get("verdict") != derived:
        errors.append(f"verdict {review_data.get('verdict')!r} 与 issues 推导结果 {derived!r} 不一致")
    return errors


def cmd_rewrite(args) -> int:
    project_dir = _project_dir(args)
    from .prompt_router import render_prompt_bundle

    config = load_config(project_dir)
    review = active_artifact_path(project_dir, "review", args.episode)
    if not review or not review.exists():
        raise CliError(f"第{args.episode}集没有审核报告，请先 review/save-review")
    review_data = _load_json_file(review, "审核报告")
    consumption_errors = _validate_review_for_consumption(project_dir, args.episode, review_data)
    if consumption_errors:
        raise CliError("审核报告消费前再验证失败，拒绝重写：\n" + "\n".join(f"- {e}" for e in consumption_errors))
    context = _load_context_snapshot_by_hash(project_dir, args.episode, review_data["context_hash"])
    draft_path = artifact_version_path(project_dir, "script_draft", args.episode, review_data["draft_version"])
    if not draft_path:
        raise CliError(f"审核报告绑定的草稿版本 {review_data['draft_version']} 不存在，拒绝重写")
    draft_text = draft_path.read_text(encoding="utf-8")
    if sha256_text(draft_text) != review_data["draft_hash"]:
        raise CliError("审核报告绑定的草稿哈希与文件内容不一致，拒绝重写")
    bound_draft_meta = draft_meta_record(project_dir, args.episode, review_data["draft_version"]) or {}
    if bound_draft_meta.get("origin") == "automatic_rewrite":
        raise CliError("该草稿已是自动重写产物；自动重写次数有限，请人工修改后保存再继续")
    review_version = active_version_id(project_dir, "review", args.episode) or ""
    review_record = artifact_version_record(project_dir, "review", args.episode, review_version)
    review_hash = review_record.get("content_hash", "") if review_record else ""
    from .rewrite_ticket import issue_rewrite_ticket

    ticket = issue_rewrite_ticket(
        project_dir,
        episode=args.episode,
        context_hash=review_data["context_hash"],
        review_version=review_version,
        review_hash=review_hash,
        source_draft_version=review_data["draft_version"],
        source_draft_hash=review_data["draft_hash"],
    )
    rewrite_context = {**context, "script_draft": draft_text, "review_report": review_data}
    bundle = render_prompt_bundle(rewrite_context, role="rewriter", config=config)
    bundle += (
        f"\n\n## 一次性重写凭证（rewrite ticket，必须显式提交）\n"
        f"ticket_id: {ticket['ticket_id']}\n"
        f"episode: {ticket['episode']}\n"
        f"context_hash: {ticket['context_hash']}\n"
        f"review_version: {ticket['review_version']}\n"
        f"source_draft_version: {ticket['source_draft_version']}\n\n"
        f"## 当前草稿\n{draft_text}\n\n## 审核报告\n{json.dumps(review_data, ensure_ascii=False, indent=2)}\n"
    )
    path = project_dir / "state" / "prompt_bundles" / f"ep{args.episode:03d}_rewriter.md"
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    print(f"重写上下文包已写入：{path}（context_hash={context['context_hash']}）")
    print(f"rewrite ticket：{ticket['ticket_id']}")
    _print_pending_revisions(project_dir, args.episode)
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
        cmd_save_draft(
            argparse.Namespace(
                dir=str(project_dir),
                episode=args.episode,
                file=str(temp_draft),
                context_hash=review_data["context_hash"],
                rewrite_ticket=ticket["ticket_id"],
            )
        )
        if args.draft_out:
            out = Path(args.draft_out).expanduser().resolve()
            ensure_dir(out.parent)
            out.write_text(text, encoding="utf-8")
        print("API 重写完成，草稿已保存。请再次 review 同一问题。")
    else:
        print(
            "Host Agent Mode：请阅读该上下文包，定向修复后用 "
            f"save-draft --rewrite-ticket {ticket['ticket_id']} 提交重写稿（ticket 只能消费一次）。"
        )
    return 0


def cmd_approve(args) -> int:
    project_dir = _project_dir(args)
    from .continuity_manager import apply_approved_script

    text = Path(args.file).expanduser().resolve()
    if not text.exists():
        raise CliError(f"定稿文件不存在：{text}")
    path = apply_approved_script(project_dir, args.episode, text.read_text(encoding="utf-8"), source=args.source)
    continuity = load_continuity(project_dir)
    from .revision_manager import mark_revisions_applied

    revision_ids = list(getattr(args, "apply_revision", None) or [])
    if revision_ids:
        applied = mark_revisions_applied(
            project_dir,
            episode=args.episode,
            revision_ids=revision_ids,
            applied_to_kind="approved_script",
            applied_to_version=active_version_id(project_dir, "approved_script", args.episode) or "",
        )
        print(f"已绑定 applied 的修改意见：{applied} 条")
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
        affects_future=False if getattr(args, "no_affects_future", False) else args.affects_future,
        direct_writer_instruction=bool(args.direct),
    )
    if args.auto_approve or args.direct:
        approve_revision(project_dir, record["revision_id"])
        record["status"] = "approved"
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_list_revisions(args) -> int:
    project_dir = _project_dir(args)
    from .revision_manager import list_revisions

    records = list_revisions(project_dir, episode=args.episode)
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


def cmd_approve_revision(args) -> int:
    project_dir = _project_dir(args)
    from .revision_manager import approve_revision

    record = approve_revision(project_dir, args.revision_id)
    if record is None:
        raise CliError(f"找不到修改意见 {args.revision_id}")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_reject_revision(args) -> int:
    project_dir = _project_dir(args)
    from .revision_manager import reject_revision

    record = reject_revision(project_dir, args.revision_id)
    if record is None:
        raise CliError(f"找不到修改意见 {args.revision_id}")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_revoke_revision(args) -> int:
    project_dir = _project_dir(args)
    from .revision_manager import revoke_revision

    record = revoke_revision(project_dir, args.revision_id, reason=args.reason)
    if record is None:
        raise CliError(f"找不到修改意见 {args.revision_id}")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_revision_status(args) -> int:
    project_dir = _project_dir(args)
    from .revision_manager import list_revisions

    for record in list_revisions(project_dir):
        if record.get("revision_id") == args.revision_id:
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 0
    raise CliError(f"找不到修改意见 {args.revision_id}")


def cmd_extract_continuity(args) -> int:
    """Host Agent Mode: render a continuity-delta extraction bundle."""
    project_dir = _project_dir(args)
    from .prompt_router import _stage_prompt
    from .state_store import artifact_version_record

    approved = active_artifact_path(project_dir, "approved_script", args.episode)
    if not approved or not approved.exists():
        raise CliError(f"第{args.episode}集没有定稿，请先 approve")
    draft_version = active_version_id(project_dir, "approved_script", args.episode) or ""
    record = artifact_version_record(project_dir, "approved_script", args.episode, draft_version) or {}
    script_hash = record.get("content_hash") or sha256_text(approved.read_text(encoding="utf-8"))
    script_text = approved.read_text(encoding="utf-8")
    continuity = load_continuity(project_dir)
    prompt = _stage_prompt("continuity_extract")
    bundle = (
        f"# 连续性提取（Host Agent Mode）\n"
        f"- 集数：{args.episode}\n"
        f"- draft_version：{draft_version}\n"
        f"- script_hash：{script_hash}\n\n"
        f"{prompt}\n\n"
        f"## 当前连续性快照\n{json.dumps(continuity, ensure_ascii=False, indent=2)}\n\n"
        f"## 当前定稿\n{script_text}\n\n"
        "输出 continuity-delta.schema.json 兼容 JSON，extraction_mode 填 host_agent，"
        "facts 每条必须带 fact_id/category/evidence_location。"
    )
    path = project_dir / "state" / "prompt_bundles" / f"ep{args.episode:03d}_continuity.md"
    ensure_dir(path.parent)
    path.write_text(bundle, encoding="utf-8")
    print(f"连续性提取包已写入：{path}（script_hash={script_hash[:12]}）")
    print("Host Agent Mode：请阅读该包，输出 delta JSON，然后用 save-continuity-delta 保存。")
    return 0


def cmd_save_continuity_delta(args) -> int:
    project_dir = _project_dir(args)
    from .continuity_manager import refresh_continuity, save_continuity_delta
    from .state_store import artifact_version_record

    delta = _load_json_file(Path(args.file), "连续性 delta")
    draft_version = active_version_id(project_dir, "approved_script", args.episode)
    if not draft_version:
        raise CliError(f"第{args.episode}集没有定稿版本登记")
    record = artifact_version_record(project_dir, "approved_script", args.episode, draft_version) or {}
    script_hash = record.get("content_hash")
    if not script_hash:
        raise CliError("定稿缺少 content_hash，拒绝保存 delta")
    path = save_continuity_delta(
        project_dir,
        episode=args.episode,
        delta=delta,
        script_hash=script_hash,
        draft_version=draft_version,
    )
    continuity = refresh_continuity(project_dir)
    info = continuity.get("episode_extraction", {}).get(str(args.episode), {})
    print(f"连续性 delta 已保存：{path}")
    print(f"该集提取模式：{info.get('mode')}，完整：{info.get('complete')}")
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
    result = commit_artifact(
        project_dir,
        "duration_forecast",
        content=forecast,
        source="ai",
        status="approved",
        ext="json",
    )
    commit_artifact(
        project_dir,
        "duration_forecast_md",
        content=render_duration_report(forecast),
        source="ai",
        status="approved",
        ext="md",
    )
    print(f"时长预估已保存：{result['path']}（{result['version']}）")
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


def cmd_activate_version(args) -> int:
    project_dir = _project_dir(args)
    from .state_store import activate_version

    result = activate_version(
        project_dir,
        args.kind,
        args.version,
        episode=args.episode,
        reason=args.reason,
        operator=args.operator,
    )
    if args.kind == "approved_script" and args.episode:
        from .continuity_manager import refresh_continuity

        continuity = refresh_continuity(project_dir)
        print(
            f"已恢复定稿 {args.version} 并重建连续性"
            f"（version={continuity.get('version')}，degraded={continuity.get('degraded_episodes')}）"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
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
            transport_format=config.get("transport_format", "plain"),
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
    p.add_argument("--replace", action="store_true", help="显式整表替换集纲（默认按集 upsert 并保留未出现集数）")
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
    p.add_argument("--rewrite-ticket", default=None, help="一次性重写凭证（由 rewrite 命令签发，Host Agent 保存重写稿时必须提交）")
    p.add_argument("--context-hash", default=None, help=argparse.SUPPRESS)
    p.add_argument("--apply-revision", action="append", default=[], help="显式绑定已执行的修改意见 revision_id（可重复）")
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
    p.add_argument("--apply-revision", action="append", default=[], help="显式绑定已执行的修改意见 revision_id（可重复）")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("apply-revision")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--instruction", required=True)
    p.add_argument("--source", default="cli")
    p.add_argument("--requested-by", default="writer")
    p.add_argument("--affects-future", dest="affects_future", action="store_true", default=None)
    p.add_argument("--no-affects-future", dest="no_affects_future", action="store_true", default=False)
    p.add_argument("--auto-approve", action="store_true")
    p.add_argument("--direct", action="store_true", help="编剧明确直接指令，创建即 approved")
    p.set_defaults(func=cmd_apply_revision)

    p = sub.add_parser("list-revisions")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int)
    p.set_defaults(func=cmd_list_revisions)

    for name, func in (
        ("approve-revision", cmd_approve_revision),
        ("reject-revision", cmd_reject_revision),
        ("revoke-revision", cmd_revoke_revision),
        ("revision-status", cmd_revision_status),
    ):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True)
        p.add_argument("--revision-id", required=True)
        if name == "revoke-revision":
            p.add_argument("--reason", default="")
        p.set_defaults(func=func)

    p = sub.add_parser("extract-continuity")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.set_defaults(func=cmd_extract_continuity)

    p = sub.add_parser("save-continuity-delta")
    p.add_argument("--dir", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_save_continuity_delta)

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

    p = sub.add_parser("activate-version")
    p.add_argument("--dir", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--episode", type=int)
    p.add_argument("--reason", default="")
    p.add_argument("--operator", default="cli")
    p.set_defaults(func=cmd_activate_version)

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
