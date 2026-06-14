"""File scanner — walks project and collects source file content for indexing."""

from __future__ import annotations

import fnmatch
import os

DEFAULT_EXTENSIONS = [
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".hh",
    ".cs", ".swift", ".kt", ".kts", ".scala", ".sh", ".bash",
    ".sql", ".r", ".lua", ".pl", ".pm",
]

DEFAULT_IGNORE_DIRS = [
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
]


def _is_ignored_dir(dirname: str, ignore_dirs: list[str]) -> bool:
    for pattern in ignore_dirs:
        if fnmatch.fnmatch(dirname, pattern):
            return True
    if dirname.startswith("."):
        return True
    return False


def _matches_glob(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    basename = os.path.basename(path)
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def scan_project(project_path: str,
                 extensions: list[str] | None = None,
                 ignore_dirs: list[str] | None = None,
                 include: list[str] | None = None,
                 exclude: list[str] | None = None) -> list[dict]:
    """Walk a project directory and collect file content for indexing.

    extensions: file extensions to scan (default: common source code extensions).
    ignore_dirs: directory names to skip (default: .git, node_modules, etc.).
    include: only scan files matching these glob patterns (if set).
    exclude: skip files matching these glob patterns.

    Returns a list of dicts with 'path' (relative) and 'content' (raw text).
    """
    results = []
    _extensions = extensions if extensions is not None else DEFAULT_EXTENSIONS
    _ignore = ignore_dirs if ignore_dirs is not None else DEFAULT_IGNORE_DIRS

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not _is_ignored_dir(d, _ignore)]
        for filename in sorted(files):
            ext = os.path.splitext(filename)[1]
            if ext not in _extensions:
                continue
            filepath = os.path.join(root, filename)
            relpath = os.path.relpath(filepath, project_path)

            if include and not _matches_glob(relpath, include):
                continue
            if exclude and _matches_glob(relpath, exclude):
                continue

            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue
            results.append({
                "path": relpath,
                "content": content,
            })
    return results
