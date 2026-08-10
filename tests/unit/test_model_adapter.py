"""Unit tests for model call abstraction."""

import os
import unittest
from unittest import mock

from scripts.model_adapter import (
    ModelUnavailableError,
    build_payload,
    call_generate,
    parse_json_response,
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

    def test_build_payload_supports_deepseek_output_params(self):
        payload = build_payload(
            system_prompt="s",
            user_context="u",
            model_config={
                "model": "deepseek-v4-flash",
                "output_token_param": "max_completion_tokens",
                "max_output_tokens": 16000,
                "disable_thinking": True,
            },
        )
        self.assertEqual(payload["max_completion_tokens"], 16000)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_parse_json_response_handles_code_fence_and_wrapper(self):
        data = parse_json_response('```json\n{"review_report": {"verdict": "pass"}}\n```')
        self.assertEqual(data["review_report"]["verdict"], "pass")
        data2 = parse_json_response('前置说明 {"episode": 1} 后置说明')
        self.assertEqual(data2["episode"], 1)

    def test_parse_json_response_raises_on_invalid(self):
        with self.assertRaises(ValueError):
            parse_json_response("这不是 JSON")

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

    def test_call_generate_fails_honestly_on_finish_reason_length(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": "不完整的 JSON"},
                        }
                    ]
                }

        with mock.patch("requests.post", return_value=FakeResponse()):
            with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
                call_generate(
                    stage="review",
                    system_prompt="s",
                    user_context="u",
                    model_config={
                        "api_url": "https://example.invalid/v1",
                        "api_key_env": "MY_CUSTOM_KEY",
                    },
                )


if __name__ == "__main__":
    unittest.main()
