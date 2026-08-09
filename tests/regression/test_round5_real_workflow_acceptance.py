"""Round-5 acceptance cases derived from the first real Fangcun Next run.

The fixtures are synthetic.  They preserve the production failure shapes
without copying the user's novel or project artifacts into the repository.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.context_builder import ContextIncompleteError, build_episode_context
from scripts.project_cli import main
from scripts.source_ingest import split_chapters
from scripts.source_retriever import _snap_span, retrieve_source_evidence
from scripts.state_store import (
    active_artifact_path,
    active_version_id,
    artifact_version_record,
    init_project,
)


CONFIG = {
    "project_id": "round5",
    "novel_name": "测试小说",
    "drama_name": "测试短剧",
    "platform": "竖屏短剧",
    "aspect_ratio": "9:16",
    "genre": ["喜剧"],
    "initial_episode_count": 3,
    "minimum_episode_seconds": 60,
    "preferred_episode_seconds": [90, 150],
    "script_format": "default-cn",
    "fidelity": "medium",
    "dialogue_policy": "prefer_original",
    "writer_has_final_authority": True,
}


def run_cli(*argv: str, expect: int = 0) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(argv))
    output = stdout.getvalue() + stderr.getvalue()
    if code != expect:
        raise AssertionError(
            f"CLI returned {code}, expected {expect}: {' '.join(argv)}\n{output[-2000:]}"
        )
    return output


class Round5RealWorkflowAcceptance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        init_project(self.project, dict(CONFIG))

    def tearDown(self):
        self._tmp.cleanup()

    def _write_novel(self, text: str) -> Path:
        path = self.root / "novel.txt"
        path.write_text(text, encoding="utf-8")
        run_cli("ingest-source", "--dir", str(self.project), "--file", str(path), "--overwrite")
        return path

    def _save_events(self, events: list[dict]) -> Path:
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        run_cli("save-events", "--dir", str(self.project), "--file", str(path))
        return path

    def _save_outline(self, outline: dict, *, expect: int = 0, extra: list[str] | None = None) -> str:
        path = self.root / "outline.json"
        path.write_text(json.dumps({"episodes": [outline]}, ensure_ascii=False), encoding="utf-8")
        output = run_cli(
            "save-episode-outline",
            "--dir",
            str(self.project),
            "--outline-json",
            str(path),
            "--manual-import",
            "--manual-reason",
            "synthetic writer fixture",
            *(extra or []),
            expect=expect,
        )
        if expect == 0:
            version = active_version_id(self.project, "episode_outline")
            run_cli(
                "confirm-stage",
                "--dir",
                str(self.project),
                "--stage",
                "episode_outline",
                "--version",
                str(version),
                "--operator",
                "round5-writer",
                "--confirmation-ref",
                "round5-outline-fixture-confirmation",
                "--override-reason",
                "synthetic writer fixture reviewed",
            )
        return output

    @staticmethod
    def _event(event_id: str, chapter: int, start: int, end: int, text: str, **extra) -> dict:
        return {
            "event_id": event_id,
            "chapter_id": chapter,
            "event": text,
            "source_span": {"start": start, "end": end},
            "source_quote": extra.pop("source_quote", ""),
            "importance": extra.pop("importance", "mainline"),
            "minimum_screen_seconds": extra.pop("minimum_screen_seconds", 20),
            "preferred_screen_seconds": extra.pop("preferred_screen_seconds", 35),
            **extra,
        }

    @staticmethod
    def _outline(**overrides) -> dict:
        base = {
            "episode": 1,
            "title": "第一集",
            "source_event_ids": ["CH001-E01"],
            "source_chapters": [1],
            "opening_bridge": "承接开场",
            "episode_goal": "完成当前事件",
            "must_keep": [{"text": "保留当前事件", "event_id": "CH001-E01"}],
            "causal_chains": [["触发", "行动", "结果"]],
            "knowledge_at_start": {},
            "knowledge_at_end": {},
            "dialogue_anchors": [],
            "ending_hook": "留下钩子",
            "suggested_seconds": [60, 90],
        }
        base.update(overrides)
        return base

    def test_section_sentence_is_not_a_chapter_heading(self):
        chapters = split_chapters(
            "第1章 开始\n正文。\n第二节是体育课。\n继续正文。\n第2章 后续\n结束。\n"
        )
        self.assertEqual([c["heading"] for c in chapters], ["第1章 开始", "第2章 后续"])

    def test_snap_span_keeps_event_when_start_is_sentence_start(self):
        text = "前一句。这个事件必须完整保留？！后一句。"
        start = text.index("这个事件")
        end = text.index("！") + 1
        snapped = _snap_span(text, start, end)
        self.assertLessEqual(snapped[0], start)
        self.assertGreaterEqual(snapped[1], end)
        self.assertIn("这个事件必须完整保留？！", text[snapped[0] : snapped[1]])

    def test_event_retrieval_uses_rich_event_context_not_quote_only(self):
        novel = "第1章 开始\n起因发生。人物犹豫。人物采取行动。对方作出反应。事件得到结果。下一事件开始。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        quote = "人物采取行动。"
        start = chapter.index(quote)
        self._save_events([
            self._event("CH001-E01", 1, start, start + len(quote), "起因到结果的完整事件", source_quote=quote)
        ])
        evidence = retrieve_source_evidence(
            self.project,
            self._outline(),
            json.loads(active_artifact_path(self.project, "source_events").read_text()),
        )
        event_excerpt = next(x for x in evidence["raw_excerpts"] if x["reason"] == "event:CH001-E01")
        self.assertIn("起因发生", event_excerpt["text"])
        self.assertIn("事件得到结果", event_excerpt["text"])

    def test_direct_anchors_do_not_trigger_unrelated_global_keyword_excerpt(self):
        novel = (
            "第1章 当前\n当前事件发生。关键台词。当前事件结束。\n"
            "第2章 无关\n" + "无关剧情。" * 300 + "关键台词。\n"
        )
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        quote = "关键台词。"
        start = chapter.index(quote)
        self._save_events([
            self._event(
                "CH001-E01",
                1,
                start,
                start + len(quote),
                "当前事件",
                source_quote=quote,
                key_quotes=[{"speaker": "甲", "text": quote}],
            )
        ])
        evidence = retrieve_source_evidence(
            self.project,
            self._outline(),
            json.loads(active_artifact_path(self.project, "source_events").read_text()),
        )
        self.assertFalse(any(x["chapter_id"] == 2 for x in evidence["raw_excerpts"]))
        self.assertFalse(any(str(x["reason"]).startswith("keyword:") for x in evidence["raw_excerpts"]))

    def test_single_quote_anchor_is_not_misclassified_as_missing_pair(self):
        novel = "第1章 当前\n前置动作。甲说：关键台词。对方震惊。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        quote = "关键台词。"
        start = chapter.index(quote)
        self._save_events([
            self._event(
                "CH001-E01",
                1,
                start,
                start + len(quote),
                "说出关键台词",
                source_quote=quote,
                key_quotes=[{"speaker": "甲", "text": quote}],
            )
        ])
        self._save_outline(
            self._outline(
                dialogue_anchors=[{"type": "quote", "quote": quote, "source_event_id": "CH001-E01"}]
            )
        )
        context = build_episode_context(self.project, 1, save=False)
        omitted = [x for x in context["source_evidence"]["coverage"] if x.get("omitted")]
        self.assertFalse(omitted)

    def test_unrelated_adaptation_basis_cannot_waive_missing_source_anchor(self):
        novel = "第1章 当前\n只有当前事件。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        quote = "当前事件"
        start = chapter.index(quote)
        self._save_events([
            self._event("CH001-E01", 1, start, start + len(quote), "当前事件", source_quote=quote)
        ])
        outline = self._outline(
            dialogue_anchors=[{
                "type": "pair",
                "setup": "不存在的提问",
                "payoff": "不存在的回答",
                "source_event_id": "CH001-E01",
            }],
            adaptation_basis=[{"id": "AD-UNRELATED", "text": "只允许调整场景时间"}],
        )
        output = self._save_outline(outline, expect=1)
        self.assertIn("dialogue_anchor", output)

    def test_unresolved_plain_text_must_keep_is_rejected_at_save(self):
        novel = "第1章 当前\n当前事件发生。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        start = chapter.index("当前事件")
        self._save_events([
            self._event("CH001-E01", 1, start, start + 4, "当前事件", source_quote="当前事件")
        ])
        output = self._save_outline(
            self._outline(must_keep=["完全不存在的必保留内容"]),
            expect=1,
        )
        self.assertIn("must_keep", output)

    def test_episode_outline_always_writes_matching_human_readable_version(self):
        novel = "第1章 当前\n当前事件发生。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        start = chapter.index("当前事件")
        self._save_events([
            self._event("CH001-E01", 1, start, start + 4, "当前事件", source_quote="当前事件")
        ])
        self._save_outline(self._outline())
        json_record = artifact_version_record(
            self.project, "episode_outline", None, active_version_id(self.project, "episode_outline")
        )
        md_record = artifact_version_record(
            self.project, "episode_outline_md", None, active_version_id(self.project, "episode_outline_md")
        )
        self.assertIsNotNone(md_record)
        self.assertEqual(
            json_record["meta"]["outline_sync_id"],
            md_record["meta"]["outline_sync_id"],
        )
        self.assertIn("第1集", active_artifact_path(self.project, "episode_outline_md").read_text())

    def test_ai_stage_save_is_not_approved_until_review_and_writer_confirmation(self):
        from scripts.stage_lifecycle import build_stage_context, save_stage_artifact

        context = build_stage_context(self.project, "adaptation")
        result = save_stage_artifact(
            self.project,
            stage="adaptation",
            content="# 改编指引\n",
            stage_context=context,
        )
        record = artifact_version_record(self.project, "adaptation_strategy", None, result["version"])
        self.assertEqual(record["status"], "needs_writer_confirmation")

    def test_downstream_stage_refuses_unconfirmed_or_stale_upstream(self):
        from scripts.stage_lifecycle import assert_stage_ready, build_stage_context, confirm_stage, save_stage_artifact

        context = build_stage_context(self.project, "adaptation")
        saved = save_stage_artifact(
            self.project, stage="adaptation", content="# v1\n", stage_context=context
        )
        with self.assertRaises(ValueError):
            assert_stage_ready(self.project, "story_outline")
        confirm_stage(
            self.project,
            stage="adaptation",
            version=saved["version"],
            operator="writer",
            confirmation_ref="round5-message-stage-ready",
            review_override_reason="writer confirmed after manual review",
        )
        assert_stage_ready(self.project, "story_outline")
        save_stage_artifact(
            self.project, stage="adaptation", content="# v2\n", stage_context=context
        )
        with self.assertRaises(ValueError):
            assert_stage_ready(self.project, "story_outline")

    def test_stage_confirmation_requires_auditable_user_reference(self):
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        context = build_stage_context(self.project, "adaptation")
        saved = save_stage_artifact(
            self.project, stage="adaptation", content="# 待确认\n", stage_context=context
        )
        with self.assertRaisesRegex(ValueError, "confirmation_ref"):
            confirm_stage(
                self.project,
                stage="adaptation",
                version=saved["version"],
                operator="writer",
                confirmation_ref="",
                review_override_reason="fixture",
            )

    def test_stage_context_binds_exact_upstream_versions_and_hashes(self):
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        base = build_stage_context(self.project, "adaptation")
        saved = save_stage_artifact(self.project, stage="adaptation", content="# v1\n", stage_context=base)
        confirm_stage(
            self.project,
            stage="adaptation",
            version=saved["version"],
            operator="writer",
            confirmation_ref="round5-message-upstream-binding",
            review_override_reason="manual confirmation",
        )
        context = build_stage_context(self.project, "story_outline")
        binding = next(x for x in context["upstream_bindings"] if x["kind"] == "adaptation_strategy")
        self.assertEqual(binding["version"], saved["version"])
        self.assertEqual(binding["content_hash"], saved["content_hash"])

    def test_transposed_canonical_character_name_is_rejected(self):
        from scripts.entity_registry import validate_entity_names

        events = [{"characters": ["季来之", "宋今今"], "key_quotes": []}]
        problems = validate_entity_names("宋今今闯进季之来的房间。", events, {})
        self.assertTrue(any("季之来" in p and "季来之" in p for p in problems))

    def test_save_events_rejects_transposed_name_before_commit(self):
        self._write_novel("第1章 回家\n季来之回到家中。")
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start = chapter.index("季来之")
        event = self._event(
            "CH001-E01",
            1,
            start,
            start + len("季来之回到家中。"),
            "季之来回到家中。",
            source_quote="季来之回到家中。",
            characters=["季来之"],
            trigger="季之来结束工作",
            actions=["季之来进门"],
            result="季之来到家",
        )
        path = self.root / "bad_events.json"
        path.write_text(json.dumps([event], ensure_ascii=False), encoding="utf-8")
        output = run_cli("save-events", "--dir", str(self.project), "--file", str(path), expect=1)
        self.assertIn("季之来", output)
        self.assertIsNone(active_artifact_path(self.project, "source_events"))

    def test_large_stage_bundle_uses_compact_event_catalog(self):
        from scripts.stage_lifecycle import compact_event_catalog

        events = [
            {
                "event_id": f"CH{i:03d}-E01",
                "chapter_id": i,
                "event": "主线事件" + ("很长的模型摘要" * 20),
                "actions": ["动作" * 100],
                "key_quotes": [{"speaker": "甲", "text": "台词" * 100}],
                "importance": "mainline",
                "minimum_screen_seconds": 20,
                "preferred_screen_seconds": 35,
            }
            for i in range(1, 111)
        ]
        compact = compact_event_catalog(events)
        rendered = json.dumps(compact, ensure_ascii=False)
        full = json.dumps(events, ensure_ascii=False)
        self.assertLess(len(rendered), len(full) * 0.35)
        self.assertTrue(all("actions" not in x and "key_quotes" not in x for x in compact))

    def test_writer_and_reviewer_prompts_define_playable_action_lines(self):
        writer = (Path(__file__).parents[2] / "references/prompts/writer.md").read_text()
        reviewer = (Path(__file__).parents[2] / "references/prompts/reviewer.md").read_text()
        for token in ("具体", "可拍", "情绪", "衔接", "蒙太奇"):
            self.assertIn(token, writer)
        self.assertIn("动作行", reviewer)
        self.assertIn("情节提要", reviewer)

    def test_density_is_advisory_and_uses_event_seconds_not_event_count(self):
        from scripts.stage_lifecycle import episode_density_report

        events = {
            "CH001-E01": {"minimum_screen_seconds": 50, "preferred_screen_seconds": 80},
            "CH001-E02": {"minimum_screen_seconds": 50, "preferred_screen_seconds": 80},
        }
        report = episode_density_report(
            self._outline(
                source_event_ids=["CH001-E01", "CH001-E02"],
                suggested_seconds=[60, 90],
            ),
            events,
        )
        self.assertEqual(report["pressure"], "high")
        self.assertTrue(report["advisory_only"])
        self.assertNotIn("max_event_count", report)

    def test_stage_review_is_bound_and_required_before_downstream_generation(self):
        novel = "第1章 当前\n当前事件发生。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text()
        start = chapter.index("当前事件")
        self._save_events([
            self._event("CH001-E01", 1, start, start + 4, "当前事件", source_quote="当前事件")
        ])
        from scripts.stage_lifecycle import build_stage_context

        context = build_stage_context(self.project, "adaptation")
        artifact = self.root / "adaptation.md"
        artifact.write_text("# 改编指引\n保留当前事件。\n", encoding="utf-8")
        run_cli(
            "save-adaptation", "--dir", str(self.project), "--file", str(artifact),
            "--stage-context-hash", context["context_hash"],
        )
        version = active_version_id(self.project, "adaptation_strategy")
        record = artifact_version_record(self.project, "adaptation_strategy", None, version)
        self.assertEqual(record["status"], "needs_writer_confirmation")
        run_cli("generate-story-outline", "--dir", str(self.project), expect=1)

        review = {
            "stage": "adaptation",
            "stage_context_hash": context["context_hash"],
            "artifact_version": version,
            "artifact_hash": record["content_hash"],
            "verdict": "blocked",
            "summary": "没有阻塞问题",
            "issues": [],
        }
        review_path = self.root / "stage_review.json"
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        run_cli(
            "save-stage-review", "--dir", str(self.project), "--stage", "adaptation",
            "--file", str(review_path),
        )
        run_cli(
            "confirm-stage", "--dir", str(self.project), "--stage", "adaptation",
            "--version", str(version),
            "--operator", "round5-writer", "--confirmation-ref", "round5-message-stage-review",
        )
        self.assertEqual(
            artifact_version_record(self.project, "adaptation_strategy", None, version)["status"],
            "approved",
        )
        run_cli("generate-story-outline", "--dir", str(self.project))

    def test_stage_review_api_uses_bound_save_path(self):
        novel = "第1章 当前\n当前事件发生。"
        self._write_novel(novel)
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start = chapter.index("当前事件")
        self._save_events([
            self._event("CH001-E01", 1, start, start + 4, "当前事件", source_quote="当前事件")
        ])
        from scripts.stage_lifecycle import build_stage_context

        context = build_stage_context(self.project, "adaptation")
        artifact = self.root / "adaptation_api.md"
        artifact.write_text("# 改编指引\n保留当前事件。\n", encoding="utf-8")
        run_cli(
            "save-adaptation", "--dir", str(self.project), "--file", str(artifact),
            "--stage-context-hash", context["context_hash"],
        )
        version = active_version_id(self.project, "adaptation_strategy")
        record = artifact_version_record(self.project, "adaptation_strategy", None, version)
        model_report = {
            "stage": "adaptation",
            "stage_context_hash": context["context_hash"],
            "artifact_version": version,
            "artifact_hash": record["content_hash"],
            "verdict": "blocked",
            "summary": "没有有效问题",
            "issues": [],
        }
        with mock.patch(
            "scripts.model_adapter.call_generate",
            return_value=json.dumps(model_report, ensure_ascii=False),
        ):
            run_cli("review-stage", "--dir", str(self.project), "--stage", "adaptation", "--api")
        saved = json.loads(active_artifact_path(self.project, "stage_review_adaptation").read_text(encoding="utf-8"))
        self.assertEqual(saved["verdict"], "pass")

    def test_stage_review_evidence_accepts_whitespace_only_variation(self):
        from scripts.stage_lifecycle import build_stage_context

        context = build_stage_context(self.project, "adaptation")
        artifact = self.root / "adaptation_multiline.md"
        artifact.write_text("# 改编指引\n第一条事实。\n第二条事实。\n", encoding="utf-8")
        run_cli(
            "save-adaptation", "--dir", str(self.project), "--file", str(artifact),
            "--stage-context-hash", context["context_hash"],
        )
        version = active_version_id(self.project, "adaptation_strategy")
        record = artifact_version_record(self.project, "adaptation_strategy", None, version)
        review = {
            "stage": "adaptation",
            "stage_context_hash": context["context_hash"],
            "artifact_version": version,
            "artifact_hash": record["content_hash"],
            "verdict": "pass",
            "summary": "跨行证据",
            "issues": [{
                "id": "STAGE-001",
                "severity": "error",
                "category": "continuity",
                "problem": "两条事实顺序错误",
                "evidence": {"artifact_quote": "第一条事实。 第二条事实。"},
            }],
        }
        review_path = self.root / "stage_review_multiline.json"
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        run_cli(
            "save-stage-review", "--dir", str(self.project), "--stage", "adaptation",
            "--file", str(review_path),
        )
        saved = json.loads(active_artifact_path(self.project, "stage_review_adaptation").read_text(encoding="utf-8"))
        self.assertEqual(saved["verdict"], "blocked")

        review["issues"][0]["evidence"]["artifact_quote"] = "完全不存在的证据"
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        run_cli(
            "save-stage-review", "--dir", str(self.project), "--stage", "adaptation",
            "--file", str(review_path), expect=1,
        )

    def test_stage_save_rejects_missing_or_tampered_context_hash(self):
        artifact = self.root / "adaptation.md"
        artifact.write_text("# 改编指引\n", encoding="utf-8")
        output = run_cli(
            "save-adaptation", "--dir", str(self.project), "--file", str(artifact),
            expect=1,
        )
        self.assertIn("stage-context-hash", output)
        output = run_cli(
            "save-adaptation", "--dir", str(self.project), "--file", str(artifact),
            "--stage-context-hash", "0" * 64,
            expect=1,
        )
        self.assertIn("stage_context", output)

    def test_stage_context_cannot_omit_required_upstream_binding(self):
        from scripts.common import stable_hash
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        adaptation_context = build_stage_context(self.project, "adaptation")
        adaptation = save_stage_artifact(
            self.project,
            stage="adaptation",
            content="# 已确认改编指引\n",
            stage_context=adaptation_context,
        )
        confirm_stage(
            self.project,
            stage="adaptation",
            version=adaptation["version"],
            operator="writer",
            confirmation_ref="round5-message-context-binding",
            review_override_reason="synthetic fixture reviewed",
        )
        valid = build_stage_context(self.project, "story_outline", save=False)
        forged_body = {key: value for key, value in valid.items() if key != "context_hash"}
        forged_body["upstream_bindings"] = [
            item for item in forged_body["upstream_bindings"]
            if item.get("kind") != "adaptation_strategy"
        ]
        forged = {**forged_body, "context_hash": stable_hash(forged_body)}
        with self.assertRaises(ValueError):
            save_stage_artifact(
                self.project,
                stage="story_outline",
                content="# 伪造故事大纲\n",
                stage_context=forged,
            )


if __name__ == "__main__":
    unittest.main()
