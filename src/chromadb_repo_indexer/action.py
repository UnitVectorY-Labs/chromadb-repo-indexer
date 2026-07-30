from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from .config import parse_lines, resolve_settings
from .errors import ConfigurationError, IndexerError
from .models import Identity
from .sync import synchronize


def _input(name: str) -> str | None:
    value = os.environ.get("INPUT_" + name.upper())
    return value if value not in (None, "") else None


def _integer(name: str) -> int | None:
    value = _input(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"Action input {name.lower()} must be an integer") from exc


def _boolean(name: str) -> bool | None:
    value = _input(name)
    if value is None:
        return None
    if value.lower() not in {"true", "false"}:
        raise ConfigurationError(f"Action input {name.lower()} must be true or false")
    return value.lower() == "true"


def run() -> int:
    workspace = os.environ.get("GITHUB_WORKSPACE", "")
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    sha = os.environ.get("GITHUB_SHA", "")
    parts = github_repository.split("/")
    if not workspace or len(parts) != 2 or not all(parts) or not ref_name or not sha:
        raise ConfigurationError(
            "Action mode requires GITHUB_WORKSPACE, a valid GITHUB_REPOSITORY, GITHUB_REF_NAME, and GITHUB_SHA"
        )
    root = Path(workspace).resolve()
    config_value = _input("CONFIG-FILE")
    config_path = None
    if config_value:
        config_path = (root / config_value).resolve()
        if not config_path.is_relative_to(root):
            raise ConfigurationError("config-file must remain beneath GITHUB_WORKSPACE")
    cli = {
        "server_url": _input("SERVER-URL"),
        "collection_name": _input("COLLECTION-NAME"),
        "bearer_token": _input("BEARER-TOKEN"),
        "tenant": _input("TENANT"),
        "database": _input("DATABASE"),
        "include_paths": parse_lines(_input("INCLUDE-PATHS")),
        "exclude_paths": parse_lines(_input("EXCLUDE-PATHS")),
        "include_extensions": parse_lines(_input("INCLUDE-EXTENSIONS")),
        "exclude_extensions": parse_lines(_input("EXCLUDE-EXTENSIONS")),
        "chunk_size": _integer("CHUNK-SIZE"),
        "chunk_overlap": _integer("CHUNK-OVERLAP"),
        "batch_size": _integer("BATCH-SIZE"),
        "dry_run": _boolean("DRY-RUN"),
    }
    settings = resolve_settings(root=root, cli=cli, config_path=config_path)
    identity = Identity(parts[0], parts[1], ref_name, sha)
    summary, _ = synchronize(settings, identity)
    data = summary.as_dict()
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        try:
            with Path(output_file).open("a", encoding="utf-8") as output:
                for key, value in data.items():
                    output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
                output.write("summary=" + json.dumps(data, separators=(",", ":")) + "\n")
        except OSError as exc:
            raise IndexerError(f"could not write GitHub Action outputs: {exc}") from exc
    print(json.dumps(data, sort_keys=True))
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    try:
        raise SystemExit(run())
    except (IndexerError, ValueError, TypeError) as exc:
        logging.getLogger("chromadb_repo_indexer").error("%s", exc)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
