from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from typing import Any, TypeVar
from urllib.parse import urlsplit

import chromadb
import httpx
from chromadb.errors import NotFoundError

from .errors import ChromaError
from .models import Record, Settings

T = TypeVar("T")


def _safe_error(exc: Exception, settings: Settings) -> str:
    message = str(exc)
    for secret in (settings.bearer_token,):
        if secret:
            message = message.replace(secret, "<redacted>")
    return message[:1000]


def _status_code(exc: Exception) -> int | None:
    candidates = [exc, getattr(exc, "response", None)]
    cursor = exc.__cause__ or exc.__context__
    while cursor is not None and cursor not in candidates:
        candidates.extend([cursor, getattr(cursor, "response", None)])
        cursor = cursor.__cause__ or cursor.__context__
    for candidate in candidates:
        status = getattr(candidate, "status_code", None) or getattr(candidate, "status", None)
        code = getattr(candidate, "code", None)
        if status is None and callable(code):
            try:
                status = code()
            except (TypeError, ValueError):
                status = None
        if isinstance(status, int):
            return status
    return None


def _retryable(exc: Exception) -> bool:
    status = _status_code(exc)
    if status is not None:
        return status == 429 or status >= 500
    cursor: BaseException | None = exc
    while cursor is not None:
        if isinstance(cursor, (ConnectionError, TimeoutError, OSError, httpx.TransportError)):
            return True
        cursor = cursor.__cause__ or cursor.__context__
    return False


class ChromaRepository:
    def __init__(self, settings: Settings, sleep: Callable[[float], None] = time.sleep) -> None:
        self.settings = settings
        self._sleep = sleep
        parsed = urlsplit(settings.server_url)
        headers = {"Authorization": f"Bearer {settings.bearer_token}"} if settings.bearer_token else None
        self.client = None
        for attempt in range(1, settings.retry_attempts + 1):
            try:
                self.client = chromadb.HttpClient(
                    host=parsed.hostname or "",
                    port=parsed.port or (443 if parsed.scheme == "https" else 80),
                    ssl=parsed.scheme == "https",
                    headers=headers,
                    tenant=settings.tenant,
                    database=settings.database,
                )
                break
            except Exception as exc:
                if attempt >= settings.retry_attempts or not _retryable(exc):
                    raise ChromaError(f"could not configure Chroma client: {_safe_error(exc, settings)}") from exc
                sleep(min(8.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.25))
        self.collection: Any = None
        self._collection_missing = False

    def _call(self, operation: str, function: Callable[[], T]) -> T:
        attempts = self.settings.retry_attempts
        for attempt in range(1, attempts + 1):
            try:
                return function()
            except Exception as exc:
                if attempt >= attempts or not _retryable(exc):
                    raise ChromaError(f"Chroma {operation} failed: {_safe_error(exc, self.settings)}") from exc
                self._sleep(min(8.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.25))
        raise AssertionError("unreachable")

    def connect(self) -> None:
        self._call("heartbeat", self.client.heartbeat)
        if self.settings.dry_run:
            try:
                self.collection = self.client.get_collection(
                    name=self.settings.collection_name,
                    embedding_function=None,
                )
                return
            except NotFoundError:
                self._collection_missing = True
                return
            except Exception:
                # Repeat through the retry classifier so transient failures are bounded.
                self.collection = self._call(
                    "collection lookup",
                    lambda: self.client.get_collection(
                        name=self.settings.collection_name,
                        embedding_function=None,
                    ),
                )
                return
        self.collection = self._call(
            "collection lookup",
            lambda: self.client.get_or_create_collection(
                name=self.settings.collection_name,
                embedding_function=None,
            ),
        )

    def effective_batch_size(self) -> int:
        maximum = self.settings.batch_size
        getter = getattr(self.client, "get_max_batch_size", None)
        if callable(getter):
            try:
                maximum = min(maximum, int(self._call("maximum batch size lookup", getter)))
            except (TypeError, ValueError):
                pass
        return max(1, maximum)

    def current(self, namespace: str) -> dict[str, dict[str, Any]]:
        if self._collection_missing:
            return {}
        if self.collection is None:
            raise RuntimeError("connect must be called first")
        result: dict[str, dict[str, Any]] = {}
        offset = 0
        page_size = max(1, self.settings.batch_size)
        while True:
            page = self._call(
                "namespace retrieval",
                lambda: self.collection.get(
                    where={"namespace_id": namespace},
                    limit=page_size,
                    offset=offset,
                    include=["metadatas"],
                ),
            )
            ids = list(page.get("ids") or [])
            metadatas = list(page.get("metadatas") or [])
            for index, record_id in enumerate(ids):
                result[record_id] = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            if len(ids) < page_size:
                break
            offset += len(ids)
        return result

    def upsert(self, records: list[Record], batch_size: int) -> None:
        for batch in batches(records, batch_size):
            self._call(
                "upsert",
                lambda batch=batch: self.collection.upsert(
                    ids=[record.id for record in batch],
                    documents=[record.document for record in batch],
                    metadatas=[record.metadata for record in batch],
                ),
            )

    def delete(self, ids: list[str], batch_size: int) -> None:
        for batch in batches(ids, batch_size):
            self._call("delete", lambda batch=batch: self.collection.delete(ids=batch))

    def count_namespace(self, namespace: str) -> int:
        return len(self.current(namespace))


def batches(values: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]
