import json
import tempfile
import unittest
from pathlib import Path

from skills.drama.tools.source_io import (
    save_project_rule,
    load_project_rules,
    build_project_rules_change_summary,
    validate_project_rules_applied,
)


class ProjectRulesTest(unittest.TestCase):
    def _config(self, tmp):
        return {
            "output_dir": str(Path(tmp) / "project_out"),
            "project": {
                "episodes": 10,
                "episode_duration": 2,
                "chapter_range": [1, 20],
                "platform": "竖屏9:16",
                "aspect_ratio": "9:16",
                "style": "复仇",
                "paywall": "前10集免费",
            },
        }

    def test_save_and_version_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config(tmp)
            save_project_rule(cfg, "不要反差", source="writerA", stage="outline")
            save_project_rule(cfg, "不要强反转堆叠", source="writerA", stage="skeleton")
            rules = load_project_rules(cfg)
            self.assertIn("不要反差", rules)
            self.assertIn("不要强反转堆叠", rules)
            summary = build_project_rules_change_summary(cfg)
            self.assertIn("v2", summary)
            self.assertIn("不要反差", summary)
            data = json.loads((Path(cfg["output_dir"]) / "project_rules.json").read_text(encoding="utf-8"))
            self.assertEqual(data["rules_version"], 2)
            self.assertEqual(len(data["entries"]), 2)

    def test_validate_negative_rule_and_checklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config(tmp)
            save_project_rule(cfg, "不要反差", source="writerA", stage="global")
            issues = validate_project_rules_applied(cfg, "这里仍然强调反差卖点")
            self.assertTrue(any("反差" in i for i in issues))
            self.assertTrue(any("项目规则落实清单" in i for i in issues))
            ok = validate_project_rules_applied(cfg, "项目规则落实清单\n- 已去掉反差设计，改用稳定压迫感推进")
            self.assertFalse(any("疑似未落实" in i for i in ok))


if __name__ == "__main__":
    unittest.main()
