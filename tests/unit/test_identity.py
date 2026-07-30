import hashlib
import json

from chromadb_repo_indexer.identity import document_id, namespace_id, record_id, sha256_text
from chromadb_repo_indexer.models import Identity


def test_deterministic_identifiers() -> None:
    identity = Identity("UnitVectorY-Labs", "example", "main")
    expected = hashlib.sha256(
        json.dumps(["UnitVectorY-Labs", "example", "main"], separators=(",", ":")).encode()
    ).hexdigest()
    assert namespace_id(identity) == expected
    parent = document_id(expected, "docs/readme.md")
    assert parent == f"repodoc:v1:{expected}:{sha256_text('docs/readme.md')}"
    assert record_id(expected, "docs/readme.md", "a" * 64, 7).endswith(":" + "a" * 64 + ":00000007")


def test_identity_case_is_preserved() -> None:
    assert namespace_id(Identity("Org", "Repo", "Main")) != namespace_id(Identity("org", "repo", "main"))

