#!/usr/bin/env python3
"""Build a physical, allowlisted workspace for a future legal experiment agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath

MANIFEST_NAME = ".workspace-manifest.json"
WORKSPACE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ALLOWED_EXACT = {
    PurePosixPath("AGENTS.md"),
    PurePosixPath("corpus/manifest/title17.json"),
    PurePosixPath("corpus/manifest/title17-sections.json"),
    PurePosixPath("tools/prepare_title17.py"),
    PurePosixPath("tools/search_sections.py"),
}
ALLOWED_PREFIXES = {
    PurePosixPath(".pi/skills/legal-lookup"),
    PurePosixPath("corpus/sections/title17"),
    PurePosixPath("corpus/source/title17"),
    PurePosixPath("eval/agent-visible/legal"),
}
DENIED_PREFIXES = {
    PurePosixPath(".git"),
    PurePosixPath(".pi-cache"),
    PurePosixPath("eval/evaluator-only"),
    PurePosixPath("results"),
    PurePosixPath("local-data"),
}
DENIED_NAMES = {"credentials.json", "secrets.json"}


class WorkspaceError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def has_prefix(path: PurePosixPath, prefix: PurePosixPath) -> bool:
    return path == prefix or prefix in path.parents


def is_allowed(relative: PurePosixPath) -> bool:
    return relative in ALLOWED_EXACT or any(has_prefix(relative, prefix) for prefix in ALLOWED_PREFIXES)


def is_denied(relative: PurePosixPath) -> bool:
    if any(has_prefix(relative, prefix) for prefix in DENIED_PREFIXES):
        return True
    return any(part.startswith(".env") or part in DENIED_NAMES for part in relative.parts)


def normalize_requested_path(repo_root: Path, requested: str) -> tuple[PurePosixPath, Path]:
    candidate_text = requested.replace("\\", "/")
    pure = PurePosixPath(candidate_text)
    if not candidate_text or pure.is_absolute() or ".." in pure.parts:
        raise WorkspaceError(f"unsafe path: {requested}")
    relative = PurePosixPath(*[part for part in pure.parts if part not in ("", ".")])
    if not relative.parts or is_denied(relative) or not is_allowed(relative):
        raise WorkspaceError(f"path is not allowlisted: {requested}")

    lexical = repo_root.joinpath(*relative.parts)
    if not lexical.exists() and not lexical.is_symlink():
        raise WorkspaceError(f"unknown path: {requested}")

    current = repo_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise WorkspaceError(f"symlinks are forbidden: {requested}")

    resolved = lexical.resolve(strict=True)
    if not is_within(resolved, repo_root):
        raise WorkspaceError(f"path escapes repository: {requested}")
    return relative, resolved


def enumerate_files(repo_root: Path, requested: str) -> list[tuple[PurePosixPath, Path]]:
    relative, source = normalize_requested_path(repo_root, requested)
    if source.is_file():
        return [(relative, source)]
    if not source.is_dir():
        raise WorkspaceError(f"not a regular file or directory: {requested}")

    files: list[tuple[PurePosixPath, Path]] = []
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(dirnames + filenames):
            item = directory_path / name
            child_relative = PurePosixPath(item.relative_to(repo_root).as_posix())
            if item.is_symlink():
                raise WorkspaceError(f"symlinks are forbidden: {child_relative}")
            if is_denied(child_relative) or not is_allowed(child_relative):
                raise WorkspaceError(f"directory contains forbidden path: {child_relative}")
        dirnames.sort()
        for name in sorted(filenames):
            item = directory_path / name
            if not item.is_file():
                raise WorkspaceError(f"not a regular file: {item}")
            child_relative = PurePosixPath(item.relative_to(repo_root).as_posix())
            files.append((child_relative, item.resolve(strict=True)))
    return files


def build_workspace(repo_root: Path, workspace_name: str, includes: list[str]) -> tuple[Path, dict]:
    repo_root = repo_root.resolve(strict=True)
    if not WORKSPACE_NAME.fullmatch(workspace_name):
        raise WorkspaceError("workspace name must contain only lowercase letters, digits, and hyphens")
    if not includes:
        raise WorkspaceError("at least one explicit include is required")

    selected: dict[PurePosixPath, Path] = {}
    for requested in includes:
        for relative, source in enumerate_files(repo_root, requested):
            selected[relative] = source
    if not selected:
        raise WorkspaceError("explicit includes selected no files")

    cache_root = repo_root / ".pi-cache"
    workspace_parent = cache_root / "agent-workspaces"
    destination = workspace_parent / workspace_name
    temporary = workspace_parent / f".{workspace_name}.tmp"
    for path in (cache_root, workspace_parent, destination, temporary):
        if path.is_symlink():
            raise WorkspaceError(f"workspace output path may not be a symlink: {path}")
    if cache_root.exists() and not cache_root.is_dir():
        raise WorkspaceError(f"workspace cache root is not a directory: {cache_root}")
    if workspace_parent.exists() and not workspace_parent.is_dir():
        raise WorkspaceError(f"workspace parent is not a directory: {workspace_parent}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)

    entries = []
    try:
        for relative in sorted(selected, key=lambda value: value.as_posix()):
            source = selected[relative]
            target = temporary.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target, follow_symlinks=False)
            if target.is_symlink():
                raise WorkspaceError(f"staged symlink detected: {relative}")
            entries.append(
                {
                    "path": relative.as_posix(),
                    "byte_size": target.stat().st_size,
                    "sha256": sha256(target),
                }
            )

        manifest = {
            "schema_version": 1,
            "workspace_name": workspace_name,
            "files": entries,
        }
        (temporary / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination, manifest


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="safe name under .pi-cache/agent-workspaces")
    parser.add_argument("--include", action="append", default=[], help="explicit repository-relative path")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        destination, manifest = build_workspace(repo_root, args.workspace, args.include)
        print(f"built {destination} with {len(manifest['files'])} files")
        return 0
    except (OSError, WorkspaceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
