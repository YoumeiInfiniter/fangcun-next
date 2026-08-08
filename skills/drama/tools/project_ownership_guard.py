#!/usr/bin/env python3
"""Fangcun project ownership and path guard.

This guard prevents cross-bot / cross-project outputs by validating the current
runtime against the project config before generation or Feishu sync.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

GUARD_ERROR = "检测到当前 bot、项目目录或飞书账号与项目绑定不一致，本次未生成、未同步任何产物。"


class ProjectOwnershipError(RuntimeError):
    pass


def normalize_chat_id(chat_id: str) -> str:
    return str(chat_id or "").strip().replace("chat:", "", 1)


def current_bot_id() -> str:
    env_value = os.environ.get("OPENCLAW_AGENT_ID") or os.environ.get("OPENCLAW_ACCOUNT_ID") or os.environ.get("FANGCUN_BOT_ID")
    if env_value:
        return env_value.strip()
    cwd = Path.cwd().resolve()
    parts = cwd.parts
    if "workspaces" in parts:
        idx = parts.index("workspaces")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    # claw3 layout: /root/.openclaw/agents/<bot_id>/workspace/...
    if "agents" in parts:
        idx = parts.index("agents")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def current_feishu_account(default: str = "") -> str:
    return (os.environ.get("FANGCUN_FEISHU_ACCOUNT") or os.environ.get("OPENCLAW_AGENT_ID") or default or "").strip()


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _fail(reason: str) -> None:
    raise ProjectOwnershipError(f"{GUARD_ERROR}\n原因：{reason}")


def assert_config_binding(config: dict, *, config_path: str | Path, account: Optional[str] = None) -> None:
    """Validate bot/account and canonical Fangcun project paths.

    Formal config path must be:
    <project_workspace>/drama/config.json
    Formal output root must be inside:
    <project_workspace>/drama/output
    """
    cfg_path = _resolve(config_path)
    bot_id = str(config.get("bot_id") or "").strip()
    runtime_bot = current_bot_id()
    if bot_id and runtime_bot and runtime_bot != bot_id:
        _fail(f"当前 bot={runtime_bot}，项目 bot_id={bot_id}")
    if bot_id and not runtime_bot:
        _fail("无法识别当前 OPENCLAW_AGENT_ID，不能校验 bot_id")

    expected_account = str(config.get("feishu_account") or "").strip()
    runtime_account = current_feishu_account(account or "")
    if expected_account and runtime_account and runtime_account != expected_account:
        _fail(f"当前飞书账号={runtime_account}，项目 feishu_account={expected_account}")
    if expected_account and not runtime_account:
        _fail("无法识别当前飞书账号，不能校验 feishu_account")

    project_slug = str(config.get("project_slug") or cfg_path.parent.parent.name).strip()
    project_workspace = _resolve(config.get("project_workspace") or cfg_path.parent.parent)
    expected_cfg = project_workspace / "drama" / "config.json"
    if cfg_path != expected_cfg:
        _fail(f"config 路径不是正式路径：{cfg_path}；应为：{expected_cfg}")
    if project_slug and project_workspace.name != project_slug:
        _fail(f"project_slug={project_slug} 与项目目录名={project_workspace.name} 不一致")

    drama_root = project_workspace / "drama"
    output_dir = _resolve(config.get("output_dir") or (drama_root / "output"))
    expected_output_root = drama_root / "output"
    if output_dir != expected_output_root and not _inside(output_dir, expected_output_root):
        _fail(f"output_dir 不在 canonical output root 内：{output_dir}；应在：{expected_output_root}")


def assert_state_binding(config: dict, state: dict, *, require_project_node: bool = True) -> None:
    """Validate feishu_sync_state.json belongs to the same project."""
    project_workspace = _resolve(config.get("project_workspace") or Path(config.get("output_dir", ".")).parent.parent)
    output_dir = _resolve(config.get("output_dir") or (project_workspace / "drama" / "output"))
    state_file = output_dir / "feishu_sync_state.json"
    if state_file.exists():
        expected_state_path = project_workspace / "drama" / "output" / "feishu_sync_state.json"
        if state_file != expected_state_path:
            _fail(f"feishu_sync_state.json 路径不属于当前项目：{state_file}")

    project_slug = str(config.get("project_slug") or project_workspace.name)
    state_slug = str(state.get("project_slug") or "")
    if state_slug and state_slug != project_slug:
        _fail(f"state project_slug={state_slug}，config project_slug={project_slug}")

    config_chat = normalize_chat_id(config.get("chat_id") or "")
    state_chat = normalize_chat_id(state.get("chat_id") or "")
    if state_chat and config_chat and state_chat != config_chat:
        _fail(f"state chat_id={state_chat}，config chat_id={config_chat}")

    state_root = state.get("project_root") or state.get("project_workspace_path")
    if state_root and _resolve(state_root) != project_workspace:
        _fail(f"state project_root={state_root}，config project_workspace={project_workspace}")

    workspace = state.get("project_workspace") if isinstance(state.get("project_workspace"), dict) else {}
    if require_project_node and not workspace.get("project_node_token"):
        _fail("project_node_token 不存在，禁止绕开项目文件夹创建/同步产物")


def stamp_state_identity(config: dict, state: dict) -> None:
    """Persist project identity into feishu_sync_state.json for later validation."""
    project_workspace = _resolve(config.get("project_workspace") or Path(config.get("output_dir", ".")).parent.parent)
    state["bot_id"] = config.get("bot_id") or state.get("bot_id") or current_bot_id()
    state["feishu_account"] = config.get("feishu_account") or state.get("feishu_account") or current_feishu_account()
    state["project_slug"] = config.get("project_slug") or project_workspace.name
    state["chat_id"] = normalize_chat_id(config.get("chat_id") or state.get("chat_id") or "")
    state["project_root"] = str(project_workspace)
