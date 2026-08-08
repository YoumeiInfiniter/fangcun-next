"""Unit tests for the deterministic JSON Schema validator."""

import tempfile
import unittest
from pathlib import Path

from scripts.common import atomic_write_json, schemas_dir
from scripts.schema_validate import SchemaValidationError, ensure_valid, load_schema, validate


class SchemaValidateTests(unittest.TestCase):
    def test_all_schemas_are_valid_json_files(self):
        files = sorted(schemas_dir().glob("*.schema.json"))
        self.assertGreaterEqual(len(files), 8)
        for path in files:
            data = load_schema(path.name)
            self.assertEqual(data["type"], "object", path.name)

    def test_project_config_accepts_spec_example(self):
        config = {
            "project_id": "fc-demo-001",
            "novel_name": "原著名",
            "drama_name": "剧名",
            "platform": "竖屏短剧",
            "aspect_ratio": "9:16",
            "genre": ["喜剧", "甜宠", "脑洞"],
            "initial_episode_count": 30,
            "minimum_episode_seconds": 60,
            "minimum_total_seconds": 1800,
            "preferred_episode_seconds": [60, 100],
            "preferred_total_seconds": None,
            "source_scope": {"start_chapter": 1, "end_chapter": 340},
            "reach_original_ending": True,
            "fidelity": "medium",
            "dialogue_policy": "prefer_original",
            "review_policy": "advisory_with_writer_confirmation",
            "script_format": "default-cn",
            "writer_has_final_authority": True,
        }
        ok, errors = validate(config, "project-config.schema.json")
        self.assertTrue(ok, errors)

    def test_project_config_rejects_missing_writer_authority(self):
        ok, errors = validate(
            {"project_id": "p1", "novel_name": "n", "drama_name": "d", "platform": "x", "genre": ["g"]},
            "project-config.schema.json",
        )
        self.assertFalse(ok)
        self.assertTrue(any("writer_has_final_authority" in e for e in errors))

    def test_episode_outline_accepts_spec_example(self):
        outline = {
            "episode": 1,
            "title": "系统绑错人",
            "source_event_ids": ["CH001-E01", "CH001-E02", "CH001-E03"],
            "source_chapters": [1],
            "opening_bridge": "谢淮舟提出录完恋综后离婚",
            "episode_goal": "建立叶聆退休穿书、996出现、谢淮舟能听见系统及惩罚错绑规则",
            "must_keep": ["叶聆刚完成任务退休", "谢淮舟能听见996", "五秒牵手任务", "任务失败后雷劈谢淮舟"],
            "causal_chains": [["系统发布任务", "谢淮舟拒绝", "倒计时失败", "叶聆挑衅", "雷击错绑", "三方反应"]],
            "knowledge_at_start": {"叶聆": ["自己完成快穿任务准备退休"], "谢淮舟": ["准备与叶聆离婚"]},
            "knowledge_at_end": {"叶聆": ["系统惩罚错误作用于谢淮舟"], "谢淮舟": ["能听见996并会受任务惩罚"]},
            "dialogue_anchors": [{"setup": "吃得苦中苦，你就能得到——", "payoff": "吃不完的苦。", "source": "第1章"}],
            "allowed_compression": ["退休背景可用短闪回表现"],
            "forbidden_additions": ["无依据的新人物", "改变系统可被听见的规则"],
            "ending_hook": "996承认绑错惩罚对象",
            "suggested_seconds": [90, 130],
            "writer_notes": [],
        }
        ok, errors = validate(outline, "episode-outline.schema.json")
        self.assertTrue(ok, errors)

    def test_episode_outline_rejects_empty_must_keep(self):
        outline = {
            "episode": 1,
            "title": "t",
            "source_event_ids": ["E1"],
            "source_chapters": [1],
            "opening_bridge": "b",
            "episode_goal": "g",
            "must_keep": [],
            "causal_chains": [["a", "b"]],
            "knowledge_at_start": {},
            "knowledge_at_end": {},
            "ending_hook": "h",
        }
        ok, errors = validate(outline, "episode-outline.schema.json")
        self.assertFalse(ok)
        self.assertTrue(any("must_keep" in e for e in errors))

    def test_review_report_enforces_severity_enum(self):
        report = {
            "episode": 1,
            "verdict": "blocked",
            "summary": "问题",
            "issues": [{"id": "X1", "severity": "fatal", "category": "causality", "problem": "p"}],
        }
        ok, errors = validate(report, "review-report.schema.json")
        self.assertFalse(ok)
        self.assertTrue(any("severity" in e for e in errors))

    def test_ensure_valid_raises_with_messages(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            ensure_valid({"episode": 0}, "episode-outline.schema.json")
        self.assertTrue(ctx.exception.messages)

    def test_validator_can_read_repo_schemas_without_network(self):
        # Guards against accidental reliance on external schema hosting.
        self.assertFalse(load_schema("source-event.schema.json")["$schema"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()

