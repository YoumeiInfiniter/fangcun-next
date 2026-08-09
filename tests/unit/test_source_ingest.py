"""Unit tests for chapter indexing and source archiving."""

import tempfile
import unittest
from pathlib import Path

from scripts.source_ingest import (
    chapter_count,
    chapters_dir,
    ingest_novel,
    load_chapter_index,
    read_all_chapters,
    split_chapters,
)


NOVEL = """序章
叶聆完成任务，准备退休。

第一章 系统的声音
谢淮舟把离婚协议放下：录完节目，我们离婚。
叶聆心里想着：我的三亿呢？
半空弹出一只发光小团：炮灰自救系统996号为您服务！

第二章 吃不完的苦
996：吃得苦中苦，你就能得到——
叶聆：吃不完的苦。
"""


class SourceIngestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "project"
        self.novel = self.project_dir.parent / "novel.txt"
        self.novel.write_text(NOVEL, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_split_chapters_detects_headings(self):
        chapters = split_chapters(NOVEL)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0]["title"], "")
        self.assertEqual(chapters[1]["chapter_index"], 2)
        self.assertIn("系统", chapters[1]["heading"])

    def test_ingest_writes_chapter_files_and_index(self):
        result = ingest_novel(self.project_dir, self.novel)
        self.assertTrue(result["created"])
        self.assertEqual(result["chapters"], 3)
        files = sorted(p.name for p in chapters_dir(self.project_dir).glob("*.txt"))
        self.assertEqual(files, ["chapter_001.txt", "chapter_002.txt", "chapter_003.txt"])
        index = load_chapter_index(self.project_dir)
        self.assertEqual(index["total_chars"], len(NOVEL))
        self.assertEqual(index["coordinate_base"], "chapter_file_content")
        first = index["chapters"][0]
        stored = (self.project_dir / first["file"]).read_text(encoding="utf-8")
        self.assertEqual(stored, NOVEL[first["span"]["start"] : first["span"]["end"]])
        self.assertEqual(len(read_all_chapters(self.project_dir)), 3)

    def test_ingest_is_idempotent_on_same_file(self):
        ingest_novel(self.project_dir, self.novel)
        second = ingest_novel(self.project_dir, self.novel)
        self.assertFalse(second["created"])

    def test_ingest_single_unit_when_no_headings(self):
        plain = self.project_dir.parent / "plain.txt"
        plain.write_text("没有章节标题的一段正文。", encoding="utf-8")
        result = ingest_novel(self.project_dir, plain)
        self.assertEqual(result["chapters"], 1)
        self.assertEqual(chapter_count(self.project_dir), 1)


if __name__ == "__main__":
    unittest.main()
