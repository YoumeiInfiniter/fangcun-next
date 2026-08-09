"""Round-4 external acceptance tests derived before implementation changes.

These cases exercise invariants that Round 3's public tests did not cover.
They intentionally use temporary projects and dynamic paths/content.
"""

from __future__ import annotations

import json
import shutil
import uuid

from scripts.common import atomic_write_json, read_json, sha256_text
from scripts.continuity_manager import (
    _delta_pointer_path,
    _load_delta,
    apply_approved_script,
    refresh_continuity,
    save_continuity_delta,
)
from scripts.project_cli import _validate_issue_evidence
from scripts.source_retriever import _build_coverage, retrieve_source_evidence
from scripts.state_store import (
    ArtifactStateError,
    activate_version,
    load_continuity,
    load_manifest,
    init_project,
    read_artifact_version,
    save_manifest,
)
from tests.regression.test_round1_bypass import Round1BypassBase, _run


SCRIPT = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：什么动静？\n"


class Round4ArtifactResolverTests(Round1BypassBase):
    def test_r4_01_historical_read_and_activation_reject_external_path(self):
        self._full_ep1_setup()
        manifest = load_manifest(self.project_dir)
        record = manifest["artifacts"]["script_draft:1"]["versions"][0]
        outside = self.root / f"outside-{uuid.uuid4().hex}.txt"
        outside.write_text("EXTERNAL-SECRET", encoding="utf-8")
        record["path"] = str(outside)
        record["content_hash"] = sha256_text("EXTERNAL-SECRET")
        save_manifest(self.project_dir, manifest)

        with self.assertRaises(ArtifactStateError):
            read_artifact_version(self.project_dir, "script_draft", 1, record["version"])
        with self.assertRaises(ArtifactStateError):
            activate_version(self.project_dir, "script_draft", record["version"], episode=1)


class Round4ContinuityBindingTests(Round1BypassBase):
    def test_r4_02_same_content_new_logical_version_rejects_stale_delta(self):
        self._init()
        first = apply_approved_script(self.project_dir, 1, SCRIPT, source="writer-A")
        save_continuity_delta(
            self.project_dir,
            episode=1,
            delta={
                "extraction_mode": "host_agent",
                "facts": [
                    {
                        "fact_id": "F-A",
                        "category": "event",
                        "fact": "只属于A版本",
                        "evidence_location": "1-1",
                    }
                ],
            },
            script_hash=first["content_hash"],
            draft_version=first["version"],
        )
        second = apply_approved_script(self.project_dir, 1, SCRIPT, source="writer-B")
        self.assertNotEqual(first["version"], second["version"])
        self.assertEqual(first["content_hash"], second["content_hash"])

        continuity = refresh_continuity(self.project_dir)
        self.assertNotIn("只属于A版本", [f.get("fact") for f in continuity["facts"]])
        self.assertIn("1", continuity["degraded_episodes"])

    def test_r4_03_pointer_episode_and_script_hash_are_verified(self):
        self._init()
        approved = apply_approved_script(self.project_dir, 1, SCRIPT)
        save_continuity_delta(
            self.project_dir,
            episode=1,
            delta={
                "extraction_mode": "host_agent",
                "facts": [
                    {
                        "fact_id": "F-P",
                        "category": "event",
                        "fact": "篡改pointer后不得进入",
                        "evidence_location": "1-1",
                    }
                ],
            },
            script_hash=approved["content_hash"],
            draft_version=approved["version"],
        )
        pointer_path = _delta_pointer_path(self.project_dir, 1, approved["content_hash"])
        pointer = read_json(pointer_path)
        pointer["episode"] = 999
        pointer["script_hash"] = "0" * 64
        atomic_write_json(pointer_path, pointer)

        continuity = refresh_continuity(self.project_dir)
        self.assertNotIn("篡改pointer后不得进入", [f.get("fact") for f in continuity["facts"]])
        self.assertIn("1", continuity["degraded_episodes"])

    def test_r4_04_same_short_prefix_uses_distinct_pointer_identity(self):
        self._init()
        hash_a = "deadbeef" + "a" * 56
        hash_b = "deadbeef" + "b" * 56
        save_continuity_delta(
            self.project_dir,
            episode=1,
            delta={
                "extraction_mode": "host_agent",
                "facts": [{"fact_id": "A", "category": "event", "fact": "A", "evidence_location": "1-1"}],
            },
            script_hash=hash_a,
            draft_version="v001",
        )
        save_continuity_delta(
            self.project_dir,
            episode=1,
            delta={
                "extraction_mode": "host_agent",
                "facts": [{"fact_id": "B", "category": "event", "fact": "B", "evidence_location": "1-1"}],
            },
            script_hash=hash_b,
            draft_version="v002",
        )

        self.assertNotEqual(
            _delta_pointer_path(self.project_dir, 1, hash_a),
            _delta_pointer_path(self.project_dir, 1, hash_b),
        )
        self.assertEqual(_load_delta(self.project_dir, 1, hash_a, "v001")["facts"][0]["fact"], "A")
        self.assertEqual(_load_delta(self.project_dir, 1, hash_b, "v002")["facts"][0]["fact"], "B")

    def test_r4_05_unsupported_delta_field_is_rejected(self):
        self._init()
        approved = apply_approved_script(self.project_dir, 1, SCRIPT)
        with self.assertRaises(ValueError):
            save_continuity_delta(
                self.project_dir,
                episode=1,
                delta={"extraction_mode": "host_agent", "unsupported_story_truth": {"x": 1}},
                script_hash=approved["content_hash"],
                draft_version=approved["version"],
            )

    def test_r4_06_copied_delta_cannot_cross_project_boundary(self):
        self._init()
        approved_a = apply_approved_script(self.project_dir, 1, SCRIPT)
        save_continuity_delta(
            self.project_dir,
            episode=1,
            delta={
                "extraction_mode": "host_agent",
                "facts": [
                    {
                        "fact_id": "CROSS-A",
                        "category": "event",
                        "fact": "A项目独有事实",
                        "evidence_location": "1-1",
                    }
                ],
            },
            script_hash=approved_a["content_hash"],
            draft_version=approved_a["version"],
        )
        project_b = self.root / "projects" / "other-project"
        init_project(project_b, {**self._config(), "project_id": "other-project"})
        apply_approved_script(project_b, 1, SCRIPT)
        source_dir = self.project_dir / "state" / "continuity_deltas"
        target_dir = project_b / "state" / "continuity_deltas"
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)

        continuity = refresh_continuity(project_b)
        self.assertNotIn("A项目独有事实", [f.get("fact") for f in continuity["facts"]])
        self.assertIn("1", continuity["degraded_episodes"])

    def test_r4_07_nested_unknown_fact_field_is_rejected(self):
        self._init()
        approved = apply_approved_script(self.project_dir, 1, SCRIPT)
        with self.assertRaises(ValueError):
            save_continuity_delta(
                self.project_dir,
                episode=1,
                delta={
                    "extraction_mode": "host_agent",
                    "facts": [
                        {
                            "fact_id": "F-X",
                            "category": "event",
                            "fact": "事实",
                            "evidence_location": "1-1",
                            "unsupported": "不得静默丢弃",
                        }
                    ],
                },
                script_hash=approved["content_hash"],
                draft_version=approved["version"],
            )

    def test_r4_08_notes_only_delta_is_projected_but_remains_degraded(self):
        self._init()
        approved = apply_approved_script(self.project_dir, 1, SCRIPT)
        save_continuity_delta(
            self.project_dir,
            episode=1,
            delta={"extraction_mode": "host_agent", "notes": ["后续保留沉默规则"]},
            script_hash=approved["content_hash"],
            draft_version=approved["version"],
        )
        continuity = refresh_continuity(self.project_dir)
        self.assertIn("EP1: 后续保留沉默规则", continuity["notes_for_future"])
        self.assertIn("1", continuity["degraded_episodes"])


class Round4SourceEvidenceTests(Round1BypassBase):
    def test_r4_09_event_key_quote_missing_payoff_is_not_satisfied(self):
        self._init()
        self._novel()
        chapter_path = self.project_dir / "source" / "chapters" / "chapter_001.txt"
        chapter_text = chapter_path.read_text(encoding="utf-8")
        start = chapter_text.index("系统登场。")
        events = [
            {
                "event_id": "PAIR-E1",
                "chapter_id": 1,
                "event": "系统登场",
                "importance": "mainline",
                "source_span": {"start": start, "end": start + len("系统登场。")},
                "key_quotes": [
                    {
                        "speaker": "叶聆",
                        "text": "系统登场。",
                        "must_preserve_pairing": True,
                        "setup": "系统登场。",
                        "payoff": "不存在的回收句",
                    }
                ],
            }
        ]
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["source_event_ids"] = ["PAIR-E1"]
        outline["source_chapters"] = [1]

        evidence = retrieve_source_evidence(self.project_dir, outline, events)
        event_item = next(c for c in evidence["coverage"] if c.get("anchor_id") == "PAIR-E1")
        self.assertFalse(event_item["included"])
        self.assertEqual(event_item["reason"], "missing_payoff")

    def test_r4_10_bound_must_keep_requires_its_own_event_excerpt(self):
        ledger = _build_coverage(
            outline={"must_keep": [{"text": "关键事实", "event_id": "E1"}]},
            anchor_ids=[],
            anchor_chapters=[],
            dep_ids=[],
            resolved_events=[],
            kept=[
                {
                    "chapter_id": 99,
                    "source_span": {"start": 0, "end": 100},
                    "text": "无关摘录",
                    "reason": "event:OTHER",
                }
            ],
            events_by_id={"E1": {"event_id": "E1", "chapter_id": 1, "source_span": {"start": 10, "end": 20}}},
            fallback_used=False,
            degraded_event_ids=set(),
            event_fail_reasons={},
            anchor_fail_reasons={},
        )
        self.assertFalse(ledger[0]["included"])

    def test_r4_11_free_text_adaptation_basis_cannot_authorize_must_keep(self):
        ledger = _build_coverage(
            outline={
                "must_keep": ["编剧新增高光"],
                "adaptation_basis": [{"id": "D1", "text": "编剧新增高光"}],
            },
            anchor_ids=[],
            anchor_chapters=[],
            dep_ids=[],
            resolved_events=[],
            kept=[],
            events_by_id={},
            fallback_used=False,
            degraded_event_ids=set(),
            event_fail_reasons={},
            anchor_fail_reasons={},
        )
        self.assertFalse(ledger[0]["included"])

    def test_r4_12_event_id_only_is_not_sufficient_error_evidence(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = read_json(current_context_path(self.project_dir, 1))
        errors = _validate_issue_evidence(
            {"severity": "error", "evidence": {"evidence_type": "source", "event_id": "CH001-E01"}},
            context,
        )
        self.assertTrue(errors)

    def test_r4_13_source_quote_must_match_chapter_file_span(self):
        self._init()
        self._novel()
        events = [
            {
                "event_id": "COORD-E1",
                "chapter_id": 1,
                "event": "系统登场",
                "coordinate_base": "chapter_file_content",
                "source_span": {"start": 0, "end": 5},
                "source_quote": "系统登场",
            }
        ]
        path = self.root / "wrong-coordinate-events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        _run("save-events", "--dir", str(self.project_dir), "--file", str(path), expect=1)


class Round4RewriteAuditTests(Round1BypassBase):
    def test_r4_14_empty_cancel_reason_rejected_and_ticket_stays_issued(self):
        self._full_ep1_setup()
        self._save_review(1, self._review_report(1))
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self.assertIsNotNone(ticket)
        _run(
            "cancel-rewrite-ticket",
            "--dir",
            str(self.project_dir),
            "--ticket-id",
            ticket["ticket_id"],
            expect=1,
        )
        draft = self.root / "plain-after-failed-cancel.txt"
        draft.write_text(SCRIPT, encoding="utf-8")
        _run(
            "save-draft",
            "--dir",
            str(self.project_dir),
            "--episode",
            "1",
            "--file",
            str(draft),
            expect=1,
        )

    def test_r4_15_ticket_lookup_cannot_hide_older_matching_context(self):
        self._init()
        from scripts.rewrite_ticket import issue_rewrite_ticket, latest_issued_ticket

        matching = issue_rewrite_ticket(
            self.project_dir,
            episode=1,
            context_hash="context-target",
            review_version="v001",
            review_hash="1" * 64,
            source_draft_version="v001",
            source_draft_hash="2" * 64,
        )
        issue_rewrite_ticket(
            self.project_dir,
            episode=1,
            context_hash="context-other",
            review_version="v002",
            review_hash="3" * 64,
            source_draft_version="v002",
            source_draft_hash="4" * 64,
        )
        found = latest_issued_ticket(self.project_dir, 1, context_hash="context-target")
        self.assertEqual(found["ticket_id"], matching["ticket_id"])


if __name__ == "__main__":
    import unittest

    unittest.main()
