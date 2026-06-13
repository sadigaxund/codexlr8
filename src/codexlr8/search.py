"""Search engine — SQLite FTS5 index with custom ranking for code search."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime

from .meta import META_EXTENSION, read_meta
from .scanner import scan_project

INDEX_DB_NAME = ".codexlr8_index.db"


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file.

    Matches:
    - files in a 'tests/', 'test/', 'spec/', or '__tests__/' directory
    - files whose name starts with 'test_' or ends with '_test'
    """
    # Directory-based patterns
    for pattern in [
        r"(^|[/\\])tests?([/\\]|$)",
        r"(^|[/\\])spec([/\\]|$)",
        r"(^|[/\\])__tests__([/\\]|$)",
    ]:
        if re.search(pattern, path):
            return True

    # Filename-based patterns
    basename = os.path.basename(path)
    name, ext = os.path.splitext(basename)
    if name.startswith("test_") or name.endswith("_test"):
        return True

    return False


def _is_init_file(path: str) -> bool:
    return os.path.basename(path) == "__init__.py"


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens for matching."""
    if not text:
        return []
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())


class SearchEngine:
    """SQLite FTS5-backed search engine for a codebase."""

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self.db_path = os.path.join(self.project_path, INDEX_DB_NAME)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def build_index(self) -> int:
        """Build the full search index from scratch.

        Scans project files, reads content + .meta.yaml fields,
        inserts everything into FTS5. Returns number of files indexed.
        """
        files_data = scan_project(self.project_path)
        conn = self._get_connection()

        conn.execute("DROP TABLE IF EXISTS files")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(
                path,
                summary,
                tags,
                public_api,
                content,
                tokenize='porter unicode61'
            )
        """)

        conn.execute("DROP TABLE IF EXISTS file_meta")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_meta (
                path TEXT PRIMARY KEY,
                content_size INTEGER,
                has_meta BOOLEAN,
                is_test BOOLEAN,
                is_init BOOLEAN
            )
        """)

        count = 0
        for entry in files_data:
            path = entry["path"]
            content = entry.get("content", "")

            abspath = os.path.join(self.project_path, path)
            meta = read_meta(abspath + META_EXTENSION) or {}

            summary = meta.get("summary", "")
            tags = " ".join(meta.get("tags", []))
            public_api = " ".join(meta.get("public_api", []))

            conn.execute(
                "INSERT INTO files (path, summary, tags, public_api, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, summary, tags, public_api, content),
            )

            line_count = content.count('\n')
            if content and not content.endswith('\n'):
                line_count += 1

            conn.execute(
                "INSERT OR REPLACE INTO file_meta (path, content_size, has_meta, is_test, is_init) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, line_count, bool(meta), _is_test_file(path), _is_init_file(path)),
            )
            count += 1

        conn.commit()
        conn.close()
        return count

    def search(self, query: str, include_tests: bool = False, limit: int = 10) -> list[dict]:
        """Search the codebase and return ranked results.

        Returns list of result dicts with path, line_start, line_end,
        summary, tags, score, and preview snippet.
        """
        if not os.path.exists(self.db_path):
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        conn = self._get_connection()

        fts_query = " OR ".join(tokens)

        # Fetch more than limit for re-ranking
        cursor = conn.execute(
            "SELECT f.path, f.summary, f.tags, f.public_api, "
            "       m.is_test, m.is_init, rank "
            "FROM files f "
            "JOIN file_meta m ON f.path = m.path "
            "WHERE files MATCH ? "
            "ORDER BY rank "
            "LIMIT ?",
            (fts_query, limit * 5),
        )

        results = []
        for row in cursor:
            score = self._compute_score(tokens, dict(row))
            if not include_tests:
                score *= 0.5 if row["is_test"] else 1.0
            if row["is_init"]:
                score *= 0.6
            results.append({
                "path": row["path"],
                "summary": row["summary"] or None,
                "tags": (row["tags"] or "").split(),
                "public_api": row["public_api"] or "",
                "score": score,
            })

        conn.close()

        results.sort(key=lambda r: r["score"], reverse=True)

        final = []
        for r in results[:limit]:
            preview, line_range = self._get_preview(r["path"], tokens)
            final.append({
                "path": r["path"],
                "line_start": line_range[0],
                "line_end": line_range[1],
                "summary": r["summary"],
                "tags": r["tags"],
                "score": r["score"],
                "preview": preview,
            })

        return final

    def _compute_score(self, tokens: list[str], row: dict) -> float:
        """Compute custom relevance score.

        Ranking weights:
        - match in public_api:  1.0  (strongest signal)
        - match in tags:        0.8
        - match in summary:     0.6
        - match in content:     base BM25 from FTS5
        - test penalty:         0.5x (applied in search())
        - __init__.py penalty:  0.6x
        """
        score = 0.0

        public_api = (row.get("public_api") or "").lower()
        summary = (row.get("summary") or "").lower()
        tags = (row.get("tags") or "").lower()

        api_tokens = set(_tokenize(public_api))
        tag_tokens = set(tags.split())
        summary_tokens = set(_tokenize(summary))

        for token in tokens:
            if token in api_tokens:
                score += 1.0
            elif token in tag_tokens:
                score += 0.8
            elif token in summary_tokens:
                score += 0.6
            else:
                # Content match via FTS5 — give a base boost for each token
                score += 0.2

        return round(score, 4)

    def _get_preview(self, relpath: str, tokens: list[str]) -> tuple[str, tuple[int, int]]:
        """Read the source file and extract a relevant preview snippet.

        Finds the line with the most token matches and returns a window
        around it as the preview.

        Returns (preview_text, (line_start, line_end)).
        """
        filepath = os.path.join(self.project_path, relpath)
        if not os.path.exists(filepath):
            return "", (0, 0)

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return "", (0, 0)

        if not lines:
            return "", (0, 0)

        best_line = 0
        best_matches = 0
        for i, line in enumerate(lines):
            line_lower = line.lower()
            matches = sum(1 for t in tokens if t in line_lower)
            if matches > best_matches:
                best_matches = matches
                best_line = i

        start = max(0, best_line - 2)
        end = min(len(lines), best_line + 8)
        snippet = "".join(lines[start:end])

        return snippet, (start + 1, end)

    def status(self) -> dict:
        """Return index state and file coverage."""
        result = {
            "project_path": self.project_path,
            "files_indexed": 0,
            "files_with_meta": 0,
            "files_without_meta": 0,
            "total_lines": 0,
            "index_age": "No index yet",
        }

        if not os.path.exists(self.db_path):
            return result

        conn = self._get_connection()

        row = conn.execute("SELECT COUNT(*) as cnt FROM files").fetchone()
        result["files_indexed"] = row["cnt"] if row else 0

        row = conn.execute("SELECT COUNT(*) as cnt FROM file_meta WHERE has_meta = 1").fetchone()
        result["files_with_meta"] = row["cnt"] if row else 0

        result["files_without_meta"] = result["files_indexed"] - result["files_with_meta"]

        row = conn.execute("SELECT SUM(content_size) as total FROM file_meta").fetchone()
        result["total_lines"] = row["total"] or 0

        mtime = os.path.getmtime(self.db_path)
        mtime_dt = datetime.fromtimestamp(mtime)
        age = datetime.now() - mtime_dt
        if age.seconds < 60:
            result["index_age"] = f"{age.seconds}s ago"
        elif age.seconds < 3600:
            result["index_age"] = f"{age.seconds // 60}m ago"
        else:
            result["index_age"] = f"{age.seconds // 3600}h ago"

        conn.close()
        return result
