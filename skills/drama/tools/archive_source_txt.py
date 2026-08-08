#!/usr/bin/env python3
"""Archive a user-provided novel/script txt into the Fangcun project wiki folder.

After project workspace + Table 1/Table 2 are initialized, run this when the
user sends the source novel txt. It creates a docx under the project wiki folder,
writes the txt content under the project wiki folder, and prints user-facing
clickable link lines for the group reply. By current project rule it does NOT
write file links back into Table 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Allow running directly from tools/.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from feishu_project_executor import (  # noqa: E402
    DEFAULT_ACCOUNT,
    FeishuApiError,
    FeishuProjectExecutor,
    create_project_doc,
    load_state,
    save_state,
    sync_doc_title,
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_title(config: dict[str, Any], state: dict[str, Any]) -> str:
    ws = state.get("project_workspace") or {}
    folder = (ws.get("folder_title") or "").removesuffix("项目文件夹")
    return (
        config.get("drama_name")
        or config.get("novel_name")
        or config.get("project", {}).get("name")
        or folder
        or "未命名项目"
    )


def read_text_file(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def safe_doc_markdown(title: str, source_name: str, content: str) -> str:
    # Keep raw text as plain paragraphs; do not put source text in project-info dashboard.
    return f"# {title}\n\n来源文件：{source_name}\n\n归档时间：{datetime.now().isoformat(timespec='seconds')}\n\n---\n\n{content.strip()}\n"


def list_records(client: FeishuProjectExecutor, app_token: str, table_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        payload = client.request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params=params)
        data = payload.get("data", {})
        items.extend(data.get("items") or [])
        page_token = data.get("page_token")
        if not data.get("has_more") or not page_token:
            return items


def update_record(client: FeishuProjectExecutor, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    payload = client.request(
        "PUT",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        json_body={"fields": fields},
    )
    return payload.get("data", {}).get("record", {})


def update_table1_source_link(client: FeishuProjectExecutor, workspace: dict[str, Any], title: str, url: str) -> Optional[str]:
    """Deprecated no-op.

    用户最新要求：Fangcun 不需要把小说/剧本原文或其他文件链接贴入表格。
    表1/表2只做项目初始化与信息登记；文件链接通过群聊回贴和项目目录查看。
    保留函数名仅兼容旧调用路径。
    """
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Archive source novel txt into Fangcun project wiki folder and Table 1")
    ap.add_argument("--file", required=True, help="Local txt file path")
    ap.add_argument("--config", required=True, help="Fangcun project config.json")
    ap.add_argument("--account", default=os.environ.get("FANGCUN_FEISHU_ACCOUNT", DEFAULT_ACCOUNT))
    ap.add_argument("--title", default="小说/剧本原文", help="Task/title suffix")
    ap.add_argument("--version", default="", help="Optional explicit version label, e.g. V1")
    args = ap.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"txt file not found: {file_path}")
    if not config_path.exists():
        raise SystemExit(f"config not found: {config_path}")

    config = read_json(config_path)
    state = load_state(config)
    workspace = state.get("project_workspace") or {}
    if not workspace.get("project_node_token"):
        raise SystemExit("project workspace is not initialized; create project folder/Table1/Table2 first")

    client = FeishuProjectExecutor(account=args.account)
    proj = project_title(config, state)
    version = args.version or datetime.now().strftime("v%Y%m%d-r1")
    title = sync_doc_title(proj, args.title, version)
    content = read_text_file(file_path)
    created = create_project_doc(client, title, config, workspace)
    write_result = client.write_doc(created["doc_token"], safe_doc_markdown(title, file_path.name, content))

    row_id = update_table1_source_link(client, workspace, title, created["url"])

    docs = state.setdefault("docs", {})
    entry = docs.setdefault("source_txt", {"versions": []})
    now_iso = datetime.now().isoformat(timespec="seconds")
    item = {
        "version": version,
        "created_at": now_iso,
        "doc_token": created.get("doc_token"),
        "node_token": created.get("node_token"),
        "url": created.get("url"),
        "title": title,
        "doc_kind": "source_txt",
        "phase": "source_txt",
        "local_path": str(file_path),
        "table1_record_id": row_id,
        "last_synced_at": now_iso,
    }
    entry.setdefault("versions", []).append(item)
    entry["active_version"] = version
    entry.update({k: item[k] for k in ("doc_token", "url", "title", "doc_kind", "phase", "last_synced_at")})
    save_state(config, state)

    print(json.dumps({"status": "ok", "source_url": created.get("url"), "title": title, "table1_record_id": row_id, "table1_update": "skipped_by_rule", "write_result": write_result}, ensure_ascii=False, indent=2))
    print(f"小说/剧本原文：[{title}]({created.get('url')})")
    print("表1不写入文件链接：按项目规则跳过表格更新")


if __name__ == "__main__":
    try:
        main()
    except FeishuApiError as exc:
        raise SystemExit(str(exc))
