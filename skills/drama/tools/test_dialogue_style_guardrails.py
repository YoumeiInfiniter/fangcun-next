#!/usr/bin/env python3
from dialogue_style_guardrails import validate_dialogue_style


def test_ai_cliche_detected():
    text = "角色（冷笑）：从今天起，我再也不是从前的我，你们所有人终将付出代价。"
    r = validate_dialogue_style(text)
    assert r["issue_count"] >= 2
    assert any(i["type"] == "ai_cliche_dialogue" for i in r["issues"])


def test_short_specific_line_clean():
    text = "角色（压低声音）：门后有人。"
    r = validate_dialogue_style(text)
    assert r["issue_count"] == 0


if __name__ == "__main__":
    test_ai_cliche_detected()
    test_short_specific_line_clean()
    print("ok")
