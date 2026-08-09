"""Unit tests for advisory capacity estimation."""

import tempfile
import unittest
from pathlib import Path

from scripts.capacity_estimator import compute_forecast, save_forecast
from scripts.state_store import active_artifact_path, init_project, record_artifact


def make_events(count=40) -> list[dict]:
    return [
        {
            "event_id": f"E{i:03d}",
            "chapter_id": 1,
            "event": f"事件{i}",
            "importance": "mainline" if i % 3 else "subline",
            "minimum_screen_seconds": 20,
            "preferred_screen_seconds": 35,
        }
        for i in range(1, count + 1)
    ]


class CapacityEstimatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name) / "project"
        init_project(
            self.project_dir,
            {
                "project_id": "cap-test",
                "novel_name": "n",
                "drama_name": "d",
                "platform": "p",
                "genre": ["悬疑"],
                "initial_episode_count": 30,
                "minimum_episode_seconds": 60,
                "minimum_total_seconds": 1800,
                "reach_original_ending": True,
                "writer_has_final_authority": True,
            },
        )
        events_path = self.project_dir / "artifacts" / "source_events" / "events.json"
        events_path.parent.mkdir(parents=True)
        events_path.write_text(__import__("json").dumps(make_events(), ensure_ascii=False), encoding="utf-8")
        record_artifact(self.project_dir, "source_events", events_path, source="ai", status="approved")

    def tearDown(self):
        self._tmp.cleanup()

    def test_forecast_has_ranges_options_and_advisory_flag(self):
        forecast = compute_forecast(
            {"initial_episode_count": 30, "minimum_episode_seconds": 60, "minimum_total_seconds": 1800, "reach_original_ending": True},
            make_events(),
        )
        self.assertTrue(forecast["advisory_only"])
        self.assertGreaterEqual(len(forecast["options"]), 2)
        self.assertTrue(forecast["recommended"])
        self.assertIn(forecast["pressure"], ("low", "medium", "high"))
        self.assertIn(forecast["forecast"]["confidence"], ("low", "medium", "high"))

    def test_missing_preferred_seconds_lowers_confidence(self):
        events = make_events()
        for event in events:
            event.pop("preferred_screen_seconds", None)
        forecast = compute_forecast(
            {"initial_episode_count": 30, "minimum_episode_seconds": 60, "minimum_total_seconds": 1800, "reach_original_ending": True},
            events,
        )
        self.assertEqual(forecast["forecast"]["confidence"], "low")

    def test_pressure_high_when_capacity_small(self):
        forecast = compute_forecast(
            {"initial_episode_count": 5, "minimum_episode_seconds": 60, "minimum_total_seconds": 300},
            make_events(),
        )
        self.assertEqual(forecast["pressure"], "high")

    def test_pressure_low_when_capacity_ample(self):
        forecast = compute_forecast(
            {"initial_episode_count": 100, "minimum_episode_seconds": 60, "minimum_total_seconds": 6000},
            make_events(10),
        )
        self.assertEqual(forecast["pressure"], "low")

    def test_save_forecast_persists_json_and_markdown(self):
        forecast = save_forecast(self.project_dir)
        path = active_artifact_path(self.project_dir, "capacity_forecast")
        self.assertIsNotNone(path)
        md = active_artifact_path(self.project_dir, "capacity_forecast_md")
        self.assertTrue(md.exists())
        self.assertIn("不阻断", md.read_text(encoding="utf-8"))
        self.assertEqual(forecast["advisory_only"], True)


if __name__ == "__main__":
    unittest.main()
