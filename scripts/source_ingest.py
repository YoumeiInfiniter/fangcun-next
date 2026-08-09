"""Source novel archiving and chapter indexing (deterministic).

Produces:
    <project_dir>/source/index.json
    <project_dir>/source/raw/<original-name>
    <project_dir>/source/chapters/chapter_<NNN>.txt

Chapter detection is heading-based, never fixed-width, and never allocates
chapters by averaging.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .common import atomic_write_json, ensure_dir, now_iso, sha256_file, read_json


CHAPTER_HEADING = re.compile(
    r"^(?P<heading>"
    r"(?:第\s*[0-9一二三四五六七八九十百千万零两]+\s*章"
    r"|序章|楔子|番外\s*[0-9一二三四五六七八九十百千万零两]*"
    r"|Chapter\s+[0-9]+"
    r"|第\s*[0-9一二三四五六七八九十百千万零两]+\s*节"
    r")(?:[ \t:：、.\-—·]*(?P<title>.+?)?)\s*$"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def chapter_index_path(project_dir: Path) -> Path:
    return project_dir / "source" / "index.json"


def raw_source_dir(project_dir: Path) -> Path:
    return project_dir / "source" / "raw"


def chapters_dir(project_dir: Path) -> Path:
    return project_dir / "source" / "chapters"


def load_chapter_index(project_dir: Path) -> dict:
    data = read_json(chapter_index_path(project_dir), {})
    return data if isinstance(data, dict) else {}


def split_chapters(text: str) -> list[dict]:
    """Split novel text into chapters by headings. Returns heading offsets."""
    matches = list(CHAPTER_HEADING.finditer(text))
    result = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        result.append(
            {
                "chapter_index": idx + 1,
                "heading": match.group("heading").strip(),
                "title": (match.group("title") or "").strip(),
                "span": {"start": start, "end": end},
            }
        )
    return result


def _safe_chapter_title(chapter: dict, index: int) -> str:
    title = chapter.get("title") or chapter.get("heading") or f"第{index}章"
    return re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", title).strip()[:80]


def ingest_novel(project_dir: Path, source_file: Path, *, overwrite: bool = False) -> dict:
    """Archive a novel file, split chapters and write the chapter index."""
    source_file = source_file.resolve()
    if not source_file.exists():
        raise FileNotFoundError(f"原文文件不存在: {source_file}")
    text = source_file.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        raise ValueError("原文文件为空")

    source_hash = sha256_file(source_file)
    existing = load_chapter_index(project_dir)
    if existing.get("source_file") and existing.get("source_hash") == source_hash and not overwrite:
        return {"created": False, "index": existing, "chapters": len(existing.get("chapters", []))}

    chapters = split_chapters(text)
    if not chapters:
        # No headings found: keep the whole file as one indexed unit so the
        # retriever can still work on event spans/keywords.
        chapters = [{"chapter_index": 1, "heading": "全文", "title": "全文", "span": {"start": 0, "end": len(text)}}]

    raw_dir = ensure_dir(raw_source_dir(project_dir))
    raw_path = raw_dir / source_file.name
    if raw_path.resolve() != source_file:
        shutil.copy2(source_file, raw_path)
    ch_dir = ensure_dir(chapters_dir(project_dir))
    for chapter in chapters:
        ch_num = chapter["chapter_index"]
        body = text[chapter["span"]["start"] : chapter["span"]["end"]].strip()
        title = _safe_chapter_title(chapter, ch_num)
        ch_path = ch_dir / f"chapter_{ch_num:03d}.txt"
        ch_path.write_text(f"{title}\n\n{body}\n", encoding="utf-8")
        chapter["file"] = f"source/chapters/chapter_{ch_num:03d}.txt"
        chapter["text_length"] = len(body)

    index = {
        "schema_version": 1,
        "source_file": str(raw_path),
        "source_hash": source_hash,
        "total_chars": len(text),
        "created_at": now_iso(),
        "coordinate_base": "chapter_file_content",
        "chapters": chapters,
    }
    atomic_write_json(chapter_index_path(project_dir), index)
    return {"created": True, "index": index, "chapters": len(chapters)}


def read_chapter(project_dir: Path, chapter_id: int) -> tuple[str, dict] | None:
    index = load_chapter_index(project_dir)
    for chapter in index.get("chapters", []):
        if chapter.get("chapter_index") == chapter_id:
            path = project_dir / chapter["file"]
            if path.exists():
                return path.read_text(encoding="utf-8"), chapter
            return None
    return None


def read_all_chapters(project_dir: Path) -> dict[int, str]:
    index = load_chapter_index(project_dir)
    out: dict[int, str] = {}
    for chapter in index.get("chapters", []):
        path = project_dir / chapter["file"]
        if path.exists():
            out[chapter["chapter_index"]] = path.read_text(encoding="utf-8")
    return out


def chapter_count(project_dir: Path) -> int:
    return len(load_chapter_index(project_dir).get("chapters", []))
