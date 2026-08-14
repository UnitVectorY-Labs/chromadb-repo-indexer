from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CHUNKING_VERSION = 2


@dataclass(frozen=True)
class Identity:
    organization: str
    repository: str
    branch: str
    commit_sha: str = ""


@dataclass(frozen=True)
class Settings:
    root: Path
    server_url: str
    collection_name: str
    bearer_token: str = ""
    tenant: str = "default_tenant"
    database: str = "default_database"
    include_paths: tuple[str, ...] = ("**",)
    exclude_paths: tuple[str, ...] = ()
    include_extensions: tuple[str, ...] = ()
    exclude_extensions: tuple[str, ...] = ()
    chunk_size: int = 512
    chunk_overlap: int = 64
    batch_size: int = 100
    retry_attempts: int = 3
    dry_run: bool = False
    chunk_report: bool = False
    output_manifest: Path | None = None
    include_document_text_in_manifest: bool = False
    embedding_api_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative_path: str
    extension: str


@dataclass(frozen=True)
class Chunk:
    excerpt: str
    start_line: int
    end_line: int
    section: str = ""
    symbol: str = ""


@dataclass(frozen=True)
class Record:
    id: str
    document: str
    metadata: dict[str, str | int | float | bool]

    def manifest_dict(self, include_document: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "metadata": self.metadata}
        if include_document:
            result["document"] = self.document
        return result


@dataclass
class DiscoveryStats:
    files_scanned: int = 0
    files_eligible: int = 0
    files_binary_skipped: int = 0
    files_other_skipped: int = 0


@dataclass
class SyncSummary:
    namespace_id: str
    organization: str
    repository: str
    branch: str
    files_scanned: int = 0
    files_eligible: int = 0
    files_indexed: int = 0
    files_binary_skipped: int = 0
    files_other_skipped: int = 0
    chunks_desired: int = 0
    chunks_added_or_updated: int = 0
    chunks_unchanged: int = 0
    chunks_deleted: int = 0
    dry_run: bool = False
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
