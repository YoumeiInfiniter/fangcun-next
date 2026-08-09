"""Unit tests for episode context building."""

import tempfile
import unittest
from pathlib import Path

from scripts.context_builder import (
    ContextIncompleteError,
    build_episode_context,
    current_context_path,
    verify_context_hash,
)
from scripts.state_store import (
    active_artifact_path,
    append_writer_override,
    init_project,
    record_artifact,
    save_continuity,
)
from scripts.source_ingest import ingest_novel


def make_config() -> dict:
    return {
        "project_id": "fc-ctx-001",
        "novel_name": "测试小说",
        "drama_name": "测试短剧",
        "platform": "竖屏短剧",
        "aspect_ratio": "9:16",
        "genre": ["喜剧", "甜宠"],
        "initial_episode_count": 3,
        "minimum_episode_seconds": 60,
        "preferred_episode_seconds": [90, 130],
        "script_format": "default-cn",
        "fidelity": "medium",
        "dialogue_policy": "prefer_original",
        "writer_has_final_authority": True,
    }


NOVEL = """第一章 系统的声音
谢淮舟提出录完节目离婚。
半空弹出光团：炮灰自救系统996号为您服务！
谢淮舟：什么动静？
叶聆：吃不完的苦。
雷击错绑，叶聆与996同时震惊。
996：绑错惩罚对象了。
"""

EVENTS = [
    {
        "event_id": "CH001-E01",
        "chapter_id": 1,
        "event": "系统登场并绑定",
        "importance": "mainline",
        "source_span": {"start": 0, "end": 40},
        "key_quotes": [{"speaker": "谢淮舟", "text": "什么动静？"}],
    },
    {
        "event_id": "CH001-E02",
        "chapter_id": 1,
        "event": "雷击错绑",
        "importance": "mainline",
        "source_span": {"start": 40, "end": 120},
        "key_quotes": [{"speaker": "996", "text": "绑错惩罚对象了。"}],
    },
]

OUTLINES = [
    {
        "episode": 1,
        "title": "系统绑错人",
        "source_event_ids": ["CH001-E01", "CH001-E02"],
        "source_chapters": [1],
        "opening_bridge": "谢淮舟提出录完节目离婚",
        "episode_goal": "建立系统规则",
        "must_keep": ["谢淮舟提出录完节目离婚", "雷击错绑"],
        "causal_chains": [["系统登场", "雷击错绑"]],
        "knowledge_at_start": {"叶聆": ["准备退休"]},
        "knowledge_at_end": {"谢淮舟": ["能听见系统"]},
        "ending_hook": "996承认绑错惩罚对象",
        "suggested_seconds": [90, 130],
        "episode_function": ["opening", "hook"],
    },
    {
        "episode": 2,
        "title": "第二集",
        "source_event_ids": ["CH001-E02"],
        "source_chapters": [1],
        "opening_bridge": "承接雷击错绑",
        "episode_goal": "推进关系",
        "must_keep": ["雷击错绑"],
        "causal_chains": [["雷击错绑", "双方反应"]],
        "knowledge_at_start": {},
        "knowledge_at_end": {},
        "ending_hook": "新钩子",
    },
]


class ContextBuilderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "projects" / "fc-ctx-001"
        init_project(self.project_dir, make_config())
        novel = self.project_dir.parent.parent / "novel.txt"
        novel.write_text(NOVEL, encoding="utf-8")
        ingest_novel(self.project_dir, novel)
        self._save_events()
        self._save_outlines()

    def tearDown(self):
        self._tmp.cleanup()

    def _save_events(self):
        path = self.project_dir / "artifacts" / "source_events" / "events.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(__import__("json").dumps(EVENTS, ensure_ascii=False), encoding="utf-8")
        record_artifact(self.project_dir, "source_events", path, source="ai", status="approved")

    def _save_outlines(self):
        path = self.project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            __import__("json").dumps({"episodes": OUTLINES}, ensure_ascii=False),
            encoding="utf-8",
        )
        record_artifact(self.project_dir, "episode_outline", path, source="ai", status="approved")

    def _approve_episode_one(self):
        script = self.project_dir / "artifacts" / "approved_scripts" / "ep001.txt"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("第1集：系统绑错人\n1-1 家 夜 内\n人物：叶聆、谢淮舟、996\n△雷击错绑。\n", encoding="utf-8")
        record_artifact(self.project_dir, "approved_script", script, episode=1, source="writer", status="approved")
        continuity = {
            "version": 1,
            "updated_from_episode": 1,
            "approved_episodes": [1],
            "facts": [],
            "character_knowledge": {"谢淮舟": ["能听见系统"]},
            "open_hooks": [{"hook": "996承认绑错惩罚对象", "introduced_in": 1, "status": "open"}],
        }
        save_continuity(self.project_dir, continuity)

    def test_builds_context_with_evidence_and_verifiable_hash(self):
        context = build_episode_context(self.project_dir, 1, save=True)
        self.assertEqual(context["episode"], 1)
        self.assertTrue(context["source_evidence"]["raw_excerpts"])
        ok, expected = verify_context_hash(context)
        self.assertTrue(ok)
        self.assertEqual(context["context_hash"], expected)
        self.assertTrue(current_context_path(self.project_dir, 1).exists())

    def test_reviewer_consumes_same_snapshot_hash(self):
        writer_ctx = build_episode_context(self.project_dir, 1, save=False)
        reviewer_ctx = build_episode_context(self.project_dir, 1, role="reviewer", save=False)
        self.assertEqual(writer_ctx["context_hash"], reviewer_ctx["context_hash"])
        self.assertEqual(writer_ctx["source_evidence"], reviewer_ctx["source_evidence"])

    def test_missing_outline_is_hard_blocked(self):
        with self.assertRaises(ContextIncompleteError) as ctx:
            build_episode_context(self.project_dir, 99)
        self.assertTrue(any("没有" in p for p in ctx.exception.problems))

    def test_must_keep_without_evidence_blocks_context(self):
        outlines = __import__("json").loads(
            (self.project_dir / "artifacts" / "episode_outline" / "episode_outlines.json").read_text(encoding="utf-8")
        )
        outlines["episodes"][0]["must_keep"] = ["完全不存在的事件"]
        path = self.project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
        path.write_text(__import__("json").dumps(outlines, ensure_ascii=False), encoding="utf-8")
        record_artifact(self.project_dir, "episode_outline", path, source="ai", status="approved")
        with self.assertRaises(ContextIncompleteError) as ctx:
            build_episode_context(self.project_dir, 1)
        self.assertTrue(any("完全不存在的事件" in p for p in ctx.exception.problems))

    def test_previous_approved_script_and_hook_are_included(self):
        self._approve_episode_one()
        context = build_episode_context(self.project_dir, 2)
        self.assertIn("第1集", context["previous_approved_script"])
        self.assertEqual(context["previous_episode_hook"], "996承认绑错惩罚对象")

    def test_writer_overrides_are_applied(self):
        from scripts.revision_manager import approve_revision, create_revision

        local = create_revision(
            self.project_dir,
            episode=1,
            instruction="保留顺口溜",
            source="cli",
            affects_future=False,
            direct_writer_instruction=True,
        )
        future = create_revision(
            self.project_dir,
            episode=1,
            instruction="未来集沿用新设定",
            source="cli",
            affects_future=True,
            scope="future_episodes",
            direct_writer_instruction=True,
        )
        context = build_episode_context(self.project_dir, 2)
        instructions = [o["instruction"] for o in context["writer_overrides"]]
        self.assertIn("未来集沿用新设定", instructions)
        self.assertNotIn("保留顺口溜", instructions)

    def test_craft_modules_selected_by_genre_and_function(self):
        context = build_episode_context(self.project_dir, 1)
        modules = context["selected_craft_modules"]
        self.assertIn("comedy", modules)
        self.assertIn("romance", modules)
        self.assertIn("hook", modules)
        self.assertNotIn("suspense", modules)

    def test_evidence_retrieval_fallback_does_not_hard_block_with_adaptation_basis(self):
        outlines = __import__("json").loads(
            (self.project_dir / "artifacts" / "episode_outline" / "episode_outlines.json").read_text(encoding="utf-8")
        )
        outlines["episodes"][1]["source_event_ids"] = ["NOPE"]
        outlines["episodes"][1]["source_chapters"] = []
        outlines["episodes"][1]["adaptation_basis"] = ["编剧要求新增场景"]
        outlines["episodes"][1]["must_keep"] = ["新增场景"]
        outlines["episodes"][1]["episode_goal"] = "新增目标"
        outlines["episodes"][1]["opening_bridge"] = "新增承接"
        outlines["episodes"][1]["ending_hook"] = "新增钩子"
        outlines["episodes"][1]["dialogue_anchors"] = []
        path = self.project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
        path.write_text(__import__("json").dumps(outlines, ensure_ascii=False), encoding="utf-8")
        record_artifact(self.project_dir, "episode_outline", path, source="ai", status="approved")
        context = build_episode_context(self.project_dir, 2)
        self.assertTrue(context["source_evidence"]["retrieval_report"]["fallback_used"])
        self.assertTrue(context["completeness"]["evidence_problems"])


if __name__ == "__main__":
    unittest.main()
