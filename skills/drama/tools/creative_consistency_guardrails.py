#!/usr/bin/env python3
"""Project-rule creative consistency guardrails.

Catches common Fangcun regressions:
- user-deleted/forbidden characters reappear;
- repeatedly required key characters disappear from later outputs;
- source-faithfulness demands lack an explicit source-basis checklist.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NAME_RE = r"(?:[A-Za-z][A-Za-z0-9_·-]{1,20}|[\u4e00-\u9fa5]{2,4})"
FORBIDDEN_PATTERNS = [
    re.compile(rf"(?:删除|删掉|删去|去掉|不要|禁止|不能出现|不得出现)的?(?:人物|角色|人名)?[：:\s]*({NAME_RE})(?:这个人物|这个角色)?(?=[，。；;、\s]|$)"),
    re.compile(rf"({NAME_RE})(?:这个人物|这个角色)?(?:删除|删掉|删去|去掉|不要再出现|禁止出现|不得出现|不能出现)"),
]
REQUIRED_PATTERNS = [
    re.compile(rf"(?:反复强调|强调|必须|需要|保留|强化)[^。；;\n]{{0,8}}?({NAME_RE})(?:作为|承担|保持|的)[^。；;\n]{{0,40}}(?:作用|贯穿|监督|质疑|线索|主线|核心)"),
    re.compile(rf"(?:^|[，。；;\s\]）)])({NAME_RE})[^。；;\n]{{0,12}}(?:作为|承担|保持)[^。；;\n]{{0,30}}(?:监督|质疑|线索|主线|核心)[^。；;\n]{{0,12}}(?:贯穿|作用)"),
]
SOURCE_FAITHFUL_RE = re.compile(r"贴合原著|原著|原文|禁止原创|不能原创|不要原创|不得原创|忠于原文|source[- ]?faithful", re.I)
KNOWLEDGE_VERBS_RE = re.compile(r"知道|得知|发现|看出|识破|意识到|明白|获悉|听说")
KNOWLEDGE_TIMELINE_PATTERNS = [
    re.compile(rf"({NAME_RE})[^。；;\n]{{0,20}}(?:后面|后|第?\s*\d+\s*多?\s*章|\d+\s*多?\s*章后)[^。；;\n]{{0,20}}才(?:知道|得知|发现|意识到|明白)([^。；;\n]{{1,30}})"),
    re.compile(rf"(?:不要|不能|不得|禁止|不准)[^。；;\n]{{0,12}}提前(?:让)?({NAME_RE})(?:知道|得知|发现|意识到|明白)([^。；;\n]{{1,30}})"),
    re.compile(rf"({NAME_RE})[^。；;\n]{{0,12}}(?:什么时候|何时)(?:知道|得知|发现|意识到|明白)([^。；;\n]{{1,30}})(?:根据|按照|跟着|依照)小说"),
]


def _unique(items: list[str]) -> list[str]:
    seen = set(); out = []
    for x in items:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out


def extract_forbidden_names(rules_text: str) -> list[str]:
    names: list[str] = []
    for line in (rules_text or "").splitlines():
        for pat in FORBIDDEN_PATTERNS:
            names.extend(m.group(1) for m in pat.finditer(line))
    return _unique(names)


def extract_required_names(rules_text: str) -> list[str]:
    names: list[str] = []
    for line in (rules_text or "").splitlines():
        for pat in REQUIRED_PATTERNS:
            names.extend(m.group(1) for m in pat.finditer(line))
    # Avoid extracting generic words if any slip through.
    stop = {"这个", "人物", "角色", "原著", "原文", "用户", "编剧", "项目", "反复强调", "强调", "必须", "需要", "保留", "强化"}
    return [n for n in _unique(names) if n not in stop]



def _fact_keywords(text: str) -> list[str]:
    """Extract compact fact keywords from a knowledge-timeline rule."""
    raw = str(text or "")
    raw = re.sub(r"^(女主|男主|她|他|这个|这件事|了|的|，|,|：|:|\s)+", "", raw)
    candidates = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}", raw)
    stop = {"根据小说", "按照小说", "这个事情", "这件事情", "时候", "什么样", "大事", "后面", "后续", "原著"}
    out: list[str] = []
    for item in candidates:
        if item in stop:
            continue
        # Split common long phrases into semantically useful fragments too.
        out.append(item)
        if "生病" in item:
            out.append("生病")
        if "怀孕" in item:
            out.append("怀孕")
        if "身份" in item:
            out.append("身份")
    return _unique([x for x in out if len(x) >= 2])[:5]


def extract_knowledge_timeline_rules(rules_text: str) -> list[dict[str, object]]:
    """Extract rules such as “Sunny 后100多章才知道女主生病”."""
    rules: list[dict[str, object]] = []
    for line in (rules_text or "").splitlines():
        clean = re.sub(r"^[-*]\s*", "", line).strip()
        if not clean:
            continue
        for pat in KNOWLEDGE_TIMELINE_PATTERNS:
            for m in pat.finditer(clean):
                name = m.group(1)
                fact = m.group(2).strip(" ：:，。；;,.!！?？")
                keywords = _fact_keywords(fact)
                if name and keywords:
                    rules.append({"name": name, "fact": fact, "keywords": keywords, "evidence": clean[:160]})
    # de-dupe by name+keywords
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[dict[str, object]] = []
    for item in rules:
        key = (str(item["name"]), tuple(item["keywords"]))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _violates_knowledge_timeline(text: str, name: str, keywords: list[str]) -> bool:
    """Best-effort scan: the protected character is shown knowing/discovering the protected fact."""
    if not name or name not in text:
        return False
    for line in (text or "").splitlines():
        if name not in line:
            continue
        if not any(k in line for k in keywords):
            continue
        if KNOWLEDGE_VERBS_RE.search(line) or re.search(r"[：:]", line):
            return True
    # Cross-line fallback: same short window has name + knowledge verb + fact keyword.
    compact = re.sub(r"\s+", "", text or "")
    for kw in keywords:
        if re.search(re.escape(name) + r".{0,50}" + KNOWLEDGE_VERBS_RE.pattern + r".{0,50}" + re.escape(kw), compact):
            return True
        if re.search(re.escape(name) + r".{0,50}" + re.escape(kw) + r".{0,50}" + KNOWLEDGE_VERBS_RE.pattern, compact):
            return True
    return False

def validate_creative_consistency(content: str, rules_text: str = "") -> dict[str, object]:
    text = content or ""
    rules = rules_text or ""
    issues: list[dict[str, object]] = []

    for name in extract_forbidden_names(rules):
        if name in text:
            issues.append({
                "type": "forbidden_character_reappears",
                "severity": "error",
                "name": name,
                "message": f"用户/项目规则已删除或禁止角色「{name}」，但本次产出仍出现该角色。",
            })

    for name in extract_required_names(rules):
        if name not in text:
            issues.append({
                "type": "required_character_missing",
                "severity": "error",
                "name": name,
                "message": f"用户/项目规则强调角色「{name}」需承担贯穿作用，但本次产出未出现。",
            })

    body_for_timeline = text.split("项目规则落实清单", 1)[0]
    for rule in extract_knowledge_timeline_rules(rules):
        name = str(rule.get("name") or "")
        keywords = [str(x) for x in rule.get("keywords", [])]
        if _violates_knowledge_timeline(body_for_timeline, name, keywords):
            issues.append({
                "type": "character_knowledge_timeline_violation",
                "severity": "error",
                "name": name,
                "keywords": keywords,
                "message": f"项目规则限定角色「{name}」的知情时间线，但本次产出疑似让其提前知道/发现「{'/'.join(keywords)}」。人物何时知道重大信息必须按原著和项目规则推进。",
            })

    if SOURCE_FAITHFUL_RE.search(rules) and not re.search(r"原文依据|原著依据|改编依据|source basis|source evidence", text, re.I):
        issues.append({
            "type": "missing_source_basis_checklist",
            "severity": "warning",
            "message": "项目规则要求贴合原著/禁止原创，但产出缺少『原文依据/原著依据/改编依据』说明，无法核对新增情节和台词来源。",
        })

    return {"ok": not any(i.get("severity") == "error" for i in issues), "issue_count": len(issues), "issues": issues}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate creative consistency against project rules")
    ap.add_argument("content")
    ap.add_argument("--rules", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    content = Path(args.content).read_text(encoding="utf-8")
    rules = Path(args.rules).read_text(encoding="utf-8")
    result = validate_creative_consistency(content, rules)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
