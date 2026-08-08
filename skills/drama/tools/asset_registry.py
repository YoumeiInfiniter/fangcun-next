#!/usr/bin/env python3
"""Project text asset registry for Fangcun drama workflow.

MVP goal:
- Keep a project-local project_assets.json index.
- Register AI/human/imported outputs by stage and version.
- Provide a markdown dashboard that can later be synced to Feishu docx.

This module intentionally stores metadata and links, not full source text.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ASSET_TYPES = {
    "adaptation",
    "outline",
    "skeleton",
    "script_batch",
    "script_full",
    "review",
    "human_revision",
    "translation",
    "other",
}

STATUSES = {"draft", "reviewing", "approved", "archived", "blocked"}
SOURCES = {"ai", "human", "imported"}


@dataclass
class TextAsset:
    asset_id: str
    project_id: str
    project_name: str
    asset_type: str
    stage: str
    version: str
    source: str
    status: str
    title: str
    episode_range: str = ""
    local_path: str = ""
    doc_url: str = ""
    doc_token: str = ""
    parent_asset_id: str = ""
    created_by: str = ""
    updated_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def registry_path(project_dir: Path) -> Path:
    return project_dir / "project_assets.json"


def load_registry(project_dir: Path) -> dict[str, Any]:
    path = registry_path(project_dir)
    if not path.exists():
        return {"schema_version": 1, "assets": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(project_dir: Path, data: dict[str, Any]) -> None:
    path = registry_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise SystemExit(f"invalid {name}: {value}; allowed={sorted(allowed)}")


def final_delivery_allowed(project_dir: Path) -> tuple[bool, str]:
    """script_full assets may only be registered after explicit project finish.

    Final batch confirmation accepts the delivered episodes; it is not project
    completion because users may keep revising batches. Completion requires the
    user to say 剧本完结/剧本结束/项目结束 and for that to be recorded in state.json.
    """
    state_path = project_dir / "state.json"
    if not state_path.exists():
        return False, f"state.json 不存在：{state_path}"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"state.json 读取失败：{exc}"
    finished = state.get("project_finished") or {}
    if finished.get("user_confirmed") is not True or finished.get("status") != "confirmed":
        return False, "用户尚未明确说“剧本完结/剧本结束/项目结束”，禁止登记完结"
    batches = ((state.get("script_batches") or {}).get("confirmed") or [])
    if not batches:
        return False, "没有已提升的剧本批次"
    batch = batches[-1]
    if batch.get("user_confirmed") is True:
        return True, f"最终批次 {batch.get('batch_id')} 已确认，且项目完结口令已确认：{finished.get('finish_text', '')}"
    eps = batch.get("episodes") or []
    label = f"EP{int(eps[0]):03d}-EP{int(eps[-1]):03d}" if eps else batch.get("batch_id", "latest")
    return False, f"最终批次 {label} 尚未用户确认"


def register_asset(args: argparse.Namespace) -> TextAsset:
    project_dir = Path(args.project_dir).resolve()
    data = load_registry(project_dir)
    validate_choice("asset_type", args.asset_type, ASSET_TYPES)
    if args.asset_type == "script_full":
        allowed, reason = final_delivery_allowed(project_dir)
        if not allowed:
            raise SystemExit(f"最终批次未获用户确认，禁止登记 script_full：{reason}")
    validate_choice("source", args.source, SOURCES)
    validate_choice("status", args.status, STATUSES)
    ts = now_iso()
    asset = TextAsset(
        asset_id=args.asset_id or f"asset_{uuid.uuid4().hex[:12]}",
        project_id=args.project_id,
        project_name=args.project_name,
        asset_type=args.asset_type,
        stage=args.stage,
        version=args.version,
        source=args.source,
        status=args.status,
        title=args.title,
        episode_range=args.episode_range or "",
        local_path=args.local_path or "",
        doc_url=args.doc_url or "",
        doc_token=args.doc_token or "",
        parent_asset_id=args.parent_asset_id or "",
        created_by=args.actor or "",
        updated_by=args.actor or "",
        created_at=ts,
        updated_at=ts,
        notes=args.notes or "",
    )
    assets = data.setdefault("assets", [])
    # Upsert by explicit asset_id; otherwise append.
    for i, item in enumerate(assets):
        if item.get("asset_id") == asset.asset_id:
            prev_created_at = item.get("created_at") or asset.created_at
            prev_created_by = item.get("created_by") or asset.created_by
            updated = asdict(asset)
            updated["created_at"] = prev_created_at
            updated["created_by"] = prev_created_by
            assets[i] = updated
            break
    else:
        assets.append(asdict(asset))
    save_registry(project_dir, data)
    return asset


def dashboard_markdown(project_dir: Path) -> str:
    data = load_registry(project_dir)
    assets = data.get("assets", [])
    project_name = assets[0].get("project_name") if assets else project_dir.name
    lines = [
        f"# 《{project_name}》文本资产 Dashboard",
        "",
        "| 类型 | 阶段 | 集数 | 版本 | 来源 | 状态 | 标题 | 链接 | 更新时间 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a in assets:
        link = a.get("doc_url") or a.get("local_path") or ""
        lines.append(
            "| {asset_type} | {stage} | {episode_range} | {version} | {source} | {status} | {title} | {link} | {updated_at} |".format(
                asset_type=a.get("asset_type", ""),
                stage=a.get("stage", ""),
                episode_range=a.get("episode_range", ""),
                version=a.get("version", ""),
                source=a.get("source", ""),
                status=a.get("status", ""),
                title=(a.get("title", "") or "").replace("|", "/"),
                link=link,
                updated_at=a.get("updated_at", ""),
            )
        )
    return "\n".join(lines) + "\n"


def write_dashboard(args: argparse.Namespace) -> Path:
    project_dir = Path(args.project_dir).resolve()
    out = Path(args.out).resolve() if args.out else project_dir / "project_assets_dashboard.md"
    out.write_text(dashboard_markdown(project_dir), encoding="utf-8")
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Fangcun project text asset registry")
    sub = ap.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register")
    reg.add_argument("--project-dir", required=True)
    reg.add_argument("--project-id", required=True)
    reg.add_argument("--project-name", required=True)
    reg.add_argument("--asset-type", required=True)
    reg.add_argument("--stage", required=True)
    reg.add_argument("--version", default="r1")
    reg.add_argument("--source", default="ai")
    reg.add_argument("--status", default="draft")
    reg.add_argument("--title", required=True)
    reg.add_argument("--episode-range", default="")
    reg.add_argument("--local-path", default="")
    reg.add_argument("--doc-url", default="")
    reg.add_argument("--doc-token", default="")
    reg.add_argument("--parent-asset-id", default="")
    reg.add_argument("--asset-id", default="")
    reg.add_argument("--actor", default="")
    reg.add_argument("--notes", default="")

    dash = sub.add_parser("dashboard")
    dash.add_argument("--project-dir", required=True)
    dash.add_argument("--out", default="")
    return ap


def main() -> None:
    args = build_parser().parse_args()
    if args.cmd == "register":
        asset = register_asset(args)
        print(json.dumps(asdict(asset), ensure_ascii=False, indent=2))
    elif args.cmd == "dashboard":
        out = write_dashboard(args)
        print(out)


if __name__ == "__main__":
    main()
