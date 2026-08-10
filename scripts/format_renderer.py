"""Business screenplay format ↔ platform transport format (spec §19).

Writer always emits one business format. XML is an optional adapter wrapper,
never maintained by the Writer prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

from .common import assets_dir, read_json
from .script_validator import validate_script


XML_WRAP_RE = re.compile(r"^<scriptItem name=\"([^\"]*)\">\s*(.*?)\s*</scriptItem>\s*$", re.DOTALL)


def load_template(name: str) -> str:
    path = assets_dir() / "screenplay-templates" / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def business_format(script_text: str, format_profile: str = "default-cn") -> str:
    """Return the business-format body (unwrap XML when needed)."""
    if format_profile == "legacy-scriptitem":
        match = XML_WRAP_RE.fullmatch(script_text.strip())
        if match:
            return match.group(2).strip() + "\n"
    return script_text.strip() + "\n"


def wrap_xml(script_text: str, title: str) -> str:
    """Wrap business text in the legacy <scriptItem> transport format."""
    body = business_format(script_text).strip()
    return f'<scriptItem name="{title}">\n{body}\n</scriptItem>'


def render_export(
    project_dir: Path,
    scripts: list[tuple[int, str]],
    *,
    transport_format: str = "plain",
    xml: bool = False,
) -> str:
    """Merge approved/draft scripts into one export (business or XML-wrapped)."""
    parts: list[str] = []
    for episode, text in sorted(scripts):
        report = validate_script(text, format_profile="default-cn", expected_episode=episode)
        if not report["ok"]:
            raise ValueError(f"第{episode}集格式未通过，无法导出：{report['errors'][0]['message']}")
        body = business_format(text)
        if xml or transport_format == "legacy-scriptitem":
            body = wrap_xml(body, f"EP{episode:03d}")
        parts.append(body.strip())
    return "\n\n".join(parts) + "\n"


def render_project_brief_markdown(config: dict) -> str:
    """Human-readable project brief from project config."""
    lines = [
        f"# 项目需求：{config.get('drama_name', '未定')}",
        "",
        f"- 原著：{config.get('novel_name', '')}",
        f"- 题材：{'、'.join(config.get('genre', []) or [])}",
        f"- 平台：{config.get('platform', '')}（{config.get('aspect_ratio', '')}）",
        f"- 初始集数：{config.get('initial_episode_count', '未定')}",
        f"- 单集最低时长：{config.get('minimum_episode_seconds', 0)} 秒",
        f"- 建议单集时长：{config.get('preferred_episode_seconds') or '未定'} 秒",
        f"- 抵达原著结局：{'是' if config.get('reach_original_ending') else '未要求'}",
        f"- 忠实度：{config.get('fidelity', 'medium')}",
        f"- 台词策略：{config.get('dialogue_policy', 'prefer_original')}",
        f"- 编剧最终决定权：{'是' if config.get('writer_has_final_authority') else '否'}",
    ]
    if config.get("must_keep"):
        lines.extend(["", "编剧要求保留：", *[f"- {x}" for x in config["must_keep"]]])
    if config.get("forbidden_changes"):
        lines.extend(["", "编剧禁止改动：", *[f"- {x}" for x in config["forbidden_changes"]]])
    if config.get("pending_confirmation"):
        lines.extend(["", "待确认事项：", *[f"- {x}" for x in config["pending_confirmation"]]])
    if config.get("content_distribution_notes"):
        lines.extend(["", "内容分配偏好：", *[f"- {x}" for x in config["content_distribution_notes"]]])
    if config.get("episode_timing_overrides"):
        lines.extend(["", "局部集数时长/内容权重："])
        for item in config["episode_timing_overrides"]:
            lines.append(
                f"- EP{item.get('start_episode')}–EP{item.get('end_episode')}："
                f"{item.get('preferred_seconds') or '沿用全局区间'} / {item.get('content_weight', 'normal')}"
                f"；{item.get('note', '')}"
            )
    if config.get("planning_checkpoints"):
        lines.extend(["", "编剧指定剧情检查点："])
        for item in config["planning_checkpoints"]:
            lines.append(f"- EP{item.get('episode')}：{item.get('expectation')}")
    return "\n".join(lines) + "\n"


def render_episode_outline_markdown(episodes: list[dict], density_reports: list[dict] | None = None) -> str:
    """Render the JSON source of truth into an always-synchronized writer view."""
    reports = {int(item.get("episode", 0)): item for item in (density_reports or [])}
    lines = ["# 分集纲要", ""]
    for outline in sorted(episodes, key=lambda item: int(item.get("episode", 0))):
        episode = int(outline.get("episode", 0))
        lines.extend(
            [
                f"## 第{episode}集：{outline.get('title', '')}",
                "",
                f"- 本集目标：{outline.get('episode_goal', '')}",
                f"- 开场承接：{outline.get('opening_bridge', '')}",
                f"- 集末钩子：{outline.get('ending_hook', '')}",
                f"- 原文事件：{', '.join(outline.get('source_event_ids', []) or []) or '改编决策驱动'}",
                f"- 原文章节：{', '.join(str(x) for x in (outline.get('source_chapters', []) or [])) or '无'}",
            ]
        )
        if outline.get("episode_focus"):
            lines.append(f"- 本集记忆点：{outline.get('episode_focus')}")
        if outline.get("project_rule_refs"):
            lines.append(f"- 项目规则引用：{', '.join(outline.get('project_rule_refs', []))}")
        if outline.get("suggested_seconds"):
            seconds = outline["suggested_seconds"]
            lines.append(f"- 建议时长：{seconds[0]}–{seconds[-1]} 秒（仅供编剧判断）")
        report = reports.get(episode)
        if report:
            lines.append(
                f"- 容量压力：{report.get('pressure')}（事件最低 {report.get('minimum_event_seconds')} 秒，"
                f"偏好 {report.get('preferred_event_seconds')} 秒；不作硬门禁）"
            )
        lines.extend(["", "必保留："])
        for item in outline.get("must_keep", []) or []:
            text = item.get("text") if isinstance(item, dict) else item
            lines.append(f"- {text}")
        if outline.get("required_story_beats"):
            lines.extend(["", "必须发生的剧情变化（required_story_beats）："])
            for beat in outline["required_story_beats"]:
                lines.append(f"- {beat.get('text')}")
        if outline.get("required_quotes"):
            lines.extend(["", "必须保留的台词（required_quotes）："])
            for item in outline["required_quotes"]:
                lines.append(f"- {item.get('quote')}")
        if outline.get("optional_beats"):
            lines.extend(["", "可选内容（可压缩/删除/延后）："])
            for beat in outline["optional_beats"]:
                lines.append(f"- {beat.get('text')}")
        lines.extend(["", "因果链："])
        for chain in outline.get("causal_chains", []) or []:
            lines.append("- " + " → ".join(str(part) for part in chain))
        if outline.get("dialogue_anchors"):
            lines.extend(["", "台词锚点："])
            for anchor in outline["dialogue_anchors"]:
                if anchor.get("type") == "quote":
                    lines.append(f"- 原句：{anchor.get('quote')}")
                else:
                    lines.append(f"- {anchor.get('setup') or ''} → {anchor.get('payoff') or ''}")
        if outline.get("beat_plan"):
            lines.extend(["", "Beat 呈现计划："])
            for beat in outline["beat_plan"]:
                lines.append(
                    f"- {beat.get('beat_id')}：{beat.get('function')} "
                    f"（{beat.get('presentation', 'full')}；{beat.get('visible_outcome', '')}）"
                )
                if beat.get("required_visual_beats"):
                    lines.append(f"  - 关键视觉落点：{'；'.join(beat['required_visual_beats'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
