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
    format_profile: str = "default-cn",
    xml: bool = False,
) -> str:
    """Merge approved/draft scripts into one export (business or XML-wrapped)."""
    parts: list[str] = []
    for episode, text in sorted(scripts):
        report = validate_script(text, format_profile=format_profile, expected_episode=episode)
        if not report["ok"]:
            raise ValueError(f"第{episode}集格式未通过，无法导出：{report['errors'][0]['message']}")
        body = business_format(text, format_profile)
        if xml and format_profile != "legacy-scriptitem":
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
    return "\n".join(lines) + "\n"

