"""File scanner — walks project and collects source file content for indexing."""

from __future__ import annotations

import os

SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".hh",
    ".cs", ".swift", ".kt", ".kts", ".scala", ".sh", ".bash",
    ".sql", ".r", ".lua", ".pl", ".pm",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
}


def _is_ignored_dir(dirname: str) -> bool:
    return dirname in IGNORE_DIRS or dirname.startswith(".")


def scan_project(project_path: str) -> list[dict]:
    """Walk a project directory and collect file content for indexing.

    Returns a list of dicts with 'path' (relative) and 'content' (raw text).
    No parsing — just raw content ready for FTS5 tokenization.
    """
    results = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not _is_ignored_dir(d)]
        for filename in sorted(files):
            ext = os.path.splitext(filename)[1]
            if ext not in SOURCE_EXTENSIONS:
                continue
            filepath = os.path.join(root, filename)
            relpath = os.path.relpath(filepath, project_path)
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
