"""Layered prompt assembly and on-demand craft routing (deterministic).

Every writing call receives at most seven layers (spec §13.1):
  system base → stage role → project → episode contract → source evidence
  → continuity/overrides → selected craft modules.

The same episode_context snapshot is used by Writer, Reviewer and Rewriter;
the context_hash is embedded in every bundle so reviewers cannot silently
switch to a different evidence set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import read_json, references_dir


ALWAYS_MODULES = ["source-fidelity", "causality", "knowledge-state", "screenplay-format"]

GENRE_ALIASES = {
    "喜剧": "comedy",
    "搞笑": "comedy",
    "甜宠": "romance",
    "恋爱": "romance",
    "言情": "romance",
    "虐恋": "romance",
    "复仇": "revenge",
    "悬疑": "suspense",
    "惊悚": "suspense",
    "推理": "suspense",
    "家庭伦理": "family",
    "家庭": "family",
    "男频": "male-progression",
    "男频升级": "male-progression",
    "升级": "male-progression",
    "都市异能": "urban-ability",
    "脑洞": "brainhole",
    "现代言情": "romance",
    "现代": "romance",
    "娱乐圈": "romance",
}

FUNCTION_MODULES = {
    "opening": [],
    "hook": ["hook"],
    "付费点": ["hook"],
    "cliffhanger": ["hook"],
    "rule-reveal": [],
    "reversal": ["reversal"],
    "反转": ["reversal"],
    "satisfaction": ["satisfaction"],
    "爽点": ["satisfaction"],
    "abuse": ["abuse"],
    "虐点": ["abuse"],
    "expand": ["expand"],
    "扩写": ["expand"],
    "compress": ["compress"],
    "压缩": ["compress"],
    "audiovisual": ["audiovisual"],
    "视听": ["audiovisual"],
}

OPERATION_MODULES = {
    "compress-without-breaking-causality": ["compress"],
    "compress": ["compress"],
    "expand": ["expand"],
    "hook": ["hook"],
    "reversal": ["reversal"],
    "satisfaction": ["satisfaction"],
    "audiovisual": ["audiovisual"],
}

KNOWN_CRAFT_MODULES = {
    "hook",
    "reversal",
    "satisfaction",
    "abuse",
    "expand",
    "compress",
    "audiovisual",
}


def _read_text(relative: str) -> str:
    path = references_dir() / relative
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def genre_modules(genres: list[str]) -> list[str]:
    result: list[str] = []
    for genre in genres:
        mapped = GENRE_ALIASES.get(str(genre).strip(), str(genre).strip().lower())
        if mapped not in result:
            result.append(mapped)
    return result


def select_craft_modules(
    config: dict | None = None,
    outline: dict | None = None,
    operation: str | None = None,
) -> list[str]:
    """Select craft modules on demand. Never returns all modules."""
    config = config or {}
    outline = outline or {}
    modules = list(ALWAYS_MODULES)
    for genre in genre_modules(config.get("genre", []) or []):
        if genre not in modules:
            modules.append(genre)
    for function in outline.get("episode_function", []) or []:
        for module in FUNCTION_MODULES.get(str(function), []):
            if module not in modules:
                modules.append(module)
    op = operation or outline.get("operation")
    if op:
        for module in OPERATION_MODULES.get(str(op), []):
            if module not in modules:
                modules.append(module)
    return modules


def load_craft_prompt(module: str) -> str:
    """Load a genre or craft module prompt; unknown modules return empty."""
    candidates = [
        f"genres/{module}.md",
        f"craft/{module}.md",
        f"genres/{module}.md",
    ]
    for candidate in candidates:
        text = _read_text(candidate)
        if text:
            return f"## Craft 模块：{module}\n{text}"
    return ""


def _stage_prompt(role: str) -> str:
    mapping = {
        "writer": "prompts/writer.md",
        "reviewer": "prompts/reviewer.md",
        "rewriter": "prompts/rewriter.md",
        "requirements": "prompts/stage_requirements.md",
        "events": "prompts/stage_events.md",
        "adaptation": "prompts/stage_adaptation.md",
        "story_outline": "prompts/stage_story_outline.md",
        "episode_outline": "prompts/stage_episode_outline.md",
        "continuity_extract": "prompts/continuity_extract.md",
    }
    return _read_text(mapping.get(role, "prompts/writer.md"))


def _project_section(config: dict, outline: dict | None = None, *, role: str = "writer") -> str:
    brief = config or {}
    lines = [
        "## 项目需求",
        f"- 剧名：{brief.get('drama_name', '未定')}",
        f"- 题材：{'、'.join(brief.get('genre', []) or [])}",
        f"- 平台：{brief.get('platform', '未指定')}",
        f"- 画幅：{brief.get('aspect_ratio', '未指定')}",
        f"- 忠实度：{brief.get('fidelity', 'medium')}",
        f"- 台词策略：{brief.get('dialogue_policy', 'prefer_original')}",
        f"- 编剧最终决定权：{bool(brief.get('writer_has_final_authority', True))}",
    ]
    if brief.get("must_keep"):
        lines.append("- 编剧要求保留：" + "；".join(brief["must_keep"]))
    if brief.get("forbidden_changes"):
        lines.append("- 编剧禁止改动：" + "；".join(brief["forbidden_changes"]))
    if outline:
        lines.append(f"- 本集建议时长：{outline.get('suggested_seconds') or '未定'}（仅预期）")
    project_rules = config.get("project_specific_requirements", []) or []
    rule_refs = (outline or {}).get("project_rule_refs", []) or []
    selected_rules = [
        item for item in project_rules
        if isinstance(item, dict) and item.get("id") in rule_refs
    ]
    if selected_rules:
        if role == "writer":
            from .execution_brief import sanitize_writer_text

            selected_rules = [
                {**item, "text": sanitize_writer_text(item.get("text", ""))}
                for item in selected_rules
            ]
        lines.extend(["", "当前项目已引用规则（只加载本集引用项）："])
        for item in selected_rules:
            lines.append(f"- {item.get('id')}：{item.get('text', '')}")
    return "\n".join(lines)


def _contract_section(outline: dict, context: dict | None = None, *, role: str = "writer") -> str:
    from .common import canonical_json

    if role == "writer" and context and context.get("episode_execution_brief"):
        return (
            "## 本集执行任务（episode_execution_brief）\n"
            "只执行以下任务；其中的容量、时长和批次信息是编排提示，不能替代编剧判断。\n"
            + canonical_json(context["episode_execution_brief"])
        )
    return (
        "## 当前集创作契约（episode_contract）\n"
        "你只执行本集契约，不重新设计全剧。\n"
        + canonical_json(outline)
    )


def _evidence_section(evidence: dict) -> str:
    from .common import canonical_json

    parts = [
        "## 原文证据（source_evidence）",
        f"覆盖章节：{evidence.get('chapter_ids') or []}",
        f"检索报告：{canonical_json(evidence.get('retrieval_report', {}))}",
    ]
    for excerpt in evidence.get("raw_excerpts", []) or []:
        parts.append(
            f"\n### 摘录 第{excerpt.get('chapter_id')}章 {excerpt.get('chapter_title', '')} "
            f"（span {excerpt.get('source_span', {})}，{excerpt.get('reason', '')}）\n{excerpt.get('text', '')}"
        )
    for quote in evidence.get("quotes", []) or []:
        parts.append(f"- 原句 {quote.get('speaker', '?')}：{quote.get('text', '')}（{quote.get('source', '') or quote.get('chapter_id', '')}）")
    return "\n".join(parts)


def _continuity_section(context: dict) -> str:
    from .common import canonical_json

    continuity = context.get("continuity_state", {})
    parts = [
        "## 连续性与编剧覆盖",
        f"已确认集：{sorted(continuity.get('approved_episodes', []))}",
        f"人物已知信息：{canonical_json(continuity.get('character_knowledge', {}))}",
        f"已发生事实：{canonical_json(continuity.get('facts', []))}",
        f"开放钩子：{canonical_json(continuity.get('open_hooks', []))}",
    ]
    previous = context.get("previous_approved_script")
    if previous:
        parts.append(f"\n### 上一集确认剧本（必须承接）\n{previous}")
    if context.get("previous_episode_hook"):
        parts.append(f"\n上一集钩子：{context['previous_episode_hook']}")
    if context.get("writer_overrides"):
        parts.append("\n### 编剧最新指令\n" + "\n".join(
            f"- {o.get('instruction', '')}" for o in context.get("writer_overrides", [])
        ))
    provisional = context.get("provisional_batch_context")
    if provisional:
        parts.append(
            "\n### 同批临时上下文（未确认，不得写入正式连续性）\n"
            + canonical_json(provisional)
        )
    return "\n".join(parts)


def _advisory_section(context: dict) -> str:
    from .common import canonical_json

    advisory = context.get("advisory_timing", {}) or {}
    parts = [
        "## 容量与时长提示（advisory_only，不阻断）",
        f"最低时长：{advisory.get('minimum_seconds')} 秒；建议时长：{advisory.get('preferred_seconds') or advisory.get('outline_suggested_seconds') or '未定'} 秒",
    ]
    density = advisory.get("density_report") or {}
    if density:
        parts.append(
            f"本集容量压力：{density.get('pressure')}"
            f"（事件最低 {density.get('minimum_event_seconds')} 秒，"
            f"偏好 {density.get('preferred_event_seconds')} 秒，置信度 {density.get('confidence')}）"
        )
        if density.get("binding"):
            parts.append(
                "容量绑定：集纲 "
                f"{density.get('binding', {}).get('outline_version')} / "
                f"{str(density.get('binding', {}).get('outline_hash') or '')[:12]}"
            )
    if context.get("draft_metrics"):
        parts.append(
            "草稿确定性时长指标（系统计算，Reviewer 不得猜测或覆盖）：\n"
            + canonical_json(context["draft_metrics"])
        )
    if context.get("draft_quality"):
        parts.append(
            "草稿质量信号（系统计算；Reviewer 必须逐项确认/反驳，不得自行改写数值）：\n"
            + canonical_json(context["draft_quality"])
        )
    plan = context.get("capacity_plan") or {}
    if plan:
        action = plan.get("overflow_action") or ""
        parts.append(
            "容量取舍计划（已绑定编剧选择）："
            f"{plan.get('priority_mode')} / {plan.get('coverage_mode')}；"
            f"溢出策略 {action or '按计划执行'}。"
        )
        if action == "accept_overflow":
            parts.append("该计划明确接受超出原偏好时长的内容，不再要求机械压回原区间。")
    return "\n".join(parts)


def assemble_prompt_layers(
    context: dict,
    *,
    role: str = "writer",
    config: dict | None = None,
) -> dict[str, str]:
    """Assemble the seven prompt layers for one episode context snapshot."""
    config = config or context.get("project_brief", {})
    outline = context.get("episode_outline", {})
    layers = {
        "system_base": _read_text("prompts/system_base.md"),
        "stage_role": _stage_prompt(role),
        "project": _project_section(config, outline, role=role),
        "contract": _contract_section(outline, context, role=role),
        "evidence": _evidence_section(context.get("source_evidence", {})),
        "continuity": _continuity_section(context),
        "advisory": _advisory_section(context),
    }
    craft_parts = []
    for module in context.get("selected_craft_modules", []) or []:
        text = load_craft_prompt(module)
        if text:
            craft_parts.append(text)
    layers["craft"] = "\n\n".join(craft_parts)
    layers["review"] = ""
    if role == "rewriter" and context.get("review_report"):
        from .common import canonical_json

        layers["review"] = (
            "## 审核报告（只修复以下明确问题，不得另写一版）\n"
            + canonical_json(context["review_report"])
        )
    return layers


def render_prompt_bundle(
    context: dict,
    *,
    role: str = "writer",
    config: dict | None = None,
) -> str:
    """Render a single host-agent-readable prompt bundle."""
    layers = assemble_prompt_layers(context, role=role, config=config)
    header = (
        "# Fangcun Next 单集上下文（Host Agent Mode）\n"
        f"- 集数：{context.get('episode')}\n"
        f"- 角色：{role}\n"
        f"- context_hash：{context.get('context_hash')}\n"
        f"- 上下文快照文件：{context.get('context_file', '')}\n"
        "\n你必须消费本文件中与快照一致的上下文。只输出产物，不输出审核说明。\n"
    )
    return "\n\n".join(
        [
            header,
            layers["system_base"],
            layers["stage_role"],
            layers["project"],
            layers["contract"],
            layers["evidence"],
            layers["continuity"],
            layers["advisory"],
            layers["craft"],
            layers["review"],
        ]
    )
