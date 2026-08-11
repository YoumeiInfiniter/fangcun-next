"""Event browser HTML generation tests."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from scripts.project_cli import main


CONFIG = {
    "project_id": "browser-e2e",
    "novel_name": "测试小说",
    "drama_name": "测试短剧",
    "platform": "竖屏短剧",
    "aspect_ratio": "9:16",
    "genre": ["喜剧", "甜宠"],
    "initial_episode_count": 1,
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
        "source_span": {"start": 0, "end": 30},
        "key_quotes": [{"speaker": "谢淮舟", "text": "什么动静？"}],
    },
    {
        "event_id": "CH001-E02",
        "chapter_id": 1,
        "event": "雷击错绑",
        "importance": "mainline",
        "source_span": {"start": 30, "end": 80},
        "key_quotes": [{"speaker": "996", "text": "绑错惩罚对象了。"}],
    },
]

OUTLINES = [
    {
        "episode": 1,
        "title": "系统绑错人",
        "source_event_ids": ["CH001-E01"],
        "source_chapters": [1],
        "opening_bridge": "谢淮舟提出离婚",
        "episode_goal": "建立系统规则",
        "must_keep": ["谢淮舟提出录完节目离婚"],
        "causal_chains": [["系统登场", "雷击错绑"]],
        "knowledge_at_start": {},
        "knowledge_at_end": {"谢淮舟": ["能听见系统"]},
        "ending_hook": "996承认绑错惩罚对象",
        "suggested_seconds": [90, 130],
        "episode_function": ["opening", "hook"],
    },
]


class EventBrowserTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project_dir = self.root / "projects" / "browser-e2e"
        self.config_file = self.root / "config.json"
        self.config_file.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        self.novel = self.root / "novel.txt"
        self.novel.write_text(NOVEL, encoding="utf-8")
        self.events = self.root / "events.json"
        self.events.write_text(json.dumps(EVENTS, ensure_ascii=False), encoding="utf-8")
        self.outlines = self.root / "outlines.json"
        self.outlines.write_text(json.dumps({"episodes": OUTLINES}, ensure_ascii=False), encoding="utf-8")
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.run_cli("ingest-source", "--dir", str(self.project_dir), "--file", str(self.novel))
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv, expect=0):
        code = main(list(argv))
        self.assertEqual(code, expect, f"CLI 失败: {argv}")

    def _save_outline(self):
        self.run_cli(
            "save-episode-outline", "--dir", str(self.project_dir),
            "--outline-json", str(self.outlines),
            "--manual-import", "--manual-reason", "unit-test writer fixture",
        )

    def _html_path(self):
        return self.project_dir / "event_browser" / "index.html"

    def test_cli_generates_browser_html(self):
        self._save_outline()
        self.run_cli("event-browser", "--dir", str(self.project_dir))
        html = self._html_path()
        self.assertTrue(html.exists())
        text = html.read_text(encoding="utf-8")
        # 事件行 + 详情 JSON + 原文高亮
        self.assertIn('class="ev used"', text)
        self.assertIn("CH001-E01", text)
        m = re.search(r"const DETAILS=(\{.*?\});\nlet curF", text, re.DOTALL)
        self.assertIsNotNone(m, "缺少 DETAILS 数据")
        details = json.loads(m.group(1))
        self.assertIn("CH001-E01", details)
        self.assertIn('class="evmark"', text)

    def test_save_episode_outline_auto_rebuilds_browser(self):
        # 未手动跑 event-browser：保存集纲后应自动重建
        self._save_outline()
        html = self._html_path()
        self.assertTrue(html.exists(), "save-episode-outline 后未自动生成事件浏览器")
        self.assertIn("CH001-E02", html.read_text(encoding="utf-8"))

    def test_save_events_auto_rebuilds_browser(self):
        # 集纲已存在后重新保存事件，浏览器应跟随最新事件资产更新
        self._save_outline()
        html = self._html_path()
        self.assertTrue(html.exists())
        extra = {
            "event_id": "CH001-E03",
            "chapter_id": 1,
            "event": "新增事件",
            "importance": "subline",
            "source_span": {"start": 40, "end": 60},
        }
        evs = EVENTS + [extra]
        self.events.write_text(json.dumps(evs, ensure_ascii=False), encoding="utf-8")
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))
        self.assertIn("CH001-E03", html.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
