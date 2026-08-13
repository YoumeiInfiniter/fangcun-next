"""Fangcun Next 0.3.0 Agent-first public acceptance cases.

Covers the fourth implementation contract: density propagation, draft
metrics, standard/quick modes, V2 outline contract, project-rule isolation,
default-zero-API and honest experimental API failure.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.project_cli import main
from scripts.state_store import (
    active_artifact_path,
    active_version_id,
    artifact_version_record,
    draft_meta_record,
)


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
    return output


CONFIG = {
    "project_id": "v030",
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


def make_event(event_id: str, chapter: int, start: int, end: int, text: str, *, min_s: int = 20, pref_s: int = 35) -> dict:
    return {
        "event_id": event_id,
        "chapter_id": chapter,
        "event": text,
        "source_span": {"start": start, "end": end},
        "source_quote": text,
        "importance": "mainline",
        "minimum_screen_seconds": min_s,
        "preferred_screen_seconds": pref_s,
    }


def base_outline(**overrides) -> dict:
    outline = {
        "episode": 1,
        "title": "第一集",
        "source_event_ids": ["CH001-E01"],
        "source_chapters": [1],
        "opening_bridge": "承接",
        "episode_goal": "目标",
        "must_keep": [{"text": "事件一开始", "event_id": "CH001-E01"}],
        "causal_chains": [["触发", "结果"]],
        "knowledge_at_start": {},
        "knowledge_at_end": {},
        "dialogue_anchors": [],
        "ending_hook": "钩子",
        "suggested_seconds": [60, 90],
        "episode_function": ["opening"],
    }
    outline.update(overrides)
    return outline


class V030AgentFirstTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        self.novel_path = self.root / "novel.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def _init(self, config: dict | None = None):
        config = config or CONFIG
        path = self.root / "config.json"
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        run_cli("init", "--dir", str(self.project), "--config", str(path))

    def _novel(self, text: str = "第一章 当前\n事件一开始。事件一结束。\n事件二开始。事件二结束。\n"):
        self.novel_path.write_text(text, encoding="utf-8")
        run_cli("ingest-source", "--dir", str(self.project), "--file", str(self.novel_path), "--overwrite")

    def _events(self, events: list[dict]):
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        run_cli("save-events", "--dir", str(self.project), "--file", str(path))

    def _save_outline(
        self,
        outline: dict,
        *,
        capacity: str | None = None,
        confirm: bool = True,
        expect: int = 0,
    ) -> str:
        path = self.root / "outline.json"
        path.write_text(json.dumps({"episodes": [outline]}, ensure_ascii=False), encoding="utf-8")
        save_output = run_cli(
            "save-episode-outline",
            "--dir",
            str(self.project),
            "--outline-json",
            str(path),
            "--manual-import",
            "--manual-reason",
            "v030 synthetic fixture",
        )
        if expect != 0:
            return ""
        if not confirm:
            return save_output
        version = active_version_id(self.project, "episode_outline")
        argv = [
            "confirm-stage",
            "--dir",
            str(self.project),
            "--stage",
            "episode_outline",
            "--version",
            str(version),
            "--operator",
            "v030-writer",
            "--confirmation-ref",
            "v030-message",
            "--override-reason",
            "synthetic fixture reviewed",
        ]
        if capacity:
            argv += ["--capacity-decision", capacity]
        run_cli(*argv)
        return str(version)

    def _setup_two_events(self, min_s: int = 20, pref_s: int = 35) -> dict:
        self._init()
        self._novel()
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start1 = chapter.index("事件一开始")
        start2 = chapter.index("事件二开始")
        events = [
            make_event("CH001-E01", 1, start1, start1 + len("事件一开始。事件一结束。"), "事件一开始。事件一结束。", min_s=min_s, pref_s=pref_s),
            make_event("CH001-E02", 1, start2, start2 + len("事件二开始。事件二结束。"), "事件二开始。事件二结束。", min_s=min_s, pref_s=pref_s),
        ]
        self._events(events)
        return events

    def test_density_propagates_to_meta_markdown_stage_review_and_accept(self):
        self._setup_two_events(min_s=50, pref_s=80)
        outline = base_outline(
            source_event_ids=["CH001-E01", "CH001-E02"],
            must_keep=[
                {"text": "事件一开始", "event_id": "CH001-E01"},
                {"text": "事件二开始", "event_id": "CH001-E02"},
            ],
            suggested_seconds=[60, 90],
        )
        out = self._save_outline(outline, confirm=False)
        self.assertIn("容量风险", out)
        record = artifact_version_record(
            self.project,
            "episode_outline",
            None,
            active_version_id(self.project, "episode_outline"),
        )
        density = record["meta"]["density_reports"][0]
        self.assertEqual(density["pressure"], "high")
        self.assertEqual(density["binding"]["outline_version"], record["version"])
        self.assertEqual(density["binding"]["outline_hash"], record["content_hash"])
        md = active_artifact_path(self.project, "episode_outline_md").read_text(encoding="utf-8")
        self.assertIn("容量压力：high", md)
        version = active_version_id(self.project, "episode_outline")
        fail_out = run_cli(
            "confirm-stage",
            "--dir",
            str(self.project),
            "--stage",
            "episode_outline",
            "--version",
            str(version),
            "--operator",
            "v030-writer",
            "--confirmation-ref",
            "v030-message",
            "--override-reason",
            "synthetic fixture reviewed",
            expect=1,
        )
        self.assertIn("容量风险", fail_out)
        run_cli("generate-capacity-plan", "--dir", str(self.project))
        plan_options_path = self.project / "state" / "capacity_plan_options.json"
        plan_options = json.loads(plan_options_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(plan_options["options"]), 3)
        run_cli(
            "save-capacity-plan",
            "--dir",
            str(self.project),
            "--plan-json",
            str(plan_options_path),
            "--option-id",
            "quality_first_mainline",
            "--operator",
            "v030-writer",
            "--confirmation-ref",
            "v030-capacity-message",
        )
        capacity_plan_version = json.loads(
            (self.project / "state" / "active_versions.json").read_text(encoding="utf-8")
        )["capacity_plan"]["version"]
        run_cli(
            "confirm-stage",
            "--dir",
            str(self.project),
            "--stage",
            "episode_outline",
            "--version",
            str(version),
            "--operator",
            "v030-writer",
            "--confirmation-ref",
            "v030-message",
            "--override-reason",
            "synthetic fixture reviewed",
            "--capacity-plan-version",
            capacity_plan_version,
        )
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project, 1).read_text(encoding="utf-8"))
        self.assertEqual(context["advisory_timing"]["density_report"]["pressure"], "high")
        from scripts.capacity_plan import load_active_capacity_plan

        plan = load_active_capacity_plan(self.project, require_approved=True)
        self.assertEqual(plan["status"], "approved")
        self.assertEqual(plan["outline_hash"], record["content_hash"])

    def test_density_aggregate_enters_ai_stage_review_bundle(self):
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        self._setup_two_events(min_s=50, pref_s=80)
        adaptation_context = build_stage_context(self.project, "adaptation")
        adaptation = save_stage_artifact(
            self.project,
            stage="adaptation",
            content="# 改编指引\n保留当前事件。\n",
            stage_context=adaptation_context,
        )
        confirm_stage(
            self.project,
            stage="adaptation",
            version=adaptation["version"],
            operator="v030-writer",
            confirmation_ref="v030-adaptation",
            review_override_reason="synthetic fixture reviewed",
        )
        story_context = build_stage_context(self.project, "story_outline")
        story = save_stage_artifact(
            self.project,
            stage="story_outline",
            content="# 故事大纲\n主线。\n",
            stage_context=story_context,
        )
        confirm_stage(
            self.project,
            stage="story_outline",
            version=story["version"],
            operator="v030-writer",
            confirmation_ref="v030-story",
            review_override_reason="synthetic fixture reviewed",
        )
        episode_context = build_stage_context(self.project, "episode_outline")
        outline = base_outline(
            source_event_ids=["CH001-E01", "CH001-E02"],
            must_keep=[
                {"text": "事件一开始", "event_id": "CH001-E01"},
                {"text": "事件二开始", "event_id": "CH001-E02"},
            ],
            suggested_seconds=[60, 90],
        )
        outline_path = self.root / "outline_ai.json"
        outline_path.write_text(json.dumps({"episodes": [outline]}, ensure_ascii=False), encoding="utf-8")
        run_cli(
            "save-episode-outline",
            "--dir",
            str(self.project),
            "--outline-json",
            str(outline_path),
            "--stage-context-hash",
            episode_context["context_hash"],
        )
        review_out = run_cli(
            "review-stage",
            "--dir",
            str(self.project),
            "--stage",
            "episode_outline",
        )
        self.assertIn("集纲容量风险摘要", review_out)
        self.assertIn("high 1 集", review_out)

    def test_low_density_long_draft_metrics_and_system_timing_advisory(self):
        self._setup_two_events(min_s=5, pref_s=10)
        self._save_outline(
            base_outline(
                source_event_ids=["CH001-E01"],
                must_keep=[{"text": "事件一开始", "event_id": "CH001-E01"}],
                suggested_seconds=[60, 90],
            ),
            capacity=None,
        )
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        long_lines = "\n".join(f"叶聆：这是第{idx}句很长很长很长很长很长很长很长很长很长的台词。" for idx in range(30))
        script = f"第1集：第一集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n{long_lines}\n"
        draft = self.root / "draft.txt"
        draft.write_text(script, encoding="utf-8")
        run_cli("save-draft", "--dir", str(self.project), "--episode", "1", "--file", str(draft))
        version = active_version_id(self.project, "script_draft", 1)
        meta = draft_meta_record(self.project, 1, version)
        metrics = json.loads(active_artifact_path(self.project, "draft_metrics", 1).read_text(encoding="utf-8"))
        self.assertEqual(metrics["draft_version"], version)
        self.assertEqual(metrics["draft_hash"], meta["draft_hash"])
        self.assertEqual(metrics["deviation"], "above")
        run_cli("review", "--dir", str(self.project), "--episode", "1")
        bundle = (self.project / "state" / "prompt_bundles" / "ep001_reviewer.md").read_text(encoding="utf-8")
        self.assertIn("draft_metrics", bundle)
        self.assertIn(str(metrics["estimated_seconds"]), bundle)
        report = {
            "episode": 1,
            "context_hash": meta["context_hash"],
            "draft_hash": meta["draft_hash"],
            "draft_version": version,
            "verdict": "warning",
            "summary": "时长偏长但可接受",
            "issues": [
                {
                    "id": "TIMING-001",
                    "severity": "warning",
                    "category": "timing",
                    "problem": "台词较长，节奏可压缩",
                    "fix": "可压缩",
                }
            ],
            "timing_advisory": {"estimated_seconds": 1, "preferred_seconds": [60, 90], "blocking": False},
        }
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        run_cli("save-review", "--dir", str(self.project), "--episode", "1", "--file", str(review_path))
        saved = json.loads(active_artifact_path(self.project, "review", 1).read_text(encoding="utf-8"))
        self.assertEqual(saved["timing_advisory"]["estimated_seconds"], metrics["estimated_seconds"])
        self.assertEqual(saved["timing_advisory"]["deviation"], "above")
        self.assertEqual(saved["legacy_model_estimate"]["estimated_seconds"], 1)
        record = artifact_version_record(self.project, "script_draft", 1, version)
        self.assertEqual(record["status"], "reviewed")
        run_cli("approve", "--dir", str(self.project), "--episode", "1", "--file", str(draft))

    def test_shootability_severity_prompt_and_error_save(self):
        self._setup_two_events()
        self._save_outline(base_outline(), capacity=None)
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        script = "第1集：第一集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△事件一开始。\n△叶聆和996争执。\n叶聆：什么动静？\n996：绑错了。\n"
        draft = self.root / "draft.txt"
        draft.write_text(script, encoding="utf-8")
        run_cli("save-draft", "--dir", str(self.project), "--episode", "1", "--file", str(draft))
        version = active_version_id(self.project, "script_draft", 1)
        meta = draft_meta_record(self.project, 1, version)
        report = {
            "episode": 1,
            "context_hash": meta["context_hash"],
            "draft_hash": meta["draft_hash"],
            "draft_version": version,
            "verdict": "blocked",
            "summary": "核心反应没有演出",
            "issues": [
                {
                    "id": "SHOOT-001",
                    "severity": "error",
                    "category": "shootability",
                    "problem": "关键震惊反应只写成概述，观众无法理解发生过程",
                    "evidence": {"evidence_type": "source", "quote": "事件一开始"},
                    "fix": "演出震惊反应",
                }
            ],
        }
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        run_cli("save-review", "--dir", str(self.project), "--episode", "1", "--file", str(path))
        saved = json.loads(active_artifact_path(self.project, "review", 1).read_text(encoding="utf-8"))
        self.assertEqual(saved["verdict"], "blocked")
        reviewer_prompt = (Path(__file__).parents[2] / "references/prompts/reviewer.md").read_text(encoding="utf-8")
        self.assertIn("required_visual_beats", reviewer_prompt)
        self.assertIn("不得因为动作行较短就自动报错", reviewer_prompt)

    def test_project_rules_isolated_to_referencing_project(self):
        config_a = dict(CONFIG)
        config_a["project_id"] = "v030-a"
        config_a["project_specific_requirements"] = [
            {"id": "PRJ-A-001", "text": "项目A专用：系统面板必须可视化", "scope": "project_wide"}
        ]
        self._init(config_a)
        self._novel()
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start = chapter.index("事件一开始")
        self._events([
            make_event("CH001-E01", 1, start, start + len("事件一开始。事件一结束。"), "事件一开始。事件一结束。")
        ])
        outline_a = base_outline(project_rule_refs=["PRJ-A-001"])
        self._save_outline(outline_a, capacity=None)
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        from scripts.context_builder import current_context_path

        context_a = json.loads(current_context_path(self.project, 1).read_text(encoding="utf-8"))
        self.assertEqual(context_a["episode_outline"]["project_rule_refs"], ["PRJ-A-001"])
        bundle_a = (self.project / "state" / "prompt_bundles" / "ep001_writer.md").read_text(encoding="utf-8")
        self.assertIn("系统面板必须可视化", bundle_a)

        config_b = dict(CONFIG)
        config_b["project_id"] = "v030-b"
        self.project_b = self.root / "project_b"
        path_b = self.root / "config_b.json"
        path_b.write_text(json.dumps(config_b, ensure_ascii=False), encoding="utf-8")
        run_cli("init", "--dir", str(self.project_b), "--config", str(path_b))
        novel_b = self.root / "novel_b.txt"
        novel_b.write_text("第一章 当前\n事件一开始。事件一结束。\n", encoding="utf-8")
        run_cli("ingest-source", "--dir", str(self.project_b), "--file", str(novel_b), "--overwrite")
        chapter_b = (self.project_b / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start_b = chapter_b.index("事件一开始")
        events_b = [make_event("CH001-E01", 1, start_b, start_b + len("事件一开始。事件一结束。"), "事件一开始。事件一结束。")]
        events_path_b = self.root / "events_b.json"
        events_path_b.write_text(json.dumps(events_b, ensure_ascii=False), encoding="utf-8")
        run_cli("save-events", "--dir", str(self.project_b), "--file", str(events_path_b))
        outline_b = base_outline()
        outline_path_b = self.root / "outline_b.json"
        outline_path_b.write_text(json.dumps({"episodes": [outline_b]}, ensure_ascii=False), encoding="utf-8")
        run_cli(
            "save-episode-outline",
            "--dir",
            str(self.project_b),
            "--outline-json",
            str(outline_path_b),
            "--manual-import",
            "--manual-reason",
            "v030 synthetic fixture",
        )
        version_b = active_version_id(self.project_b, "episode_outline")
        run_cli(
            "confirm-stage",
            "--dir",
            str(self.project_b),
            "--stage",
            "episode_outline",
            "--version",
            str(version_b),
            "--operator",
            "v030-writer",
            "--confirmation-ref",
            "v030-message",
            "--override-reason",
            "synthetic fixture reviewed",
        )
        run_cli("get-episode-context", "--dir", str(self.project_b), "--episode", "1")
        bundle_b = (self.project_b / "state" / "prompt_bundles" / "ep001_writer.md").read_text(encoding="utf-8")
        self.assertNotIn("系统面板必须可视化", bundle_b)

    def test_standard_and_quick_modes_record_workflow_and_quick_cannot_approve(self):
        self._setup_two_events()
        self._save_outline(base_outline(), capacity=None)
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        standard = self.root / "standard.txt"
        standard.write_text("第1集：第一集\n\n1-1 家 夜 内\n人物：叶聆\n\n△事件一开始。\n△动作。\n叶聆：标准稿。\n", encoding="utf-8")
        run_cli("save-draft", "--dir", str(self.project), "--episode", "1", "--file", str(standard))
        standard_meta = draft_meta_record(self.project, 1, active_version_id(self.project, "script_draft", 1))
        self.assertEqual(standard_meta["workflow_mode"], "standard")
        self.assertEqual(standard_meta["semantic_review_status"], "pending_review")

        quick = self.root / "quick.txt"
        quick.write_text("第1集：第一集\n\n1-1 家 夜 内\n人物：叶聆\n\n△事件一开始。\n△动作。\n叶聆：快速稿。\n", encoding="utf-8")
        run_cli(
            "save-draft",
            "--dir",
            str(self.project),
            "--episode",
            "1",
            "--file",
            str(quick),
            "--workflow-mode",
            "quick_draft",
        )
        quick_meta = draft_meta_record(self.project, 1, active_version_id(self.project, "script_draft", 1))
        self.assertEqual(quick_meta["workflow_mode"], "quick_draft")
        self.assertEqual(quick_meta["semantic_review_status"], "unreviewed")
        self.assertIsNone(active_artifact_path(self.project, "review", 1))
        run_cli("approve", "--dir", str(self.project), "--episode", "1", "--file", str(quick), expect=1)
        self.assertIsNone(active_artifact_path(self.project, "approved_script", 1))

    def test_default_zero_api_and_experimental_length_fails_honestly(self):
        self._setup_two_events()
        self._save_outline(base_outline(), capacity=None)
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        script = self.root / "draft.txt"
        script.write_text("第1集：第一集\n\n1-1 家 夜 内\n人物：叶聆\n\n△事件一开始。\n△动作。\n叶聆：默认稿。\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FANGCUN_API_KEY": "sk-fake"}), mock.patch("requests.post") as post:
            run_cli("save-draft", "--dir", str(self.project), "--episode", "1", "--file", str(script))
            run_cli("review", "--dir", str(self.project), "--episode", "1")
            post.assert_not_called()
        version = active_version_id(self.project, "script_draft", 1)
        meta = draft_meta_record(self.project, 1, version)
        report = {
            "episode": 1,
            "context_hash": meta["context_hash"],
            "draft_hash": meta["draft_hash"],
            "draft_version": version,
            "verdict": "blocked",
            "summary": "截断",
            "issues": [
                {
                    "id": "LEN-001",
                    "severity": "error",
                    "category": "causality",
                    "problem": "问题",
                    "evidence": {"evidence_type": "source", "quote": "事件一开始"},
                    "fix": "修复",
                }
            ],
        }
        with mock.patch(
            "scripts.model_adapter.call_generate",
            side_effect=RuntimeError("finish_reason=length"),
        ):
            run_cli("review", "--dir", str(self.project), "--episode", "1", "--api", expect=1)
        self.assertIsNone(active_artifact_path(self.project, "review", 1))

    def test_v2_outline_fields_enter_context_and_old_compat(self):
        self._init()
        self._novel("第一章 当前\n事件一开始。关键台词原句。事件一结束。\n")
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start = chapter.index("事件一开始")
        self._events([
            make_event("CH001-E01", 1, start, len(chapter), "事件一开始。关键台词原句。事件一结束。")
        ])
        outline = base_outline(
            episode_focus="建立系统错绑规则",
            required_story_beats=[
                {"id": "B01", "text": "系统错绑必须发生", "event_ids": ["CH001-E01"], "priority": "core"}
            ],
            required_quotes=[
                {"quote": "关键台词原句", "source_event_id": "CH001-E01", "pair_id": "P01"}
            ],
            beat_plan=[
                {
                    "beat_id": "B01",
                    "function": "揭示错绑",
                    "event_ids": ["CH001-E01"],
                    "presentation": "full",
                    "estimated_seconds": [20, 35],
                    "visible_outcome": "观众看见雷击落到谢淮舟身上",
                    "required_visual_beats": ["谢淮舟被击中后的身体反应"],
                }
            ],
            overflow_options=[{"beat_id": "B01", "allowed_actions": ["compress", "accept_overflow"]}],
        )
        self._save_outline(outline, capacity=None)
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        context = json.loads(
            (self.project / "state" / "episode_contexts" / f"current_EP001.json").read_text(encoding="utf-8")
        )
        context_path = self.project / "state" / "episode_contexts" / context["path"]
        context = json.loads(context_path.read_text(encoding="utf-8"))
        self.assertEqual(context["episode_outline"]["episode_focus"], "建立系统错绑规则")
        coverage = context["source_evidence"]["coverage"]
        for anchor_type in ("required_story_beat", "required_quote"):
            self.assertTrue(any(c["anchor_type"] == anchor_type and not c["omitted"] for c in coverage))
        bundle = (self.project / "state" / "prompt_bundles" / "ep001_writer.md").read_text(encoding="utf-8")
        self.assertIn("required_story_beats", bundle)
        self.assertIn("本集容量压力", bundle)
        self.assertNotIn("high_episodes", bundle)
        self.assertNotIn("medium_episodes", bundle)
        from scripts.migration import mark_legacy_must_keep

        marked = mark_legacy_must_keep({"episode": 2, "must_keep": ["旧条目"]})
        self.assertEqual(marked["must_keep"][0]["legacy_classification"], "legacy_unspecified")

    def test_required_quote_rejects_same_chapter_text_outside_bound_event_span(self):
        self._setup_two_events()
        outline = base_outline(
            required_quotes=[
                {"quote": "事件二开始。", "source_event_id": "CH001-E01"}
            ]
        )
        path = self.root / "wrong-event-quote.json"
        path.write_text(json.dumps({"episodes": [outline]}, ensure_ascii=False), encoding="utf-8")
        output = run_cli(
            "save-episode-outline",
            "--dir",
            str(self.project),
            "--outline-json",
            str(path),
            "--manual-import",
            "--manual-reason",
            "required quote wrong-event regression",
            expect=1,
        )
        self.assertIn("required_quote", output)
        self.assertIn("quote_not_in_source_event", output)

    def test_required_quote_accepts_text_inside_bound_event_span(self):
        self._setup_two_events()
        outline = base_outline(
            required_quotes=[
                {"quote": "事件一开始。", "source_event_id": "CH001-E01"}
            ]
        )
        self._save_outline(outline)
        run_cli("get-episode-context", "--dir", str(self.project), "--episode", "1")
        pointer = json.loads(
            (self.project / "state" / "episode_contexts" / "current_EP001.json").read_text(encoding="utf-8")
        )
        context = json.loads(
            (self.project / "state" / "episode_contexts" / pointer["path"]).read_text(encoding="utf-8")
        )
        coverage = [
            item for item in context["source_evidence"]["coverage"]
            if item.get("anchor_type") == "required_quote"
        ]
        self.assertEqual(1, len(coverage))
        self.assertFalse(coverage[0]["omitted"])


if __name__ == "__main__":
    unittest.main()
