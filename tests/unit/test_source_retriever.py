"""Unit tests for anchor-driven source retrieval."""

import tempfile
import unittest
from pathlib import Path

from scripts.source_ingest import ingest_novel
from scripts.source_retriever import retrieve_source_evidence, source_evidence_complete


LONG_CHAPTER = """第一章 长章节
第一句话介绍了主角。第二句话发生了冲突。第三句话是事件结果。
谢淮舟：吃得苦中苦，你就能得到——
叶聆：吃不完的苦。
这句话发生在雷击之前。这句话发生在雷击之后。
雷击错绑后，叶聆与996同时震惊。996承认绑错了对象。
"""


class SourceRetrieverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "project"
        novel = self.project_dir.parent / "novel.txt"
        novel.write_text(LONG_CHAPTER, encoding="utf-8")
        ingest_novel(self.project_dir, novel)
        self.events = [
            {
                "event_id": "CH001-E01",
                "chapter_id": 1,
                "event": "系统发布任务",
                "importance": "mainline",
                "source_span": {"start": 0, "end": 40},
                "key_quotes": [
                    {"speaker": "谢淮舟", "text": "吃得苦中苦，你就能得到——", "must_preserve_pairing": True},
                    {"speaker": "叶聆", "text": "吃不完的苦。", "must_preserve_pairing": True},
                ],
            },
            {
                "event_id": "CH001-E02",
                "chapter_id": 1,
                "event": "雷击错绑",
                "dependencies": ["CH001-E01"],
                "importance": "mainline",
                "source_span": {"start": 60, "end": 130},
            },
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def _outline(self, **overrides) -> dict:
        outline = {
            "episode": 1,
            "title": "系统绑错人",
            "source_event_ids": ["CH001-E01", "CH001-E02"],
            "source_chapters": [1],
            "opening_bridge": "谢淮舟提出离婚",
            "episode_goal": "建立系统与雷击规则",
            "must_keep": ["五秒牵手任务", "雷击错绑"],
            "causal_chains": [["系统发布任务", "雷击错绑"]],
            "knowledge_at_start": {},
            "knowledge_at_end": {},
            "ending_hook": "996承认绑错",
            "dialogue_anchors": [
                {"setup": "吃得苦中苦，你就能得到——", "payoff": "吃不完的苦。", "source": "第1章"}
            ],
        }
        outline.update(overrides)
        return outline

    def test_retrieves_by_event_ids_and_keeps_quote_intact(self):
        evidence = retrieve_source_evidence(self.project_dir, self._outline(), self.events, max_chars=5000)
        self.assertEqual(evidence["chapter_ids"], [1])
        self.assertEqual(len(evidence["events"]), 2)
        text = "\n".join(ex["text"] for ex in evidence["raw_excerpts"])
        self.assertIn("吃得苦中苦，你就能得到——", text)
        self.assertIn("吃不完的苦。", text)
        self.assertFalse(evidence["retrieval_report"]["fallback_used"])

    def test_short_chapter_is_included_whole(self):
        evidence = retrieve_source_evidence(self.project_dir, self._outline(), self.events, max_chars=5000)
        full = [ex for ex in evidence["raw_excerpts"] if ex["reason"] == "chapter_full"]
        self.assertTrue(full)

    def test_excerpts_respect_sentence_boundaries(self):
        evidence = retrieve_source_evidence(self.project_dir, self._outline(), self.events, max_chars=200)
        text = evidence["raw_excerpts"][0]["text"]
        # Excerpt may start at a sentence boundary; verify no partial sentence
        # is introduced by checking that the first char is not mid-sentence
        # (snapped spans start after 。！？!?\n or at 0).
        chapter_text = self.project_dir.joinpath("source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start = evidence["raw_excerpts"][0]["source_span"]["start"]
        self.assertTrue(start == 0 or chapter_text[start - 1] in "。！？!?\n", f"start={start}")

    def test_dependency_events_are_included(self):
        outline = self._outline(source_event_ids=["CH001-E02"], source_chapters=[])
        evidence = retrieve_source_evidence(self.project_dir, outline, self.events, max_chars=5000)
        ids = {e["event_id"] for e in evidence["events"]}
        self.assertIn("CH001-E01", ids)

    def test_keyword_fallback_when_anchors_missing(self):
        outline = self._outline(source_event_ids=[], source_chapters=[], title="雷击")
        evidence = retrieve_source_evidence(self.project_dir, outline, self.events, max_chars=2000)
        self.assertTrue(evidence["raw_excerpts"])
        self.assertIn("keywords", evidence["retrieval_report"]["order_used"])
        self.assertFalse(evidence["retrieval_report"]["fallback_used"])

    def test_proportional_fallback_only_when_nothing_resolves(self):
        outline = self._outline(
            source_event_ids=[],
            source_chapters=[],
            title="不存在的词",
            episode_goal="不存在的目标",
            opening_bridge="不存在的桥",
            ending_hook="不存在的钩子",
            must_keep=["不存在的任务"],
            dialogue_anchors=[],
        )
        evidence = retrieve_source_evidence(self.project_dir, outline, [], max_chars=1000)
        self.assertTrue(evidence["retrieval_report"]["fallback_used"])
        problems = source_evidence_complete(evidence)
        self.assertTrue(any("比例回退" in p for p in problems))

    def test_empty_evidence_is_reported_incomplete(self):
        problems = source_evidence_complete({"chapter_ids": [], "events": [], "raw_excerpts": []})
        self.assertGreaterEqual(len(problems), 1)

    def test_budget_keeps_mainline_and_marks_truncated(self):
        evidence = retrieve_source_evidence(self.project_dir, self._outline(), self.events, max_chars=60)
        self.assertTrue(evidence["retrieval_report"]["truncated"])
        reasons = [ex["reason"] for ex in evidence["raw_excerpts"]]
        self.assertTrue(any("event:CH001-E01" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
