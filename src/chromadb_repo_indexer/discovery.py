from __future__ import annotations

import os
from pathlib import Path

import pathspec

from .errors import ConfigurationError
from .models import DiscoveryStats, Settings, SourceFile


def discover_files(settings: Settings) -> tuple[list[SourceFile], DiscoveryStats]:
    root = settings.root.resolve()
    includes = pathspec.PathSpec.from_lines("gitwildmatch", settings.include_paths)
    excludes = pathspec.PathSpec.from_lines("gitwildmatch", settings.exclude_paths)
    stats = DiscoveryStats()
    files: list[SourceFile] = []

    def onerror(error: OSError) -> None:
        raise error

    try:
        walker = os.walk(root, topdown=True, followlinks=False, onerror=onerror)
        for directory, dirnames, filenames in walker:
            current = Path(directory)
            kept_dirs: list[str] = []
            for name in dirnames:
                candidate = current / name
                relative = candidate.relative_to(root).as_posix()
                if candidate.is_symlink() or relative == ".git" or relative.startswith(".git/"):
                    stats.files_other_skipped += 1
                else:
                    kept_dirs.append(name)
            dirnames[:] = sorted(kept_dirs)
            for name in sorted(filenames):
                candidate = current / name
                if candidate.is_symlink() or not candidate.is_file():
                    stats.files_other_skipped += 1
                    continue
                relative = candidate.relative_to(root).as_posix()
                stats.files_scanned += 1
                if relative == ".git" or relative.startswith(".git/"):
                    continue
                extension = candidate.suffix.lower()
                eligible = (
                    includes.match_file(relative)
                    and not excludes.match_file(relative)
                    and (not settings.include_extensions or extension in settings.include_extensions)
                    and extension not in settings.exclude_extensions
                )
                if eligible:
                    files.append(SourceFile(candidate, relative, extension))
                    stats.files_eligible += 1
    except OSError as exc:
        raise ConfigurationError(f"failed while traversing {root}: {exc}") from exc
    files.sort(key=lambda item: item.relative_path)
    return files, stats

