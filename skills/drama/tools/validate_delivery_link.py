#!/usr/bin/env python3
"""Validate Fangcun delivery links before posting them to a Feishu group.

A Fangcun formal delivery doc link is valid only if its doc token is already
registered in the current project's feishu_sync_state.json. This blocks ad-hoc
feishu_doc.create links from being treated as official deliveries.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from project_ownership_guard import ProjectOwnershipError, assert_config_binding, assert_state_binding  # noqa: E402

DELIVERY_ERROR = "检测到游离飞书文档，未进入 Fangcun 项目资产体系。本次不作为正式交付。请先通过 Fangcun 同步执行器导入/重同步。"

DOC_TOKEN_RE = re.compile(r"/(?:docx|doc)/([A-Za-z0-9_-]+)")


def extract_doc_token(text: str) -> Optional[str]:
    text = str(text or "").strip()
    if not text:
        return None
    match = DOC_TOKEN_RE.search(text)
    if match:
        return match.group(1)
    # Allow raw token input for scripts/tests.
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text):
        return text
    return None


def state_path(config: dict) -> Path:
    return Path(config.get("output_dir", ".")).expanduser().resolve() / "feishu_sync_state.json"


def load_state(config: dict) -> dict:
    path = state_path(config)
    if not path.exists():
        raise RuntimeError(f"feishu_sync_state.json 不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_registered_doc_tokens(state: dict) -> Iterable[str]:
    docs = state.get("docs") if isinstance(state.get("docs"), dict) else {}
    for entry in docs.values():
        if not isinstance(entry, dict):
            continue
        token = entry.get("doc_token")
        if token:
            yield str(token)
        versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
        for item in versions:
            if isinstance(item, dict) and item.get("doc_token"):
                yield str(item["doc_token"])


def find_registered_doc_kind(state: dict, token: str) -> str:
    docs = state.get("docs") if isinstance(state.get("docs"), dict) else {}
    for key, entry in docs.items():
        if not isinstance(entry, dict):
            continue
        versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
        for item in versions:
            if isinstance(item, dict) and str(item.get("doc_token") or "") == token:
                return str(item.get("doc_kind") or key)
        if str(entry.get("doc_token") or "") == token:
            return str(entry.get("doc_kind") or key)
    return ""


def validate_links(config: dict, config_path: Path, links: list[str], *, account: str = "") -> dict:
    assert_config_binding(config, config_path=config_path, account=account)
    state = load_state(config)
    assert_state_binding(config, state, require_project_node=True)
    registered = set(iter_registered_doc_tokens(state))
    results = []
    invalid = []
    for link in links:
        token = extract_doc_token(link)
        ok = bool(token and token in registered)
        doc_kind = find_registered_doc_kind(state, token) if ok and token else ""
        if ok and doc_kind == "script_full" and (state.get("final_delivery") or {}).get("status") != "confirmed":
            ok = False
        item = {"link": link, "doc_token": token, "registered": ok, "doc_kind": doc_kind}
        results.append(item)
        if not ok:
            invalid.append(item)
    if invalid:
        return {
            "status": "blocked",
            "reason": DELIVERY_ERROR,
            "state_path": str(state_path(config)),
            "invalid": invalid,
            "registered_count": len(registered),
            "results": results,
        }
    return {
        "status": "ok",
        "state_path": str(state_path(config)),
        "registered_count": len(registered),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Fangcun 正式交付链接是否已登记在当前项目 feishu_sync_state.json")
    parser.add_argument("--config", required=True, help="项目正式 config 路径：projects/<slug>/drama/config.json")
    parser.add_argument("--account", default="", help="当前飞书账号；默认从环境读取")
    parser.add_argument("--link", action="append", default=[], help="待回贴的飞书 doc/docx 链接；可重复")
    parser.add_argument("--doc-token", action="append", default=[], help="待校验 doc_token；可重复")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    links = list(args.link) + list(args.doc_token)
    if not links:
        print("未提供 --link 或 --doc-token", file=sys.stderr)
        return 2

    config_path = Path(args.config).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["_config_path"] = str(config_path)
    try:
        result = validate_links(config, config_path, links, account=args.account)
    except (ProjectOwnershipError, RuntimeError, json.JSONDecodeError) as exc:
        result = {"status": "blocked", "reason": str(exc)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("status") == "ok":
            print("OK: 待回贴 Fangcun 文档链接均已登记在当前项目 feishu_sync_state.json。")
        else:
            print(result.get("reason") or DELIVERY_ERROR)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
