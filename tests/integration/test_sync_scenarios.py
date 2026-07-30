from pathlib import Path

from chromadb_repo_indexer.config import resolve_settings
from chromadb_repo_indexer.models import Identity
from chromadb_repo_indexer.sync import synchronize


class StatefulRepository:
    records = {}

    def __init__(self, settings):
        self.settings = settings

    def connect(self):
        pass

    def current(self, namespace):
        return {
            record_id: metadata
            for record_id, (_, metadata) in type(self).records.items()
            if metadata["namespace_id"] == namespace
        }

    def effective_batch_size(self):
        return self.settings.batch_size

    def upsert(self, records, batch_size):
        for record in records:
            type(self).records[record.id] = (record.document, record.metadata)

    def delete(self, ids, batch_size):
        for record_id in ids:
            type(self).records.pop(record_id, None)

    def count_namespace(self, namespace):
        return len(self.current(namespace))


def settings(root: Path, **overrides):
    return resolve_settings(
        root=root,
        environ={},
        cli={"server_url": "http://localhost:8000", "collection_name": "integration-test", **overrides},
    )


def test_add_edit_delete_idempotency_and_namespace_isolation(tmp_path: Path) -> None:
    StatefulRepository.records = {}
    root = tmp_path / "repository"
    root.mkdir()
    source = root / "README.md"
    source.write_text("# First\n\nOriginal content.\n", encoding="utf-8")
    main = Identity("Org", "Repo", "main")
    other_branch = Identity("Org", "Repo", "release")

    initial, initial_records = synchronize(settings(root, batch_size=1), main, StatefulRepository)
    assert initial.chunks_added_or_updated == len(initial_records)
    unchanged, _ = synchronize(settings(root), main, StatefulRepository)
    assert unchanged.chunks_added_or_updated == 0
    assert unchanged.chunks_unchanged == len(initial_records)

    branch_summary, branch_records = synchronize(settings(root), other_branch, StatefulRepository)
    assert branch_summary.chunks_added_or_updated == len(branch_records)
    assert len(StatefulRepository.records) == len(initial_records) + len(branch_records)

    old_main_ids = {record.id for record in initial_records}
    source.write_text("# First\n\nEdited content with a new hash.\n", encoding="utf-8")
    edited, edited_records = synchronize(settings(root), main, StatefulRepository)
    assert edited.chunks_added_or_updated == len(edited_records)
    assert edited.chunks_deleted == len(initial_records)
    assert old_main_ids.isdisjoint(StatefulRepository.records)
    assert all(record.id in StatefulRepository.records for record in branch_records)

    source.unlink()
    deleted, _ = synchronize(settings(root), main, StatefulRepository)
    assert deleted.chunks_desired == 0
    assert deleted.chunks_deleted == len(edited_records)
    assert all(record.id in StatefulRepository.records for record in branch_records)
