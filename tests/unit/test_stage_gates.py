"""0.3.4 P2-1/P2-2 tests: batch-confirm capacity preflight and carried
episode-outline capacity-decision audit backfill.

P2-1: confirm-stages preflight now includes the episode-outline capacity gate,
so a missing/invalid capacity decision rejects the whole batch BEFORE any
stage is confirmed (no partial 'earlier stages confirmed, later failed' state).

P2-2: a carried-forward episode outline gets its capacity decision backfilled
to the new version, so capacity_decision_for(new_version, hash) is traceable.
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
    resolve_active,
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
    "project_id": "gates",
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


class StageGatesBase(unittest.TestCase):
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

    def _setup(self):
        self._init()
        self._novel()
        chapter = (self.project / "source/chapters/chapter_001.txt").read_text(encoding="utf-8")
        start1 = chapter.index("事件一开始")
        start2 = chapter.index("事件二开始")
        events = [
            make_event("CH001-E01", 1, start1, start1 + len("事件一开始。事件一结束。"), "事件一开始。事件一结束。"),
            make_event("CH001-E02", 1, start2, start2 + len("事件二开始。事件二结束。"), "事件二开始。事件二结束。"),
        ]
        path = self.root / "events.json"
        path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        run_cli("save-events", "--dir", str(self.project), "--file", str(path))

    def _confirm_stage(self, stage: str, content, *, capacity_decision=None, extra_meta=None) -> dict:
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        ctx = build_stage_context(self.project, stage)
        art = save_stage_artifact(
            self.project, stage=stage, content=content, stage_context=ctx, extra_meta=extra_meta
        )
        confirm_stage(
            self.project,
            stage=stage,
            version=art["version"],
            operator="test-writer",
            confirmation_ref="gates-1",
            review_override_reason="synthetic reviewed",
            capacity_decision=capacity_decision,
        )
        return art


class BatchConfirmCapacityPreflightTests(StageGatesBase):
    def _stage_chain(self, density_pressure: str) -> tuple[dict, dict, dict]:
        if not (self.project / "config.json").exists():
            self._setup()
        from scripts.stage_lifecycle import build_stage_context, confirm_stage, save_stage_artifact

        adaptation = self._confirm_stage("adaptation", "# 改编指引\n保留当前事件。\n")
        story_ctx = build_stage_context(self.project, "story_outline")
        story = save_stage_artifact(
            self.project, stage="story_outline", content="# 故事大纲\n主线。\n", stage_context=story_ctx
        )
        confirm_stage(
            self.project, stage="story_outline", version=story["version"], operator="test-writer",
            confirmation_ref="gates-so", review_override_reason="synthetic reviewed",
        )
        eo_ctx = build_stage_context(self.project, "episode_outline")
        eo = save_stage_artifact(
            self.project,
            stage="episode_outline",
            content={"episodes": [{"episode": 1}]},
            stage_context=eo_ctx,
            extra_meta={"density_reports": [{
                "episode": 1,
                "pressure": density_pressure,
                "minimum_event_seconds": 100,
                "preferred_event_seconds": 120,
                "suggested_seconds": [60, 90],
            }]},
        )
        return adaptation, story, eo

    def test_batch_rejects_missing_capacity_before_any_write(self):
        from scripts.stage_lifecycle import confirm_stages

        _, _, eo = self._stage_chain("high")
        history_path = self.project / "state" / "stage_status_history.jsonl"
        before = len(history_path.read_text(encoding="utf-8").splitlines()) if history_path.exists() else 0
        with self.assertRaises(ValueError) as ctx:
            confirm_stages(
                self.project,
                stages=["adaptation", "story_outline", "episode_outline"],
                operator="test-writer",
                confirmation_ref="gates-batch-missing",
                review_override_reason="synthetic reviewed",
            )
        self.assertIn("容量风险", str(ctx.exception))
        after = len(history_path.read_text(encoding="utf-8").splitlines())
        # 预检整体拒绝：任何阶段都不新增状态历史（无部分提交）
        self.assertEqual(after, before, "缺失容量决定时不得写入任何阶段状态")
        eo_rec = artifact_version_record(self.project, "episode_outline", None, eo["version"])
        self.assertNotEqual(eo_rec.get("status"), "approved")

    def test_batch_rejects_invalid_capacity_before_any_write(self):
        from scripts.stage_lifecycle import confirm_stages

        _, _, eo = self._stage_chain("medium")
        history_path = self.project / "state" / "stage_status_history.jsonl"
        before = len(history_path.read_text(encoding="utf-8").splitlines()) if history_path.exists() else 0
        with self.assertRaises(ValueError):
            confirm_stages(
                self.project,
                stages=["story_outline", "episode_outline"],
                operator="test-writer",
                confirmation_ref="gates-batch-invalid",
                review_override_reason="synthetic reviewed",
                capacity_decisions={"episode_outline": "bogus"},
            )
        after = len(history_path.read_text(encoding="utf-8").splitlines())
        self.assertEqual(after, before)
        self.assertNotEqual(
            artifact_version_record(self.project, "episode_outline", None, eo["version"]).get("status"),
            "approved",
        )

    def test_batch_with_capacity_decision_confirms_all(self):
        from scripts.stage_lifecycle import confirm_stages

        _, _, eo = self._stage_chain("high")
        result = confirm_stages(
            self.project,
            stages=["adaptation", "story_outline", "episode_outline"],
            operator="test-writer",
            confirmation_ref="gates-batch-ok",
            review_override_reason="synthetic reviewed",
            capacity_decisions={"episode_outline": "accept_current_plan"},
        )
        self.assertEqual(len(result["stages"]), 3)
        self.assertTrue(all(s["status"] == "approved" for s in result["stages"]))
        self.assertEqual(
            artifact_version_record(self.project, "episode_outline", None, eo["version"]).get("status"),
            "approved",
        )


class CarriedCapacityDecisionBackfillTests(StageGatesBase):
    def test_carried_episode_outline_backfills_capacity_decision(self):
        from scripts.stage_lifecycle import (
            build_stage_context,
            capacity_decision_for,
            confirm_stage,
            save_stage_artifact,
        )

        self._setup()
        self._confirm_stage("adaptation", "# 改编指引\n保留当前事件。\n")
        # story_outline 确认
        story_ctx = build_stage_context(self.project, "story_outline")
        story = save_stage_artifact(self.project, stage="story_outline", content="# 故事大纲\n主线。\n", stage_context=story_ctx)
        confirm_stage(self.project, stage="story_outline", version=story["version"], operator="test-writer",
                      confirmation_ref="gates-so", review_override_reason="synthetic reviewed")
        # episode_outline（low 密度 → not_applicable 记录）
        eo_ctx = build_stage_context(self.project, "episode_outline")
        eo_v1 = save_stage_artifact(
            self.project, stage="episode_outline", content={"episodes": [{"episode": 1}]}, stage_context=eo_ctx,
            extra_meta={"density_reports": [{"episode": 1, "pressure": "low"}]},
        )
        confirm_stage(self.project, stage="episode_outline", version=eo_v1["version"], operator="test-writer",
                      confirmation_ref="gates-eo", review_override_reason="synthetic reviewed",
                      capacity_decision="not_applicable")
        old_hash = artifact_version_record(self.project, "episode_outline", None, eo_v1["version"]).get("content_hash")
        cap_old = capacity_decision_for(self.project, outline_version=eo_v1["version"], outline_hash=old_hash or "")
        self.assertIsNotNone(cap_old)
        self.assertEqual(cap_old["decision"], "not_applicable")

        # 上游 v002 同 content_hash
        manifest = load_manifest(self.project)
        entry = manifest["artifacts"]["source_events"]
        v1 = next(r for r in entry["versions"] if r["version"] == resolve_active(self.project, "source_events")["version"])
        v2 = dict(v1)
        v2["version"] = "v002"
        entry["versions"].append(v2)
        save_manifest(self.project, manifest)
        activate_version(self.project, "source_events", "v002", operator="test")

        # 重绑同内容 → carried
        eo_v2 = save_stage_artifact(
            self.project, stage="episode_outline", content={"episodes": [{"episode": 1}]},
            stage_context=build_stage_context(self.project, "episode_outline"),
            extra_meta={"density_reports": [{"episode": 1, "pressure": "low"}]},
        )
        self.assertTrue(eo_v2.get("carried_forward"))
        new_hash = artifact_version_record(self.project, "episode_outline", None, eo_v2["version"]).get("content_hash")
        # P2-2：新版本按 (version, hash) 可追溯旧决定，且带 carried_from_version
        cap_new = capacity_decision_for(self.project, outline_version=eo_v2["version"], outline_hash=new_hash or "")
        self.assertIsNotNone(cap_new, "carried 集纲新版本必须可追溯容量决定")
        self.assertEqual(cap_new["outline_version"], eo_v2["version"])
        self.assertEqual(cap_new["decision"], "not_applicable")
        self.assertEqual(cap_new.get("carried_from_version"), eo_v1["version"])


if __name__ == "__main__":
    unittest.main()
