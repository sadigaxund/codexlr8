"""Tests for the eval engine."""

import json

from codexlr8.eval import load_queries, run_eval, _compute_metrics


class TestLoadQueries:
    def test_loads_valid_file(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login", "expected": "auth/session.py"},
            {"query": "checkout", "expected": "cart/cart.py", "min_rank": 3},
        ]))
        queries = load_queries(str(qfile))
        assert len(queries) == 2
        assert queries[0]["query"] == "login"
        assert queries[0]["expected"] == "auth/session.py"
        assert queries[0]["min_rank"] == 1  # default
        assert queries[1]["min_rank"] == 3

    def test_missing_required_field(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login"}  # missing expected
        ]))
        try:
            load_queries(str(qfile))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "missing required key" in str(e).lower() or "expected" in str(e).lower()

    def test_not_a_list(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text('{"query": "login", "expected": "a.py"}')
        try:
            load_queries(str(qfile))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "array" in str(e).lower() or "list" in str(e).lower()


class TestComputeMetrics:
    def test_all_pass_at_rank_1(self):
        results = [
            {"query": "a", "expected": "a.py", "min_rank": 1, "rank": 1, "score": 0.9, "status": "pass"},
            {"query": "b", "expected": "b.py", "min_rank": 1, "rank": 1, "score": 0.8, "status": "pass"},
        ]
        m = _compute_metrics(results)
        assert m["precision_at_1"] == 1.0
        assert m["recall_at_5"] == 1.0
        assert m["mrr"] == 1.0
        assert m["passed"] == 2
        assert m["failed"] == 0

    def test_all_fail(self):
        results = [
            {"query": "a", "expected": "a.py", "min_rank": 1, "rank": None, "score": None, "status": "fail"},
            {"query": "b", "expected": "b.py", "min_rank": 1, "rank": None, "score": None, "status": "fail"},
        ]
        m = _compute_metrics(results)
        assert m["precision_at_1"] == 0.0
        assert m["recall_at_5"] == 0.0
        assert m["mrr"] == 0.0
        assert m["passed"] == 0

    def test_mixed_results(self):
        results = [
            {"query": "a", "expected": "a.py", "min_rank": 1, "rank": 1, "score": 0.9, "status": "pass"},
            {"query": "b", "expected": "b.py", "min_rank": 1, "rank": 3, "score": 0.5, "status": "found@3 (needed ≤1)"},
            {"query": "c", "expected": "c.py", "min_rank": 1, "rank": None, "score": None, "status": "fail"},
            {"query": "d", "expected": "d.py", "min_rank": 5, "rank": 2, "score": 0.7, "status": "pass (top-5)"},
        ]
        m = _compute_metrics(results)
        # p1: only 'a' at rank 1 = 1/4 = 0.25. But 'd' also passed (top-5) so mrr includes it
        assert m["precision_at_1"] == 0.25
        assert m["recall_at_5"] == 0.75  # a, b, d found in top 5; c not found
        # mrr: 1/1 + 1/3 + 0 + 1/2 = 1 + 0.333 + 0 + 0.5 = 1.833 / 4
        assert m["mrr"] == round((1.0 + 1.0/3 + 0 + 0.5) / 4, 4)
        assert m["passed"] == 2  # a and d

    def test_empty_results(self):
        m = _compute_metrics([])
        assert m["precision_at_1"] == 0.0
        assert m["passed"] == 0


class TestRunEval:
    def test_evaluates_against_sample_project(self, sample_project):
        from codexlr8.search import SearchEngine
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        queries = [
            {"query": "login", "expected": "auth/session.py", "min_rank": 1},
            {"query": "checkout", "expected": "cart/cart.py", "min_rank": 3},
            {"query": "zzz_nonexistent", "expected": "nowhere.py", "min_rank": 1},
        ]
        metrics = run_eval(str(sample_project), queries)

        assert metrics["num_queries"] == 3
        assert len(metrics["results"]) == 3

        # Login should find auth/session.py first
        r1 = metrics["results"][0]
        assert r1["rank"] == 1
        assert "pass" in r1["status"].lower()

        # Checkout should find cart/cart.py somewhere
        r2 = metrics["results"][1]
        assert r2["rank"] is not None

        # Nonexistent query fails
        r3 = metrics["results"][2]
        assert r3["rank"] is None
        assert r3["status"] == "fail"

        # Metrics should exist
        assert metrics["mrr"] >= 0.0

    def test_eval_cli_command(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import eval_cmd
        from codexlr8.search import SearchEngine

        engine = SearchEngine(str(sample_project))
        engine.build_index()

        qfile = sample_project / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login", "expected": "auth/session.py"},
            {"query": "zzz_nonexistent", "expected": "nowhere.py"},
        ]))

        runner = CliRunner()
        result = runner.invoke(
            eval_cmd,
            [str(sample_project), "--queries", str(qfile)]
        )
        assert result.exit_code == 0
        assert "Precision@1" in result.output
        assert "MRR" in result.output
        assert "Recall@5" in result.output
        assert '"login"' in result.output
