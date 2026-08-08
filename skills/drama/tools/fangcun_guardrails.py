#!/usr/bin/env python3
"""
Fangcun 工程兜底工具。

只服务 Fangcun 主流程：项目名、路径边界、用户可见中文消息、飞书错误提示。
不写表1业务产物，不写表2 token 统计。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping, Optional

_CHAT_ID_RE = re.compile(r"^(?:chat:)?oc_[0-9a-f]{12,}$", re.I)
_USER_ID_RE = re.compile(r"^(?:user:)?ou_[0-9a-f]{12,}$", re.I)
_ENGINEERING_LOG_RE = re.compile(
    r"(?:^|\n)\s*(?:\[[A-Z_ -]{2,}\]|Traceback|File \"|Exception:|Error:|WARN(?:ING)?:|INFO:|DEBUG:|HTTP \d{3}|code=\d+|pid=\d+|returncode=|stack trace)",
    re.I,
)


def is_machine_identifier(value: object) -> bool:
    """判断是否是 chat_id/user_id，而不是可作为项目名的自然语言标题。"""
    text = str(value or "").strip()
    if not text:
        return False
    return bool(_CHAT_ID_RE.match(text) or _USER_ID_RE.match(text))


def safe_project_display_name(*candidates: object, fallback: str = "未命名项目（待补剧名）") -> str:
    """从候选名中选择一个安全展示名，避免项目文件夹退化为 oc_xxx/chat_id。"""
    for item in candidates:
        text = str(item or "").strip().strip("《》")
        if not text:
            continue
        if is_machine_identifier(text):
            continue
        if text.lower() in {"unknown", "none", "null", "untitled"}:
            continue
        return text
    return fallback


def ensure_path_under(project_root: str | Path, target: str | Path, *, label: str = "产物路径") -> Path:
    """确保 target 位于 project_root 内；否则拒绝写入正式业务产物。"""
    root = Path(project_root).expanduser().resolve()
    path = Path(target).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}越过项目边界：{path} 不在 {root} 内") from exc
    return path


def output_project_root(output_dir: str | Path) -> Path:
    """Fangcun 正式产物边界：默认以 output_dir 为根。"""
    return Path(output_dir).expanduser().resolve()


def ensure_output_path(output_dir: str | Path, target: str | Path, *, label: str = "产物路径") -> Path:
    return ensure_path_under(output_project_root(output_dir), target, label=label)


def chinese_feishu_error_message(error: object) -> str:
    """将飞书/附件权限错误映射成用户可执行的中文指引。"""
    text = str(error or "")
    low = text.lower()
    if "resource invisible" in low or "not visible" in low or "permission" in low or "no permission" in low or "forbidden" in low or "99991663" in low:
        return (
            "飞书附件当前对机器人不可见，无法直接读取。请任选一种方式重发：\n"
            "1. 把文件上传到飞书云盘，并给本群/机器人可读权限；\n"
            "2. 转成飞书文档链接，并确认机器人可访问；\n"
            "3. 在群里重新发送文件后再 @ 我处理。"
        )
    if "not found" in low or "404" in low:
        return "没有找到该飞书资源。请确认文件/文档没有被删除，并重新发送可访问链接。"
    if "timeout" in low or "timed out" in low:
        return "读取飞书资源超时。请稍后重试，或改用飞书云盘/文档链接发送。"
    return f"飞书资源处理失败：{text[:180]}。请确认机器人有访问权限后重试。"


def sanitize_user_visible_text(text: object, *, fallback: str = "任务已处理，请查看上方链接或产物清单。") -> str:
    """群聊可见消息净化：移除英文工程日志，保留中文业务结果。"""
    raw = str(text or "").replace("\r\n", "\n").strip()
    if not raw:
        return fallback
    kept: list[str] = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            kept.append("")
            continue
        if _ENGINEERING_LOG_RE.search(s):
            continue
        # 过滤明显的命令/路径日志；链接和中文路径保留。
        if re.search(r"\b(?:python3?|Traceback|subprocess|returncode|stderr|stdout|json\.loads|FileNotFoundError)\b", s):
            continue
        kept.append(s)
    cleaned = "\n".join(kept).strip()
    return cleaned or fallback


def format_delivery_summary(*, status: str, title: str = "方寸任务", links: Optional[Iterable[Mapping[str, object]]] = None, state_path: str = "", note: str = "") -> str:
    """生成给飞书主群直发的中文交付摘要。"""
    ok = status in {"ok", "success", "done"}
    lines = [f"{'✅' if ok else '⚠️'} {title}：{'已完成' if ok else '需要处理'}"]
    seen = set()
    for item in links or []:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        name = safe_project_display_name(item.get("title") or item.get("key") or "产物链接", fallback="产物链接")
        lines.append(f"- {name}：{url}")
    if state_path:
        lines.append(f"- 本地状态：{state_path}")
    if note:
        lines.append(str(note).strip())
    return sanitize_user_visible_text("\n".join(lines))
