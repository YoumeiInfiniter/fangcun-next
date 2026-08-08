import tempfile
import unittest
from pathlib import Path

from skills.drama.tools.agent_tools import validate_script
from skills.drama.tools.script_workflow import (
    format_batch_id,
    get_draft_path,
    is_review_blocked,
    load_continuity_state,
    load_draft,
    load_review_report,
    promote_batch_to_scripts,
    save_continuity_state,
    save_draft,
    save_review_report,
    save_rewrite_attempt,
    write_batch_summary,
)


FANGCUN_ROOT = Path(__file__).resolve().parents[2]

def fangcun_file(relative_path: str) -> Path:
    return FANGCUN_ROOT / relative_path

class ScriptWorkflowTests(unittest.TestCase):
    def test_draft_is_saved_under_batch_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_draft(tmp, "batch_001", 3, "EP3 draft")

            self.assertEqual(path, Path(tmp) / "drafts" / "batch_001" / "ep_003.txt")
            self.assertEqual(load_draft(tmp, "batch_001", 3), "EP3 draft")

    def test_review_report_writes_json_and_markdown(self):
        report = {
            "verdict": "blocked",
            "severe_issues": ["缺少集末钩子"],
            "non_blocking_issues": ["对白略直白"],
            "rewrite_instructions": ["补上钩子"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = save_review_report(tmp, "batch_001", 1, report)

            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertTrue(is_review_blocked(load_review_report(tmp, "batch_001", 1)))
            self.assertIn("缺少集末钩子", md_path.read_text(encoding="utf-8"))

    def test_promote_batch_copies_drafts_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_draft(tmp, "batch_001", 1, "EP1")
            promoted = promote_batch_to_scripts(tmp, "batch_001", [1])

            self.assertEqual(promoted, [Path(tmp) / "scripts" / "ep_001.txt"])
            self.assertEqual((Path(tmp) / "scripts" / "ep_001.txt").read_text(encoding="utf-8"), "EP1")
            self.assertEqual(load_draft(tmp, "batch_001", 1), "EP1")

    def test_continuity_state_defaults_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_continuity_state(tmp), {"version": 1, "episodes": []})
            path = save_continuity_state(tmp, {"version": 1, "episodes": [{"id": 1}]})

            self.assertEqual(path, Path(tmp) / "continuity_state.json")
            self.assertEqual(load_continuity_state(tmp)["episodes"], [{"id": 1}])

    def test_batch_local_continuity_state_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_continuity_state(tmp, {"version": 1, "episodes": [{"id": 1}]}, "batch_001")

            self.assertEqual(load_continuity_state(tmp), {"version": 1, "episodes": []})
            self.assertEqual(load_continuity_state(tmp, "batch_001")["episodes"], [{"id": 1}])

    def test_rewrite_attempt_is_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_rewrite_attempt(tmp, "batch_001", 2, 1, "old blocked draft")

            self.assertEqual(path, Path(tmp) / "drafts" / "batch_001" / "rewrites" / "ep_002_attempt_01.txt")
            self.assertEqual(path.read_text(encoding="utf-8"), "old blocked draft")

    def test_batch_summary_lists_reviews_and_actions(self):
        reports = {
            1: {"verdict": "pass", "severe_issues": [], "non_blocking_issues": []},
            2: {"verdict": "warning", "severe_issues": [], "non_blocking_issues": ["节奏略慢"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_batch_summary(tmp, "batch_001", [1, 2], reports)

            text = path.read_text(encoding="utf-8")
            self.assertIn("batch_001", text)
            self.assertIn("ep_001.txt", text)
            self.assertIn("节奏略慢", text)
            self.assertIn("--confirm-draft-batch", text)

    def test_batch_id_format(self):
        self.assertEqual(format_batch_id(7), "batch_007")
        self.assertEqual(get_draft_path("out", "batch_007", 12), Path("out") / "drafts" / "batch_007" / "ep_012.txt")

    def test_tool_placeholder_output_is_blocked(self):
        content = '<tool_call name="get_planData"></tool_call>\n第11集剧本已写入，请在工作台查看。'

        issues = validate_script(content, target_words=750)

        self.assertTrue(any("工具调用占位" in issue for issue in issues))
        self.assertTrue(any(issue.startswith("严重") for issue in issues))


if __name__ == "__main__":
    unittest.main()

class ScriptPromptTests(unittest.TestCase):
    def test_script_review_prompt_requires_json_verdict(self):
        text = fangcun_file("skills/drama/prompts/script_review.md").read_text(encoding="utf-8")
        self.assertIn('"verdict"', text)
        self.assertIn('"severe_issues"', text)
        self.assertIn("blocked", text)

    def test_script_rewrite_prompt_is_targeted(self):
        text = fangcun_file("skills/drama/prompts/script_rewrite.md").read_text(encoding="utf-8")
        self.assertIn("审核报告", text)
        self.assertIn("保留", text)
        self.assertIn("严重问题", text)

    def test_continuity_prompt_keeps_structured_state(self):
        text = fangcun_file("skills/drama/prompts/continuity_update.md").read_text(encoding="utf-8")
        self.assertIn('"episodes"', text)
        self.assertIn('"open_hooks"', text)
        self.assertIn('"character_states"', text)

class ScriptDocumentationTests(unittest.TestCase):
    def test_skill_docs_describe_draft_confirmation(self):
        text = fangcun_file("skills/drama/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("drafts/", text)
        self.assertIn("--confirm-draft-batch", text)
        self.assertIn("OpenClaw", text)

    def test_decision_prompt_blocks_next_episode_on_severe_issue(self):
        text = fangcun_file("skills/drama/prompts/decision.md").read_text(encoding="utf-8")
        self.assertIn("current episode must pass", text)
        self.assertIn("must not generate the next episode", text)

    def test_script_writer_mentions_draft_first_output(self):
        text = fangcun_file("agents/script-writer.md").read_text(encoding="utf-8")
        self.assertIn("draft", text)
        self.assertIn("severe issues", text)

    def test_script_prompt_for_local_file_mode_forbids_workbench_confirmation(self):
        text = fangcun_file("skills/drama/prompts/script_local.md").read_text(encoding="utf-8")
        self.assertIn("OpenClaw 本地文件模式", text)
        self.assertIn("只输出 `<scriptItem>...</scriptItem>`", text)
        self.assertNotIn("完成写入后返回一句确认", text)
        self.assertNotIn("确认格式示例", text)
        self.assertIn("禁止拆成单独的 `1-1` + `场：场景-夜-内`", text)

    def test_native_script_prompt_keeps_toonflow_workbench_semantics(self):
        text = fangcun_file("skills/drama/prompts/script.md").read_text(encoding="utf-8")
        self.assertIn("get_planData", text)
        self.assertIn("get_novel_events", text)
        self.assertIn("完成写入后返回一句确认", text)
        self.assertIn("请在工作台查看", text)
