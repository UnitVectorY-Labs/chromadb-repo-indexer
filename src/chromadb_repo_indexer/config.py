from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

from .errors import ConfigurationError
from .models import Settings

DEFAULTS: dict[str, Any] = {
    "tenant": "default_tenant",
    "database": "default_database",
    "include_paths": ["**"],
    "exclude_paths": [],
    "include_extensions": [],
    "exclude_extensions": [],
    "chunk_size": 512,
    "chunk_overlap": 64,
    "batch_size": 100,
    "retry_attempts": 3,
    "embedding_api_url": "",
    "embedding_model": "",
    "embedding_api_key": "",
}
ENV_MAP = {
    "server_url": "CHROMA_REPO_INDEXER_SERVER_URL",
    "collection_name": "CHROMA_REPO_INDEXER_COLLECTION_NAME",
    "bearer_token": "CHROMA_REPO_INDEXER_BEARER_TOKEN",
    "tenant": "CHROMA_REPO_INDEXER_TENANT",
    "database": "CHROMA_REPO_INDEXER_DATABASE",
    "embedding_api_url": "CHROMA_REPO_INDEXER_EMBEDDING_API_URL",
    "embedding_model": "CHROMA_REPO_INDEXER_EMBEDDING_MODEL",
    "embedding_api_key": "CHROMA_REPO_INDEXER_EMBEDDING_API_KEY",
}
ROOT_KEYS = {"version", "chroma", "files", "chunking", "sync", "embedding"}
SECTION_KEYS = {
    "chroma": {"server_url", "collection_name", "tenant", "database"},
    "files": {"include_paths", "exclude_paths", "include_extensions", "exclude_extensions"},
    "chunking": {"chunk_size", "chunk_overlap"},
    "sync": {"batch_size", "retry_attempts"},
    "embedding": {"api_url", "model", "api_key"},
}


def normalize_extensions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        value = str(value).strip().lower()
        if not value:
            continue
        if value and not value.startswith("."):
            value = "." + value
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def parse_lines(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [line.strip() for line in value.splitlines() if line.strip()]


def load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"could not read config file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("config root must be a mapping")
    unknown = set(raw) - ROOT_KEYS
    if unknown:
        raise ConfigurationError(f"unknown config keys: {', '.join(sorted(unknown))}")
    if raw.get("version") != 1:
        raise ConfigurationError("config version must be 1")
    for section, allowed in SECTION_KEYS.items():
        value = raw.get(section, {})
        if not isinstance(value, dict):
            raise ConfigurationError(f"config section {section} must be a mapping")
        extras = set(value) - allowed
        if extras:
            raise ConfigurationError(f"unknown {section} keys: {', '.join(sorted(extras))}")
    return raw


def _flatten_config(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section in ("chroma", "files", "chunking", "sync"):
        result.update(raw.get(section, {}))
    emb = raw.get("embedding", {})
    if emb.get("api_url"):
        result["embedding_api_url"] = emb["api_url"]
    if emb.get("model"):
        result["embedding_model"] = emb["model"]
    if emb.get("api_key"):
        result["embedding_api_key"] = emb["api_key"]
    return result


def resolve_settings(
    *,
    root: Path,
    cli: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Settings:
    env = os.environ if environ is None else environ
    selected_config = config_path
    if selected_config is None:
        candidate = cli.get("config") or env.get("CHROMA_REPO_INDEXER_CONFIG_FILE")
        selected_config = Path(candidate) if candidate else None
    values = dict(DEFAULTS)
    values.update(_flatten_config(load_yaml(selected_config)))
    for key, env_name in ENV_MAP.items():
        if env.get(env_name) not in (None, ""):
            values[key] = env[env_name]
    for key, value in cli.items():
        if key != "config" and value is not None:
            values[key] = value
    values["root"] = root
    for name in ("include_paths", "exclude_paths"):
        raw = values[name]
        if isinstance(raw, str):
            raw = parse_lines(raw) or []
        if not isinstance(raw, (list, tuple)) or any(not isinstance(x, str) for x in raw):
            raise ConfigurationError(f"{name} must be a list of strings")
        values[name] = tuple(x.strip() for x in raw if x.strip())
    if not values["include_paths"]:
        raise ConfigurationError("include_paths must contain at least one pattern")
    for name in ("include_extensions", "exclude_extensions"):
        raw = values[name]
        if isinstance(raw, str):
            raw = parse_lines(raw) or []
        if not isinstance(raw, (list, tuple)):
            raise ConfigurationError(f"{name} must be a list")
        values[name] = normalize_extensions(raw)
    values.setdefault("bearer_token", "")
    values.setdefault("embedding_api_url", "")
    values.setdefault("embedding_model", "")
    values.setdefault("embedding_api_key", "")
    validate_settings(values)
    allowed = set(Settings.__dataclass_fields__)
    return Settings(**{key: value for key, value in values.items() if key in allowed})


def validate_settings(values: Mapping[str, Any]) -> None:
    root = Path(values["root"])
    if not root.exists() or not root.is_dir():
        raise ConfigurationError(f"root is not an existing directory: {root}")
    url = str(values.get("server_url", ""))
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ConfigurationError("server_url is not a valid HTTP(S) origin") from exc
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.path not in ("", "/"):
        raise ConfigurationError("server_url must be a full HTTP(S) origin without a path")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError("server_url may not contain credentials, query, or fragment")
    collection_value = values.get("collection_name", "")
    collection = collection_value if isinstance(collection_value, str) else ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]", collection):
        raise ConfigurationError("collection_name must be 3-512 characters and use letters, numbers, '.', '_' or '-'")
    for name in ("tenant", "database"):
        if not isinstance(values[name], str) or not values[name].strip():
            raise ConfigurationError(f"{name} must be a non-empty string")
    for name in ("chunk_size", "batch_size", "retry_attempts"):
        if not isinstance(values[name], int) or isinstance(values[name], bool) or values[name] <= 0:
            raise ConfigurationError(f"{name} must be a positive integer")
    overlap = values["chunk_overlap"]
    if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 0:
        raise ConfigurationError("chunk_overlap must be a non-negative integer")
    if overlap >= values["chunk_size"]:
        raise ConfigurationError("chunk_overlap must be smaller than chunk_size")
