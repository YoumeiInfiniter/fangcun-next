"""Unit tests for deterministic screenplay format validation."""

import unittest

from scripts.script_validator import extract_speakers, parse_script, validate_script


GOOD_SCRIPT = """第1集：系统绑错人

1-1 谢家书房 夜 内
人物：叶聆、谢淮舟、996

△谢淮舟将离婚协议放到叶聆面前。
谢淮舟（冷淡）：录完节目，我们离婚。
叶聆（OS）：我的三亿呢？

△半空弹出一只发光小团。
996：炮灰自救系统996号为您服务！
"""


class ScriptValidatorTests(unittest.TestCase):
    def test_valid_default_cn_passes(self):
        report = validate_script(GOOD_SCRIPT, expected_episode=1)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["parsed"]["episode_number"], 1)
        self.assertEqual(report["parsed"]["title"], "系统绑错人")
        self.assertIn("叶聆", report["parsed"]["speakers"])
        self.assertEqual(len(report["parsed"]["scenes"]), 1)

    def test_missing_episode_header_fails(self):
        report = validate_script("1-1 家 夜 内\n人物：A\n△动作。\n")
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["code"] == "episode_header" for e in report["errors"]))

    def test_bad_episode_header_fails(self):
        report = validate_script("第1集 标题\n1-1 家 夜 内\n人物：A\n△动作。\n")
        self.assertFalse(report["ok"])

    def test_consecutive_duplicate_scene_key_fails(self):
        script = """第1集：测试

1-1 家 夜 内
人物：A
△动作。

1-2 家 夜 内
人物：A
△另一个动作。
"""
        report = validate_script(script)
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["code"] == "consecutive_scene_key" for e in report["errors"]))

    def test_empty_scene_fails(self):
        script = """第1集：测试

1-1 家 夜 内
人物：A

1-2 街 日 外
人物：A
△动作。
"""
        report = validate_script(script)
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["code"] == "empty_scene" for e in report["errors"]))

    def test_unparsable_line_fails(self):
        script = GOOD_SCRIPT + "这是一行无法归类的文字。\n"
        report = validate_script(script)
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["code"] == "unparsable_line" for e in report["errors"]))

    def test_xml_wrapper_mode(self):
        xml = f'<scriptItem name="EP001">\n{GOOD_SCRIPT.strip()}\n</scriptItem>\n'
        report = validate_script(xml, format_profile="legacy-scriptitem")
        self.assertTrue(report["ok"], report["errors"])

    def test_xml_mode_rejects_content_outside_tags(self):
        xml = f'<scriptItem name="EP001">\n{GOOD_SCRIPT.strip()}\n</scriptItem>\n多余内容'
        report = validate_script(xml, format_profile="legacy-scriptitem")
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["code"] == "xml_wrapper" for e in report["errors"]))

    def test_episode_mismatch_fails(self):
        report = validate_script(GOOD_SCRIPT, expected_episode=2)
        self.assertFalse(report["ok"])
        self.assertTrue(any(e["code"] == "episode_mismatch" for e in report["errors"]))

    def test_forbidden_stats_line_fails(self):
        script = GOOD_SCRIPT + "字数：128\n"
        report = validate_script(script)
        self.assertFalse(report["ok"])

    def test_parse_and_speaker_extraction(self):
        parsed = parse_script(GOOD_SCRIPT)
        self.assertEqual(parsed["scenes"][0]["dialogues"][1]["delivery"], "OS")
        speakers = extract_speakers(GOOD_SCRIPT)
        self.assertEqual(speakers, ["叶聆", "谢淮舟", "996"])

    def test_old_bad_bracket_sample_classification(self):
        # A dialogue that loses its closing bracket is not parseable.
        bad = GOOD_SCRIPT.replace("叶聆（OS）：我的三亿呢？", "叶聆（OS：我的三亿呢？")
        report = validate_script(bad)
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()

