"""Round-2 independent-review bypass tests (fix-brief §13, items 1–50).

Every test method name maps to one numbered scenario. Tests drive the real
CLI/modules in temporary projects and assert the deterministic guarantee,
not a helper copy.
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
    artifact_versions,
    draft_meta_record,
)
from tests.regression.test_round1_bypass import Round1BypassBase, _run


SPANNED_EVENTS = [
    {
        "event_id": "CH001-E01",
        "chapter_id": 1,
        "event": "系统登场",
        "importance": "mainline",
        "source_span": {"start": 10, "end": 40},
        "key_quotes": [
            {
                "speaker": "叶聆",
                "text": "什么动静？",
                "must_preserve_pairing": True,
                "pair_id": "P1",
                "setup": "系统登场。",
                "payoff": "什么动静？",
            }
        ],
    },
    {
        "event_id": "CH001-E02",
        "chapter_id": 1,
        "event": "雷击错绑",
        "importance": "mainline",
        "source_span": {"start": 60, "end": 89},
        "key_quotes": [
            {"speaker": "996", "text": "绑错惩罚对象了。", "must_preserve_pairing": True, "pair_id": "P2"}
        ],
    },
]


class Round2AuditTests(Round1BypassBase):
    """§13 items 1–10: review verdict, evidence relations, file integrity."""

    def _valid_report(self, verdict: str, severity: str) -> dict:
        report = self._review_report(1)
        report["verdict"] = verdict
        report["issues"] = [
            {
                "id": "R2",
                "severity": severity,
                "category": "causality",
                "problem": "问题",
                "evidence": {"evidence_type": "source", "quote": "什么动静？"},
                "fix": "修复",
            }
        ]
        return report

    def _save_report_expect(self, report: dict, expect: int = 0) -> str:
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=expect)

    def test_r2_01_verdict_pass_with_error_saved_as_blocked(self):
        self._full_ep1_setup()
        self._save_report_expect(self._valid_report("pass", "error"))
        saved = json.loads(active_artifact_path(self.project_dir, "review", 1).read_text(encoding="utf-8"))
        self.assertEqual(saved["verdict"], "blocked")
        self.assertEqual(saved["model_verdict"], "pass")

    def test_r2_02_verdict_pass_with_warning_saved_as_warning(self):
        self._full_ep1_setup()
        self._save_report_expect(self._valid_report("pass", "warning"))
        saved = json.loads(active_artifact_path(self.project_dir, "review", 1).read_text(encoding="utf-8"))
        self.assertEqual(saved["verdict"], "warning")

    def test_r2_03_reversed_span_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1)
        report["issues"][0]["evidence"] = {
            "evidence_type": "source",
            "quote": "什么动静？",
            "source_span": {"start": 50, "end": 10},
        }
        self._save_report_expect(report, expect=1)

    def test_r2_04_zero_length_span_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1)
        report["issues"][0]["evidence"] = {
            "evidence_type": "source",
            "quote": "什么动静？",
            "source_span": {"start": 10, "end": 10},
        }
        self._save_report_expect(report, expect=1)

    def test_r2_05_out_of_bounds_span_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1)
        report["issues"][0]["evidence"] = {
            "evidence_type": "source",
            "quote": "什么动静？",
            "source_span": {"start": 999999, "end": 1000000},
        }
        self._save_report_expect(report, expect=1)

    def test_r2_06_event_a_quote_b_cross_assembly_rejected(self):
        self._init()
        self._novel()
        self._events(SPANNED_EVENTS)
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["source_event_ids"] = ["CH001-E01", "CH001-E02"]
        self._save_outlines([outline])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        report = self._review_report(1)
        report["issues"][0]["evidence"] = {
            "evidence_type": "source",
            "event_id": "CH001-E01",
            "quote": "绑错惩罚对象了。",
        }
        self._save_report_expect(report, expect=1)

    def test_r2_07_quote_and_excerpt_hash_from_different_excerpts_rejected(self):
        self._init()
        self._novel()
        self._events(SPANNED_EVENTS)
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["source_event_ids"] = ["CH001-E01", "CH001-E02"]
        self._save_outlines([outline])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        excerpts = context["source_evidence"]["raw_excerpts"]
        e02_hash = next(ex["excerpt_hash"] for ex in excerpts if "E02" in ex["reason"])
        report = self._review_report(1)
        report["issues"][0]["evidence"] = {
            "evidence_type": "source",
            "quote": "什么动静？",
            "excerpt_hash": e02_hash,
        }
        self._save_report_expect(report, expect=1)

    def test_r2_08_tampered_review_rejected_by_rewrite(self):
        self._full_ep1_setup()
        self._save_review(1, self._review_report(1))
        review_path = active_artifact_path(self.project_dir, "review", 1)
        data = json.loads(review_path.read_text(encoding="utf-8"))
        data["summary"] = "被篡改的摘要"
        review_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1", expect=1)

    def test_r2_09_manifest_review_hash_tampered_rejected_by_rewrite(self):
        self._full_ep1_setup()
        self._save_review(1, self._review_report(1))
        manifest_path = self.project_dir / "state" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["review:1"]["versions"][-1]["content_hash"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1", expect=1)

    def test_r2_10_invalid_issue_shapes_rejected(self):
        self._full_ep1_setup()
        for label, mutate in (
            ("non_object", lambda r: r["issues"].append("not-a-dict")),
            ("empty_problem", lambda r: r["issues"].__setitem__(0, {"id": "X", "severity": "error", "category": "causality", "problem": "   ", "evidence": {"evidence_type": "source", "quote": "什么动静？"}})),
            ("bad_severity", lambda r: r["issues"].__setitem__(0, {"id": "X", "severity": "fatal", "category": "causality", "problem": "p"})),
        ):
            with self.subTest(label=label):
                report = self._review_report(1)
                mutate(report)
                self._save_report_expect(report, expect=1)


class Round2ContinuityTests(Round1BypassBase):
    """§13 items 11–18: clean continuity rebuild and delta lifecycle."""

    def _approve_script(self, episode: int, text: str) -> None:
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, episode, text)

    def _save_delta(self, episode: int, facts: list[dict]) -> None:
        delta = {"extraction_mode": "host_agent", "facts": facts}
        path = self.root / "delta.json"
        path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
        _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", str(episode), "--file", str(path))

    def test_r2_11_replacing_approved_script_drops_old_facts(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta(
            1,
            [{"fact_id": "F-A", "category": "event", "fact": "A 独有事实", "evidence_location": "1-1 叶聆台词", "status": "active"}],
        )
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        from scripts.state_store import load_continuity

        continuity = load_continuity(self.project_dir)
        self.assertNotIn("A 独有事实", [f.get("fact") for f in continuity["facts"]])

    def test_r2_12_two_projects_do_not_share_facts(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta(
            1,
            [{"fact_id": "F-A", "category": "event", "fact": "项目A独有", "evidence_location": "1-1", "status": "active"}],
        )
        # Project B in the same Python process.
        other = self.root / "projects" / "other"
        from scripts.continuity_manager import apply_approved_script as apply2
        from scripts.state_store import init_project, load_continuity as load2

        init_project(
            other,
            {
                "project_id": "other",
                "novel_name": "b",
                "drama_name": "b",
                "platform": "p",
                "genre": ["喜剧"],
                "writer_has_final_authority": True,
            },
        )
        apply2(other, 1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        facts_b = [f.get("fact") for f in load2(other)["facts"]]
        self.assertNotIn("项目A独有", facts_b)

    def test_r2_13_repeated_refresh_does_not_duplicate(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta(
            1,
            [{"fact_id": "F-A", "category": "event", "fact": "事实X", "evidence_location": "1-1", "status": "active"}],
        )
        from scripts.continuity_manager import refresh_continuity
        from scripts.state_store import load_continuity

        first = load_continuity(self.project_dir)
        refresh_continuity(self.project_dir)
        second = load_continuity(self.project_dir)
        self.assertEqual(len(first["facts"]), len(second["facts"]))
        self.assertEqual(first["character_knowledge"], second["character_knowledge"])

    def test_r2_14_restoring_approved_version_restores_its_facts(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta(
            1,
            [{"fact_id": "F-A", "category": "event", "fact": "A事实", "evidence_location": "1-1", "status": "active"}],
        )
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v001", "--reason", "restore A")
        from scripts.state_store import load_continuity

        facts = [f.get("fact") for f in load_continuity(self.project_dir)["facts"]]
        self.assertIn("A事实", facts)

    def test_r2_15_incomplete_host_agent_delta_flagged_degraded(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        delta = {"extraction_mode": "host_agent", "notes": ["没有结构化事实"]}
        path = self.root / "delta.json"
        path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
        _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path))
        from scripts.state_store import load_continuity

        continuity = load_continuity(self.project_dir)
        self.assertIn("1", continuity["degraded_episodes"])
        self.assertFalse(continuity["episode_extraction"]["1"]["complete"])

    def test_r2_16_fact_missing_required_fields_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        for missing in ("fact_id", "category", "evidence_location"):
            with self.subTest(missing=missing):
                fact = {"fact_id": "F", "category": "event", "fact": "事实", "evidence_location": "1-1", "status": "active"}
                fact.pop(missing)
                delta = {"extraction_mode": "host_agent", "facts": [fact]}
                path = self.root / "delta.json"
                path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
                _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=1)

    def test_r2_17_multiple_deltas_consume_only_current_pointer(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._save_delta(1, [{"fact_id": "F1", "category": "event", "fact": "第一版事实", "evidence_location": "1-1", "status": "active"}])
        self._save_delta(1, [{"fact_id": "F2", "category": "event", "fact": "第二版事实", "evidence_location": "1-1", "status": "active"}])
        from scripts.state_store import load_continuity

        facts = [f.get("fact") for f in load_continuity(self.project_dir)["facts"]]
        self.assertIn("第二版事实", facts)
        self.assertNotIn("第一版事实", facts)

    def test_r2_18_mixed_extraction_mode_reported_accurately(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._approve_script(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._approve_script(2, "第2集：第2集\n\n2-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        self._save_delta(
            1,
            [{"fact_id": "F-A", "category": "event", "fact": "EP1事实", "evidence_location": "1-1", "status": "active"}],
        )
        from scripts.state_store import load_continuity

        continuity = load_continuity(self.project_dir)
        self.assertEqual(continuity["extraction_mode"], "mixed")
        self.assertEqual(continuity["episode_extraction"]["1"]["mode"], "host_agent")
        self.assertEqual(continuity["episode_extraction"]["2"]["mode"], "deterministic")


class Round2RewriteSourceTests(Round1BypassBase):
    """§13 items 19–24: Host Agent rewrite provenance."""

    def _prepare_reviewed_draft(self) -> dict:
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        self._save_review(1, self._review_report(1))
        from scripts.state_store import draft_meta_record

        v1 = active_version_id(self.project_dir, "script_draft", 1)
        return {"v1": v1, "meta": draft_meta_record(self.project_dir, 1, v1)}

    def test_r2_19_host_agent_ticket_draft_marked_automatic_rewrite(self):
        binding = self._prepare_reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self.assertIsNotNone(ticket)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n",
            context_hash=binding["meta"]["context_hash"],
            rewrite_ticket=ticket["ticket_id"],
        )
        v2 = active_version_id(self.project_dir, "script_draft", 1)
        meta = draft_meta_record(self.project_dir, 1, v2)
        self.assertEqual(meta["origin"], "automatic_rewrite")
        self.assertEqual(meta["rewrite_ticket_id"], ticket["ticket_id"])

    def test_r2_20_same_ticket_second_consumption_rejected(self):
        binding = self._prepare_reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n",
            context_hash=binding["meta"]["context_hash"],
            rewrite_ticket=ticket["ticket_id"],
        )
        # Second consumption of the same ticket must be rejected.
        _run(
            "save-draft",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--file", str(self.root / "draft_ep1.txt"),
            "--rewrite-ticket", ticket["ticket_id"],
            expect=1,
        )

    def test_r2_21_ticket_for_other_episode_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        self._save_review(1, self._review_report(1))
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self._context(2)
        path = self.root / "draft_ep2.txt"
        path.write_text("第2集：第2集\n\n2-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：B。\n", encoding="utf-8")
        _run(
            "save-draft",
            "--dir", str(self.project_dir),
            "--episode", "2",
            "--file", str(path),
            "--rewrite-ticket", ticket["ticket_id"],
            expect=1,
        )

    def test_r2_22_automatic_rewrite_draft_cannot_be_auto_rewritten_again(self):
        binding = self._prepare_reviewed_draft()
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
                    "id": "R2-22",
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

    def test_r2_23_manual_new_version_gets_one_more_rewrite(self):
        binding = self._prepare_reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n",
            context_hash=binding["meta"]["context_hash"],
            rewrite_ticket=ticket["ticket_id"],
        )
        # Manual save (no ticket) resets the automatic-rewrite opportunity.
        v3 = self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△人工动作。\n叶聆：什么动静？\n996：人工台词。\n",
            context_hash=binding["meta"]["context_hash"],
            manual_edit=True,
        )
        meta3 = draft_meta_record(self.project_dir, 1, v3)
        self.assertEqual(meta3["origin"], "manual")
        report3 = {
            "episode": 1,
            "context_hash": meta3["context_hash"],
            "draft_hash": meta3["draft_hash"],
            "draft_version": v3,
            "verdict": "blocked",
            "summary": "人工后重写",
            "issues": [
                {
                    "id": "R2-23",
                    "severity": "error",
                    "category": "causality",
                    "problem": "问题",
                    "evidence": {"evidence_type": "source", "quote": "什么动静？"},
                    "fix": "修复",
                }
            ],
        }
        self._save_review(1, report3)
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")

    def test_r2_24_omitting_ticket_cannot_pretend_manual(self):
        binding = self._prepare_reviewed_draft()
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        # Omitting the ticket must be REJECTED, not silently treated as manual.
        path = self.root / "draft_no_ticket.txt"
        path.write_text(
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△人工动作。\n叶聆：什么动静？\n996：人工台词。\n",
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
        # Explicit manual-edit flow cancels the ticket and records the audit.
        v2 = self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△人工动作。\n叶聆：什么动静？\n996：人工台词。\n",
            context_hash=binding["meta"]["context_hash"],
            manual_edit=True,
        )
        meta = draft_meta_record(self.project_dir, 1, v2)
        self.assertEqual(meta["origin"], "manual")
        self.assertNotIn("rewrite_ticket_id", meta)
        from scripts.rewrite_ticket import latest_issued_ticket

        self.assertIsNone(latest_issued_ticket(self.project_dir, 1))
        audit = (self.project_dir / "state" / "manual_edits.jsonl").read_text(encoding="utf-8")
        self.assertIn("writer manual edit", audit)


class Round2LogicalVersionTests(Round1BypassBase):
    """§13 items 25–30: logical versions, idempotency, restore."""

    def _approve(self, text: str):
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, 1, text)

    def test_r2_25_same_content_same_context_same_source_idempotent(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n"
        v1 = self._draft(1, text)
        v1_again = self._draft(1, text)
        self.assertEqual(v1, v1_again)
        self.assertEqual(len(artifact_versions(self.project_dir, "script_draft", 1)), 1)

    def test_r2_26_same_content_different_context_new_logical_version(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n"
        v1 = self._draft(1, text)
        self._save_outlines([self._outline(1, extra_must_keep=["系统登场", "雷击错绑"])])
        self._context(1)
        from scripts.context_builder import current_context_path

        h2 = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))["context_hash"]
        v2 = self._draft(1, text, context_hash=h2)
        self.assertNotEqual(v1, v2)
        meta2 = draft_meta_record(self.project_dir, 1, v2)
        self.assertEqual(meta2["context_hash"], h2)

    def test_r2_27_activate_v1_points_active_to_v1(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._approve("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v001", "--reason", "test")
        active = active_artifact_path(self.project_dir, "approved_script", 1).read_text(encoding="utf-8")
        self.assertIn("动作A", active)
        self.assertNotIn("动作B", active)

    def test_r2_28_restore_missing_or_corrupt_version_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v999", expect=1)
        v1_path = artifact_version_path(self.project_dir, "approved_script", 1, "v001")
        v1_path.write_text("tampered", encoding="utf-8")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v001", expect=1)

    def test_r2_29_restore_approved_script_rebuilds_matching_continuity(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._approve("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n")
        self._approve("第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n")
        _run("activate-version", "--dir", str(self.project_dir), "--kind", "approved_script", "--episode", "1", "--version", "v001", "--reason", "restore")
        active = active_artifact_path(self.project_dir, "approved_script", 1).read_text(encoding="utf-8")
        self.assertIn("动作A", active)

    def test_r2_30_resaving_old_content_does_not_mark_new_revision_applied(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n"
        self._draft(1, text)
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "新修改意见",
            "--direct",
        )
        from scripts.revision_manager import list_revisions

        revision_id = list_revisions(self.project_dir, episode=1)[0]["revision_id"]
        # Re-saving the exact same content is idempotent → no applied binding.
        self._draft(1, text, apply_revision_ids=[revision_id])
        state = list_revisions(self.project_dir, episode=1)[0]
        self.assertEqual(state["status"], "approved")


class Round2EvidenceTests(Round1BypassBase):
    """§13 items 31–37: dialogue pairing and must_keep traceability."""

    def _outline_with_anchor(self, setup: str, payoff: str) -> dict:
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["dialogue_anchors"] = [{"setup": setup, "payoff": payoff, "source": "第1章"}]
        return outline

    def _save_outlines_rejected(self, outlines: list[dict]) -> str:
        path = self.root / "rejected-outlines.json"
        path.write_text(json.dumps(outlines, ensure_ascii=False), encoding="utf-8")
        return _run(
            "save-episode-outline", "--dir", str(self.project_dir),
            "--outline-json", str(path),
            "--manual-import", "--manual-reason", "negative test fixture",
            expect=1,
        )

    def test_r2_31_setup_missing_payoff_only_anchor_omitted(self):
        self._init()
        self._novel()
        self._events()
        output = self._save_outlines_rejected([self._outline_with_anchor("不存在的话", "吃不完的苦")])
        self.assertIn("dialogue_anchor", output)

    def test_r2_32_payoff_missing_setup_only_anchor_omitted(self):
        self._init()
        self._novel()
        self._events()
        output = self._save_outlines_rejected([self._outline_with_anchor("吃得苦中苦，你就能得到……", "不存在的话")])
        self.assertIn("dialogue_anchor", output)

    def test_r2_33_both_ends_present_kept_at_low_budget(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline_with_anchor("吃得苦中苦，你就能得到……", "吃不完的苦")])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        pair = [ex for ex in context["source_evidence"]["raw_excerpts"] if ex["reason"].startswith("dialogue_anchor")]
        self.assertTrue(pair)
        self.assertIn("吃得苦中苦", pair[0]["text"])
        self.assertIn("吃不完的苦", pair[0]["text"])

    def test_r2_34_must_preserve_pairing_quote_pair_not_split(self):
        self._init()
        self._novel()
        self._events(SPANNED_EVENTS)
        self._save_outlines([self._outline(1, extra_must_keep=["系统登场"])])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        e1_excerpt = next(ex for ex in context["source_evidence"]["raw_excerpts"] if "CH001-E01" in ex["reason"])
        self.assertIn("系统登场。", e1_excerpt["text"])
        self.assertIn("什么动静？", e1_excerpt["text"])

    def test_r2_35_must_keep_only_in_event_summary_rejected(self):
        self._init()
        self._novel()
        self._events()
        output = self._save_outlines_rejected([self._outline(1, extra_must_keep=["系统登场并绑定"])])
        self.assertIn("must_keep", output)

    def test_r2_36_event_without_span_marked_degraded(self):
        self._init()
        self._novel()
        events = [{"event_id": "CH001-E01", "chapter_id": 1, "event": "无锚点事件", "importance": "mainline"}]
        self._events(events)
        self._save_outlines([self._outline(1, extra_must_keep=["系统登场"])])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        event_coverage = [c for c in context["source_evidence"]["coverage"] if c["anchor_type"] == "event"]
        self.assertTrue(event_coverage)
        self.assertTrue(all(c.get("degraded") for c in event_coverage))
        self.assertTrue(all(c.get("degraded_reason") == "needs_reanchor" for c in event_coverage))

    def test_r2_37_must_keep_adaptation_decision_requires_valid_id(self):
        self._init()
        self._novel()
        self._events()
        valid = self._outline(1, extra_must_keep=["系统登场"])
        valid["must_keep"] = [{"text": "编剧新增的高光保留项", "adaptation_decision_id": "D1"}]
        valid["adaptation_basis"] = [{"id": "D1", "text": "保留编剧新增高光"}]
        self._save_outlines([valid])
        self._context(1)
        invalid = self._outline(1, extra_must_keep=["系统登场"])
        invalid["must_keep"] = [{"text": "编剧新增的高光保留项", "adaptation_decision_id": "D-NOPE"}]
        invalid["adaptation_basis"] = [{"id": "D1", "text": "保留编剧新增高光"}]
        output = self._save_outlines_rejected([invalid])
        self.assertIn("adaptation_decision_id", output)


class Round2RevisionTests(Round1BypassBase):
    """§13 items 38–43: revision revoke, pending, applied bindings."""

    def _revision(self, instruction: str, *, affects_future: bool | None = None, direct: bool = False) -> str:
        argv = [
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", instruction,
        ]
        if affects_future is not None:
            argv += ["--no-affects-future"] if not affects_future else ["--affects-future"]
        if direct:
            argv += ["--direct"]
        _run(*argv)
        from scripts.revision_manager import list_revisions

        return list_revisions(self.project_dir, episode=1)[-1]["revision_id"]

    def test_r2_38_approved_then_rejected_does_not_enter_context(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        revision_id = self._revision("下一集沿用新规则", affects_future=True, direct=True)
        _run("approve-revision", "--dir", str(self.project_dir), "--revision-id", revision_id)
        _run("reject-revision", "--dir", str(self.project_dir), "--revision-id", revision_id)
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        self.assertNotIn("下一集沿用新规则", [o.get("instruction") for o in context["writer_overrides"]])

    def test_r2_39_applied_revision_revoked_stops_propagating_with_audit(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._context(1)
        revision_id = self._revision("下一集沿用新规则", affects_future=True, direct=True)
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n"
        self._draft(1, text, apply_revision_ids=[revision_id])
        from scripts.revision_manager import list_revisions

        state = list_revisions(self.project_dir, episode=1)[0]
        self.assertEqual(state["status"], "applied")
        self.assertEqual(state["applied_to"]["kind"], "script_draft")
        _run("revoke-revision", "--dir", str(self.project_dir), "--revision-id", revision_id, "--reason", "撤销")
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        self.assertNotIn("下一集沿用新规则", [o.get("instruction") for o in context["writer_overrides"]])
        log = (self.project_dir / "state" / "revisions.jsonl").read_text(encoding="utf-8")
        self.assertIn("revoked", log)

    def test_r2_40_future_pending_revision_announced_in_later_episode(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._revision("下一集台词要更贴原文", affects_future=True)
        out = _run("get-episode-context", "--dir", str(self.project_dir), "--episode", "2")
        self.assertIn("待编剧确认", out)

    def test_r2_41_affects_future_false_overrides_keywords(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        self._revision("下一集沿用新规则", affects_future=False, direct=True)
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        self.assertNotIn("下一集沿用新规则", [o.get("instruction") for o in context["writer_overrides"]])

    def test_r2_42_plain_draft_save_does_not_mark_applied(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        revision_id = self._revision("改台词", direct=True)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n")
        from scripts.revision_manager import list_revisions

        self.assertEqual(list_revisions(self.project_dir, episode=1)[0]["status"], "approved")

    def test_r2_43_only_explicit_revision_ids_bound_applied(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        rev_a = self._revision("改A", direct=True)
        rev_b = self._revision("改B", direct=True)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n",
            apply_revision_ids=[rev_a],
        )
        from scripts.revision_manager import list_revisions

        states = {r["revision_id"]: r["status"] for r in list_revisions(self.project_dir, episode=1)}
        self.assertEqual(states[rev_a], "applied")
        self.assertEqual(states[rev_b], "approved")


class Round2ContextFormatTests(Round1BypassBase):
    """§13 items 44–50: context immutability and XML/business separation."""

    def test_r2_44_role_bundles_do_not_change_snapshot_bytes(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        _run("get-episode-context", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.context_builder import current_context_path
        from scripts.prompt_router import render_prompt_bundle

        snapshot = current_context_path(self.project_dir, 1)
        before = snapshot.read_bytes()
        context = json.loads(snapshot.read_text(encoding="utf-8"))
        for role in ("writer", "reviewer", "rewriter"):
            render_prompt_bundle(context, role=role, config=context["project_brief"])
        self.assertEqual(snapshot.read_bytes(), before)

    def test_r2_45_valid_json_tampering_rejected_on_consume(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n")
        from scripts.context_builder import current_context_path

        snapshot = current_context_path(self.project_dir, 1)
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        data["episode_outline"]["episode_goal"] = "被篡改的目标"
        snapshot.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        _run("review", "--dir", str(self.project_dir), "--episode", "1", expect=1)

    def test_r2_46_same_hash_path_with_different_bytes_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        from scripts.context_builder import current_context_path, snapshot_path

        snapshot = current_context_path(self.project_dir, 1)
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        fake = snapshot_path(self.project_dir, 1, data["context_hash"])
        fake.write_text('{"evil": true}', encoding="utf-8")
        from scripts.context_builder import ContextIncompleteError, build_episode_context

        with self.assertRaises(ContextIncompleteError):
            build_episode_context(self.project_dir, 1)

    def test_r2_47_legacy_config_still_saves_business_body(self):
        self._init()
        from scripts.state_store import config_path

        config = json.loads(config_path(self.project_dir).read_text(encoding="utf-8"))
        config["script_format"] = "legacy-scriptitem"
        config_path(self.project_dir).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        from scripts.state_store import load_config

        migrated = load_config(self.project_dir)
        self.assertEqual(migrated["script_format"], "default-cn")
        self.assertEqual(migrated["transport_format"], "legacy-scriptitem")
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n"
        version = self._draft(1, text)
        saved = artifact_version_path(self.project_dir, "script_draft", 1, version).read_text(encoding="utf-8")
        self.assertNotIn("<scriptItem", saved)
        self.assertIn("第1集：第1集", saved)

    def test_r2_48_xml_only_in_export_internal_approved_plain(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        text = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n"
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, 1, text)
        out_path = self.root / "export.xml"
        _run("export", "--dir", str(self.project_dir), "--xml", "--out", str(out_path))
        exported = out_path.read_text(encoding="utf-8")
        self.assertIn("<scriptItem", exported)
        approved = active_artifact_path(self.project_dir, "approved_script", 1).read_text(encoding="utf-8")
        self.assertNotIn("<scriptItem", approved)

    def test_r2_49_legacy_xml_import_saved_as_plain_business(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        # v0.3.6 语义覆盖守卫要求草稿包含 must_keep 节拍“系统登场”。
        xml_text = '<scriptItem name="EP001">\n第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△系统登场。\n△动作。\n叶聆：A。\n</scriptItem>\n'
        path = self.root / "xml_draft.txt"
        path.write_text(xml_text, encoding="utf-8")
        _run("save-draft", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path))
        version = active_version_id(self.project_dir, "script_draft", 1)
        saved = artifact_version_path(self.project_dir, "script_draft", 1, version).read_text(encoding="utf-8")
        self.assertNotIn("<scriptItem", saved)
        self.assertIn("第1集：第1集", saved)

    def test_r2_50_xml_content_outside_tags_rejected(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        xml_text = (
            '<scriptItem name="EP001">\n第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作。\n叶聆：A。\n</scriptItem>\n'
            "标签外内容"
        )
        path = self.root / "bad_xml.txt"
        path.write_text(xml_text, encoding="utf-8")
        _run("save-draft", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=1)


if __name__ == "__main__":
    unittest.main()
