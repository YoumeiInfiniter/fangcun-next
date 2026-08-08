#!/usr/bin/env python3
"""Dialogue/localization culture guardrails for overseas short-drama outputs."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

OVERSEAS_MARKERS = re.compile(r"海外|北美|欧美|美国|英国|加拿大|澳洲|英语|English|US|USA|America|Western|西方", re.I)

# Chinese institution / address forms that are usually wrong in US/Western settings.
HIGH_RISK_TERMS = [
    (re.compile(r"[\u4e00-\u9fa5]{1,3}队长"), "海外警务/职场语境不要保留中文‘X队长’称呼；按地区改为 Detective/Officer/Captain/Chief/Sergeant 或角色名。"),
    (re.compile(r"[\u4e00-\u9fa5]{1,3}局长"), "海外警务/政府语境不要保留中文‘X局长’；按地区改为 Chief/Commissioner/Director 等。"),
    (re.compile(r"派出所|公安局|公安|民警|刑警队|城管|居委会|街道办|户口本|户籍|身份证号"), "海外文化背景下出现中国制度/机构词，需要替换为目标地区对应机构或改写情节。"),
]

US_POLICE_SUGGESTIONS = {
    "队长": "Captain / Sergeant / Detective（按职责选择）",
    "局长": "Police Chief / Commissioner",
    "派出所": "precinct / police station",
    "公安": "police / law enforcement",
    "民警": "officer",
    "刑警": "detective",
}


def should_apply(text: str, locale: str = "") -> bool:
    return bool(OVERSEAS_MARKERS.search(locale or "") or OVERSEAS_MARKERS.search(text or ""))


def validate_localization(text: str, locale: str = "") -> dict[str, object]:
    issues: list[dict[str, object]] = []
    if not should_apply(text, locale):
        return {"ok": True, "issue_count": 0, "issues": issues, "applied": False}
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for pattern, message in HIGH_RISK_TERMS:
            for m in pattern.finditer(line):
                term = m.group(0)
                suggestions = [v for k, v in US_POLICE_SUGGESTIONS.items() if k in term]
                issues.append({
                    "type": "culture_mismatch",
                    "severity": "error",
                    "line": line_no,
                    "term": term,
                    "message": message,
                    "suggestion": suggestions[0] if suggestions else "按目标地区建立术语表/人名表后替换。",
                    "text": line.strip()[:180],
                })
    return {"ok": not issues, "issue_count": len(issues), "issues": issues, "applied": True}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate localization/culture terms in overseas scripts/translations")
    ap.add_argument("path")
    ap.add_argument("--locale", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    p = Path(args.path)
    result = validate_localization(p.read_text(encoding="utf-8"), args.locale)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "OK" if result["ok"] else "FAILED"
        print(f"{status}: {p} localization guardrails, issues={result['issue_count']}, applied={result['applied']}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
