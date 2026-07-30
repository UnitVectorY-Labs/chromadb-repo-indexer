from __future__ import annotations

from dataclasses import dataclass

from binaryornot.helpers import is_binary_string
from charset_normalizer import from_bytes

from .errors import IndexerError
from .models import SourceFile

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
LANGUAGE_EXTENSIONS = {
    ".bash": "bash",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".lua": "lua",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "bash",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass(frozen=True)
class DecodedFile:
    text: str
    strategy: str
    file_type: str
    language: str


def read_text(source: SourceFile) -> DecodedFile | None:
    try:
        data = source.path.read_bytes()
    except OSError as exc:
        raise IndexerError(f"could not read eligible file {source.relative_path}: {exc}") from exc
    if b"\x00" in data or is_binary_string(data):
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        match = from_bytes(data).best()
        if match is None or match.chaos > 0.2 or match.encoding is None:
            return None
        try:
            text = str(match)
        except (UnicodeError, LookupError):
            return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if source.extension in MARKDOWN_EXTENSIONS:
        return DecodedFile(text, "markdown", "markdown", "")
    language = LANGUAGE_EXTENSIONS.get(source.extension, "")
    if language:
        return DecodedFile(text, "code", language, language)
    return DecodedFile(text, "generic", "text", "")
