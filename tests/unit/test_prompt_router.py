"""Unit tests for layered prompt assembly and craft routing."""

import unittest

from scripts.prompt_router import (
    ALWAYS_MODULES,
    assemble_prompt_layers,
    genre_modules,
    load_craft_prompt,
    render_prompt_bundle,
    select_craft_modules,
)


class PromptRouterTests(unittest.TestCase):
    def test_always_modules_are_always_present(self):
        modules = select_craft_modules({"genre": ["喜剧"]}, {})
        for module in ALWAYS_MODULES:
            self.assertIn(module, modules)

    def test_genre_alias_maps_chinese_to_module(self):
        self.assertEqual(genre_modules(["甜宠", "喜剧"]), ["romance", "comedy"])

    def test_episode_function_and_operation_add_modules(self):
        modules = select_craft_modules(
            {"genre": ["悬疑"]},
            {"episode_function": ["hook", "reversal"]},
            operation="compress-without-breaking-causality",
        )
        self.assertIn("suspense", modules)
        self.assertIn("hook", modules)
        self.assertIn("reversal", modules)
        self.assertIn("compress", modules)

    def test_craft_never_loads_all(self):
        modules = select_craft_modules(
            {"genre": ["喜剧", "甜宠", "复仇", "悬疑", "家庭伦理", "男频"]},
            {"episode_function": ["hook", "reversal", "satisfaction", "abuse", "expand", "compress", "audiovisual"]},
        )
        self.assertLess(len(modules), len(ALWAYS_MODULES) + 14)

    def test_load_craft_prompt_returns_content_for_known_and_empty_for_unknown(self):
        self.assertIn("喜剧", load_craft_prompt("comedy"))
        self.assertEqual(load_craft_prompt("no-such-module"), "")

    def test_layers_include_contract_evidence_and_craft(self):
        context = {
            "episode": 1,
            "context_hash": "abc",
            "project_brief": {"drama_name": "测试", "genre": ["喜剧"]},
            "episode_outline": {"episode": 1, "must_keep": ["任务"]},
            "source_evidence": {"chapter_ids": [1], "raw_excerpts": [], "quotes": []},
            "continuity_state": {"approved_episodes": []},
            "previous_approved_script": None,
            "writer_overrides": [],
            "selected_craft_modules": ["comedy"],
        }
        layers = assemble_prompt_layers(context, role="writer", config=context["project_brief"])
        self.assertIn("episode_contract", layers["contract"])
        self.assertIn("原文证据", layers["evidence"])
        self.assertIn("喜剧", layers["craft"])
        self.assertIn("编剧最终决定权", layers["project"])

    def test_render_bundle_embeds_hash_and_no_feishu_fields(self):
        context = {
            "episode": 2,
            "context_hash": "h" * 64,
            "project_brief": {"drama_name": "测试", "genre": ["悬疑"]},
            "episode_outline": {"episode": 2, "must_keep": ["线索"]},
            "source_evidence": {"chapter_ids": [1], "raw_excerpts": [], "quotes": []},
            "continuity_state": {"approved_episodes": []},
            "previous_approved_script": None,
            "writer_overrides": [],
            "selected_craft_modules": ["suspense"],
        }
        bundle = render_prompt_bundle(context, role="writer")
        self.assertIn("context_hash", bundle)
        self.assertNotIn("表1", bundle)
        self.assertNotIn("bot_id", bundle.lower())


if __name__ == "__main__":
    unittest.main()

