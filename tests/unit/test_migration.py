"""Unit tests for legacy project migration."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.migration import map_legacy_config, migrate_all, migrate_project


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.legacy_projects = self.root / "legacy_projects"
        self.project_root = self.legacy_projects / "demo"
        self.out_dir = self.root / "migrated"
        self._build_legacy_project()

    def _build_legacy_project(self):
        drama = self.project_root / "drama"
        cache = self.project_root / "_cache"
        drama.mkdir(parents=True)
        cache.mkdir(parents=True)
        config = {
            "project_workspace": str(self.project_root),
            "project": {
                "source_book": "旧书",
                "project_name": "旧剧",
                "style": "喜剧",
                "episodes": 20,
                "episode_duration": 2,
                "platform": "竖屏短剧",
            },
        }
        (drama / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        (cache / "events.json").write_text(
            json.dumps([{"id": 1, "chapter_index": 1, "chapter": "第1章", "event": "系统登场"}], ensure_ascii=False),
            encoding="utf-8",
        )
        (self.project_root / "story_skeleton.md").write_text("# 旧骨架\n- 第一集", encoding="utf-8")
        scripts = self.project_root / "scripts"
        scripts.mkdir()
        (scripts / "ep_001.txt").write_text("第1集：旧定稿\n1-1 家 夜 内\n人物：A\n△动作。\n", encoding="utf-8")
        (self.project_root / "continuity_state.json").write_text(
            json.dumps({"approved_episodes": [1]}), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_map_legacy_config_maps_fields(self):
        legacy = {
            "project": {"source_book": "书", "project_name": "剧", "style": "甜宠", "episodes": 30, "episode_duration": 1.5},
        }
        mapped = map_legacy_config(legacy, "demo")
        self.assertEqual(mapped["novel_name"], "书")
        self.assertEqual(mapped["drama_name"], "剧")
        self.assertEqual(mapped["genre"], ["甜宠"])
        self.assertEqual(mapped["initial_episode_count"], 30)
        self.assertEqual(mapped["minimum_episode_seconds"], 90)
        self.assertTrue(mapped["writer_has_final_authority"])

    def test_migrate_project_copies_artifacts_and_reports(self):
        report = migrate_project(self.project_root / "drama" / "config.json", self.out_dir)
        target = self.out_dir / "demo"
        self.assertTrue((target / "artifacts" / "source_events" / "events.json").exists())
        events = json.loads((target / "artifacts" / "source_events" / "events.json").read_text(encoding="utf-8"))
        self.assertEqual(events[0]["event_id"], "LEGACY-1")
        self.assertTrue((target / "artifacts" / "approved_scripts" / "ep001.txt").exists())
        self.assertTrue((target / "artifacts" / "episode_outline" / "episode_outline.md").exists())
        self.assertTrue((target / "state" / "continuity.json").exists())
        self.assertTrue((target / "state" / "migration_report.md").exists())
        self.assertTrue(any(m["type"] == "approved_scripts" for m in report["mapped"]))

    def test_migrate_never_deletes_source(self):
        migrate_project(self.project_root / "drama" / "config.json", self.out_dir)
        self.assertTrue((self.project_root / "story_skeleton.md").exists())
        self.assertTrue((self.project_root / "scripts" / "ep_001.txt").exists())

    def test_migrate_all_reports_all_projects(self):
        reports = migrate_all(self.legacy_projects, self.out_dir)
        self.assertEqual(len(reports), 1)
        self.assertNotIn("error", reports[0])


if __name__ == "__main__":
    unittest.main()

