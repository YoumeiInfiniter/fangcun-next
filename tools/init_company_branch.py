#!/usr/bin/env python3
"""Initialize a long-lived company branch for Fangcun delivery.

What it does when not in --dry-run mode:
1. Ensure git worktree is clean.
2. Checkout base branch (default main).
3. Create or checkout company/<slug> branch.
4. Write a non-secret company profile placeholder under skills/fangcun/company-profiles/<slug>/.
5. Commit the profile if changed.
6. Optionally build the first delivery ZIP.

This script does not push. Push remains explicit and protected by the repo's
pre-push hook.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
FANGCUN = ROOT / "skills" / "fangcun"


def safe_slug(text: str) -> str:
    text = (text or "company").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-._") or "company"


def run(cmd: list[str], *, dry_run: bool = False, capture: bool = False) -> str:
    printable = " ".join(cmd)
    if dry_run:
        print(f"[DRY-RUN] {printable}")
        return ""
    if capture:
        return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()
    subprocess.run(cmd, cwd=ROOT, check=True)
    return ""


def git(args: Iterable[str], *, dry_run: bool = False, capture: bool = False) -> str:
    return run(["git", *args], dry_run=dry_run, capture=capture)


def current_branch() -> str:
    try:
        return git(["branch", "--show-current"], capture=True) or "detached"
    except Exception:
        return "unknown"


def ensure_clean(*, allow_dirty: bool = False) -> None:
    if allow_dirty:
        return
    status = git(["status", "--porcelain"], capture=True)
    if status.strip():
        raise SystemExit("git worktree is dirty; commit/stash first or pass --allow-dirty")


def branch_exists(branch: str) -> bool:
    res = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


def write_company_profile(company: str, slug: str, branch: str, *, dry_run: bool = False) -> list[Path]:
    profile_dir = FANGCUN / "company-profiles" / slug
    files = [profile_dir / "PROFILE.md", profile_dir / "company.json"]
    if dry_run:
        for p in files:
            print(f"[DRY-RUN] write {p.relative_to(ROOT)}")
        return files

    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "PROFILE.md").write_text(f"""# {company} 公司配置占位

- 公司 slug：`{slug}`
- 分支：`{branch}`
- 交付类型：统一交付
- 初始化时间：{datetime.now().isoformat(timespec='seconds')}

## 用途

此目录只存放该公司的非敏感交付配置和私有定制说明。

## 禁止写入

- token / secret / 私钥
- 客户原文素材
- 剧本项目产物
- 数据库 / 日志 / 缓存
- 个人账号凭据

## 私有定制记录

后续如需给该公司增加私有能力，请在此记录：

```text
日期：
能力：
影响文件：
是否进入 main：否
```
""", encoding="utf-8")

    data = {
        "schema_version": 2,
        "company": company,
        "company_slug": slug,
        "branch": branch,
        "delivery_type": "unified",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "non_secret_only": True,
        "notes": "Company-specific private config placeholder. Do not store secrets or customer source material here.",
    }
    (profile_dir / "company.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return files


def build_delivery(company: str, version: str, *, dry_run: bool = False, smoke_test: bool = False) -> None:
    cmd = [
        "python3",
        str(FANGCUN / "tools" / "build_company_delivery.py"),
        "--company", company,
    ]
    if version:
        cmd.extend(["--version", version])
    if smoke_test:
        cmd.append("--smoke-test")
    run(cmd, dry_run=dry_run)


def main() -> None:
    ap = argparse.ArgumentParser(description="Initialize Fangcun company branch")
    ap.add_argument("--company", required=True, help="company display name")
    ap.add_argument("--base", default="main", help="base branch, default main")
    ap.add_argument("--branch", default="", help="branch name, default company/<slug>")
    ap.add_argument("--version", default="", help="first delivery version, default build script date version")
    ap.add_argument("--build-delivery", action="store_true", help="build first delivery zip after branch init")
    ap.add_argument("--smoke-test", action="store_true", help="run delivery smoke test after building first zip")
    ap.add_argument("--reset-existing", action="store_true", help="reset existing company branch to base before writing profile")
    ap.add_argument("--return-to-original", action="store_true", help="checkout original branch at the end")
    ap.add_argument("--allow-dirty", action="store_true", help="allow running with dirty worktree (not recommended)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    slug = safe_slug(args.company)
    branch = args.branch or f"company/{slug}"
    if not (branch == "main" or branch.startswith("company/")):
        raise SystemExit("branch must be main or company/<name> to match pre-push policy")

    original = current_branch()
    ensure_clean(allow_dirty=args.allow_dirty or args.dry_run)

    print(json.dumps({
        "company": args.company,
        "company_slug": slug,
        "delivery_type": "unified",
        "base": args.base,
        "branch": branch,
        "original_branch": original,
        "dry_run": args.dry_run,
    }, ensure_ascii=False, indent=2))

    git(["checkout", args.base], dry_run=args.dry_run)
    exists = branch_exists(branch) if not args.dry_run else False
    if exists and args.reset_existing:
        git(["checkout", branch], dry_run=args.dry_run)
        git(["reset", "--hard", args.base], dry_run=args.dry_run)
    elif exists:
        git(["checkout", branch], dry_run=args.dry_run)
    else:
        git(["checkout", "-b", branch, args.base], dry_run=args.dry_run)

    files = write_company_profile(args.company, slug, branch, dry_run=args.dry_run)
    rels = [str(p.relative_to(ROOT)) for p in files]
    git(["add", *rels], dry_run=args.dry_run)

    if args.dry_run:
        print(f"[DRY-RUN] git commit -m 'init company branch {slug}'")
    else:
        status = git(["status", "--porcelain"], capture=True)
        if status.strip():
            git(["commit", "-m", f"init company branch {slug}"], dry_run=False)
        else:
            print("[OK] no profile changes to commit")

    if args.build_delivery:
        build_delivery(args.company, args.version, dry_run=args.dry_run, smoke_test=args.smoke_test)

    if args.return_to_original and original not in ("", "detached", "unknown"):
        git(["checkout", original], dry_run=args.dry_run)

    print("[OK] company branch initialization complete")


if __name__ == "__main__":
    main()
