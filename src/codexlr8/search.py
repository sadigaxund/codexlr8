"""Search engine — SQLite FTS5 index with custom ranking for code search."""

from __future__ import annotations

import os
import re
import sqlite3

from .meta import META_EXTENSION, read_meta
from .scanner import scan_project, SOURCE_EXTENSIONS, _is_ignored_dir

TEST_DIR_PATTERNS = [
    r"(^|[/\\])tests?([/\\]|$)",
    r"^test_",
    r"_test\.",
    r"^spec[/\\]",
    r"(^|[/\\])__tests__([/\\]|$)",
]

INDEX_DB_NAME = ".codexlr8_index.db"


def _is_test_file(path: str) -> bool:
    for pattern in TEST_DIR_PATTERNS:
        if re.search(pattern, path):
            return True
    return False


def _is_init_file(path: str) -> bool:
    return os.path.basename(path) == "__init__.py"


def _tokenize(text: str) -> list[str]:
    """Split text into search tokens, lowercased."""
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

        Steps: scan project → collect symbols, docstrings, meta → insert into FTS5.

        Returns number of files indexed.
        """
        symbols_data = scan_project(self.project_path)
        conn = self._get_connection()

        conn.execute("DROP TABLE IF EXISTS files")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(
                path,
                symbol_names,
                symbol_kinds,
                docstring,
                summary,
                tags,
                content,
                tokenize='porter unicode61'
            )
        """)

        count = 0
        for entry in symbols_data:
            path = entry["path"]
            symbols = entry.get("symbols", [])

            # Collect symbol names and kinds
            symbol_names = " ".join(s.get("name", "") for s in symbols)
            symbol_kinds = " ".join(s.get("kind", "") for s in symbols)

            # Collect docstrings
            docstring_text = entry.get("docstring", "") or ""
            for s in symbols:
                if s.get("docstring"):
                    docstring_text += " " + s["docstring"]

            # Read .meta.yaml if present
            abspath = os.path.join(self.project_path, path)
            meta = read_meta(abspath + META_EXTENSION) or {}

            summary = meta.get("summary", "")
            tags = " ".join(meta.get("tags", []))

            # Content: everything combined for full-text search
            content = f"{symbol_names} {docstring_text} {summary} {tags}"

            conn.execute(
                "INSERT INTO files (path, symbol_names, symbol_kinds, docstring, summary, tags, content) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, symbol_names, symbol_kinds, docstring_text, summary, tags, content),
            )
            count += 1

        # Store file metadata in a regular table for the ranker
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_meta (
                path TEXT PRIMARY KEY,
                num_symbols INTEGER,
                has_meta BOOLEAN,
                is_test BOOLEAN,
                is_init BOOLEAN,
                public_api TEXT
            )
        """)
        conn.execute("DELETE FROM file_meta")

        for entry in symbols_data:
            path = entry["path"]
            symbols = entry.get("symbols", [])
            abspath = os.path.join(self.project_path, path)
            meta = read_meta(abspath + META_EXTENSION) or {}

            public_api = " ".join(meta.get("public_api", []))

            conn.execute(
                "INSERT OR REPLACE INTO file_meta (path, num_symbols, has_meta, is_test, is_init, public_api) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    path,
                    len(symbols),
                    bool(meta),
                    _is_test_file(path),
                    _is_init_file(path),
                    public_api,
                ),
            )

        conn.commit()
        conn.close()
        return count

    def search(self, query: str, include_tests: bool = False, limit: int = 10) -> list[dict]:
        """Search the codebase and return ranked results.

        Args:
            query: Natural language search query.
            include_tests: If False, penalize test files.
            limit: Maximum number of results.

        Returns:
            List of result dicts with path, line_start, line_end, symbol,
            summary, tags, score, preview.
        """
        if not os.path.exists(self.db_path):
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        conn = self._get_connection()

        # Build FTS5 query — OR all tokens
        fts_query = " OR ".join(tokens)

        results = []

        cursor = conn.execute(
            "SELECT f.path, f.symbol_names, f.docstring, f.summary, f.tags, "
            "       m.is_test, m.is_init, m.public_api, "
            "       rank "
            "FROM files f "
            "JOIN file_meta m ON f.path = m.path "
            "WHERE files MATCH ? "
            "ORDER BY rank "
            "LIMIT ?",
            (fts_query, limit * 5),  # fetch more than limit for re-ranking
        )

        for row in cursor:
            score = self._compute_score(
                tokens, dict(row)
            )
            results.append({
                "path": row["path"],
                "symbol_names": row["symbol_names"] or "",
                "summary": row["summary"] or None,
                "tags": (row["tags"] or "").split(),
                "is_test": bool(row["is_test"]),
                "is_init": bool(row["is_init"]),
                "public_api": row["public_api"] or "",
                "fts_rank": row["rank"],
                "score": score,
            })

        conn.close()

        # Apply custom ranking
        results.sort(key=lambda r: r["score"], reverse=True)

        # Read previews for top results
        final = []
        for r in results[:limit]:
            filepath = os.path.join(self.project_path, r["path"])
            preview, line_range = self._get_preview(filepath, tokens)
            # Find best matching symbol
            symbol_name = self._best_symbol(r, tokens)

            final.append({
                "path": r["path"],
                "line_start": line_range[0],
                "line_end": line_range[1],
                "symbol": symbol_name,
                "summary": r["summary"],
                "tags": r["tags"],
                "score": r["score"],
                "preview": preview,
            })

        return final

    def _compute_score(self, tokens: list[str], row: dict) -> float:
        """Compute a custom relevance score for a search result.

        Ranking weights:
        - exact match in public_api: 1.0
        - match in tags: 0.8
        - match in summary: 0.6
        - match in symbol names: 0.4
        - match in docstring: 0.3

        Penalties:
        - test file: 0.5x
        - __init__.py re-export: 0.6x
        """
        score = 0.0

        public_api = (row.get("public_api") or "").lower()
        symbol_names = (row.get("symbol_names") or "").lower()
        summary = (row.get("summary") or "").lower()
        tags = (row.get("tags") or "").lower()

        for token in tokens:
            if token in _tokenize(public_api):
                score += 1.0
            elif token in tags.split():
                score += 0.8
            elif token in summary:
                score += 0.6
            elif token in _tokenize(symbol_names):
                score += 0.4
            else:
                score += 0.1  # FTS5 match but no token hit in weighted fields

        # Penalties
        if row.get("is_test"):
            score *= 0.5
        if row.get("is_init"):
            score *= 0.6

        return round(score, 4)

    def _best_symbol(self, row: dict, tokens: list[str]) -> str | None:
        """Find the best matching symbol name for the query."""
        symbol_names = (row.get("symbol_names") or "").split()
        if not symbol_names:
            return None

        best = None
        best_score = 0
        for name in symbol_names:
            name_tokens = set(_tokenize(name))
            match_count = sum(1 for t in tokens if t in name_tokens)
            if match_count > best_score:
                best_score = match_count
                best = name

        return best or (symbol_names[0] if symbol_names else None)

    def _get_preview(self, filepath: str, tokens: list[str]) -> tuple[str, tuple[int, int]]:
        """Read the source file and extract a relevant preview snippet.

        Returns (preview_text, (line_start, line_end)).
        """
        if not os.path.exists(filepath):
            return "", (0, 0)

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return "", (0, 0)

        if not lines:
            return "", (0, 0)

        # Find the most relevant line by token matching
        best_line = 0
        best_matches = 0
        for i, line in enumerate(lines):
            line_lower = line.lower()
            matches = sum(1 for t in tokens if t in line_lower)
            if matches > best_matches:
                best_matches = matches
                best_line = i

        # Take a window around the best line
        start = max(0, best_line - 2)
        end = min(len(lines), best_line + 8)
        snippet = "".join(lines[start:end])

        return snippet, (start + 1, end)

    def status(self) -> dict:
        """Return index status and file coverage."""
        result = {
            "project_path": self.project_path,
            "files_indexed": 0,
            "files_with_meta": 0,
            "files_without_meta": 0,
            "total_symbols": 0,
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

        row = conn.execute("SELECT SUM(num_symbols) as total FROM file_meta").fetchone()
        result["total_symbols"] = row["total"] or 0

        mtime = os.path.getmtime(self.db_path)
        from datetime import datetime
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
