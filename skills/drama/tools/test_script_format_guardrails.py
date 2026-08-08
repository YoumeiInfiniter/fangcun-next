import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_tools import validate_script


class ScriptFormatGuardrailsTest(unittest.TestCase):
    def test_accepts_combined_scene_heading_with_ep_marker(self):
        content = '''<scriptItem name="EP001">
EP001：会走路的罚单
# 目标时长：1分钟

### 剧情梗概
张沫处理九尾狐和毕方引发的荒诞事故。

1-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上，九尾狐低头躲开众妖视线。
张沫（压火）：你身份证呢？
九尾狐（委屈）：今天不太准。
1-2　公司走廊　日　内
△消防喷淋还在滴水，毕方缩在墙角冒烟。
张沫（指着罚单）：你又烧什么了？
毕方（小声）：空气。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertFalse(any('场次标题' in i or '旧场次格式' in i or '第一集第一场' in i or '分集标识' in i for i in issues), issues)

    def test_rejects_missing_visible_episode_marker(self):
        content = '''<scriptItem name="EP001">
1-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：我站着呢。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertTrue(any('缺少规范分集标识' in i for i in issues), issues)

    def test_rejects_episode_marker_hidden_after_title(self):
        content = '''<scriptItem name="EP001">
# 怪力乱神管理局 EP001：会走路的罚单
1-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：我站着呢。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertTrue(any('缺少规范分集标识' in i for i in issues), issues)

    def test_accepts_chinese_episode_marker_with_arabic_digits(self):
        content = '''<scriptItem name="EP001">
第1集：会走路的罚单
1-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：我站着呢。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertFalse(any('分集标识' in i for i in issues), issues)

    def test_rejects_chinese_numeral_episode_marker(self):
        content = '''<scriptItem name="EP015">
第十五集：会走路的罚单
15-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：我站着呢。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertTrue(any('阿拉伯数字' in i for i in issues), issues)

    def test_rejects_bracketed_explanatory_scene_title(self):
        content = '''<scriptItem name="EP001">
EP001：会走路的罚单
【第一集第一场】
1-1　怪力乱神管理局 大会场　日　内
△张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：我站着呢。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertTrue(any('第一集第一场' in i for i in issues), issues)

    def test_rejects_legacy_split_scene_format(self):
        content = '''<scriptItem name="EP001">
EP001：会走路的罚单
1-1
场：怪力乱神管理局 大会场-日-内
△张沫把罚单拍在桌上。
张沫（压火）：站好。
△九尾狐低头。
九尾狐（委屈）：我站着呢。
</scriptItem>'''
        issues = validate_script(content, target_words=20)
        self.assertTrue(any('旧场次格式' in i for i in issues), issues)
        self.assertTrue(any('缺少规范场次标题' in i for i in issues), issues)


if __name__ == '__main__':
    unittest.main()
