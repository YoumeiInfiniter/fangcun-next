"""Build the writer-facing execution brief from the immutable episode context.

The internal ``episode_contract`` remains available to Reviewer and Rewriter,
but Writer receives a task-shaped view.  Internal planning labels (beat IDs,
paywall labels and summary headings) are removed at this boundary so they do
not become screenplay text by copy/paste.
"""

from __future__ import annotations

import re
from typing import Any

from .common import stable_hash


_INTERNAL_MARKERS = re.compile(
    r"(?:EP\s*\d+\s*[-_ ]\s*[BO]\s*\d+|付费点\s*\d*|paywall\s*\d*|\bbeat\s*[-_ ]?\d+|\bB\d{1,3}\b|拦路审判|胜负已定)",
    re.IGNORECASE,
)


def sanitize_writer_text(value: Any) -> str:
    """Remove internal heading prefixes while retaining the actual task."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = _INTERNAL_MARKERS.sub("", text)
    # A planning label followed by a colon is not a useful screenplay
    # instruction.  Keep the clause after it, which is the actionable part.
    if "：" in text:
        prefix, suffix = text.split("：", 1)
        if _INTERNAL_MARKERS.search(prefix) or len(prefix.strip()) <= 12:
            text = suffix.strip()
    elif ":" in text:
        prefix, suffix = text.split(":", 1)
        if _INTERNAL_MARKERS.search(prefix) or len(prefix.strip()) <= 12:
            text = suffix.strip()
    return re.sub(r"\s+", " ", text).strip(" ：:")


def _text(value: Any) -> str:
    return sanitize_writer_text(value)


def _beat_from_required(beat: dict) -> dict:
    result = {
        "requirement": _text(beat.get("text") or beat.get("requirement")),
        "trigger": _text(beat.get("trigger") or beat.get("entry_state")),
        "action": _text(beat.get("action") or beat.get("development")),
        "response": _text(beat.get("response") or beat.get("reaction")),
        "reaction": _text(beat.get("reaction") or beat.get("visible_reaction") or beat.get("response")),
        "outcome": _text(beat.get("outcome") or beat.get("visible_outcome")),
        "source_event_ids": list(beat.get("event_ids") or []),
        "required_visual_beats": [_text(x) for x in (beat.get("required_visual_beats") or [])],
    }
    return {key: value for key, value in result.items() if value not in ("", [], None)}


def _beat_from_plan(beat: dict) -> dict:
    result = {
        "requirement": _text(beat.get("function")),
        "trigger": _text(beat.get("entry_state")),
        "action": _text(beat.get("action") or beat.get("development")),
        "response": _text(beat.get("reaction") or beat.get("response")),
        "reaction": _text(beat.get("reaction") or beat.get("visible_reaction") or beat.get("response")),
        "outcome": _text(beat.get("visible_outcome") or beat.get("outcome")),
        "source_event_ids": list(beat.get("event_ids") or []),
        "required_visual_beats": [_text(x) for x in (beat.get("required_visual_beats") or [])],
        "presentation": beat.get("presentation"),
    }
    return {key: value for key, value in result.items() if value not in ("", [], None)}


def _required_quotes(outline: dict) -> list[dict]:
    quotes: list[dict] = []
    for item in outline.get("required_quotes", []) or []:
        if not isinstance(item, dict) or not item.get("quote"):
            continue
        mode = item.get("mode") or item.get("quote_mode") or "legacy_unspecified"
        if mode not in ("exact", "semantic", "legacy_unspecified"):
            mode = "legacy_unspecified"
        quote = {
            "quote_id": str(item.get("quote_id") or item.get("id") or f"required-quote-{len(quotes) + 1:03d}"),
            "quote": str(item["quote"]),
            "mode": mode,
            "source_event_id": item.get("source_event_id"),
        }
        if item.get("pair_id"):
            quote["pair_id"] = item["pair_id"]
        quotes.append({key: value for key, value in quote.items() if value not in (None, "")})
    for item in outline.get("dialogue_anchors", []) or []:
        if not isinstance(item, dict) or item.get("type") != "quote" or not item.get("quote"):
            continue
        if not any(q.get("quote") == item.get("quote") for q in quotes):
            quotes.append(
                {
                    "quote_id": str(item.get("quote_id") or item.get("id") or f"required-quote-{len(quotes) + 1:03d}"),
                    "quote": str(item["quote"]),
                    "mode": "legacy_unspecified",
                    "source_event_id": item.get("source_event_id"),
                }
            )
    return quotes


def build_episode_execution_brief(
    outline: dict,
    source_evidence: dict | None = None,
    continuity_state: dict | None = None,
    capacity_plan: dict | None = None,
    provisional_batch_context: dict | None = None,
) -> dict:
    """Create a stable writer-facing brief without changing the contract."""
    outline = outline or {}
    required = [_beat_from_required(item) for item in outline.get("required_story_beats", []) or [] if isinstance(item, dict)]
    planned = [_beat_from_plan(item) for item in outline.get("beat_plan", []) or [] if isinstance(item, dict)]
    # Avoid duplicating a planned beat when the outline already provided the
    # same actionable text; IDs are intentionally never copied into this view.
    beats = list(required)
    for item in planned:
        if item not in beats:
            beats.append(item)
    previous = (continuity_state or {}).get("open_hooks", []) or []
    previous_hooks = [_text(item.get("hook")) for item in previous if isinstance(item, dict) and item.get("hook")]
    brief = {
        "brief_version": "0.3.7",
        "episode": outline.get("episode"),
        "title": _text(outline.get("title")),
        "episode_goal": _text(outline.get("episode_goal")),
        "opening_state": _text(outline.get("opening_bridge")),
        "episode_focus": _text(outline.get("episode_focus")),
        "ending_hook": _text(outline.get("ending_hook")),
        "core_beats": beats,
        "required_quotes": _required_quotes(outline),
        "compressible": [_text(x) for x in (outline.get("allowed_compression") or [])],
        "deferred": list((capacity_plan or {}).get("deferred_event_ids", []) or []),
        "forbidden": [_text(x) for x in (outline.get("forbidden_additions") or [])],
        "previous_episode_state": {
            "approved_facts": (continuity_state or {}).get("facts", []) or [],
            "open_hooks": previous_hooks,
            "approved_episodes": (continuity_state or {}).get("approved_episodes", []) or [],
        },
        "source_evidence_refs": [
            item.get("event_id")
            for item in ((source_evidence or {}).get("events", []) or [])
            if isinstance(item, dict) and item.get("event_id")
        ],
        "capacity_choice": {
            "plan_version": (capacity_plan or {}).get("plan_version") or (capacity_plan or {}).get("plan_id"),
            "coverage_mode": (capacity_plan or {}).get("coverage_mode"),
            "priority_mode": (capacity_plan or {}).get("priority_mode"),
            "compressible_event_ids": (capacity_plan or {}).get("compressible_event_ids", []) or [],
            "deferred_event_ids": (capacity_plan or {}).get("deferred_event_ids", []) or [],
        },
        "provisional_batch_context": provisional_batch_context or None,
        "timing_policy": {
            "is_advisory": True,
            "suggested_seconds": outline.get("suggested_seconds"),
            "overflow_action": (capacity_plan or {}).get("overflow_action"),
            "instruction": (
                "该计划明确接受超出原偏好时长，按已选内容执行。"
                if (capacity_plan or {}).get("overflow_action") == "accept_overflow"
                else "时长是预期，不以单一题材阈值阻断创作；优先保证因果、人物认知和可拍性。"
            ),
        },
    }
    # Drop empty collections to keep the brief compact, but retain the stable
    # top-level contract fields so consumers can depend on them.
    brief["execution_brief_hash"] = stable_hash(brief)
    return brief


def verify_execution_brief(brief: dict) -> bool:
    expected = brief.get("execution_brief_hash")
    if not expected:
        return False
    body = {
        key: value
        for key, value in brief.items()
        if key not in ("execution_brief_hash", "context_hash")
    }
    return stable_hash(body) == expected
