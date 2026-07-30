from pathlib import Path

from chromadb_repo_indexer.classification import read_text
from chromadb_repo_indexer.config import resolve_settings
from chromadb_repo_indexer.discovery import discover_files
from chromadb_repo_indexer.models import SourceFile


def settings(tmp_path: Path, **overrides):
    values = {"server_url": "http://localhost:8000", "collection_name": "test-collection", **overrides}
    return resolve_settings(root=tmp_path, environ={}, cli=values)


def test_discovery_filters_hidden_files_and_never_git(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflow.yml").write_text("name: test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.PY").write_text("print('yes')")
    (tmp_path / "src" / "skip.py").write_text("print('no')")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret")
    files, stats = discover_files(
        settings(tmp_path, include_paths=("**/*.PY", ".github/**"), exclude_paths=("src/skip.py",))
    )
    assert [file.relative_path for file in files] == [".github/workflow.yml", "src/keep.PY"]
    assert stats.files_eligible == 2
    assert all(file.relative_path != ".git" and not file.relative_path.startswith(".git/") for file in files)


def test_decode_bom_newlines_and_binary(tmp_path: Path) -> None:
    text_path = tmp_path / "doc.md"
    text_path.write_bytes(b"\xef\xbb\xbf# Title\r\nBody\r")
    decoded = read_text(SourceFile(text_path, "doc.md", ".md"))
    assert decoded is not None
    assert decoded.text == "# Title\nBody\n"
    assert decoded.strategy == "markdown"
    binary_path = tmp_path / "data.bin"
    binary_path.write_bytes(b"abc\x00def")
    assert read_text(SourceFile(binary_path, "data.bin", ".bin")) is None
