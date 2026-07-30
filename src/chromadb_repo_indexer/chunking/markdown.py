from __future__ import annotations

import re

from .base import Span

HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")


def markdown_spans(text: str) -> list[Span]:
    lines = text.splitlines(keepends=True)
    positions: list[int] = []
    cursor = 0
    for line in lines:
        positions.append(cursor)
        cursor += len(line)
    headings: list[tuple[int, int, str]] = []
    fenced = False
    fence_marker = ""
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fenced:
                fenced, fence_marker = True, marker
            elif marker == fence_marker:
                fenced = False
            continue
        if fenced:
            continue
        match = HEADING.match(line.rstrip("\n"))
        if match:
            headings.append((positions[index], len(match.group(1)), match.group(2).strip()))
    if not headings:
        return _block_spans(text, Span(0, len(text)))
    sections: list[Span] = []
    if headings[0][0] > 0:
        sections.append(Span(0, headings[0][0]))
    path: list[str] = []
    for index, (start, level, title) in enumerate(headings):
        path = path[: level - 1]
        path.append(title)
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        sections.append(Span(start, end, " > ".join(path)))
    spans: list[Span] = []
    for section in sections:
        spans.extend(_block_spans(text, section))
    return spans


def _block_spans(text: str, section: Span) -> list[Span]:
    """Split a section at blank-line block boundaries, never inside a fence."""
    value = text[section.start : section.end]
    lines = value.splitlines(keepends=True)
    spans: list[Span] = []
    block_start = 0
    cursor = 0
    fenced = False
    fence_marker = ""
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fenced:
                fenced, fence_marker = True, marker
            elif marker == fence_marker:
                fenced = False
        cursor += len(line)
        if not fenced and not line.strip():
            spans.append(Span(section.start + block_start, section.start + cursor, section.section))
            block_start = cursor
    if block_start < len(value):
        spans.append(Span(section.start + block_start, section.end, section.section))
    return [span for span in spans if text[span.start : span.end].strip()]
