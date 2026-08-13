"""Independent regressions for the production-facing v0.3.7 quality gates."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from scripts.batch_context import (
    confirm_provisional_batch,
    provisional_batch_context,
    record_provisional_draft,
    record_provisional_review,
    start_provisional_batch,
)
from scripts.capacity_plan import suggest_capacity_plans, validate_capacity_plan
from scripts.common import sha256_text
from scripts.review_quality import CORE_DIMENSIONS, derive_review_verdict, validate_review_completeness
from scripts.state_store import commit_artifact, init_project


class V037HiddenVariantRegressions(unittest.TestCase):
    @staticmethod
    def _dimensions(*, error: str | None = None) -> list[dict]:
        return [
            {
                "dimension": dimension,
                "status": "error" if dimension == error else "pass",
                "severity": "error" if dimension == error else "none",
                "draft_evidence": {"line_start": 1, "line_end": 1, "artifact_quote": "草稿行"}
                if dimension == error
                else None,
                "fix": "修复该维度" if dimension == error else "",
            }
            for dimension in CORE_DIMENSIONS
        ]

    def test_empty_issues_cannot_hide_beat_or_dimension_error(self):
        context = {
            "episode_outline": {
                "required_story_beats": [{"id": "B01", "text": "必须演出"}],
            }
        }
        report = {
            "review_contract_version": "0.3.7",
            "issues": [],
            "beat_checks": [
                {
                    "beat_id": "B01",
                    "status": "missing",
                    "causality_complete": False,
                    "dialogue_chain_complete": False,
                    "visible_reaction_present": False,
                    "required_visuals_present": False,
                    "draft_evidence": None,
                    "severity": "error",
                    "fix": "补齐核心 beat",
                }
            ],
            "dimension_checks": self._dimensions(error="continuity"),
            "required_quote_checks": [],
            "risk_signal_checks": [],
        }
        self.assertEqual(validate_review_completeness(report, context, "草稿行\n"), [])
        self.assertEqual(derive_review_verdict(report, context, "草稿行\n"), "blocked")

    def test_semantic_quote_has_per_quote_blocking_exit(self):
        context = {
            "episode_outline": {
                "required_quotes": [
                    {"id": "Q01", "quote": "原文语义", "mode": "semantic", "source_event_id": "E1"}
                ]
            }
        }
        report = {
            "review_contract_version": "0.3.7",
            "issues": [],
            "beat_checks": [],
            "dimension_checks": self._dimensions(),
            "required_quote_checks": [
                {
                    "quote_id": "Q01",
                    "quote": "原文语义",
                    "mode": "semantic",
                    "status": "semantic_mismatch",
                    "severity": "error",
                    "draft_evidence": {"line_start": 1, "line_end": 1, "artifact_quote": "草稿行"},
                    "assessment": "草稿没有保留原意",
                    "fix": "恢复语义",
                }
            ],
            "risk_signal_checks": [],
        }
        self.assertEqual(validate_review_completeness(report, context, "草稿行\n"), [])
        self.assertEqual(derive_review_verdict(report, context, "草稿行\n"), "blocked")
        missing_quote_report = copy.deepcopy(report)
        missing_quote_report["required_quote_checks"] = []
        self.assertTrue(validate_review_completeness(missing_quote_report, context, "草稿行\n"))

    def _capacity_project(self) -> Path:
        raw = tempfile.mkdtemp()
        project = Path(raw) / "project"
        init_project(project, {"project_id": "capacity-hidden", "initial_episode_count": 2})
        commit_artifact(
            project,
            "source_events",
            content=[
                {"event_id": "E1", "importance": "mainline", "preferred_screen_seconds": 80},
                {"event_id": "E2", "importance": "subline", "preferred_screen_seconds": 80},
            ],
            status="approved",
            source="test",
        )
        commit_artifact(
            project,
            "capacity_forecast",
            content={
                "requested": {"episodes": 2, "preferred_episode_seconds": [60, 90]},
                "scenario_metrics": {
                    "mainline_episode_range_at_preferred_length": [1, 1],
                    "full_episode_range_at_preferred_length": [2, 2],
                },
                "pressure": "high",
                "advisory_only": True,
            },
            status="approved",
            source="test",
        )
        commit_artifact(project, "episode_outline", content={"episodes": [{"episode": 1}]}, status="approved", source="test")
        return project

    def test_capacity_plan_rejects_empty_incomplete_and_unknown_event_assignment(self):
        project = self._capacity_project()
        proposal = suggest_capacity_plans(project)
        base = proposal["options"][0]
        empty = copy.deepcopy(base)
        empty["event_partition"] = {}
        empty["kept_event_ids"] = []
        empty["compressible_event_ids"] = []
        empty["compressed_event_ids"] = []
        empty["deferred_event_ids"] = []
        empty["omitted_event_ids"] = []
        self.assertTrue(validate_capacity_plan(empty, project))

        duplicate = copy.deepcopy(base)
        duplicate["event_partition"]["EP001"].append("E1")
        duplicate["kept_event_ids"].append("E1")
        self.assertTrue(any("重复" in error for error in validate_capacity_plan(duplicate, project)))

        unknown = copy.deepcopy(base)
        unknown.setdefault("deferred_event_ids", []).append("UNKNOWN")
        self.assertTrue(any("不存在" in error for error in validate_capacity_plan(unknown, project)))

    @staticmethod
    def _record_artifact(project: Path, kind: str, episode: int, text: str, *, draft_hash: str | None = None) -> dict:
        content = text if kind == "script_draft" else {"verdict": "pass", "draft_hash": draft_hash}
        return commit_artifact(project, kind, content=content, episode=episode, source="test", status="approved")

    def test_stale_previous_episode_blocks_confirmation_and_explains_rebuild(self):
        project = Path(tempfile.mkdtemp()) / "project"
        init_project(project, {"project_id": "batch-hidden"})
        batch = start_provisional_batch(project, start_episode=4, size=3)
        d4 = self._record_artifact(project, "script_draft", 4, "EP4 old")
        d5 = self._record_artifact(project, "script_draft", 5, "EP5")
        record_provisional_draft(project, episode=4, draft_version=d4["version"], draft_hash=d4["content_hash"], draft_text="EP4 old", context_hash="c" * 64)
        record_provisional_draft(project, episode=5, draft_version=d5["version"], draft_hash=d5["content_hash"], draft_text="EP5", context_hash="d" * 64)
        r4 = self._record_artifact(project, "review", 4, "", draft_hash=d4["content_hash"])
        r5 = self._record_artifact(project, "review", 5, "", draft_hash=d5["content_hash"])
        record_provisional_review(project, episode=4, review_version=r4["version"], review_hash=r4["content_hash"], verdict="pass")
        record_provisional_review(project, episode=5, review_version=r5["version"], review_hash=r5["content_hash"], verdict="pass")

        d4_new = self._record_artifact(project, "script_draft", 4, "EP4 revised")
        record_provisional_draft(project, episode=4, draft_version=d4_new["version"], draft_hash=d4_new["content_hash"], draft_text="EP4 revised", context_hash="e" * 64)
        context = provisional_batch_context(project, 6)
        self.assertTrue(context["rebuild_required"])
        self.assertIn(5, {item["episode"] for item in context["invalidated_previous_episodes"]})
        self.assertIn("重新生成并审核", context["rebuild_instruction"])
        with self.assertRaisesRegex(ValueError, "stale|重建"):
            confirm_provisional_batch(project, batch_id=batch["batch_id"], operator="writer", confirmation_ref="natural-language-confirmation")


if __name__ == "__main__":
    unittest.main()
