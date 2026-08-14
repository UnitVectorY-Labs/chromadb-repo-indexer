from __future__ import annotations

import logging
import statistics
import time
from typing import Any

from .chunking.base import TokenCounter
from .classification import read_text
from .discovery import discover_files
from .identity import namespace_id, validate_identity
from .models import CHUNKING_VERSION, Identity, Settings
from .records import build_records

LOGGER = logging.getLogger("chromadb_repo_indexer")

HISTOGRAM_BUCKETS = (128, 256, 384, 512, 768, 1024)


def _percentiles(values: list[int]) -> dict[str, float]:
    if len(values) < 2:
        return {}
    quantiles = statistics.quantiles(sorted(values), n=100, method="inclusive")
    return {
        "p25": round(quantiles[24], 1),
        "p50": round(quantiles[49], 1),
        "p75": round(quantiles[74], 1),
        "p95": round(quantiles[94], 1),
        "p99": round(quantiles[98], 1),
    }


def _size_stats(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "max": 0, "mean": 0.0, "median": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.fmean(values), 1),
        "median": round(statistics.median(values), 1),
        **_percentiles(values),
    }


def _histogram(values: list[int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    previous = 0
    for limit in HISTOGRAM_BUCKETS:
        label = f"0-{limit}" if previous == 0 else f"{previous + 1}-{limit}"
        counts[label] = sum(1 for value in values if previous < value <= limit)
        previous = limit
    counts[f"{previous + 1}+"] = sum(1 for value in values if value > previous)
    return counts


def _pct(part: int, whole: int) -> float:
    if not whole:
        return 0.0
    return round(part * 100.0 / whole, 1)


def build_chunk_report(settings: Settings, identity: Identity) -> dict[str, Any]:
    started = time.monotonic()
    validate_identity(identity)
    namespace = namespace_id(identity)
    LOGGER.info("phase=discover chunk_report namespace=%s", namespace)
    sources, stats = discover_files(settings)
    counter = TokenCounter()
    token_values: list[int] = []
    char_values: list[int] = []
    file_entries: list[dict[str, Any]] = []
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
        if not records:
            continue
        indexed_files += 1
        tokens = [counter.count(record.document) for record in records]
        chars = [len(record.document) for record in records]
        token_values.extend(tokens)
        char_values.extend(chars)
        file_entries.append(
            {
                "path": source.relative_path,
                "strategy": decoded.strategy,
                "chunks": len(records),
                "tokens": _size_stats(tokens),
                "total_tokens": sum(tokens),
            }
        )
    total = len(token_values)
    within_budget = sum(1 for value in token_values if value <= settings.chunk_size)
    below_half_budget = sum(1 for value in token_values if value <= settings.chunk_size // 2)
    report: dict[str, Any] = {
        "report": "chunking",
        "report_version": 1,
        "chunking_version": CHUNKING_VERSION,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "organization": identity.organization,
        "repository": identity.repository,
        "branch": identity.branch,
        "files": {
            "scanned": stats.files_scanned,
            "eligible": stats.files_eligible,
            "indexed": indexed_files,
            "binary_skipped": binary_skipped,
            "other_skipped": stats.files_other_skipped,
        },
        "chunks": {
            "total": total,
            "tokens": _size_stats(token_values),
            "characters": _size_stats(char_values),
            "within_budget": {"count": within_budget, "pct": _pct(within_budget, total)},
            "below_half_budget": {"count": below_half_budget, "pct": _pct(below_half_budget, total)},
            "histogram_tokens": _histogram(token_values),
        },
        "files_detail": file_entries,
        "duration_ms": 0,
    }
    report["duration_ms"] = round((time.monotonic() - started) * 1000)
    LOGGER.info(
        "phase=complete chunk_report files=%d chunks=%d duration_ms=%d",
        indexed_files, total, report["duration_ms"],
    )
    return report
