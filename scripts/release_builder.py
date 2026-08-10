"""Clean release package builder with private-isolation checks (spec §31).

The package contains only the new skill: SKILL.md, references/, scripts/,
assets/ and packaging metadata. Legacy code, tests, research, project data,
caches, keys and platform credentials are excluded by default.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from .common import atomic_write_json, ensure_dir, skill_root


EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "tests",
    "docs",
    "skills",
    "skills-legacy",
    "tools",
    "hooks",
    "memory",
    "projects",
    "output",
    "logs",
    "_cache",
    "tmp",
    "dist",
    ".claude-plugin",
    ".codex",
    ".cursor-plugin",
    ".opencode",
}

EXCLUDED_FILES = {
    "AGENTS.md",
    "START_HERE.md",
    "CLAUDE.md",
    "GEMINI.md",
    "gemini-extension.json",
    "requirements.txt",
    ".gitignore",
    "README.md",
    "feishu_project_table_templates.json",
    "feishu_project_table_templates.md",
    "platform-tools.md",
    "drama-director.md",
    "script-writer.md",
    "event-extractor.md",
    "skeleton-builder.md",
    "adaptation-strategist.md",
    "quality-supervisor.md",
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}", re.I),
    re.compile(r"(?i)(api[_-]?key|secret|password|private[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_\-/+]{8,}"),
    re.compile(r"feishu\.cn/(base|wiki)/[A-Za-z0-9]+"),
    re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"openclaw\.json"),
]

ALLOWED_EXPLICIT = {
    "pyproject.toml",
}


def iter_package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
            continue
        if any(part.endswith(".egg-info") for part in rel.parts[:-1]):
            continue
        if rel.name in EXCLUDED_FILES or rel.name.endswith((".pyc", ".pyo", ".zip")):
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(path)
    return files


def check_private_isolation(files: list[Path]) -> list[str]:
    problems: list[str] = []
    text_suffixes = {".py", ".md", ".json", ".txt", ".toml", ".yaml", ".yml"}
    for path in files:
        if path.suffix not in text_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"{path.name}: 命中私密内容模式 {pattern.pattern[:40]}")
                break
    return problems


def build_package(out_path: Path, *, version: str = "0.3.2") -> Path:
    """Build dist/<name>-<version>.zip plus release_manifest.json."""
    root = skill_root()
    files = iter_package_files(root)
    if not files:
        raise RuntimeError("发布包为空")
    problems = check_private_isolation(files)
    if problems:
        raise RuntimeError("发布包含私密内容，已拒绝生成：\n" + "\n".join(problems))

    out_path = out_path.resolve()
    if out_path.suffix != ".zip":
        out_path = out_path.with_suffix(".zip")
    ensure_dir(out_path.parent)
    prefix = f"fangcun-next-{version}"
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(root)
            archive_name = f"{prefix}/{rel.as_posix()}"
            zf.write(path, archive_name)
            entries.append(
                {
                    "path": rel.as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                }
            )
    manifest = {
        "package": f"fangcun-next-{version}.zip",
        "version": version,
        "created_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": entries,
        "excluded": sorted(EXCLUDED_DIRS | {name.lower() for name in EXCLUDED_FILES}),
    }
    atomic_write_json(out_path.parent / "release_manifest.json", manifest)
    return out_path


def render_package_manifest(manifest: dict) -> str:
    lines = ["# 发布包清单", "", f"- 包：{manifest['package']}", f"- 版本：{manifest['version']}", f"- 文件数：{len(manifest['files'])}", ""]
    lines.extend(f"- {e['path']}" for e in manifest["files"])
    return "\n".join(lines) + "\n"
