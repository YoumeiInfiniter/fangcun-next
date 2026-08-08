#!/usr/bin/env python3
"""Render translated dialogue back into original script structure.

Input translation JSONL rows:
  {"id":"dlg_0001","translated_text":"..."}

Modes:
- replace: speaker: translated_text
- bilingual: speaker: original / translated_text
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIALOGUE_RE = re.compile(r"^(?P<prefix>\s*(?P<speaker>[\u4e00-\u9fffA-Za-z0-9_·・（）()]{1,20})\s*[：:])\s*(?P<text>\S.*)$")
NON_SPEAKERS = {"场景", "时间", "地点", "镜头", "动作", "旁白", "音效", "字幕", "备注"}


def load_translations(path: Path) -> dict[str, dict]:
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            data[row["id"]] = row
    return data


def render(src: Path, translations: dict[str, dict], mode: str) -> str:
    out = []
    idx = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        m = DIALOGUE_RE.match(line)
        if not m or line.lstrip().startswith("#") or line.lstrip().startswith("|") or m.group("speaker").strip() in NON_SPEAKERS:
            out.append(line)
            continue
        idx += 1
        did = f"dlg_{idx:04d}"
        trans = translations.get(did, {})
        translated = trans.get("translated_text") or trans.get("translation") or ""
        if not translated:
            out.append(line)
        elif mode == "replace":
            out.append(f"{m.group('prefix')} {translated}")
        elif mode == "bilingual":
            out.append(line)
            out.append(f"{m.group('speaker')}（译）：{translated}")
        else:
            raise SystemExit(f"unknown mode: {mode}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("translations_jsonl")
    ap.add_argument("--mode", choices=["replace", "bilingual"], default="bilingual")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = render(Path(args.script), load_translations(Path(args.translations_jsonl)), args.mode)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result, encoding="utf-8")
    print(f"rendered out={out}")


if __name__ == "__main__":
    main()
