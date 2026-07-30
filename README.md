# chromadb-repo-indexer

`chromadb-repo-indexer` is a Docker GitHub Action and Python CLI that keeps the text content of a repository directory synchronized with a remote ChromaDB collection. It discovers files without consulting Git, creates deterministic Markdown- and code-aware chunks, and safely converges one organization/repository/branch namespace without touching any other namespace in the collection.

The indexer sends documents and metadata without explicitly supplying embeddings. The collection's configured embedding function must be able to embed documents.

## GitHub Action

```yaml
name: Index repository in ChromaDB

on:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: chromadb-index-${{ github.repository }}-${{ github.ref_name }}
  cancel-in-progress: false

jobs:
  index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: UnitVectorY-Labs/chromadb-repo-indexer@v1
        with:
          server-url: ${{ secrets.CHROMA_SERVER_URL }}
          bearer-token: ${{ secrets.CHROMA_BEARER_TOKEN }}
          collection-name: repository-content
          exclude-paths: |
            dist/**
            coverage/**
```

The checkout step is required. Action identity is always derived from `GITHUB_REPOSITORY`, `GITHUB_REF_NAME`, and `GITHUB_SHA`; there are no identity override inputs. Consumers must serialize runs for the same collection/repository/branch namespace with a GitHub Actions concurrency group.

The Action runs the public multi-architecture image at `ghcr.io/unitvectory-labs/chromadb-repo-indexer:v1`. Consumers still reference `UnitVectorY-Labs/chromadb-repo-indexer@v1`; `action.yml` connects that Action release to the corresponding GHCR major-version image.

### Inputs

| Input | Required | Default | Description |
|---|---:|---|---|
| `server-url` | yes | — | Full `http://` or `https://` Chroma origin |
| `collection-name` | yes | — | Target collection |
| `bearer-token` | no | empty | Static token sent as `Authorization: Bearer …` |
| `tenant` | no | `default_tenant` | Existing Chroma tenant |
| `database` | no | `default_database` | Existing Chroma database |
| `config-file` | no | empty | Workspace-relative YAML config path |
| `include-paths` | no | config or `**` | Newline-separated Git wildmatch patterns |
| `exclude-paths` | no | config or empty | Newline-separated Git wildmatch patterns |
| `include-extensions` | no | config or empty | Newline-separated allowlist |
| `exclude-extensions` | no | config or empty | Newline-separated denylist |
| `chunk-size` | no | `512` | Maximum tokens, including context prefix |
| `chunk-overlap` | no | `64` | Overlap when subdividing an oversized unit |
| `batch-size` | no | `100` | Requested mutation batch size |
| `dry-run` | no | `false` | Calculate the remote diff without mutations |

### Outputs

The Action exposes `namespace_id`, `files_scanned`, `files_eligible`, `files_indexed`, `files_binary_skipped`, `files_other_skipped`, `chunks_desired`, `chunks_added_or_updated`, `chunks_unchanged`, `chunks_deleted`, `dry_run`, `duration_ms`, and a `summary` JSON object.

## Python CLI

Python 3.13 and 3.14 are supported.

```bash
python -m pip install .

chromadb-repo-indexer index \
  --root . \
  --organization UnitVectorY-Labs \
  --repository example \
  --branch main \
  --server-url https://chroma.example.com \
  --collection-name repository-content
```

Manual identity is mandatory and is never inferred from Git, YAML, or environment variables. Optional flags are:

```text
--commit-sha SHA
--bearer-token TOKEN
--tenant TENANT
--database DATABASE
--config PATH
--include-path PATTERN                 (repeatable)
--exclude-path PATTERN                 (repeatable)
--include-extension EXT                (repeatable)
--exclude-extension EXT                (repeatable)
--chunk-size N
--chunk-overlap N
--batch-size N
--retry-attempts N
--dry-run
--output-manifest PATH
--include-document-text-in-manifest
```

The last flag is deliberately separate because repository content may be sensitive. Manifests omit document text by default and contain deterministic IDs, metadata, hashes, and line boundaries.

The CLI recognizes these non-identity environment variables:

```text
CHROMA_REPO_INDEXER_SERVER_URL
CHROMA_REPO_INDEXER_COLLECTION_NAME
CHROMA_REPO_INDEXER_BEARER_TOKEN
CHROMA_REPO_INDEXER_TENANT
CHROMA_REPO_INDEXER_DATABASE
CHROMA_REPO_INDEXER_CONFIG_FILE
```

## Configuration

Precedence is flags/Action inputs, environment variables, explicitly selected YAML, then built-in defaults. No config file is auto-discovered. Unknown keys and versions fail validation, and bearer tokens are forbidden in YAML.

```yaml
version: 1

chroma:
  server_url: https://chroma.example.com
  collection_name: repository-content
  tenant: default_tenant
  database: default_database

files:
  include_paths:
    - "**"
  exclude_paths:
    - "vendor/**"
    - "dist/**"
  include_extensions: []
  exclude_extensions:
    - ".lock"

chunking:
  chunk_size: 512
  chunk_overlap: 64

sync:
  batch_size: 100
  retry_attempts: 3
```

Traversal includes hidden files and does not apply `.gitignore`. `.git/**` is always excluded. Symlinks are not followed. Include/exclude paths use `pathspec` Git-wildmatch semantics; path matching is case-sensitive, while extension matching is case-insensitive. Exclusions win.

## Chunking

All decoded text has UTF-8 BOMs removed and line endings normalized to `\n`. Binary detection uses `binaryornot` plus a NUL check; UTF-8 is preferred and high-confidence `charset-normalizer` decoding is the fallback.

- Markdown (`.md`, `.markdown`, `.mdown`, `.mkd`) splits by heading structure and repeats the complete heading path in each context prefix. Natural blocks are retained when they fit.
- Recognized source files use the pinned Tree-sitter language pack to prefer top-level declarations. A missing grammar or parse error falls back to generic splitting.
- Other text recursively splits at blank lines, lines, whitespace, and finally bounded character spans.

The current recognized code extensions cover Bash, C/C++, C#, CSS, Go, HTML, Java, JavaScript/JSX, JSON, Kotlin, Lua, PHP, Python, Ruby, Rust, SQL, Swift, TOML, TypeScript/TSX, Vue, XML, and YAML. The Docker image prefetches their pinned grammars during build. For local execution, the language pack may populate its user cache the first time a grammar is used; `CHROMA_REPO_INDEXER_TREE_SITTER_CACHE` can select a different cache directory.

Every Chroma document begins with a deterministic context prefix:

```text
Source: UnitVectorY-Labs/example@main:docs/setup.md
Type: markdown
Section: Setup > Authentication

<exact normalized source excerpt>
```

The maximum token count includes this prefix. Independent structural units do not receive manufactured overlap; overlap is used only when an oversized unit needs subdivision. `chunking_version` is currently `1`.

## Metadata and identity

The synchronization namespace is exactly `organization + repository + branch`. Its ID is a SHA-256 hash of canonical JSON containing those three case-preserving strings. Record IDs include the namespace hash, path hash, normalized full-file hash, and zero-padded chunk index, so editing a file makes all of its previous chunks stale.

Every record has scalar metadata fields:

| Field | Meaning |
|---|---|
| `schema_version` | Metadata contract version (`1`) |
| `namespace_id` | Organization/repository/branch hash |
| `organization`, `repository`, `branch` | Source identity |
| `path`, `file_name`, `file_extension` | Normalized POSIX source path |
| `file_type`, `language` | Classified content type and language |
| `document_id` | Stable parent ID for the file path |
| `file_hash`, `chunk_hash` | SHA-256 normalized content hashes |
| `chunk_index`, `chunk_count` | Ordered position and total |
| `chunking_strategy`, `chunking_version` | `markdown`, `code`, or `generic`; contract version |
| `start_line`, `end_line` | One-based inclusive source boundaries |
| `section`, `symbol` | Markdown heading path or code declaration |
| `indexed_commit_sha` | Action SHA, explicit local SHA, or empty |

## Synchronization safety

Each run completes local discovery and chunk creation before connecting. It pages through only its `namespace_id`, calculates an explicit ID diff, upserts missing/current records in bounded batches, and only then deletes an explicit stale-ID list. A failed upsert prevents the entire deletion phase. An intentionally empty existing directory is valid and deletes the namespace only after successful discovery and remote-state retrieval.

The requested batch size is reduced when Chroma advertises a smaller maximum. Transient connection errors, HTTP 429 responses, and HTTP 5xx responses are retried with bounded exponential backoff. Authentication and deterministic validation failures are not retried. HTTPS always verifies certificates.

## Troubleshooting

- **Collection cannot embed documents:** configure an embedding function on the target Chroma collection. The indexer intentionally does not accept or generate embeddings.
- **Unauthorized/forbidden:** verify the bearer token, tenant, and database. Tokens and authorization headers are redacted from errors and never written to manifests or outputs.
- **No matching files:** remember that path patterns are Git-wildmatch and case-sensitive. Use `--dry-run --output-manifest manifest.json` to inspect the desired state.
- **Code uses generic chunks:** malformed source, an unavailable grammar, or a parser error intentionally falls back rather than failing the run.
- **Concurrent runs disagree:** only one run may synchronize a given collection/organization/repository/branch namespace at once; configure the workflow concurrency group shown above.

## Development

```bash
uv sync --extra test
uv run pytest --cov=chromadb_repo_indexer
docker build -t chromadb-repo-indexer .
```

Dependencies are exact-pinned in `pyproject.toml` and fully resolved in `uv.lock`. CI tests Python 3.13 and 3.14 and builds the Docker Action.

## Releases

Publishing a GitHub Release with a semantic tag such as `v1.0.0` runs `.github/workflows/release-docker-ghcr.yml`. The workflow builds native `linux/amd64` and `linux/arm64` images, creates the multi-architecture manifest, publishes `v1.0.0`, `v1.0`, and `v1` tags to GHCR, and attaches build-provenance attestations.

The movable repository tag `v1` and GHCR image tag `v1` are the public major-version channel. The GHCR package must be public so GitHub can pull the container before executing the Action. PyPI publication, if added later, is independent and only affects installation of the local CLI.
