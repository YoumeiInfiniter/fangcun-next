"""Deterministic screenplay format validation (spec §19.4).

Format checks never judge dialogue quality or plot logic. The parser also
produces structured scenes/speakers used by duration and continuity modules.
"""

from __future__ import annotations

import re
from typing import Any


EPISODE_HEADER_RE = re.compile(r"^(EP\d{3}|第\s*\d+\s*集)(?:\s*[：:]\s*(.+))?$")
SCENE_HEADING_RE = re.compile(
    r"^(\d+)-(\d+)\s+(.+?)\s+"
    r"(日|夜|晨|清晨|黄昏|傍晚|白天|夜晚|黎明|午夜)\s+(内|外)$"
)
CHARACTER_LINE_RE = re.compile(r"^人物\s*[：:]\s*(.+)$")
ACTION_RE = re.compile(r"^△.+")
DIALOGUE_RE = re.compile(r"^([^（(：:]+?)(?:（([^）)]*)）)?\s*[：:]\s*(.+)$")
XML_WRAP_RE = re.compile(r'^<scriptItem name="([^"]*)">\s*(.*?)\s*</scriptItem>\s*$', re.DOTALL)
FORBIDDEN_PATTERNS = [
    (re.compile(r"^\s*字数[：:]\s*\d+"), "剧本正文出现字数统计"),
    (re.compile(r"^\s*(审核报告|说明[：:]|注[：:]|Craft|crafT)"), "剧本正文出现审核/说明/Craft 注释"),
]


def validate_script(
    content: str,
    *,
    format_profile: str = "default-cn",
    expected_episode: int | None = None,
) -> dict:
    """Validate a screenplay. Returns {ok, errors, warnings, parsed}."""
    errors: list[dict] = []
    warnings: list[dict] = []
    text = content or ""
    xml_mode = format_profile == "legacy-scriptitem"

    if xml_mode:
        stripped = text.strip()
        match = XML_WRAP_RE.fullmatch(stripped)
        if not match:
            errors.append({"line": 1, "code": "xml_wrapper", "message": "legacy-scriptitem 模式要求完整 <scriptItem> 包裹且标签外无内容"})
            return _report(errors, warnings, expected_episode)
        inner = match.group(2)
        wrapper_name = match.group(1)
    else:
        inner = text
        wrapper_name = None

    lines = inner.splitlines()
    parsed = _parse_lines(lines, errors, warnings)
    if not parsed["episode_header"]:
        errors.append({"line": 1, "code": "episode_header", "message": "缺少规范分集标识；每集正文必须以 EP001 或 第N集 开头"})
    elif expected_episode is not None:
        actual = parsed["episode_number"]
        if actual != expected_episode:
            errors.append({"line": parsed["episode_header_line"], "code": "episode_mismatch", "message": f"分集标识为第{actual}集，期望第{expected_episode}集"})

    if xml_mode and wrapper_name and parsed["episode_header"]:
        if wrapper_name != f"EP{parsed['episode_number']:03d}":
            expected_name = f"EP{parsed['episode_number']:03d}"
            if expected_name not in wrapper_name:
                warnings.append({"line": 1, "code": "xml_name", "message": f"XML name 与分集标识不一致：{wrapper_name!r}"})

    if not parsed["scenes"]:
        errors.append({"line": 1, "code": "no_scenes", "message": "剧本没有任何可解析场次"})

    for pattern, message in FORBIDDEN_PATTERNS:
        for idx, line in enumerate(lines, start=1):
            if pattern.match(line):
                errors.append({"line": idx, "code": pattern.pattern, "message": message})

    return _report(errors, warnings, expected_episode, parsed)


def _report(errors, warnings, expected_episode, parsed=None) -> dict:
    parsed = parsed or {
        "episode_header": None,
        "episode_header_line": None,
        "episode_number": None,
        "title": None,
        "scenes": [],
        "speakers": [],
    }
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "parsed": parsed,
    }


def _parse_lines(lines: list[str], errors: list[dict], warnings: list[dict]) -> dict:
    episode_header = None
    episode_header_line = None
    episode_number = None
    title = None
    scenes: list[dict] = []
    current_scene: dict | None = None
    speakers: list[str] = []
    scene_keys: set[tuple[str, str, str]] = set()

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if episode_header is None:
            match = EPISODE_HEADER_RE.match(line)
            if match:
                episode_header = line
                episode_header_line = idx
                num_text = match.group(1)
                if num_text.startswith("EP"):
                    episode_number = int(num_text[2:])
                else:
                    episode_number = int(re.sub(r"\D", "", num_text))
                title = (match.group(2) or "").strip() or None
                continue
            # Allow one leading blank/title line? Spec requires first line header.
            errors.append({"line": idx, "code": "episode_header", "message": f"分集标识格式错误：{line!r}"})
            episode_header = line  # avoid duplicate errors
            continue

        scene_match = SCENE_HEADING_RE.match(line)
        if scene_match:
            key = (scene_match.group(3).strip(), scene_match.group(4), scene_match.group(5))
            if key in scene_keys:
                errors.append({"line": idx, "code": "duplicate_scene_key", "message": f"连续/重复场次 key 相同：{key}，必须合并为同一场"})
            scene_keys.add(key)
            current_scene = {
                "line": idx,
                "episode": episode_number,
                "scene_no": int(scene_match.group(2)),
                "location": scene_match.group(3).strip(),
                "time": scene_match.group(4),
                "inout": scene_match.group(5),
                "scene_key": key,
                "actions": [],
                "dialogues": [],
                "characters": [],
            }
            scenes.append(current_scene)
            continue

        if current_scene is None:
            errors.append({"line": idx, "code": "line_before_scene", "message": f"分集标识后第一个场次之前出现无法归类行：{line!r}"})
            continue

        char_match = CHARACTER_LINE_RE.match(line)
        if char_match:
            names = [n.strip() for n in re.split(r"[、,，]", char_match.group(1)) if n.strip()]
            current_scene["characters"] = names
            speakers.extend(names)
            continue

        if ACTION_RE.match(line):
            current_scene["actions"].append({"line": idx, "text": line})
            continue

        dia_match = DIALOGUE_RE.match(line)
        if dia_match:
            speaker = dia_match.group(1).strip()
            delivery = (dia_match.group(2) or "").strip()
            text = dia_match.group(3).strip()
            current_scene["dialogues"].append({"line": idx, "speaker": speaker, "delivery": delivery, "text": text})
            if speaker and speaker not in speakers:
                speakers.append(speaker)
            continue

        errors.append({"line": idx, "code": "unparsable_line", "message": f"无法解析的行：{line!r}"})

    # Empty scene check: heading with no action/dialogue before next heading.
    for scene in scenes:
        if not scene["actions"] and not scene["dialogues"]:
            errors.append({"line": scene["line"], "code": "empty_scene", "message": f"场次 {scene['episode']}-{scene['scene_no']} 为空（无动作行也无台词）"})

    # Adjacent duplicate scene keys are also caught above; a stronger check:
    # any two consecutive scenes with identical key.
    for prev, curr in zip(scenes, scenes[1:]):
        if prev["scene_key"] == curr["scene_key"]:
            errors.append({"line": curr["line"], "code": "consecutive_scene_key", "message": f"连续两场 scene key 完全相同（{curr['scene_key']}），必须合并为同一场"})

    # 场景跳变检测（advisory）：删节/压缩中间事件后，若相邻场景在地点或时间上跳变，
    # 且上一场景以台词收尾、下一场景以台词开场、又无转场标识，视为可能的生硬跳切，
    # 提示 Writer 补过渡桥。仅提示，不阻断保存。
    TRANSITION_MARKERS = ("转场", "快进", "蒙太奇", "闪回", "快切", "跳转", "切至", "闪白")

    def _scene_last_kind(scene):
        items = scene["dialogues"] + scene["actions"]
        if not items:
            return None
        tail = max(items, key=lambda x: x["line"])
        return "dialogue" if tail in scene["dialogues"] else "action"

    def _scene_first_kind(scene):
        items = scene["dialogues"] + scene["actions"]
        if not items:
            return None
        head = min(items, key=lambda x: x["line"])
        return "dialogue" if head in scene["dialogues"] else "action"

    for prev, curr in zip(scenes, scenes[1:]):
        if prev["location"] == curr["location"] and prev["time"] == curr["time"]:
            continue  # 同地点同时段，不算跳切
        marker_hit = any(
            m in (a["text"] or "") for a in prev["actions"] for m in TRANSITION_MARKERS
        )
        if marker_hit:
            continue
        if _scene_last_kind(prev) == "dialogue" and _scene_first_kind(curr) == "dialogue":
            warnings.append({
                "line": curr["line"],
                "code": "scene_jump_needs_bridge",
                "message": (
                    f"场景 {prev['episode']}-{prev['scene_no']}（{prev['location']} {prev['time']}）到 "
                    f"{curr['episode']}-{curr['scene_no']}（{curr['location']} {curr['time']}）可能跳切："
                    "上一场景以台词收尾、下一场景以台词开场且无转场标识。若因删节/压缩产生，"
                    "请补过渡桥（过渡动作行 / OS 承接句 / △转场），依据优先还原原文衔接。"
                ),
            })

    return {
        "episode_header": episode_header,
        "episode_header_line": episode_header_line,
        "episode_number": episode_number,
        "title": title,
        "scenes": scenes,
        "speakers": speakers,
    }


def parse_script(content: str, *, format_profile: str = "default-cn") -> dict:
    """Parse without blocking; returns parsed structure (empty on failure)."""
    report = validate_script(content, format_profile=format_profile)
    return report["parsed"] if report["ok"] else {}


def extract_speakers(content: str) -> list[str]:
    parsed = parse_script(content)
    return list(dict.fromkeys(parsed.get("speakers", [])))
