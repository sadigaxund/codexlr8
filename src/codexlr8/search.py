"""Search engine — SQLite FTS5 index with custom ranking for code search."""

from __future__ import annotations

import fnmatch
import os
import re
import sqlite3
from datetime import datetime, timezone

from .config import load_config
from .meta import META_EXTENSION, read_meta
from .scanner import scan_project

INDEX_DB_NAME = ".codexlr8_index.db"


def _is_init_file(path: str) -> bool:
    return os.path.basename(path) == "__init__.py"


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    # Capture identifiers (letter-starting) and standalone numbers
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+", text.lower())
    return [t for t in tokens if len(t) > 1 or t.isdigit()]  # skip single letters


def _token_match_info(tokens: list[str], content: str, row) -> tuple[list[str], float]:
    """Return which query tokens matched and the match ratio."""
    if not tokens:
        return [], 0.0
    summary = (row["summary"] or "") if row["summary"] else ""
    tags = (row["tags"] or "") if row["tags"] else ""
    text_lower = (content + " " + summary + " " + tags).lower()
    matched = [t for t in tokens if t in text_lower]
    return matched, len(matched) / len(tokens)


def _token_match_ratio(tokens: list[str], text: str) -> float:
    """What fraction of query tokens appear in the document text?"""
    if not tokens:
        return 0.0
    text_lower = text.lower()
    matched = sum(1 for t in tokens if t in text_lower)
    return matched / len(tokens)


def _matches_exclude(path: str, excludes: list[str]) -> bool:
    """Check if a file path matches any exclude pattern."""
    basename = os.path.basename(path)
    for pattern in excludes:
        if fnmatch.fnmatch(path, pattern):
            return True
        if fnmatch.fnmatch(basename, pattern):
            return True
    return False


def _group_results(results: list[dict], group_depth: int = 3) -> dict:
    """Group flat search results by directory prefix for cluster display.

    Returns a dict with 'groups', 'total_files', 'total_results'.
    Each group has: prefix, count, max_score, files (top 3 per group).
    """
    if not results:
        return {"groups": [], "total_files": 0, "total_results": 0}

    groups: dict[str, list[dict]] = {}
    seen_paths: set[str] = set()

    for r in results:
        path = r["path"]
        dir_parts = path.split(os.sep)[:-1]  # exclude filename
        if not dir_parts:
            prefix = "."
        else:
            prefix = os.sep.join(dir_parts[:group_depth]) + os.sep

        if prefix not in groups:
            groups[prefix] = []
        groups[prefix].append(r)
        seen_paths.add(path)

    group_list = []
    for prefix, files in groups.items():
        # Keep files sorted by score within group
        files.sort(key=lambda f: f["score"], reverse=True)
        group_list.append({
            "prefix": prefix,
            "count": len(files),
            "max_score": files[0]["score"],
            "files": files[:3],  # top 3 per group for display
            "has_more": len(files) > 3,
            "remaining": len(files) - 3 if len(files) > 3 else 0,
        })

    group_list.sort(key=lambda g: g["max_score"], reverse=True)

    return {
        "groups": group_list,
        "total_files": len(seen_paths),
        "total_results": len(results),
    }


class SearchEngine:
    """SQLite FTS5-backed search engine for a codebase."""

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self.db_path = os.path.join(self.project_path, INDEX_DB_NAME)
        self._config = None

    @property
    def config(self) -> dict:
        if self._config is None:
            self._config = load_config(self.project_path)
        return self._config

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def build_index(self, incremental: bool = False,
                    exclude: list[str] | None = None,
                    include: list[str] | None = None) -> int:
        """Build the full search index.

        If incremental=True, only re-index changed/new/removed files.
        include/exclude are glob patterns; fall back to config defaults.

        Returns number of files indexed/mutated.
        """
        if exclude is None:
            exclude = self.config.get("exclude", [])
        if include is None:
            include = self.config.get("include", [])

        root = self.config.get("root", ".")
        scan_root = os.path.join(self.project_path, root)

        files_data = scan_project(
            scan_root,
            extensions=self.config.get("extensions"),
            ignore_dirs=self.config.get("ignore_dirs"),
            include=include,
            exclude=exclude,
        )

        conn = self._get_connection()

        if not incremental:
            conn.execute("DROP TABLE IF EXISTS files")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(
                    path, summary, tags, public_api, content,
                    tokenize='porter unicode61'
                )
            """)
            conn.execute("DROP TABLE IF EXISTS file_meta")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_meta (
                    path TEXT PRIMARY KEY,
                    content_size INTEGER,
                    has_meta BOOLEAN,
                    is_init BOOLEAN,
                    file_mtime REAL,
                    index_built_at TEXT
                )
            """)

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(
                path, summary, tags, public_api, content,
                tokenize='porter unicode61'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_meta (
                path TEXT PRIMARY KEY,
                content_size INTEGER,
                has_meta BOOLEAN,
                is_init BOOLEAN,
                file_mtime REAL,
                index_built_at TEXT
            )
        """)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if incremental:
            count = self._incremental_update(conn, files_data, now)
        else:
            count = self._full_rebuild(conn, files_data, now)

        conn.commit()
        conn.close()
        return count

    def _full_rebuild(self, conn: sqlite3.Connection, files_data: list[dict], now: str) -> int:
        conn.execute("DELETE FROM files")
        conn.execute("DELETE FROM file_meta")
        count = 0
        for entry in files_data:
            self._index_file(conn, entry, now)
            count += 1
        return count

    def _incremental_update(self, conn: sqlite3.Connection, files_data: list[dict], now: str) -> int:
        current_files: dict[str, float] = {}
        file_data_map: dict[str, dict] = {}
        for entry in files_data:
            abspath = os.path.join(self.project_path, entry["path"])
            mtime = os.path.getmtime(abspath)
            current_files[entry["path"]] = mtime
            file_data_map[entry["path"]] = entry

        indexed = conn.execute("SELECT path, file_mtime FROM file_meta").fetchall()
        indexed_map = {row["path"]: row["file_mtime"] for row in indexed}

        count = 0

        removed = set(indexed_map) - set(current_files)
        for path in removed:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            conn.execute("DELETE FROM file_meta WHERE path = ?", (path,))
            count += 1

        for path, mtime in current_files.items():
            if path not in indexed_map or mtime > indexed_map[path]:
                self._index_file(conn, file_data_map[path], now, replace=True)
                count += 1

        return count

    def _index_file(self, conn: sqlite3.Connection, entry: dict, now: str, replace: bool = False):
        path = entry["path"]
        content = entry.get("content", "")
        abspath = os.path.join(self.project_path, path)
        meta = read_meta(abspath + META_EXTENSION) or {}
        mtime = os.path.getmtime(abspath)

        summary = meta.get("summary", "")
        tags = " ".join(meta.get("tags", []))
        public_api = " ".join(meta.get("public_api", []))

        if replace:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))

        conn.execute(
            "INSERT INTO files (path, summary, tags, public_api, content) "
            "VALUES (?, ?, ?, ?, ?)",
            (path, summary, tags, public_api, content),
        )

        line_count = content.count('\n')
        if content and not content.endswith('\n'):
            line_count += 1

        conn.execute(
            "INSERT OR REPLACE INTO file_meta "
            "(path, content_size, has_meta, is_init, file_mtime, index_built_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (path, line_count, bool(meta), _is_init_file(path), mtime, now),
        )

    def search(self, query: str, limit: int = 10,
               exclude: list[str] | None = None,
               scope: str | None = None) -> list[dict]:
        """Search the codebase and return ranked results.

        Uses OR semantics: any token can match. The custom scoring layer
        (path weighting, metadata boosts, match ratio) naturally surfaces
        files that match more tokens. A post-filter requires >=50% of query
        tokens to match for multi-token queries.

        This replaces the previous AND-then-OR fallback, which caused precise
        multi-token queries to return zero results (AND too strict) or too
        many flatly-scored results (OR fallback with no differentiation).
        """
        if not os.path.exists(self.db_path):
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        if exclude is None:
            exclude = self.config.get("exclude", [])

        conn = self._get_connection()

        # Build scope clause for path-prefix filtering
        scope_clause = ""
        scope_params: list[str] = []
        if scope:
            scope_norm = scope.rstrip("/")
            scope_clause = "AND f.path LIKE ?"
            scope_params = [scope_norm + "/%"]

        # Always use OR semantics. Multi-token matches naturally rank higher
        # via _compute_score (match_ratio scales with token coverage).
        or_query = " OR ".join(tokens)
        # Fetch more than needed — scoring will filter to top limit
        fetch_limit = max(limit * 20, 200)
        cursor = conn.execute(
            "SELECT f.path, f.summary, f.tags, f.public_api, f.content, "
            "       m.is_init, rank "
            "FROM files f "
            "JOIN file_meta m ON f.path = m.path "
            "WHERE files MATCH ? "
            + scope_clause + " "
            "ORDER BY rank "
            "LIMIT ?",
            [or_query] + scope_params + [fetch_limit],
        )
        rows = cursor.fetchall()

        # Post-filter: for multi-token queries, require >=50% token match
        min_ratio = 0.5 if len(tokens) >= 2 else 0.0
        results = []
        for row in rows:
            if _matches_exclude(row["path"], exclude):
                continue

            content = row["content"] or ""
            # Compute which tokens matched and the ratio
            matched, ratio = _token_match_info(tokens, content, row)
            if ratio < min_ratio:
                continue

            score = self._compute_score(tokens, dict(row), ratio)
            if row["is_init"]:
                score *= 0.6
            results.append({
                "path": row["path"],
                "summary": row["summary"] or None,
                "tags": (row["tags"] or "").split(),
                "public_api": row["public_api"] or "",
                "score": score,
                "matched_tokens": matched,
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

    def _compute_score(self, tokens: list[str], row: dict, match_ratio: float = 1.0) -> float:
        """Compute relevance score.

        Core ranking: BM25 from FTS5 (via 'rank') provides the base score.
        On top of that, a weighted token-count:
        - Metadata boost: public_api (1.0) > tags (0.8) > summary (0.6)
        - Path boost: exact filename (0.8), filename component (0.7), dir (0.5)
        - Content match: 0.3 (base weight, only if nothing above matched)
        - Match ratio: fraction of query tokens found in the document
        - init.py penalty: 0.6x (applied in search())
        """
        score = 0.0

        path = row.get("path", "")
        public_api = (row.get("public_api") or "").lower()
        summary = (row.get("summary") or "").lower()
        tags = (row.get("tags") or "").lower()

        filename_lower = os.path.splitext(os.path.basename(path))[0].lower()
        filename_parts = set(re.split(r'[_\-.]+', filename_lower))
        dir_path = os.path.dirname(path).lower()
        dir_tokens = set(_tokenize(dir_path.replace(os.sep, " ").replace("_", " ").replace("-", " ")))
        # Also add dir path segments directly (e.g., "mplot3d" from "mplot3d/axes3d.py")
        dir_tokens.update(re.split(r'[_\-.]+', dir_path.replace(os.sep, " ")))

        api_tokens = set(_tokenize(public_api))
        tag_tokens = set(tags.split())
        summary_tokens = set(_tokenize(summary))

        for token in tokens:
            if token in api_tokens:
                score += 1.0
            elif token in tag_tokens:
                score += 0.8
            elif token == filename_lower:
                # Exact filename match: token IS the filename (axes3d.py for "axes3d")
                score += 0.8
            elif token in filename_parts:
                # Token appears as a component in the filename (e.g. "axes3d" in "rotate_axes3d_sgskip.py")
                score += 0.7
            elif token in summary_tokens:
                score += 0.6
            elif token in dir_tokens:
                # Token appears in a directory name (e.g., "mplot3d" in path mplot3d/axes3d.py)
                score += 0.5
            else:
                # Content match via FTS5 — base weight
                score += 0.3

        # Multiply by match ratio: files matching more query terms rank higher
        score *= match_ratio

        return round(score, 4)

    def _get_preview(self, relpath: str, tokens: list[str]) -> tuple[str, tuple[int, int]]:
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
        result = {
            "project_path": self.project_path,
            "files_indexed": 0,
            "files_with_meta": 0,
            "files_without_meta": 0,
            "total_lines": 0,
            "index_age": "No index yet",
            "coverage_pct": 0.0,
            "warning": None,
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

        if result["files_indexed"] > 0:
            result["coverage_pct"] = round(
                (result["files_with_meta"] / result["files_indexed"]) * 100, 1
            )

        if result["files_indexed"] > 0 and result["coverage_pct"] < 10.0:
            result["warning"] = (
                f"Only {result['coverage_pct']}% of files have metadata. "
                "Search quality will be degraded. Run 'codexlr8 init .' to bootstrap."
            )

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
