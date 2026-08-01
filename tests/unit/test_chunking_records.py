from pathlib import Path

from llama_index.core.utils import get_tokenizer

from chromadb_repo_indexer.classification import DecodedFile
from chromadb_repo_indexer.identity import namespace_id, sha256_text
from chromadb_repo_indexer.models import Identity, SourceFile
from chromadb_repo_indexer.records import build_records


def test_markdown_context_metadata_and_token_limit(tmp_path: Path) -> None:
    text = "# Guide\nIntro.\n\n## Authentication\n" + ("token " * 300)
    source = SourceFile(tmp_path / "guide.md", "docs/guide.md", ".md")
    identity = Identity("Org", "Repo", "main", "abc123")
    records = build_records(
        identity,
        namespace_id(identity),
        source,
        DecodedFile(text, "markdown", "markdown", ""),
        chunk_size=80,
        overlap=10,
    )
    tokenizer = get_tokenizer()
    assert len(records) > 2
    assert all(len(tokenizer(record.document)) <= 80 for record in records)
    auth = [record for record in records if record.metadata["section"] == "Guide > Authentication"]
    assert auth
    assert all("Section: Guide > Authentication\n\n" in record.document for record in auth)
    assert [record.metadata["chunk_index"] for record in records] == list(range(len(records)))
    assert all(record.metadata["chunk_count"] == len(records) for record in records)
    assert all(record.metadata["indexed_commit_sha"] == "abc123" for record in records)


def test_python_uses_structural_symbols(tmp_path: Path) -> None:
    text = "def first():\n    return 1\n\nclass Second:\n    pass\n"
    source = SourceFile(tmp_path / "module.py", "module.py", ".py")
    identity = Identity("Org", "Repo", "main")
    records = build_records(
        identity,
        namespace_id(identity),
        source,
        DecodedFile(text, "code", "python", "python"),
        512,
        64,
    )
    assert len(records) == 2
    assert "first" in str(records[0].metadata["symbol"])
    assert "Second" in str(records[1].metadata["symbol"])
    assert "def first" in records[0].document
    assert "class Second" in records[1].document


def test_code_keeps_preamble_separate_from_the_first_symbol(tmp_path: Path) -> None:
    text = '"""Module documentation."""\n\nimport os\n\ndef first():\n    return os.name\n'
    source = SourceFile(tmp_path / "module.py", "module.py", ".py")
    identity = Identity("Org", "Repo", "main")
    records = build_records(
        identity,
        namespace_id(identity),
        source,
        DecodedFile(text, "code", "python", "python"),
        512,
        64,
    )

    assert len(records) == 2
    assert records[0].metadata["symbol"] == ""
    assert "import os" in records[0].document
    assert "first" in str(records[1].metadata["symbol"])
    assert "def first" in records[1].document


def test_file_hash_uses_normalized_full_text(tmp_path: Path) -> None:
    text = "hello\n"
    source = SourceFile(tmp_path / "note.txt", "note.txt", ".txt")
    identity = Identity("Org", "Repo", "main")
    records = build_records(identity, namespace_id(identity), source, DecodedFile(text, "generic", "text", ""), 512, 64)
    assert records[0].metadata["file_hash"] == sha256_text(text)
    assert records[0].metadata["chunk_hash"] == sha256_text(text)


def test_markdown_keeps_fences_and_tables_intact_when_they_fit(tmp_path: Path) -> None:
    fence = "```python\ndef example():\n\n    return 1\n```"
    table = "| Name | Value |\n| --- | --- |\n| one | two |"
    text = "# Blocks\n\n" + ("long introduction " * 100) + "\n\n" + fence + "\n\n" + table + "\n"
    source = SourceFile(tmp_path / "blocks.md", "blocks.md", ".md")
    identity = Identity("Org", "Repo", "main")
    records = build_records(
        identity,
        namespace_id(identity),
        source,
        DecodedFile(text, "markdown", "markdown", ""),
        80,
        10,
    )
    fence_records = [record for record in records if "```python" in record.document]
    table_records = [record for record in records if "| Name | Value |" in record.document]
    assert len(fence_records) == 1 and fence in fence_records[0].document
    assert len(table_records) == 1 and table in table_records[0].document


def test_markdown_groups_small_blocks_in_one_heading_section(tmp_path: Path) -> None:
    text = """# Usage

**Global Flags**

| Flag | Description |
| --- | --- |
| `--version`, `-v` | Print the version |
| `--help`, `-h` | Show help |
"""
    source = SourceFile(tmp_path / "usage.md", "docs/USAGE.md", ".md")
    identity = Identity("Org", "Repo", "main")
    records = build_records(
        identity,
        namespace_id(identity),
        source,
        DecodedFile(text, "markdown", "markdown", ""),
        chunk_size=512,
        overlap=64,
    )

    assert len(records) == 1
    assert "**Global Flags**" in records[0].document
    assert "| `--version`, `-v` | Print the version |" in records[0].document


def test_malformed_code_falls_back_without_failure(tmp_path: Path) -> None:
    text = "def broken(:\n  still text\n"
    source = SourceFile(tmp_path / "broken.py", "broken.py", ".py")
    identity = Identity("Org", "Repo", "main")
    records = build_records(
        identity,
        namespace_id(identity),
        source,
        DecodedFile(text, "code", "python", "python"),
        512,
        64,
    )
    assert len(records) == 1
    assert records[0].metadata["symbol"] == ""
    assert text in records[0].document
