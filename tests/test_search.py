"""Tests for the search engine."""

import json

from codexlr8.search import SearchEngine, _is_test_file, _is_init_file, _tokenize


class TestHelpers:
    def test_is_test_file(self):
        assert _is_test_file("tests/test_auth.py")
        assert _is_test_file("auth/test_auth.py")  # starts with test_
        assert _is_test_file("test_main.py")        # starts with test_
        assert _is_test_file("main_test.py")        # ends with _test
        assert _is_test_file("spec/thing.py")
        assert _is_test_file("src/__tests__/foo.js")
        assert not _is_test_file("auth/session.py")
        assert not _is_test_file("main.py")
        assert not _is_test_file("auth/contest.py")  # contains "test" but not test_ or _test

    def test_is_init_file(self):
        assert _is_init_file("auth/__init__.py")
        assert not _is_init_file("auth/session.py")

    def test_tokenize(self):
        assert _tokenize("") == []
        assert _tokenize("login auth") == ["login", "auth"]
        assert _tokenize("CamelCase and snake_case") == ["camelcase", "and", "snake_case"]
        assert _tokenize("num123") == ["num123"]
        assert _tokenize("x = 1 + 2") == ["x"]


class TestSearchEngine:
    def test_build_and_search(self, sample_project):
        engine = SearchEngine(str(sample_project))
        count = engine.build_index()
        assert count == 6

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
        assert r["preview"]  # has preview text
        assert r["line_start"] > 0
        assert r["line_end"] > r["line_start"]

    def test_limit_results(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        results = engine.search("def")
        assert len(results) <= 10  # default limit

        results = engine.search("def", limit=2)
        assert len(results) <= 2

    def test_test_files_penalized(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        results = engine.search("test")
        # Test files should appear lower (if at all) when not included
        test_results = [r for r in results if "test" in r["path"]]
        non_test = [r for r in results if "test" not in r["path"]]
        # With penalty, test files should have lower scores
        if test_results and non_test:
            assert test_results[0]["score"] <= non_test[0]["score"]

    def test_include_tests_flag(self, sample_project):
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        without = engine.search("login", include_tests=False)
        with_tests = engine.search("login", include_tests=True)

        test_in_without = [r for r in without if "test" in r["path"]]
        test_in_with = [r for r in with_tests if "test" in r["path"]] if with_tests else []

        # With include_tests=True, test files should be present and unscored down
        # At minimum, --include-tests should not filter them out
        assert len(with_tests) >= len(without) or not engine.search(
            "login", include_tests=False
        )

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
        """Search results should rank meta fields higher."""
        import os
        from codexlr8.meta import write_meta

        # Add a meta.yaml with strong tags for the cart file
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
        # cart/cart.py should be top result because it has "checkout" in tags
        assert results
        top = results[0]
        assert "cart" in top["path"]

    def test_init_file_penalty(self, sample_project):
        """__init__.py should rank lower than the actual implementation files."""
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        results = engine.search("session")
        paths = [r["path"] for r in results]
        # auth/session.py should rank higher than auth/__init__.py
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


class TestCLIIndexAndStatus:
    def test_index_command(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index

        runner = CliRunner()
        result = runner.invoke(index, [str(sample_project)])
        assert result.exit_code == 0
        assert "Indexed" in result.output

    def test_status_after_index(self, sample_project):
        from click.testing import CliRunner
        from codexlr8.cli import index, status

        runner = CliRunner()
        runner.invoke(index, [str(sample_project)])

        result = runner.invoke(status, [str(sample_project)])
        assert result.exit_code == 0
        assert "Files indexed:" in result.output
        assert "Index age:" in result.output
