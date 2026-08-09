"""Unit tests for project state, manifest and active-version management."""

import tempfile
import unittest
from pathlib import Path

from scripts.state_store import (
    active_artifact_path,
    artifact_version_path,
    append_writer_override,
    config_path,
    init_project,
    is_approved,
    load_config,
    load_manifest,
    load_active_versions,
    project_status,
    record_artifact,
    writer_overrides,
)
from scripts.common import atomic_write_json


def make_config(project_id="fc-test-001") -> dict:
    return {
        "project_id": project_id,
        "novel_name": "测试小说",
        "drama_name": "测试短剧",
        "platform": "竖屏短剧",
        "genre": ["喜剧"],
        "initial_episode_count": 10,
        "writer_has_final_authority": True,
    }


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "projects" / "fc-test-001"

    def tearDown(self):
        self._tmp.cleanup()

    def test_init_is_idempotent_and_writes_config(self):
        first = init_project(self.project_dir, make_config())
        self.assertTrue(first["created"])
        self.assertTrue(config_path(self.project_dir).exists())
        second = init_project(self.project_dir, make_config())
        self.assertFalse(second["created"])
        self.assertEqual(second["config"]["project_id"], "fc-test-001")

    def test_init_rejects_different_project_id_in_same_dir(self):
        init_project(self.project_dir, make_config())
        with self.assertRaises(ValueError):
            init_project(self.project_dir, make_config(project_id="other"))

    def test_record_artifact_versions_and_active_pointer(self):
        init_project(self.project_dir, make_config())
        draft = self.project_dir / "artifacts" / "script_drafts" / "ep001_v001.txt"
        draft.parent.mkdir(parents=True)
        draft.write_text("第1集：测试\n", encoding="utf-8")
        v1 = record_artifact(self.project_dir, "script_draft", draft, episode=1, source="ai", status="draft")
        # Same content must be idempotent (no duplicate version).
        v1_again = record_artifact(self.project_dir, "script_draft", draft, episode=1, source="ai", status="draft")
        self.assertEqual(v1_again, "v001")
        draft.write_text("第1集：修改版\n", encoding="utf-8")
        v2 = record_artifact(self.project_dir, "script_draft", draft, episode=1, source="ai", status="draft")
        self.assertEqual(v1, "v001")
        self.assertEqual(v2, "v002")
        active = active_artifact_path(self.project_dir, "script_draft", 1)
        self.assertEqual(active.read_text(encoding="utf-8"), "第1集：修改版\n")
        manifest = load_manifest(self.project_dir)
        self.assertEqual(len(manifest["artifacts"]["script_draft:1"]["versions"]), 2)

    def test_approved_flag_and_status(self):
        init_project(self.project_dir, make_config())
        self.assertFalse(is_approved(self.project_dir, 1))
        approved = self.project_dir / "artifacts" / "approved_scripts" / "ep001.txt"
        approved.parent.mkdir(parents=True)
        approved.write_text("第1集：定稿\n", encoding="utf-8")
        record_artifact(self.project_dir, "approved_script", approved, episode=1, source="writer", status="approved")
        self.assertTrue(is_approved(self.project_dir, 1))
        status = project_status(self.project_dir)
        self.assertEqual(status["approved_episodes"], [1])
        self.assertEqual(status["next_episode"], 2)

    def test_writer_overrides_append_only(self):
        init_project(self.project_dir, make_config())
        append_writer_override(self.project_dir, {"revision_id": "REV-1", "episode": 1, "instruction": "保留顺口溜"})
        append_writer_override(self.project_dir, {"revision_id": "REV-2", "episode": 1, "instruction": "删掉死我"})
        records = writer_overrides(self.project_dir)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["instruction"], "删掉死我")

    def test_active_versions_never_overwrites_history(self):
        init_project(self.project_dir, make_config())
        p1 = self.project_dir / "a.txt"
        p2 = self.project_dir / "b.txt"
        p1.parent.mkdir(parents=True, exist_ok=True)
        p1.write_text("x", encoding="utf-8")
        p2.write_text("y", encoding="utf-8")
        record_artifact(self.project_dir, "episode_outline", p1)
        record_artifact(self.project_dir, "episode_outline", p2)
        versions = load_active_versions(self.project_dir)
        active = active_artifact_path(self.project_dir, "episode_outline")
        self.assertEqual(active.read_text(encoding="utf-8"), "y")
        manifest = load_manifest(self.project_dir)
        self.assertEqual(len(manifest["artifacts"]["episode_outline"]["versions"]), 2)
        v1_path = artifact_version_path(self.project_dir, "episode_outline", None, "v001")
        v2_path = artifact_version_path(self.project_dir, "episode_outline", None, "v002")
        self.assertEqual(v1_path.read_text(encoding="utf-8"), "x")
        self.assertEqual(v2_path.read_text(encoding="utf-8"), "y")

    def test_load_config_merges_local_model_config(self):
        init_project(self.project_dir, make_config())
        local = self.project_dir / "config.local.json"
        atomic_write_json(
            local,
            {
                "model_config": {
                    "api_url": "https://api.deepseek.com",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                }
            },
        )
        config = load_config(self.project_dir)
        self.assertEqual(config["model_config"]["api_url"], "https://api.deepseek.com")
        self.assertEqual(config["model_config"]["model"], "deepseek-chat")
        self.assertEqual(config["_local_overrides"], {"model_config": True})

    def test_load_config_without_local_file_keeps_original(self):
        init_project(self.project_dir, make_config())
        config = load_config(self.project_dir)
        self.assertNotIn("model_config", config)


if __name__ == "__main__":
    unittest.main()
