"""P1/P2 unit tests: upstream rebind no-redundancy, batch confirm, span locator.

Covers the 2026-08-10 real-content findings:
- source_events v001→v002 (span-only fix) must NOT force downstream re-confirmation
  when the rebound content_hash is identical (P1).
- content_hash truly changed must still force a full rebind (anti-stale guard).
- multi-stage rebind can be confirmed in one batch (P1).
- event extraction gets a local semi-automatic span locator (P1/P2).
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_cli import main
from scripts.state_store import (
    activate_version,
    artifact_version_record,
    load_manifest,
    save_manifest,
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
    "project_id": "rebind",
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


def make_event(event_id: str, chapter: int, start: int, end: int, text: str) -> dict:
    return {
        "event_id": event_id,
        "chapter_id": chapter,
        "event": text,
        "source_span": {"start": start, "end": end},
        "source_quote": text,
        "importance": "mainline",
        "minimum_screen_seconds": 20,
        "preferred_screen_seconds": 35,
    }


class StageRebindTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        self.novel_path = self.root / "novel.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def _init(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        run_cli("init", "--dir", str(self.project), "--config", str(config_path))

    def _novel(self, text: str = "第一章 当前\n事件一开始。事件一结束。\n事件二开始。事件二结束。\n"):
        self.novel_path.write_text(text, encoding="utf-8")
        run_cli("ingest-source", "--dir", str(self.project), "--file", str(self.novel_path), "--overwrite")

    def _save_events(self, events: list[dict]) -> str:
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        run_cli("save-events", "--dir", str(self.project), "--file", str(path))
        return self._active_version("source_events")

    def _active_version(self, kind: str) -> str:
        from scripts.state_store import resolve_active

        resolved = resolve_active(self.project, kind)
        return resolved["version"] if resolved else None

    def _setup(self) -> tuple[list[dict], str]:
        """init + novel + events v001; returns (events, v001)."""
        self._init()
        self._novel()
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start1 = chapter.index("事件一开始")
        start2 = chapter.index("事件二开始")
        events = [
            make_event("CH001-E01", 1, start1, start1 + len("事件一开始。事件一结束。"), "事件一开始。事件一结束。"),
            make_event("CH001-E02", 1, start2, start2 + len("事件二开始。事件二结束。"), "事件二开始。事件二结束。"),
        ]
        version = self._save_events(events)
        return events, version

    def _confirm_adaptation(self, *, content: str = "# 改编指引\n保留当前事件。\n") -> dict:
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        ctx = build_stage_context(self.project, "adaptation")
        adaptation = save_stage_artifact(
            self.project,
            stage="adaptation",
            content=content,
            stage_context=ctx,
        )
        confirm_stage(
            self.project,
            stage="adaptation",
            version=adaptation["version"],
            operator="test-writer",
            confirmation_ref="rebind-msg-1",
            review_override_reason="synthetic reviewed",
        )
        return adaptation

    def test_upstream_version_change_same_hash_not_stale(self):
        """P1: 上游 version 变但 content_hash 相同 → 下游已确认产物不判过期。"""
        from scripts.stage_lifecycle import (
            _record_is_stale,
            assert_stage_artifact_confirmed,
        )

        _, events_v001 = self._setup()
        adaptation = self._confirm_adaptation()

        # 模拟 v002：content_hash 与 v001 完全相同，仅 version 号不同。
        manifest = load_manifest(self.project)
        entry = manifest["artifacts"]["source_events"]
        v001 = next(r for r in entry["versions"] if r["version"] == events_v001)
        v002 = dict(v001)
        v002["version"] = "v002"
        v002["created_at"] = "2026-08-10T12:00:00+08:00"
        entry["versions"].append(v002)
        save_manifest(self.project, manifest)
        activate_version(self.project, "source_events", "v002", operator="test")

        record = artifact_version_record(self.project, "adaptation_strategy", None, adaptation["version"])
        self.assertEqual(record.get("status"), "approved")
        # 关键断言：hash 相同 → 无 stale 问题
        self.assertEqual(_record_is_stale(self.project, record), [])
        assert_stage_artifact_confirmed(self.project, "adaptation")  # 不抛错

    def test_upstream_hash_change_still_stale(self):
        """P1 防过期底线: 上游 content_hash 真变 → 下游已确认产物仍判过期。"""
        from scripts.stage_lifecycle import _record_is_stale

        _, _v001 = self._setup()
        adaptation = self._confirm_adaptation()

        # 保存真正的 v002（span 修正 → content_hash 真变）
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start1 = chapter.index("事件一开始")
        events_v002 = [
            make_event("CH001-E01", 1, start1, start1 + len("事件一开始。"), "事件一开始。"),
            make_event("CH001-E02", 1, chapter.index("事件二开始"), chapter.index("事件二开始") + len("事件二开始。"), "事件二开始。"),
        ]
        self._save_events(events_v002)

        record = artifact_version_record(self.project, "adaptation_strategy", None, adaptation["version"])
        stale = _record_is_stale(self.project, record)
        self.assertNotEqual(stale, [], f"expected stale, got {stale}")

    def test_rebind_same_content_auto_carries_confirmation(self):
        """P1: 上游 hash 真变 → 完整重绑，但重绑内容一字未变 → 自动沿用旧确认。"""
        from scripts.stage_lifecycle import build_stage_context, save_stage_artifact

        _, _v001 = self._setup()
        adaptation = self._confirm_adaptation(content="# 改编指引\n保留当前事件。\n")

        # 上游真变（v002）
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        events_v002 = [
            make_event("CH001-E01", 1, chapter.index("事件一开始"), chapter.index("事件一开始") + len("事件一开始。"), "事件一开始。"),
            make_event("CH001-E02", 1, chapter.index("事件二开始"), chapter.index("事件二开始") + len("事件二开始。"), "事件二开始。"),
        ]
        self._save_events(events_v002)

        # 重绑：同样内容重新生成 → 保存后应自动 approved（carried_from v001）
        ctx = build_stage_context(self.project, "adaptation")
        rebound = save_stage_artifact(
            self.project,
            stage="adaptation",
            content="# 改编指引\n保留当前事件。\n",
            stage_context=ctx,
        )
        self.assertTrue(rebound.get("carried_forward"), "同内容重绑应自动沿用旧确认")
        self.assertEqual(rebound.get("carried_from"), adaptation["version"])
        record = artifact_version_record(self.project, "adaptation_strategy", None, rebound["version"])
        self.assertEqual(record.get("status"), "approved")
        self.assertEqual((record.get("meta") or {}).get("carried_from"), adaptation["version"])
        self.assertTrue((record.get("meta") or {}).get("carried_forward"))

    def test_content_change_still_needs_confirmation(self):
        """防误放行: 重绑内容真的变化 → 不得自动沿用旧确认，仍 needs_writer_confirmation。"""
        from scripts.stage_lifecycle import build_stage_context, save_stage_artifact

        _, _v001 = self._setup()
        self._confirm_adaptation(content="# 改编指引\n保留当前事件。\n")
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        events_v002 = [
            make_event("CH001-E01", 1, chapter.index("事件一开始"), chapter.index("事件一开始") + len("事件一开始。"), "事件一开始。"),
            make_event("CH001-E02", 1, chapter.index("事件二开始"), chapter.index("事件二开始") + len("事件二开始。"), "事件二开始。"),
        ]
        self._save_events(events_v002)
        ctx = build_stage_context(self.project, "adaptation")
        changed = save_stage_artifact(
            self.project,
            stage="adaptation",
            content="# 改编指引\n内容真的变了，新增方向。\n",
            stage_context=ctx,
        )
        self.assertFalse(changed.get("carried_forward"), "内容变化不得自动沿用")
        record = artifact_version_record(self.project, "adaptation_strategy", None, changed["version"])
        self.assertEqual(record.get("status"), "needs_writer_confirmation")

    def test_batch_confirm_stages(self):
        """P1: 批量确认一次处理多个阶段，已自动沿用旧确认的阶段被跳过。"""
        from scripts.stage_lifecycle import build_stage_context, confirm_stages, save_stage_artifact

        _, events_v001 = self._setup()
        adaptation = self._confirm_adaptation()

        # 模拟上游 v002（content_hash 相同、version 不同）：下游不 stale
        manifest = load_manifest(self.project)
        entry = manifest["artifacts"]["source_events"]
        v001 = next(r for r in entry["versions"] if r["version"] == events_v001)
        v002 = dict(v001)
        v002["version"] = "v002"
        entry["versions"].append(v002)
        save_manifest(self.project, manifest)
        activate_version(self.project, "source_events", "v002", operator="test")

        # 重绑同内容 → 自动沿用旧确认（approved/carried）
        ctx = build_stage_context(self.project, "adaptation")
        save_stage_artifact(
            self.project, stage="adaptation", content="# 改编指引\n保留当前事件。\n", stage_context=ctx
        )

        # story_outline 正常待确认
        story_ctx = build_stage_context(self.project, "story_outline")
        story = save_stage_artifact(
            self.project, stage="story_outline", content="# 故事大纲\n主线。\n", stage_context=story_ctx
        )

        result = confirm_stages(
            self.project,
            stages=["adaptation", "story_outline"],
            operator="test-writer",
            confirmation_ref="rebind-batch-1",
            review_override_reason="synthetic reviewed",
        )
        # adaptation 已 carried_forward → 跳过；story_outline 被确认
        self.assertEqual(result["carried_forward_skipped"], 1)
        self.assertEqual(len(result["stages"]), 1)
        self.assertEqual(result["stages"][0]["version"], story["version"])
        record = artifact_version_record(self.project, "story_outline", None, story["version"])
        self.assertEqual(record.get("status"), "approved")

    def test_batch_confirm_stages_rejects_stale(self):
        """批量确认预检: 任一阶段过期 → 整体拒绝，不部分提交。"""
        from scripts.stage_lifecycle import confirm_stages

        _, _v001 = self._setup()
        self._confirm_adaptation()
        # 上游 hash 真变 → 已确认的 adaptation 过期
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        events_v002 = [
            make_event("CH001-E01", 1, chapter.index("事件一开始"), chapter.index("事件一开始") + len("事件一开始。"), "事件一开始。"),
            make_event("CH001-E02", 1, chapter.index("事件二开始"), chapter.index("事件二开始") + len("事件二开始。"), "事件二开始。"),
        ]
        self._save_events(events_v002)
        with self.assertRaises(ValueError):
            confirm_stages(
                self.project,
                stages=["adaptation"],
                operator="test-writer",
                confirmation_ref="rebind-batch-2",
                review_override_reason="synthetic reviewed",
            )

    def test_span_locator_exact_and_occurrence(self):
        from scripts.span_locator import locate_span

        text = "事件一开始。事件一结束。\n事件二开始。事件二结束。"
        result = locate_span(text, "事件一开始。")
        self.assertTrue(result["found"])
        self.assertEqual(result["source_quote"], "事件一开始。")
        self.assertEqual(text[result["span"]["start"]:result["span"]["end"]], "事件一开始。")
        self.assertEqual(result["coordinate_base"], "chapter_file_content")

        # occurrence=2
        two = locate_span("事件X。事件X。", "事件X。", occurrence=2)
        self.assertTrue(two["found"])
        self.assertEqual(two["span"]["start"], 4)

    def test_span_locator_result_feeds_save_events(self):
        """P2 闭环: 半自动定位出的 span 可直接构造事件并通过 save-events 校验。"""
        from scripts.span_locator import locate_span

        self._init()
        self._novel()
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        loc = locate_span(chapter, "事件一开始。")
        self.assertTrue(loc["found"])
        events = [
            make_event("CH001-E01", 1, loc["span"]["start"], loc["span"]["end"], loc["source_quote"])
        ]
        self._save_events(events)  # save-events 会校验 span/quote/hash 一致性，失败则抛错
        from scripts.state_store import resolve_active

        resolved = resolve_active(self.project, "source_events")
        self.assertIsNotNone(resolved)
        self.assertEqual(len(resolved["record"].get("content") or json.loads(resolved["path"].read_text(encoding="utf-8"))), 1)

    def test_span_locator_fuzzy_and_not_found(self):
        from scripts.span_locator import locate_span

        text = "事件一\n开始。事件一 结束。"
        # 精确失败、弱匹配成功（容忍换行/空格差异）
        exact = locate_span(text, "事件一开始。")
        self.assertFalse(exact["found"])
        fuzzy = locate_span(text, "事件一开始。", fuzzy=True)
        self.assertTrue(fuzzy["found"])
        self.assertEqual(text[fuzzy["span"]["start"]:fuzzy["span"]["end"]], "事件一\n开始。")

        missing = locate_span(text, "不存在的片段")
        self.assertFalse(missing["found"])
        self.assertEqual(missing["suggest"], "needs_reanchor")


if __name__ == "__main__":
    unittest.main()
