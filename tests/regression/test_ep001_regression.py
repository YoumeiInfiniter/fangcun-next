"""EP001 generic regression tests (spec §25.2)."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.script_validator import validate_script
from tests.regression.ep001_checks import run_ep001_checks


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ep001"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class Ep001RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.buggy = fixture("script_buggy.txt")
        cls.fixed = fixture("script_fixed.txt")
        cls.outline = json.loads(fixture("episode_outline.json"))
        cls.events = json.loads(fixture("events.json"))
        cls.review = json.loads(fixture("review_report.json"))

    def test_buggy_version_detected_by_all_generic_checks(self):
        results = run_ep001_checks(self.buggy)
        self.assertGreaterEqual(sum(1 for r in results if not r["ok"]), 4)

    def test_fixed_version_passes_all_generic_checks(self):
        results = run_ep001_checks(self.fixed)
        failures = [r for r in results if not r["ok"]]
        self.assertEqual(failures, [], failures)

    def test_both_versions_are_format_parseable(self):
        self.assertTrue(validate_script(self.buggy)["ok"])
        self.assertTrue(validate_script(self.fixed)["ok"])

    def test_reviewer_report_cites_source_evidence_for_errors(self):
        from scripts.schema_validate import validate

        ok, errors = validate(self.review, "review-report.schema.json")
        self.assertTrue(ok, errors)
        for issue in self.review["issues"]:
            self.assertTrue(issue.get("source_evidence"), issue["id"])

    def test_context_builder_exposes_evidence_for_ep001(self):
        import scripts.context_builder as cb
        import scripts.source_ingest as si
        import scripts.state_store as ss

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            ss.init_project(
                project_dir,
                {
                    "project_id": "ep001-reg",
                    "novel_name": "测试书",
                    "drama_name": "测试剧",
                    "platform": "竖屏",
                    "genre": ["喜剧", "甜宠"],
                    "script_format": "default-cn",
                    "writer_has_final_authority": True,
                },
            )
            novel = Path(tmp) / "novel.md"
            novel.write_text(fixture("novel_excerpt.md"), encoding="utf-8")
            si.ingest_novel(project_dir, novel)
            events_path = project_dir / "artifacts" / "source_events" / "events.json"
            events_path.parent.mkdir(parents=True)
            events_path.write_text(fixture("events.json"), encoding="utf-8")
            ss.record_artifact(project_dir, "source_events", events_path, source="ai", status="approved")
            outlines_path = project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
            outlines_path.parent.mkdir(parents=True)
            outlines_path.write_text(json.dumps({"episodes": [self.outline]}, ensure_ascii=False), encoding="utf-8")
            ss.record_artifact(project_dir, "episode_outline", outlines_path, source="ai", status="approved")

            context = cb.build_episode_context(project_dir, 1)
            excerpt_text = "\n".join(ex["text"] for ex in context["source_evidence"]["raw_excerpts"])
            self.assertIn("吃不完的苦", excerpt_text)
            self.assertIn("你有本事就劈死我", excerpt_text)
            self.assertIn("绑错惩罚对象", excerpt_text)
            ok, _ = cb.verify_context_hash(context)
            self.assertTrue(ok)

    def test_rewriter_bundle_keeps_same_context_and_evidence(self):
        import scripts.context_builder as cb
        import scripts.prompt_router as pr
        import scripts.source_ingest as si
        import scripts.state_store as ss

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            ss.init_project(
                project_dir,
                {
                    "project_id": "ep001-rw",
                    "novel_name": "测试书",
                    "drama_name": "测试剧",
                    "platform": "竖屏",
                    "genre": ["喜剧"],
                    "script_format": "default-cn",
                    "writer_has_final_authority": True,
                },
            )
            novel = Path(tmp) / "novel.md"
            novel.write_text(fixture("novel_excerpt.md"), encoding="utf-8")
            si.ingest_novel(project_dir, novel)
            events_path = project_dir / "artifacts" / "source_events" / "events.json"
            events_path.parent.mkdir(parents=True)
            events_path.write_text(fixture("events.json"), encoding="utf-8")
            ss.record_artifact(project_dir, "source_events", events_path, source="ai", status="approved")
            outlines_path = project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
            outlines_path.parent.mkdir(parents=True)
            outlines_path.write_text(json.dumps({"episodes": [self.outline]}, ensure_ascii=False), encoding="utf-8")
            ss.record_artifact(project_dir, "episode_outline", outlines_path, source="ai", status="approved")
            context = cb.build_episode_context(project_dir, 1)
            review_ctx = {**context, "script_draft": self.buggy, "review_report": self.review}
            bundle = pr.render_prompt_bundle(review_ctx, role="rewriter", config=context["project_brief"])
            self.assertIn(context["context_hash"], bundle)
            self.assertIn("吃不完的苦", bundle)
            self.assertIn("你有本事就劈死我", bundle)
            self.assertIn("DIALOGUE-001", bundle)


if __name__ == "__main__":
    unittest.main()
