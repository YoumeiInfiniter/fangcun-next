"""API 客户端：带指数退避重试的 API 调用（已裁剪为 drama-only）。

凭据解析优先级：
  1. 环境变量 API_KEY / API_BASE_URL
  2. config.json 的 api_key / api_base_url
  3. ~/.openclaw/openclaw.json 中的 OpenAI-compatible provider
"""

import json
import os
import time
from pathlib import Path
import requests

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_API_URL = os.environ.get("DEFAULT_API_URL", "https://api.deepseek.com/v1/chat/completions")

# 复用 TCP 连接，减少 TLS 握手开销
_session = requests.Session()
_discovered_creds = None


def _build_chat_url(base_url: str) -> str:
    """从 base_url 构建 /v1/chat/completions 完整 URL。"""
    base = (base_url or "").rstrip("/")
    if not base:
        return DEFAULT_API_URL
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base + "/chat/completions"


def _model_id(item):
    if isinstance(item, dict):
        return item.get("id") or item.get("name")
    if isinstance(item, str):
        return item
    return None


def _pick_model(models) -> str:
    """从 OpenClaw provider models 列表中提取模型 id。

    中转站 provider 常常同时挂 Claude/GPT/Gemini。默认优先 GPT5.5，
    避免误取列表第一个 Claude 模型；仍允许 config.model / model_overrides 覆盖。
    """
    if not models:
        return DEFAULT_MODEL
    candidates = []
    if isinstance(models, dict):
        for key, value in models.items():
            candidates.append(_model_id(value) or key)
    elif isinstance(models, list):
        candidates = [_model_id(x) for x in models]
    else:
        candidates = [_model_id(models)]
    candidates = [x for x in candidates if x]
    if not candidates:
        return DEFAULT_MODEL
    preferred_keywords = ("geneasy-gpt-5.5", "gpt-5.5", "gpt5.5", "gpt-5")
    for keyword in preferred_keywords:
        for model in candidates:
            if keyword.lower() in model.lower():
                return model
    return candidates[0]


def _provider_creds(name: str, provider: dict):
    api_key = (
        provider.get("apiKey")
        or provider.get("api_key")
        or provider.get("key")
        or ""
    )
    if not api_key:
        return None
    base_url = (
        provider.get("baseUrl")
        or provider.get("base_url")
        or provider.get("url")
        or ""
    )
    extra_headers = provider.get("headers") if isinstance(provider.get("headers"), dict) else {}
    return {
        "api_key": api_key,
        "api_url": _build_chat_url(base_url),
        "model": _pick_model(provider.get("models", [])),
        "headers": extra_headers,
        "auth_header": provider.get("authHeader"),
        "source": f"~/.openclaw/openclaw.json:{name}",
    }


def _discover_credentials_from_openclaw():
    """从 ~/.openclaw/openclaw.json 自动发现兼容 OpenAI 的 API 凭据。"""
    global _discovered_creds
    if _discovered_creds is not None:
        return _discovered_creds or None

    cfg_path = Path(os.environ.get("OPENCLAW_CONFIG", Path.home() / ".openclaw" / "openclaw.json"))
    if not cfg_path.exists():
        _discovered_creds = False
        return None

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        providers = cfg.get("models", {}).get("providers", {})
    except Exception:
        _discovered_creds = False
        return None

    if isinstance(providers, dict):
        # Fangcun runs inside OpenClaw. Prefer the workspace/default OpenAI-compatible
        # gateway (for example geneasy) over the legacy GitHub/toonflow DeepSeek config.
        # DeepSeek remains a fallback or an explicit config/env override.
        preferred_names = ("geneasy", "openai", "openai-completions")
        for preferred in preferred_names:
            provider = providers.get(preferred)
            if isinstance(provider, dict) and provider.get("api") == "openai-completions":
                result = _provider_creds(preferred, provider)
                if result:
                    _discovered_creds = result
                    return result

        for name, provider in providers.items():
            if not isinstance(provider, dict):
                continue
            if name == "deepseek":
                continue
            if provider.get("api") == "openai-completions":
                result = _provider_creds(name, provider)
                if result:
                    _discovered_creds = result
                    return result

        deepseek = providers.get("deepseek")
        if isinstance(deepseek, dict):
            result = _provider_creds("deepseek", deepseek)
            if result:
                _discovered_creds = result
                return result

    _discovered_creds = False
    return None


def get_api_url(config=None):
    """获取 API URL，确保包含 /v1/chat/completions。"""
    if os.environ.get("API_BASE_URL"):
        return _build_chat_url(os.environ["API_BASE_URL"])
    if config and config.get("api_base_url"):
        return _build_chat_url(config["api_base_url"])
    creds = _discover_credentials_from_openclaw()
    if creds:
        return creds["api_url"]
    return DEFAULT_API_URL


def get_api_url_source(config=None):
    if os.environ.get("API_BASE_URL"):
        return "env:API_BASE_URL"
    if config and config.get("api_base_url"):
        return "config.api_base_url"
    creds = _discover_credentials_from_openclaw()
    if creds:
        return creds["source"]
    return "default"


def get_api_key(config=None):
    """获取 API Key。"""
    if os.environ.get("API_KEY"):
        return os.environ["API_KEY"]
    if config and config.get("api_key"):
        return config["api_key"]
    creds = _discover_credentials_from_openclaw()
    if creds:
        return creds["api_key"]
    return None


def get_api_key_source(config=None):
    if os.environ.get("API_KEY"):
        return "env:API_KEY"
    if config and config.get("api_key"):
        return "config.api_key"
    creds = _discover_credentials_from_openclaw()
    if creds:
        return creds["source"]
    return "missing"


def get_discovered_model(default=None):
    creds = _discover_credentials_from_openclaw()
    if creds and creds.get("model"):
        return creds["model"]
    return default


def _auth_headers(api_key: str, api_url: str = "", config_provider: str = "") -> dict:
    """Build request headers for OpenAI-compatible providers without leaking secrets.

    OpenClaw provider config may supply either a full headers dict or an
    `authHeader` marker.  When `authHeader` is true, the provider expects the
    standard Authorization bearer header.  Legacy MiMo still uses `api-key`.
    """
    creds = _discover_credentials_from_openclaw() or {}
    extra_headers = creds.get("headers") if isinstance(creds.get("headers"), dict) else {}
    if extra_headers:
        return {**extra_headers, "Content-Type": "application/json"}

    auth_header = creds.get("auth_header")
    if isinstance(auth_header, str) and auth_header.strip():
        raw = auth_header.strip()
        # Accept either "Header-Name" or "Header-Name: value-with-{api_key}".
        if ":" in raw:
            name, value = raw.split(":", 1)
            value = value.strip().replace("{api_key}", api_key).replace("${api_key}", api_key)
            return {name.strip(): value, "Content-Type": "application/json"}
        return {raw: f"Bearer {api_key}", "Content-Type": "application/json"}
    if auth_header is True:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if "mimo" in (api_url or "") or "xiaomimimo" in (api_url or ""):
        return {"api-key": api_key, "Content-Type": "application/json"}
    if config_provider == "deepseek" or "deepseek" in (api_url or ""):
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _max_tokens_payload_key(model: str) -> str:
    """GPT-5 style models reject max_tokens and require max_completion_tokens."""
    m = (model or "").lower()
    if "gpt-5" in m or "gpt5" in m:
        return "max_completion_tokens"
    return "max_tokens"


def call_api(api_key, model, user_prompt,
             system_prompt=None, api_url=None, max_retries=3,
             temperature=0.8, max_tokens=None, return_usage=False, provider=None):
    """调用 API，带指数退避重试。

    Args:
        temperature: 默认 0.8。审稿推荐 0.3，修复推荐 0.6。
        max_tokens: 最大输出 token 数。None 表示不限制。
        return_usage: 是否返回 (content, usage_dict) 元组。
        provider: API 提供商（"deepseek", "openai", "mimo" 等）

    Returns:
        str 或 (str, dict): 返回内容。return_usage=True 时额外返回 usage。

    重试策略：
    - 429 (限流): 指数退避 10/20/40 秒
    - 5xx (服务端错误): 指数退避 5/10/20 秒
    - 402 (余额不足): 立即停止，不重试
    - 超时: 重试，超时时间翻倍
    - 其他错误: 不重试
    """
    url = api_url or DEFAULT_API_URL

    headers = _auth_headers(api_key, url, provider or "")

    sys_prompt = system_prompt or ""
    # 标准 OpenAI Chat Completions 消息格式。不要加入 cache_control，
    # 部分中转站/GPT 类模型会拒绝非标准字段。
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt}
    ]
    data = {
        "model": model,
        "messages": messages,
    }
    # GPT-5 style models only accept the default temperature; sending any
    # non-default value makes compatible gateways reject the request.
    if not ("gpt-5" in (model or "").lower() or "gpt5" in (model or "").lower()):
        data["temperature"] = temperature
    if max_tokens:
        data[_max_tokens_payload_key(model)] = max_tokens

    timeout = 300  # 初始超时 5 分钟

    for attempt in range(max_retries + 1):
        try:
            resp = _session.post(url, headers=headers, json=data, timeout=timeout)

            if resp.status_code == 200:
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {})
                if return_usage:
                    return content, usage
                return content

            # 402 余额不足 - 立即停止
            if resp.status_code == 402:
                error_msg = resp.text[:200]
                raise Exception(f"余额不足，请充值后重试: {error_msg}")

            # 401 认证失败 - 立即停止
            if resp.status_code == 401:
                error_msg = resp.text[:200]
                raise Exception(f"API Key 无效: {error_msg}")

            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                print(f"    [429] 限流，等待 {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                wait = 5 * (2 ** attempt)
                print(f"    [{resp.status_code}] 服务端错误，等待 {wait}s...")
                time.sleep(wait)
                continue

            # 其他错误不重试
            raise Exception(f"API 错误 {resp.status_code}: {resp.text[:200]}")

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                timeout *= 2
                print(f"    [TIMEOUT] 超时，重试 (timeout={timeout}s)...")
                continue
            raise Exception(f"请求超时，已重试 {max_retries} 次")

        except requests.exceptions.ConnectionError as e:
            # 连接失败 - 快速失败，不重试（可能是断网）
            raise Exception(f"连接失败，请检查网络: {str(e)[:100]}")

    raise Exception(f"API 调用失败，已重试 {max_retries} 次")


def test_api_connection(config=None, timeout=10, model=None):
    """测试 API 连接是否正常。
    
    Returns:
        dict: {
            "success": bool,
            "url": str,
            "model": str,
            "latency_ms": float or None,
            "error": str or None
        }
    """
    api_key = get_api_key(config)
    api_url = get_api_url(config)
    model = model or (config or {}).get("model") or get_discovered_model(DEFAULT_MODEL)
    
    if not api_key:
        return {
            "success": False,
            "url": api_url,
            "model": model,
            "latency_ms": None,
            "error": "未配置 API_KEY"
        }
    
    provider = (config or {}).get("provider", "")
    headers = _auth_headers(api_key, api_url, provider)
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": "test"}
        ],
        _max_tokens_payload_key(model): 5,
    }
    
    try:
        start_time = time.time()
        resp = _session.post(api_url, headers=headers, json=data, timeout=timeout)
        latency_ms = (time.time() - start_time) * 1000
        
        if resp.status_code == 200:
            return {
                "success": True,
                "url": api_url,
                "model": model,
                "latency_ms": round(latency_ms, 2),
                "error": None
            }
        else:
            return {
                "success": False,
                "url": api_url,
                "model": model,
                "latency_ms": round(latency_ms, 2),
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}"
            }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "url": api_url,
            "model": model,
            "latency_ms": None,
            "error": f"连接超时 ({timeout}s)"
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "url": api_url,
            "model": model,
            "latency_ms": None,
            "error": f"连接失败: {str(e)[:200]}"
        }
    except Exception as e:
        return {
            "success": False,
            "url": api_url,
            "model": model,
            "latency_ms": None,
            "error": f"未知错误: {str(e)[:200]}"
        }
