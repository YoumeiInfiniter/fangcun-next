#!/usr/bin/env python3
"""Dialogue style guardrails: detect AI-ish / essay-like short-drama lines."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIALOGUE_RE = re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{0,12})(?:VO|OS)?(?:（[^）]{1,20}）)?[：:](?P<text>.+?)\s*$")
AI_CLICHES = [
    "命运的齿轮", "不再是从前", "这一刻", "你可曾想过", "我再也不是", "从今天起", "属于我的一切", "终将付出代价",
    "这一次我要", "你们所有人", "我会让你知道", "我倒要看看", "别怪我不客气", "我一定会证明", "拭目以待",
    "你根本不懂", "你知道什么", "这一切都是", "我所承受的", "血债血偿", "天道轮回",
]
ESSAY_PATTERNS = [
    re.compile(r"因为.{0,18}所以"),
    re.compile(r"不只是.{0,18}更是"),
    re.compile(r"从某种意义上"),
    re.compile(r"换句话说"),
    re.compile(r"你要明白"),
]


def validate_dialogue_style(text: str) -> dict[str, object]:
    issues: list[dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        m = DIALOGUE_RE.match(line)
        if not m:
            continue
        dialogue = m.group("text").strip()
        if len(dialogue) > 28 and not any(mark in dialogue for mark in "？！!?…"):
            issues.append({
                "type": "long_flat_dialogue",
                "severity": "warning",
                "line": line_no,
                "message": "台词偏长且缺少口语停顿/情绪切口，疑似书面化；短剧台词建议≤20字，长句拆成动作+短句。",
                "text": dialogue[:120],
            })
        for phrase in AI_CLICHES:
            if phrase in dialogue:
                issues.append({
                    "type": "ai_cliche_dialogue",
                    "severity": "warning",
                    "line": line_no,
                    "phrase": phrase,
                    "message": "命中高频AI腔/口号式台词，请改成角色当下能说出口的短句。",
                    "text": dialogue[:120],
                })
        for pattern in ESSAY_PATTERNS:
            if pattern.search(dialogue):
                issues.append({
                    "type": "essay_dialogue",
                    "severity": "warning",
                    "line": line_no,
                    "message": "台词像解释性文章，不像真人对话；请改为试探、压迫、反击、隐瞒等具体意图短句。",
                    "text": dialogue[:120],
                })
    return {"ok": True, "issue_count": len(issues), "issues": issues}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate dialogue style guardrails")
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    p = Path(args.path)
    result = validate_dialogue_style(p.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"OK: {p} dialogue style guardrails, issues={result['issue_count']}")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
