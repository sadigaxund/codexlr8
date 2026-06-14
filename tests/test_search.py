"""Tests for the search engine."""

import json

from codexlr8.search import SearchEngine, _is_init_file, _tokenize, _matches_exclude, _group_results


class TestHelpers:
    def test_is_init_file(self):
        assert _is_init_file("auth/__init__.py")
        assert not _is_init_file("auth/session.py")

    def test_tokenize(self):
        assert _tokenize("") == []
        assert _tokenize("login auth") == ["login", "auth"]
        assert _tokenize("CamelCase_123 snake_case") == ["camelcase_123", "snake_case"]
        assert _tokenize("Phase 28") == ["phase", "28"]
        assert _tokenize("x = 1 + 2") == ["1", "2"]  # single letters filtered
        assert _tokenize("go API v2") == ["go", "api", "v2"]  # 2-letter keeps

    def test_matches_exclude(self):
        assert _matches_exclude("tests/test_auth.py", ["tests/*"])
        assert _matches_exclude("test_main.py", ["test_*"])
        assert _matches_exclude("main_test.py", ["*_test.*"])
        assert _matches_exclude("auth/test_helpers.py", ["test_*"])
        assert _matches_exclude("vendor/lib/utils.py", ["vendor/*", "node_modules/*"])
        assert not _matches_exclude("auth/session.py", ["tests/*", "test_*"])
        assert not _matches_exclude("models.py", ["tests/*"])

    def test_group_results_empty(self):
        assert _group_results([]) == {"groups": [], "total_files": 0, "total_results": 0}

    def test_group_results_multi_dir(self):
        results = [
            {"path": "lib/foo/bar.py", "score": 0.9, "summary": "bar module"},
            {"path": "lib/foo/baz.py", "score": 0.7, "summary": "baz module"},
            {"path": "lib/other/qux.py", "score": 0.8, "summary": "qux module"},
            {"path": "src/main.py", "score": 0.5, "summary": "entry point"},
        ]
        grouped = _group_results(results, group_depth=3)
        assert grouped["total_files"] == 4
        assert grouped["total_results"] == 4
        assert len(grouped["groups"]) == 3

        # Sorted by max score: lib/foo/ (0.9), lib/other/ (0.8), src/ (0.5)
        assert grouped["groups"][0]["prefix"] == "lib/foo/"
        assert grouped["groups"][0]["count"] == 2
        assert grouped["groups"][0]["max_score"] == 0.9
        assert not grouped["groups"][0]["has_more"]
        assert grouped["groups"][1]["prefix"] == "lib/other/"
        assert grouped["groups"][2]["prefix"] == "src/"

    def test_group_results_root_files(self):
        results = [
            {"path": "main.py", "score": 0.9},
            {"path": "utils.py", "score": 0.7},
        ]
        grouped = _group_results(results)
        assert len(grouped["groups"]) == 1
        assert grouped["groups"][0]["prefix"] == "."

    def test_group_results_depth_capping(self):
        results = [
            {"path": "a/b/c/d/e/file.py", "score": 0.9},
        ]
        grouped = _group_results(results, group_depth=2)
        assert grouped["groups"][0]["prefix"] == "a/b/"

    def test_group_results_truncates_per_group(self):
        results = [
            {"path": f"lib/many/file_{i}.py", "score": 0.9 - i * 0.01}
            for i in range(10)
        ]
        grouped = _group_results(results)
        g = grouped["groups"][0]
        assert g["count"] == 10
        assert len(g["files"]) == 3
        assert g["has_more"]
        assert g["remaining"] == 7

    def test_group_results_sorts_by_max_score(self):
        results = [
            {"path": "lib/low/file.py", "score": 0.3},
            {"path": "src/high/main.py", "score": 0.9},
            {"path": "lib/low/other.py", "score": 0.1},
        ]
        grouped = _group_results(results)
        assert grouped["groups"][0]["prefix"] == "src/high/"
        assert grouped["groups"][1]["prefix"] == "lib/low/"


class TestSearchEngine:
    def test_build_and_search(self, sample_project):
        engine = SearchEngine(str(sample_project))
        count = engine.build_index()
        assert count == 5  # 6 files - 1 test file excluded by default exclude

    def test_search_finds_by_content(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("login")
        paths = [r["path"] for r in results]
        assert "auth/session.py" in paths
        assert results[0]["score"] > 0

    def test_search_finds_by_docstring(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("authenticate")
        paths = [r["path"] for r in results]
        assert "auth/session.py" in paths

    def test_search_finds_by_class_name(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("shoppingcart")
        paths = [r["path"] for r in results]
        assert "cart/cart.py" in paths

    def test_returns_preview_snippets(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("login")
        assert len(results) > 0
        r = results[0]
        assert r["preview"]
        assert r["line_start"] > 0
        assert r["line_end"] > r["line_start"]

    def test_limit_results(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("def")
        assert len(results) <= 10
        results = engine.search("def", limit=2)
        assert len(results) <= 2

    def test_exclude_patterns(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("login")
        paths = [r["path"] for r in results]
        # With default excludes, test files are excluded
        assert "tests/test_auth.py" not in paths

    def test_exclude_patterns_override(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index(exclude=[])  # index everything, including tests
        results = engine.search("test_login", exclude=[])
        paths = [r["path"] for r in results]
        assert "tests/test_auth.py" in paths

    def test_exclude_custom_pattern(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("login", exclude=["cart/*"])
        paths = [r["path"] for r in results]
        assert "cart/cart.py" not in paths
        # But auth still visible
        assert "auth/session.py" in paths

    def test_no_results_for_empty_query(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("")
        assert results == []

    def test_no_results_if_no_index(self, tmp_path):
        engine = SearchEngine(str(tmp_path))
        results = engine.search("anything")
        assert results == []

    def test_metadata_boost(self, sample_project):
        import os
        from codexlr8.meta import write_meta

        cart_meta_path = os.path.join(str(sample_project), "cart", "cart.py.meta.yaml")
        write_meta(cart_meta_path, {
            "public_api": ["add_item", "checkout"],
            "dependencies": [],
            "used_by": [],
            "summary": "Shopping cart with checkout flow",
            "tags": ["cart", "payment", "checkout"],
        })

        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("checkout")
        assert results
        top = results[0]
        assert "cart" in top["path"]

    def test_init_file_penalty(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("session")
        paths = [r["path"] for r in results]
        if "auth/session.py" in paths and "auth/__init__.py" in paths:
            session_idx = paths.index("auth/session.py")
            init_idx = paths.index("auth/__init__.py")
            assert session_idx < init_idx

    def test_json_output_format(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import search

        engine = SearchEngine(str(sample_project))
        engine.build_index()

        runner = CliRunner()
        result = runner.invoke(
            search, [str(sample_project), "login", "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        if data:
            assert "path" in data[0]
            assert "score" in data[0]

    def test_search_cli_exclude_flag(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import search

        engine = SearchEngine(str(sample_project))
        engine.build_index()

        runner = CliRunner()
        result = runner.invoke(
            search, [str(sample_project), "login", "--exclude", "auth/*"]
        )
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        # auth files should not appear
        auth_lines = [l for l in lines if "auth/" in l]
        assert not auth_lines

    def test_search_cli_grouped(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import search

        engine = SearchEngine(str(sample_project))
        engine.build_index()

        runner = CliRunner()
        result = runner.invoke(
            search, [str(sample_project), "login", "--grouped"]
        )
        assert result.exit_code == 0
        # Should show directory groupings and the scope hint
        assert "Use --scope" in result.output
        assert "(" in result.output  # file count per dir


class TestCLIIndexAndStatus:
    def test_index_command(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index

        runner = CliRunner()
        result = runner.invoke(index, [str(sample_project)])
        assert result.exit_code == 0
        assert "Indexed" in result.output

    def test_index_with_exclude(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index

        runner = CliRunner()
        result = runner.invoke(
            index, [str(sample_project), "--exclude", "tests/*"]
        )
        assert result.exit_code == 0
        assert "Indexed 5 files" in result.output

    def test_index_incremental(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index

        runner = CliRunner()
        runner.invoke(index, [str(sample_project)])
        result = runner.invoke(index, [str(sample_project), "--incremental"])
        assert result.exit_code == 0

        auth_session = sample_project / "auth" / "session.py"
        auth_session.write_text(auth_session.read_text() + "\ndef new_func(): pass\n")
        result = runner.invoke(index, [str(sample_project), "--incremental"])
        assert result.exit_code == 0
        assert "1 files" in result.output

    def test_incremental_handles_new_files(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index

        runner = CliRunner()
        runner.invoke(index, [str(sample_project)])
        (sample_project / "new_module.py").write_text("def hello(): pass\n")
        result = runner.invoke(index, [str(sample_project), "--incremental"])
        assert result.exit_code == 0
        assert "1 files" in result.output

    def test_incremental_handles_deleted_files(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index

        runner = CliRunner()
        runner.invoke(index, [str(sample_project)])
        (sample_project / "config.py").unlink()
        result = runner.invoke(index, [str(sample_project), "--incremental"])
        assert result.exit_code == 0
        assert "1 files" in result.output

    def test_status_after_index(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index, status

        runner = CliRunner()
        runner.invoke(index, [str(sample_project)])
        result = runner.invoke(status, [str(sample_project)])
        assert result.exit_code == 0
        assert "Files indexed:" in result.output
        assert "Index age:" in result.output
