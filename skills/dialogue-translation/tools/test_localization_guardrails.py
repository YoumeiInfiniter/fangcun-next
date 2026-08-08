#!/usr/bin/env python3
from localization_guardrails import validate_localization


def test_us_police_chinese_title_is_error():
    text = "海外剧，美国洛杉矶警局。\n刘队长：把人带回派出所。"
    r = validate_localization(text, locale="US")
    assert r["ok"] is False
    terms = {i["term"] for i in r["issues"]}
    assert "刘队长" in terms
    assert "派出所" in terms


def test_chinese_setting_not_applied():
    text = "现代中国刑侦剧。\n刘队长：把人带回派出所。"
    r = validate_localization(text, locale="中国大陆")
    assert r["ok"] is True
    assert r["applied"] is False


if __name__ == "__main__":
    test_us_police_chinese_title_is_error()
    test_chinese_setting_not_applied()
    print("ok")
