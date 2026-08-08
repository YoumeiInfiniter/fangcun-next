#!/usr/bin/env python3
"""Extract dialogue lines from Chinese drama script markdown/txt.

MVP parser supports lines like:
  角色：台词
  角色: dialogue

It avoids scene headings and markdown headings. Output is JSONL.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIALOGUE_RE = re.compile(r"^\s*(?P<speaker>[\u4e00-\u9fffA-Za-z0-9_·・（）()]{1,20})\s*[：:]\s*(?P<text>\S.*)$")

NON_SPEAKERS = {"场景", "时间", "地点", "镜头", "动作", "旁白", "音效", "字幕", "备注"}


def extract(path: Path) -> list[dict]:
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#") or line.lstrip().startswith("|"):
            continue
        m = DIALOGUE_RE.match(line)
        if not m:
            continue
        speaker = m.group("speaker").strip()
        text = m.group("text").strip()
        if speaker in NON_SPEAKERS:
            continue
        rows.append({
            "id": f"dlg_{len(rows)+1:04d}",
            "line_no": i,
            "speaker": speaker,
            "text": text,
            "context": "",
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = extract(Path(args.input))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    print(f"extracted dialogue lines={len(rows)} out={out}")


if __name__ == "__main__":
    main()
