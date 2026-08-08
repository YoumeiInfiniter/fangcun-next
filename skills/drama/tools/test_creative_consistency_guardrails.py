#!/usr/bin/env python3
from creative_consistency_guardrails import validate_creative_consistency


def test_forbidden_character_reappears():
    rules = "- [v1] 删除李四这个人物，后续不要再出现。"
    content = "第3集：李四突然回来挑拨。\n项目规则落实清单：已落实。"
    r = validate_creative_consistency(content, rules)
    assert r["ok"] is False
    assert any(i["type"] == "forbidden_character_reappears" for i in r["issues"])


def test_required_character_missing():
    rules = "- [v2] 反复强调薛守正作为监督、质疑者贯穿始终。"
    content = "第4集：主角独自推进，没有其他人质疑。\n项目规则落实清单：已落实。"
    r = validate_creative_consistency(content, rules)
    assert r["ok"] is False
    assert any(i["type"] == "required_character_missing" for i in r["issues"])


def test_source_basis_required_when_no_original():
    rules = "- 禁止原创剧情/台词，必须贴合原著。"
    content = "第1集：主角反击。\n项目规则落实清单：已落实。"
    r = validate_creative_consistency(content, rules)
    assert any(i["type"] == "missing_source_basis_checklist" for i in r["issues"])


def test_rejects_premature_character_knowledge_timeline():
    rules = "Sunny这个角色后面100多章才知道女主生病，不能提前让Sunny知道女主生病。"
    content = '''<scriptItem name="EP002">
2-1　别墅客厅　夜　内
△Sunny攥紧病历单，指尖发白。
Sunny（发颤）：我早就知道她生病了。
</scriptItem>

项目规则落实清单：已参考原著。
'''
    report = validate_creative_consistency(content, rules)
    assert report["ok"] is False, report
    assert any(i["type"] == "character_knowledge_timeline_violation" for i in report["issues"]), report


def test_allows_character_present_without_knowing_protected_fact():
    rules = "Sunny后100多章才知道女主生病。"
    content = '''<scriptItem name="EP002">
2-1　别墅客厅　夜　内
△Sunny把外套递给江绵，避开她苍白的脸色。
Sunny（压低声音）：外面冷。
</scriptItem>

项目规则落实清单：Sunny未获知女主生病。
'''
    report = validate_creative_consistency(content, rules)
    assert report["ok"] is True, report


if __name__ == "__main__":
    test_forbidden_character_reappears()
    test_required_character_missing()
    test_source_basis_required_when_no_original()
    test_rejects_premature_character_knowledge_timeline()
    test_allows_character_present_without_knowing_protected_fact()
    print("ok")
