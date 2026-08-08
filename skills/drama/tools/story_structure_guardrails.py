#!/usr/bin/env python3
"""Fangcun story/skeleton/script structure guardrails.

Checks two recurring issues from the Issue feedback table:
1. Same time + same place scenes are split into consecutive scenes instead of merged.
2. Episode/skeleton chunks have obviously unbalanced volume.

This tool is local and deterministic. It does not create projects, write table1,
or write token table2; it only validates Fangcun business outputs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCENE_NO_RE = re.compile(r"^\s*(?:\[)?(?P<ep>\d{1,3})[-－](?P<scene>\d{1,3})(?:\])?\s*$")
STANDARD_SCENE_RE = re.compile(r"^\s*(?P<ep>\d{1,3})[-－](?P<scene>\d{1,3})\s+(?P<place>[^\n：:【】]+?)\s+(?P<time>日|夜|晨|午|昏|傍晚|清晨|深夜)\s+(?P<io>内|外|内外)\s*$")
ZH_SCENE_RE = re.compile(r"^\s*场[:：]\s*(?P<place>.+?)[-—－](?P<time>日|夜|晨|午|昏|傍晚|清晨|深夜|Day|Night|Morning|Evening)[-—－](?P<io>内|外|内外|INT|EXT|INT/EXT)\s*$", re.I)
EN_SCENE_RE = re.compile(r"^\s*(?:\[)?(?P<ep>\d{1,3})[-－](?P<scene>\d{1,3})(?:\])?\s+(?P<time>Day|Night|Morning|Evening|Dawn|Dusk)\s*[·•]\s*(?P<place>.+?)(?:\s*[（(].*?[）)])?\s*$", re.I)
EPISODE_RE = re.compile(r"^\s*(?:#{1,4}\s*)?(?:第\s*(?P<zh>\d{1,3})\s*集|EP\s*(?P<ep>\d{1,3})|Episode\s*(?P<en>\d{1,3}))\b", re.I)
SUBAREA_RE = re.compile(r"△\s*(?:看台上|解说席|对站台|候场区|后台|观众席|裁判席|走廊|门口|角落|同一(?:大)?场景内)")
TIME_JUMP_RE = re.compile(
    r"(?:半日后|半个时辰后|一炷香后|片刻后|良久|过了许久|午膳后|晚膳后|入夜|夜色|天色渐暗|灯火|掌灯|晨光|日头西斜|日上三竿|次日|翌日|第二日|转眼|时辰已过|宴席散去|众人散去|重新落座)")


def norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower().replace("（", "(").replace("）", ")"))


@dataclass
class Scene:
    scene_no: str
    start_line: int
    end_line: int
    place: str
    time: str
    io: str
    body: str

    @property
    def scene_key(self) -> tuple[str, str, str]:
        """Deterministic split key: same place + same time + same interior/exterior = one scene.

        This intentionally ignores dramatic function, mood, information beat, and character
        relationship shifts. Those changes must be expressed inside the same scene with
        action lines / camera movement, not by opening a new scene heading.
        """
        return norm(self.place), norm(self.time), norm(self.io)

    @property
    def key(self) -> tuple[str, str, str]:
        # Backward-compatible alias used by older tests/callers.
        return self.scene_key

    @property
    def scene_key_label(self) -> str:
        return f"{self.place.strip()}|{self.time.strip()}|{self.io.strip()}"

    @property
    def has_subarea_markers(self) -> bool:
        return bool(SUBAREA_RE.search(self.body))


def parse_scenes(text: str) -> list[Scene]:
    lines = text.splitlines()
    markers: list[tuple[int, str, str, str, str]] = []
    pending_no = ""
    for idx, line in enumerate(lines, start=1):
        m_std = STANDARD_SCENE_RE.match(line)
        if m_std:
            scene_no = f"{int(m_std.group('ep'))}-{int(m_std.group('scene'))}"
            markers.append((idx, scene_no, m_std.group("place"), m_std.group("time"), m_std.group("io")))
            pending_no = ""
            continue
        m_no = SCENE_NO_RE.match(line)
        if m_no:
            pending_no = f"{int(m_no.group('ep'))}-{int(m_no.group('scene'))}"
            continue
        m = ZH_SCENE_RE.match(line)
        if m:
            markers.append((idx, pending_no or f"scene@{idx}", m.group("place"), m.group("time"), m.group("io")))
            pending_no = ""
            continue
        m2 = EN_SCENE_RE.match(line)
        if m2:
            scene_no = f"{int(m2.group('ep'))}-{int(m2.group('scene'))}"
            markers.append((idx, scene_no, m2.group("place"), m2.group("time"), ""))
    scenes: list[Scene] = []
    for i, (start, no, place, time, io) in enumerate(markers):
        end = markers[i + 1][0] - 1 if i + 1 < len(markers) else len(lines)
        body = "\n".join(lines[start - 1 : end])
        scenes.append(Scene(no, start, end, place.strip(), time.strip(), io.strip(), body))
    return scenes


def _has_explicit_time_jump(prev: Scene, cur: Scene) -> bool:
    """Return whether adjacent same-place scenes contain a visible time transition.

    This catches the common fake split: same place + same interior/exterior, but the
    writer changes `日` to `午`/`夜` only to force a new beat into a new scene.  A real
    time split must be visible in the script body (e.g. 午膳后、入夜、灯火点起、众人散去后重开).  A
    heading label alone is not enough.
    """
    boundary_text = "\n".join([
        "\n".join(prev.body.splitlines()[-6:]),
        "\n".join(cur.body.splitlines()[:8]),
    ])
    return bool(TIME_JUMP_RE.search(boundary_text))


def check_consecutive_same_scene(text: str) -> list[dict[str, object]]:
    """Block adjacent scene headings split by fake scene changes.

    Hard rules:
    - Same place + same time + same interior/exterior = must merge.
    - Same place + same interior/exterior but only the time label changes is also
      blocked unless the script body provides an explicit, visible time jump.

    Dramatic function, mood, information beat, character entrance, evidence arrival,
    and relationship shifts are never valid split reasons by themselves; handle them
    inside the same scene with action lines/camera movement/sub-area markers.
    """
    scenes = parse_scenes(text)
    issues: list[dict[str, object]] = []
    for prev, cur in zip(scenes, scenes[1:]):
        if prev.scene_key == cur.scene_key:
            issues.append(
                {
                    "type": "same_scene_key_split",
                    "severity": "error",
                    "message": "连续两场 scene key 完全相同（地点/时间/内外三项一致），必须合并为同一场；不得按戏剧关系、情绪功能或信息功能变化拆场。大场景也应合并为一场，并在动作行用△看台上/△解说席/△对站台等标注子区域。",
                    "previous_scene": prev.scene_no,
                    "current_scene": cur.scene_no,
                    "previous_line": prev.start_line,
                    "current_line": cur.start_line,
                    "place": prev.place,
                    "time": prev.time,
                    "io": prev.io,
                    "scene_key": prev.scene_key_label,
                }
            )
            continue
        same_place = norm(prev.place) == norm(cur.place)
        same_io = norm(prev.io) == norm(cur.io)
        different_time = norm(prev.time) != norm(cur.time)
        if same_place and same_io and different_time and not _has_explicit_time_jump(prev, cur):
            issues.append(
                {
                    "type": "time_label_only_split",
                    "severity": "error",
                    "message": "连续两场地点和内外关系相同，只改了时间标签，但正文没有明确、可拍的时间跳转。禁止为了剧情 beat 硬把“日”改成“午/夜”拆场；若只是新人物进来、新证据出现、冲突升级，应合并到上一场，用动作行承接。",
                    "previous_scene": prev.scene_no,
                    "current_scene": cur.scene_no,
                    "previous_line": prev.start_line,
                    "current_line": cur.start_line,
                    "place": prev.place,
                    "previous_time": prev.time,
                    "current_time": cur.time,
                    "io": prev.io,
                    "scene_key_without_time": f"{prev.place.strip()}|{prev.io.strip()}",
                }
            )
    return issues


def validate_script_scene_keys(text: str) -> dict[str, object]:
    """Public gate for script scene splitting.

    Kept separate from validate_text so callers that only care about hard scene-key
    correctness can fail fast without episode-volume warnings.
    """
    issues = check_consecutive_same_scene(text)
    return {"ok": not issues, "issue_count": len(issues), "issues": issues}


def parse_episode_chunks(text: str) -> list[tuple[int, int, int]]:
    lines = text.splitlines()
    starts: list[tuple[int, int]] = []
    for idx, line in enumerate(lines, start=1):
        m = EPISODE_RE.match(line)
        if not m:
            continue
        ep = int(m.group("zh") or m.group("ep") or m.group("en"))
        starts.append((idx, ep))
    chunks: list[tuple[int, int, int]] = []
    for i, (start, ep) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines)
        body = [ln for ln in lines[start - 1 : end] if ln.strip()]
        chunks.append((ep, start, len(body)))
    return chunks


def check_episode_volume_balance(text: str) -> list[dict[str, object]]:
    chunks = parse_episode_chunks(text)
    if len(chunks) < 3:
        return []
    counts = [c for _, _, c in chunks if c > 0]
    if not counts:
        return []
    mean = sum(counts) / len(counts)
    issues: list[dict[str, object]] = []
    too_short = [(ep, line, c) for ep, line, c in chunks if c < mean * 0.55]
    too_long = [(ep, line, c) for ep, line, c in chunks if c > mean * 1.8]
    if too_short or too_long:
        issues.append(
            {
                "type": "episode_volume_unbalanced",
                "severity": "warning",
                "message": "分集体量明显失衡。1.5-2分钟单集应控制戏量均衡，避免一集空泛、一集塞太多事件；确需长短差异时应在分集说明中写明原因。",
                "mean_nonempty_lines": round(mean, 2),
                "too_short": [{"episode": ep, "line": line, "nonempty_lines": c} for ep, line, c in too_short],
                "too_long": [{"episode": ep, "line": line, "nonempty_lines": c} for ep, line, c in too_long],
            }
        )
    return issues


def validate_text(text: str) -> dict[str, object]:
    issues = []
    issues.extend(check_consecutive_same_scene(text))
    issues.extend(check_episode_volume_balance(text))
    return {"ok": not any(i.get("severity") == "error" for i in issues), "issue_count": len(issues), "issues": issues}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate Fangcun story skeleton/script structural guardrails")
    ap.add_argument("path", help="Markdown/script file to validate")
    ap.add_argument("--json", action="store_true", help="Emit JSON only")
    args = ap.parse_args()
    path = Path(args.path)
    result = validate_text(path.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(f"OK: {path} passed story structure guardrails ({result['issue_count']} warning/issues).")
        else:
            print(f"FAILED: {path} has story structure errors.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
