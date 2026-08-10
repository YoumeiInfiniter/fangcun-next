"""Model call abstraction (spec §21.1).

Two modes share the same episode_context, prompts and validators:
- Host Agent Mode: the host agent reads the rendered prompt bundle and writes
  the artifact directly (no API call made here);
- API Mode: this adapter calls an OpenAI-compatible endpoint.

Without credentials the runtime MUST NOT pretend an API review happened.
"""

from __future__ import annotations

import os
import json
import re
from typing import Any


class ModelUnavailableError(RuntimeError):
    pass


def resolve_api_key(model_config: dict | None) -> str:
    model_config = model_config or {}
    env_name = model_config.get("api_key_env")
    if env_name:
        key = os.environ.get(env_name, "")
        if key:
            return key
    for fallback in ("FANGCUN_API_KEY", "DEEPSEEK_API_KEY"):
        key = os.environ.get(fallback, "")
        if key:
            return key
    raise ModelUnavailableError(
        "未配置 API 密钥。请设置环境变量 FANGCUN_API_KEY 或 DEEPSEEK_API_KEY，"
        "或在 config.local.json 的 model_config.api_key_env 指定其他变量名。"
    )


def build_payload(
    *,
    system_prompt: str,
    user_context: str,
    model_config: dict | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> dict:
    model_config = model_config or {}
    model = model_config.get("model") or os.environ.get("FANGCUN_MODEL", "gpt-4.1-mini")
    output_param = model_config.get("output_token_param", "max_tokens")
    output_value = model_config.get("max_output_tokens") or max_tokens
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context},
        ],
        "temperature": temperature,
    }
    payload[output_param] = output_value
    if model_config.get("disable_thinking"):
        payload["thinking"] = {"type": "disabled"}
    return payload


def call_generate(
    *,
    stage: str,
    system_prompt: str,
    user_context: str,
    output_contract: str = "",
    model_config: dict | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""
    import requests

    model_config = model_config or {}
    api_url = model_config.get("api_url") or os.environ.get("FANGCUN_API_URL")
    if not api_url:
        raise ModelUnavailableError("未配置 api_url（model_config.api_url 或 FANGCUN_API_URL）。")
    key = resolve_api_key(model_config)
    payload = build_payload(
        system_prompt=system_prompt,
        user_context=user_context + (f"\n\n输出契约：\n{output_contract}" if output_contract else ""),
        model_config=model_config,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    response = requests.post(
        api_url.rstrip("/") + "/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    try:
        choice = data["choices"][0]
        finish_reason = str(choice.get("finish_reason") or "")
        if finish_reason == "length":
            raise RuntimeError(
                "模型输出因 max_output_tokens 被截断（finish_reason=length），"
                "禁止当作完整结果继续保存。请提高配置或改用 Host Agent Mode。"
            )
        message = choice["message"]
        content = message.get("content") or ""
        if not content.strip():
            reasoning = (message.get("reasoning_content") or "").strip()
            if reasoning:
                raise RuntimeError(
                    "模型只返回了推理内容（reasoning_content），正文为空。"
                    "请增大 max_tokens，或改用非推理模型。"
                )
            raise RuntimeError("模型返回空正文")
        return content
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"模型响应格式不兼容: {exc}") from exc


def parse_json_response(text: str) -> Any:
    """Extract a JSON object from model output (handles code fences)."""
    text = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("模型输出不是合法 JSON，无法解析")
