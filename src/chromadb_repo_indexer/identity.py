from __future__ import annotations

import hashlib
import json

from .errors import ConfigurationError
from .models import Identity


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def namespace_id(identity: Identity) -> str:
    canonical = json.dumps(
        [identity.organization, identity.repository, identity.branch],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256_text(canonical)


def path_hash(relative_path: str) -> str:
    return sha256_text(relative_path)


def document_id(namespace: str, relative_path: str) -> str:
    return f"repodoc:v1:{namespace}:{path_hash(relative_path)}"


def record_id(namespace: str, relative_path: str, file_hash: str, index: int) -> str:
    return f"repochunk:v1:{namespace}:{path_hash(relative_path)}:{file_hash}:{index:08d}"


def validate_identity(identity: Identity) -> None:
    for name, value in (
        ("organization", identity.organization),
        ("repository", identity.repository),
        ("branch", identity.branch),
    ):
        if not value or value.strip() != value or "\x00" in value:
            raise ConfigurationError(f"{name} must be a non-empty, trimmed value")

