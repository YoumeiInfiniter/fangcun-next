#!/usr/bin/env python3
"""Local registry helper for feishu-artifact-sync.

This script intentionally does NOT call Feishu APIs. The agent uses first-class
feishu_doc/feishu_perm tools for network writes; this helper only handles
version naming, hashes, registry mutation, and safe local pull writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "feishu-artifact-sync.v1"
TZ = dt.timezone(dt.timedelta(hours=8))


def now_iso() -> str:
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_id(project: str, stage: str, local_path: str) -> str:
    raw = f"{project}|{stage}|{local_path}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "artifacts": []}
    data = json.loads(path.read_text("utf-8"))
    data.setdefault("schema", SCHEMA)
    data.setdefault("artifacts", [])
    return data


def save_registry(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    tmp.replace(path)


def find_artifact(data: dict[str, Any], aid: str) -> dict[str, Any] | None:
    for item in data.get("artifacts", []):
        if item.get("artifact_id") == aid:
            return item
    return None


def find_by_doc(data: dict[str, Any], doc_token: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for art in data.get("artifacts", []):
        for ver in art.get("versions", []):
            if ver.get("doc_token") == doc_token:
                return art, ver
    return None


def cmd_next(args: argparse.Namespace) -> None:
    local = Path(args.local_path)
    if not local.exists():
        raise SystemExit(f"local_path not found: {local}")
    data = load_registry(Path(args.registry))
    aid = artifact_id(args.project, args.stage, str(local))
    art = find_artifact(data, aid)
    n = len(art.get("versions", [])) + 1 if art else 1
    version = f"v{n:03d}"
    title = args.title or f"《{args.project}》{args.stage} {version}｜{args.label}"
    print(json.dumps({
        "artifact_id": aid,
        "version": version,
        "title": title,
        "local_path": str(local),
        "local_sha256": sha256_file(local),
        "local_bytes": local.stat().st_size,
    }, ensure_ascii=False, indent=2))


def cmd_record(args: argparse.Namespace) -> None:
    local = Path(args.local_path)
    if not local.exists():
        raise SystemExit(f"local_path not found: {local}")
    reg = Path(args.registry)
    data = load_registry(reg)
    aid = args.artifact_id or artifact_id(args.project, args.stage, str(local))
    art = find_artifact(data, aid)
    if art is None:
        art = {
            "artifact_id": aid,
            "project": args.project,
            "stage": args.stage,
            "local_path": str(local),
            "versions": [],
        }
        data["artifacts"].append(art)
    version = args.version or f"v{len(art.get('versions', [])) + 1:03d}"
    item = {
        "version": version,
        "label": args.label,
        "doc_token": args.doc_token,
        "url": args.url or f"https://feishu.cn/docx/{args.doc_token}",
        "title": args.title,
        "local_sha256": sha256_file(local),
        "local_bytes": local.stat().st_size,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "pulled_from_doc_at": None,
        "backup_path": None,
    }
    art.setdefault("versions", []).append(item)
    save_registry(reg, data)
    print(json.dumps({"recorded": True, "artifact_id": aid, "version": version, "url": item["url"]}, ensure_ascii=False, indent=2))


def cmd_pull(args: argparse.Namespace) -> None:
    reg = Path(args.registry)
    data = load_registry(reg)
    found = find_by_doc(data, args.doc_token)
    if not found:
        raise SystemExit(f"doc_token not found in registry: {args.doc_token}")
    art, ver = found
    local = Path(args.local_path or art["local_path"])
    content = Path(args.content_file).read_text("utf-8")
    ts = dt.datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    backup = local.with_name(local.name + f".bak.{ts}")
    local.parent.mkdir(parents=True, exist_ok=True)
    if local.exists():
        shutil.copy2(local, backup)
    local.write_text(content, "utf-8")
    ver["pulled_from_doc_at"] = now_iso()
    ver["backup_path"] = str(backup) if backup.exists() else None
    ver["updated_at"] = now_iso()
    ver["local_sha256"] = sha256_file(local)
    ver["local_bytes"] = local.stat().st_size
    save_registry(reg, data)
    print(json.dumps({"pulled": True, "local_path": str(local), "backup_path": ver["backup_path"]}, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    data = load_registry(Path(args.registry))
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("next")
    n.add_argument("--registry", default="memory/feishu-artifact-sync.json")
    n.add_argument("--local-path", required=True)
    n.add_argument("--project", required=True)
    n.add_argument("--stage", required=True)
    n.add_argument("--label", default="验收版")
    n.add_argument("--title")
    n.set_defaults(func=cmd_next)

    r = sub.add_parser("record")
    r.add_argument("--registry", default="memory/feishu-artifact-sync.json")
    r.add_argument("--local-path", required=True)
    r.add_argument("--project", required=True)
    r.add_argument("--stage", required=True)
    r.add_argument("--label", default="验收版")
    r.add_argument("--artifact-id")
    r.add_argument("--version")
    r.add_argument("--doc-token", required=True)
    r.add_argument("--url")
    r.add_argument("--title", required=True)
    r.set_defaults(func=cmd_record)

    pull = sub.add_parser("pull")
    pull.add_argument("--registry", default="memory/feishu-artifact-sync.json")
    pull.add_argument("--doc-token", required=True)
    pull.add_argument("--content-file", required=True)
    pull.add_argument("--local-path")
    pull.set_defaults(func=cmd_pull)

    s = sub.add_parser("status")
    s.add_argument("--registry", default="memory/feishu-artifact-sync.json")
    s.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
