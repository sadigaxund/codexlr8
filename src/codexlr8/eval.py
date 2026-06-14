"""Search quality evaluation — measure query-to-result accuracy."""

from __future__ import annotations

import json
import os

from .search import SearchEngine


def load_queries(path: str) -> list[dict]:
    """Load evaluation queries from a JSON file.

    Schema:
    [
      {"query": "login auth", "expected": "auth/session.py", "min_rank": 1},
      {"query": "login auth", "expected": "auth/session.py",
       "scope": {"start": 14, "end": 27}, "assert": "scope"}
    ]

    Fields:
      query    — search query string
      expected — file path that should appear in results
      min_rank — required ranking position (default 1)
      scope    — line range the result should cover: {start, end}
      assert   — "file" (default), "scope", or "exact"
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
        q.setdefault("assert", "file")
        if q["assert"] not in ("file", "scope", "exact"):
            raise ValueError(
                f"Query item {i}: assert must be 'file', 'scope', or 'exact'"
            )
        if q["assert"] in ("scope", "exact") and "scope" not in q:
            raise ValueError(
                f"Query item {i}: assert='{q['assert']}' requires a 'scope' field"
            )

    return queries


def run_eval(project_path: str, queries: list[dict],
             limit: int = 10, exclude: list[str] | None = None,
             scope: str | None = None) -> dict:
    """Run search evaluation and return per-query results + aggregate metrics.

    Returns: {
        "project_path": str,
        "num_queries": int,
        "results": [{query, expected, rank, score, status, mode}],
        "precision_at_1": float,
        "recall_at_5": float,
        "mrr": float,
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
              search_scope: str | None) -> dict:
    """Run a single query and check if expected file/scope appears in results."""
    search_results = engine.search(
        query_def["query"], limit=limit, exclude=exclude, scope=search_scope
    )

    expected_file = query_def["expected"]
    min_rank = query_def.get("min_rank", 1)
    assert_mode = query_def.get("assert", "file")
    expected_scope = query_def.get("scope")

    found = False
    rank = None
    score = None
    matched = []
    result_lines = (0, 0)

    for i, r in enumerate(search_results):
        if r["path"] == expected_file:
            found = True
            rank = i + 1
            score = r["score"]
            matched = r.get("matched_tokens", [])
            result_lines = (r.get("line_start", 0), r.get("line_end", 0))
            break

    # File-level check
    if not found:
        return {
            "query": query_def["query"],
            "expected": expected_file,
            "assert": assert_mode,
            "scope": expected_scope,
            "min_rank": min_rank,
            "rank": None,
            "score": None,
            "matched_tokens": [],
            "line_start": 0,
            "line_end": 0,
            "status": "fail",
        }

    if found and rank > min_rank:
        return {
            "query": query_def["query"],
            "expected": expected_file,
            "assert": assert_mode,
            "scope": expected_scope,
            "min_rank": min_rank,
            "rank": rank,
            "score": score,
            "matched_tokens": matched,
            "line_start": result_lines[0],
            "line_end": result_lines[1],
            "status": f"found@{rank} (needed ≤{min_rank})",
        }

    # File found at correct rank. Check scope if required.
    scope_status = None
    if assert_mode in ("scope", "exact") and expected_scope:
        scope_status = _check_scope_overlap(result_lines, expected_scope, assert_mode)

    if scope_status:
        return {
            "query": query_def["query"],
            "expected": expected_file,
            "assert": assert_mode,
            "scope": expected_scope,
            "min_rank": min_rank,
            "rank": rank,
            "score": score,
            "matched_tokens": matched,
            "line_start": result_lines[0],
            "line_end": result_lines[1],
            "status": scope_status,
        }

    # File-level pass
    suffix = f" (top-{min_rank})" if min_rank > 1 else ""
    return {
        "query": query_def["query"],
        "expected": expected_file,
        "assert": assert_mode,
        "scope": expected_scope,
        "min_rank": min_rank,
        "rank": rank,
        "score": score,
        "matched_tokens": matched,
        "line_start": result_lines[0],
        "line_end": result_lines[1],
        "status": f"pass{suffix}",
    }


def _check_scope_overlap(
    result_lines: tuple[int, int],
    expected_scope: dict,
    mode: str,
) -> str | None:
    """Check if result line range overlaps expected scope. Returns status or None."""
    r_start, r_end = result_lines
    e_start = expected_scope.get("start", 0)
    e_end = expected_scope.get("end", 0)

    if r_start == 0 or e_start == 0:
        return "fail (no line data)"

    overlap_start = max(r_start, e_start)
    overlap_end = min(r_end, e_end)

    if overlap_end <= overlap_start:
        return "fail (no scope overlap)"

    overlap_lines = overlap_end - overlap_start
    expected_lines = e_end - e_start
    ratio = overlap_lines / expected_lines if expected_lines > 0 else 0

    if mode == "exact":
        if ratio >= 0.8:
            return f"pass (scope {ratio:.0%})"
        return f"found (scope {ratio:.0%} < 80%)"
    elif mode == "scope":
        return "pass (scope overlap)"

    return None


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

    p1_count = 0
    recall5_count = 0
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
