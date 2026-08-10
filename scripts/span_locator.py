"""Event-extraction span-location helper (P1/P2, local-only).

半自动锚点定位：给原文片段自动计算 Python 字符串坐标（0-based、左闭右开），
替代事件提取时手工数坐标，从源头减少 span 返工与由此引发的上游 v002 重绑。

约定与 `references/prompts/stage_events.md` 一致：
- coordinate_base = "chapter_file_content"（章节文件正文，不含标题行）；
- 找不到时返回 `suggest: "needs_reanchor"`，禁止猜坐标；
- 可选弱匹配（--fuzzy）只容忍空白差异（全角/半角空格、换行），不做语义改写。
"""

from __future__ import annotations

from typing import Any


def normalize_text(text: str) -> str:
    """折叠所有空白（含全角空格、换行），用于弱匹配坐标映射。"""
    return "".join(text.split())


def _find_occurrence(haystack: str, needle: str, occurrence: int) -> int | None:
    start = -1
    for _ in range(occurrence):
        start = haystack.find(needle, start + 1)
        if start == -1:
            return None
    return start


def _locate_exact(text: str, needle: str, occurrence: int) -> tuple[int, int] | None:
    start = _find_occurrence(text, needle, occurrence)
    if start is None:
        return None
    return (start, start + len(needle))


def _locate_fuzzy(text: str, needle: str, occurrence: int) -> tuple[int, int] | None:
    """弱匹配：原文与片段均折叠空白后查找，再把归一化坐标映射回原文坐标。"""
    normalized_needle = normalize_text(needle)
    if not normalized_needle:
        return None
    positions = [i for i, ch in enumerate(text) if not ch.isspace()]
    normalized_text = "".join(text[i] for i in positions)
    start_n = _find_occurrence(normalized_text, normalized_needle, occurrence)
    if start_n is None:
        return None
    start = positions[start_n]
    end = positions[start_n + len(normalized_needle) - 1] + 1
    return (start, end)


def locate_span(
    chapter_text: str,
    needle: str,
    *,
    occurrence: int = 1,
    fuzzy: bool = False,
) -> dict[str, Any]:
    """在章节正文中定位一个原文片段。

    Returns:
        found=True: {"found", "span": {"start","end"}, "source_quote",
                     "coordinate_base", "occurrence", "matches"}
        found=False: {"found", "reason", "suggest": "needs_reanchor", "matches"}
    """
    if not chapter_text or not needle:
        return {
            "found": False,
            "reason": "empty_input",
            "suggest": "needs_reanchor",
            "matches": 0,
        }
    if occurrence < 1:
        occurrence = 1
    span = _locate_exact(chapter_text, needle, occurrence)
    if span is None and fuzzy:
        span = _locate_fuzzy(chapter_text, needle, occurrence)
    if span is None:
        return {
            "found": False,
            "reason": "not_found",
            "suggest": "needs_reanchor",
            "matches": chapter_text.count(needle),
        }
    start, end = span
    return {
        "found": True,
        "span": {"start": start, "end": end},
        "source_quote": chapter_text[start:end],
        "coordinate_base": "chapter_file_content",
        "occurrence": occurrence,
        "matches": chapter_text.count(needle),
    }
