"""Unit tests for shared runtime utilities."""

import unittest

from scripts.common import slugify, stable_hash, strip_code_fence


class CommonTests(unittest.TestCase):
    def test_strip_code_fence_removes_text_fence(self):
        text = "```text\n第1集：测试\n\n1-1 家 夜 内\n△动作。\n```"
        self.assertEqual(strip_code_fence(text), "第1集：测试\n\n1-1 家 夜 内\n△动作。")

    def test_strip_code_fence_ignores_plain_text(self):
        text = "第1集：测试\n"
        self.assertEqual(strip_code_fence(text), text)

    def test_slugify_safe_characters(self):
        self.assertEqual(slugify("错位婚约 Demo!"), "错位婚约-Demo")
        self.assertEqual(slugify(""), "project")

    def test_stable_hash_is_deterministic(self):
        self.assertEqual(stable_hash({"a": 1}), stable_hash({"a": 1}))
        self.assertNotEqual(stable_hash({"a": 1}), stable_hash({"a": 2}))


if __name__ == "__main__":
    unittest.main()
