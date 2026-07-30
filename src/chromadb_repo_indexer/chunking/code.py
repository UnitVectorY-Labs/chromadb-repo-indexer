from __future__ import annotations

import os
from pathlib import Path

from tree_sitter_language_pack import PackConfig, configure, get_parser

from .base import Span

STRUCTURAL_TYPES = {
    "class_declaration",
    "class_definition",
    "function_declaration",
    "function_definition",
    "method_declaration",
    "method_definition",
    "interface_declaration",
    "impl_item",
    "struct_item",
    "enum_item",
    "type_declaration",
    "lexical_declaration",
}
_CONFIGURED_CACHE: str | None = None


def _configure_cache() -> None:
    global _CONFIGURED_CACHE
    cache = os.environ.get("CHROMA_REPO_INDEXER_TREE_SITTER_CACHE")
    if cache and cache != _CONFIGURED_CACHE:
        Path(cache).mkdir(parents=True, exist_ok=True)
        configure(PackConfig(cache_dir=cache))
        _CONFIGURED_CACHE = cache


def _symbol(node, source: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        for child in node.named_children:
            if child.type in {"identifier", "type_identifier", "property_identifier"}:
                name = child
                break
    value = source[name.start_byte : name.end_byte].decode("utf-8", "replace") if name else ""
    return f"{node.type}:{value}" if value else node.type


def code_spans(text: str, language: str) -> list[Span] | None:
    try:
        _configure_cache()
        parser = get_parser(language)
        source = text.encode("utf-8")
        tree = parser.parse(source)
    except Exception:
        return None
    if tree.root_node.has_error:
        return None
    nodes = [child for child in tree.root_node.named_children if child.type in STRUCTURAL_TYPES]
    if not nodes:
        nodes = list(tree.root_node.named_children)
    if not nodes:
        return [Span(0, len(text))]
    # Tree-sitter byte offsets equal character offsets only for ASCII. Convert once.
    def character_offset(byte_offset: int) -> int:
        return len(source[:byte_offset].decode("utf-8", "strict"))

    spans: list[Span] = []
    cursor = 0
    for index, node in enumerate(nodes):
        node_start = character_offset(node.start_byte)
        next_start = character_offset(nodes[index + 1].start_byte) if index + 1 < len(nodes) else len(text)
        start = cursor
        end = max(character_offset(node.end_byte), next_start)
        spans.append(Span(start, end, symbol=_symbol(node, source)))
        cursor = end
    if cursor < len(text):
        spans.append(Span(cursor, len(text)))
    return spans
