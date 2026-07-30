class IndexerError(Exception):
    """Base error that is safe to present to users."""


class ConfigurationError(IndexerError):
    """Configuration is absent or invalid."""


class ChromaError(IndexerError):
    """The configured Chroma service could not complete an operation."""

