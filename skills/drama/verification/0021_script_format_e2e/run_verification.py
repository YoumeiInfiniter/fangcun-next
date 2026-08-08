#!/usr/bin/env python3
"""0021 剧本场次格式端到端验证脚本。

运行位置：仓库根目录或本目录均可。
输出：reports/verification_report.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[4]
TOOLS = WORKSPACE / "skills" / "fangcun" / "skills" / "drama" / "tools"
if not TOOLS.exists():
    # FangcunSkills 仓库根结构：skills/drama/tools
    WORKSPACE = ROOT.parents[3]
    TOOLS = WORKSPACE / "skills" / "drama" / "tools"
sys.path.insert(0, str(TOOLS))

from agent_tools import validate_script  # noqa: E402

ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

CASES = [
    {
        "name": "good_combined_heading",
        "file": ARTIFACTS / "script_ep001_good.txt",
        "expect_pass": True,
        "must_contain": [],
    },
    {
        "name": "bad_bracket_explanatory_title",
        "file": ARTIFACTS / "script_ep001_bad_bracket.txt",
        "expect_pass": False,
        "must_contain": ["第一集第一场"],
    },
    {
        "name": "bad_legacy_split_heading",
        "file": ARTIFACTS / "script_ep001_bad_legacy.txt",
        "expect_pass": False,
        "must_contain": ["旧场次格式", "缺少规范场次标题"],
    },
    {
        "name": "bad_literary_non_visual_action",
        "file": ARTIFACTS / "script_ep001_bad_literary.txt",
        "expect_pass": False,
        "must_contain": ["导演拍不出来"],
    },
]


def main() -> int:
    results = []
    ok = True
    for case in CASES:
        text = case["file"].read_text(encoding="utf-8")
        issues = validate_script(text, target_words=360)
        severe = [i for i in issues if i.startswith("严重")]
        passed = not severe
        contains_ok = all(any(token in issue for issue in issues) for token in case["must_contain"])
        case_ok = (passed == case["expect_pass"]) and contains_ok
        ok = ok and case_ok
        results.append({
            "name": case["name"],
            "file": str(case["file"].relative_to(ROOT)),
            "expected": "pass" if case["expect_pass"] else "fail",
            "actual": "pass" if passed else "fail",
            "case_ok": case_ok,
            "issues": issues,
        })

    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S GMT+8")
    report = [
        "# 0021 剧本场次格式 E2E 验证报告",
        "",
        f"- 生成时间：{now}",
        "- 验证对象：Fangcun `validate_script()` + 剧本格式 prompt",
        "- 目标格式：`1-1　怪力乱神管理局 大会场　日　内`",
        "- 禁止格式：`【第一集第一场】`、`1-1` 单独行 + `场：地点-时间-内外`",
        "",
        "## 使用流程与中间产物",
        "",
        "1. 需求确认：`inputs/requirements_confirmation.md`",
        "2. 测试原文：`source/novel_excerpt.md`",
        "3. 改编指引：`artifacts/adaptation_strategy.md`",
        "4. 故事大纲：`artifacts/story_outline.md`",
        "5. 集纲：`artifacts/story_skeleton.md`",
        "6. 正确剧本样例：`artifacts/script_ep001_good.txt`",
        "7. 错误样例 A：`artifacts/script_ep001_bad_bracket.txt`",
        "8. 错误样例 B：`artifacts/script_ep001_bad_legacy.txt`",
        "9. 错误样例 C：`artifacts/script_ep001_bad_literary.txt`",
        "",
        "## 自动验证结果",
        "",
    ]
    for item in results:
        mark = "✅" if item["case_ok"] else "❌"
        report += [
            f"### {mark} {item['name']}",
            "",
            f"- 文件：`{item['file']}`",
            f"- 预期：{item['expected']}",
            f"- 实际：{item['actual']}",
            "- 问题：",
        ]
        if item["issues"]:
            report += [f"  - {issue}" for issue in item["issues"]]
        else:
            report.append("  - 无严重问题")
        report.append("")

    report += [
        "## 结论",
        "",
        "通过。" if ok else "未通过，请查看上方失败 case。",
        "",
        "## 机器可读结果",
        "",
        "```json",
        json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    (REPORTS / "verification_report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"REPORT={REPORTS / 'verification_report.md'}")
    print(f"RESULT={'pass' if ok else 'fail'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
