#!/usr/bin/env python3
"""Check Fangcun company-private isolation.

Use cases:
- main branch: fail if any company profile/private directory leaked into main.
- delivery package: fail if a company delivery contains profiles for another company.
- branch/package: warn/fail on obvious secret-like filenames.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROFILE_ROOT = Path("skills/fangcun/company-profiles")
PRIVATE_ROOT = Path("skills/fangcun/company-private")
SECRET_FILE_RE = re.compile(r"(\.env|\.token|\.secret|\.key|\.pem|\.p12|\.pfx)$", re.I)


def safe_slug(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-._")


def fail(msg: str) -> None:
    raise SystemExit(f"[FAIL] {msg}")


def extract_if_zip(path: Path) -> tuple[Path, Path | None]:
    if path.is_dir():
        return path, None
    if not zipfile.is_zipfile(path):
        fail(f"not a directory or zip: {path}")
    tmp = Path(tempfile.mkdtemp(prefix="fangcun_isolation_"))
    with zipfile.ZipFile(path) as zf:
        zf.extractall(tmp)
    return tmp, tmp


def list_dirs(root: Path, rel_root: Path) -> list[str]:
    base = root / rel_root
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def secret_like_files(root: Path) -> list[str]:
    bad = []
    for p in root.rglob("*"):
        if p.is_file() and SECRET_FILE_RE.search(p.name):
            bad.append(p.relative_to(root).as_posix())
    return bad


def check_main(root: Path) -> dict:
    profiles = list_dirs(root, PROFILE_ROOT)
    private = list_dirs(root, PRIVATE_ROOT)
    secrets = secret_like_files(root)
    errors = []
    if profiles:
        errors.append(f"main contains company profiles: {profiles}")
    if private:
        errors.append(f"main contains company-private dirs: {private}")
    if secrets:
        errors.append(f"secret-like files found: {secrets[:20]}")
    if errors:
        fail("; ".join(errors))
    return {"mode": "main", "profiles": profiles, "private": private, "secret_like_files": secrets}


def check_delivery(root: Path, expected_company: str) -> dict:
    slug = safe_slug(expected_company)
    if not slug:
        fail("--expected-company is required in delivery mode")
    profiles = list_dirs(root, PROFILE_ROOT)
    private = list_dirs(root, PRIVATE_ROOT)
    secrets = secret_like_files(root)
    errors = []
    foreign_profiles = [x for x in profiles if x != slug]
    foreign_private = [x for x in private if x != slug]
    if foreign_profiles:
        errors.append(f"foreign company profiles in delivery: {foreign_profiles}")
    if foreign_private:
        errors.append(f"foreign company-private dirs in delivery: {foreign_private}")
    if secrets:
        errors.append(f"secret-like files found: {secrets[:20]}")
    if errors:
        fail("; ".join(errors))
    return {
        "mode": "delivery",
        "expected_company": slug,
        "profiles": profiles,
        "private": private,
        "secret_like_files": secrets,
    }


def check_branch(root: Path, expected_company: str = "") -> dict:
    slug = safe_slug(expected_company)
    profiles = list_dirs(root, PROFILE_ROOT)
    private = list_dirs(root, PRIVATE_ROOT)
    secrets = secret_like_files(root)
    errors = []
    if slug:
        foreign_profiles = [x for x in profiles if x != slug]
        foreign_private = [x for x in private if x != slug]
        if foreign_profiles:
            errors.append(f"branch has foreign company profiles: {foreign_profiles}")
        if foreign_private:
            errors.append(f"branch has foreign company-private dirs: {foreign_private}")
    if secrets:
        errors.append(f"secret-like files found: {secrets[:20]}")
    if errors:
        fail("; ".join(errors))
    return {
        "mode": "branch",
        "expected_company": slug or None,
        "profiles": profiles,
        "private": private,
        "secret_like_files": secrets,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Check Fangcun company-private isolation")
    ap.add_argument("path", nargs="?", default=str(ROOT), help="repo/package directory or delivery zip")
    ap.add_argument("--mode", choices=["main", "delivery", "branch"], default="delivery")
    ap.add_argument("--expected-company", default="")
    args = ap.parse_args()

    path = Path(args.path).resolve()
    root, tmp = extract_if_zip(path)
    try:
        if args.mode == "main":
            result = check_main(root)
        elif args.mode == "delivery":
            result = check_delivery(root, args.expected_company)
        else:
            result = check_branch(root, args.expected_company)
        result["status"] = "ok"
        result["path"] = str(path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
