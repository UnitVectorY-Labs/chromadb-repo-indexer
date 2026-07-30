from pathlib import Path

import pytest

from chromadb_repo_indexer.config import normalize_extensions, resolve_settings
from chromadb_repo_indexer.errors import ConfigurationError


def test_config_precedence_and_extension_normalization(tmp_path: Path) -> None:
    config = tmp_path / "indexer.yml"
    config.write_text(
        """version: 1
chroma:
  server_url: https://config.example
  collection_name: config-collection
files:
  exclude_extensions: [LOCK]
chunking:
  chunk_size: 300
sync:
  retry_attempts: 2
""",
        encoding="utf-8",
    )
    settings = resolve_settings(
        root=tmp_path,
        config_path=config,
        environ={"CHROMA_REPO_INDEXER_COLLECTION_NAME": "env-collection"},
        cli={"server_url": "https://cli.example", "chunk_size": 400},
    )
    assert settings.server_url == "https://cli.example"
    assert settings.collection_name == "env-collection"
    assert settings.chunk_size == 400
    assert settings.retry_attempts == 2
    assert settings.exclude_extensions == (".lock",)


def test_config_rejects_unknown_keys_and_bearer_token(tmp_path: Path) -> None:
    config = tmp_path / "bad.yml"
    config.write_text("version: 1\nchroma:\n  bearer_token: secret\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown chroma keys"):
        resolve_settings(root=tmp_path, config_path=config, environ={}, cli={})


@pytest.mark.parametrize("value,expected", [(["PY", ".Md", "py"], (".py", ".md")), ([""], ())])
def test_normalize_extensions(value, expected) -> None:
    assert normalize_extensions(value) == expected


def test_validation_rejects_url_paths_and_bad_overlap(tmp_path: Path) -> None:
    base = {"server_url": "https://example.test/api", "collection_name": "valid-name"}
    with pytest.raises(ConfigurationError, match="origin"):
        resolve_settings(root=tmp_path, environ={}, cli=base)
    base["server_url"] = "https://example.test"
    base.update(chunk_size=32, chunk_overlap=32)
    with pytest.raises(ConfigurationError, match="smaller"):
        resolve_settings(root=tmp_path, environ={}, cli=base)

