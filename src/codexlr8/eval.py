"""Search quality evaluation — measure query-to-result accuracy."""

from __future__ import annotations

import json
import os

from .search import SearchEngine


def load_queries(path: str) -> list[dict]:
    """Load evaluation queries from a JSON file.

    Schema: [{"query": "...", "expected": "path/to/file.py", "min_rank": 1}]
    min_rank: how high the expected file must rank (1 = top result, 3 = top 3)
    """
    with open(path, "r", encoding="utf-8") as f:
        queries = json.load(f)

    if not isinstance(queries, list):
        raise ValueError("Queries file must be a JSON array")

    for i, q in enumerate(queries):
        for key in ("query", "expected"):
            if key not in q:
                raise ValueError(f"Query item {i}: missing required key '{key}'")
        q.setdefault("min_rank", 1)

    return queries


def run_eval(project_path: str, queries: list[dict],
             limit: int = 10, exclude: list[str] | None = None,
             scope: str | None = None) -> dict:
    """Run search evaluation and return per-query results + aggregate metrics.

    Returns: {
        "project_path": str,
        "num_queries": int,
        "results": [{query, expected, rank, score, status, matched_tokens}],
        "precision_at_1": float,
        "recall_at_5": float,
        "mrr": float,         # Mean Reciprocal Rank
        "passed": int,
        "failed": int,
    }
    """
    engine = SearchEngine(project_path)

    query_results = []
    for q in queries:
        result = _eval_one(engine, q, limit, exclude, scope)
        query_results.append(result)

    metrics = _compute_metrics(query_results)
    metrics["project_path"] = project_path
    metrics["num_queries"] = len(queries)
    metrics["results"] = query_results

    return metrics


def _eval_one(engine: SearchEngine, query_def: dict,
              limit: int, exclude: list[str] | None,
              scope: str | None) -> dict:
    """Run a single query and check if expected file appears in results."""
    search_results = engine.search(
        query_def["query"], limit=limit, exclude=exclude, scope=scope
    )

    expected = query_def["expected"]
    min_rank = query_def.get("min_rank", 1)

    found = False
    rank = None
    score = None
    matched = []

    for i, r in enumerate(search_results):
        if r["path"] == expected:
            found = True
            rank = i + 1
            score = r["score"]
            matched = r.get("matched_tokens", [])
            break

    if found and rank <= min_rank:
        if min_rank == 1:
            status = "pass"
        else:
            status = f"pass (top-{min_rank})"
    elif found:
        status = f"found@{rank} (needed ≤{min_rank})"
    else:
        status = "fail"

    return {
        "query": query_def["query"],
        "expected": expected,
        "min_rank": min_rank,
        "rank": rank,
        "score": score,
        "matched_tokens": matched,
        "status": status,
    }


def _compute_metrics(query_results: list[dict]) -> dict:
    """Compute Precision@1, MRR, Recall@5 from per-query results."""
    n = len(query_results)
    if n == 0:
        return {
            "precision_at_1": 0.0,
            "recall_at_5": 0.0,
            "mrr": 0.0,
            "passed": 0,
            "failed": 0,
        }

    p1_count = 0       # found at rank 1
    recall5_count = 0  # found anywhere in top 5
    reciprocal_sum = 0.0
    passed = 0

    for r in query_results:
        rank = r["rank"]
        if rank == 1:
            p1_count += 1
        if rank is not None and rank <= 5:
            recall5_count += 1
        if rank is not None:
            reciprocal_sum += 1.0 / rank
        if r["status"].startswith("pass"):
            passed += 1

    return {
        "precision_at_1": round(p1_count / n, 4),
        "recall_at_5": round(recall5_count / n, 4),
        "mrr": round(reciprocal_sum / n, 4),
        "passed": passed,
        "failed": n - passed,
    }
