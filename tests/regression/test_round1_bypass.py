"""Round-1 independent-review bypass tests (fix-brief §10, items 1–22).

Every test name maps to one bypass scenario from the review contract. Tests
drive the real CLI/modules and must fail before the round-1 fixes, pass after.
"""

import contextlib
import io
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
    commit_artifact,
    draft_meta_record,
)


def _run(*argv, expect=0) -> str:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    if code != expect:
        raise AssertionError(
            f"CLI 返回 {code}（期望 {expect}）: {' '.join(argv)}\nstdout={out.getvalue()[-800:]}\nstderr={err.getvalue()[-800:]}"
        )
    return out.getvalue() + err.getvalue()


class Round1BypassBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project_dir = self.root / "projects" / "bypass"

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self) -> dict:
        return {
            "project_id": "bypass",
            "novel_name": "测试书",
            "drama_name": "测试剧",
            "platform": "竖屏短剧",
            "genre": ["喜剧"],
            "initial_episode_count": 3,
            "minimum_episode_seconds": 60,
            "script_format": "default-cn",
            "writer_has_final_authority": True,
        }

    def _init(self):
        config = self.root / "config.json"
        config.write_text(json.dumps(self._config(), ensure_ascii=False), encoding="utf-8")
        _run("init", "--dir", str(self.project_dir), "--config", str(config))

    def _novel(self, text: str | None = None):
        novel = self.root / "novel.txt"
        novel.write_text(
            text
            or (
                "第一章 规则建立\n谢淮舟提出录完节目离婚。系统登场。叶聆：什么动静？996：我不是b动静。"
                "996：吃得苦中苦，你就能得到……叶聆：吃不完的苦。雷击错绑。996：绑错惩罚对象了。\n"
                "第二章 第二集\n叶聆：你搁我家床底看见了？\n"
                "第三章 第三集\n叶聆：所以一定是闹鬼了。\n"
            ),
            encoding="utf-8",
        )
        _run("ingest-source", "--dir", str(self.project_dir), "--file", str(novel))

    def _events(self, events: list[dict] | None = None):
        events = events or [
            {
                "event_id": "CH001-E01",
                "chapter_id": 1,
                "event": "系统登场并绑定",
                "importance": "mainline",
                "key_quotes": [{"speaker": "叶聆", "text": "什么动静？", "must_preserve_pairing": True}],
            },
            {
                "event_id": "CH001-E02",
                "chapter_id": 1,
                "event": "雷击错绑",
                "importance": "mainline",
                "key_quotes": [{"speaker": "996", "text": "绑错惩罚对象了。", "must_preserve_pairing": True}],
            },
            {"event_id": "CH002-E01", "chapter_id": 2, "event": "报警反击", "importance": "mainline"},
            {"event_id": "CH003-E01", "chapter_id": 3, "event": "闹鬼论", "importance": "mainline"},
        ]
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        _run("save-events", "--dir", str(self.project_dir), "--file", str(path))

    def _outline(self, episode: int, extra_must_keep: list[str] | None = None) -> dict:
        default_must_keep = {
            1: ["系统登场"],
            2: ["你搁我家床底看见了？"],
            3: ["所以一定是闹鬼了。"],
        }
        return {
            "episode": episode,
            "title": f"第{episode}集",
            "source_event_ids": [f"CH00{episode}-E01"],
            "source_chapters": [episode],
            "opening_bridge": "承接",
            "episode_goal": "目标",
            "must_keep": extra_must_keep or default_must_keep.get(episode, ["系统登场并绑定"]),
            "causal_chains": [["刺激", "回应"]],
            "knowledge_at_start": {},
            "knowledge_at_end": {},
            "ending_hook": "钩子",
            "suggested_seconds": [90, 130],
            "episode_function": ["opening"],
        }

    def _save_outlines(self, outlines: list[dict], *, replace: bool = False):
        path = self.root / "outlines.json"
        path.write_text(json.dumps(outlines, ensure_ascii=False), encoding="utf-8")
        argv = ["save-episode-outline", "--dir", str(self.project_dir), "--outline-json", str(path)]
        argv += ["--manual-import", "--manual-reason", "round1 synthetic writer fixture"]
        if replace:
            argv.append("--replace")
        _run(*argv)
        version = active_version_id(self.project_dir, "episode_outline")
        _run(
            "confirm-stage", "--dir", str(self.project_dir),
            "--stage", "episode_outline", "--version", str(version),
            "--operator", "round1-writer", "--confirmation-ref", "round1-fixture-confirmation",
            "--override-reason", "round1 synthetic writer fixture reviewed",
        )

    def _context(self, episode: int):
        _run("get-episode-context", "--dir", str(self.project_dir), "--episode", str(episode))

    def _draft(
        self,
        episode: int,
        text: str,
        *,
        context_hash: str | None = None,
        rewrite_ticket: str | None = None,
        apply_revision_ids: list[str] | None = None,
        manual_edit: bool = False,
    ) -> str:
        # v0.3.6 新增“必保留语义覆盖”守卫后，合成精简草稿必须包含集纲
        # must_keep 节拍（系统登场 / 雷击错绑）才能通过 save-draft。
        # 追加节拍只让夹具符合新契约，不改变各用例断言的绕过/哈希/证据语义。
        if "系统登场" not in text:
            text += "△系统登场。\n"
        if "雷击错绑" not in text:
            text += "△雷击错绑。\n"
        path = self.root / f"draft_ep{episode}.txt"
        path.write_text(text, encoding="utf-8")
        argv = ["save-draft", "--dir", str(self.project_dir), "--episode", str(episode), "--file", str(path)]
        if context_hash:
            argv += ["--context-hash", context_hash]
        if rewrite_ticket:
            argv += ["--rewrite-ticket", rewrite_ticket]
        if manual_edit:
            argv += ["--manual-edit", "--manual-reason", "writer manual edit"]
        for revision_id in apply_revision_ids or []:
            argv += ["--apply-revision", revision_id]
        _run(*argv)
        version = active_version_id(self.project_dir, "script_draft", episode)
        self.assertIsNotNone(version)
        return version

    def _review_report(self, episode: int, *, quote: str = "什么动静？", issue_id: str = "BYPASS-001") -> dict:
        version = active_version_id(self.project_dir, "script_draft", episode)
        meta = draft_meta_record(self.project_dir, episode, version)
        self.assertIsNotNone(meta)
        return {
            "episode": episode,
            "context_hash": meta["context_hash"],
            "draft_hash": meta["draft_hash"],
            "draft_version": version,
            "verdict": "blocked",
            "summary": "绕过测试",
            "issues": [
                {
                    "id": issue_id,
                    "severity": "error",
                    "category": "causality",
                    "problem": "问题",
                    "evidence": {"evidence_type": "source", "quote": quote},
                    "fix": "修复",
                }
            ],
        }

    def _save_review(self, episode: int, report: dict):
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", str(episode), "--file", str(path))

    def _full_ep1_setup(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")


class BypassHashBindingTests(Round1BypassBase):
    """§10 items 1–7: context/draft/review must be truly same-source."""

    def test_01_review_missing_context_hash_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1)
        report.pop("context_hash")
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=1)

    def test_02_review_missing_draft_hash_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1)
        report.pop("draft_hash")
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=1)

    def test_03_draft_from_h1_cannot_be_reviewed_with_h2_context(self):
        self._full_ep1_setup()
        # Change the outline and rebuild the context (H2 replaces the pointer).
        self._save_outlines([self._outline(1, extra_must_keep=["系统登场", "雷击错绑"])])
        self._context(1)
        _run("review", "--dir", str(self.project_dir), "--episode", "1", expect=1)

    def test_04_v1_review_cannot_rewrite_v2_draft(self):
        self._full_ep1_setup()
        v1 = active_version_id(self.project_dir, "script_draft", 1)
        self._save_review(1, self._review_report(1))
        # Upload a v2 draft; the v1 review must still bind v1 only.
        meta = draft_meta_record(self.project_dir, 1, v1)
        self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：新台词。\n", context_hash=meta["context_hash"])
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        bundle = (self.project_dir / "state" / "prompt_bundles" / "ep001_rewriter.md").read_text(encoding="utf-8")
        self.assertIn("什么动静？", bundle)
        self.assertNotIn("新台词", bundle)

    def test_05_tampered_context_snapshot_hash_fails(self):
        self._full_ep1_setup()
        from scripts.context_builder import current_context_path

        snapshot = current_context_path(self.project_dir, 1)
        snapshot.write_text(snapshot.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
        _run("review", "--dir", str(self.project_dir), "--episode", "1", expect=1)

    def test_06_arbitrary_evidence_string_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1, quote="任意字符串证据")
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=1)

    def test_07_nonexistent_event_id_evidence_rejected(self):
        self._full_ep1_setup()
        report = self._review_report(1)
        report["issues"][0]["evidence"] = {
            "evidence_type": "source",
            "event_id": "NOPE-E99",
            "quote": "什么动静？",
        }
        path = self.root / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        _run("save-review", "--dir", str(self.project_dir), "--episode", "1", "--file", str(path), expect=1)


class BypassVersioningTests(Round1BypassBase):
    """§10 items 8–12: real version history and idempotency."""

    def test_08_single_episode_outline_update_keeps_other_episodes(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        modified = self._outline(1)
        modified["episode_goal"] = "修改后的目标"
        self._save_outlines([modified])
        from scripts.context_builder import _load_episode_outlines

        outlines = _load_episode_outlines(self.project_dir)
        self.assertIn(1, outlines)
        self.assertIn(2, outlines)
        self.assertEqual(outlines[1]["episode_goal"], "修改后的目标")

    def test_09_small_batch_outline_update_keeps_out_of_batch_episodes(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2), self._outline(3)])
        self._save_outlines([self._outline(2), self._outline(3)])
        from scripts.context_builder import _load_episode_outlines

        outlines = _load_episode_outlines(self.project_dir)
        self.assertEqual(sorted(outlines), [1, 2, 3])

    def test_10_two_approved_versions_both_readable(self):
        self._init()
        approved1 = "第1集：定稿A\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作A。\n叶聆：A。\n"
        approved2 = "第1集：定稿B\n\n1-1 家 夜 内\n人物：叶聆\n\n△动作B。\n叶聆：B。\n"
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, 1, approved1)
        apply_approved_script(self.project_dir, 1, approved2)
        v1_path = artifact_version_path(self.project_dir, "approved_script", 1, "v001")
        v2_path = artifact_version_path(self.project_dir, "approved_script", 1, "v002")
        self.assertEqual(v1_path.read_text(encoding="utf-8"), approved1)
        self.assertEqual(v2_path.read_text(encoding="utf-8"), approved2)

    def test_11_two_review_versions_both_readable(self):
        self._full_ep1_setup()
        self._save_review(1, self._review_report(1, issue_id="R1"))
        meta = draft_meta_record(self.project_dir, 1, active_version_id(self.project_dir, "script_draft", 1))
        second = self._review_report(1, quote="绑错惩罚对象了。", issue_id="R2")
        self._save_review(1, second)
        v1_path = artifact_version_path(self.project_dir, "review", 1, "v001")
        v2_path = artifact_version_path(self.project_dir, "review", 1, "v002")
        self.assertIn("R1", v1_path.read_text(encoding="utf-8"))
        self.assertIn("R2", v2_path.read_text(encoding="utf-8"))

    def test_12_identical_content_repeat_save_is_idempotent(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._save_outlines([self._outline(1)])
        self.assertEqual(len(artifact_versions(self.project_dir, "episode_outline")), 1)


class BypassContinuityTests(Round1BypassBase):
    """§10 items 13–14: host-agent continuity and current-approved context."""

    def test_13_host_agent_delta_fact_reaches_ep3_context(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2), self._outline(3)])
        script = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n"
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, 1, script)
        delta = {
            "extraction_mode": "host_agent",
            "facts": [
                {
                    "fact_id": "F-001",
                    "category": "system_rule",
                    "fact": "谢淮舟能听见系统并会替叶聆受罚",
                    "episode": 1,
                    "evidence_location": "1-1 叶聆台词",
                    "status": "active",
                }
            ],
            "character_knowledge": {"叶聆": ["系统惩罚会落到谢淮舟"]},
        }
        delta_file = self.root / "delta.json"
        delta_file.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
        _run("save-continuity-delta", "--dir", str(self.project_dir), "--episode", "1", "--file", str(delta_file))
        self._context(3)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 3).read_text(encoding="utf-8"))
        facts = [f.get("fact") for f in context["continuity_state"]["facts"]]
        self.assertIn("谢淮舟能听见系统并会替叶聆受罚", facts)
        self.assertIn("系统惩罚会落到谢淮舟", context["continuity_state"]["character_knowledge"]["叶聆"])

    def test_14_revision_context_for_approved_episode_includes_current_approved(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        script = "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n"
        from scripts.continuity_manager import apply_approved_script

        apply_approved_script(self.project_dir, 1, script)
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        self.assertIn("第1集", context["current_approved_script"])


class BypassRetrievalTests(Round1BypassBase):
    """§10 items 15–17: retrieval coverage and pair protection."""

    def test_15_long_explicit_chapter_has_excerpt(self):
        self._init()
        long_chapter = "第一章 长章节\n" + ("这是一个很长的句子，用于撑满预算。\n" * 120)
        self._novel(long_chapter)
        events = [
            {
                "event_id": "CH001-E01",
                "chapter_id": 1,
                "event": "长章节事件",
                "importance": "mainline",
            }
        ]
        self._events(events)
        self._save_outlines([self._outline(1, extra_must_keep=["这是一个很长的句子"])])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        chapter_coverage = [c for c in context["source_evidence"]["coverage"] if c["anchor_type"] == "chapter"]
        self.assertTrue(chapter_coverage)
        self.assertTrue(all(c["included"] for c in chapter_coverage))
        self.assertTrue(any(ex["chapter_id"] == 1 for ex in context["source_evidence"]["raw_excerpts"]))

    def test_16_setup_payoff_not_split_at_low_budget(self):
        self._init()
        self._novel()
        self._events()
        outline = self._outline(1, extra_must_keep=["系统登场"])
        outline["dialogue_anchors"] = [
            {"setup": "吃得苦中苦，你就能得到……", "payoff": "吃不完的苦。", "source": "第1章"}
        ]
        self._save_outlines([outline])
        self._context(1)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 1).read_text(encoding="utf-8"))
        pair_excerpts = [ex for ex in context["source_evidence"]["raw_excerpts"] if ex["reason"].startswith("dialogue_anchor")]
        self.assertTrue(pair_excerpts)
        self.assertIn("吃得苦中苦", pair_excerpts[0]["text"])
        self.assertIn("吃不完的苦", pair_excerpts[0]["text"])

    def test_17_completeness_flags_chapter_ids_without_excerpts(self):
        from scripts.source_retriever import source_evidence_complete

        problems = source_evidence_complete(
            {
                "chapter_ids": [1, 2],
                "events": [],
                "raw_excerpts": [],
                "coverage": [
                    {
                        "anchor_type": "chapter",
                        "anchor_id": "1",
                        "requested": True,
                        "resolved": False,
                        "included": False,
                        "omitted": True,
                        "reason": "no_excerpt",
                    }
                ],
                "retrieval_report": {"fallback_used": False},
            }
        )
        self.assertTrue(any("章节" in p or "chapter" in p or "锚点" in p for p in problems))


class BypassRevisionTests(Round1BypassBase):
    """§10 items 18–22: revision lifecycle and rewrite limits."""

    def test_18_pending_revision_warned_before_creation(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "下一集台词要更贴原文",
        )
        out = _run("get-episode-context", "--dir", str(self.project_dir), "--episode", "1")
        self.assertIn("待编剧确认", out)

    def test_19_approved_revision_enters_context(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "下一集沿用新规则",
        )
        from scripts.revision_manager import list_revisions

        records = list_revisions(self.project_dir, episode=1)
        revision_id = records[0]["revision_id"]
        _run("approve-revision", "--dir", str(self.project_dir), "--revision-id", revision_id)
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        instructions = [o.get("instruction") for o in context["writer_overrides"]]
        self.assertIn("下一集沿用新规则", instructions)

    def test_20_rejected_revision_does_not_enter_context(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "下一集沿用新规则",
        )
        from scripts.revision_manager import list_revisions

        revision_id = list_revisions(self.project_dir, episode=1)[0]["revision_id"]
        _run("reject-revision", "--dir", str(self.project_dir), "--revision-id", revision_id)
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        instructions = [o.get("instruction") for o in context["writer_overrides"]]
        self.assertNotIn("下一集沿用新规则", instructions)

    def test_21_explicit_affects_future_false_overrides_keywords(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1), self._outline(2)])
        _run(
            "apply-revision",
            "--dir", str(self.project_dir),
            "--episode", "1",
            "--instruction", "下一集沿用新规则",
            "--auto-approve",
            "--no-affects-future",
        )
        from scripts.revision_manager import list_revisions

        record = list_revisions(self.project_dir, episode=1)[0]
        self.assertFalse(record["affects_future"])
        self._context(2)
        from scripts.context_builder import current_context_path

        context = json.loads(current_context_path(self.project_dir, 2).read_text(encoding="utf-8"))
        instructions = [o.get("instruction") for o in context["writer_overrides"]]
        self.assertNotIn("下一集沿用新规则", instructions)

    def test_22_automatic_rewrite_limited_human_versions_unlimited(self):
        self._init()
        self._novel()
        self._events()
        self._save_outlines([self._outline(1)])
        self._context(1)
        v1 = self._draft(1, "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△动作。\n叶聆：什么动静？\n996：绑错惩罚对象了。\n")
        self._save_review(1, self._review_report(1))
        meta = draft_meta_record(self.project_dir, 1, v1)
        # System issues one rewrite ticket; Host Agent consumes it for v2.
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1")
        from scripts.rewrite_ticket import latest_issued_ticket

        ticket = latest_issued_ticket(self.project_dir, 1)
        self.assertIsNotNone(ticket)
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△新动作。\n叶聆：什么动静？\n996：重写台词。\n",
            context_hash=meta["context_hash"],
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
                    "id": "B2",
                    "severity": "error",
                    "category": "causality",
                    "problem": "问题",
                    "evidence": {"evidence_type": "source", "quote": "什么动静？"},
                    "fix": "修复",
                }
            ],
        }
        self._save_review(1, report2)
        # Second automatic rewrite must be refused.
        _run("rewrite", "--dir", str(self.project_dir), "--episode", "1", expect=1)
        # Human saves v3 (no automatic flag) → rewrite allowed again.
        self._draft(
            1,
            "第1集：第1集\n\n1-1 家 夜 内\n人物：叶聆、996\n\n△人工动作。\n叶聆：什么动静？\n996：人工台词。\n",
            context_hash=meta2["context_hash"],
            manual_edit=True,
        )
        v3 = active_version_id(self.project_dir, "script_draft", 1)
        meta3 = draft_meta_record(self.project_dir, 1, v3)
        report3 = {
            "episode": 1,
            "context_hash": meta3["context_hash"],
            "draft_hash": meta3["draft_hash"],
            "draft_version": v3,
            "verdict": "blocked",
            "summary": "人工后重写",
            "issues": [
                {
                    "id": "B3",
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


if __name__ == "__main__":
    unittest.main()
