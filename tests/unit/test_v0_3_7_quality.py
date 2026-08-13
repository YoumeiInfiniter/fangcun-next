"""Focused deterministic tests for the v0.3.7 quality contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.batch_context import (
    record_provisional_draft,
    start_provisional_batch,
    provisional_batch_context,
)
from scripts.capacity_plan import save_capacity_plan, suggest_capacity_plans, validate_capacity_plan
from scripts.common import sha256_text
from scripts.draft_quality import compute_draft_quality
from scripts.execution_brief import build_episode_execution_brief, verify_execution_brief
from scripts.review_quality import CORE_DIMENSIONS, validate_review_completeness
from scripts.state_store import commit_artifact, init_project, resolve_active


class V037QualityTests(unittest.TestCase):
    def _context(self, *, core: bool = False) -> dict:
        outline = {
            "episode": 1,
            "title": "测试",
            "opening_bridge": "进入现场",
            "episode_goal": "完成目标",
            "ending_hook": "留下问题",
            "must_keep": ["一个合法的保留项"],
            "causal_chains": [["触发", "结果"]],
            "knowledge_at_start": {},
            "knowledge_at_end": {},
        }
        if core:
            outline["required_story_beats"] = [
                {
                    "id": "EP001-B01",
                    "text": "触发与回应",
                    "event_ids": ["E1"],
                    "priority": "core",
                    "required_visual_beats": ["人物看见结果"],
                }
            ]
            outline["required_quotes"] = [
                {"quote": "必须原句。", "source_event_id": "E1", "mode": "exact"}
            ]
        context = {
            "episode": 1,
            "context_hash": "c" * 64,
            "episode_outline": outline,
            "episode_execution_brief": build_episode_execution_brief(
                outline,
                {"events": [{"event_id": "E1"}]},
                {},
                None,
                None,
            ),
        }
        return context

    def test_execution_brief_removes_internal_labels_and_binds_hash(self):
        outline = self._context(core=True)["episode_outline"]
        outline["required_story_beats"][0]["text"] = "拦路审判：触发与回应"
        brief = build_episode_execution_brief(outline, {"events": []}, {}, None, None)
        rendered = str(brief)
        self.assertNotIn("EP001-B01", rendered)
        self.assertNotIn("拦路审判", rendered)
        self.assertTrue(verify_execution_brief(brief))

    def test_draft_quality_exact_quote_and_label_are_hard_gates(self):
        context = self._context(core=True)
        text = "第1集：测试\n\n1-1 室内 夜 内\n人物：甲\n\n△拦路审判：触发。\n甲：没有原句。\n"
        quality = compute_draft_quality(
            text,
            context,
            draft_version="v001",
            draft_hash=sha256_text(text),
            config={},
        )
        codes = {item["code"] for item in quality["hard_errors"]}
        self.assertIn("exact_quote_missing", codes)
        self.assertIn("planning_label_leakage", codes)

    def test_risk_signals_are_not_universal_hard_thresholds(self):
        context = self._context()
        text = "第1集：测试\n\n1-1 室内 夜 内\n人物：甲\n\n甲（OS）：？\n"
        quality = compute_draft_quality(
            text,
            context,
            draft_version="v001",
            draft_hash=sha256_text(text),
            config={},
        )
        self.assertFalse(quality["hard_errors"])
        self.assertTrue(quality["risk_signals"])

    def test_review_completeness_requires_every_core_beat_dimension_and_signal(self):
        context = self._context(core=True)
        draft = "第1集：测试\n\n1-1 室内 夜 内\n人物：甲\n\n△触发。\n甲：必须原句。\n"
        quality = {"risk_signals": [{"risk_id": "os_ratio"}]}
        report = {
            "beat_checks": [
                {
                    "beat_id": "EP001-B01",
                    "status": "dramatized",
                    "causality_complete": True,
                    "dialogue_chain_complete": True,
                    "visible_reaction_present": True,
                    "required_visuals_present": True,
                    "draft_evidence": {"line_start": 6, "line_end": 7, "artifact_quote": "触发"},
                    "severity": "none",
                    "fix": "",
                }
            ],
            "dimension_checks": [
                {"dimension": dimension, "status": "pass", "severity": "none"}
                for dimension in CORE_DIMENSIONS
            ],
            "risk_signal_checks": [
                {"risk_id": "os_ratio", "status": "confirmed", "assessment": "保留为合法表现"}
            ],
            "required_quote_checks": [
                {
                    "quote_id": "required-quote-001",
                    "quote": "必须原句。",
                    "mode": "exact",
                    "status": "exact_match",
                    "severity": "none",
                    "draft_evidence": {"line_start": 7, "line_end": 7, "artifact_quote": "必须原句。"},
                    "fix": "",
                }
            ],
        }
        self.assertEqual(validate_review_completeness(report, context, draft, quality), [])

    def test_capacity_plan_is_bound_to_forecast_and_outline(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            init_project(
                project,
                {
                    "project_id": "plan-test",
                    "novel_name": "n",
                    "drama_name": "d",
                    "platform": "p",
                    "aspect_ratio": "9:16",
                    "genre": ["悬疑"],
                    "initial_episode_count": 2,
                    "preferred_episode_seconds": [85, 95],
                },
            )
            commit_artifact(project, "source_events", content=[
                {"event_id": "E1", "importance": "mainline", "minimum_screen_seconds": 80, "preferred_screen_seconds": 90},
                {"event_id": "E2", "importance": "subline", "minimum_screen_seconds": 80, "preferred_screen_seconds": 90},
            ], status="approved", source="test")
            commit_artifact(project, "capacity_forecast", content={
                "requested": {"episodes": 2, "preferred_episode_seconds": [85, 95]},
                "forecast": {"mainline_minimum_seconds": [80, 90], "full_adaptation_seconds": [150, 180]},
                "pressure": "high", "options": ["a"], "advisory_only": True,
            }, status="approved", source="test")
            commit_artifact(project, "episode_outline", content={"episodes": [{"episode": 1}]}, status="approved", source="test")
            proposal = suggest_capacity_plans(project)
            self.assertGreaterEqual(len(proposal["options"]), 3)
            option_ids = {item["option_id"] for item in proposal["options"]}
            self.assertIn("accept_duration_overflow", option_ids)
            self.assertIn("explicit_mainline_reduction", option_ids)
            selected = dict(proposal["options"][0])
            result = save_capacity_plan(
                project,
                selected,
                operator="writer",
                confirmation_ref="message-1",
            )
            self.assertEqual(result["version"], "v001")
            active = resolve_active(project, "capacity_plan")
            self.assertEqual(active["record"]["status"], "approved")

    def test_capacity_plan_full_accept_overflow_and_legacy_modes(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            init_project(
                project,
                {
                    "project_id": "full-plan-test",
                    "initial_episode_count": 2,
                    "preferred_episode_seconds": [85, 95],
                },
            )
            commit_artifact(
                project,
                "source_events",
                content=[
                    {"event_id": "E1", "importance": "mainline", "preferred_screen_seconds": 90},
                    {"event_id": "E2", "importance": "subline", "preferred_screen_seconds": 90},
                ],
                status="approved",
                source="test",
            )
            commit_artifact(
                project,
                "capacity_forecast",
                content={
                    "requested": {"episodes": 2, "preferred_episode_seconds": [85, 95]},
                    "forecast": {"full_adaptation_seconds": [160, 180]},
                    "pressure": "high",
                    "advisory_only": True,
                },
                status="approved",
                source="test",
            )
            commit_artifact(
                project,
                "episode_outline",
                content={"episodes": [{"episode": 1}]},
                status="approved",
                source="test",
            )
            proposal = suggest_capacity_plans(project)
            options = {item["option_id"]: item for item in proposal["options"]}

            def bound(option):
                result = dict(option)
                result.update(
                    {
                        "plan_schema_version": "0.3.7",
                        "forecast_version": proposal["forecast_version"],
                        "forecast_hash": proposal["forecast_hash"],
                        "status": "approved",
                    }
                )
                return result

            full = bound(options["accept_duration_overflow"])
            self.assertEqual(validate_capacity_plan(full, project), [])
            saved = save_capacity_plan(project, full, operator="writer", confirmation_ref="full-plan")
            self.assertEqual(saved["version"], "v001")

            omitted = dict(full)
            omitted["omitted_event_ids"] = ["E1"]
            errors = validate_capacity_plan(omitted, project)
            self.assertIn("coverage_mode=full 不能省略事件", errors)

            for option_id in ("quality_first_mainline", "fixed_count_explicit_overflow"):
                self.assertEqual(validate_capacity_plan(bound(options[option_id]), project), [])

    def test_provisional_context_invalidates_later_records_when_prior_draft_changes(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            init_project(project, {"project_id": "batch-test"})
            start_provisional_batch(project, start_episode=1)
            record_provisional_draft(project, episode=1, draft_version="v001", draft_hash="a" * 64, draft_text="△a", context_hash="c" * 64)
            record_provisional_draft(project, episode=2, draft_version="v001", draft_hash="b" * 64, draft_text="△b", context_hash="d" * 64)
            record_provisional_draft(project, episode=1, draft_version="v002", draft_hash="e" * 64, draft_text="△e", context_hash="f" * 64)
            context = provisional_batch_context(project, 3)
            self.assertTrue(context["invalidated_previous_episodes"])
            self.assertTrue(context["unconfirmed"])


if __name__ == "__main__":
    unittest.main()
