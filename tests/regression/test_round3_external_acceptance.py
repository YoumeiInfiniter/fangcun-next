"""Round-3 external acceptance cases (fix-brief §14, groups A–J).

These cases are provided by the independent reviewer. They must not be
weakened or inverted. All projects are random temporary directories.
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_cli import main
from scripts.state_store import (
    active_artifact_path,
    active_version_id,
    artifact_version_path,
    draft_meta_record,
    load_manifest,
)
from tests.regression.test_round1_bypass import Round1BypassBase, _run


class Round3ActiveArtifactTests(Round1BypassBase):
    """Group A: single trusted active-artifact resolver."""

    def _approved(self, text: str) -> dict:
        from scripts.continuity_manager import apply_approved_script

        return apply_approved_script(self.project_dir, 1, text)

    def test_a1_external_index_path_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        outside = self.root / "outside.txt"
        outside.write_text("外部内容", encoding="utf-8")
        index_path = self.project_dir / "state" / "active_versions.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["approved_script:1"]["path"] = str(outside)
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        from scripts.state_store import ArtifactStateError, resolve_active

        with self.assertRaises(ArtifactStateError):
            resolve_active(self.project_dir, "approved_script", 1)

    def test_a2_cross_combination_index_manifest_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        index_path = self.project_dir / "state" / "active_versions.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["approved_script:1"]["version"] = "v999"
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        from scripts.state_store import ArtifactStateError, resolve_active

        with self.assertRaises(ArtifactStateError):
            resolve_active(self.project_dir, "approved_script", 1)

    def test_a3_tampered_active_content_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        active = active_artifact_path(self.project_dir, "approved_script", 1)
        active.write_text(active.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
        from scripts.state_store import ArtifactStateError, resolve_active

        with self.assertRaises(ArtifactStateError):
            resolve_active(self.project_dir, "approved_script", 1)

    def test_a4_dotdot_absolute_and_symlink_escape_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        outside = self.root / "outside.txt"
        outside.write_text("外部内容", encoding="utf-8")
        symlink = self.project_dir / "state" / "escaped_link.txt"
        symlink.symlink_to(outside)
        from scripts.state_store import ArtifactStateError, _validated_version_path

        for raw_path in ("../outside.txt", str(outside), "state/escaped_link.txt"):
            with self.subTest(path=raw_path):
                record = {"path": raw_path, "content_hash": result["content_hash"]}
                with self.assertRaises(ArtifactStateError):
                    _validated_version_path(self.project_dir, record)


class Round3RewriteProvenanceTests(Round1BypassBase):
    """Group B: rewrite provenance cannot be bypassed."""

    def _reviewed_draft(self) -> dict:
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        self._save_review(1, self._review_report(1))
        from scripts.state_store import draft_meta_record

        return {"meta": draft_meta_record(self.project_dir, 1, active_version_id(self.project_dir, "script_draft", 1))}

    def test_b1_repeated_rewrite_issues_single_ticket(self):
        binding = self._reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import _ticket_path, read_jsonl

        records = read_jsonl(_ticket_path(self.project_dir))
        issued = [r for r in records if r.get("status") == "issued"]
        self.assertEqual(len(issued), 1)
        self.assertEqual(len(records), 1)

    def test_b2_omitting_ticket_after_issue_rejected(self):
        binding = self._reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        path = self.root / "draft_no_ticket.txt"
        path.write_text(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：新台词。\n",
            encoding="utf-8",
        )
        _run(
            "save-draft",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--file", str(path),
            "--context-hash", binding["meta"]["context_hash"],
            expect=1,
        )

    def test_b3_cancel_then_manual_save_audited(self):
        binding = self._reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        _run("cancel-rewrite-ticket", "--dir", str(self.project_dir), "--ticket-id", ticket["ticket_id"], "--reason", "writer decided manual")
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△人工动作。\n叶聆：什么动静？\n996：人工台词。\n",
            context_hash=binding["meta"]["context_hash"],
        )
        version = active_version_id(self.project_dir, "script_draft", 1)
        meta = draft_meta_record(self.project_dir, 1, version)
        self.assertEqual(meta["origin"], "manual")
        from scripts.rewrite_ticket import ticket_state

        self.assertEqual(ticket_state(self.project_dir, ticket["ticket_id"])["status"], "cancelled")

    def test_b4_consumed_ticket_second_consumption_rejected(self):
        binding = self._reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n",
            context_hash=binding["meta"]["context_hash"],
            rewrite_ticket=ticket["ticket_id"],
        )
        _run(
            "save-draft",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--file", str(self.root / "draft_ep1.txt"),
            "--rewrite-ticket", ticket["ticket_id"],
            expect=1,
        )

    def test_b5_auto_rewrite_without_manual_edit_cannot_rewrite_again(self):
        binding = self._reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n",
            context_hash=binding["meta"]["context_hash"],
            rewrite_ticket=ticket["ticket_id"],
        )
        v2 = active_version_id(self.project_dir, "script_draft", 1)
        meta2 = draft_meta_record(self.project_dir, 1, v2)
        report2 = {
            "episode": 1,
            "context_hash": meta2["context_hash"],
            "draft_hash": meta2["draft_hash"],
            "draft_version": v2,
            "verdict": "blocked",
            "summary": "继续",
            "issues": [
                {
                    "id": "B5",
                    "severity": "error",
                    "category": "causality",
                    "problem": "问题",
                    "evidence": {"evidence_type": "source", "quote": "什么动静？"},
                    "fix": "修复",
                }
            ],
        }
        self._save_review(1, report2)
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1", expect=1)

    def test_b6_pass_with_empty_issues_rewrite_rejected_no_ticket(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n")
        binding = {"meta": draft_meta_record(self.project_dir, 1, active_version_id(self.project_dir, "script_draft", 1))}
        report = {
            "episode": 1,
            "context_hash": binding["meta"]["context_hash"],
            "draft_hash": binding["meta"]["draft_hash"],
            "draft_version": active_version_id(self.project_dir, "script_draft", 1),
            "verdict": "pass",
            "summary": "通过",
            "issues": [],
        }
        path = self.root / "pass_review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path))
        from scripts.rewrite_ticket import _ticket_path, read_jsonl

        before = len(read_jsonl(_ticket_path(self.project_dir)))
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1", expect=1)
        self.assertEqual(len(read_jsonl(_ticket_path(self.project_dir))), before)


class Round3DeltaBindingTests(Round1BypassBase):
    """Group C: continuity delta fully bound to current approved script."""

    def _approved(self, text: str) -> dict:
        from scripts.continuity_manager import apply_approved_script

        return apply_approved_script(self.project_dir, 1, text)

    def _delta_file(self, facts: list[dict]) -> Path:
        delta = {"extraction_mode": "host_agent", "facts": facts}
        path = self.root / "delta.json"
        path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
        return path

    def _save_delta(self, facts: list[dict]) -> None:
        _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", "1", "--file", str(self._delta_file(facts)))

    def test_c1_forged_pointer_cannot_move_delta_to_other_approved(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result_a = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta(
            [{"fact_id": "F-A", "category": "event", "fact": "A独有事实", "evidence_location": "1-1", "status": "active"}]
        )
        result_b = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        # Forge B's pointer to point at A's delta file.
        from scripts.continuity_manager import _delta_dir, _delta_pointer_path
        from scripts.state_store import load_continuity

        pointer = json.loads(_delta_pointer_path(self.project_dir, 1, result_a["content_hash"]).read_text(encoding="utf-8"))
        forged = _delta_pointer_path(self.project_dir, 1, result_b["content_hash"])
        forged.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
        from scripts.continuity_manager import refresh_continuity

        refresh_continuity(self.project_dir)
        continuity = load_continuity(self.project_dir)
        self.assertNotIn("A独有事实", [f.get("fact") for f in continuity["facts"]])
        self.assertIn("1", continuity["degraded_episodes"])

    def test_c2_pointer_fields_mismatch_delta_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta([{"fact_id": "F-A", "category": "event", "fact": "A事实", "evidence_location": "1-1", "status": "active"}])
        from scripts.continuity_manager import _delta_pointer_path
        from scripts.state_store import load_continuity

        pointer_path = _delta_pointer_path(self.project_dir, 1, result["content_hash"])
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["approved_version"] = "v999"
        pointer_path.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
        from scripts.continuity_manager import refresh_continuity

        refresh_continuity(self.project_dir)
        continuity = load_continuity(self.project_dir)
        self.assertNotIn("A事实", [f.get("fact") for f in continuity["facts"]])

    def test_c3_delta_path_outside_dir_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta([{"fact_id": "F-A", "category": "event", "fact": "A事实", "evidence_location": "1-1", "status": "active"}])
        from scripts.continuity_manager import _delta_pointer_path
        from scripts.state_store import load_continuity

        pointer_path = _delta_pointer_path(self.project_dir, 1, result["content_hash"])
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["delta_path"] = "../escaped.json"
        pointer_path.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
        from scripts.continuity_manager import refresh_continuity

        refresh_continuity(self.project_dir)
        self.assertNotIn("A事实", [f.get("fact") for f in load_continuity(self.project_dir)["facts"]])

    def test_c4_short_hash_prefix_collision_distinguished_by_full_hash(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta([{"fact_id": "F-A", "category": "event", "fact": "真实事实", "evidence_location": "1-1", "status": "active"}])
        from scripts.continuity_manager import _delta_dir, _delta_pointer_path
        from scripts.state_store import load_continuity

        pointer = json.loads(_delta_pointer_path(self.project_dir, 1, result["content_hash"]).read_text(encoding="utf-8"))
        original = _delta_dir(self.project_dir) / pointer["delta_path"]
        forged = _delta_dir(self.project_dir) / f"delta_EP001_{result['content_hash'][:8]}_ffffffff.json"
        forged.write_text(json.dumps({"extraction_mode": "host_agent", "facts": [{"fact_id": "F-X", "category": "event", "fact": "伪造事实", "evidence_location": "1-1", "status": "active"}], "episode": 1, "draft_version": "v001", "script_hash": result["content_hash"]}, ensure_ascii=False), encoding="utf-8")
        pointer["delta_path"] = forged.name
        _delta_pointer_path(self.project_dir, 1, result["content_hash"]).write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
        from scripts.continuity_manager import refresh_continuity

        refresh_continuity(self.project_dir)
        facts = [f.get("fact") for f in load_continuity(self.project_dir)["facts"]]
        self.assertNotIn("伪造事实", facts)
        self.assertIn("1", load_continuity(self.project_dir)["degraded_episodes"])

    def test_c5_restoring_a_consumes_only_a_bound_delta(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result_a = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta([{"fact_id": "F-A", "category": "event", "fact": "A事实", "evidence_location": "1-1", "status": "active"}])
        result_b = self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v001", "--reason", "restore A")
        from scripts.state_store import load_continuity

        facts = [f.get("fact") for f in load_continuity(self.project_dir)["facts"]]
        self.assertIn("A事实", facts)
        self.assertNotIn("B", facts)


class Round3RichContinuityTests(Round1BypassBase):
    """Group D: rich continuity fields complete and idempotent."""

    def _approve_and_delta(self, script_text: str, delta: dict) -> dict:
        from scripts.continuity_manager import apply_approved_script

        result = apply_approved_script(self.project_dir, 1, script_text)
        path = self.root / "delta.json"
        path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
        _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path))
        return result

    def test_d1_character_states_only_delta_valid_and_merged(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_and_delta(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n",
            {"extraction_mode": "host_agent", "character_states": {"叶聆": {"mood": "摆烂"}}},
        )
        from scripts.state_store import load_continuity

        self.assertEqual(load_continuity(self.project_dir)["character_states"]["叶聆"]["mood"], "摆烂")

    def test_d2_relationship_props_locations_not_lost(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_and_delta(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n",
            {
                "extraction_mode": "host_agent",
                "relationship_states": {"叶聆_谢淮舟": "离婚倒计时"},
                "props": {"离婚协议": "桌上"},
                "locations": {"书房": "首见"},
            },
        )
        from scripts.state_store import load_continuity

        continuity = load_continuity(self.project_dir)
        self.assertEqual(continuity["relationship_states"]["叶聆_谢淮舟"], "离婚倒计时")
        self.assertEqual(continuity["props"]["离婚协议"], "桌上")
        self.assertEqual(continuity["locations"]["书房"], "首见")

    def test_d3_repeated_refresh_idempotent(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_and_delta(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n",
            {"extraction_mode": "host_agent", "character_states": {"叶聆": {"mood": "摆烂"}}},
        )
        from scripts.continuity_manager import refresh_continuity
        from scripts.state_store import load_continuity

        refresh_continuity(self.project_dir)
        second = load_continuity(self.project_dir)
        self.assertEqual(second["character_states"]["叶聆"]["mood"], "摆烂")
        self.assertEqual(len([1 for _ in second["character_states"]]), 1)

    def test_d4_switch_and_restore_rich_fields(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        result_a = self._approve_and_delta(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n",
            {"extraction_mode": "host_agent", "character_states": {"叶聆": {"mood": "A状态"}}},
        )
        result_b = self._approve_and_delta(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n",
            {"extraction_mode": "host_agent", "character_states": {"叶聆": {"mood": "B状态"}}},
        )
        from scripts.state_store import load_continuity

        self.assertEqual(load_continuity(self.project_dir)["character_states"]["叶聆"]["mood"], "B状态")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v001", "--reason", "restore A")
        self.assertEqual(load_continuity(self.project_dir)["character_states"]["叶聆"]["mood"], "A状态")


class Round3EvidenceSpanTests(Round1BypassBase):
    """Group E: review quote must actually lie inside the claimed span."""

    def _spanned_setup(self):
        self._init()
        self._novel("第一章 第一章\n系统登场。叶聆：什么动静？\n")
        self._events(
            [
                {
                    "event_id": "CH001-E01",
                    "chapter_id": 1,
                    "event": "系统登场",
                    "importance": "mainline",
                    "source_span": {"start": 0, "end": 20},
                    "key_quotes": [{"speaker": "叶聆", "text": "什么动静？"}],
                }
            ]
        )
        self._save_outlines([self._outline(1, extra_must_keep=["系统登场"])])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：什么动静？\n")
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        return context

    def _report_with_span(self, context: dict, quote: str, span: dict, expect: int = 1) -> None:
        version = active_version_id(self.project_dir, "script_draft", 1)
        meta = draft_meta_record(self.project_dir, 1, version)
        report = {
            "episode": 1,
            "context_hash": meta["context_hash"],
            "draft_hash": meta["draft_hash"],
            "draft_version": version,
            "verdict": "blocked",
            "summary": "证据",
            "issues": [
                {
                    "id": "E",
                    "severity": "error",
                    "category": "causality",
                    "problem": "问题",
                    "evidence": {"evidence_type": "source", "quote": quote, "source_span": span},
                    "fix": "修复",
                }
            ],
        }
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=expect)

    def test_e1_quote_at_excerpt_tail_span_at_head_rejected(self):
        context = self._spanned_setup()
        ex = context["source_evidence"]["raw_excerpts"][0]
        span = {"start": ex["source_span"]["start"], "end": ex["source_span"]["start"] + 5}
        self._report_with_span(context, "什么动静？", span, expect=1)

    def test_e2_quote_partially_inside_span_rejected(self):
        context = self._spanned_setup()
        ex = context["source_evidence"]["raw_excerpts"][0]
        quote_pos = ex["text"].find("什么动静？")
        ex_start = ex["source_span"]["start"]
        span = {
            "start": ex_start + quote_pos,
            "end": ex_start + quote_pos + 2,
        }
        self._report_with_span(context, "什么动静？", span, expect=1)

    def test_e3_correct_ids_but_quote_outside_span_rejected(self):
        context = self._spanned_setup()
        ex = context["source_evidence"]["raw_excerpts"][0]
        ex_start = ex["source_span"]["start"]
        span = {"start": ex_start, "end": ex_start + 5}
        self._report_with_span(context, "什么动静？", span, expect=1)

    def test_e4_quote_fully_inside_span_accepted(self):
        context = self._spanned_setup()
        ex = context["source_evidence"]["raw_excerpts"][0]
        quote_pos = ex["text"].find("什么动静？")
        ex_start = ex["source_span"]["start"]
        span = {
            "start": ex_start + quote_pos - 1,
            "end": ex_start + quote_pos + len("什么动静？"),
        }
        self._report_with_span(context, "什么动静？", span, expect=0)


class Round3PairingTests(Round1BypassBase):
    """Group F: setup/payoff both must exist."""

    def _anchor_outline(self, setup: str | None, payoff: str | None) -> dict:
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["dialogue_anchors"] = [{"setup": setup, "payoff": payoff, "source": "第1章"}]
        return outline

    def _save_rejected(self, outline: dict) -> str:
        path = self.root / "rejected-outline.json"
        path.write_text(json.dumps({"episodes": [outline]}, ensure_ascii=False), encoding="utf-8")
        return _run(
            "save-episode-outline", "--dir", str(self.project_dir),
            "--outline-json", str(path),
            "--manual-import", "--manual-reason", "negative test fixture",
            expect=1,
        )

    def test_f1_setup_only_not_satisfied(self):
        self._init()
        self._novel()
        self._events()
        output = self._save_rejected(self._anchor_outline("吃得苦中苦，你就能得到……", None))
        self.assertIn("Schema", output)

    def test_f2_payoff_only_not_satisfied(self):
        self._init()
        self._novel()
        self._events()
        # Explicit quote anchors are valid; this legacy shape claims to be a
        # pair and is therefore rejected instead of silently reclassified.
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["dialogue_anchors"] = [{
            "type": "pair", "setup": "", "payoff": "吃不完的苦", "source_event_id": "CH001-E01"
        }]
        output = self._save_rejected(outline)
        self.assertIn("Schema", output)

    def test_f3_both_present_span_covers_both(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._anchor_outline("吃得苦中苦，你就能得到……", "吃不完的苦")])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        pair = [ex for ex in context["source_evidence"]["raw_excerpts"] if ex["reason"].startswith("dialogue_anchor")]
        self.assertTrue(pair)
        self.assertIn("吃得苦中苦", pair[0]["text"])
        self.assertIn("吃不完的苦", pair[0]["text"])

    def test_f4_pair_across_chapters_not_satisfied(self):
        self._init()
        novel = (
            "第一章 第一章\n第一句。系统登场。叶聆：什么动静？\n"
            "第二章 第二章\n第二句。996：绑错惩罚对象了。\n"
        )
        self._novel(novel)
        self._events()
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["dialogue_anchors"] = [{"setup": "第一句。", "payoff": "第二句。", "source": "跨章"}]
        output = self._save_rejected(outline)
        self.assertIn("dialogue_anchor", output)


class Round3SourceSpanTests(Round1BypassBase):
    """Group G: source span coordinate contract."""

    def test_g1_reversed_span_rejected_at_save(self):
        self._init()
        self._novel()
        events = [{"event_id": "E1", "chapter_id": 1, "event": "事件", "source_span": {"start": 50, "end": 10}}]
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        _run("save-events", "--dir", str(self.project_dir), "--file", str(path), expect=1)

    def _save_events_expect_fail(self, span: dict) -> None:
        self._init()
        self._novel()
        events = [{"event_id": "E1", "chapter_id": 1, "event": "事件", "source_span": span}]
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        _run("save-events", "--dir", str(self.project_dir), "--file", str(path), expect=1)

    def test_g2_zero_length_span_rejected(self):
        self._save_events_expect_fail({"start": 10, "end": 10})

    def test_g3_end_beyond_chapter_marks_needs_reanchor(self):
        self._init()
        self._novel()
        events = [{"event_id": "E1", "chapter_id": 1, "event": "事件", "source_span": {"start": 10, "end": 99999}}]
        self._events(events)
        outline = self._outline(1, extra_must_keep=["目标正文内容"])
        outline["source_event_ids"] = ["E1"]
        path = self.root / "rejected-outline.json"
        path.write_text(json.dumps({"episodes": [outline]}, ensure_ascii=False), encoding="utf-8")
        output = _run(
            "save-episode-outline", "--dir", str(self.project_dir),
            "--outline-json", str(path),
            "--manual-import", "--manual-reason", "negative test fixture",
            expect=1,
        )
        self.assertTrue("must_keep" in output or "锚点" in output)

    def test_g4_long_title_excerpt_contains_target_body(self):
        self._init()
        long_title = "第一章 " + "很" * 200
        novel = long_title + "\n目标正文内容。系统登场。叶聆：什么动静？\n"
        self._novel(novel)
        chapter_text = (self.project_dir / "source" / "chapters" / "chapter_001.txt").read_text(encoding="utf-8")
        target = "目标正文内容"
        pos = chapter_text.find(target)
        events = [
            {
                "event_id": "E1",
                "chapter_id": 1,
                "event": "事件",
                "source_span": {"start": pos, "end": pos + len(target)},
            }
        ]
        self._events(events)
        outline = self._outline(1, extra_must_keep=["目标正文内容"])
        outline["source_event_ids"] = ["E1"]
        self._save_outlines([outline])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        excerpt = next(ex for ex in context["source_evidence"]["raw_excerpts"] if "E1" in ex["reason"])
        self.assertIn("目标正文内容", excerpt["text"])

    def test_g5_leading_whitespace_and_newlines_coordinates_stable(self):
        self._init()
        novel = "第一章 第一章\n\n\n　　缩进正文。系统登场。叶聆：什么动静？\n"
        self._novel(novel)
        chapter_text = (self.project_dir / "source" / "chapters" / "chapter_001.txt").read_text(encoding="utf-8")
        target = "系统登场"
        pos = chapter_text.find(target)
        events = [
            {
                "event_id": "E1",
                "chapter_id": 1,
                "event": "事件",
                "source_span": {"start": pos, "end": pos + len(target)},
            }
        ]
        self._events(events)
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["source_event_ids"] = ["E1"]
        self._save_outlines([outline])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        excerpt = next(ex for ex in context["source_evidence"]["raw_excerpts"] if "E1" in ex["reason"])
        self.assertIn("系统登场", excerpt["text"])


class Round3AppliedRevisionTests(Round1BypassBase):
    """Group H: revision applied must bind a truly new version."""

    def _approved(self, text: str) -> dict:
        from scripts.continuity_manager import apply_approved_script

        return apply_approved_script(self.project_dir, 1, text)

    def _revision(self) -> str:
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "改台词",
            "--direct",
        )
        from scripts.revision_manager import list_revisions

        return list_revisions(self.project_dir, episode=1)[0]["revision_id"]

    def test_h1_resave_existing_approved_does_not_bind_revision(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n"
        self._approved(text)
        revision_id = self._revision()
        path = self.root / "a.txt"
        path.write_text(text, encoding="utf-8")
        out = _run("approve", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), "--apply-revision", revision_id)
        from scripts.revision_manager import list_revisions

        self.assertEqual(list_revisions(self.project_dir, episode=1)[0]["status"], "approved")
        self.assertIn("不绑定 applied", out)

    def test_h2_new_version_binds_explicit_revision(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        revision_id = self._revision()
        new_text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n"
        path = self.root / "b.txt"
        path.write_text(new_text, encoding="utf-8")
        _run("approve", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), "--apply-revision", revision_id)
        from scripts.revision_manager import list_revisions

        state = list_revisions(self.project_dir, episode=1)[0]
        self.assertEqual(state["status"], "applied")
        self.assertEqual(state["applied_to"]["version"], "v002")

    def test_h3_retry_does_not_duplicate_applied(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        revision_id = self._revision()
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n"
        path = self.root / "b.txt"
        path.write_text(text, encoding="utf-8")
        _run("approve", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), "--apply-revision", revision_id)
        _run("approve", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), "--apply-revision", revision_id)
        from scripts.revision_manager import list_revisions

        states = [r for r in list_revisions(self.project_dir, episode=1) if r["revision_id"] == revision_id]
        self.assertEqual(states[-1]["status"], "applied")
        self.assertEqual(len([s for s in states if s["status"] == "applied"]), 1)

    def test_h4_other_episode_revision_not_bound(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._approved("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "2",
            "--instruction", "EP2意见",
            "--direct",
        )
        from scripts.revision_manager import list_revisions

        other_id = list_revisions(self.project_dir, episode=2)[0]["revision_id"]
        new_text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n"
        path = self.root / "b.txt"
        path.write_text(new_text, encoding="utf-8")
        _run("approve", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), "--apply-revision", other_id)
        self.assertEqual(list_revisions(self.project_dir, episode=2)[0]["status"], "approved")


class Round3OverrideProjectionTests(Round1BypassBase):
    """Group I: writer override projection from revision log."""

    def test_i1_approved_then_rejected_disappears_from_continuity_and_context(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "下一集沿用新规则",
            "--affects-future",
            "--direct",
        )
        from scripts.revision_manager import list_revisions

        revision_id = list_revisions(self.project_dir, episode=1)[0]["revision_id"]
        _run("approve-revision", "--dir", str(self.project_dir), "--revision-id", revision_id)
        _run("refresh-continuity", "--dir", str(self.project_dir))
        from scripts.state_store import load_continuity

        self.assertIn("下一集沿用新规则", [o["instruction"] for o in load_continuity(self.project_dir)["writer_overrides"]])
        _run("reject-revision", "--dir", str(self.project_dir), "--revision-id", revision_id)
        _run("refresh-continuity", "--dir", str(self.project_dir))
        self.assertNotIn("下一集沿用新规则", [o["instruction"] for o in load_continuity(self.project_dir)["writer_overrides"]])
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        self.assertNotIn("下一集沿用新规则", [o.get("instruction") for o in context["writer_overrides"]])

    def test_i2_only_latest_projection_survives(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "未来规则",
            "--affects-future",
            "--direct",
        )
        from scripts.revision_manager import list_revisions

        revision_id = list_revisions(self.project_dir, episode=1)[0]["revision_id"]
        for action in ("approve-revision", "reject-revision", "approve-revision"):
            _run(action, "--dir", str(self.project_dir), "--revision-id", revision_id)
        states = [r["status"] for r in list_revisions(self.project_dir, episode=1) if r["revision_id"] == revision_id]
        self.assertEqual(states[-1], "approved")
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        self.assertIn("未来规则", [o.get("instruction") for o in context["writer_overrides"]])


class Round3LifecycleTests(Round1BypassBase):
    """Group J: full lifecycle and tamper blocking."""

    def test_j1_full_lifecycle_runs(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._context(1)
        v1 = self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        self._save_review(1, self._review_report(1))
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        meta = draft_meta_record(self.project_dir, 1, v1)
        v2 = self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n",
            context_hash=meta["context_hash"],
            rewrite_ticket=ticket["ticket_id"],
        )
        meta2 = draft_meta_record(self.project_dir, 1, v2)
        report2 = {
            "episode": 1,
            "context_hash": meta2["context_hash"],
            "draft_hash": meta2["draft_hash"],
            "draft_version": v2,
            "verdict": "warning",
            "summary": "复审",
            "issues": [
                {
                    "id": "J1",
                    "severity": "warning",
                    "category": "timing",
                    "problem": "时长略超",
                    "fix": "可接受",
                }
            ],
        }
        self._save_review(1, report2)
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, 1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△定稿动作。\n叶聆：什么动静？\n996：定稿台词。\n")
        delta = {
            "extraction_mode": "host_agent",
            "facts": [{"fact_id": "J-F", "category": "event", "fact": "定稿事实", "evidence_location": "1-1", "status": "active"}],
        }
        path = self.root / "delta.json"
        path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
        _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path))
        _run("refresh-continuity", "--dir", str(self.project_dir))
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        self.assertIn("定稿事实", [f.get("fact") for f in context["continuity_state"]["facts"]])

    def test_j2_tampering_each_artifact_blocks_its_consumer(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        self._save_review(1, self._review_report(1))
        # Tamper review → rewrite must block.
        review_path = active_artifact_path(self.project_dir, "review", 1)
        original_review = review_path.read_text(encoding="utf-8")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["summary"] = "篡改"
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1", expect=1)
        # Restore review, tamper draft → review must block.
        review_path.write_text(original_review, encoding="utf-8")
        draft_path = active_artifact_path(self.project_dir, "script_draft", 1)
        draft_path.write_text(draft_path.read_text(encoding="utf-8") + "tamper", encoding="utf-8")
        _run("review", "--dir", str(self.project_dir), "--episode", "1", expect=1)


if __name__ == "__main__":
    unittest.main()
