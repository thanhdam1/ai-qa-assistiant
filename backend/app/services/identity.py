"""Stable source anchors for human-reviewed requirements."""

import hashlib
import re
from typing import Any


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def fingerprint(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length].upper()


def acceptance_criterion_sources(story: Any) -> list[dict[str, str]]:
    occurrences: dict[str, int] = {}
    sources = []
    for index, text in enumerate(story.acceptance_criteria or []):
        key = normalized_text(text)
        occurrences[key] = occurrences.get(key, 0) + 1
        anchor = f"acceptance_criteria:{key}:{occurrences[key]}"
        sources.append(
            {
                "source_id": f"SRC-AC-{fingerprint(anchor)}",
                "source_field": f"acceptance_criteria[{index}]",
                "text": text,
            }
        )
    return sources


def criterion_source_id(criterion: Any, story: Any | None) -> str | None:
    if story is None:
        return criterion.source_id
    sources = acceptance_criterion_sources(story)
    by_id = {source["source_id"]: source for source in sources}
    if criterion.source_id in by_id:
        return criterion.source_id

    reference = criterion.source_reference.strip()
    pointer = re.fullmatch(r"acceptance_criteria\[(\d+)\]", reference, re.IGNORECASE)
    numbered = re.fullmatch(r"AC\s*[-#:]?\s*(\d+)", reference, re.IGNORECASE)
    index = int(pointer.group(1)) if pointer else (int(numbered.group(1)) - 1 if numbered else -1)
    if 0 <= index < len(sources):
        return sources[index]["source_id"]

    matching = [
        source for source in sources
        if normalized_text(source["text"]) == normalized_text(criterion.criterion)
    ]
    if len(matching) == 1:
        return matching[0]["source_id"]

    quote = reference.strip('"“”\' ')
    if len(quote) < 8:
        return None
    fields = [
        ("description", story.description or ""),
        ("business_context", story.business_context or ""),
        *[("dependencies", item) for item in story.dependencies or []],
    ]
    anchors = set()
    for field, text in fields:
        statements = [part.strip() for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text)]
        matching = [part for part in statements if quote in part]
        if not matching and quote in text:
            matching = [text]
        for statement in matching:
            anchors.add(f"{field}:{normalized_text(statement)}")
    if len(anchors) == 1:
        return f"SRC-CONTEXT-{fingerprint(next(iter(anchors)))}"
    return None
