#!/usr/bin/env python3
"""剧本视听化与动作格式门禁。

目标：拦截两类业务高频问题：
1. 动作/场景描述没有使用 △。
2. 把小说旁白、心理描写、抽象文学性表达直接写进剧本，导演拍不出来。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


SCENE_HEADING_RE = re.compile(
    r"^\s*\d+[-－]\d+\s+[^\n：:【】]+?\s+(?:日|夜|晨|午|傍晚|清晨|深夜)\s+(?:内|外)\s*$"
)
DIALOGUE_RE = re.compile(r"^\s*[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{0,12}(?:（[^）]+）)?(?:VO|OS)?[：:]")
XML_OR_COMMENT_RE = re.compile(r"^\s*(?:</?scriptItem\b|<!--|-->|#|```)")

NON_VISUAL_PATTERNS = [
    ("心理描写", re.compile(r"心里|心中|内心|脑海|心底|潜意识|意识到|终于明白|突然明白|这才明白|觉得|感觉到|想起自己|她想|他想|只当她|没有再追问")),
    ("抽象文学性表达", re.compile(r'命运|宿命|灵魂|深处|无形的手|巨大的阴影|世界仿佛|空气仿佛|时间仿佛|沉重得让人喘不过气|三观(?:再次)?受到暴击|CPU(?:被)?烧了(?:一秒|一下)?|被(?:一个)?[“"『「]?呵[”"』」]?扎穿|像要去占山头|老毛病')),
    ("不可拍情绪结论", re.compile(r"孤独感|破碎感|压迫感|宿命感|安全感|无力感|绝望感|悲凉感|荒诞感|震惊感|窒息感")),
    ("抽象态度/关系变化", re.compile(r"感激(?:一点点)?(?:收回|退去|消失)|信任(?:崩塌|动摇|裂开|消失)|态度(?:变了|转变)|立场(?:变了|转变)|关系(?:变了|破裂|缓和)|脸色变了|眼神从[^。；，,.!?！？]{0,12}变成|笑意(?:挂住|挂不住|消失|僵住|僵在)|温柔(?:快)?挂不住|光环(?:裂了|破了|碎了)|气氛|氛围|全场(?:都)?(?:明白|认可|动摇|相信)|众人(?:都)?(?:明白|认可|动摇|相信|不再相信)")),
    ("结果性/评价性动作行", re.compile(r"(?:开始|不再|终于|彻底|一点点|慢慢)(?:认可|相信|怀疑|动摇|破防|崩塌|被说服)|被(?:击穿|说服|震住|打动)|显得(?:尴尬|狼狈|可笑|无助)|看起来(?:尴尬|狼狈|可笑|无助)")),
    ("导演拍不出来的说明", re.compile(r"导演拍不出来|非视觉化|文学性描写|小说性描写")),
]

ACTION_START_RE = re.compile(
    r"^\s*(?:他|她|它|他们|她们|众人|所有人|张沫|九尾狐|毕方|夫诸|鸣蛇|蛊雕|郎日|郎月|郎星|镜头|手机|门|灯|水|火|雨|玻璃|桌|罚单|招牌|办公室|会议桌|人群|工作人员)"
)


@dataclass
class GuardrailIssue:
    severity: str
    type: str
    line: int
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "type": self.type,
            "line": self.line,
            "message": self.message,
        }


def _is_ignorable_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if XML_OR_COMMENT_RE.search(stripped):
        return True
    if SCENE_HEADING_RE.search(stripped):
        return True
    if DIALOGUE_RE.search(stripped):
        return True
    if stripped.startswith("△"):
        return True
    if stripped.startswith("（") and stripped.endswith("）"):
        return True
    return False


def validate_cinematic_action(content: str) -> dict:
    """校验剧本是否足够视听化。

    返回：{"ok": bool, "issues": [GuardrailIssue dict]}
    """
    issues: list[GuardrailIssue] = []
    lines = content.splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if _is_ignorable_line(stripped):
            # 即使是 △ 动作行，也要检查是否把心理/抽象文学性表达塞进动作。
            if stripped.startswith("△"):
                for kind, pattern in NON_VISUAL_PATTERNS:
                    if pattern.search(stripped):
                        issues.append(GuardrailIssue(
                            "error",
                            "non_visual_action",
                            idx,
                            f"动作行包含{kind}，导演拍不出来；请改成具体人物动作、视线/手部反应、站位变化、道具变化、声音反馈或镜头信息。",
                        ))
            continue

        if ACTION_START_RE.search(stripped):
            issues.append(GuardrailIssue(
                "error",
                "missing_delta_action",
                idx,
                "疑似动作/场景描述未使用 △ 开头；动作必须另起一行并以 △ 标记。",
            ))

        for kind, pattern in NON_VISUAL_PATTERNS:
            if pattern.search(stripped):
                issues.append(GuardrailIssue(
                    "error",
                    "non_visual_prose",
                    idx,
                    f"发现{kind}，这更像小说旁白而不是剧本执行指令；请转成可拍画面。",
                ))

    return {"ok": not any(i.severity == "error" for i in issues), "issues": [i.to_dict() for i in issues]}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    if len(sys.argv) != 2:
        print("Usage: cinematic_guardrails.py <script.txt>", file=sys.stderr)
        raise SystemExit(2)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    report = validate_cinematic_action(text)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)
