"""Embedding provider — optional semantic search layer.

Requires optional dependencies: pip install codexlr8[embeddings]
Provides cosine-similarity reranking on top of BM25 results.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

_EMBEDDING_AVAILABLE = False
_SentenceTransformer = None


def _check_deps() -> bool:
    """Lazy-import sentence-transformers. Returns True if available."""
    global _EMBEDDING_AVAILABLE, _SentenceTransformer
    if _EMBEDDING_AVAILABLE:
        return True
    try:
        from sentence_transformers import SentenceTransformer as ST
        _SentenceTransformer = ST
        _EMBEDDING_AVAILABLE = True
        return True
    except ImportError:
        return False


class EmbeddingProvider:
    """Lazy-loading sentence-transformers model for embedding text."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            if not _check_deps():
                raise ImportError(
                    "Embeddings require 'pip install codexlr8[embeddings]' "
                    "(installs sentence-transformers)"
                )
            self._model = _SentenceTransformer(self.model_name)
        return self._model

    @property
    def dims(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Encode texts into normalized embedding vectors."""
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_file(self, path: str, content: str, summary: str = "",
                   tags: list[str] | None = None) -> list[float]:
        """Embed a single file combining path, summary, tags, and content preview."""
        tags_str = " ".join(tags) if tags else ""
        # Combine metadata with first 2000 chars of content for context
        text = f"{path} {summary} {tags_str} {content[:2000]}"
        return self.embed([text])[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two normalized vectors."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # Clamp to [-1, 1] for floating-point safety
    return max(-1.0, min(1.0, dot))


def init_embeddings_table(conn: sqlite3.Connection):
    """Create the embeddings table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            path TEXT PRIMARY KEY,
            vector TEXT,
            dims INTEGER,
            embedded_at TEXT
        )
    """)


def store_embeddings(conn: sqlite3.Connection, path: str,
                     vector: list[float], embedded_at: str):
    """Store or update an embedding vector for a file."""
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (path, vector, dims, embedded_at) "
        "VALUES (?, ?, ?, ?)",
        (path, json.dumps(vector), len(vector), embedded_at),
    )


def load_embeddings(conn: sqlite3.Connection) -> dict[str, list[float]]:
    """Load all stored embeddings from the database."""
    rows = conn.execute("SELECT path, vector FROM embeddings").fetchall()
    return {row["path"]: json.loads(row["vector"]) for row in rows}


def hybrid_rerank(
    bm25_results: list[dict],
    embedded_vectors: dict[str, list[float]],
    query_vector: list[float],
    bm25_weight: float = 0.6,
    embed_weight: float = 0.4,
) -> list[dict]:
    """Merge BM25 scores with cosine similarity and re-rank results.

    bm25_weight / embed_weight control the blending.
    Default 0.6/0.4 favors BM25 (precise token matching) with semantic uplift.
    """
    if not query_vector or not embedded_vectors:
        return bm25_results

    # Normalize BM25 scores to [0, 1] range
    scores = [r["score"] for r in bm25_results]
    if not scores:
        return bm25_results
    max_score = max(scores)
    min_score = min(scores)
    score_range = max_score - min_score if max_score != min_score else 1.0

    for r in bm25_results:
        bm25_norm = (r["score"] - min_score) / score_range

        vec = embedded_vectors.get(r["path"])
        cosine = cosine_similarity(query_vector, vec) if vec else 0.0

        # Weighted blend
        r["score"] = round(bm25_weight * bm25_norm + embed_weight * cosine, 4)
        r["_bm25_norm"] = round(bm25_norm, 4)
        r["_cosine"] = round(cosine, 4)

    bm25_results.sort(key=lambda r: r["score"], reverse=True)
    return bm25_results
