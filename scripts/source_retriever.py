"""Anchor-driven source retrieval for a single episode (deterministic).

Retrieval order (spec §12.2):
  1. event ids listed by the episode outline;
  2. chapters listed by the episode outline;
  3. keyword matches (characters, quotes, event terms);
  4. dependency events;
  5. necessary surrounding context;
  6. proportional fallback ONLY when no anchor resolves.

Every request is tracked in a coverage ledger (S1-1). Direct event/chapter
anchors must be backed by real excerpt text; setup/payoff pairs and
must_preserve_pairing quotes are indivisible; long explicit chapters always
yield at least one excerpt. When the budget would omit a required anchor the
retrieval is retried with a higher budget before reporting omission.
"""

from __future__ import annotations

from copy import deepcopy
import re

from .common import sha256_text
from .source_ingest import load_chapter_index, read_all_chapters, read_chapter


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?…])|(?<=\n)")


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
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    spans = _sentence_spans(text)
    snapped_start = start
    snapped_end = end
    start_set = False
    for s, e in spans:
        if e > start and not start_set:
            snapped_start = s
            start_set = True
        if e >= end:
            snapped_end = e
            break
    if snapped_end < end and spans:
        snapped_end = spans[-1][1]
    return snapped_start, snapped_end


def enrich_event_retrieval_spans(events: list[dict], chapters: dict[int, str]) -> list[dict]:
    """Attach a rich retrieval span without weakening the exact evidence span.

    Models often anchor ``source_span`` to the shortest verifiable quote.  That
    is useful for integrity checks but too small for screenplay writing.  For
    every chapter, partition the chapter around the ordered exact anchors so
    each event receives surrounding trigger/action/reaction/result context.
    The exact source span and hash remain untouched.
    """
    grouped: dict[int, list[dict]] = {}
    for event in events:
        chapter_id = event.get("chapter_id")
        span = event.get("source_span") or {}
        if (
            isinstance(chapter_id, int)
            and chapter_id in chapters
            and isinstance(span, dict)
            and isinstance(span.get("start"), int)
            and isinstance(span.get("end"), int)
            and 0 <= span["start"] < span["end"] <= len(chapters[chapter_id])
        ):
            grouped.setdefault(chapter_id, []).append(event)

    for chapter_id, chapter_events in grouped.items():
        text = chapters[chapter_id]
        ordered = sorted(
            chapter_events,
            key=lambda item: (item["source_span"]["start"], item["source_span"]["end"]),
        )
        boundaries = [0]
        for left, right in zip(ordered, ordered[1:]):
            left_end = int(left["source_span"]["end"])
            right_start = int(right["source_span"]["start"])
            boundaries.append(max(left_end, (left_end + right_start) // 2))
        boundaries.append(len(text))
        for index, event in enumerate(ordered):
            start, end = _snap_span(text, boundaries[index], boundaries[index + 1])
            exact = event["source_span"]
            start = min(start, exact["start"])
            end = max(end, exact["end"])
            excerpt = text[start:end]
            event["retrieval_span"] = {"start": start, "end": end}
            event["retrieval_excerpt_hash"] = sha256_text(excerpt)
    return events


def _expand_to_quote(text: str, start: int, end: int, quote: str) -> tuple[int, int]:
    pos = text.find(quote, start, end)
    if pos < 0:
        return start, end
    q_start, q_end = _snap_span(text, pos, pos + len(quote))
    return min(start, q_start), max(end, q_end)


def _make_excerpt(chapter_text: str, chapter: dict, start: int, end: int, reason: str) -> dict:
    text = chapter_text[start:end]
    return {
        "chapter_id": chapter["chapter_index"],
        "chapter_title": chapter.get("title") or chapter.get("heading", ""),
        "source_file": chapter.get("file", ""),
        "source_span": {"start": start, "end": end},
        "reason": reason,
        "text": text,
        "excerpt_hash": sha256_text(text),
    }


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
    for key in ("title", "episode_goal", "episode_focus", "opening_bridge", "ending_hook", "must_keep"):
        value = outline.get(key)
        if isinstance(value, str):
            for chunk in re.split(r"[，。；、\s]+", value):
                if len(chunk) >= 2:
                    keywords.append(chunk)
        elif isinstance(value, list):
            for item in value:
                text = item.get("text") if isinstance(item, dict) else item
                if isinstance(text, str):
                    for chunk in re.split(r"[，。；、\s]+", text):
                        if len(chunk) >= 2:
                            keywords.append(chunk)
    for beat in outline.get("required_story_beats", []) or []:
        if isinstance(beat, dict):
            for chunk in re.split(r"[，。；、\s]+", str(beat.get("text") or "")):
                if len(chunk) >= 2:
                    keywords.append(chunk)
    for quote_item in outline.get("required_quotes", []) or []:
        for part in (
            quote_item.get("quote"),
            quote_item.get("setup"),
            quote_item.get("payoff"),
        ):
            if isinstance(part, str) and len(part) >= 2:
                keywords.append(part)
    for beat in outline.get("beat_plan", []) or []:
        for key in ("function", "visible_outcome", "entry_state"):
            value = beat.get(key)
            if isinstance(value, str):
                for chunk in re.split(r"[，。；、\s]+", value):
                    if len(chunk) >= 2:
                        keywords.append(chunk)
    for event in events:
        for quote in event.get("key_quotes", []) or []:
            if isinstance(quote.get("text"), str) and len(quote["text"]) >= 2:
                keywords.append(quote["text"])
    for anchor in outline.get("dialogue_anchors", []) or []:
        for part in (anchor.get("quote"), anchor.get("setup"), anchor.get("payoff")):
            if isinstance(part, str) and len(part) >= 2:
                keywords.append(part)
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
    return _make_excerpt(chapter_text, chapter, start, end, f"keyword:{keyword[:20]}")


def _pair_span(chapter_text: str, setup: str | None, payoff: str | None) -> tuple[int, int] | None:
    """Union span covering both setup and payoff (indivisible unit)."""
    if not setup or not payoff:
        return None
    s1 = chapter_text.find(setup) if setup else -1
    s2 = chapter_text.find(payoff) if payoff else -1
    if s1 < 0 and s2 < 0:
        return None
    if s1 < 0 or s2 < 0:
        return None
    start = min(s1, s2)
    end = max(s1 + len(setup or ""), s2 + len(payoff or ""))
    return _snap_span(chapter_text, start, end)


def _event_excerpts(
    chapter_text: str,
    chapter: dict,
    event: dict,
    budget: int,
) -> tuple[list[dict], bool, str]:
    span = event.get("source_span") or {}
    if not isinstance(span, dict) or "start" not in span or "end" not in span:
        # Missing span: keep a degraded whole-chapter excerpt (needs re-anchor),
        # but never claim a precise event location.
        return [_make_excerpt(chapter_text, chapter, 0, len(chapter_text), f"event:{event.get('event_id')}")], True, "needs_reanchor"
    start, end = span.get("start"), span.get("end")
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not (0 <= start < end <= len(chapter_text))
    ):
        return [], True, "needs_reanchor"
    if event.get("needs_reanchor"):
        return [], True, "needs_reanchor"
    if event.get("coordinate_base") not in (None, "chapter_file_content"):
        return [], True, "needs_reanchor"
    chapter_hash = chapter.get("content_hash") or sha256_text(chapter_text)
    if event.get("chapter_content_hash") and event.get("chapter_content_hash") != chapter_hash:
        return [], True, "needs_reanchor"
    exact_excerpt = chapter_text[start:end]
    if event.get("source_excerpt_hash") and event.get("source_excerpt_hash") != sha256_text(exact_excerpt):
        return [], True, "needs_reanchor"
    if event.get("source_quote") and str(event.get("source_quote")) not in exact_excerpt:
        return [], True, "needs_reanchor"
    retrieval_span = event.get("retrieval_span") or {}
    if (
        isinstance(retrieval_span, dict)
        and isinstance(retrieval_span.get("start"), int)
        and isinstance(retrieval_span.get("end"), int)
        and 0 <= retrieval_span["start"] <= start < end <= retrieval_span["end"] <= len(chapter_text)
    ):
        retrieval_text = chapter_text[retrieval_span["start"] : retrieval_span["end"]]
        retrieval_hash = event.get("retrieval_excerpt_hash")
        if retrieval_hash and retrieval_hash != sha256_text(retrieval_text):
            return [], True, "needs_reanchor"
        start, end = retrieval_span["start"], retrieval_span["end"]
    else:
        start, end = _snap_span(chapter_text, start, end)
    for quote in event.get("key_quotes", []) or []:
        qtext = quote.get("text", "")
        if qtext:
            setup = quote.get("setup")
            payoff = quote.get("payoff")
            if quote.get("must_preserve_pairing") and (setup or payoff):
                if not setup:
                    return [], True, "missing_setup"
                if not payoff:
                    return [], True, "missing_payoff"
                setup_pos = chapter_text.find(setup)
                payoff_pos = chapter_text.find(payoff)
                if setup_pos < 0:
                    return [], True, "missing_setup"
                if payoff_pos < 0:
                    return [], True, "missing_payoff"
                pair = _pair_span(chapter_text, setup, payoff)
                if pair is None:
                    return [], True, "pair_not_in_same_chapter"
                start = min(start, pair[0])
                end = max(end, pair[1])
            start, end = _expand_to_quote(chapter_text, start, end, qtext)
    excerpt_text = chapter_text[start:end]
    if end - start > budget:
        exact_start = int(span["start"])
        exact_end = int(span["end"])
        half = max(1, (budget - (exact_end - exact_start)) // 2)
        window_start = max(start, exact_start - half)
        window_end = min(end, exact_end + half)
        start, end = _snap_span(chapter_text, window_start, window_end)
        if end - start > budget * 3 // 2:
            start = max(0, exact_start - half)
            end = min(len(chapter_text), start + budget)
    if end > start:
        return [_make_excerpt(chapter_text, chapter, start, end, f"event:{event.get('event_id')}")], False, ""
    return [], True, "no_excerpt"


def _dedupe_excerpts(excerpts: list[dict]) -> list[dict]:
    seen: set[tuple[int, int, int, str]] = set()
    result: list[dict] = []
    for ex in excerpts:
        key = (ex["chapter_id"], ex["source_span"]["start"], ex["source_span"]["end"], ex.get("reason", ""))
        if key not in seen:
            seen.add(key)
            result.append(ex)
    return result


def _retrieve(
    project_dir,
    outline: dict,
    events: list[dict],
    *,
    max_chars: int,
    per_chapter_budget: int,
) -> dict:
    chapters = read_all_chapters(project_dir)
    # Old event artifacts may predate retrieval_span.  Enrich a private copy
    # at read time so immutable historical versions are never rewritten while
    # every writer still receives causal context around the exact anchor.
    events = enrich_event_retrieval_spans(deepcopy(events), chapters)
    events_by_id = _events_by_id(events)
    anchor_ids = list(outline.get("source_event_ids", []) or [])
    v2_event_ids: list[str] = []
    for beat in outline.get("required_story_beats", []) or []:
        for eid in beat.get("event_ids", []) or []:
            if eid not in v2_event_ids:
                v2_event_ids.append(eid)
    for beat in outline.get("beat_plan", []) or []:
        for eid in beat.get("event_ids", []) or []:
            if eid not in v2_event_ids:
                v2_event_ids.append(eid)
    anchor_chapters = list(outline.get("source_chapters", []) or [])
    anchor_chapters = [int(c) for c in anchor_chapters]

    resolved_events: list[dict] = []
    for eid in anchor_ids:
        event = events_by_id.get(eid)
        if event:
            resolved_events.append(event)
            ch = event.get("chapter_id")
            if isinstance(ch, int) and ch not in anchor_chapters:
                anchor_chapters.append(ch)
    for eid in v2_event_ids:
        event = events_by_id.get(eid)
        if event and event not in resolved_events:
            resolved_events.append(event)
            ch = event.get("chapter_id")
            if isinstance(ch, int) and ch not in anchor_chapters:
                anchor_chapters.append(ch)

    dep_ids: list[str] = []
    seen_deps: set[str] = set()
    for eid in anchor_ids + v2_event_ids:
        for dep in _collect_dependencies(eid, events_by_id, seen_deps):
            event = events_by_id.get(dep)
            if event and event not in resolved_events:
                resolved_events.append(event)
                dep_ids.append(dep)
                ch = event.get("chapter_id")
                if isinstance(ch, int) and ch not in anchor_chapters:
                    anchor_chapters.append(ch)

    chapter_meta = {
        ch.get("chapter_index"): ch
        for ch in load_chapter_index(project_dir).get("chapters", [])
    }
    excerpts: list[dict] = []
    chapter_ids: list[int] = []
    used_order: list[str] = []
    degraded_event_ids: set[str] = set()
    event_fail_reasons: dict[str, str] = {}
    anchor_fail_reasons: dict[int, str] = {}

    for event in resolved_events:
        ch_id = event.get("chapter_id")
        chapter_text = chapters.get(ch_id)
        if not chapter_text:
            continue
        if ch_id not in chapter_ids:
            chapter_ids.append(ch_id)
        meta = chapter_meta.get(ch_id, {})
        chapter = {
            "chapter_index": ch_id,
            "title": meta.get("title", ""),
            "file": meta.get("file", ""),
            "content_hash": meta.get("content_hash", ""),
        }
        event_excerpts, degraded, fail_reason = _event_excerpts(chapter_text, chapter, event, per_chapter_budget)
        excerpts.extend(event_excerpts)
        if degraded:
            degraded_event_ids.add(event["event_id"])
        if fail_reason:
            event_fail_reasons[event["event_id"]] = fail_reason
    if anchor_ids or resolved_events:
        used_order.append("event_ids")

    # Explicit chapters: long chapters still must yield at least one excerpt.
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
        meta = chapter_meta.get(ch_id, {})
        chapter_dict = {
            "chapter_index": ch_id,
            "title": meta.get("title", ""),
            "file": meta.get("file", ""),
            "content_hash": meta.get("content_hash", ""),
        }
        has_excerpt = any(ex["chapter_id"] == ch_id for ex in excerpts)
        if not has_excerpt:
            if len(chapter_text) <= per_chapter_budget:
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, 0, len(chapter_text), "chapter_full"))
            else:
                start, end = _snap_span(chapter_text, 0, per_chapter_budget)
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, start, end, "chapter_head"))
    if anchor_chapters:
        used_order.append("chapters")

    # Dialogue anchors distinguish a single reusable quote from an indivisible
    # setup/payoff pair.  Legacy payoff-only anchors are normalized as quotes.
    for idx, anchor in enumerate(outline.get("dialogue_anchors", []) or []):
        anchor_type = anchor.get("type")
        setup = anchor.get("setup")
        payoff = anchor.get("payoff")
        quote = anchor.get("quote")
        source_event_id = anchor.get("source_event_id") or anchor.get("source")
        if not anchor_type:
            anchor_type = "pair" if setup else ("quote" if payoff or quote else "")
        if anchor_type == "quote":
            quote = quote or payoff
            if not quote:
                anchor_fail_reasons[idx] = "missing_quote"
                continue
            event = events_by_id.get(source_event_id)
            candidate_chapters = [event.get("chapter_id")] if event else list(chapter_ids)
            for ch_id in candidate_chapters:
                chapter_text = chapters.get(ch_id)
                if not chapter_text:
                    continue
                pos = chapter_text.find(quote)
                if pos < 0:
                    continue
                span = _snap_span(chapter_text, pos, pos + len(quote))
                meta = chapter_meta.get(ch_id, {})
                chapter_dict = {
                    "chapter_index": ch_id,
                    "title": meta.get("title", ""),
                    "file": meta.get("file", ""),
                    "content_hash": meta.get("content_hash", ""),
                }
                excerpts.append(
                    _make_excerpt(chapter_text, chapter_dict, span[0], span[1], f"dialogue_anchor:{idx:03d}")
                )
                break
            else:
                anchor_fail_reasons[idx] = "quote_not_in_source_event"
            continue
        if anchor_type != "pair" or (not setup and not payoff):
            continue
        # Both ends must exist; a lone end is NOT a valid pair.
        if not setup or not payoff:
            anchor_fail_reasons[idx] = "missing_setup" if not setup else "missing_payoff"
            continue
        event = events_by_id.get(source_event_id)
        candidate_chapters = [event.get("chapter_id")] if event else list(chapter_ids)
        for ch_id in candidate_chapters:
            chapter_text = chapters.get(ch_id)
            if not chapter_text:
                continue
            s1 = chapter_text.find(setup)
            s2 = chapter_text.find(payoff)
            if s1 >= 0 and s2 >= 0:
                span = _snap_span(chapter_text, min(s1, s2), max(s1 + len(setup), s2 + len(payoff)))
                meta = chapter_meta.get(ch_id, {})
                chapter_dict = {
                    "chapter_index": ch_id,
                    "title": meta.get("title", ""),
                    "file": meta.get("file", ""),
                    "content_hash": meta.get("content_hash", ""),
                }
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, span[0], span[1], f"dialogue_anchor:{idx:03d}"))
                break
        else:
            anchor_fail_reasons[idx] = "pair_not_in_same_chapter"

    # V2 required_quotes: same indivisible quote/pair semantics, tracked under
    # required_quote coverage instead of dialogue_anchor.
    for idx, item in enumerate(outline.get("required_quotes", []) or []):
        if not isinstance(item, dict):
            continue
        setup = item.get("setup")
        payoff = item.get("payoff")
        quote = item.get("quote")
        source_event_id = item.get("source_event_id")
        event = events_by_id.get(source_event_id)
        found = False
        event_span = (event or {}).get("source_span") or {}
        ch_id = (event or {}).get("chapter_id")
        if (
            isinstance(ch_id, int)
            and isinstance(event_span.get("start"), int)
            and isinstance(event_span.get("end"), int)
            and 0 <= event_span["start"] < event_span["end"]
        ):
            chapter_text = chapters.get(ch_id)
            event_start = event_span["start"]
            event_end = min(event_span["end"], len(chapter_text or ""))
            if chapter_text and event_start < event_end and setup and payoff:
                s1 = chapter_text.find(setup, event_start, event_end)
                s2 = chapter_text.find(payoff, event_start, event_end)
                if s1 >= 0 and s2 >= 0:
                    span = _snap_span(chapter_text, min(s1, s2), max(s1 + len(setup), s2 + len(payoff)))
                    found = True
            elif chapter_text and event_start < event_end and quote:
                pos = chapter_text.find(quote, event_start, event_end)
                if pos >= 0:
                    span = _snap_span(chapter_text, pos, pos + len(quote))
                    found = True
            if found:
                meta = chapter_meta.get(ch_id, {})
                chapter_dict = {
                    "chapter_index": ch_id,
                    "title": meta.get("title", ""),
                    "file": meta.get("file", ""),
                    "content_hash": meta.get("content_hash", ""),
                }
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, span[0], span[1], f"required_quote:{idx:03d}"))
        if not found:
            anchor_fail_reasons[f"required_quote_{idx}"] = "quote_not_in_source_event"

    # Direct event/chapter anchors already satisfy the source request.  Do not
    # double-count them and then search the entire novel for a repeated word.
    # Keyword-only retrieval remains available when no direct anchor exists.
    if not excerpts or (not anchor_ids and not anchor_chapters):
        keyword_events = list(resolved_events)
        for eid in anchor_ids:
            event = events_by_id.get(eid)
            if event and event not in keyword_events:
                keyword_events.append(event)
        keywords = _keywords_from(outline, keyword_events)
        for kw in keywords:
            search_ids = chapter_ids or list(chapters)
            for ch_id in search_ids:
                chapter_text = chapters.get(ch_id)
                if chapter_text is None:
                    continue
                meta = chapter_meta.get(ch_id, {})
                chapter_dict = {
                    "chapter_index": ch_id,
                    "title": meta.get("title", ""),
                    "file": meta.get("file", ""),
                    "content_hash": meta.get("content_hash", ""),
                }
                ex = _excerpt_for_keyword(chapter_text, chapter_dict, kw, per_chapter_budget)
                if ex:
                    excerpts.append(ex)
                    if ch_id not in chapter_ids:
                        chapter_ids.append(ch_id)
                    break
    used_order.append("keywords")
    if not anchor_ids and not anchor_chapters:
        used_order.append("keywords_only")

    excerpts = _dedupe_excerpts(excerpts)

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
                meta = chapter_meta.get(ch_id, {})
                chapter_dict = {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")}
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, start, end, "proportional_fallback"))
                if ch_id not in chapter_ids:
                    chapter_ids.append(ch_id)

    def _priority(ex: dict) -> tuple[int, int, int]:
        reason = str(ex.get("reason", ""))
        reason_priority = (
            0
            if reason.startswith("event:")
            else 1
            if reason.startswith(("dialogue_anchor:", "required_quote:"))
            else 2
        )
        event_id = str(ex.get("reason", "")).replace("event:", "")
        importance = 1
        for event in resolved_events:
            if event.get("event_id") == event_id:
                importance = 0 if event.get("importance") == "mainline" else 1
        return (reason_priority, importance, ex["source_span"]["start"])

    excerpts.sort(key=_priority)
    kept: list[dict] = []
    total = 0
    truncated = False
    required_budget_overflow = False
    for ex in excerpts:
        text = ex.get("text", "")
        if total + len(text) > max_chars:
            truncated = True
            reason = str(ex.get("reason", ""))
            required = (
                (reason.startswith("event:") and reason.removeprefix("event:") in anchor_ids)
                or reason.startswith("dialogue_anchor:")
                or reason.startswith("required_quote:")
                or (ex.get("chapter_id") in anchor_chapters and not any(k.get("chapter_id") == ex.get("chapter_id") for k in kept))
            )
            if not required:
                continue
            # A configured character budget is an optimization, never
            # permission to silently drop an explicit contract anchor.
            required_budget_overflow = True
        kept.append(ex)
        total += len(text)

    quotes = []
    for event in resolved_events:
        for quote in event.get("key_quotes", []) or []:
            quotes.append({**quote, "event_id": event["event_id"], "chapter_id": event["chapter_id"]})
    for anchor in outline.get("dialogue_anchors", []) or []:
        quotes.append({"anchor": True, **anchor})

    coverage = _build_coverage(
        outline=outline,
        anchor_ids=anchor_ids,
        anchor_chapters=anchor_chapters,
        dep_ids=dep_ids,
        resolved_events=resolved_events,
        kept=kept,
        events_by_id=events_by_id,
        fallback_used=fallback_used,
        degraded_event_ids=degraded_event_ids,
        event_fail_reasons=event_fail_reasons,
        anchor_fail_reasons=anchor_fail_reasons,
    )

    return {
        "chapter_ids": sorted(set(chapter_ids)),
        "events": resolved_events,
        "quotes": quotes,
        "raw_excerpts": kept,
        "coverage": coverage,
        "retrieval_report": {
            "order_used": used_order,
            "fallback_used": fallback_used,
            "truncated": truncated,
            "required_budget_overflow": required_budget_overflow,
            "total_excerpt_chars": total,
            "degraded_events": sorted(degraded_event_ids),
        },
    }


def _build_coverage(
    *,
    outline: dict,
    anchor_ids: list[str],
    anchor_chapters: list[int],
    dep_ids: list[str],
    resolved_events: list[dict],
    kept: list[dict],
    events_by_id: dict[str, dict],
    fallback_used: bool,
    degraded_event_ids: set[str],
    event_fail_reasons: dict[str, str],
    anchor_fail_reasons: dict[int | str, str],
) -> list[dict]:
    ledger: list[dict] = []
    kept_text = "\n".join(ex.get("text", "") for ex in kept)
    adaptation_basis = outline.get("adaptation_basis", []) or []

    def _has_event_excerpt(eid: str) -> bool:
        return any(ex.get("reason") == f"event:{eid}" for ex in kept)

    for eid in anchor_ids:
        event = events_by_id.get(eid)
        resolved = event is not None
        included = resolved and _has_event_excerpt(eid)
        degraded = bool(resolved and (not (event or {}).get("source_span") or eid in degraded_event_ids))
        degraded_reason = event_fail_reasons.get(eid, "needs_reanchor" if degraded else "")
        ledger.append(
            {
                "anchor_type": "event",
                "anchor_id": eid,
                "requested": True,
                "resolved": resolved,
                "included": included,
                "omitted": not included,
                "degraded": degraded,
                "degraded_reason": degraded_reason,
                "reason": (
                    ""
                    if included
                    else ("event_not_found" if not resolved else (degraded_reason if degraded else "no_excerpt"))
                ),
            }
        )
    for dep in dep_ids:
        included = _has_event_excerpt(dep)
        ledger.append(
            {
                "anchor_type": "dependency",
                "anchor_id": dep,
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": "" if included else "no_excerpt",
            }
        )
    for ch in anchor_chapters:
        included = any(ex.get("chapter_id") == ch for ex in kept)
        ledger.append(
            {
                "anchor_type": "chapter",
                "anchor_id": str(ch),
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": "" if included else "no_excerpt",
            }
        )
    for idx, anchor in enumerate(outline.get("dialogue_anchors", []) or []):
        if not (anchor.get("quote") or anchor.get("setup") or anchor.get("payoff")):
            continue
        included = any(ex.get("reason") == f"dialogue_anchor:{idx:03d}" for ex in kept)
        fail_reason = anchor_fail_reasons.get(idx, "" if included else "pair_not_in_chapter_or_budget")
        ledger.append(
            {
                "anchor_type": "dialogue_anchor",
                "anchor_id": anchor.get("source_event_id") or anchor.get("source", f"anchor-{idx:03d}"),
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": "" if included else fail_reason,
            }
        )
    for idx, beat in enumerate(outline.get("required_story_beats", []) or []):
        if not isinstance(beat, dict):
            continue
        text_value = str(beat.get("text") or "")
        event_ids = beat.get("event_ids", []) or []
        decision_id = beat.get("adaptation_decision_id")
        if not text_value:
            continue
        has_events = bool(event_ids) and all(_has_event_excerpt(str(eid)) for eid in event_ids)
        has_basis = bool(decision_id) and any(
            isinstance(b, dict) and b.get("id") == decision_id
            for b in adaptation_basis
        )
        bound = bool(event_ids) or bool(decision_id)
        included = bound and (has_events or has_basis)
        ledger.append(
            {
                "anchor_type": "required_story_beat",
                "anchor_id": text_value,
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": (
                    ""
                    if included
                    else (
                        "missing_binding"
                        if not bound
                        else ("event_excerpt_missing" if event_ids and not has_events else "adaptation_basis_missing")
                    )
                ),
            }
        )
    for idx, item in enumerate(outline.get("required_quotes", []) or []):
        if not isinstance(item, dict):
            continue
        quote = item.get("quote") or item.get("payoff") or item.get("setup")
        if not quote:
            continue
        included = any(ex.get("reason") == f"required_quote:{idx:03d}" for ex in kept)
        fail_reason = anchor_fail_reasons.get(f"required_quote_{idx}", "" if included else "quote_not_in_source_event")
        ledger.append(
            {
                "anchor_type": "required_quote",
                "anchor_id": str(quote),
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": "" if included else fail_reason,
            }
        )
    for idx, item in enumerate(outline.get("must_keep", []) or []):
        text_value = item
        bound_event_id = None
        bound_decision_id = None
        if isinstance(item, dict):
            text_value = str(item.get("text") or "")
            bound_event_id = item.get("event_id")
            bound_decision_id = item.get("adaptation_decision_id")
        if not text_value:
            continue
        has_source = text_value in kept_text
        has_basis = False
        if bound_event_id:
            event = events_by_id.get(bound_event_id)
            has_source = False
            if event and event.get("source_span"):
                span = event["source_span"]
                has_source = any(
                    ex.get("reason") == f"event:{bound_event_id}"
                    and ex.get("chapter_id") == event.get("chapter_id")
                    and ex.get("source_span", {}).get("start", -1) <= span.get("start", -1)
                    and span.get("end", -1) <= ex.get("source_span", {}).get("end", -2)
                    for ex in kept
                )
        if bound_decision_id:
            has_basis = any(
                isinstance(b, dict) and b.get("id") == bound_decision_id
                for b in adaptation_basis
            )
        included = has_source or has_basis
        ledger.append(
            {
                "anchor_type": "must_keep",
                "anchor_id": text_value,
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": (
                    ""
                    if included
                    else (
                        "bound_event_missing_span"
                        if bound_event_id and not has_source
                        else "no_source_or_adaptation_basis"
                    )
                ),
            }
        )
    if fallback_used:
        ledger.append(
            {
                "anchor_type": "fallback",
                "anchor_id": "proportional",
                "requested": False,
                "resolved": False,
                "included": False,
                "omitted": True,
                "reason": "proportional_fallback_used",
            }
        )
    return ledger


def retrieve_source_evidence(
    project_dir,
    outline: dict,
    events: list[dict],
    *,
    max_chars: int = 6000,
    per_chapter_budget: int = 2000,
) -> dict:
    """Build source_evidence; retry once with a bigger budget when required
    anchors would otherwise be omitted."""
    result = _retrieve(
        project_dir,
        outline,
        events,
        max_chars=max_chars,
        per_chapter_budget=per_chapter_budget,
    )
    required_omitted = [
        c for c in result["coverage"]
        if c.get("anchor_type") in (
            "event",
            "chapter",
            "dialogue_anchor",
            "required_story_beat",
            "required_quote",
        )
        and c.get("omitted")
        and c.get("reason") != "event_not_found"
    ]
    if required_omitted:
        retried = _retrieve(
            project_dir,
            outline,
            events,
            max_chars=max_chars * 2,
            per_chapter_budget=per_chapter_budget * 3,
        )
        retried_omitted = [
            c for c in retried["coverage"]
            if c.get("anchor_type") in (
                "event",
                "chapter",
                "dialogue_anchor",
                "required_story_beat",
                "required_quote",
            )
            and c.get("omitted")
        ]
        if len(retried_omitted) < len(required_omitted) or not retried_omitted:
            result = retried
        for coverage_item in result["coverage"]:
            if coverage_item.get("omitted") and coverage_item.get("reason") == "no_excerpt":
                coverage_item["reason"] = "no_excerpt_after_budget_retry"
    return result


def source_evidence_complete(evidence: dict) -> list[str]:
    """Completeness checks driven by the coverage ledger (spec §12.4)."""
    problems: list[str] = []
    if not evidence.get("chapter_ids"):
        problems.append("当前集没有任何原文证据")
    if not evidence.get("events") and not evidence.get("raw_excerpts"):
        problems.append("当前集事件和摘录均为空")
    if evidence.get("retrieval_report", {}).get("fallback_used"):
        problems.append("未找到集纲锚点，使用了全剧比例回退，证据强度低")
    for item in evidence.get("coverage", []) or []:
        if not item.get("requested"):
            continue
        if item.get("omitted"):
            anchor = item.get("anchor_id", "")
            kind = item.get("anchor_type", "anchor")
            reason = item.get("reason", "omitted")
            problems.append(f"锚点 {kind}:{anchor} 未进入原文证据（{reason}）")
    return problems
