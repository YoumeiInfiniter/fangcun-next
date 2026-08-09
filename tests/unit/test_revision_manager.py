"""Unit tests for revision requests and writer overrides."""

import tempfile
import unittest
from pathlib import Path

from scripts.revision_manager import (
    analyze_impact,
    approve_revision,
    create_revision,
    list_revisions,
    reject_revision,
)
from scripts.state_store import init_project, writer_overrides


class RevisionManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "project"
        init_project(
            self.project_dir,
            {"project_id": "rev-test", "novel_name": "n", "drama_name": "d", "platform": "p", "genre": ["喜剧"], "writer_has_final_authority": True},
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_local_revision_does_not_affect_future(self):
        record = create_revision(self.project_dir, episode=1, instruction="保留系统顺口溜，删除结尾死我")
        self.assertEqual(record["scope"], "local_episode")
        self.assertFalse(record["affects_future"])
        self.assertEqual(record["status"], "pending")

    def test_future_markers_detected(self):
        impact = analyze_impact("下一集要承接人物认知变化，未来伏笔保留")
        self.assertTrue(impact["affects_future"])
        self.assertIn("character_knowledge", impact["scope"])

    def test_project_wide_markers_detected(self):
        impact = analyze_impact("整体重做结局，改主线")
        self.assertEqual(impact["scope"], "project_wide")

    def test_approve_propagates_override_to_context(self):
        record = create_revision(self.project_dir, episode=2, instruction="下一集沿用新规则", affects_future=True)
        updated = approve_revision(self.project_dir, record["revision_id"])
        self.assertEqual(updated["status"], "approved")
        overrides = writer_overrides(self.project_dir)
        self.assertTrue(any(o["revision_id"] == record["revision_id"] and o["status"] == "approved" for o in overrides))

    def test_reject_does_not_propagate(self):
        record = create_revision(self.project_dir, episode=1, instruction="删台词")
        reject_revision(self.project_dir, record["revision_id"])
        from scripts.revision_manager import list_revisions

        state = list_revisions(self.project_dir, episode=1)[0]
        self.assertEqual(state["status"], "rejected")
        self.assertNotIn("删台词", [o.get("instruction") for o in writer_overrides(self.project_dir) if o.get("status") == "approved"])

    def test_list_filters_by_episode(self):
        create_revision(self.project_dir, episode=1, instruction="改台词")
        create_revision(self.project_dir, episode=2, instruction="改动作")
        self.assertEqual(len(list_revisions(self.project_dir, episode=1)), 1)
        self.assertEqual(len(list_revisions(self.project_dir)), 2)

    def test_revision_ids_are_sequential(self):
        r1 = create_revision(self.project_dir, episode=1, instruction="a")
        r2 = create_revision(self.project_dir, episode=1, instruction="b")
        self.assertNotEqual(r1["revision_id"], r2["revision_id"])


if __name__ == "__main__":
    unittest.main()
