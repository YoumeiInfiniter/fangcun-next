#!/usr/bin/env python3
"""Runtime path resolver for Fangcun.

Fangcun can be installed under different OpenClaw layouts, for example:
- /root/.openclaw/workspaces/<bot_id>/skills/fangcun/...
- /root/.openclaw/agents/<bot_id>/workspace/skills/fangcun/...

Do not hard-code those absolute roots. Resolve paths from runtime anchors and
persist the resolved project paths into project config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FangcunRuntimePaths:
    workspace_dir: Path
    skill_dir: Path
    drama_dir: Path
    tools_dir: Path
    projects_dir: Path


def _first_env_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser().resolve()
    return None


def _find_skill_dir_from_file(anchor_file: Path) -> Path:
    """Find the enclosing fangcun skill directory from this tool file."""
    resolved = anchor_file.expanduser().resolve()
    for parent in [resolved.parent, *resolved.parents]:
        if parent.name == "fangcun" and (parent / "SKILL.md").exists():
            return parent
    # Fallback for the known layout: fangcun/skills/drama/tools/runtime_paths.py
    return resolved.parents[3]


def _find_workspace_from_cwd_or_skill(skill_dir: Path) -> Path:
    """Resolve the OpenClaw workspace root without assuming one fixed layout."""
    env_workspace = _first_env_path(
        "FANGCUN_WORKSPACE",
        "OPENCLAW_WORKSPACE",
        "OPENCLAW_WORKSPACE_DIR",
        "WORKSPACE_DIR",
    )
    if env_workspace:
        return env_workspace

    cwd = Path.cwd().expanduser().resolve()
    candidates = [cwd, *cwd.parents, skill_dir, *skill_dir.parents]
    for candidate in candidates:
        # The workspace root usually owns skills/fangcun.
        if (candidate / "skills" / "fangcun" / "SKILL.md").exists():
            return candidate
        # If the cwd is already inside the skill, the parent above skills is root.
        if candidate.name == "skills" and (candidate / "fangcun" / "SKILL.md").exists():
            return candidate.parent
    # Last resort: current directory is safer than /root/.openclaw guesses.
    return cwd


def resolve_runtime_paths(anchor_file: str | Path | None = None) -> FangcunRuntimePaths:
    """Resolve Fangcun runtime paths from env/cwd/skill anchors.

    Priority:
    1. Explicit env override for workspace/projects.
    2. Current OpenClaw workspace inferred from cwd or installed skill location.
    3. Skill resources relative to SKILL.md / this file.
    """
    anchor = Path(anchor_file).resolve() if anchor_file else Path(__file__).resolve()
    skill_dir = _find_skill_dir_from_file(anchor)
    workspace_dir = _find_workspace_from_cwd_or_skill(skill_dir)
    drama_dir = skill_dir / "skills" / "drama"
    tools_dir = drama_dir / "tools"

    projects_override = _first_env_path("FANGCUN_PROJECTS", "FANGCUN_PROJECTS_DIR")
    projects_dir = projects_override or (workspace_dir / "projects")

    return FangcunRuntimePaths(
        workspace_dir=workspace_dir,
        skill_dir=skill_dir,
        drama_dir=drama_dir,
        tools_dir=tools_dir,
        projects_dir=projects_dir,
    )


def print_runtime_paths(paths: FangcunRuntimePaths | None = None) -> None:
    paths = paths or resolve_runtime_paths()
    print("🔎 Fangcun runtime paths")
    print(f"  workspace_dir: {paths.workspace_dir}")
    print(f"  skill_dir: {paths.skill_dir}")
    print(f"  projects_dir: {paths.projects_dir}")
    print(f"  tools_dir: {paths.tools_dir}")
