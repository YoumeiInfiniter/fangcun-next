"""Unit tests for model call abstraction."""

import os
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

    def test_resolve_api_key_falls_back_to_deepseek_env(self):
        os.environ["DEEPSEEK_API_KEY"] = "sk-test-deepseek"
        try:
            self.assertEqual(resolve_api_key({}), "sk-test-deepseek")
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)

    def test_resolve_api_key_prefers_explicit_env_name(self):
        os.environ["MY_CUSTOM_KEY"] = "sk-custom"
        try:
            self.assertEqual(resolve_api_key({"api_key_env": "MY_CUSTOM_KEY"}), "sk-custom")
        finally:
            os.environ.pop("MY_CUSTOM_KEY", None)


if __name__ == "__main__":
    unittest.main()
