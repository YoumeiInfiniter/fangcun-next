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
    for s, e in spans:
        if e > start and snapped_start == start:
            snapped_start = s
        if e >= end:
            snapped_end = e
            break
    if snapped_end < end and spans:
        snapped_end = spans[-1][1]
    return snapped_start, snapped_end


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
    s1 = chapter_text.find(setup) if setup else -1
    s2 = chapter_text.find(payoff) if payoff else -1
    if s1 < 0 and s2 < 0:
        return None
    if s1 < 0:
        s1 = s2
    if s2 < 0:
        s2 = s1
    start = min(s1, s2)
    end = max(s1 + len(setup or ""), s2 + len(payoff or ""))
    return _snap_span(chapter_text, start, end)


def _event_excerpts(chapter_text: str, chapter: dict, event: dict, budget: int) -> list[dict]:
    span = event.get("source_span") or {}
    start, end = span.get("start", 0), span.get("end", len(chapter_text))
    start, end = _snap_span(chapter_text, start, end)
    for quote in event.get("key_quotes", []) or []:
        qtext = quote.get("text", "")
        if qtext:
            setup = quote.get("setup")
            payoff = quote.get("payoff")
            if quote.get("must_preserve_pairing") and setup and payoff:
                pair = _pair_span(chapter_text, setup, payoff)
                if pair:
                    start = min(start, pair[0])
                    end = max(end, pair[1])
            start, end = _expand_to_quote(chapter_text, start, end, qtext)
    excerpt_text = chapter_text[start:end]
    if len(excerpt_text) > budget:
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
            spans = _sentence_spans(chapter_text[start : start + budget * 2])
            if spans:
                e3 = start + spans[-1][1]
            s3, e3 = _snap_span(chapter_text, start, e3)
        start, end = s3, e3
    if end > start:
        return [_make_excerpt(chapter_text, chapter, start, end, f"event:{event.get('event_id')}")]
    return []


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
    events_by_id = _events_by_id(events)
    anchor_ids = list(outline.get("source_event_ids", []) or [])
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

    dep_ids: list[str] = []
    seen_deps: set[str] = set()
    for eid in anchor_ids:
        for dep in _collect_dependencies(eid, events_by_id, seen_deps):
            event = events_by_id.get(dep)
            if event and event not in resolved_events:
                resolved_events.append(event)
                dep_ids.append(dep)
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

    for event in resolved_events:
        ch_id = event.get("chapter_id")
        chapter_text = chapters.get(ch_id)
        if not chapter_text:
            continue
        if ch_id not in chapter_ids:
            chapter_ids.append(ch_id)
        meta = chapter_meta.get(ch_id, {})
        chapter = {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")}
        excerpts.extend(_event_excerpts(chapter_text, chapter, event, per_chapter_budget))
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
        chapter_dict = {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")}
        has_excerpt = any(ex["chapter_id"] == ch_id for ex in excerpts)
        if not has_excerpt:
            if len(chapter_text) <= per_chapter_budget:
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, 0, len(chapter_text), "chapter_full"))
            else:
                start, end = _snap_span(chapter_text, 0, per_chapter_budget)
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, start, end, "chapter_head"))
    if anchor_chapters:
        used_order.append("chapters")

    # Dialogue anchors: setup/payoff are indivisible units.
    for idx, anchor in enumerate(outline.get("dialogue_anchors", []) or []):
        setup = anchor.get("setup")
        payoff = anchor.get("payoff")
        if not setup and not payoff:
            continue
        # Both ends must exist; a lone end is NOT a valid pair.
        if not setup or not payoff:
            continue
        for ch_id in chapter_ids:
            chapter_text = chapters.get(ch_id)
            if not chapter_text:
                continue
            s1 = chapter_text.find(setup)
            s2 = chapter_text.find(payoff)
            if s1 >= 0 and s2 >= 0:
                span = _snap_span(chapter_text, min(s1, s2), max(s1 + len(setup), s2 + len(payoff)))
                meta = chapter_meta.get(ch_id, {})
                chapter_dict = {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")}
                excerpts.append(_make_excerpt(chapter_text, chapter_dict, span[0], span[1], f"dialogue_anchor:{idx:03d}"))
                break

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
                chapter_dict = {"chapter_index": ch_id, "title": meta.get("title", ""), "file": meta.get("file", "")}
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

    coverage = _build_coverage(
        outline=outline,
        anchor_ids=anchor_ids,
        anchor_chapters=anchor_chapters,
        dep_ids=dep_ids,
        resolved_events=resolved_events,
        kept=kept,
        events_by_id=events_by_id,
        fallback_used=fallback_used,
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
            "total_excerpt_chars": total,
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
        degraded = bool(resolved and not (event or {}).get("source_span"))
        ledger.append(
            {
                "anchor_type": "event",
                "anchor_id": eid,
                "requested": True,
                "resolved": resolved,
                "included": included,
                "omitted": not included,
                "degraded": degraded,
                "degraded_reason": "needs_reanchor" if degraded else "",
                "reason": "" if included else ("event_not_found" if not resolved else "no_excerpt"),
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
        if not (anchor.get("setup") or anchor.get("payoff")):
            continue
        included = any(ex.get("reason") == f"dialogue_anchor:{idx:03d}" for ex in kept)
        ledger.append(
            {
                "anchor_type": "dialogue_anchor",
                "anchor_id": anchor.get("source", f"anchor-{idx:03d}"),
                "requested": True,
                "resolved": included,
                "included": included,
                "omitted": not included,
                "reason": "" if included else "pair_not_in_chapter_or_budget",
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
        has_basis = any(text_value in str(b) for b in adaptation_basis)
        if bound_event_id:
            event = events_by_id.get(bound_event_id)
            has_source = False
            if event and event.get("source_span"):
                span = event["source_span"]
                has_source = any(
                    ex.get("source_span", {}).get("start", -1) <= span.get("start", -1)
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
        if c.get("anchor_type") in ("event", "chapter", "dialogue_anchor")
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
            if c.get("anchor_type") in ("event", "chapter", "dialogue_anchor") and c.get("omitted")
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
