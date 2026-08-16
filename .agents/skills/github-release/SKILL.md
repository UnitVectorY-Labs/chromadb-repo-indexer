---
name: github-release
description: Release a new version of chromadb-repo-indexer to GitHub. Use when the user asks to cut, publish, or tag a new release/version. Bumps the version in pyproject.toml, commits and pushes to main, tags the release, and creates a GitHub release with generated notes.
---

# GitHub Release

Cut a new version of this project and publish it on GitHub.

Versioning is strict: the new version must be **exactly one segment** bumped from the current version, with all lower segments reset to `0`.

## Procedure

Work through these steps in order. Stop and report to the user if any step fails.

### 1. Verify preconditions

All of the following must be true, otherwise stop and tell the user what is wrong:

- Working tree is clean: `git status --porcelain` returns nothing.
- On the `main` branch: `git branch --show-current` prints `main`.
- Up to date with remote: run `git fetch origin`, then confirm local `main` matches `origin/main` (e.g. `git rev-list --left-right --count main...origin/main` prints `0 0`).

### 2. Determine the target version

Read the current version from `pyproject.toml` (the `version` field under `[project]`).

- **If the user's prompt already specifies a version**, use it, but validate it (step 3).
- **If no version was provided**, ask the user which of the three valid next versions to release. Present exactly the three options computed in step 3 (e.g. for current `1.1.1`: `1.1.2` (patch), `1.2.0` (minor), `2.0.0` (major)) and wait for their choice.

### 3. Validate the version is a strict single-segment bump

Given current version `X.Y.Z`, the only valid next versions are:

- patch: `X.Y.(Z+1)`
- minor: `X.(Y+1).0`
- major: `(X+1).0.0`

If the target version is not exactly one of these, stop and tell the user it is not a valid next version, listing the three valid options. Do not proceed.

### 4. Run the test suite

Run the tests the same way CI does:

```
uv sync --frozen --extra test
uv run pytest
```

If any test fails, stop and report the failures. Do not release.

### 5. Bump the version and push to main

1. Update the `version` field under `[project]` in `pyproject.toml` to the new version.
2. Commit and push:

```
git add pyproject.toml
git commit -m "bump: version <NEW_VERSION>"
git push origin main
```

Use the exact commit-message format `bump: version <NEW_VERSION>` (matches existing history, e.g. `bump: version 1.1.1`).

### 6. Tag the release

Create a **lightweight** tag (no `-a`/`-m`, matching existing tags) on the new commit and push it:

```
git tag v<NEW_VERSION>
git push origin v<NEW_VERSION>
```

Only create the full `vX.Y.Z` tag here. Do **not** touch the `vX.Y` and `vX` tags — the `release.yml` workflow moves them automatically when the release is published (see step 8).

### 7. Create the GitHub release

Create a published (not draft) release with GitHub-generated notes:

```
gh release create v<NEW_VERSION> --generate-notes
```

Do not pass `--draft`. This publishes the release immediately.

### 8. Confirm the moving tags updated

The `release.yml` workflow is triggered by the published release and force-moves the `vX.Y` and `vX` tags to the release commit. Wait briefly, then verify they now point at the new commit:

```
git fetch origin --tags
git rev-list -n 1 v<NEW_VERSION>
git rev-list -n 1 v<X.Y>
git rev-list -n 1 v<X>
```

All three should resolve to the same commit SHA. If the workflow has not run yet, note that it is in progress rather than failing the release.

## Done

Report the new version, the release URL (`gh release view v<NEW_VERSION> --web` or the URL printed by `gh release create`), and confirmation that the full, minor, and major tags all point at the release commit.
