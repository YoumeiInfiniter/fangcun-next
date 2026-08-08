"""Multi-genre smoke tests (spec §25.3).

Scenarios:
1. comedy/romance opening episode;
2. suspense information-gap episode;
3. late episode depending on approved continuity.

Every scenario runs the local deterministic loop (context → draft → review →
approve → continuity) with no API and asserts genre modules differ while the
generic baseline holds.
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.continuity_manager import apply_approved_script
from scripts.context_builder import build_episode_context, verify_context_hash
from scripts.duration_estimator import estimate_episode_seconds
from scripts.prompt_router import render_prompt_bundle
from scripts.script_validator import validate_script
from scripts.source_ingest import ingest_novel
from scripts.state_store import init_project, load_continuity, record_artifact


def make_project(tmp: Path, project_id: str, genre: list[str], episodes: list[dict]) -> Path:
    project_dir = tmp / "projects" / project_id
    init_project(
        project_dir,
        {
            "project_id": project_id,
            "novel_name": "冒烟小说",
            "drama_name": "冒烟短剧",
            "platform": "竖屏短剧",
            "aspect_ratio": "9:16",
            "genre": genre,
            "initial_episode_count": len(episodes),
            "minimum_episode_seconds": 60,
            "preferred_episode_seconds": [90, 130],
            "script_format": "default-cn",
            "fidelity": "medium",
            "dialogue_policy": "prefer_original",
            "writer_has_final_authority": True,
        },
    )
    novel = tmp / f"{project_id}.txt"
    novel.write_text("第一章 开场\n系统出现，规则建立。\n第二章 冲突\n主角依据已知信息行动。\n", encoding="utf-8")
    ingest_novel(project_dir, novel)
    events = [
        {
            "event_id": "CH001-E01",
            "chapter_id": 1,
            "event": "规则建立",
            "importance": "mainline",
            "key_quotes": [{"speaker": "系统", "text": "规则只有一次说明机会。"}],
        }
    ]
    events_path = project_dir / "artifacts" / "source_events" / "events.json"
    events_path.parent.mkdir(parents=True)
    events_path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    record_artifact(project_dir, "source_events", events_path, source="ai", status="approved")
    outlines_path = project_dir / "artifacts" / "episode_outline" / "episode_outlines.json"
    outlines_path.parent.mkdir(parents=True)
    outlines_path.write_text(json.dumps({"episodes": episodes}, ensure_ascii=False), encoding="utf-8")
    record_artifact(project_dir, "episode_outline", outlines_path, source="ai", status="approved")
    return project_dir


def base_outline(episode: int, title: str, function: list[str], must_keep: list[str]) -> dict:
    return {
        "episode": episode,
        "title": title,
        "source_event_ids": ["CH001-E01"],
        "source_chapters": [1],
        "opening_bridge": "承接上一集",
        "episode_goal": "推进本集目标",
        "must_keep": must_keep,
        "causal_chains": [["刺激", "回应", "反应"]],
        "knowledge_at_start": {},
        "knowledge_at_end": {},
        "ending_hook": "集末钩子",
        "suggested_seconds": [90, 130],
        "episode_function": function,
    }


def valid_script(episode: int, title: str, speaker: str = "主角") -> str:
    return f"""第{episode}集：{title}

{episode}-1 家 夜 内
人物：{speaker}、系统

△{speaker}依据已知信息行动。
{speaker}：规则只有一次说明机会？
系统：是的。
△反应成立，集末钩子出现。
"""


class MultiGenreSmokeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_loop(self, project_dir: Path, episode: int, title: str) -> dict:
        context = build_episode_context(project_dir, episode)
        ok, _ = verify_context_hash(context)
        self.assertTrue(ok)
        script = valid_script(episode, title)
        report = validate_script(script, expected_episode=episode)
        self.assertTrue(report["ok"], report["errors"])
        timing = estimate_episode_seconds(script)
        self.assertFalse(timing["blocking"])
        apply_approved_script(project_dir, episode, script, source="smoke")
        continuity = load_continuity(project_dir)
        self.assertIn(episode, continuity["approved_episodes"])
        bundle = render_prompt_bundle(context, role="writer", config=context["project_brief"])
        return {"context": context, "timing": timing, "bundle": bundle}

    def test_comedy_romance_opening(self):
        outline = base_outline(1, "甜宠开篇", ["opening", "hook"], ["规则建立"])
        project_dir = make_project(self.tmp, "smoke-comedy", ["喜剧", "甜宠"], [outline])
        result = self._run_loop(project_dir, 1, "甜宠开篇")
        modules = result["context"]["selected_craft_modules"]
        self.assertIn("comedy", modules)
        self.assertIn("romance", modules)
        self.assertIn("hook", modules)
        self.assertNotIn("suspense", modules)
        self.assertNotIn("reversal", modules)

    def test_suspense_information_gap(self):
        outline = base_outline(1, "谁在说谎", ["rule-reveal", "reversal"], ["规则建立"])
        project_dir = make_project(self.tmp, "smoke-suspense", ["悬疑"], [outline])
        result = self._run_loop(project_dir, 1, "谁在说谎")
        modules = result["context"]["selected_craft_modules"]
        self.assertIn("suspense", modules)
        self.assertIn("reversal", modules)
        self.assertNotIn("comedy", modules)
        self.assertNotIn("romance", modules)

    def test_late_episode_depends_on_continuity(self):
        outlines = [
            base_outline(1, "第一集", ["opening"], ["规则建立"]),
            base_outline(2, "第二集", ["hook"], ["规则建立"]),
            base_outline(3, "第三集", ["reversal"], ["规则建立"]),
            base_outline(4, "后段集", ["satisfaction"], ["规则建立"]),
        ]
        project_dir = make_project(self.tmp, "smoke-continuity", ["家庭伦理", "悬疑"], outlines)
        for episode in (1, 2, 3):
            self._run_loop(project_dir, episode, f"第{episode}集")
        result = self._run_loop(project_dir, 4, "后段集")
        context = result["context"]
        self.assertEqual(context["continuity_state"]["approved_episodes"], [1, 2, 3])
        self.assertIsNotNone(context["previous_approved_script"])
        self.assertIn("第3集", context["previous_approved_script"])
        modules = context["selected_craft_modules"]
        self.assertIn("family", modules)
        self.assertIn("suspense", modules)
        self.assertIn("satisfaction", modules)
        self.assertNotIn("comedy", modules)

    def test_generic_baseline_holds_across_genres(self):
        """All genres keep the four always-on baseline modules."""
        for project_id, genre, outline in [
            ("smoke-base-comedy", ["喜剧"], base_outline(1, "喜", ["opening"], ["规则建立"])),
            ("smoke-base-suspense", ["悬疑"], base_outline(1, "悬", ["reversal"], ["规则建立"])),
            ("smoke-base-family", ["家庭伦理"], base_outline(1, "家", ["hook"], ["规则建立"])),
        ]:
            with self.subTest(project_id=project_id):
                project_dir = make_project(self.tmp, project_id, genre, [outline])
                context = build_episode_context(project_dir, 1)
                modules = context["selected_craft_modules"]
                for always in ("source-fidelity", "causality", "knowledge-state", "screenplay-format"):
                    self.assertIn(always, modules)


if __name__ == "__main__":
    unittest.main()
