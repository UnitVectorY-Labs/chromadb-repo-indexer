from pathlib import Path

import pytest
from chromadb.errors import NotFoundError, RateLimitError

from chromadb_repo_indexer import chroma
from chromadb_repo_indexer.config import resolve_settings
from chromadb_repo_indexer.models import Record


class FakeCollection:
    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.pages = [
            {"ids": ["a", "b"], "metadatas": [{"schema_version": 1}, {"schema_version": 1}]},
            {"ids": ["c"], "metadatas": [{"schema_version": 1}]},
        ]

    def get(self, **kwargs):
        return self.pages[kwargs["offset"] // 2]

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def delete(self, **kwargs):
        self.deletes.append(kwargs)


class FakeClient:
    def __init__(self, collection=None, missing=False):
        self.collection = collection or FakeCollection()
        self.missing = missing
        self.created = False

    def heartbeat(self):
        return 1

    def get_collection(self, **kwargs):
        if self.missing:
            raise NotFoundError("missing")
        return self.collection

    def get_or_create_collection(self, **kwargs):
        self.created = True
        return self.collection

    def get_max_batch_size(self):
        return 2


def settings(tmp_path: Path, **kwargs):
    return resolve_settings(
        root=tmp_path,
        environ={},
        cli={"server_url": "https://example.test", "collection_name": "test-collection", **kwargs},
    )


def test_repository_pages_and_mutates_without_explicit_embeddings(tmp_path: Path, monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(chroma.chromadb, "HttpClient", lambda **kwargs: client)
    repository = chroma.ChromaRepository(settings(tmp_path, batch_size=2))
    repository.connect()
    assert list(repository.current("namespace")) == ["a", "b", "c"]
    record = Record("id", "document", {"schema_version": 1})
    repository.upsert([record], repository.effective_batch_size())
    assert "embeddings" not in client.collection.upserts[0]
    repository.delete(["id"], 2)
    assert client.collection.deletes == [{"ids": ["id"]}]


def test_dry_run_does_not_create_a_missing_collection(tmp_path: Path, monkeypatch) -> None:
    client = FakeClient(missing=True)
    monkeypatch.setattr(chroma.chromadb, "HttpClient", lambda **kwargs: client)
    repository = chroma.ChromaRepository(settings(tmp_path, dry_run=True))
    repository.connect()
    assert repository.current("namespace") == {}
    assert client.created is False


def test_secret_is_redacted_from_connection_errors(tmp_path: Path, monkeypatch) -> None:
    def fail(**kwargs):
        raise ValueError("bad secret-token")

    monkeypatch.setattr(chroma.chromadb, "HttpClient", fail)
    with pytest.raises(chroma.ChromaError) as error:
        chroma.ChromaRepository(settings(tmp_path, bearer_token="secret-token"))
    assert "secret-token" not in str(error.value)
    assert "<redacted>" in str(error.value)


def test_rate_limits_are_retried(tmp_path: Path, monkeypatch) -> None:
    attempts = 0
    client = FakeClient()

    def construct(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RateLimitError("slow down")
        return client

    monkeypatch.setattr(chroma.chromadb, "HttpClient", construct)
    repository = chroma.ChromaRepository(settings(tmp_path, retry_attempts=3), sleep=lambda _: None)
    assert repository.client is client
    assert attempts == 3
