"""Canonical entity extraction and deterministic typo checks."""

from __future__ import annotations

import re


def canonical_characters(events: list[dict]) -> list[str]:
    names: list[str] = []
    for event in events:
        for name in event.get("characters", []) or []:
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        for quote in event.get("key_quotes", []) or []:
            speaker = quote.get("speaker")
            if isinstance(speaker, str) and speaker.strip():
                names.append(speaker.strip())
    return list(dict.fromkeys(names))


def validate_entity_names(content: str, events: list[dict], aliases: dict | None = None) -> list[str]:
    """Catch accidental character-name transpositions without fuzzy guessing."""
    aliases = aliases or {}
    allowed: set[str] = set()
    for canonical, values in aliases.items():
        allowed.add(str(canonical))
        if isinstance(values, str):
            allowed.add(values)
        elif isinstance(values, list):
            allowed.update(str(value) for value in values)
    problems: list[str] = []
    for canonical in canonical_characters(events):
        if not (3 <= len(canonical) <= 4) or len(set(canonical)) != len(canonical):
            continue
        # Match only contiguous Han-character tokens of the same length and
        # report exact permutations.  This avoids broad edit-distance guesses.
        candidates = {
            content[index : index + len(canonical)]
            for index in range(max(0, len(content) - len(canonical) + 1))
            if re.fullmatch(r"[\u3400-\u9fff]+", content[index : index + len(canonical)])
        }
        for candidate in candidates:
            if candidate == canonical or candidate in allowed:
                continue
            if sorted(candidate) == sorted(canonical):
                problems.append(f"疑似角色名次序错误：{candidate}；原文规范名为 {canonical}")
    return sorted(set(problems))
