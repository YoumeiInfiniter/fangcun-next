import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cinematic_guardrails import validate_cinematic_action
from agent_tools import validate_script


class CinematicGuardrailsTest(unittest.TestCase):
    def test_accepts_visual_delta_actions(self):
        content = '''<scriptItem name="EP001">
1-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上，纸角压住九尾狐的临时身份证。
张沫（压火）：站好。
△九尾狐低头，指尖把身份证翻到背面。
九尾狐（委屈）：我今天没换脸。
</scriptItem>'''
        report = validate_cinematic_action(content)
        self.assertTrue(report["ok"], report)

    def test_rejects_action_without_delta(self):
        content = '''<scriptItem name="EP001">
1-1　怪力乱神管理局 大会场　日　内
张沫把罚单拍在桌上，纸角压住九尾狐的临时身份证。
张沫（压火）：站好。
△九尾狐低头，指尖把身份证翻到背面。
九尾狐（委屈）：我今天没换脸。
</scriptItem>'''
        report = validate_cinematic_action(content)
        self.assertFalse(report["ok"], report)
        self.assertTrue(any(i["type"] == "missing_delta_action" for i in report["issues"]), report)

    def test_rejects_non_visual_literary_prose(self):
        content = '''<scriptItem name="EP001">
1-1　怪力乱神管理局 大会场　日　内
△张沫心里一沉，终于明白命运的阴影笼罩了她。
张沫（压火）：站好。
△九尾狐低头，指尖把身份证翻到背面。
九尾狐（委屈）：我今天没换脸。
</scriptItem>'''
        report = validate_cinematic_action(content)
        self.assertFalse(report["ok"], report)
        self.assertTrue(any(i["type"] == "non_visual_action" for i in report["issues"]), report)

    def test_validate_script_includes_cinematic_gate(self):
        content = '''<scriptItem name="EP001">
1-1　怪力乱神管理局 大会场　日　内
张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：没换脸。
</scriptItem>'''
        issues = validate_script(content, target_words=80)
        self.assertTrue(any("动作必须" in issue or "△" in issue for issue in issues), issues)

    def test_rejects_user_reported_unfilmable_examples(self):
        content = '''<scriptItem name="EP001">
1-1　别墅客厅　日　内
△江绵看着两个女人，三观再次受到暴击。
江绵（低声）：你们先出去。
△Sunny的笑僵住，CPU被烧了一秒。
Sunny（发紧）：你说什么？
△三只狼气势汹汹地下楼，像要去占山头。
</scriptItem>'''
        report = validate_cinematic_action(content)
        self.assertFalse(report["ok"], report)
        self.assertGreaterEqual(len(report["issues"]), 2, report)

    def test_validate_script_rejects_missing_delta_even_when_format_ok(self):
        content = '''<scriptItem name="EP001">
1-1　别墅客厅　日　内
江绵把手机扣在桌上。
江绵（低声）：你们先出去。
Sunny（发紧）：你说什么？
</scriptItem>'''
        issues = validate_script(content, target_words=60)
        self.assertTrue(any("缺少△" in issue or "动作必须" in issue for issue in issues), issues)

    def test_rejects_abstract_attitude_change_in_delta_action(self):
        content = '''<scriptItem name="EP002">
2-1　侯府正厅　日　内
△管事们脸色变了，刚才的感激一点点收回。
陆莞（冷）：你求她做什么？
△青禾的笑意挂不住，众人态度变了。
</scriptItem>'''
        report = validate_cinematic_action(content)
        self.assertFalse(report["ok"], report)
        self.assertTrue(any(i["type"] == "non_visual_action" for i in report["issues"]), report)
        issues = validate_script(content, target_words=60)
        self.assertTrue(any("动作行包含抽象态度/关系变化" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
