import json
from collections import Counter
from pathlib import Path

import pytest

from chromadb_repo_indexer import cli
from chromadb_repo_indexer.chunk_report import build_chunk_report
from chromadb_repo_indexer.config import resolve_settings
from chromadb_repo_indexer.errors import ConfigurationError
from chromadb_repo_indexer.models import Identity, Settings
from chromadb_repo_indexer.sync import synchronize


def write_repo(root: Path) -> None:
    (root / "README.md").write_text(
        "# Title\n\nIntro paragraph.\n\n## Section One\n\n"
        + ("word " * 400)
        + "\n\n## Section Two\n\n"
        + ("token " * 400)
        + "\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\n\nShort.\n", encoding="utf-8")
    (root / "notes.txt").write_text("not markdown\n", encoding="utf-8")


def test_cli_chunk_report_prints_stats_without_chroma_config(tmp_path: Path, capsys) -> None:
    write_repo(tmp_path)
    result = cli.run(
        [
            "index",
            "--root", str(tmp_path),
            "--organization", "Org",
            "--repository", "Repo",
            "--branch", "main",
            "--include-extension", "md",
            "--chunk-report",
        ]
    )
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"] == "chunking"
    assert payload["chunk_size"] == 512
    assert payload["files"] == {
        "scanned": 3,
        "eligible": 2,
        "indexed": 2,
        "binary_skipped": 0,
        "other_skipped": 0,
    }
    assert payload["chunks"]["total"] >= 3
    assert payload["chunks"]["tokens"]["max"] <= 512
    assert payload["chunks"]["within_budget"]["pct"] == 100.0
    assert sum(payload["chunks"]["histogram_tokens"].values()) == payload["chunks"]["total"]
    paths = [entry["path"] for entry in payload["files_detail"]]
    assert paths == ["README.md", "docs/guide.md"]
    readme = payload["files_detail"][0]
    assert readme["strategy"] == "markdown"
    assert readme["chunks"] >= 1
    assert readme["total_tokens"] >= readme["tokens"]["min"] * readme["chunks"]


def test_index_without_flag_still_requires_chroma_config(tmp_path: Path) -> None:
    write_repo(tmp_path)
    with pytest.raises(ConfigurationError, match="server_url"):
        cli.run(
            [
                "index",
                "--root", str(tmp_path),
                "--organization", "Org",
                "--repository", "Repo",
                "--branch", "main",
            ]
        )


def test_build_chunk_report_honors_chunk_size(tmp_path: Path) -> None:
    write_repo(tmp_path)
    settings = resolve_settings(
        root=tmp_path,
        cli={"include_extensions": ["md"], "chunk_size": 128, "chunk_overlap": 16, "chunk_report": True},
        environ={},
    )
    report = build_chunk_report(settings, Identity("Org", "Repo", "main"))
    assert report["chunk_size"] == 128
    assert report["chunks"]["tokens"]["max"] <= 128
    assert report["files"]["indexed"] == 2
    assert report["chunks"]["total"] == sum(entry["chunks"] for entry in report["files_detail"])
    assert report["chunks"]["tokens"]["min"] >= 1


def test_report_matches_the_records_sync_would_insert(tmp_path: Path) -> None:
    write_repo(tmp_path)
    settings = resolve_settings(
        root=tmp_path,
        cli={
            "server_url": "https://example.test",
            "collection_name": "test-collection",
            "include_extensions": ["md"],
        },
        environ={},
    )
    identity = Identity("Org", "Repo", "main")

    class FakeRepository:
        def __init__(self, settings) -> None:
            self.upserted = []

        def connect(self) -> None:
            pass

        def current(self, namespace):
            return {}

        def effective_batch_size(self):
            return 100

        def upsert(self, records, batch_size):
            self.upserted.extend(records)

        def delete(self, ids, batch_size):
            pass

        def count_namespace(self, namespace):
            return len(self.upserted)

    repository = FakeRepository(settings)
    summary, _ = synchronize(settings, identity, repository_factory=lambda s: repository)
    report = build_chunk_report(settings, identity)
    sync_counts = Counter(record.metadata["path"] for record in repository.upserted)
    report_counts = {entry["path"]: entry["chunks"] for entry in report["files_detail"]}
    assert set(sync_counts) == set(report_counts)
    assert all(sync_counts[path] == count for path, count in report_counts.items())
    assert summary.chunks_desired == report["chunks"]["total"]


def test_build_chunk_report_single_chunk_has_no_percentiles(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# Only\n\nOne small block.\n", encoding="utf-8")
    settings = Settings(root=tmp_path, server_url="", collection_name="", chunk_report=True)
    report = build_chunk_report(settings, Identity("Org", "Repo", "main"))
    assert report["chunks"]["total"] == 1
    tokens = report["chunks"]["tokens"]
    assert tokens["min"] == tokens["max"] == tokens["mean"] == tokens["median"]
    assert "p25" not in tokens
    assert sum(report["chunks"]["histogram_tokens"].values()) == 1


def test_build_chunk_report_empty_repo(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, server_url="", collection_name="", chunk_report=True)
    report = build_chunk_report(settings, Identity("Org", "Repo", "main"))
    assert report["chunks"]["total"] == 0
    assert report["files"]["indexed"] == 0
    assert report["files_detail"] == []
    assert report["chunks"]["tokens"] == {"min": 0, "max": 0, "mean": 0.0, "median": 0.0}
    assert report["chunks"]["within_budget"]["pct"] == 0.0
