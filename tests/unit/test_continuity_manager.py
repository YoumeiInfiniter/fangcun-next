"""Unit tests for continuity extraction and rebuild."""

import tempfile
import unittest
from pathlib import Path

from scripts.continuity_manager import (
    apply_approved_script,
    extract_deterministic,
    refresh_continuity,
)
from scripts.state_store import init_project, load_continuity, save_continuity


SCRIPT1 = """第1集：系统绑错人

1-1 谢家书房 夜 内
人物：叶聆、谢淮舟、996

△谢淮舟将离婚协议放到叶聆面前。
谢淮舟（冷淡）：录完节目，我们离婚。
叶聆（OS）：我的三亿呢？

△半空弹出一只发光小团。
996：炮灰自救系统996号为您服务！
"""

SCRIPT2 = """第2集：听见系统

2-1 谢家书房 日 内
人物：谢淮舟、996

△谢淮舟听见系统声音。
谢淮舟：什么动静？
996：我是高级AI。
"""


class ContinuityManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "project"
        init_project(
            self.project_dir,
            {"project_id": "cont-test", "novel_name": "n", "drama_name": "d", "platform": "p", "genre": ["喜剧"], "script_format": "default-cn", "writer_has_final_authority": True},
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_deterministic_extraction_finds_characters_locations_and_hook(self):
        extracted = extract_deterministic(1, SCRIPT1)
        self.assertIn("叶聆", extracted["characters_seen"])
        self.assertEqual(extracted["locations"], {"谢家书房": 1})
        self.assertTrue(extracted["ending_hook_candidate"])
        self.assertEqual(extracted["extraction_mode"], "deterministic")

    def test_approve_updates_continuity_and_rebuild_is_idempotent(self):
        apply_approved_script(self.project_dir, 1, SCRIPT1, source="writer")
        continuity = load_continuity(self.project_dir)
        self.assertEqual(continuity["approved_episodes"], [1])
        self.assertIn("谢淮舟", continuity["character_states"])
        self.assertIn("谢家书房", continuity["locations"])
        self.assertTrue(continuity["open_hooks"])
        self.assertEqual(continuity["extraction_mode"], "deterministic")
        version = continuity["version"]

        apply_approved_script(self.project_dir, 2, SCRIPT2, source="writer")
        continuity = load_continuity(self.project_dir)
        self.assertEqual(continuity["approved_episodes"], [1, 2])
        self.assertGreater(continuity["version"], version)

        rebuilt = refresh_continuity(self.project_dir)
        self.assertEqual(rebuilt["approved_episodes"], [1, 2])
        self.assertGreaterEqual(rebuilt["version"], continuity["version"])

    def test_approve_rejects_invalid_format(self):
        with self.assertRaises(ValueError):
            apply_approved_script(self.project_dir, 1, "没有分集标识的文本")

    def test_model_assisted_returns_none_without_api(self):
        from scripts.continuity_manager import extract_model_assisted

        self.assertIsNone(extract_model_assisted(self.project_dir, 1, SCRIPT1))

    def test_rebuild_preserves_no_fake_facts_without_api(self):
        apply_approved_script(self.project_dir, 1, SCRIPT1)
        continuity = load_continuity(self.project_dir)
        # Deterministic mode must not invent semantic facts.
        self.assertEqual(continuity["extraction_mode"], "deterministic")
        self.assertEqual(continuity["facts"], [])


if __name__ == "__main__":
    unittest.main()

