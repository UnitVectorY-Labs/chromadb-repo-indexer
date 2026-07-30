from pathlib import Path

import pytest

from chromadb_repo_indexer.config import resolve_settings
from chromadb_repo_indexer.models import Identity
from chromadb_repo_indexer.sync import synchronize


class FakeRepository:
    initial = {}
    fail_upsert = False
    last = None

    def __init__(self, settings):
        self.settings = settings
        self.records = dict(type(self).initial)
        self.deleted = []
        self.upserted = []
        type(self).last = self

    def connect(self):
        pass

    def current(self, namespace):
        return dict(self.records)

    def effective_batch_size(self):
        return 2

    def upsert(self, records, batch_size):
        self.upserted.extend(record.id for record in records)
        if type(self).fail_upsert:
            raise RuntimeError("forced failure")
        for record in records:
            self.records[record.id] = record.metadata

    def delete(self, ids, batch_size):
        self.deleted.extend(ids)
        for item in ids:
            self.records.pop(item, None)

    def count_namespace(self, namespace):
        return len(self.records)


def make_settings(tmp_path: Path, **kwargs):
    return resolve_settings(
        root=tmp_path,
        environ={},
        cli={"server_url": "http://localhost:8000", "collection_name": "test-collection", **kwargs},
    )


def test_idempotent_diff_and_stale_deletion(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    FakeRepository.initial = {"stale-id": {"schema_version": 1}}
    FakeRepository.fail_upsert = False
    first, records = synchronize(make_settings(tmp_path), Identity("Org", "Repo", "main"), FakeRepository)
    assert first.chunks_added_or_updated == 1
    assert first.chunks_deleted == 1
    assert FakeRepository.last.deleted == ["stale-id"]
    FakeRepository.initial = {record.id: record.metadata for record in records}
    second, _ = synchronize(make_settings(tmp_path), Identity("Org", "Repo", "main"), FakeRepository)
    assert second.chunks_added_or_updated == 0
    assert second.chunks_unchanged == 1
    assert second.chunks_deleted == 0


def test_failed_upsert_never_deletes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("new")
    FakeRepository.initial = {"stale-id": {"schema_version": 1}}
    FakeRepository.fail_upsert = True
    with pytest.raises(RuntimeError, match="forced"):
        synchronize(make_settings(tmp_path), Identity("Org", "Repo", "main"), FakeRepository)
    assert FakeRepository.last.deleted == []
    FakeRepository.fail_upsert = False


def test_dry_run_and_manifest_do_not_mutate(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("new")
    manifest = tmp_path / "out" / "manifest.json"
    FakeRepository.initial = {"stale-id": {"schema_version": 1}}
    summary, records = synchronize(
        make_settings(tmp_path, dry_run=True, output_manifest=manifest),
        Identity("Org", "Repo", "main"),
        FakeRepository,
    )
    assert summary.dry_run is True
    assert FakeRepository.last.upserted == []
    assert FakeRepository.last.deleted == []
    body = manifest.read_text()
    assert records[0].document not in body
    assert records[0].id in body

