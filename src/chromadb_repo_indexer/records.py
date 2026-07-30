from __future__ import annotations

from pathlib import PurePosixPath

from .chunking import chunk_document
from .classification import DecodedFile
from .identity import document_id, record_id, sha256_text
from .models import CHUNKING_VERSION, SCHEMA_VERSION, Identity, Record, SourceFile


def context_prefix(identity: Identity, source: SourceFile, decoded: DecodedFile, section: str, symbol: str) -> str:
    lines = [
        f"Source: {identity.organization}/{identity.repository}@{identity.branch}:{source.relative_path}",
        f"Type: {decoded.file_type}",
    ]
    if section:
        lines.append(f"Section: {section}")
    if symbol:
        lines.append(f"Symbol: {symbol}")
    return "\n".join(lines) + "\n\n"


def build_records(
    identity: Identity,
    namespace: str,
    source: SourceFile,
    decoded: DecodedFile,
    chunk_size: int,
    overlap: int,
) -> list[Record]:
    file_hash = sha256_text(decoded.text)

    def prefix_for(section: str, symbol: str) -> str:
        return context_prefix(identity, source, decoded, section, symbol)

    chunks = chunk_document(
        decoded.text,
        decoded.strategy,
        decoded.language,
        chunk_size,
        overlap,
        prefix_for,
    )
    count = len(chunks)
    parent_id = document_id(namespace, source.relative_path)
    records: list[Record] = []
    for index, chunk in enumerate(chunks):
        metadata: dict[str, str | int | float | bool] = {
            "schema_version": SCHEMA_VERSION,
            "namespace_id": namespace,
            "organization": identity.organization,
            "repository": identity.repository,
            "branch": identity.branch,
            "path": source.relative_path,
            "file_name": PurePosixPath(source.relative_path).name,
            "file_extension": source.extension,
            "file_type": decoded.file_type,
            "language": decoded.language,
            "document_id": parent_id,
            "file_hash": file_hash,
            "chunk_hash": sha256_text(chunk.excerpt),
            "chunk_index": index,
            "chunk_count": count,
            "chunking_strategy": decoded.strategy,
            "chunking_version": CHUNKING_VERSION,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "section": chunk.section,
            "symbol": chunk.symbol,
            "indexed_commit_sha": identity.commit_sha,
        }
        records.append(
            Record(
                id=record_id(namespace, source.relative_path, file_hash, index),
                document=prefix_for(chunk.section, chunk.symbol) + chunk.excerpt,
                metadata=metadata,
            )
        )
    return records

