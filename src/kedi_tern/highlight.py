"""Convert the grammar's captures into non-overlapping Tern decorations.

Offsets are zero-based, end-exclusive UTF-16 code units. This module parses
source only: embedded Python is never executed.
"""

from __future__ import annotations

import heapq
import re
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

import tree_sitter_kedi
import tree_sitter_python
from tree_sitter import Language, Node, Parser, Query, QueryCursor

MAX_SOURCE_BYTES = 1024 * 1024
MAX_CAPTURES = 100_000

CAPTURE_TO_TERN = {
    "comment": "syntaxComment",
    "keyword": "syntaxKeyword",
    "string": "syntaxString",
    "number": "syntaxNumber",
    "float": "syntaxNumber",
    "boolean": "syntaxKeyword",
    "constant": "syntaxVariable",
    "constant.builtin": "syntaxKeyword",
    "function": "syntaxFunction",
    "method": "syntaxFunction",
    "constructor": "syntaxFunction",
    "type": "syntaxType",
    "namespace": "syntaxType",
    "variable": "syntaxVariable",
    "property": "syntaxVariable",
    "label": "syntaxVariable",
    "operator": "syntaxOperator",
    "punctuation": "syntaxPunctuation",
    "escape": "syntaxString",
    "embedded": "syntaxVariable",
}


def token_for_capture(name: str) -> str | None:
    """Prefer an exact mapping, then progressively remove dotted suffixes."""
    if name.startswith("_"):
        return None
    while name:
        if name in CAPTURE_TO_TERN:
            return CAPTURE_TO_TERN[name]
        name = name.rpartition(".")[0]
    return None


@dataclass(frozen=True)
class Capture:
    start: int
    end: int
    token: str
    priority: int = 0
    pattern: int = 0
    capture_index: int = 0
    layer: int = 0


def resolve_overlaps(captures: list[Capture]) -> list[tuple[int, int, str]]:
    """Sweep boundaries in O(n log n), choosing one color for every segment.

    Higher language layer wins, then explicit query priority, narrower ranges,
    and later query patterns. A capture's declaration index breaks remaining ties.
    This is our documented policy, not an implicit Tree-sitter guarantee.
    """
    ordered = sorted((c for c in captures if c.end > c.start), key=lambda c: c.start)
    boundaries = sorted({p for c in ordered for p in (c.start, c.end)})
    active: list[tuple[int, int, int, int, int, str, int, int]] = []
    result: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        while cursor < len(ordered) and ordered[cursor].start <= start:
            c = ordered[cursor]
            heapq.heappush(
                active,
                (
                    -c.layer,
                    -c.priority,
                    c.end - c.start,
                    -c.pattern,
                    -c.capture_index,
                    c.token,
                    cursor,
                    c.end,
                ),
            )
            cursor += 1
        while active and active[0][-1] <= start:
            heapq.heappop(active)
        if not active:
            continue
        token = active[0][5]
        if result and result[-1][1] == start and result[-1][2] == token:
            result[-1] = (result[-1][0], end, token)
        else:
            result.append((start, end, token))
    return result


def utf16_offsets(source: str, boundaries: set[int]) -> tuple[dict[int, int], int]:
    """Convert only requested UTF-8 boundaries, without a per-byte array."""
    converted = {0: 0} if 0 in boundaries else {}
    byte_offset = units = 0
    for char in source:
        byte_offset += len(char.encode("utf-8"))
        units += 2 if ord(char) > 0xFFFF else 1
        if byte_offset in boundaries:
            converted[byte_offset] = units
    if converted.keys() != boundaries:
        raise ValueError("Capture offset is not a UTF-8 character boundary")
    return converted, units


@lru_cache(maxsize=1)
def grammar() -> tuple[Language, Query]:
    language = Language(tree_sitter_kedi.language())
    source = files("tree_sitter_kedi").joinpath("queries/highlights.scm").read_text("utf-8")
    return language, Query(language, source)


@lru_cache(maxsize=1)
def injections() -> Query:
    source = files("tree_sitter_kedi").joinpath("queries/injections.scm").read_text("utf-8")
    return Query(grammar()[0], source)


@lru_cache(maxsize=1)
def python_grammar() -> tuple[Language, Query]:
    language = Language(tree_sitter_python.language())
    # Upstream captures a method name as both function.method and property.
    # Give the callable role priority under our later-pattern-wins policy.
    method_priority = """
    ((call function: (attribute attribute: (identifier) @function.method))
     (#set! priority "1"))
    """
    return language, Query(language, tree_sitter_python.HIGHLIGHTS_QUERY + method_priority)


def collect_captures(
    query: Query,
    root: Node,
    captures: list[Capture],
    *,
    offset: int = 0,
    layer: int = 0,
) -> None:
    capture_indices = {query.capture_name(i): i for i in range(query.capture_count)}
    for pattern, match in QueryCursor(query).matches(root):
        settings = query.pattern_settings(pattern)
        priority = int(settings.get("priority") or 0)
        for name, nodes in match.items():
            token = token_for_capture(name)
            if token is None:
                continue
            for node in nodes:
                captures.append(
                    Capture(
                        offset + node.start_byte,
                        offset + node.end_byte,
                        token,
                        priority,
                        pattern,
                        capture_indices[name],
                        layer,
                    )
                )
                if len(captures) > MAX_CAPTURES:
                    raise ValueError("Source produces too many highlight captures")


def highlight(source: str) -> dict:
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds the 1 MiB viewer limit")
    # Kedi's fenced-block scanner expects LF. Normalize only the parser input,
    # remembering removed CR positions so decorations still address the original.
    removed_cr = [m.start() - i for i, m in enumerate(re.finditer(b"\r\n", encoded))]
    encoded = encoded.replace(b"\r\n", b"\n")
    language, query = grammar()
    tree = Parser(language).parse(encoded)
    captures: list[Capture] = []
    collect_captures(query, tree.root_node, captures)
    has_errors = tree.root_node.has_error

    injection_query = injections()
    regions = set()
    for pattern, match in QueryCursor(injection_query).matches(tree.root_node):
        if injection_query.pattern_settings(pattern).get("injection.language") == "python":
            for node in match.get("injection.content", []):
                if node.end_byte > node.start_byte:
                    regions.add((node.start_byte, node.end_byte))

    if regions:
        python_language, python_query = python_grammar()
        parser = Parser(python_language)
        for start, end in sorted(regions):
            # Keep indentation and parse each region independently. Shift local
            # byte offsets into the document before restoring CRLF and UTF-16.
            python_tree = parser.parse(encoded[start:end])
            has_errors |= python_tree.root_node.has_error
            # Uncaptured Python punctuation/whitespace must not inherit Kedi's
            # surrounding string.special color. Real Python tokens sit above it.
            captures.append(Capture(start, end, "syntaxVariable", layer=1))
            collect_captures(python_query, python_tree.root_node, captures, offset=start, layer=2)
            if len(captures) > MAX_CAPTURES:
                raise ValueError("Source produces too many highlight captures")

    spans = resolve_overlaps(captures)
    if removed_cr:
        spans = [
            (start + bisect_left(removed_cr, start), end + bisect_left(removed_cr, end), token)
            for start, end, token in spans
        ]
    offsets, length = utf16_offsets(source, {p for a, b, _ in spans for p in (a, b)})
    return {
        "schema": 1,
        "utf16_length": length,
        "has_errors": has_errors,
        "decorations": [
            {"from": offsets[start], "to": offsets[end], "s": token} for start, end, token in spans
        ],
    }
