"""Tests for the eval engine."""

import json

from codexlr8.eval import load_queries, run_eval, _compute_metrics, _check_scope_overlap


class TestLoadQueries:
    def test_loads_valid_file(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login", "expected": "auth/session.py"},
            {"query": "checkout", "expected": "cart/cart.py", "min_rank": 3},
        ]))
        queries = load_queries(str(qfile))
        assert len(queries) == 2
        assert queries[0]["assert"] == "file"
        assert queries[0]["min_rank"] == 1
        assert queries[1]["min_rank"] == 3

    def test_loads_with_scope(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login", "expected": "auth/session.py",
             "scope": {"start": 14, "end": 27}, "assert": "scope"},
        ]))
        queries = load_queries(str(qfile))
        assert queries[0]["assert"] == "scope"
        assert queries[0]["scope"] == {"start": 14, "end": 27}

    def test_scope_requires_scope_field(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login", "expected": "auth/session.py", "assert": "scope"}
        ]))
        try:
            load_queries(str(qfile))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "scope" in str(e).lower()

    def test_invalid_assert_mode(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([
            {"query": "login", "expected": "auth/session.py", "assert": "function"}
        ]))
        try:
            load_queries(str(qfile))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "assert" in str(e).lower()

    def test_missing_required_field(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text(json.dumps([{"query": "login"}]))
        try:
            load_queries(str(qfile))
            assert False
        except ValueError as e:
            assert "expected" in str(e).lower()

    def test_not_a_list(self, tmp_path):
        qfile = tmp_path / "queries.json"
        qfile.write_text('{"query": "login", "expected": "a.py"}')
        try:
            load_queries(str(qfile))
            assert False
        except ValueError as e:
            assert "array" in str(e).lower() or "list" in str(e).lower()


class TestCheckScopeOverlap:
    def test_full_overlap(self):
        # Result range fully covers expected scope → 100% overlap
        status = _check_scope_overlap((10, 30), {"start": 14, "end": 27}, "exact")
        assert status == "pass (scope 100%)"

    def test_partial_overlap(self):
        status = _check_scope_overlap((10, 20), {"start": 14, "end": 27}, "exact")
        assert "46%" in status  # (20-14)/(27-14) = 6/13 ≈ 46%

    def test_no_overlap(self):
        status = _check_scope_overlap((10, 12), {"start": 14, "end": 27}, "scope")
        assert "fail" in status

    def test_mode_scope_any_overlap_passes(self):
        # Even a small overlap passes 'scope' mode
        status = _check_scope_overlap((13, 15), {"start": 14, "end": 27}, "scope")
        assert status == "pass (scope overlap)"

    def test_exact_mode_requires_80_percent(self):
        # 1 line overlap out of 14 expected = 7% → fails exact mode
        status = _check_scope_overlap((13, 15), {"start": 14, "end": 28}, "exact")
        assert "fail" not in status  # Wait — overlap is 14-15 (1 line), expected 28-14=14, 1/14=7%
        # Actually let me think: overlap_start=14, overlap_end=15, overlap_lines=1, expected_lines=14, ratio=0.07 → exact mode: ratio < 0.8
        # The function returns "found (scope 7% < 80%)" → starts with "found" not "pass"
        assert not status.startswith("pass")
        assert "7%" in status


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
        assert m["precision_at_1"] == 0.25
        assert m["recall_at_5"] == 0.75
        assert m["mrr"] == round((1.0 + 1.0 / 3 + 0 + 0.5) / 4, 4)
        assert m["passed"] == 2

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
        r1 = metrics["results"][0]
        assert r1["rank"] == 1
        assert r1["status"].startswith("pass")

        r2 = metrics["results"][1]
        assert r2["rank"] is not None

        r3 = metrics["results"][2]
        assert r3["rank"] is None
        assert r3["status"] == "fail"

        assert metrics["mrr"] >= 0.0

    def test_eval_with_scope_assert(self, sample_project):
        from codexlr8.search import SearchEngine
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        # auth/session.py has def login at line 14 in sample project (roughly)
        # The engine should return a preview around that area
        queries = [
            {"query": "login", "expected": "auth/session.py",
             "scope": {"start": 1, "end": 50}, "assert": "scope"},
        ]
        metrics = run_eval(str(sample_project), queries)
        r = metrics["results"][0]
        assert r["rank"] == 1
        assert "scope" in r["status"] or r["status"].startswith("pass")

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
        assert '"login"' in result.output
