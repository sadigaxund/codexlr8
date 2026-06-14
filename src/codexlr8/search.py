"""Search engine — SQLite FTS5 index with custom ranking for code search."""

from __future__ import annotations

import fnmatch
import os
import re
import sqlite3
from datetime import datetime, timezone

try:
    from difflib import get_close_matches as _get_close_matches
except ImportError:
    def _get_close_matches(word, possibilities, n=3, cutoff=0.8):
        return []

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


def _explain_query(query: str, tokens: list[str], results: list[dict]) -> dict:
    """Generate query diagnostic breakdown for --explain.

    Returns per-token hit counts, filtered words, top score — gives
    the agent the data it needs to course-correct a search query.
    """
    # Detect words in original query that were filtered by the tokenizer
    raw_lower = query.lower()
    raw_words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+", raw_lower)
    filtered = [w for w in raw_words if w not in tokens and len(w) == 1]

    # Per-token hit counts across all results
    token_hits: dict[str, int] = {}
    for token in tokens:
        count = 0
        for r in results:
            text = (
                (r.get("summary") or "") + " " +
                " ".join(r.get("tags", [])) + " " +
                r.get("path", "") + " " +
                (r.get("preview") or "")
            ).lower()
            if token in text:
                count += 1
        token_hits[token] = count

    top_score = max((r["score"] for r in results), default=0.0)

    return {
        "query": query,
        "tokens": tokens,
        "token_hits": token_hits,
        "filtered": filtered,
        "total_results": len(results),
        "top_score": round(top_score, 2),
    }


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
            count, changed = self._incremental_update(conn, files_data, now)
            embed_files = changed if changed else []
        else:
            count = self._full_rebuild(conn, files_data, now)
            embed_files = files_data

        conn.commit()

        # Embedding support: if embeddings are enabled, embed indexed files
        if embed_files and self.config.get("embeddings", {}).get("enabled"):
            self._embed_files(conn, embed_files, now)
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

    def _incremental_update(self, conn: sqlite3.Connection, files_data: list[dict], now: str) -> tuple[int, list[dict]]:
        """Returns (count, changed_entries) for incremental embedding."""
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
        changed = []

        removed = set(indexed_map) - set(current_files)
        for path in removed:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            conn.execute("DELETE FROM file_meta WHERE path = ?", (path,))
            try:
                conn.execute("DELETE FROM embeddings WHERE path = ?", (path,))
            except sqlite3.OperationalError:
                pass  # embeddings table doesn't exist yet
            count += 1

        for path, mtime in current_files.items():
            if path not in indexed_map or mtime > indexed_map[path]:
                self._index_file(conn, file_data_map[path], now, replace=True)
                changed.append(file_data_map[path])
                count += 1

        return count, changed

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

        # Fuzzy fallback: if FTS5 found nothing and fuzzy is enabled,
        # try edit-distance corrections against the indexed vocabulary.
        if not rows and self.config.get("fuzzy", True):
            fuzzy_tokens = self._fuzzy_correct(conn, tokens)
            if fuzzy_tokens and fuzzy_tokens != tokens:
                fuzzy_query = " OR ".join(fuzzy_tokens)
                cursor = conn.execute(
                    "SELECT f.path, f.summary, f.tags, f.public_api, f.content, "
                    "       m.is_init, rank "
                    "FROM files f "
                    "JOIN file_meta m ON f.path = m.path "
                    "WHERE files MATCH ? "
                    + scope_clause + " "
                    "ORDER BY rank "
                    "LIMIT ?",
                    [fuzzy_query] + scope_params + [fetch_limit],
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

        # Embedding hybrid rerank: blend BM25 scores with cosine similarity
        if results and self.config.get("embeddings", {}).get("enabled"):
            try:
                from .embeddings import EmbeddingProvider, load_embeddings
                emb_cfg = self.config.get("embeddings", {})
                provider = EmbeddingProvider(emb_cfg.get("model", "all-MiniLM-L6-v2"))
                query_vec = provider.embed([query])[0]
                stored = load_embeddings(conn)
                bm25_w = emb_cfg.get("bm25_weight", 0.6)
                embed_w = 1.0 - bm25_w
                self._blend_scores(results, query_vec, stored, bm25_w, embed_w)
            except ImportError:
                pass

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

    def _ensure_vocab(self, conn: sqlite3.Connection):
        """Create FTS5 vocabulary table if it doesn't exist (lazy, on first fuzzy use)."""
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS ft_vocab "
            "USING fts5vocab('files', 'row')"
        )

    def _fuzzy_correct(self, conn: sqlite3.Connection, tokens: list[str]) -> list[str]:
        """Attempt to correct each token against the indexed vocabulary.

        For each token with potential typos, finds close matches using
        difflib against the FTS5 vocabulary (filtered by first-letter prefix).
        Returns corrected token list, or original list if no corrections found.
        """
        self._ensure_vocab(conn)

        corrected = []
        any_corrected = False
        for token in tokens:
            # Numbers and very short tokens: skip fuzzy (unlikely typos)
            if token.isdigit() or len(token) <= 2:
                corrected.append(token)
                continue

            # Get vocabulary terms starting with same first letter
            prefix_start = token[0]
            prefix_end = token[0] + "z"  # range scan: a to az
            cursor = conn.execute(
                "SELECT term FROM ft_vocab WHERE term BETWEEN ? AND ? AND length(term) > 2",
                (prefix_start, prefix_end),
            )
            # Limit to ~5000 terms for performance
            vocab = []
            for i, row in enumerate(cursor):
                vocab.append(row["term"])
                if i > 5000:
                    break

            if not vocab:
                corrected.append(token)
                continue

            matches = _get_close_matches(token, vocab, n=1, cutoff=0.78)
            if matches and matches[0] != token:
                corrected.append(matches[0])
                any_corrected = True
            else:
                corrected.append(token)

        return corrected if any_corrected else tokens

    def _embed_files(self, conn: sqlite3.Connection, files_data: list[dict], now: str):
        """Embed indexed files using the configured embedding model."""
        from .embeddings import (
            EmbeddingProvider, init_embeddings_table, store_embeddings,
        )
        emb_cfg = self.config.get("embeddings", {})
        provider = EmbeddingProvider(emb_cfg.get("model", "all-MiniLM-L6-v2"))

        init_embeddings_table(conn)

        # Collect texts to embed
        texts: list[tuple[str, str]] = []
        for entry in files_data:
            abspath = os.path.join(self.project_path, entry["path"])
            meta = read_meta(abspath + META_EXTENSION) or {}
            summary = meta.get("summary", "")
            tags = meta.get("tags", [])
            text = f"{entry['path']} {summary} {' '.join(tags)} {entry['content'][:2000]}"
            texts.append((entry["path"], text))

        if not texts:
            return

        paths = [t[0] for t in texts]
        contents = [t[1] for t in texts]
        vectors = provider.embed(contents)

        for path, vec in zip(paths, vectors):
            store_embeddings(conn, path, vec, now)

    def _blend_scores(self, results, query_vec, stored_vectors, bm25_w, embed_w):
        """Blend _compute_score output with cosine similarity from embeddings."""
        from .embeddings import cosine_similarity

        scores = [r["score"] for r in results]
        if not scores:
            return
        max_s = max(scores)
        min_s = min(scores)
        s_range = max_s - min_s if max_s != min_s else 1.0

        for r in results:
            bm25_norm = (r["score"] - min_s) / s_range
            vec = stored_vectors.get(r["path"])
            cosine = cosine_similarity(query_vec, vec) if vec else 0.0
            r["score"] = round(bm25_w * bm25_norm + embed_w * cosine, 4)

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
