from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import resolve_settings
from .errors import IndexerError
from .models import Identity
from .sync import synchronize


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chromadb-repo-indexer")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    subcommands = parser.add_subparsers(dest="command", required=True)
    index = subcommands.add_parser("index", help="synchronize a repository directory")
    index.add_argument("--root", type=Path, default=Path.cwd())
    index.add_argument("--organization", required=True)
    index.add_argument("--repository", required=True)
    index.add_argument("--branch", required=True)
    index.add_argument("--commit-sha", default="")
    index.add_argument("--server-url")
    index.add_argument("--collection-name")
    index.add_argument("--bearer-token")
    index.add_argument("--tenant")
    index.add_argument("--database")
    index.add_argument("--config", type=Path)
    index.add_argument("--include-path", dest="include_paths", action="append")
    index.add_argument("--exclude-path", dest="exclude_paths", action="append")
    index.add_argument("--include-extension", dest="include_extensions", action="append")
    index.add_argument("--exclude-extension", dest="exclude_extensions", action="append")
    index.add_argument("--chunk-size", type=int)
    index.add_argument("--chunk-overlap", type=int)
    index.add_argument("--batch-size", type=int)
    index.add_argument("--retry-attempts", type=int)
    index.add_argument("--dry-run", action="store_true", default=None)
    index.add_argument("--output-manifest", type=Path)
    index.add_argument("--include-document-text-in-manifest", action="store_true", default=None)
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    values = vars(args)
    identity = Identity(
        organization=values.pop("organization"),
        repository=values.pop("repository"),
        branch=values.pop("branch"),
        commit_sha=values.pop("commit_sha"),
    )
    root = values.pop("root")
    values.pop("command")
    config = values.pop("config")
    values["output_manifest"] = values.get("output_manifest")
    settings = resolve_settings(root=root, cli=values, config_path=config)
    summary, _ = synchronize(settings, identity)
    print(json.dumps(summary.as_dict(), sort_keys=True))
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    try:
        raise SystemExit(run())
    except IndexerError as exc:
        logging.getLogger("chromadb_repo_indexer").error("%s", exc)
        raise SystemExit(2) from None
    except (ValueError, TypeError) as exc:
        logging.getLogger("chromadb_repo_indexer").error("configuration or chunking failed: %s", exc)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
