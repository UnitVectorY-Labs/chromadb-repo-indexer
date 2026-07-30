from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from llama_index.core.utils import get_tokenizer
from llama_index.core.node_parser import TokenTextSplitter

from ..models import Chunk


class TokenCounter:
    def __init__(self) -> None:
        self._tokenizer: Callable[[str], list[int]] = get_tokenizer()

    def count(self, text: str) -> int:
        return len(self._tokenizer(text))


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    section: str = ""
    symbol: str = ""


def line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def split_oversized(
    text: str,
    span: Span,
    budget: int,
    overlap: int,
    counter: TokenCounter,
) -> list[Span]:
    if counter.count(text[span.start : span.end]) <= budget:
        return [span]
    value = text[span.start : span.end]
    splitter = TokenTextSplitter(
        chunk_size=budget,
        chunk_overlap=min(overlap, budget - 1),
        tokenizer=counter._tokenizer,
        separator="\n\n",
        backup_separators=["\n", " "],
        keep_whitespaces=True,
    )
    pieces = splitter.split_text(value)
    if any(counter.count(piece) > budget for piece in pieces):
        raise ValueError("chunk_size cannot accommodate a source character after the context prefix")
    parts: list[Span] = []
    previous_piece = ""
    previous_start = 0
    previous_end = 0
    for index, piece in enumerate(pieces):
        if index == 0:
            local_start = value.find(piece)
        else:
            overlap_chars = 0
            maximum = min(len(previous_piece), len(piece))
            for length in range(maximum, 0, -1):
                if previous_piece[-length:] == piece[:length] and counter.count(piece[:length]) <= overlap:
                    overlap_chars = length
                    break
            local_start = previous_end - overlap_chars
            if value[local_start : local_start + len(piece)] != piece:
                local_start = value.find(piece, previous_start + 1)
        if local_start < 0:
            raise ValueError("LlamaIndex splitter returned text that is not an exact source excerpt")
        local_end = local_start + len(piece)
        parts.append(Span(span.start + local_start, span.start + local_end, span.section, span.symbol))
        previous_piece, previous_start, previous_end = piece, local_start, local_end
    return parts


def chunks_from_spans(text: str, spans: list[Span]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for span in spans:
        excerpt = text[span.start : span.end]
        if not excerpt.strip():
            continue
        end_position = max(span.start, span.end - 1)
        chunks.append(
            Chunk(
                excerpt=excerpt,
                start_line=line_number(text, span.start),
                end_line=line_number(text, end_position),
                section=span.section,
                symbol=span.symbol,
            )
        )
    return chunks


def chunk_document(
    text: str,
    strategy: str,
    language: str,
    max_tokens: int,
    overlap: int,
    prefix_for: Callable[[str, str], str],
) -> list[Chunk]:
    if not text.strip():
        return []
    counter = TokenCounter()
    if strategy == "markdown":
        from .markdown import markdown_spans

        structural = markdown_spans(text)
    elif strategy == "code":
        from .code import code_spans

        structural = code_spans(text, language) or [Span(0, len(text))]
    else:
        structural = [Span(0, len(text))]
    final: list[Span] = []
    for span in structural:
        prefix_tokens = counter.count(prefix_for(span.section, span.symbol))
        budget = max_tokens - prefix_tokens
        if budget <= 0:
            raise ValueError("chunk_size is too small for the deterministic context prefix")
        final.extend(split_oversized(text, span, budget, overlap, counter))
    return chunks_from_spans(text, final)
