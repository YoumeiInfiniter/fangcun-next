#!/usr/bin/env python3
"""Smoke test a Fangcun company delivery ZIP.

Checks:
- ZIP can be opened and tested.
- DELIVERY_MANIFEST.json exists and required fields are present.
- CHECKSUMS.sha256 matches extracted files.
- Forbidden runtime/sensitive file patterns are absent.
- Core Python tools compile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

FORBIDDEN_PATTERNS = [
    r"(^|/)__pycache__(/|$)",
    r"\.pyc$",
    r"\.pyo$",
    r"\.db$",
    r"\.sqlite3?$",
    r"\.log$",
    r"\.env$",
    r"\.token$",
    r"\.secret$",
    r"\.key$",
    r"\.pem$",
    r"\.p12$",
    r"\.pfx$",
    r"\.bak(\..*)?$",
    r"(^|/)projects(/|$)",
    r"(^|/)state\.json$",
]

REQUIRED_MANIFEST_FIELDS = [
    "schema_version",
    "product",
    "company",
    "company_slug",
    "delivery_type",
    "version",
    "git_commit",
    "built_at",
    "file_count",
    "files",
]

CORE_PYTHON_FILES = [
    "skills/fangcun/tools/build_company_delivery.py",
    "skills/fangcun/tools/check_private_isolation.py",
    "skills/fangcun/skills/drama/tools/pipeline.py",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> None:
    raise SystemExit(f"[FAIL] {msg}")


def check_zip(zip_path: Path) -> None:
    if not zip_path.exists():
        fail(f"zip not found: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad:
                fail(f"zip corrupt member: {bad}")
    except zipfile.BadZipFile as exc:
        fail(f"bad zip: {exc}")


def extract_zip(zip_path: Path, out: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out)


def check_manifest(root: Path, expected_delivery_type: str = "", expected_company: str = "") -> dict:
    path = root / "DELIVERY_MANIFEST.json"
    if not path.exists():
        fail("DELIVERY_MANIFEST.json missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_MANIFEST_FIELDS if k not in data]
    if missing:
        fail(f"manifest missing fields: {missing}")
    if data.get("product") != "fangcun":
        fail(f"manifest product mismatch: {data.get('product')}")
    if expected_delivery_type and data.get("delivery_type") != expected_delivery_type:
        fail(f"delivery_type mismatch: expected {expected_delivery_type}, got {data.get('delivery_type')}")
    if expected_company and data.get("company") != expected_company and data.get("company_slug") != expected_company:
        fail(f"company mismatch: expected {expected_company}, got {data.get('company')} / {data.get('company_slug')}")
    return data


def check_forbidden_files(root: Path) -> list[str]:
    bad = []
    regexes = [re.compile(p) for p in FORBIDDEN_PATTERNS]
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(rx.search(rel) for rx in regexes):
            bad.append(rel)
    if bad:
        fail("forbidden files found:\n" + "\n".join(bad[:50]))
    return bad


def parse_checksums(path: Path) -> dict[str, str]:
    rows = {}
    if not path.exists():
        fail("CHECKSUMS.sha256 missing")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            fail(f"invalid checksum line: {line}")
        digest, rel = parts
        rows[rel.strip()] = digest.strip()
    return rows


def check_checksums(root: Path) -> int:
    expected = parse_checksums(root / "CHECKSUMS.sha256")
    for rel, digest in expected.items():
        path = root / rel
        if not path.exists():
            fail(f"checksum target missing: {rel}")
        actual = sha256(path)
        if actual != digest:
            fail(f"checksum mismatch: {rel}")
    return len(expected)


def check_manifest_file_list(root: Path, manifest: dict) -> int:
    files = manifest.get("files") or []
    if not isinstance(files, list) or not files:
        fail("manifest files[] is empty")
    for item in files:
        rel = item.get("path")
        digest = item.get("sha256")
        if not rel or not digest:
            fail(f"invalid manifest file item: {item}")
        path = root / rel
        if not path.exists():
            fail(f"manifest file missing: {rel}")
        if sha256(path) != digest:
            fail(f"manifest sha256 mismatch: {rel}")
    return len(files)


def check_python_compile(root: Path) -> list[str]:
    checked = []
    for rel in CORE_PYTHON_FILES:
        path = root / rel
        if path.exists():
            subprocess.run(["python3", "-m", "py_compile", str(path)], check=True)
            checked.append(rel)
    if not checked:
        fail("no core python files found for compile check")
    return checked


def check_private_isolation(root: Path, expected_company: str) -> dict | None:
    if not expected_company:
        return None
    script = root / "skills/fangcun/tools/check_private_isolation.py"
    if not script.exists():
        return None
    proc = subprocess.run(
        ["python3", str(script), str(root), "--mode", "delivery", "--expected-company", expected_company],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return json.loads(proc.stdout)


def smoke_test(zip_path: Path, expected_delivery_type: str = "", expected_company: str = "", keep_extract: bool = False, check_isolation: bool = False) -> dict:
    check_zip(zip_path)
    tmp = Path(tempfile.mkdtemp(prefix="fangcun_delivery_smoke_"))
    try:
        extract_zip(zip_path, tmp)
        manifest = check_manifest(tmp, expected_delivery_type, expected_company)
        check_forbidden_files(tmp)
        checksum_count = check_checksums(tmp)
        manifest_file_count = check_manifest_file_list(tmp, manifest)
        compiled = check_python_compile(tmp)
        isolation = check_private_isolation(tmp, expected_company) if check_isolation else None
        result = {
            "status": "ok",
            "zip": str(zip_path),
            "company": manifest.get("company"),
            "delivery_type": manifest.get("delivery_type"),
            "version": manifest.get("version"),
            "git_commit": manifest.get("git_commit"),
            "checksum_count": checksum_count,
            "manifest_file_count": manifest_file_count,
            "compiled": compiled,
            "private_isolation": isolation,
            "extract_dir": str(tmp) if keep_extract else None,
        }
        return result
    finally:
        if not keep_extract:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke test Fangcun delivery ZIP")
    ap.add_argument("zip", help="delivery zip path")
    ap.add_argument("--expected-delivery-type", default="unified")
    ap.add_argument("--expected-company", default="")
    ap.add_argument("--keep-extract", action="store_true")
    ap.add_argument("--check-isolation", action="store_true", help="check company-private isolation")
    args = ap.parse_args()
    result = smoke_test(Path(args.zip).resolve(), args.expected_delivery_type, args.expected_company, args.keep_extract, args.check_isolation)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
