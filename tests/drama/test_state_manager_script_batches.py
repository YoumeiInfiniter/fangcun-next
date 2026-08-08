import tempfile
import unittest

from skills.drama.tools.state_manager import StateManager


class ScriptBatchStateTests(unittest.TestCase):
    def test_start_script_batch_records_pending_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1, 2])

            pending = state.get_pending_script_batch()
            self.assertEqual(pending["batch_id"], "batch_001")
            self.assertEqual(pending["episodes"], [1, 2])
            self.assertFalse(pending["awaiting_confirmation"])

    def test_review_status_blocks_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1])
            state.set_episode_review(1, "blocked", True, 2)

            episode = state.get_pending_script_batch()["episode_reviews"]["1"]
            self.assertTrue(episode["blocked"])
            self.assertEqual(episode["severe_count"], 2)

    def test_rewrite_attempt_counter_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1])

            self.assertEqual(state.mark_episode_rewrite_attempt(1), 1)
            self.assertEqual(state.mark_episode_rewrite_attempt(1), 2)

    def test_waiting_confirmation_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1, 2])
            state.mark_batch_waiting_confirmation("drafts/batch_001/batch_summary.md")

            self.assertTrue(state.has_pending_script_confirmation())
            self.assertEqual(state.get_resume_phase(), "script_confirmation")

    def test_confirm_batch_clears_pending_batch_and_records_promoted_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1])
            state.mark_batch_waiting_confirmation("summary.md")
            state.confirm_script_batch(["scripts/ep_001.txt"])

            self.assertIsNone(state.get_pending_script_batch())
            self.assertEqual(state.state["script_batches"]["confirmed"][-1]["promoted_paths"], ["scripts/ep_001.txt"])

    def test_human_review_gate_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.mark_human_review_required("skeleton", "reviews/skeleton_review.md", "adaptation")

            pending = state.get_pending_human_review()
            self.assertEqual(pending["target"], "skeleton")
            self.assertEqual(pending["unlock_phase"], "adaptation")
            self.assertTrue(state.has_pending_human_review())
            self.assertEqual(state.get_resume_phase(), "human_review_confirmation")

            state.confirm_human_review("skeleton", "approved", "人工确认通过")

            self.assertFalse(state.has_pending_human_review())
            self.assertEqual(state.state["human_reviews"]["confirmed"][-1]["target"], "skeleton")
if __name__ == "__main__":
    unittest.main()
