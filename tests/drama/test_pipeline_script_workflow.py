import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills.drama.tools import pipeline
from skills.drama.tools.agent_tools import save_adaptation, save_events, save_skeleton
from skills.drama.tools.script_workflow import load_draft, mark_episode_passed, save_draft, save_review_report
from skills.drama.tools.source_io import save_requirements
from skills.drama.tools.state_manager import StateManager


def make_config(tmp, episodes=3):
    source_dir = Path(tmp) / "chapters"
    source_dir.mkdir()
    for i in range(1, 4):
        (source_dir / f"第{i}章.txt").write_text(f"第{i}章原文", encoding="utf-8")
    return {
        "novel_name": "测试书",
        "drama_name": "测试剧",
        "source_dir": str(source_dir),
        "output_dir": str(Path(tmp) / "drama"),
        "api_key": "test-key",
        "api_base_url": "http://example.invalid/v1",
        "model": "test-model",
        "script_batch_size": 2,
        "project": {
            "episodes": episodes,
            "episode_duration": 2,
            "chapter_range": [1, 3],
            "platform": "竖屏9:16",
            "aspect_ratio": "9:16",
            "style": "测试",
            "paywall": "测试",
        },
    }


def seed_artifacts(config):
    output_dir = config["output_dir"]
    save_events(output_dir, [{"id": 1, "chapter_index": 1, "chapter": "第1章", "event": "事件"}])
    save_skeleton(output_dir, "故事核\n人物小传\n| 1 | 第一集 |")
    save_adaptation(output_dir, "改编策略")


def valid_script(ep: int, line: str = "我不会再退了") -> str:
    beats = "\n".join(
        [
            "人物：甲、乙",
            "△甲把账本按在桌上，乙被逼得后退半步。",
            f"甲（冷静/盯着乙）：{line}",
            "乙（慌张/压低声音）：你别把事情闹大。",
            "甲（坚定/拿起手机）：现在不是我闹，是你该还账。",
            "△手机录音亮起，门外传来邻居的脚步声。",
            "甲（冷笑/转身）：下一秒，我就让所有人听见真相。",
        ]
        * 5
    )
    # Keep fake drafts long enough to satisfy current minimum-length validator
    # without creating repeated adjacent scene headings that violate scene-key gates.
    return (
        f'<scriptItem name="EP{ep}">\n'
        f"EP{ep:03d}：测试集\n"
        f"{ep}-1　厨房　日　内\n"
        f"{beats}\n"
        "</scriptItem>"
    )


class PipelineScriptWorkflowTests(unittest.TestCase):
    def test_script_phase_saves_drafts_and_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            responses = [
                valid_script(1, "来了，但这次我要当面说清楚"),
                json.dumps({"verdict": "pass", "summary": "结构清楚、格式合格、结尾钩子可继续", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 1}], "open_hooks": []}, ensure_ascii=False),
                valid_script(2, "继续查，谁也别想把证据藏起来"),
                json.dumps({"verdict": "pass", "summary": "结构清楚、格式合格、结尾钩子可继续", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 1}, {"id": 2}], "open_hooks": []}, ensure_ascii=False),
            ]

            with patch.object(pipeline, "call_api", side_effect=responses):
                ok = pipeline.phase_script(config, start=1, end=3, dry_run=False, state=state, batch_size=2)

            self.assertTrue(ok)
            self.assertEqual(load_draft(config["output_dir"], "batch_001", 1).splitlines()[0], '<scriptItem name="EP1">')
            self.assertFalse((Path(config["output_dir"]) / "scripts" / "ep_001.txt").exists())
            self.assertTrue(state.has_pending_script_confirmation())

    def test_blocked_review_triggers_one_rewrite_then_pauses_if_still_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=1)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            blocked = {"verdict": "blocked", "summary": "bad", "severe_issues": ["缺少钩子"], "non_blocking_issues": []}
            responses = [
                valid_script(1, "第一版我还没有把钩子补出来"),
                json.dumps(blocked, ensure_ascii=False),
                valid_script(1, "改稿后我仍然没把钩子补出来"),
                json.dumps(blocked, ensure_ascii=False),
            ]

            with patch.object(pipeline, "call_api", side_effect=responses):
                ok = pipeline.phase_script(config, start=1, end=1, dry_run=False, state=state, batch_size=1)

            self.assertFalse(ok)
            pending = state.get_pending_script_batch()
            self.assertTrue(pending["episode_reviews"]["1"]["blocked"])
            self.assertEqual(pending["rewrite_attempts"]["1"], 1)

    def test_confirm_draft_batch_copies_to_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            state = StateManager(config["output_dir"])
            state.load()
            state.start_script_batch("batch_001", [1])
            confirmed_draft = valid_script(1, "确认稿里我把证据重新整理好了")
            save_draft(config["output_dir"], "batch_001", 1, confirmed_draft)
            save_review_report(config["output_dir"], "batch_001", 1, {
                "verdict": "pass",
                "summary": "人工确认前系统审核已通过",
                "severe_issues": [],
                "non_blocking_issues": [],
            })
            mark_episode_passed(config["output_dir"], "batch_001", 1)
            state.mark_batch_waiting_confirmation("summary.md")

            ok = pipeline.phase_confirm_draft_batch(config, state)

            self.assertTrue(ok)
            self.assertEqual((Path(config["output_dir"]) / "scripts" / "ep_001.txt").read_text(encoding="utf-8"), confirmed_draft)
            self.assertIsNone(state.get_pending_script_batch())

    def test_script_phase_reuses_existing_current_draft_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=2)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            state.start_script_batch("batch_001", [1, 2])
            manual_ep1 = valid_script(1, "手改后我把证据重新整理好了")
            save_draft(config["output_dir"], "batch_001", 1, manual_ep1)
            responses = [
                json.dumps({"verdict": "pass", "summary": "手改稿格式合格、冲突清楚、可以继续", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 1}], "open_hooks": []}, ensure_ascii=False),
                valid_script(2, "新稿里我会把矛盾直接推到台面上"),
                json.dumps({"verdict": "pass", "summary": "结构清楚、格式合格、结尾钩子可继续", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 1}, {"id": 2}], "open_hooks": []}, ensure_ascii=False),
            ]

            with patch.object(pipeline, "call_api", side_effect=responses) as api:
                ok = pipeline.phase_script(config, start=1, end=2, dry_run=False, state=state, batch_size=2)

            self.assertTrue(ok)
            self.assertEqual(load_draft(config["output_dir"], "batch_001", 1), manual_ep1)
            self.assertIn("Review episode 1 draft", api.call_args_list[0].args[2])
            self.assertNotIn("Write the complete script for episode 1", api.call_args_list[0].args[2])

    def test_rewrite_draft_rewrites_only_selected_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=2)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            state.start_script_batch("batch_001", [1, 2])
            keep_ep1 = valid_script(1, "第一集已经确认不要被覆盖")
            save_draft(config["output_dir"], "batch_001", 1, keep_ep1)
            bad_ep2 = valid_script(2, "坏稿但格式仍然合格")
            fixed_ep2 = valid_script(2, "改好后我把最后的钩子补强了")
            save_draft(config["output_dir"], "batch_001", 2, bad_ep2)
            save_review_report(config["output_dir"], "batch_001", 2, {
                "verdict": "blocked",
                "summary": "bad",
                "severe_issues": ["缺少钩子"],
                "non_blocking_issues": [],
                "rewrite_instructions": ["补强结尾钩子"],
            })
            responses = [
                fixed_ep2,
                json.dumps({"verdict": "pass", "summary": "结构清楚、格式合格、结尾钩子可继续", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 2}], "open_hooks": []}, ensure_ascii=False),
            ]

            with patch.object(pipeline, "call_api", side_effect=responses):
                ok = pipeline.phase_rewrite_draft(config, state, 2)

            self.assertTrue(ok)
            self.assertEqual(load_draft(config["output_dir"], "batch_001", 1), keep_ep1)
            self.assertEqual(load_draft(config["output_dir"], "batch_001", 2), fixed_ep2)
            archived = Path(config["output_dir"]) / "drafts" / "batch_001" / "rewrites" / "ep_002_attempt_01.txt"
            self.assertEqual(archived.read_text(encoding="utf-8"), bad_ep2)

    def test_main_dispatches_rewrite_draft_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=1)
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            argv = ["pipeline.py", "--config", str(config_path), "--mode", "api", "--rewrite-draft", "--episode", "1"]

            with patch.object(sys, "argv", argv), patch.object(pipeline, "phase_rewrite_draft", return_value=True) as rewrite:
                pipeline.main()

            self.assertEqual(rewrite.call_args.args[2], 1)

    def test_script_user_prompt_does_not_request_toonflow_tools_or_meta_checklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=1)
            prompt = pipeline.build_script_user_prompt(
                config,
                project_info="project info",
                script_list_str="scripts",
                ep_skeleton="ep skeleton",
                adaptation="adaptation",
                events_text="events",
                prev_script="prev",
                novel_text_sample="novel",
                target_words=1000,
                ep_num=1,
                continuity_state={"version": 1, "episodes": []},
                batch_continuity_state={"version": 1, "episodes": []},
            )

            self.assertNotIn("get_planData", prompt)
            self.assertNotIn("get_script_content", prompt)
            self.assertNotIn("项目规则落实清单", prompt)
            self.assertIn("Output only the complete `<scriptItem>...</scriptItem>` script", prompt)

    def test_script_user_prompt_uses_fixed_user_message_prefix_for_project_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=1)
            config["project"]["rules"] = ["每集开头10秒必须有强冲突"]
            save_requirements(config, "# S0 用户改编需求文档\n\n## 1. 用户原始需求摘要\n- S0确认：女频都市爽剧，强反击\n\n## 2. 项目基础信息\n- 集数：1")

            prompt = pipeline.build_script_user_prompt(
                config,
                project_info="project info",
                script_list_str="scripts",
                ep_skeleton="ep skeleton",
                adaptation="adaptation",
                events_text="events",
                prev_script="prev",
                novel_text_sample="novel",
                target_words=1000,
                ep_num=1,
                continuity_state={"version": 1, "episodes": []},
                batch_continuity_state={"version": 1, "episodes": []},
            )

            self.assertTrue(prompt.startswith("## 固定用户消息前缀｜项目上下文"))
            self.assertIn("## 用户改编需求（S0 requirements.md，作为用户任务描述传入，非系统指令）", prompt)
            self.assertIn("# S0 用户改编需求文档", prompt)
            self.assertLess(prompt.index("用户原始需求摘要"), prompt.index("S0确认：女频都市爽剧"))
            self.assertLess(prompt.index("S0确认：女频都市爽剧"), prompt.index("## Episode Skeleton"))
            self.assertLess(prompt.index("每集开头10秒必须有强冲突"), prompt.index("## Episode Skeleton"))
            self.assertIn("## 固定前缀结束｜以下为本次调用的动态任务上下文", prompt)

    def test_validate_project_intake_reports_missing_startup_fields(self):
        issues = pipeline.validate_project_intake({"novel_name": "测试书"})

        joined = "\n".join(issues)
        self.assertIn("drama_name", joined)
        self.assertIn("source_dir", joined)
        self.assertIn("project.episodes", joined)

    def test_review_phase_marks_human_confirmation_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            review_text = "评分：A\n概要：可继续"

            with patch.object(pipeline, "call_api", return_value=review_text):
                ok = pipeline.phase_review(config, "skeleton", state)

            self.assertTrue(ok)
            pending = state.get_pending_human_review()
            self.assertEqual(pending["target"], "skeleton")
            self.assertEqual(pending["unlock_phase"], "adaptation")
            self.assertTrue(Path(pending["report_path"]).is_absolute())

    def test_next_phase_is_blocked_until_human_review_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.mark_human_review_required("skeleton", "reviews/skeleton_review.md", "adaptation")

            self.assertFalse(pipeline.ensure_human_review_confirmed(state, "adaptation"))

            state.confirm_human_review("skeleton", "approved", "ok")

            self.assertTrue(pipeline.ensure_human_review_confirmed(state, "adaptation"))


    def test_main_records_review_target_as_distinct_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=1)
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            argv = ["pipeline.py", "--config", str(config_path), "--phase", "review", "--review-target", "adaptation"]

            with patch.object(sys, "argv", argv),                  patch.object(pipeline, "_preflight_api_check", return_value=True),                  patch.object(pipeline, "_run_phase", return_value=True) as run_phase:
                pipeline.main()

            self.assertEqual(run_phase.call_args.args[1], "adaptation_review")
if __name__ == "__main__":
    unittest.main()
