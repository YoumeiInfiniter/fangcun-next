"""Model call abstraction (spec §21.1).

Two modes share the same episode_context, prompts and validators:
- Host Agent Mode: the host agent reads the rendered prompt bundle and writes
  the artifact directly (no API call made here);
- API Mode: this adapter calls an OpenAI-compatible endpoint.

Without credentials the runtime MUST NOT pretend an API review happened.
"""

from __future__ import annotations

import os
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
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


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
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"模型响应格式不兼容: {exc}") from exc
