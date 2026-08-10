"""P2-3 (0.3.3): span locator ambiguity guard and fuzzy match counting.

- unique_required=True + 重复片段 + 未显式 occurrence → ambiguous_occurrence /
  needs_reanchor，禁止静默选第一个位置；
- 显式 --occurrence N 仍可选中第 N 次；
- fuzzy 下的 matches 计数按归一化文本计算；
- 默认函数行为保持向后兼容（unique_required=False 不改变旧调用）。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_cli import main
from scripts.span_locator import locate_span


def run_cli(*argv: str, expect: int = 0) -> str:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    output = out.getvalue() + err.getvalue()
    if code != expect:
        raise AssertionError(
            f"CLI returned {code}, expected {expect}: {' '.join(argv)}\n{output[-2000:]}"
        )
    return out.getvalue()


CONFIG = {
    "project_id": "spanloc",
    "novel_name": "测试小说",
    "drama_name": "测试短剧",
    "platform": "竖屏短剧",
    "aspect_ratio": "9:16",
    "genre": ["喜剧"],
    "initial_episode_count": 2,
    "minimum_episode_seconds": 60,
    "preferred_episode_seconds": [60, 90],
    "script_format": "default-cn",
    "fidelity": "medium",
    "dialogue_policy": "prefer_original",
    "writer_has_final_authority": True,
}


class SpanLocatorAmbiguityTests(unittest.TestCase):
    def test_default_behavior_backward_compatible(self):
        """不启用歧义保护时，旧行为不变（重复文本默认返回第一个位置+matches 计数）。"""
        result = locate_span("事件X。事件X。", "事件X。")
        self.assertTrue(result["found"])
        self.assertEqual(result["span"]["start"], 0)
        self.assertEqual(result["matches"], 2)

    def test_ambiguous_guard_blocks_duplicate(self):
        result = locate_span("事件X。事件X。", "事件X。", unique_required=True)
        self.assertFalse(result["found"])
        self.assertEqual(result["reason"], "ambiguous_occurrence")
        self.assertEqual(result["suggest"], "needs_reanchor")
        self.assertEqual(result["matches"], 2)
        self.assertIn("--occurrence", result["message"])

    def test_ambiguous_guard_allows_unique(self):
        result = locate_span("事件X。事件Y。", "事件X。", unique_required=True)
        self.assertTrue(result["found"])
        self.assertEqual(result["span"], {"start": 0, "end": 4})

    def test_ambiguous_guard_respects_explicit_occurrence(self):
        result = locate_span("事件X。事件X。", "事件X。", occurrence=2, unique_required=True)
        self.assertTrue(result["found"])
        self.assertEqual(result["span"]["start"], 4)

    def test_ambiguous_guard_occurrence_gt1_skips_check(self):
        # unique_required 只在 occurrence==1 时拦截；occurrence>1 本身已显式指定
        result = locate_span("事件X。事件X。事件X。", "事件X。", occurrence=3, unique_required=True)
        self.assertTrue(result["found"])
        self.assertEqual(result["span"]["start"], 8)

    def test_fuzzy_matches_count_normalized(self):
        text = "事件一\n开始。事件一 开始。"
        result = locate_span(text, "事件一开始。", fuzzy=True)
        self.assertTrue(result["found"])
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["source_quote"], "事件一\n开始。")

    def test_fuzzy_ambiguous_guard(self):
        text = "事件一\n开始。事件一 开始。"
        result = locate_span(text, "事件一开始。", fuzzy=True, unique_required=True)
        self.assertFalse(result["found"])
        self.assertEqual(result["reason"], "ambiguous_occurrence")
        self.assertEqual(result["matches"], 2)

    def test_not_found_still_needs_reanchor(self):
        result = locate_span("事件X。", "不存在的片段")
        self.assertFalse(result["found"])
        self.assertEqual(result["reason"], "not_found")
        self.assertEqual(result["suggest"], "needs_reanchor")


class SpanLocatorCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        self.novel_path = self.root / "novel.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def _project_with_duplicate(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        run_cli("init", "--dir", str(self.project), "--config", str(config_path))
        self.novel_path.write_text("第一章 当前\n她转身离开。她转身离开。\n", encoding="utf-8")
        run_cli("ingest-source", "--dir", str(self.project), "--file", str(self.novel_path), "--overwrite")

    def test_cli_ambiguous_without_occurrence(self):
        self._project_with_duplicate()
        out = run_cli("locate-span", "--dir", str(self.project), "--chapter", "1", "--text", "她转身离开。")
        result = json.loads(out)
        self.assertFalse(result["found"])
        self.assertEqual(result["reason"], "ambiguous_occurrence")
        self.assertEqual(result["suggest"], "needs_reanchor")
        self.assertEqual(result["matches"], 2)

    def test_cli_explicit_occurrence_selects_second(self):
        self._project_with_duplicate()
        out = run_cli("locate-span", "--dir", str(self.project), "--chapter", "1",
                      "--text", "她转身离开。", "--occurrence", "2")
        result = json.loads(out)
        self.assertTrue(result["found"])
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        first = chapter.index("她转身离开。")
        second = chapter.index("她转身离开。", first + 1)
        self.assertEqual(result["span"]["start"], second)
        self.assertEqual(result["occurrence"], 2)
        self.assertEqual(result["coordinate_base"], "chapter_file_content")
        self.assertEqual(len(result["chapter_content_hash"]), 64)
        self.assertEqual(result["source_quote"], "她转身离开。")


if __name__ == "__main__":
    unittest.main()
