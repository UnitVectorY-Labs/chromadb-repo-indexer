from __future__ import annotations

import logging
import statistics
import time
from typing import Any

from .chunking.base import TokenCounter
from .classification import read_text
from .discovery import discover_files
from .identity import namespace_id
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


def build_chunk_report(settings: Settings, verbose: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    root = settings.root
    identity = Identity("local", root.name or "root", "local")
    namespace = namespace_id(identity)
    LOGGER.info("phase=discover chunk_report root=%s", root)
    sources, stats = discover_files(settings)
    counter = TokenCounter()
    token_values: list[int] = []
    char_values: list[int] = []
    file_entries: list[dict[str, Any]] = []
    extension_data: dict[str, dict[str, Any]] = {}
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
        data = extension_data.setdefault(
            source.extension or "(none)", {"files": 0, "chunks": 0, "token_values": []}
        )
        data["files"] += 1
        data["chunks"] += len(records)
        data["token_values"].extend(tokens)
    by_extension: dict[str, Any] = {}
    for label, data in sorted(
        extension_data.items(),
        key=lambda item: (-sum(item[1]["token_values"]), item[0]),
    ):
        values = data["token_values"]
        by_extension[label] = {
            "files": data["files"],
            "chunks": data["chunks"],
            "total_tokens": sum(values),
            "tokens": _size_stats(values),
        }
    total = len(token_values)
    within_budget = sum(1 for value in token_values if value <= settings.chunk_size)
    below_half_budget = sum(1 for value in token_values if value <= settings.chunk_size // 2)
    report: dict[str, Any] = {
        "report": "chunking",
        "report_version": 3,
        "chunking_version": CHUNKING_VERSION,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "root": str(root),
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
        "by_extension": by_extension,
        "duration_ms": 0,
    }
    if verbose:
        report["files_detail"] = file_entries
    report["duration_ms"] = round((time.monotonic() - started) * 1000)
    LOGGER.info(
        "phase=complete chunk_report files=%d chunks=%d duration_ms=%d",
        indexed_files, total, report["duration_ms"],
    )
    return report


def _stat_line(stats: dict[str, float | int]) -> str:
    order = ("min", "p25", "p50", "p75", "p95", "p99", "max", "mean", "median")
    return "  ".join(f"{key}={stats[key]}" for key in order if key in stats)


def format_chunk_report(report: dict[str, Any]) -> str:
    files = report["files"]
    chunks = report["chunks"]
    lines = [
        f"Chunk report: {report['root']}",
        (
            f"chunking_version={report['chunking_version']} "
            f"chunk_size={report['chunk_size']} "
            f"chunk_overlap={report['chunk_overlap']} "
            f"duration={report['duration_ms']}ms"
        ),
        "",
        "Files",
        f"  scanned         {files['scanned']}",
        f"  eligible        {files['eligible']}",
        f"  indexed         {files['indexed']}",
        f"  binary_skipped  {files['binary_skipped']}",
        f"  other_skipped   {files['other_skipped']}",
        "",
        "Chunks",
        f"  total           {chunks['total']}",
        f"  within_budget   {chunks['within_budget']['count']} ({chunks['within_budget']['pct']}%)",
        f"  below_half      {chunks['below_half_budget']['count']} ({chunks['below_half_budget']['pct']}%)",
        f"  tokens          {_stat_line(chunks['tokens'])}",
        f"  characters      {_stat_line(chunks['characters'])}",
        "  histogram (tokens)",
    ]
    for label, count in chunks["histogram_tokens"].items():
        lines.append(f"    {label:<10} {count}")
    if report.get("by_extension"):
        lines.append("")
        lines.append("By extension")
        lines.append(f"  {'ext':<12} {'files':>5} {'chunks':>6} {'total_tokens':>12}")
        for label, data in report["by_extension"].items():
            lines.append(
                f"  {label:<12} {data['files']:>5} {data['chunks']:>6} {data['total_tokens']:>12}"
            )
    if report.get("files_detail"):
        lines.append("")
        lines.append("Files detail")
        lines.append(f"  {'path':<40} {'strategy':<12} {'chunks':>6} {'tokens':>8}")
        for entry in report["files_detail"]:
            lines.append(
                f"  {entry['path']:<40} {entry['strategy']:<12} {entry['chunks']:>6} {entry['total_tokens']:>8}"
            )
    return "\n".join(lines)
