from pathlib import Path

import pytest
import yaml

from chromadb_repo_indexer import action, cli
from chromadb_repo_indexer.errors import ConfigurationError
from chromadb_repo_indexer.models import SyncSummary


def summary(identity):
    return SyncSummary(
        namespace_id="a" * 64,
        organization=identity.organization,
        repository=identity.repository,
        branch=identity.branch,
        chunks_desired=3,
    )


def test_cli_requires_explicit_identity_and_prints_json(tmp_path: Path, monkeypatch, capsys) -> None:
    captured = {}

    def fake_sync(settings, identity):
        captured["settings"] = settings
        captured["identity"] = identity
        return summary(identity), []

    monkeypatch.setattr(cli, "synchronize", fake_sync)
    result = cli.run(
        [
            "index",
            "--root", str(tmp_path),
            "--organization", "Org",
            "--repository", "Repo",
            "--branch", "main",
            "--server-url", "https://example.test",
            "--collection-name", "test-collection",
        ]
    )
    assert result == 0
    assert captured["identity"].organization == "Org"
    assert '"chunks_desired": 3' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.run(["index", "--root", str(tmp_path)])


def test_action_uses_only_github_identity_and_writes_outputs(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "github-output"
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_REPOSITORY": "Owner/Project",
        "GITHUB_REF_NAME": "main",
        "GITHUB_SHA": "deadbeef",
        "GITHUB_OUTPUT": str(output),
        "INPUT_SERVER_URL": "https://example.test",
        "INPUT_COLLECTION_NAME": "test-collection",
        "INPUT_DRY_RUN": "true",
        "INPUT_EMBEDDING_API_URL": "https://embeddings.example.test",
        "INPUT_EMBEDDING_MODEL": "example-model",
        "INPUT_EMBEDDING_API_KEY": "example-key",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    captured = {}

    def fake_sync(settings, identity):
        captured["identity"] = identity
        captured["settings"] = settings
        return summary(identity), []

    monkeypatch.setattr(action, "synchronize", fake_sync)
    assert action.run() == 0
    assert captured["identity"].organization == "Owner"
    assert captured["identity"].repository == "Project"
    assert captured["identity"].commit_sha == "deadbeef"
    assert captured["settings"].dry_run is True
    assert captured["settings"].embedding_api_url == "https://embeddings.example.test"
    assert captured["settings"].embedding_model == "example-model"
    assert captured["settings"].embedding_api_key == "example-key"
    assert "chunks_desired=3" in output.read_text()


def test_action_rejects_missing_context_before_sync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "malformed")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "abc")
    with pytest.raises(ConfigurationError, match="Action mode requires"):
        action.run()


def test_action_metadata_is_valid() -> None:
    metadata = yaml.safe_load(Path("action.yml").read_text())
    assert metadata["runs"]["using"] == "composite"
    assert metadata["runs"]["steps"][-1]["id"] == "index"
    assert metadata["runs"]["steps"][-1]["env"]["INPUT_SERVER_URL"] == "${{ inputs.server-url }}"
    assert metadata["outputs"]["summary"]["value"] == "${{ steps.index.outputs.summary }}"
    assert {
        "embedding-api-url",
        "embedding-model",
        "embedding-api-key",
    } <= metadata["inputs"].keys()
    assert "organization" not in metadata["inputs"]
    assert "repository" not in metadata["inputs"]
    assert "branch" not in metadata["inputs"]
