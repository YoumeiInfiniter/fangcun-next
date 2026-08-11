"""End-to-end tests for the Fangcun Next CLI."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.project_cli import main


CONFIG = {
    "project_id": "cli-e2e",
    "novel_name": "测试小说",
    "drama_name": "测试短剧",
    "platform": "竖屏短剧",
    "aspect_ratio": "9:16",
    "genre": ["喜剧", "甜宠"],
    "initial_episode_count": 2,
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
        "source_event_ids": ["CH001-E01", "CH001-E02"],
        "source_chapters": [1],
        "opening_bridge": "谢淮舟提出离婚",
        "episode_goal": "建立系统规则",
        "must_keep": ["谢淮舟提出录完节目离婚", "雷击错绑"],
        "causal_chains": [["系统登场", "雷击错绑"]],
        "knowledge_at_start": {},
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

SCRIPT1 = """第1集：系统绑错人

1-1 谢家书房 夜 内
人物：叶聆、谢淮舟、996

△谢淮舟将离婚协议放到叶聆面前。
谢淮舟（冷淡）：录完节目，我们离婚。
叶聆（OS）：我的三亿呢？

△半空弹出一只发光小团。
996：炮灰自救系统996号为您服务！
"""


class ProjectCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project_dir = self.root / "projects" / "cli-e2e"
        self.config_file = self.root / "config.json"
        self.config_file.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        self.novel = self.root / "novel.txt"
        self.novel.write_text(NOVEL, encoding="utf-8")
        self.events = self.root / "events.json"
        self.events.write_text(json.dumps(EVENTS, ensure_ascii=False), encoding="utf-8")
        self.outlines = self.root / "outlines.json"
        self.outlines.write_text(json.dumps({"episodes": OUTLINES}, ensure_ascii=False), encoding="utf-8")
        self.script = self.root / "script1.txt"
        self.script.write_text(SCRIPT1, encoding="utf-8")
        self._old_workspace_root = os.environ.get("FANGCUN_WORKSPACE_ROOT")
        os.environ["FANGCUN_WORKSPACE_ROOT"] = str(self.root)

    def tearDown(self):
        if self._old_workspace_root is None:
            os.environ.pop("FANGCUN_WORKSPACE_ROOT", None)
        else:
            os.environ["FANGCUN_WORKSPACE_ROOT"] = self._old_workspace_root
        self._tmp.cleanup()

    def run_cli(self, *argv, expect=0):
        code = main(list(argv))
        self.assertEqual(code, expect, f"CLI 失败: {argv}")

    def enable_feishu_group_delivery(self):
        (self.project_dir / ".feishu-output.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "channel": "feishu",
                    "chat_type": "group",
                    "auto_sync_on_group": True,
                    "stop_for_confirmation": True,
                    "default_folder_token": None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _draft_binding(self, episode: int) -> dict:
        from scripts.state_store import active_version_id, draft_meta_record

        version = active_version_id(self.project_dir, "script_draft", episode)
        self.assertIsNotNone(version)
        meta = draft_meta_record(self.project_dir, episode, version)
        self.assertIsNotNone(meta)
        return {"draft_version": version, **meta}

    def _save_outlines_confirmed(self, path: Path | None = None) -> None:
        from scripts.state_store import active_version_id

        self.run_cli(
            "save-episode-outline", "--dir", str(self.project_dir),
            "--outline-json", str(path or self.outlines),
            "--manual-import", "--manual-reason", "unit-test writer fixture",
        )
        version = active_version_id(self.project_dir, "episode_outline")
        self.run_cli(
            "confirm-stage", "--dir", str(self.project_dir),
            "--stage", "episode_outline", "--version", str(version),
            "--operator", "unit-test-writer", "--confirmation-ref", "unit-test-message-1",
            "--override-reason", "unit-test writer fixture reviewed",
        )

    def test_full_local_workflow(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.run_cli("ingest-source", "--dir", str(self.project_dir), "--file", str(self.novel))
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))
        self.run_cli("estimate-capacity", "--dir", str(self.project_dir))
        self._save_outlines_confirmed()
        self.run_cli("get-episode-context", "--dir", str(self.project_dir), "--episode", "1")
        self.run_cli("save-draft", "--dir", str(self.project_dir), "--episode", "1", "--file", str(self.script))

        binding = self._draft_binding(1)
        review = {
            "episode": 1,
            "context_hash": binding["context_hash"],
            "draft_hash": binding["draft_hash"],
            "draft_version": binding["draft_version"],
            "verdict": "blocked",
            "summary": "存在台词铺垫缺失",
            "issues": [
                {
                    "id": "DIALOGUE-001",
                    "severity": "error",
                    "category": "dialogue_pairing",
                    "problem": "删除了原文铺垫",
                    "evidence": {"evidence_type": "source", "quote": "什么动静？"},
                    "fix": "恢复铺垫",
                }
            ],
        }
        review_file = self.root / "review.json"
        review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        self.run_cli("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(review_file))
        self.run_cli("approve", "--dir", str(self.project_dir), "--episode", "1", "--file", str(self.script))
        self.run_cli("refresh-continuity", "--dir", str(self.project_dir))
        self.run_cli("forecast-duration", "--dir", str(self.project_dir))
        self.run_cli("status", "--dir", str(self.project_dir))
        self.run_cli("export", "--dir", str(self.project_dir))
        self.assertTrue((self.project_dir / "export" / "export.txt").exists())

    def test_review_api_uses_same_derived_verdict_save_path(self):
        from scripts.state_store import active_artifact_path

        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.run_cli("ingest-source", "--dir", str(self.project_dir), "--file", str(self.novel))
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))
        self._save_outlines_confirmed()
        self.run_cli("get-episode-context", "--dir", str(self.project_dir), "--episode", "1")
        self.run_cli("save-draft", "--dir", str(self.project_dir), "--episode", "1", "--file", str(self.script))
        binding = self._draft_binding(1)
        model_report = {
            "episode": 1,
            "context_hash": binding["context_hash"],
            "draft_hash": binding["draft_hash"],
            "draft_version": binding["draft_version"],
            "verdict": "blocked",
            "summary": "没有有效问题",
            "issues": [],
        }
        with mock.patch(
            "scripts.model_adapter.call_generate",
            return_value=json.dumps(model_report, ensure_ascii=False),
        ):
            self.run_cli("review", "--dir", str(self.project_dir), "--episode", "1", "--api")
        saved = json.loads(active_artifact_path(self.project_dir, "review", 1).read_text(encoding="utf-8"))
        self.assertEqual(saved["verdict"], "pass")
        self.assertEqual(saved["model_verdict"], "blocked")

    def test_review_error_without_evidence_is_rejected(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.run_cli("ingest-source", "--dir", str(self.project_dir), "--file", str(self.novel))
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))
        self._save_outlines_confirmed()
        self.run_cli("get-episode-context", "--dir", str(self.project_dir), "--episode", "1")
        self.run_cli("save-draft", "--dir", str(self.project_dir), "--episode", "1", "--file", str(self.script))
        binding = self._draft_binding(1)
        review = {
            "episode": 1,
            "context_hash": binding["context_hash"],
            "draft_hash": binding["draft_hash"],
            "draft_version": binding["draft_version"],
            "verdict": "blocked",
            "summary": "无证据",
            "issues": [{"id": "X1", "severity": "error", "category": "causality", "problem": "断裂"}],
        }
        bad = self.root / "bad_review.json"
        bad.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        self.run_cli("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(bad), expect=1)

    def test_revision_affects_future_context(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.run_cli("ingest-source", "--dir", str(self.project_dir), "--file", str(self.novel))
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))
        self._save_outlines_confirmed()
        self.run_cli(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "下一集沿用新规则",
            "--auto-approve",
        )
        self.run_cli("get-episode-context", "--dir", str(self.project_dir), "--episode", "2")
        from scripts.context_builder import current_context_path

        context_file = current_context_path(self.project_dir, 2)
        self.assertIsNotNone(context_file)
        context = json.loads(context_file.read_text(encoding="utf-8"))
        self.assertTrue(any("下一集沿用新规则" in o["instruction"] for o in context["writer_overrides"]))

    def test_init_with_brief_writes_input_file(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--project-id", "brief-proj", "--drama-name", "测试", "--brief", "改成15集甜宠")
        brief = self.project_dir / "state" / "project_brief_input.md"
        self.assertTrue(brief.exists())
        self.assertIn("15集甜宠", brief.read_text(encoding="utf-8"))

    def test_save_stage_emits_feishu_sync_event_in_group_context(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.enable_feishu_group_delivery()
        strategy = self.root / "strategy.md"
        strategy.write_text("# 改编指引\n\n请导演验收。\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.run_cli(
                "save-adaptation", "--dir", str(self.project_dir), "--file", str(strategy),
                "--manual-import", "--manual-reason", "unit-test writer fixture",
            )
        lines = [line for line in buf.getvalue().splitlines() if line.startswith("FANGCUN_FEISHU_SYNC_EVENT:")]
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0].split(":", 1)[1])
        self.assertEqual(event["kind"], "adaptation_strategy")
        self.assertEqual(event["sync_version"], "v001")
        self.assertIsNone(event["folder_token"])
        self.assertIn("未指定输出文件夹", event.get("notice", ""))
        self.assertTrue(Path(event["event_file"]).exists())

    def test_feishu_delivery_record_requires_readback_and_writes_registry(self):
        from scripts.feishu_artifact_delivery import main as delivery_main

        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.enable_feishu_group_delivery()
        outline = self.root / "outline.md"
        outline.write_text("# 故事大纲\n\n验收版。\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.run_cli(
                "save-story-outline", "--dir", str(self.project_dir), "--file", str(outline),
                "--manual-import", "--manual-reason", "unit-test writer fixture",
            )
        event_line = next(line for line in buf.getvalue().splitlines() if line.startswith("FANGCUN_FEISHU_SYNC_EVENT:"))
        event = json.loads(event_line.split(":", 1)[1])
        with self.assertRaises(SystemExit):
            delivery_main(["record", "--event-file", event["event_file"], "--doc-token", "DOC123", "--url", "https://feishu.cn/docx/DOC123"])
        delivery_main([
            "record", "--event-file", event["event_file"], "--doc-token", "DOC123",
            "--url", "https://feishu.cn/docx/DOC123", "--readback-ok",
        ])
        registry = json.loads(Path(event["registry"]).read_text(encoding="utf-8"))
        version = registry["artifacts"][0]["versions"][0]
        self.assertEqual(version["doc_token"], "DOC123")
        self.assertEqual(version["version"], "v001")

    def test_save_episode_outline_accepts_single_object(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        self.run_cli("ingest-source", "--dir", str(self.project_dir), "--file", str(self.novel))
        self.run_cli("save-events", "--dir", str(self.project_dir), "--file", str(self.events))
        single = self.root / "single_outline.json"
        single.write_text(json.dumps(OUTLINES[0], ensure_ascii=False), encoding="utf-8")
        self._save_outlines_confirmed(single)
        from scripts.state_store import active_artifact_path

        outlines = json.loads(active_artifact_path(self.project_dir, "episode_outline").read_text(encoding="utf-8"))
        self.assertEqual(len(outlines["episodes"]), 1)

    def test_check_api_without_config_fails_cleanly(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.run_cli("check-api", "--dir", str(self.project_dir), expect=1)

    def test_check_api_with_local_deepseek_config_fails_cleanly_without_key(self):
        self.run_cli("init", "--dir", str(self.project_dir), "--config", str(self.config_file))
        local = self.project_dir / "config.local.json"
        local.write_text(
            json.dumps(
                {
                    "model_config": {
                        "api_url": "https://api.deepseek.com",
                        "api_key_env": "DEEPSEEK_API_KEY",
                        "model": "deepseek-chat",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.run_cli("check-api", "--dir", str(self.project_dir), expect=1)

    def test_review_verdict_normalization_maps_needs_revision(self):
        from scripts.project_cli import _normalize_verdict

        self.assertEqual(_normalize_verdict("needs_revision", []), "blocked")
        self.assertEqual(_normalize_verdict("通过", []), "pass")
        self.assertEqual(_normalize_verdict("unknown", [{"severity": "warning"}]), "warning")
        self.assertEqual(_normalize_verdict("unknown", [{"severity": "error"}]), "blocked")
        self.assertEqual(_normalize_verdict("unknown", []), "pass")


if __name__ == "__main__":
    unittest.main()
