#!/usr/bin/env python3
"""Build a company delivery ZIP for Fangcun skill.

The package includes the full public Fangcun skill and delivery metadata. It
intentionally does not include runtime project files, customer data, logs,
state, databases, secrets, or OpenClaw agent identity files.

Example:
  python3 skills/fangcun/tools/build_company_delivery.py --company acme
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DELIVERY_DIR = ROOT / "deliveries"
DEFAULT_EXCLUDE = [
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.DS_Store",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*.log",
    "**/*.token",
    "**/*.secret",
    "**/*.key",
    "**/*.pem",
    "**/*.bak",
    "**/*.bak.*",
]


def safe_slug(text: str) -> str:
    text = (text or "company").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = text.strip("-._")
    return text or "company"


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def git_branch() -> str:
    try:
        return subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() or "detached"
    except Exception:
        return "unknown"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def matches(path: Path, patterns: list[str]) -> bool:
    s = path.as_posix()
    for pat in patterns:
        if fnmatch.fnmatch(s, pat):
            return True
        if pat.endswith("/**") and (s == pat[:-3] or s.startswith(pat[:-2])):
            return True
    return False


def fangcun_files() -> list[Path]:
    base = ROOT / "skills" / "fangcun"
    rows: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if matches(rel, DEFAULT_EXCLUDE):
            continue
        rows.append(rel)
    return sorted(rows)


def copy_skill(out: Path) -> None:
    files = fangcun_files()
    if not files:
        raise SystemExit("no Fangcun files selected for delivery")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel in files:
        src = ROOT / rel
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def collect_files(base: Path) -> list[dict]:
    rows = []
    for p in sorted(base.rglob("*")):
        if p.is_file():
            rel = p.relative_to(base).as_posix()
            rows.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256(p)})
    return rows


def write_delivery_readme(out: Path, *, company: str, version: str, commit: str) -> None:
    content = f"""# 方寸短剧改编引擎交付包

- 公司：{company}
- 交付类型：统一交付
- 版本：{version}
- Git commit：{commit}

## 内容

本交付包只包含 Fangcun skill 文件和交付元数据，不包含客户素材、项目产物、日志、数据库、token、私钥或 OpenClaw 主 Agent 配置。

目录：

```text
skills/fangcun/        # skill 主体
DELIVERY_MANIFEST.json # 交付清单
CHECKSUMS.sha256       # 文件校验
README_DELIVERY.md     # 本说明
```

## 安装建议

把 `skills/fangcun/` 复制到目标 OpenClaw agent workspace 的 `skills/fangcun/`。

示例：

```bash
unzip {out.name}.zip -d /tmp/fangcun-delivery
cp -a /tmp/fangcun-delivery/skills/fangcun <目标workspace>/skills/
```

## 验收

1. 确认 `DELIVERY_MANIFEST.json` 中 `company`、`delivery_type`、`git_commit` 正确。
2. 使用 `CHECKSUMS.sha256` 校验文件完整性。
3. 在目标环境运行 smoke test 或至少执行 `python3 -m py_compile` 检查工具脚本。
"""
    (out / "README_DELIVERY.md").write_text(content, encoding="utf-8")


def prune_company_private(package_dir: Path, company_slug: str) -> None:
    """Keep only the target company's optional profile/private directories."""
    for rel_root in ["skills/fangcun/company-profiles", "skills/fangcun/company-private"]:
        base = package_dir / rel_root
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and child.name != company_slug:
                shutil.rmtree(child)


def make_zip(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir).as_posix())


def build_delivery(company: str, version: str | None = None, out_dir: Path | None = None) -> dict:
    slug = safe_slug(company)
    version = version or datetime.now().strftime("v%Y%m%d-r1")
    commit = git_commit()
    branch = git_branch()
    out_root = out_dir or DELIVERY_DIR
    package_dir = out_root / f"fangcun-{slug}-{version}"

    copy_skill(package_dir)
    prune_company_private(package_dir, slug)
    write_delivery_readme(package_dir, company=company, version=version, commit=commit)

    files = collect_files(package_dir)
    manifest = {
        "schema_version": 2,
        "product": "fangcun",
        "company": company,
        "company_slug": slug,
        "delivery_type": "unified",
        "version": version,
        "git_commit": commit,
        "git_branch": branch,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(files),
        "files": files,
        "excludes": [
            "customer source material",
            "project outputs",
            "runtime state",
            "logs",
            "databases",
            "tokens/secrets/private keys",
            "OpenClaw agent identity files",
            "version-level split manifests",
        ],
    }
    (package_dir / "DELIVERY_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    files = collect_files(package_dir)
    checksums = "".join(f"{item['sha256']}  {item['path']}\n" for item in files)
    (package_dir / "CHECKSUMS.sha256").write_text(checksums, encoding="utf-8")

    zip_path = out_root / f"fangcun-{slug}-{version}.zip"
    make_zip(package_dir, zip_path)

    return {
        "status": "ok",
        "company": company,
        "delivery_type": "unified",
        "version": version,
        "package_dir": str(package_dir),
        "zip_path": str(zip_path),
        "zip_sha256": sha256(zip_path),
        "git_commit": commit,
        "file_count": len(files),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Fangcun company delivery zip")
    ap.add_argument("--company", required=True, help="company/customer name or slug")
    ap.add_argument("--version", default="", help="delivery version, default vYYYYMMDD-r1")
    ap.add_argument("--out-dir", default="", help="output root, default ./deliveries")
    ap.add_argument("--smoke-test", action="store_true", help="run smoke_test_delivery.py after building")
    args = ap.parse_args()
    result = build_delivery(
        args.company,
        version=args.version or None,
        out_dir=Path(args.out_dir).resolve() if args.out_dir else None,
    )
    if args.smoke_test:
        smoke_cmd = [
            "python3", str(ROOT / "skills" / "fangcun" / "tools" / "smoke_test_delivery.py"), result["zip_path"],
            "--expected-company", args.company,
            "--check-isolation",
        ]
        subprocess.run(smoke_cmd, cwd=ROOT, check=True)
        result["smoke_test"] = "ok"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
