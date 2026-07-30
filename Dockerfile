FROM python:3.14.6-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN python -m pip install --upgrade pip==25.2 \
    && python -m pip install uv==0.11.32 \
    && uv sync --frozen --no-dev --no-install-project
ENV CHROMA_REPO_INDEXER_TREE_SITTER_CACHE=/opt/tree-sitter-cache
RUN .venv/bin/python -c "from tree_sitter_language_pack import PackConfig, configure, prefetch; configure(PackConfig(cache_dir='/opt/tree-sitter-cache')); prefetch(['bash','c','cpp','csharp','css','go','html','java','javascript','json','kotlin','lua','php','python','ruby','rust','sql','swift','toml','tsx','typescript','vue','xml','yaml'])"
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

ARG VERSION=dev
LABEL org.opencontainers.image.version="${VERSION}"

ENTRYPOINT ["/app/.venv/bin/python", "-m", "chromadb_repo_indexer.action"]
