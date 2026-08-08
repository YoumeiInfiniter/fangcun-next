"""Unit tests for model call abstraction."""

import unittest

from scripts.model_adapter import (
    ModelUnavailableError,
    build_payload,
    resolve_api_key,
)


class ModelAdapterTests(unittest.TestCase):
    def test_resolve_api_key_raises_without_env(self):
        with self.assertRaises(ModelUnavailableError):
            resolve_api_key({})

    def test_build_payload_uses_model_config(self):
        payload = build_payload(
            system_prompt="s",
            user_context="u",
            model_config={"model": "test-model"},
        )
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["messages"][0]["content"], "s")
        self.assertEqual(payload["messages"][1]["content"], "u")

    def test_build_payload_defaults_model(self):
        payload = build_payload(system_prompt="s", user_context="u", model_config=None)
        self.assertTrue(payload["model"])


if __name__ == "__main__":
    unittest.main()
