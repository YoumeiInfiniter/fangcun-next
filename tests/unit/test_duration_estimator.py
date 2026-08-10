"""Unit tests for advisory duration estimation."""

import unittest

from scripts.duration_estimator import (
    DEFAULT_DIALOGUE_CPM,
    compute_draft_metrics,
    estimate_episode_seconds,
    forecast_duration,
    render_duration_report,
)


SCRIPT = """第1集：测试

1-1 家 夜 内
人物：A、B

△A进门。
A：你好。
B：你好，你来了？
△两人坐下。
"""


class DurationEstimatorTests(unittest.TestCase):
    def test_metrics_are_separate(self):
        est = estimate_episode_seconds(SCRIPT)
        self.assertGreater(est["dialogue_chars"], 0)
        self.assertGreater(est["action_lines"], 0)
        self.assertNotEqual(est["dialogue_chars"], est["action_chars"])
        self.assertFalse(est["blocking"])
        self.assertGreater(est["estimated_seconds"], 0)

    def test_estimated_range_is_advisory(self):
        est = estimate_episode_seconds(SCRIPT, dialogue_chars_per_minute=150)
        self.assertLess(est["estimated_range"][0], est["estimated_range"][1])

    def test_below_minimum_is_reminder_not_block(self):
        forecast = forecast_duration({"minimum_episode_seconds": 600}, [(1, SCRIPT)])
        self.assertTrue(forecast["per_episode"][0]["below_minimum"])
        self.assertFalse(forecast["per_episode"][0]["blocking"])
        self.assertTrue(forecast["advisory_only"])

    def test_total_forecast_sums_episodes(self):
        forecast = forecast_duration({}, [(1, SCRIPT), (2, SCRIPT.replace("第1集", "第2集").replace("1-1", "2-1"))])
        self.assertEqual(len(forecast["per_episode"]), 2)
        total = sum(e["estimated_seconds"] for e in forecast["per_episode"])
        self.assertAlmostEqual(forecast["total_estimated_seconds"], total, places=1)

    def test_no_hardcoded_total_chars_per_minute(self):
        forecast = forecast_duration({"advisory_timing": {"script_total_chars_per_minute_hint": None}}, [(1, SCRIPT)])
        self.assertIsNone(forecast["script_total_chars_per_minute_hint"])
        self.assertEqual(forecast["dialogue_chars_per_minute"], DEFAULT_DIALOGUE_CPM)

    def test_report_is_renderable(self):
        forecast = forecast_duration({"preferred_episode_seconds": [90, 120]}, [(1, SCRIPT)])
        report = render_duration_report(forecast)
        self.assertIn("仅提示，不阻断", report)
        self.assertIn("第1集", report)

    def test_draft_metrics_bound_and_deviation_above(self):
        metrics = compute_draft_metrics(
            SCRIPT,
            episode=1,
            context_hash="c" * 64,
            draft_version="v001",
            draft_hash="d" * 64,
            preferred_seconds=[1, 2],
        )
        self.assertEqual(metrics["draft_version"], "v001")
        self.assertEqual(metrics["draft_hash"], "d" * 64)
        self.assertEqual(metrics["deviation"], "above")
        self.assertFalse(metrics["blocking"])
        self.assertEqual(metrics["source"], "system")


if __name__ == "__main__":
    unittest.main()
