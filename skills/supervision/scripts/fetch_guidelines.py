#!/usr/bin/env python3
"""从短剧创作者中心 API 拉取过审红线，自动解析飞书文档正文并缓存。

用法：
  python fetch_guidelines.py                    # 拉取真人版 + 动画版，缓存完整正文
  python fetch_guidelines.py --check            # 仅检查是否有更新
  python fetch_guidelines.py --type real        # 仅拉取真人版
  python fetch_guidelines.py --type animation   # 仅拉取动画版

流程：
  1. 调知识详情 API 获取 feishuDocxToken + modifyTime
  2. 与本地区缓存 modifyTime 对比，若未更新则跳过
  3. 若有更新，调用飞书文档 API 拉取正文
  4. 写入本地缓存文件

数据源：
  - 知识详情 API:  https://www.shortdramas.com/support/backend/content/knowledge/detail?spaceId=-1&knowledgeId={id}
  - 飞书文档 API:  https://open.feishu.cn/open-apis/docx/v1/documents/{token}/raw_content
  - 飞书 Token API: https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal

认证来源（按优先级）：
  1. 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
  2. ~/.openclaw/openclaw.json → channels.feishu.accounts 下首个有效账号
  3. 项目目录下的 .feishu_credentials.json
"""

import json
import sys
import time
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.error

# ─── 配置 ──────────────────────────────────────────────────────────
# 短剧平台内容创作建议
REAL_KNOWLEDGE_ID = 207462
REAL_DOCX_TOKEN = "RMJidVnPZoBpWjxDunwcFeFEnhf"
ANIMATION_KNOWLEDGE_ID = 207461
ANIMATION_DOCX_TOKEN = "ZVdTdZuRqohP99xZj5Jcw9eXnFe"

# API 地址
KNOWLEDGE_API = "https://www.shortdramas.com/support/backend/content/knowledge/detail"
FEISHU_AUTH_API = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_DOCX_API = "https://open.feishu.cn/open-apis/docx/v1/documents/{token}/raw_content"

# 本地路径
THIS_DIR = Path(__file__).resolve().parent
REFERENCES_DIR = THIS_DIR.parent / "references"
CREDENTIALS_FILE = THIS_DIR.parent / ".feishu_credentials.json"

# ─── 认证 ──────────────────────────────────────────────────────────

def load_feishu_credentials() -> tuple[str, str]:
    """加载飞书应用凭证（按优先级多源搜索）。"""
    # 1. 环境变量
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if app_id and app_secret:
        print("[AUTH] 使用环境变量 FEISHU_APP_ID")
        return app_id, app_secret

    # 2. openclaw.json
    openclaw_config = Path.home() / ".openclaw" / "openclaw.json"
    if openclaw_config.exists():
        try:
            cfg = json.loads(openclaw_config.read_text())
            accounts = cfg.get("channels", {}).get("feishu", {}).get("accounts", {})
            for acct_name, acct_cfg in accounts.items():
                aid = acct_cfg.get("appId")
                asecret = acct_cfg.get("appSecret")
                if aid and asecret and aid != "cli_" + "placeholder":
                    print(f"[AUTH] 使用 openclaw.json 账号: {acct_name}")
                    return aid, asecret
        except Exception:
            pass

    # 3. 本地缓存凭据
    if CREDENTIALS_FILE.exists():
        try:
            cred = json.loads(CREDENTIALS_FILE.read_text())
            if cred.get("appId") and cred.get("appSecret"):
                print("[AUTH] 使用本地凭据文件")
                return cred["appId"], cred["appSecret"]
        except Exception:
            pass

    return "", ""


def get_tenant_token(app_id: str, app_secret: str) -> str:
    """获取飞书 tenant_access_token。"""
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        FEISHU_AUTH_API,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            token = result.get("tenant_access_token", "")
            if not token:
                print(f"[ERR] 获取飞书 token 失败: {result}")
            return token
    except Exception as e:
        print(f"[ERR] 飞书认证请求失败: {e}")
        return ""

# ─── 数据获取 ──────────────────────────────────────────────────────

def _api_get(url: str, max_retries: int = 2, headers: dict = None) -> dict:
    """带重试的 GET 请求。"""
    _headers = {"Accept": "application/json"}
    if headers:
        _headers.update(headers)
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except Exception as e:
            if attempt == max_retries:
                print(f"[ERR] 请求失败（{max_retries+1}次）: {e}")
                return {}
            time.sleep(1)
    return {}


def fetch_knowledge_meta(knowledge_id: int) -> dict:
    """获取知识条目元数据。"""
    url = f"{KNOWLEDGE_API}?spaceId=-1&knowledgeId={knowledge_id}"
    data = _api_get(url)
    if not data or data.get("code") != 1:
        print(f"[ERR] 知识 API 返回异常 (id={knowledge_id}): {data}")
        return {}
    return data.get("data", {})


def fetch_docx_content(doc_token: str, tenant_token: str) -> Optional[str]:
    """通过飞书文档 API 获取完整正文。"""
    url = FEISHU_DOCX_API.format(token=doc_token)
    headers = {"Authorization": f"Bearer {tenant_token}"}
    try:
        data = _api_get(url, max_retries=3, headers=headers)
        if not data or data.get("code") != 0:
            print(f"[ERR] 飞书文档 API 返回异常: {data.get('msg', data)}")
            return None
        content = data.get("data", {}).get("content", "")
        if not content:
            print(f"[WARN] 文档正文为空")
        return content
    except Exception as e:
        print(f"[ERR] 飞书文档请求失败: {e}")
        return None

# ─── 缓存管理 ──────────────────────────────────────────────────────

def load_cached_time(cache_path: Path) -> Optional[str]:
    """从缓存文件读取上次同步时间。"""
    if not cache_path.exists():
        return None
    text = cache_path.read_text(encoding="utf-8")
    m = re.search(r"最后同步[：:] *(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if m:
        return m.group(1)
    m2 = re.search(r"modifyTime[：:] *(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    return m2.group(1) if m2 else None


def save_cache(cache_path: Path, title: str, remote_time: str, content: str,
               knowledge_id: int, doc_token: str, source_url: str):
    """写入缓存文件。"""
    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cache_path.write_text(
        f"# {title}\n\n"
        f"> 来源：{source_url}\n"
        f"> 最后同步（远程修改时间）：{remote_time}\n"
        f"> 本地同步时间：{synced_at}\n"
        f"> knowledgeId: {knowledge_id}\n"
        f"> feishuDocxToken: {doc_token}\n"
        f"> 自动同步脚本：scripts/fetch_guidelines.py\n\n"
        f"---\n\n"
        f"{content}\n",
        encoding="utf-8",
    )

# ─── 主流程 ──────────────────────────────────────────────────────

def sync_one(knowledge_id: int, doc_token: str, label: str,
             cache_path: Path, tenant_token: str, check_only: bool = False) -> bool:
    """同步单个指南。返回是否有更新。"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    # 1. 查元数据
    meta = fetch_knowledge_meta(knowledge_id)
    if not meta:
        print(f"  [FAIL] 无法获取元数据")
        return False

    remote_time = meta.get("modifyTime", "unknown")
    title = meta.get("name", label)
    print(f"  标题: {title}")
    print(f"  远程修改时间: {remote_time}")

    # 2. 对比缓存
    cached_time = load_cached_time(cache_path)
    if cached_time:
        print(f"  本地缓存时间: {cached_time}")

    if cached_time and cached_time >= remote_time:
        print(f"  [SKIP] 已是最新，无需更新")
        return False

    if check_only:
        print(f"  [UPDATE] 远程有更新！")
        return True

    # 3. 拉取正文
    print(f"  🔄 拉取完整正文...")
    if not tenant_token:
        print(f"  [WARN] 无飞书认证，仅缓存元数据。")
        print(f"  设置 FEISHU_APP_ID / FEISHU_APP_SECRET 后可自动拉取正文。")
        save_cache(cache_path, title, remote_time,
                    f"（元数据已同步，正文需手动通过 feishu_doc read doc_token={doc_token} 获取）",
                    knowledge_id, doc_token,
                    "https://www.shortdramas.com/support/content/25563649282")
        return True

    content = fetch_docx_content(doc_token, tenant_token)
    if content:
        # 4. 写入缓存
        save_cache(cache_path, title, remote_time, content,
                   knowledge_id, doc_token,
                   "https://www.shortdramas.com/support/content/25563649282")
        print(f"  [OK] 已同步 ({len(content)} chars) → {cache_path.name}")
        return True
    else:
        print(f"  [FAIL] 正文拉取失败")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="同步短剧平台过审红线指南")
    parser.add_argument("--check", action="store_true", help="仅检查是否有更新（不拉取）")
    parser.add_argument("--type", choices=["real", "animation", "all"], default="all")
    parser.add_argument("--app-id", help="飞书应用 App ID")
    parser.add_argument("--app-secret", help="飞书应用 App Secret")
    args = parser.parse_args()

    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)

    # 认证
    app_id = args.app_id or os.environ.get("FEISHU_APP_ID", "")
    app_secret = args.app_secret or os.environ.get("FEISHU_APP_SECRET", "")

    if not app_id:
        app_id, app_secret = load_feishu_credentials()

    tenant_token = ""
    if app_id and app_secret and not args.check:
        tenant_token = get_tenant_token(app_id, app_secret)
        if not tenant_token:
            print("[WARN] 飞书认证失败，将跳过正文拉取。仅缓存元数据。")
            print("       设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量后重试。")

    # 同步目标
    targets = []
    if args.type in ("real", "all"):
        targets.append(("真人版", REAL_KNOWLEDGE_ID, REAL_DOCX_TOKEN, "guidelines_real.md"))
    if args.type in ("animation", "all"):
        targets.append(("动画版", ANIMATION_KNOWLEDGE_ID, ANIMATION_DOCX_TOKEN, "guidelines_animation.md"))

    has_update = False
    for label, kid, dtok, filename in targets:
        cache_path = REFERENCES_DIR / filename
        updated = sync_one(kid, dtok, label, cache_path, tenant_token,
                          check_only=args.check)
        if updated:
            has_update = True

    # 汇总
    print(f"\n{'='*60}")
    if args.check:
        if has_update:
            print("⚠️ 有过审红线更新！请运行 fetch_guidelines.py 拉取最新版本。")
        else:
            print("✅ 所有过审红线均为最新。")
    else:
        if has_update:
            print("✅ 同步完成。")
            print(f"   缓存目录: {REFERENCES_DIR}")
        else:
            print("✅ 已是最新，无需更新。")

    sys.exit(2 if (args.check and has_update) else 0)


if __name__ == "__main__":
    main()
