"""Deterministic EP001 regression checks (spec §25.2).

These checks target generic bugs from the EP001 three-way diagnosis:
payoff without setup, the interrupted line moved after the reveal, the
hearing-the-system rule missing, and lightning without a causal chain.
They do not require any specific model output.
"""

from __future__ import annotations

import re


def _dialogue_lines(script: str) -> list[str]:
    return [line.strip() for line in script.splitlines() if "：" in line and "△" not in line]


def _line_index(script: str, pattern: str) -> int:
    regex = re.compile(pattern)
    for idx, line in enumerate(script.splitlines()):
        if regex.search(line):
            return idx
    return -1


def check_payoff_has_setup(script: str) -> dict:
    """“吃不完的苦”必须出现在语言 setup“吃得苦中苦”之后。"""
    setup_index = _line_index(script, r"吃得苦中苦")
    payoff_index = _line_index(script, r"吃不完的苦")
    ok = setup_index >= 0 and payoff_index > setup_index
    return {
        "check": "payoff_has_setup",
        "ok": ok,
        "detail": f"setup@{setup_index} payoff@{payoff_index}",
    }


def check_interrupted_line_before_reveal(script: str) -> dict:
    """“死我”的挑衅必须在“绑错惩罚对象”揭示之前。"""
    tease_index = _line_index(script, r"你有本事就劈死我")
    reveal_index = _line_index(script, r"绑错惩罚对象")
    ok = tease_index >= 0 and reveal_index >= 0 and tease_index < reveal_index
    return {
        "check": "interrupted_line_before_reveal",
        "ok": ok,
        "detail": f"tease@{tease_index} reveal@{reveal_index}",
    }


def check_hearing_rule_established(script: str) -> dict:
    """谢淮舟能听见系统的规则必须在雷击/错绑之前建立。"""
    rule_index = _line_index(script, r"能听见|听见我|听见系统")
    reveal_index = _line_index(script, r"绑错惩罚对象")
    ok = rule_index >= 0 and reveal_index >= 0 and rule_index < reveal_index
    return {
        "check": "hearing_rule_established",
        "ok": ok,
        "detail": f"rule@{rule_index} reveal@{reveal_index}",
    }


def check_lightning_causality(script: str) -> dict:
    """雷击前必须有拒绝/发誓与任务失败至少两个因果元素。"""
    refusal = _line_index(script, r"拒绝|绝不会爱上|发誓")
    failure = _line_index(script, r"任务失败|倒计时结束|五秒牵手任务")
    lightning = _line_index(script, r"雷击|雷劈|劈中")
    ok = (
        refusal >= 0
        and failure >= 0
        and lightning >= 0
        and max(refusal, failure) < lightning
    )
    return {
        "check": "lightning_causality",
        "ok": ok,
        "detail": f"refusal@{refusal} failure@{failure} lightning@{lightning}",
    }


def check_reactions_match_knowledge(script: str) -> dict:
    """错绑揭示时叶聆与996必须有符合当前认知的反应。"""
    has_reactions = (
        _line_index(script, r"叶聆.*震惊|震惊.*叶聆|叶聆.*慌乱") >= 0
        and _line_index(script, r"996.*(承认|慌乱|震惊|绑错)") >= 0
    )
    return {"check": "reactions_match_knowledge", "ok": has_reactions, "detail": ""}


def check_no_unsupported_characters(script: str, allowed: list[str]) -> dict:
    """不新增无依据且影响人物状态的角色。"""
    from scripts.script_validator import extract_speakers

    speakers = set(extract_speakers(script))
    extra = speakers - set(allowed)
    return {"check": "no_unsupported_characters", "ok": not extra, "detail": f"extra={sorted(extra)}"}


def run_ep001_checks(script: str, allowed_characters: list[str] | None = None) -> list[dict]:
    allowed = allowed_characters or ["叶聆", "谢淮舟", "996"]
    return [
        check_payoff_has_setup(script),
        check_interrupted_line_before_reveal(script),
        check_hearing_rule_established(script),
        check_lightning_causality(script),
        check_reactions_match_knowledge(script),
        check_no_unsupported_characters(script, allowed),
    ]
