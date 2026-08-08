#!/usr/bin/env python3
"""
方寸飞书项目同步执行器。

把 build_feishu_project.py 生成的 manifest 直接执行成飞书 docx create/update，
不再依赖 agent 手动逐个调用 feishu_doc 工具。

特性：
- 读取 OPENCLAW_CONFIG 或 ~/.openclaw/openclaw.json 中 channels.feishu.accounts.<account>.appId/appSecret
- doc_token 状态持久化到 <output_dir>/feishu_sync_state.json
- 默认每次同步同一 stable_key 都创建新版本文档，旧版本永久保留
- 只有显式 --overwrite-current 才覆盖当前推荐版本
- 使用飞书 docx markdown convert + descendant API 写入内容
- 项目信息文档会在同步完其他文档后追加真实链接索引

限制：
- 不删除、不清空、不自动归档旧文档；旧版本作为历史记录保留。
- Markdown 转换依赖飞书 /docx/v1/documents/blocks/convert；复杂表格/图片以飞书 API 支持为准。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

try:
    from asset_registry import register_asset, write_dashboard
except Exception:  # asset registry is optional for backward compatibility
    register_asset = None
    write_dashboard = None

from project_ownership_guard import (
    ProjectOwnershipError,
    assert_config_binding,
    assert_state_binding,
    stamp_state_identity,
)

OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", str(Path.home() / ".openclaw" / "openclaw.json")))
FEISHU_API = os.environ.get("FEISHU_API", "https://open.feishu.cn/open-apis")
DEFAULT_ACCOUNT = os.environ.get("FANGCUN_FEISHU_ACCOUNT") or os.environ.get("OPENCLAW_AGENT_ID") or "default"
DEFAULT_PROJECT_WIKI_ROOT_TOKEN = os.environ.get("FANGCUN_PROJECT_WIKI_ROOT_TOKEN", "NNfBwb32SiOhAwkrhRlcYkojnJg")
DEFAULT_PROJECT_WIKI_URL_PREFIX = os.environ.get("FANGCUN_PROJECT_WIKI_URL_PREFIX", "https://m9cfu49348.feishu.cn/wiki/")
PRODUCT_OVERVIEW_TEMPLATE_URL = "https://m9cfu49348.feishu.cn/base/NZ8vbVqpbajZqYsZuDjchf5mnvh?table=tblacd7rgShbaNBl&view=vewHS5ZPEB"
TOKEN_USAGE_TEMPLATE_URL = "https://m9cfu49348.feishu.cn/base/OIscbOQJQaf7MasVgsGccyrjndc?table=tblyC8Ee79rJXgCk&view=vewfNlNv1I"


class FeishuApiError(RuntimeError):
    pass


class FeishuProjectExecutor:
    def __init__(self, account: str = DEFAULT_ACCOUNT, config_path: Path = OPENCLAW_CONFIG):
        self.account = account
        self.config_path = Path(config_path)
        self.tenant_access_token: Optional[str] = None
        self._token_expire_at = 0.0

    def _load_app_credentials(self) -> tuple[str, str]:
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        feishu = cfg.get("channels", {}).get("feishu", {})
        accounts = feishu.get("accounts", {})
        account_cfg = accounts.get(self.account) or accounts.get("default") or {}
        app_id = account_cfg.get("appId") or account_cfg.get("app_id") or feishu.get("appId") or feishu.get("app_id")
        app_secret = account_cfg.get("appSecret") or account_cfg.get("app_secret") or feishu.get("appSecret") or feishu.get("app_secret")
        if not app_id or not app_secret:
            raise FeishuApiError(f"未找到飞书应用凭据：channels.feishu.accounts.{self.account}.appId/appSecret")
        return app_id, app_secret

    def token(self) -> str:
        now = time.time()
        if self.tenant_access_token and now < self._token_expire_at:
            return self.tenant_access_token
        app_id, app_secret = self._load_app_credentials()
        res = requests.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=30,
        )
        payload = self._checked(res, "tenant_access_token")
        token = payload.get("tenant_access_token")
        if not token:
            raise FeishuApiError("飞书未返回 tenant_access_token")
        self.tenant_access_token = token
        self._token_expire_at = now + int(payload.get("expire", 7200)) - 120
        return token

    def request(self, method: str, path: str, *, json_body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        url = f"{FEISHU_API}{path}"
        headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json; charset=utf-8"}
        res = requests.request(method, url, headers=headers, json=json_body, params=params, timeout=120)
        return self._checked(res, path)

    @staticmethod
    def _checked(res: requests.Response, where: str) -> dict:
        try:
            payload = res.json()
        except Exception as exc:
            raise FeishuApiError(f"{where} HTTP {res.status_code}: {res.text[:500]}") from exc
        code = payload.get("code", 0)
        if res.status_code >= 400 or code not in (0, None):
            raise FeishuApiError(f"{where} failed: HTTP {res.status_code}, code={code}, msg={payload.get('msg')}, body={str(payload)[:1000]}")
        return payload

    def create_doc(self, title: str, folder_token: Optional[str] = None) -> dict:
        data = {"title": title}
        if folder_token:
            data["folder_token"] = folder_token
        payload = self.request("POST", "/docx/v1/documents", json_body=data)
        doc = payload.get("data", {}).get("document", {})
        doc_token = doc.get("document_id")
        if not doc_token:
            raise FeishuApiError(f"创建文档成功但未返回 document_id: {payload}")
        return {"doc_token": doc_token, "title": doc.get("title") or title, "url": docx_url(doc_token)}

    def convert_markdown(self, markdown: str) -> tuple[List[dict], List[str]]:
        payload = self.request(
            "POST",
            "/docx/v1/documents/blocks/convert",
            json_body={"content_type": "markdown", "content": markdown or " "},
        )
        data = payload.get("data", {})
        return data.get("blocks") or [], data.get("first_level_block_ids") or []

    def list_blocks(self, doc_token: str) -> List[dict]:
        items: List[dict] = []
        page_token = None
        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            payload = self.request("GET", f"/docx/v1/documents/{doc_token}/blocks", params=params)
            data = payload.get("data", {})
            items.extend(data.get("items") or [])
            page_token = data.get("page_token")
            if not page_token:
                break
        return items

    def clear_doc(self, doc_token: str) -> int:
        blocks = self.list_blocks(doc_token)
        root_children = [b for b in blocks if b.get("parent_id") == doc_token and b.get("block_type") != 1]
        if not root_children:
            return 0
        payload = self.request(
            "DELETE",
            f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children/batch_delete",
            json_body={"start_index": 0, "end_index": len(root_children)},
        )
        return len(root_children)

    def write_doc(self, doc_token: str, markdown: str) -> dict:
        deleted = self.clear_doc(doc_token)
        markdown = sanitize_markdown_for_docx(markdown)
        blocks, root_ids = self.convert_markdown(markdown)
        if not blocks:
            return {"blocks_deleted": deleted, "blocks_added": 0}
        
        # 飞书 API 限制: children_id 和 descendants 一次最多 1000 个
        # 拆分 root_ids，每次提交一部分
        descendant_dict = {b["block_id"]: b for b in blocks}
        added_count = 0
        
        chunk_root_ids = []
        chunk_descendants = []
        
        for r_id in root_ids:
            # 计算这个 r_id 带的所有 descendants
            sub_descendants = []
            queue = [r_id]
            visited = set()
            while queue:
                curr_id = queue.pop(0)
                if curr_id in visited: continue
                visited.add(curr_id)
                if curr_id in descendant_dict:
                    b = descendant_dict[curr_id]
                    sub_descendants.append(to_descendant_block(b))
                    if "children" in b:
                        queue.extend(b["children"])
            
            if len(chunk_descendants) + len(sub_descendants) > 900:
                self.request(
                    "POST",
                    f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/descendant",
                    json_body={"children_id": chunk_root_ids, "descendants": chunk_descendants, "index": -1},
                )
                added_count += len(chunk_descendants)
                chunk_root_ids = []
                chunk_descendants = []
                
            chunk_root_ids.append(r_id)
            chunk_descendants.extend(sub_descendants)
            
        if chunk_root_ids:
            self.request(
                "POST",
                f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/descendant",
                json_body={"children_id": chunk_root_ids, "descendants": chunk_descendants, "index": -1},
            )
            added_count += len(chunk_descendants)
            
        return {"blocks_deleted": deleted, "blocks_added": added_count}

    def grant_permission(self, doc_token: str, member_id: str, member_type: str = "openid", perm: str = "full_access") -> dict:
        return self.request(
            "POST",
            f"/drive/v1/permissions/{doc_token}/members",
            params={"type": "docx", "need_notification": "false"},
            json_body={"member_type": member_type, "member_id": member_id, "perm": perm},
        )

    def get_wiki_node(self, token: str) -> dict:
        payload = self.request("GET", "/wiki/v2/spaces/get_node", params={"token": token})
        return payload.get("data", {}).get("node", {})

    def list_wiki_nodes(self, space_id: str, parent_node_token: Optional[str] = None) -> List[dict]:
        payload = self.request(
            "GET",
            f"/wiki/v2/spaces/{space_id}/nodes",
            params={"parent_node_token": parent_node_token} if parent_node_token else None,
        )
        return payload.get("data", {}).get("items") or []

    def create_wiki_node(self, space_id: str, title: str, obj_type: str = "docx", parent_node_token: Optional[str] = None) -> dict:
        payload = self.request(
            "POST",
            f"/wiki/v2/spaces/{space_id}/nodes",
            json_body={
                "obj_type": obj_type,
                "node_type": "origin",
                "title": title,
                **({"parent_node_token": parent_node_token} if parent_node_token else {}),
            },
        )
        node = payload.get("data", {}).get("node", {})
        if not node.get("node_token") or not node.get("obj_token"):
            raise FeishuApiError(f"创建 wiki 节点成功但返回不完整: {payload}")
        return node

    def get_chat_info(self, chat_id: str) -> dict:
        clean = (chat_id or "").replace("chat:", "")
        if not clean:
            return {}
        payload = self.request("GET", f"/im/v1/chats/{clean}")
        return payload.get("data", {}) or {}

    def list_bitable_tables(self, app_token: str) -> List[dict]:
        payload = self.request("GET", f"/bitable/v1/apps/{app_token}/tables")
        return payload.get("data", {}).get("items") or []

    def create_bitable_field(self, app_token: str, table_id: str, field_name: str, field_type: int, property: Optional[dict] = None) -> dict:
        payload = self.request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            json_body={"field_name": field_name, "type": field_type, **({"property": property} if property else {})},
        )
        return payload.get("data", {}).get("field", {})

    def list_bitable_fields(self, app_token: str, table_id: str) -> List[dict]:
        payload = self.request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
        return payload.get("data", {}).get("items") or []

    def delete_bitable_field(self, app_token: str, table_id: str, field_id: str) -> dict:
        payload = self.request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}")
        return payload.get("data", {})

    def update_bitable_field(self, app_token: str, table_id: str, field_id: str, field_name: str, field_type: int, property: Optional[dict] = None) -> dict:
        payload = self.request(
            "PUT",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
            json_body={"field_name": field_name, "type": field_type, **({"property": property} if property else {})},
        )
        return payload.get("data", {}).get("field", {})

    def list_bitable_records(self, app_token: str, table_id: str) -> List[dict]:
        items: List[dict] = []
        page_token = None
        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            payload = self.request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params=params)
            data = payload.get("data", {})
            items.extend(data.get("items") or [])
            page_token = data.get("page_token")
            if not page_token:
                break
        return items

    def create_bitable_record(self, app_token: str, table_id: str, fields: dict) -> dict:
        payload = self.request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body={"fields": fields},
        )
        return payload.get("data", {}).get("record", {})

    def delete_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict:
        payload = self.request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}")
        return payload.get("data", {})


def wiki_url(node_token: str) -> str:
    return f"{DEFAULT_PROJECT_WIKI_URL_PREFIX}{node_token}"


def _clean_group_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return "未命名项目"
    # Feishu group names often already contain 【】; keep them.
    return text.strip()


def project_folder_title(config: dict, manifest: Optional[dict] = None) -> str:
    raw = (
        config.get("feishu_group_name")
        or config.get("group_name")
        or config.get("chat_name")
        or config.get("project_group_name")
        or os.environ.get("FANGCUN_FEISHU_GROUP_NAME")
        or os.environ.get("FANGCUN_GROUP_NAME")
        or (manifest or {}).get("feishu_group_name")
        or (manifest or {}).get("group_name")
        or (manifest or {}).get("chat_name")
        or (manifest or {}).get("project_title")
        or config.get("drama_name")
        or config.get("novel_name")
        or "未命名项目"
    )
    clean = _clean_group_name(raw)
    return clean if clean.endswith("项目文件夹") else f"{clean}项目文件夹"


def resolve_feishu_group_name(client: FeishuProjectExecutor, config: dict, manifest: Optional[dict] = None) -> str:
    """Prefer the actual Feishu group name for project folders.

    If chat_id is available, fetch chat info and cache the name into config for the current run.
    """
    existing = config.get("feishu_group_name") or config.get("group_name") or config.get("chat_name") or (manifest or {}).get("feishu_group_name") or (manifest or {}).get("group_name")
    if existing:
        return str(existing)
    chat_id = config.get("chat_id") or config.get("feishu_chat_id") or (manifest or {}).get("chat_id") or os.environ.get("FANGCUN_FEISHU_CHAT_ID")
    if not chat_id:
        return ""
    try:
        info = client.get_chat_info(str(chat_id))
        name = info.get("name") or info.get("chat", {}).get("name")
        if name:
            config["feishu_group_name"] = name
            return str(name)
    except Exception:
        pass
    return ""


def _find_child_node(nodes: Iterable[dict], title: str, obj_type: Optional[str] = None) -> Optional[dict]:
    for node in nodes:
        if node.get("title") == title and (obj_type is None or node.get("obj_type") == obj_type):
            return node
    return None


def _ensure_bitable_fields(client: FeishuProjectExecutor, app_token: str, fields: List[tuple[str, int]]) -> Optional[str]:
    tables = client.list_bitable_tables(app_token)
    if not tables:
        return None
    table_id = tables[0].get("table_id")
    if not table_id:
        return None
    for field_spec in fields:
        if len(field_spec) == 2:
            field_name, field_type = field_spec
            prop = None
        else:
            field_name, field_type, prop = field_spec
        try:
            client.create_bitable_field(app_token, table_id, field_name, field_type, prop)
        except Exception:
            # Field may already exist or template/default fields may differ; do not block project init.
            pass
    return table_id


def _safe_create_bitable_record(client: FeishuProjectExecutor, app_token: str, table_id: str, fields: dict) -> None:
    try:
        client.create_bitable_record(app_token, table_id, fields)
    except Exception:
        # Template/default schema may differ. Initialization must not block document delivery.
        pass


def _project_title_for_config(config: dict, manifest: dict) -> str:
    return (
        manifest.get("project_title")
        or config.get("drama_name")
        or config.get("novel_name")
        or config.get("project", {}).get("name")
        or "未命名项目"
    )


def _chat_id_for_config(config: dict, manifest: dict) -> str:
    """Return the Feishu group chat_id recorded for this Fangcun project."""
    return str(
        config.get("chat_id")
        or config.get("feishu_chat_id")
        or config.get("group_chat_id")
        or manifest.get("chat_id")
        or manifest.get("feishu_chat_id")
        or os.environ.get("FANGCUN_FEISHU_CHAT_ID")
        or os.environ.get("OPENCLAW_CHAT_ID")
        or ""
    )


def normalize_token_usage_table(client: FeishuProjectExecutor, app_token: str, table_id: str) -> None:
    """Normalize Table 2 to the reference token-usage template exactly.

    Template: OIscbOQJQaf7MasVgsGccyrjndc / tblyC8Ee79rJXgCk
    Required fields, no cost/fee columns:
    序号, usage_date, person, bot_id, chat_id, project, model_provider,
    model, input_tokens, output_tokens, total_tokens, 来源说明
    """
    target = [
        ("序号", 1, None),
        ("usage_date", 5, {"date_formatter": "yyyy-MM-dd", "auto_fill": False}),
        ("person", 1, None),
        ("bot_id", 1, None),
        ("chat_id", 1, None),
        ("project", 1, None),
        ("model_provider", 1, None),
        ("model", 1, None),
        ("input_tokens", 2, {"formatter": "0"}),
        ("output_tokens", 2, {"formatter": "0"}),
        ("total_tokens", 2, {"formatter": "0"}),
        ("来源说明", 3, {"options": [{"name": "用户触发"}, {"name": "自动触发"}]}),
    ]
    rename = {
        "Text": "序号",
        "Date": "usage_date",
        "项目名称": "project",
        "模型": "model",
        "输入tokens": "input_tokens",
        "输出tokens": "output_tokens",
        "总tokens": "total_tokens",
    }
    delete_names = {"Single option", "Attachment", "Attatchment", "费用估算", "费用", "成本", "调用时间", "备注", "skill", "阶段"}

    def target_spec(name: str) -> Optional[tuple[int, Optional[dict]]]:
        for n, t, prop in target:
            if n == name:
                return t, prop
        return None

    try:
        fields = client.list_bitable_fields(app_token, table_id)
    except Exception:
        return

    # Delete fee/default columns first. Table 2 must not contain any cost/fee fields.
    for field in list(fields):
        name = field.get("field_name") or ""
        if name in delete_names or "费用" in name or "成本" in name:
            try:
                client.delete_bitable_field(app_token, table_id, field["field_id"])
            except Exception:
                pass

    try:
        fields = client.list_bitable_fields(app_token, table_id)
    except Exception:
        fields = []

    existing_names = {f.get("field_name") for f in fields}
    # Rename reusable default/legacy columns when the target does not already exist.
    for field in list(fields):
        old_name = field.get("field_name")
        new_name = rename.get(old_name)
        if not new_name or new_name in existing_names:
            continue
        spec = target_spec(new_name)
        if not spec:
            continue
        field_type, prop = spec
        try:
            client.update_bitable_field(app_token, table_id, field["field_id"], new_name, field_type, prop)
            existing_names.discard(old_name)
            existing_names.add(new_name)
        except Exception:
            pass

    try:
        fields = client.list_bitable_fields(app_token, table_id)
    except Exception:
        fields = []
    existing_by_name = {f.get("field_name"): f for f in fields}
    for name, field_type, prop in target:
        field = existing_by_name.get(name)
        if field:
            # Enforce type/properties for fragile fields, especially 来源说明 single-select options.
            try:
                if field.get("type") != field_type or prop:
                    client.update_bitable_field(app_token, table_id, field["field_id"], name, field_type, prop)
            except Exception:
                pass
        else:
            try:
                client.create_bitable_field(app_token, table_id, name, field_type, prop)
            except Exception:
                pass

    target_names = {name for name, _, _ in target}
    try:
        fields = client.list_bitable_fields(app_token, table_id)
    except Exception:
        fields = []
    for field in fields:
        name = field.get("field_name") or ""
        if name not in target_names:
            try:
                client.delete_bitable_field(app_token, table_id, field["field_id"])
            except Exception:
                pass

def cleanup_product_overview_columns(client: FeishuProjectExecutor, app_token: str, table_id: str) -> None:
    """Normalize Table 1 columns after wiki-created bitable default fields appear.

    Required by user/template:
    - Delete empty/default `Single option`, `Date`, `阶段`, `Attachment`, and `Attatchment` columns.
    """
    try:
        fields = client.list_bitable_fields(app_token, table_id)
    except Exception:
        return

    def by_name(name: str) -> Optional[dict]:
        for field in fields:
            if field.get("field_name") == name:
                return field
        return None

    for name in ["Single option", "Date", "阶段", "Attachment", "Attatchment", "备注"]:
        field = by_name(name)
        if field and field.get("field_id"):
            try:
                client.delete_bitable_field(app_token, table_id, field["field_id"])
            except Exception:
                pass


def delete_empty_bitable_records(client: FeishuProjectExecutor, app_token: str, table_id: str) -> int:
    """Delete blank/default Bitable rows so Table 1 starts at row 1 without empty gaps.

    Only rows with no non-empty field values are deleted; user/content rows are preserved.
    """
    try:
        records = client.list_bitable_records(app_token, table_id)
    except Exception:
        return 0
    deleted = 0
    for record in records:
        fields = record.get("fields") or {}
        has_value = False
        for value in fields.values():
            if value in (None, "", [], {}):
                continue
            has_value = True
            break
        if has_value:
            continue
        record_id = record.get("record_id")
        if not record_id:
            continue
        try:
            client.delete_bitable_record(app_token, table_id, record_id)
            deleted += 1
        except Exception:
            pass
    return deleted


def initialize_product_overview_table(client: FeishuProjectExecutor, app_token: str, table_id: str, config: dict, manifest: dict) -> str:
    """Fill Table 1 bootstrap rows from the reference template semantics.

    User rule:
    - Use template NZ8v... only as reference, but strictly follow its fields and first rows.
    - Populate from row 1, not after blank/default rows when possible.
    - The three bootstrap rows share the table creation timestamp in the `时间` field.
    - `BOT ID` row content is the current bot/account id.
    - Insert a `chat_id` row immediately after `BOT ID`; content is the Feishu group chat_id.
    - `剧名` row content is the project title.
    - From row 5, fill fixed Fangcun asset names and their `类型`: row 5 is 用户输入, later asset rows are bot输出, and asset rows 来源说明 are bot自动抓取.
    """
    created_at_ms = int(datetime.now().timestamp() * 1000)
    created_at = datetime.fromtimestamp(created_at_ms / 1000).isoformat(timespec="seconds")
    bot_id = config.get("bot_id") or config.get("agent_id") or os.environ.get("OPENCLAW_AGENT_ID") or os.environ.get("FANGCUN_BOT_ID") or getattr(client, "account", "fangcun")
    chat_id = _chat_id_for_config(config, manifest)
    project_title = _project_title_for_config(config, manifest)
    rows = [
        {"来源说明": "用户手动填写姓名\n", "字段": "编剧", "内容": "请填写编剧姓名", "类型": "项目信息", "时间": created_at_ms},
        {"来源说明": "bot自动抓取", "字段": "BOT ID", "内容": bot_id, "类型": "项目信息", "时间": created_at_ms},
        {"来源说明": "bot自动抓取", "字段": "chat_id", "内容": chat_id, "类型": "项目信息", "时间": created_at_ms},
        {"来源说明": "bot自动抓取", "字段": "剧名", "内容": project_title, "类型": "项目信息", "时间": created_at_ms},
        {"来源说明": "bot自动抓取", "字段": "小说/剧本原文", "类型": "用户输入"},
        {"来源说明": "bot自动抓取", "字段": "改编指引", "类型": "bot输出"},
        {"来源说明": "bot自动抓取", "字段": "改编审核", "类型": "bot输出"},
        {"来源说明": "bot自动抓取", "字段": "故事大纲", "类型": "bot输出"},
        {"来源说明": "bot自动抓取", "字段": "大纲审核", "类型": "bot输出"},
        {"来源说明": "bot自动抓取", "字段": "集纲", "类型": "bot输出"},
        {"来源说明": "bot自动抓取", "字段": "集纲审核", "类型": "bot输出"},
        {"来源说明": "bot自动抓取", "字段": "剧本汇总", "类型": "bot输出"},
    ]
    for row in rows:
        _safe_create_bitable_record(client, app_token, table_id, row)
    return created_at


def ensure_project_workspace(client: FeishuProjectExecutor, config: dict, manifest: dict, state: dict) -> dict:
    """Ensure Fangcun new-project workspace under the configured wiki root.

    New project group rule:
    1. Under configured project wiki root create/use same-name "项目文件夹".
    2. Under that folder create/use two bitables:
       - 表1:业务产物一览
       - 表2：tokens消耗明细表
    3. Subsequent phase docs are created under this project folder as wiki docx nodes.
    """
    ws = state.setdefault("project_workspace", {})
    if ws.get("project_node_token") and ws.get("space_id"):
        return ws

    root_token = (
        config.get("project_wiki_root_token")
        or config.get("feishu_project_wiki", {}).get("root_node_token")
        or DEFAULT_PROJECT_WIKI_ROOT_TOKEN
    )
    root = client.get_wiki_node(root_token)
    space_id = root.get("space_id") or config.get("project_wiki_space_id") or config.get("feishu_project_wiki", {}).get("space_id")
    parent_node_token = root.get("node_token") or root_token
    if not space_id:
        raise FeishuApiError(f"无法解析项目知识库 space_id：root={root_token}, node={root}")

    # Fangcun project folder name must come from the Feishu group name when available.
    resolve_feishu_group_name(client, config, manifest)
    folder_title = project_folder_title(config, manifest)
    children = client.list_wiki_nodes(space_id, parent_node_token)
    folder = _find_child_node(children, folder_title) or client.create_wiki_node(space_id, folder_title, "docx", parent_node_token)
    project_node_token = folder.get("node_token")

    sub_nodes = client.list_wiki_nodes(space_id, project_node_token)
    tables = {}
    table_specs = [
        ("表1:业务产物一览", "product_overview", PRODUCT_OVERVIEW_TEMPLATE_URL, [
            ("字段", 1),
            ("内容", 1),
            ("内容链接", 15),
            ("来源说明", 1),
            ("类型", 3, {"options": [{"name": "项目信息"}, {"name": "用户输入"}, {"name": "bot输出"}]}),
            ("时间", 5, {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False}),
        ]),
        ("表2：tokens消耗明细表", "token_usage", TOKEN_USAGE_TEMPLATE_URL, []),
    ]
    for title, key, template_url, fields in table_specs:
        node = _find_child_node(sub_nodes, title, "bitable") or client.create_wiki_node(space_id, title, "bitable", project_node_token)
        app_token = node.get("obj_token")
        table_id = None
        initialized_at = None
        if app_token:
            table_id = _ensure_bitable_fields(client, app_token, fields)
            if key == "product_overview" and table_id:
                cleanup_product_overview_columns(client, app_token, table_id)
                delete_empty_bitable_records(client, app_token, table_id)
                initialized_at = initialize_product_overview_table(client, app_token, table_id, config, manifest)
            elif key == "token_usage" and table_id:
                normalize_token_usage_table(client, app_token, table_id)
        tables[key] = {
            "title": title,
            "template_url": template_url,
            "node_token": node.get("node_token"),
            "app_token": app_token,
            "table_id": table_id,
            "url": wiki_url(node.get("node_token")),
            **({"initialized_at": initialized_at} if initialized_at else {}),
        }

    ws.update({
        "root_node_token": parent_node_token,
        "space_id": space_id,
        "folder_title": folder_title,
        "project_node_token": project_node_token,
        "project_obj_token": folder.get("obj_token"),
        "project_url": wiki_url(project_node_token),
        "tables": tables,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    return ws


def create_project_doc(client: FeishuProjectExecutor, title: str, config: dict, workspace: Optional[dict]) -> dict:
    """Create a docx under the Fangcun project wiki folder when available."""
    if workspace and workspace.get("space_id") and workspace.get("project_node_token"):
        node = client.create_wiki_node(workspace["space_id"], title, "docx", workspace["project_node_token"])
        return {
            "doc_token": node.get("obj_token"),
            "node_token": node.get("node_token"),
            "title": node.get("title") or title,
            "url": wiki_url(node.get("node_token")),
        }
    return client.create_doc(title, folder_token=config.get("folder_token"))


def strip_markdown_code_fences(text: str) -> str:
    """剥离 Markdown 代码围栏，只保留围栏内部正文。

    Fangcun 的飞书交付物面向业务审核阅读，不允许出现代码块样式。
    这里处理 ```、```markdown、```json、```text 等围栏；不丢弃内容，只删除围栏行。
    """
    out: List[str] = []
    in_fence = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        out.append(line)
    return "\n".join(out)


SCRIPT_DELIVERY_RE = re.compile(r"(?:<scriptItem\b|^\s*\d+[-－]\d+\s+.+?\s+(?:日|夜|晨|午|傍晚|清晨|深夜)\s+(?:内|外)\s*$)", re.M)


def preserve_script_line_breaks_for_docx(text: str) -> str:
    """为剧本飞书 docx 同步保留硬分段。

    飞书 docx 的 markdown convert 会把普通单换行当作软换行，连续的动作行/台词行
    可能在在线文档里糊成一个大段落。剧本交付需要一行一个可拍指令，因此在检测到
    scriptItem 或标准场头时，把每个非空行扩展为独立段落（行后补空行）。
    """
    if not SCRIPT_DELIVERY_RE.search(text or ""):
        return text
    out: List[str] = []
    previous_blank = True
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            previous_blank = True
            continue
        out.append(line)
        out.append("")
        previous_blank = False
    return "\n".join(out).rstrip() + "\n"


def sanitize_markdown_for_docx(markdown: str) -> str:
    """把飞书 docx 交付不允许/不稳定的 markdown 结构降级成普通文本。

    硬规则：所有 fangcun 飞书在线文档不得出现代码块/代码围栏；若源文件带有
    ```、```markdown、```json、```text 等围栏，写入前剥离围栏，只保留正文。

    另一个常见问题是 markdown 表格：convert 能返回 block，但 descendant 写入
    可能 1770001 invalid param。这里把连续表格行转成普通列表，优先保证交付闭环。

    剧本文档额外保留硬分段，避免飞书把单换行动作/台词压成一段。
    """
    markdown = strip_markdown_code_fences(markdown or "")
    markdown = preserve_script_line_breaks_for_docx(markdown)
    lines = markdown.splitlines()
    out: List[str] = []
    table_header: Optional[List[str]] = None

    def is_table_sep(line: str) -> bool:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return bool(cells) and all(c and set(c) <= set("-: ") for c in cells)

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:-1]:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if is_table_sep(stripped):
                continue
            if table_header is None:
                table_header = cells
                out.append("")
                out.append("**表格内容：**")
                continue
            pairs = []
            for idx, cell in enumerate(cells):
                key = table_header[idx] if idx < len(table_header) and table_header[idx] else f"列{idx + 1}"
                pairs.append(f"{key}：{cell}")
            out.append("- " + "；".join(pairs))
            continue
        table_header = None
        out.append(line)
    return "\n".join(out)


def to_descendant_block(block: dict) -> dict:
    """保持飞书 convert 结果结构，确保 children 字段是数组。"""
    out = dict(block)
    children = out.get("children")
    if isinstance(children, str):
        out["children"] = [children]
    elif children is None:
        out.pop("children", None)
    return out


def docx_url(doc_token: str) -> str:
    return f"https://feishu.cn/docx/{doc_token}"


def sync_doc_title(project_title: str, task: str, version: Optional[str] = None) -> str:
    version = version or datetime.now().strftime("v%Y%m%d-r1")
    clean = (project_title or "未命名项目").strip("《》")
    return f"《{clean}》-{task}-{version}"


def get_output_dir(config: dict) -> Path:
    return Path(config.get("output_dir", ".")).resolve()


def state_path(config: dict) -> Path:
    return get_output_dir(config) / "feishu_sync_state.json"


def _version_sort_value(label: str) -> int:
    import re
    text = str(label or "")
    m = re.search(r"(?:^|[-_])r(\d+)$", text, re.I) or re.search(r"^V(\d+)$", text, re.I)
    return int(m.group(1)) if m else 0


def _next_version_label(entry: dict) -> str:
    versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
    max_n = 0
    for item in versions:
        if isinstance(item, dict):
            max_n = max(max_n, _version_sort_value(str(item.get("version") or "")))
    return f"V{max_n + 1}"


def _find_version(entry: dict, version: Optional[str]) -> Optional[dict]:
    versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
    if version:
        for item in versions:
            if isinstance(item, dict) and item.get("version") == version:
                return item
    active = entry.get("active_version")
    if active:
        for item in versions:
            if isinstance(item, dict) and item.get("version") == active:
                return item
    return versions[-1] if versions else None


def _migrate_state_versions(state: dict) -> dict:
    """兼容旧 feishu_sync_state.json：单 doc_token 迁移为 versions[V1]。"""
    state.setdefault("version", 2)
    docs = state.setdefault("docs", {})
    for key, entry in list(docs.items()):
        if not isinstance(entry, dict):
            continue
        versions = entry.get("versions")
        if isinstance(versions, list) and versions:
            entry.setdefault("active_version", versions[-1].get("version"))
            continue
        if entry.get("doc_token"):
            legacy_version = entry.get("version") or "V1"
            migrated = {
                "version": legacy_version,
                "doc_token": entry.get("doc_token"),
                "url": entry.get("url") or docx_url(entry.get("doc_token")),
                "title": entry.get("title") or key,
                "doc_kind": entry.get("doc_kind"),
                "phase": entry.get("phase"),
                "created_at": entry.get("created_at") or entry.get("last_synced_at"),
                "last_synced_at": entry.get("last_synced_at"),
                "operation": entry.get("last_operation") or "migrated_legacy",
            }
            entry["versions"] = [migrated]
            entry["active_version"] = legacy_version
        else:
            entry.setdefault("versions", [])
    return state


def _set_active_entry(entry: dict, version_item: dict) -> None:
    entry["active_version"] = version_item.get("version")
    # Keep legacy top-level fields as read-only convenience pointers to active version.
    for k in ("doc_token", "url", "title", "doc_kind", "phase", "version", "last_operation", "last_synced_at"):
        if k == "version":
            entry[k] = version_item.get("version")
        elif k == "last_operation":
            entry[k] = version_item.get("operation")
        else:
            entry[k] = version_item.get(k)


def load_state(config: dict) -> dict:
    path = state_path(config)
    if path.exists():
        return _migrate_state_versions(json.loads(path.read_text(encoding="utf-8")))
    return {"version": 2, "docs": {}, "updated_at": None}


def save_state(config: dict, state: dict) -> None:
    path = state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp_state_identity(config, state)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_key(step: dict) -> str:
    kind = step.get("doc_kind") or "doc"
    phase = step.get("phase") or kind
    if kind == "script_full":
        return "script_full"
    if kind == "script_batch":
        return f"script_batch:EP{int(step.get('start_episode', 0)):03d}-{int(step.get('end_episode', 0)):03d}"
    if kind == "review":
        return f"review:{step.get('title', '').split('审核报告-', 1)[-1].split('-v', 1)[0]}"
    if kind == "project_info":
        return "project_info"
    return f"{kind}:{phase}"


def _asset_type_from_link(link: dict) -> str:
    key = link.get("key", "")
    kind = link.get("doc_kind") or ""
    if kind == "script_full" or key == "script_full":
        return "script_full"
    if kind == "script_batch" or key.startswith("script_batch:"):
        return "script_batch"
    if kind == "review" or key.startswith("review:"):
        return "review"
    if "adaptation" in key:
        return "adaptation"
    if "story_outline" in key:
        return "outline"
    if "skeleton" in key:
        return "skeleton"
    if kind == "project_info":
        return "other"
    return "other"


def _episode_range_from_key(key: str) -> str:
    if key.startswith("script_batch:"):
        return key.split(":", 1)[1]
    return ""


def format_workspace_links_for_chat(workspace: Optional[dict]) -> str:
    """Return user-facing clickable links for project startup.

    Do not wrap the returned lines in Markdown code fences. Feishu group replies must show
    the project folder and two tables as directly clickable links.
    """
    if not workspace:
        return ""
    tables = workspace.get("tables") or {}
    lines = []
    if workspace.get("project_url"):
        lines.append(f"项目文件夹：[{workspace.get('folder_title') or '项目文件夹'}]({workspace.get('project_url')})")
    product = tables.get("product_overview") or {}
    if product.get("url"):
        lines.append(f"表1：[表1:业务产物一览]({product.get('url')})")
    token_usage = tables.get("token_usage") or {}
    if token_usage.get("url"):
        lines.append(f"表2：[表2：tokens消耗明细表]({token_usage.get('url')})")
    return "\n".join(lines)


def workspace_links(workspace: Optional[dict]) -> List[dict]:
    if not workspace:
        return []
    out = []
    if workspace.get("project_url"):
        out.append({
            "key": "project_workspace",
            "title": workspace.get("folder_title") or "项目文件夹",
            "url": workspace.get("project_url"),
            "operation": "ensure_project_workspace",
            "doc_kind": "project_workspace",
        })
    for key, item in (workspace.get("tables") or {}).items():
        out.append({
            "key": f"project_table:{key}",
            "title": item.get("title") or key,
            "url": item.get("url") or "",
            "operation": "ensure_project_table",
            "doc_kind": "bitable",
            "table_id": item.get("table_id"),
            "app_token": item.get("app_token"),
            "template_url": item.get("template_url"),
        })
    return out


def register_synced_assets(config: dict, manifest: dict, links: Iterable[dict]) -> Optional[str]:
    """Register synced Feishu docs as project text assets.

    This is best-effort and must not break Feishu delivery. It writes metadata
    only, not source text.
    """
    if register_asset is None or write_dashboard is None:
        return None
    import argparse

    output_dir = get_output_dir(config)
    title = manifest.get("project_title") or config.get("drama_name") or config.get("novel_name") or output_dir.name
    project_id = config.get("project_id") or config.get("drama_id") or (output_dir.parent.name if output_dir.name == "drama" and output_dir.parent.name else output_dir.name)
    version = (manifest.get("version") or "r1").split("-", 1)[-1] if manifest.get("version") else "r1"
    for link in links:
        key = link.get("key") or ""
        if key == "project_info":
            continue
        register_asset(argparse.Namespace(
            project_dir=str(output_dir),
            project_id=project_id,
            project_name=title,
            asset_type=_asset_type_from_link(link),
            stage=link.get("doc_kind") or link.get("key") or "sync",
            version=version,
            source="ai",
            status="draft",
            title=link.get("title") or key,
            episode_range=_episode_range_from_key(key),
            local_path="",
            doc_url=link.get("url") or "",
            doc_token=(link.get("url") or "").rstrip("/").split("/")[-1] if link.get("url") else "",
            parent_asset_id="",
            asset_id=f"feishu_{key}".replace(":", "_").replace("/", "_"),
            actor="fangcun-feishu-sync",
            notes=f"operation={link.get('operation', '')}",
        ))
    dashboard = write_dashboard(argparse.Namespace(project_dir=str(output_dir), out=""))
    return str(dashboard)


def build_script_summary_content(manifest: dict) -> str:
    """Build the 飞书「剧本汇总」doc body from script batch正文, never links.

    硬规则：剧本汇总文档必须把所有已同步批次的正文粘贴到同一个文档里，
    禁止只放 batch 文档链接目录。批次链接可留在项目信息/状态文件中，但不能
    作为「剧本汇总」正文。
    """
    project_title = manifest.get("project_title") or "项目"
    batch_steps = [
        s for s in (manifest.get("steps") or [])
        if s.get("doc_kind") == "script_batch" and (s.get("content") or "").strip()
    ]
    if not batch_steps:
        return ""
    batch_steps.sort(key=lambda s: int(s.get("start_episode") or 10**9))
    starts = [int(s.get("start_episode") or 0) for s in batch_steps if s.get("start_episode")]
    ends = [int(s.get("end_episode") or 0) for s in batch_steps if s.get("end_episode")]
    first = min(starts) if starts else 0
    last = max(ends) if ends else 0
    lines = [
        f"# 《{project_title}》剧本汇总 EP{first:03d}-EP{last:03d}" if first and last else f"# 《{project_title}》剧本汇总",
        "",
        "> 本文档为所有剧本 batch 的正文合并稿；禁止只粘贴 batch 文档链接。",
        "",
    ]
    for step in batch_steps:
        start = step.get("start_episode")
        end = step.get("end_episode")
        label = f"EP{int(start):03d}-EP{int(end):03d}" if start and end else (step.get("task") or step.get("title") or "剧本批次")
        lines.extend([f"## {label}", "", (step.get("content") or "").strip(), "", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def validate_script_summary_content(content: str) -> list[str]:
    """Guard against link-only script summary docs."""
    issues: list[str] = []
    if not (content or "").strip():
        issues.append("严重：剧本汇总正文为空，必须粘贴所有 batch 正文。")
        return issues
    url_count = len(re.findall(r"https?://", content))
    script_markers = len(re.findall(r"^\s*(?:#{1,3}\s*)?(?:EP\s*0*\d+|第\s*\d+\s*集)\b", content, flags=re.IGNORECASE | re.MULTILINE))
    scene_markers = len(re.findall(r"^\s*\d+\s*-\s*\d+\s+", content, flags=re.MULTILINE))
    action_markers = content.count("△")
    if url_count and action_markers < max(2, url_count):
        issues.append("严重：剧本汇总疑似只包含 batch 链接，必须把所有 batch 剧本正文粘贴进同一个文档。")
    if script_markers == 0 or scene_markers == 0 or action_markers < 2:
        issues.append("严重：剧本汇总缺少剧本正文特征（分集标识/场次/△动作），禁止同步链接目录。")
    return issues


def validate_script_summary_latest_batches(manifest: dict, docs: dict) -> list[str]:
    """Ensure script summary is built from every known latest active script batch.

    The executor updates each script_batch entry before creating the summary, so
    the latest source of truth is docs[script_batch:*].active_version. Summary
    generation must include all such active batch keys in the current manifest;
    otherwise it may silently omit a newer/older batch.
    """
    issues: list[str] = []
    manifest_batch_keys = {
        stable_key(s)
        for s in (manifest.get("steps") or [])
        if s.get("doc_kind") == "script_batch" and (s.get("content") or "").strip()
    }
    active_batch_keys = {
        key
        for key, entry in (docs or {}).items()
        if str(key).startswith("script_batch:")
        and isinstance(entry, dict)
        and entry.get("active_version")
        and any(isinstance(v, dict) and v.get("doc_kind") == "script_batch" for v in (entry.get("versions") or []))
    }
    missing = sorted(active_batch_keys - manifest_batch_keys)
    if missing:
        issues.append("严重：剧本汇总缺少已登记最新批次正文：" + ", ".join(missing) + "。必须重新生成包含所有最新 active_version 批次的汇总。")
    for key in sorted(manifest_batch_keys):
        entry = (docs or {}).get(key) or {}
        if not entry.get("active_version"):
            issues.append(f"严重：剧本汇总包含 {key}，但同步状态中没有 active_version，无法确认是否为最新版本。")
    return issues


def sync_script_summary_doc(
    *,
    config: dict,
    manifest: dict,
    docs: dict,
    client: Optional[FeishuProjectExecutor],
    dry_run: bool,
    dashboard_path: Optional[str],
    workspace: Optional[dict] = None,
    grant_member: Optional[str] = None,
    grant_member_type: str = "openid",
    grant_perm: str = "full_access",
) -> Optional[tuple[dict, dict]]:
    """Create/update the script summary doc as a Feishu docx.

    Only call this when the manifest was built from an explicit user request to
    汇总/生成剧本汇总. Ordinary script batch sync must not create this doc.
    The local asset dashboard path is kept only as metadata/registry evidence.
    The Feishu document titled「剧本汇总」must contain merged script batch正文,
    never a directory of batch links.
    """
    summary_content = build_script_summary_content(manifest)
    if not summary_content:
        return None
    issues = validate_script_summary_content(summary_content)
    issues.extend(validate_script_summary_latest_batches(manifest, docs))
    if issues:
        raise FeishuApiError("剧本汇总门禁未通过：" + "；".join(issues))
    key = "asset_dashboard"
    entry = docs.setdefault(key, {})
    entry.setdefault("versions", [])
    requested_version = manifest.get("version")
    target_version = requested_version or _next_version_label(entry)
    title = sync_doc_title(manifest.get("project_title") or config.get("drama_name") or config.get("novel_name") or "项目", "剧本汇总", target_version)
    existing_requested = _find_version(entry, target_version) if requested_version else None
    if existing_requested:
        raise FeishuApiError(f"版本 {target_version} 已存在：{key}。如需覆盖，请先显式覆盖普通阶段文档，剧本汇总默认不覆盖历史版本。")
    doc_token = None
    operation = "create_new_version" if entry.get("versions") else "create"
    result = {"dry_run": dry_run, "blocks_deleted": 0, "blocks_added": 0}
    if dry_run:
        url = None
    else:
        if client is None:
            return None
        created = create_project_doc(client, title, config, workspace)
        doc_token = created["doc_token"]
        result = client.write_doc(doc_token, summary_content)
        if grant_member:
            try:
                client.grant_permission(doc_token, grant_member, grant_member_type, grant_perm)
                result["permission_added"] = True
            except Exception as exc:
                result["permission_error"] = str(exc)
        url = created.get("url") or docx_url(doc_token)
    now_iso = datetime.now().isoformat(timespec="seconds")
    version_item = {
        "version": target_version,
        "created_at": now_iso,
        "doc_token": doc_token,
        "url": url,
        "title": title,
        "doc_kind": "asset_dashboard",
        "phase": "asset_dashboard",
        "update_policy": "create_new_version_by_default",
        "operation": operation,
        "last_synced_at": now_iso,
        "local_path": str(dashboard_path) if dashboard_path else "",
        "content_policy": "merged_script_batch_body_only_no_link_directory",
    }
    entry.setdefault("versions", []).append(version_item)
    _set_active_entry(entry, version_item)
    link = {"key": key, "title": title, "url": url, "operation": operation, "doc_kind": "asset_dashboard", "version": target_version}
    op = {**link, **result, "content_policy": version_item["content_policy"]}
    return link, op


def _version_history_lines(docs: dict) -> list[str]:
    # Final summary links are intentionally script-only: non-script deliverables
    # (adaptation guidance, reviews, outlines, asset dashboard, project info) are
    # delivered at their own gated steps and must not be stuffed into the final hub.
    groups = [
        ("剧本分批汇总", lambda key, entry: any((v or {}).get("doc_kind") == "script_batch" for v in entry.get("versions", []))),
    ]
    lines = ["", "## 剧本分批汇总链接（含历史版本）", ""]
    for heading, pred in groups:
        matched = [(k, e) for k, e in docs.items() if isinstance(e, dict) and pred(k, e)]
        if not matched:
            continue
        lines.append(f"### {heading}")
        for key, entry in matched:
            active = entry.get("active_version")
            lines.append(f"- **{key}** 当前推荐版本：{active or '未设置'}")
            versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
            for item in versions:
                if not isinstance(item, dict):
                    continue
                marker = "（当前）" if item.get("version") == active else ""
                title = item.get("title") or key
                url = item.get("url") or ""
                created = item.get("created_at") or item.get("last_synced_at") or ""
                lines.append(f"  - {item.get('version')}{marker}｜{created}｜{title}")
                if url:
                    lines.append(f"    {url}")
        lines.append("")
    return lines


def append_link_index(content: str, links: Iterable[dict], docs: Optional[dict] = None) -> str:
    """Append a dashboard-friendly link index, including all historical versions."""
    if docs:
        return content.rstrip() + "\n" + "\n".join(_version_history_lines(docs)).rstrip() + "\n"
    link_lines = ["", "## 已同步飞书文档链接", ""]
    for item in list(links):
        title = item.get("title") or item.get("key") or "未命名文档"
        url = item.get("url") or ""
        link_lines.append(f"- {title}")
        link_lines.append(f"  {url}")
    return content.rstrip() + "\n" + "\n".join(link_lines).rstrip() + "\n"


def _final_batch_user_confirmed(config: dict) -> tuple[bool, str]:
    output_dir = Path(config.get("output_dir", "."))
    state_path = output_dir / "state.json"
    if not state_path.exists():
        return False, f"state.json 不存在：{state_path}"
    try:
        pipeline_state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"state.json 读取失败：{exc}"
    finished = pipeline_state.get("project_finished") or {}
    if finished.get("user_confirmed") is not True or finished.get("status") != "confirmed":
        return False, "用户尚未明确说“剧本完结/剧本结束/项目结束”，禁止登记完结"
    expected = int((config.get("project") or {}).get("episodes") or config.get("episodes") or 0)
    if expected <= 0:
        return False, "config 未声明总集数，无法确认最终批次"
    for batch in reversed(((pipeline_state.get("script_batches") or {}).get("confirmed") or [])):
        eps = [int(x) for x in (batch.get("episodes") or [])]
        if eps and max(eps) >= expected:
            if batch.get("user_confirmed") is True:
                return True, f"最终批次 {batch.get('batch_id')} 已确认，且项目完结口令已确认：{finished.get('finish_text', '')}"
            return False, f"最终批次 {batch.get('batch_id')} EP{eps[0]:03d}-EP{eps[-1]:03d} 尚未用户确认"
    return False, "未找到覆盖最终集的已提升剧本批次"


def execute_manifest(
    manifest: dict,
    config: dict,
    *,
    dry_run: bool = False,
    account: str = DEFAULT_ACCOUNT,
    major_revision: bool = False,
    new_version: bool = True,
    overwrite_current: bool = False,
    version_label: Optional[str] = None,
    grant_member: Optional[str] = None,
    grant_member_type: str = "openid",
    grant_perm: str = "full_access",
) -> dict:
    """执行 manifest，返回文档链接和状态文件路径。"""
    if manifest.get("status") != "ready":
        return {"status": "skip", "reason": manifest.get("reason") or "manifest not ready"}

    config_path = config.get("_config_path") or manifest.get("config_path")
    if config_path:
        assert_config_binding(config, config_path=config_path, account=account)

    if any((s.get("doc_kind") == "script_full" or s.get("final_delivery")) for s in manifest.get("steps", [])):
        allowed, reason = _final_batch_user_confirmed(config)
        if not allowed:
            return {"status": "blocked", "reason": f"最终批次未获用户确认，禁止登记完结：{reason}"}

    state = load_state(config)
    docs = state.setdefault("docs", {})
    client = None if dry_run else FeishuProjectExecutor(account=account)
    workspace = state.get("project_workspace")
    if not dry_run and client is not None:
        # Bot/account/path are checked before this external write. Project-node
        # existence is checked immediately after workspace initialization.
        workspace = ensure_project_workspace(client, config, manifest, state)
        assert_state_binding(config, state, require_project_node=bool(manifest.get("steps")))
    links: List[dict] = []
    operations: List[dict] = []
    initial_workspace_links = workspace_links(workspace)

    steps = list(manifest.get("steps") or [])
    if not steps:
        return {"status": "skip", "reason": "manifest has no steps"}

    if overwrite_current:
        new_version = False

    # 第一遍：逐文档 create/update。默认新建版本；仅 overwrite_current 覆盖当前推荐版本。
    for step in steps:
        if step.get("action") != "feishu_doc":
            continue
        key = stable_key(step)
        entry = docs.setdefault(key, {})
        entry.setdefault("versions", [])
        requested_version = version_label or manifest.get("version")
        target_version = requested_version or (_next_version_label(entry) if new_version else (entry.get("active_version") or _next_version_label(entry)))
        task = step.get("task") or (step.get("title") or key).split("-", 1)[-1].rsplit("-", 1)[0]
        title = sync_doc_title(manifest.get("project_title") or config.get("drama_name") or config.get("novel_name") or "项目", task, target_version)

        existing_requested = _find_version(entry, target_version) if requested_version else None
        if existing_requested and not overwrite_current:
            raise FeishuApiError(f"版本 {target_version} 已存在：{key}。如需覆盖，必须显式传 --overwrite-current。")
        target_item = _find_version(entry, target_version if overwrite_current else None)
        doc_token = target_item.get("doc_token") if (target_item and overwrite_current) else None
        operation = "update_current" if doc_token else ("create_new_version" if entry.get("versions") else "create")

        created_doc = None
        if dry_run:
            url = docx_url(doc_token) if doc_token else None
            result = {"dry_run": True, "blocks_deleted": 0, "blocks_added": 0}
        else:
            if not doc_token:
                created_doc = create_project_doc(client, title, config, workspace)
                doc_token = created_doc["doc_token"]
            result = client.write_doc(doc_token, step.get("content") or "")
            if grant_member:
                try:
                    client.grant_permission(doc_token, grant_member, grant_member_type, grant_perm)
                    result["permission_added"] = True
                except Exception as exc:  # 不让授权失败吞掉同步结果
                    result["permission_error"] = str(exc)
            url = created_doc.get("url") if created_doc else docx_url(doc_token)

        now_iso = datetime.now().isoformat(timespec="seconds")
        version_item = target_item if (target_item and overwrite_current) else None
        if not version_item:
            version_item = {"version": target_version, "created_at": now_iso}
            entry.setdefault("versions", []).append(version_item)
        version_item.update({
            "doc_token": doc_token,
            "url": url,
            "title": title,
            "doc_kind": step.get("doc_kind"),
            "phase": step.get("phase"),
            "update_policy": step.get("update_policy"),
            "operation": operation,
            "last_synced_at": now_iso,
        })
        if step.get("local_path"):
            version_item["local_path"] = step.get("local_path")
        if step.get("start_episode") and step.get("end_episode"):
            version_item["episode_range"] = f"EP{int(step.get('start_episode')):03d}-EP{int(step.get('end_episode')):03d}"
        if step.get("doc_kind") == "script_full" or step.get("final_delivery"):
            version_item["final_delivery"] = True
            version_item["monitor_evidence"] = {
                "doc_kind": "script_full",
                "stable_key": "script_full",
                "complete_episode_count": int(step.get("end_episode") or 0),
            }
        _set_active_entry(entry, version_item)
        if step.get("doc_kind") == "script_full" or step.get("final_delivery"):
            state["script_full"] = {
                "key": key,
                "doc_kind": "script_full",
                "doc_token": doc_token,
                "url": url,
                "title": title,
                "version": target_version,
                "local_path": step.get("local_path"),
                "episode_range": version_item.get("episode_range"),
                "final_delivery": True,
                "created_at": now_iso,
            }
            state["final_delivery"] = {
                "status": "confirmed",
                "key": key,
                "doc_kind": "script_full",
                "doc_token": doc_token,
                "url": url,
                "title": title,
                "version": target_version,
                "confirmed_at": now_iso,
                "episode_range": version_item.get("episode_range"),
            }
        link = {"key": key, "title": title, "url": url, "operation": operation, "doc_kind": step.get("doc_kind"), "version": target_version}
        links.append(link)
        operations.append({**link, **result})

    # 第二遍：资产登记只写本地 registry；普通剧本批次同步不得自动生成飞书「剧本汇总」。
    # 只有 manifest.generate_script_summary=True（用户明确说“汇总/生成剧本汇总”）时，才创建飞书汇总文档。
    has_script_output = any(s.get("doc_kind") in ("script_batch", "script_full") or s.get("phase") in ("script", "script_full") for s in steps)
    asset_dashboard_path = None
    if has_script_output:
        asset_dashboard_path = register_synced_assets(config, manifest, links)

        if manifest.get("generate_script_summary") is True:
            dashboard_sync = sync_script_summary_doc(
                config=config,
                manifest=manifest,
                docs=docs,
                client=client,
                dry_run=dry_run,
                dashboard_path=asset_dashboard_path,
                workspace=workspace,
                grant_member=grant_member,
                grant_member_type=grant_member_type,
                grant_perm=grant_perm,
            )
            if dashboard_sync:
                dash_link, dash_operation = dashboard_sync
                links.append(dash_link)
                operations.append(dash_operation)

    # 第四遍：项目信息文档补真实链接索引（普通阶段不包含剧本汇总）。
    project_steps = [s for s in steps if s.get("doc_kind") == "project_info"]
    project_entry = docs.get("project_info")
    if project_steps and project_entry and project_entry.get("doc_token") and not dry_run:
        hub_content = append_link_index(project_steps[0].get("content") or "", links, docs)
        result = client.write_doc(project_entry["doc_token"], hub_content)
        operations.append({
            "key": "project_info",
            "title": project_entry.get("title"),
            "url": project_entry.get("url"),
            "operation": "update_link_index",
            **result,
        })

    if not dry_run:
        save_state(config, state)
    return {
        "status": "ok",
        "dry_run": dry_run,
        "state_path": str(state_path(config)),
        "asset_registry_path": str(get_output_dir(config) / "project_assets.json") if asset_dashboard_path else None,
        "asset_dashboard_path": asset_dashboard_path,
        "project_workspace": workspace,
        "links": initial_workspace_links + links,
        "operations": initial_workspace_links + operations,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="执行 fangcun 飞书项目 manifest")
    parser.add_argument("manifest", help="manifest JSON 文件路径")
    parser.add_argument("--config", required=True, help="项目 config.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--major-revision", action="store_true", help="兼容旧参数；不再归档旧文档，默认仍创建新版本")
    parser.add_argument("--new-version", action="store_true", default=True, help="创建新版本（默认行为）")
    parser.add_argument("--overwrite-current", action="store_true", help="危险操作：覆盖当前推荐版本，只有显式传入才允许 update 原 doc_token")
    parser.add_argument("--version-label", help="指定版本号，如 V2 或 v20260716-r2")
    parser.add_argument("--grant-member")
    parser.add_argument("--grant-member-type", default="openid")
    parser.add_argument("--grant-perm", default="full_access")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["_config_path"] = str(config_path)
    print(json.dumps(execute_manifest(
        manifest,
        config,
        dry_run=args.dry_run,
        account=args.account,
        major_revision=args.major_revision,
        new_version=args.new_version,
        overwrite_current=args.overwrite_current,
        version_label=args.version_label,
        grant_member=args.grant_member,
        grant_member_type=args.grant_member_type,
        grant_perm=args.grant_perm,
    ), ensure_ascii=False, indent=2))
