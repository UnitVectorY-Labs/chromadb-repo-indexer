import os
from pathlib import Path


os.environ.setdefault(
    "CHROMA_REPO_INDEXER_TREE_SITTER_CACHE",
    str((Path("/private/tmp") if Path("/private/tmp").is_dir() else Path("/tmp")) / "chromadb-repo-indexer-tree-sitter-cache"),
)
