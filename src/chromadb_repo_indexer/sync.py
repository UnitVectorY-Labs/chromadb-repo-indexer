from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .chroma import ChromaRepository
from .classification import read_text
from .discovery import discover_files
from .errors import ChromaError, IndexerError
from .identity import namespace_id, validate_identity
from .models import CHUNKING_VERSION, SCHEMA_VERSION, Identity, Record, Settings, SyncSummary
from .records import build_records

LOGGER = logging.getLogger("chromadb_repo_indexer")


def synchronize(
    settings: Settings,
    identity: Identity,
    repository_factory=ChromaRepository,
) -> tuple[SyncSummary, list[Record]]:
    started = time.monotonic()
    validate_identity(identity)
    namespace = namespace_id(identity)
    LOGGER.info("phase=discover namespace=%s collection=%s", namespace, settings.collection_name)
    sources, stats = discover_files(settings)
    desired: list[Record] = []
    indexed_files = 0
    binary_skipped = 0
    for source in sources:
        decoded = read_text(source)
        if decoded is None:
            binary_skipped += 1
            LOGGER.info("phase=discover skipped=binary path=%s", source.relative_path)
            continue
        records = build_records(
            identity,
            namespace,
            source,
            decoded,
            settings.chunk_size,
            settings.chunk_overlap,
        )
        if records:
            indexed_files += 1
            desired.extend(records)
    desired.sort(key=lambda item: (str(item.metadata["path"]), int(item.metadata["chunk_index"])))
    desired_by_id = {record.id: record for record in desired}
    if len(desired_by_id) != len(desired):
        raise IndexerError("desired state contains duplicate deterministic record IDs")

    LOGGER.info("phase=connect namespace=%s desired=%d", namespace, len(desired))
    remote = repository_factory(settings)
    remote.connect()
    existing = remote.current(namespace)
    desired_ids = set(desired_by_id)
    existing_ids = set(existing)
    schema_updates = {
        record_id
        for record_id in desired_ids & existing_ids
        if existing[record_id].get("schema_version") != SCHEMA_VERSION
        or existing[record_id].get("chunking_version") != CHUNKING_VERSION
    }
    upsert_ids = sorted((desired_ids - existing_ids) | schema_updates)
    stale_ids = sorted(existing_ids - desired_ids)
    unchanged = len((desired_ids & existing_ids) - schema_updates)
    summary = SyncSummary(
        namespace_id=namespace,
        organization=identity.organization,
        repository=identity.repository,
        branch=identity.branch,
        files_scanned=stats.files_scanned,
        files_eligible=stats.files_eligible,
        files_indexed=indexed_files,
        files_binary_skipped=binary_skipped,
        files_other_skipped=stats.files_other_skipped,
        chunks_desired=len(desired),
        chunks_added_or_updated=len(upsert_ids),
        chunks_unchanged=unchanged,
        chunks_deleted=len(stale_ids),
        dry_run=settings.dry_run,
    )
    if settings.output_manifest:
        write_manifest(settings.output_manifest, summary, desired, settings.include_document_text_in_manifest)
    LOGGER.info(
        "phase=diff add_or_update=%d unchanged=%d delete=%d dry_run=%s",
        len(upsert_ids), unchanged, len(stale_ids), settings.dry_run,
    )
    if not settings.dry_run:
        batch_size = remote.effective_batch_size()
        # Deletion is deliberately unreachable until every upsert batch returns successfully.
        remote.upsert([desired_by_id[item] for item in upsert_ids], batch_size)
        remote.delete(stale_ids, batch_size)
        actual = remote.count_namespace(namespace)
        if actual != len(desired):
            raise ChromaError(f"verification failed: expected {len(desired)} namespace records, found {actual}")
    summary.duration_ms = round((time.monotonic() - started) * 1000)
    LOGGER.info("phase=complete namespace=%s duration_ms=%d", namespace, summary.duration_ms)
    return summary, desired


def write_manifest(path: Path, summary: SyncSummary, records: list[Record], include_document: bool) -> None:
    payload = {
        "manifest_version": 1,
        "summary": summary.as_dict(),
        "records": [record.manifest_dict(include_document) for record in records],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        raise IndexerError(f"could not write manifest {path}: {exc}") from exc
