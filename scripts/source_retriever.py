"""Anchor-driven source retrieval for a single episode (deterministic).

Retrieval order (spec §12.2):
  1. event ids listed by the episode outline;
  2. chapters listed by the episode outline;
  3. keyword matches (characters, quotes, event terms);
  4. dependency events;
  5. necessary surrounding context;
  6. proportional fallback ONLY when no anchor resolves.

Excerpts are never cut in the middle of a sentence or a quote, and
setup/payoff pairs are kept together.
"""

from __future__ import annotations

import re

from .source_ingest import load_chapter_index, read_all_chapters, read_chapter


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?…])|(?<=\n)")
SPACE_RE = re.compile(r"\s+")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in SENTENCE_BOUNDARY.finditer(text):
        end = match.end()
        if end > start:
            spans.append((start, end))
        start = end
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _snap_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Extend a span to sentence boundaries without cutting a quote."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    spans = _sentence_spans(text)
    snapped_start = start
    snapped_end = end
    for s, e in spans:
        if e > start and snapped_start == start:
            snapped_start = s
        if e >= end:
            snapped_end = e
            break
    # If end sits inside the last sentence, extend to its end.
    if snapped_end <= end and spans:
        snapped_end = spans[-1][1]
    return snapped_start, snapped_end


def _expand_to_quote(text: str, start: int, end: int, quote: str) -> tuple[int, int]:
    pos = text.find(quote, start, end)
    if pos < 0:
        return start, end
    q_start, q_end = _snap_span(text, pos, pos + len(quote))
    return min(start, q_start), max(end, q_end)


def _events_by_id(events: list[dict]) -> dict[str, dict]:
    return {e["event_id"]: e for e in events}


def _collect_dependencies(event_id: str, events_by_id: dict[str, dict], seen: set[str]) -> list[str]:
    if event_id in seen:
        return []
    seen.add(event_id)
    deps = list(events_by_id.get(event_id, {}).get("dependencies", []) or [])
    for dep in deps:
        deps.extend(_collect_dependencies(dep, events_by_id, seen))
    return deps


def _keywords_from(outline: dict, events: list[dict]) -> list[str]:
    keywords: list[str] = []
    for key in ("title", "episode_goal", "opening_bridge", "ending_hook", "must_keep"):
        value = outline.get(key)
        if isinstance(value, str):
            for chunk in re.split(r"[，。；、\s]+", value):
                if len(chunk) >= 2:
                    keywords.append(chunk)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    for chunk in re.split(r"[，。；、\s]+", item):
                        if len(chunk) >= 2:
                            keywords.append(chunk)
    for event in events:
        for quote in event.get("key_quotes", []) or []:
            if isinstance(quote.get("text"), str) and len(quote["text"]) >= 2:
                keywords.append(quote["text"])
    for anchor in outline.get("dialogue_anchors", []) or []:
        for part in (anchor.get("setup"), anchor.get("payoff")):
            if isinstance(part, str) and len(part) >= 2:
                keywords.append(part)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:80]


def _excerpt_for_keyword(chapter_text: str, chapter: dict, keyword: str, budget: int) -> dict | None:
    pos = chapter_text.find(keyword)
    if pos < 0:
        return None
    half = budget // 2
    start, end = _snap_span(chapter_text, max(0, pos - half), min(len(chapter_text), pos + len(keyword) + half))
    return {
        "chapter_id": chapter["chapter_index"],
        "chapter_title": chapter.get("title") or chapter.get("heading", ""),
        "source_file": chapter.get("file", ""),
        "source_span": {"start": start, "end": end},
        "reason": f"keyword:{keyword[:20]}",
        "text": chapter_text[start:end],
    }


def _event_excerpts(chapter_text: str, chapter: dict, events: list[dict], budget: int) -> list[dict]:
    excerpts: list[dict] = []
    for event in events:
        span = event.get("source_span") or {}
        start, end = span.get("start", 0), span.get("end", len(chapter_text))
        start, end = _snap_span(chapter_text, start, end)
        for quote in event.get("key_quotes", []) or []:
            qtext = quote.get("text", "")
            if qtext:
                start, end = _expand_to_quote(chapter_text, start, end, qtext)
        excerpt_text = chapter_text[start:end]
        if len(excerpt_text) > budget:
            # Prefer the core of the event: event description sentence then quotes.
            for quote in event.get("key_quotes", []) or []:
                qtext = quote.get("text", "")
                if qtext and len(qtext) <= budget:
                    qpos = chapter_text.find(qtext, start, end)
                    if qpos >= 0:
                        s2, e2 = _snap_span(chapter_text, qpos, qpos + len(qtext))
                        if e2 - s2 <= budget:
                            start, end = s2, e2
                            break
        if end - start > budget:
            s3, e3 = _snap_span(chapter_text, start, start + budget)
            if e3 - s3 > budget:
                # Last resort: sentence-level block that still respects
                # sentence boundaries, never a raw hard cut.
                spans = _sentence_spans(chapter_text[start : start + budget * 2])
                if spans:
                    e3 = start + spans[-1][1]
                s3, e3 = _snap_span(chapter_text, start, e3)
            start, end = s3, e3
        if end > start:
            excerpts.append(
                {
                    "chapter_id": chapter["chapter_index"],
                    "chapter_title": chapter.get("title") or chapter.get("heading", ""),
                    "source_file": chapter.get("file", ""),
                    "source_span": {"start": start, "end": end},
                    "reason": f"event:{event.get('event_id')}",
                    "text": chapter_text[start:end],
                }
            )
    return excerpts


def _dedupe_excerpts(excerpts: list[dict]) -> list[dict]:
    seen: set[tuple[int, int, int]] = set()
    result: list[dict] = []
    for ex in excerpts:
        key = (ex["chapter_id"], ex["source_span"]["start"], ex["source_span"]["end"])
        if key not in seen:
            seen.add(key)
            result.append(ex)
    return result


def retrieve_source_evidence(
    project_dir: Path,
    outline: dict,
    events: list[dict],
    *,
    max_chars: int = 6000,
    per_chapter_budget: int = 2000,
) -> dict:
    """Build source_evidence for one episode from anchors, never average-slicing."""
    events_by_id = _events_by_id(events)
    anchor_ids = list(outline.get("source_event_ids", []) or [])
    anchor_chapters = list(outline.get("source_chapters", []) or [])

    # 1. event ids → chapters
    resolved_events: list[dict] = []
    for eid in anchor_ids:
        event = events_by_id.get(eid)
        if event:
            resolved_events.append(event)
            ch = event.get("chapter_id")
            if isinstance(ch, int) and ch not in anchor_chapters:
                anchor_chapters.append(ch)

    # 4. dependency events (recursive), added after direct anchors.
    seen_deps: set[str] = set()
    for eid in anchor_ids:
        for dep in _collect_dependencies(eid, events_by_id, seen_deps):
            event = events_by_id.get(dep)
            if event and event not in resolved_events:
                resolved_events.append(event)
                ch = event.get("chapter_id")
                if isinstance(ch, int) and ch not in anchor_chapters:
                    anchor_chapters.append(ch)

    chapters = read_all_chapters(project_dir)
    chapter_meta = {
        ch.get("chapter_index"): ch
        for ch in load_chapter_index(project_dir).get("chapters", [])
    }
    excerpts: list[dict] = []
    chapter_ids: list[int] = []
    used_order: list[str] = []

    # Event-span excerpts first.
    for event in resolved_events:
        ch_id = event.get("chapter_id")
        chapter_text = chapters.get(ch_id)
        if not chapter_text:
            continue
        chapter_ids.append(ch_id)
        meta = chapter_meta.get(ch_id, {})
        excerpts.extend(
            _event_excerpts(
                chapter_text,
                {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")},
                [event],
                per_chapter_budget,
            )
        )
    if anchor_ids or resolved_events:
        used_order.append("event_ids")

    # 2. explicitly listed chapters.
    for ch_id in anchor_chapters:
        chapter = None
        chapter_text = chapters.get(ch_id)
        if chapter_text is None:
            result = read_chapter(project_dir, ch_id)
            if result:
                chapter_text, chapter = result
        if not chapter_text:
            continue
        if ch_id not in chapter_ids:
            chapter_ids.append(ch_id)
        if len(chapter_text) <= per_chapter_budget:
            excerpts.append(
                {
                    "chapter_id": ch_id,
                    "chapter_title": (chapter or chapter_meta.get(ch_id, {})).get("title", ""),
                    "source_file": (chapter or {}).get("file", ""),
                    "source_span": {"start": 0, "end": len(chapter_text)},
                    "reason": "chapter_full",
                    "text": chapter_text,
                }
            )

    if anchor_chapters:
        used_order.append("chapters")

    # 3. keyword search when explicit anchors are missing or too thin.
    if len(excerpts) < len(anchor_ids) + len(anchor_chapters) or not excerpts:
        keyword_events = list(resolved_events)
        for eid in anchor_ids:
            event = events_by_id.get(eid)
            if event and event not in keyword_events:
                keyword_events.append(event)
        keywords = _keywords_from(outline, keyword_events)
        for kw in keywords:
            for ch_id, chapter_text in chapters.items():
                if ch_id in chapter_ids and excerpts:
                    continue
                meta = chapter_meta.get(ch_id, {})
                ex = _excerpt_for_keyword(
                    chapter_text,
                    {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")},
                    kw,
                    per_chapter_budget,
                )
                if ex:
                    excerpts.append(ex)
                    if ch_id not in chapter_ids:
                        chapter_ids.append(ch_id)
                    break
    used_order.append("keywords")
    if not anchor_ids and not anchor_chapters:
        used_order.append("keywords_only")

    excerpts = _dedupe_excerpts(excerpts)

    # 5. surrounding context: previous chapter tail for opening bridge and
    # next chapter head for hooks are only added when requested via outline.
    # 6. proportional fallback ONLY when nothing else resolved.
    fallback_used = False
    if not excerpts:
        total_chars = sum(len(t) for t in chapters.values())
        if chapters and total_chars:
            fallback_used = True
            used_order.append("proportional_fallback")
            per = max(1, max_chars // len(chapters))
            for ch_id, chapter_text in chapters.items():
                if len(chapter_text) <= per:
                    start, end = 0, len(chapter_text)
                else:
                    start, end = _snap_span(chapter_text, 0, per)
                excerpts.append(
                    {
                        "chapter_id": ch_id,
                        "chapter_title": "",
                        "source_file": "",
                        "source_span": {"start": start, "end": end},
                        "reason": "proportional_fallback",
                        "text": chapter_text[start:end],
                    }
                )
                chapter_ids.append(ch_id)

    # Budget enforcement: prioritize mainline event excerpts, then quotes.
    def _priority(ex: dict) -> tuple[int, int]:
        event_id = str(ex.get("reason", "")).replace("event:", "")
        importance = 1
        for event in resolved_events:
            if event.get("event_id") == event_id:
                importance = 0 if event.get("importance") == "mainline" else 1
        return (importance, ex["source_span"]["start"])

    excerpts.sort(key=_priority)
    kept: list[dict] = []
    total = 0
    truncated = False
    for ex in excerpts:
        text = ex.get("text", "")
        if total + len(text) > max_chars:
            truncated = True
            continue
        kept.append(ex)
        total += len(text)

    quotes = []
    for event in resolved_events:
        for quote in event.get("key_quotes", []) or []:
            quotes.append({**quote, "event_id": event["event_id"], "chapter_id": event["chapter_id"]})
    for anchor in outline.get("dialogue_anchors", []) or []:
        quotes.append({"anchor": True, **anchor})

    return {
        "chapter_ids": sorted(set(chapter_ids)),
        "events": resolved_events,
        "quotes": quotes,
        "raw_excerpts": kept,
        "retrieval_report": {
            "order_used": used_order,
            "fallback_used": fallback_used,
            "truncated": truncated,
            "total_excerpt_chars": total,
        },
    }


def source_evidence_complete(evidence: dict) -> list[str]:
    """Completeness checks used by context_builder (spec §12.4)."""
    problems: list[str] = []
    if not evidence.get("chapter_ids"):
        problems.append("当前集没有任何原文证据")
    if not evidence.get("events") and not evidence.get("raw_excerpts"):
        problems.append("当前集事件和摘录均为空")
    if evidence.get("retrieval_report", {}).get("fallback_used"):
        problems.append("未找到集纲锚点，使用了全剧比例回退，证据强度低")
    return problems
