"""Tests for the MCP server integration."""


from codexlr8.search import SearchEngine


class TestMCPServerLogic:
    """Test the search/index logic that the MCP server wraps.

    The MCP server is a thin stdio wrapper around SearchEngine.
    These tests verify the same operations agents perform via tools.
    """

    def test_search_finds_files(self, sample_project):
        """codebase_search tool: query returns ranked results."""
        engine = SearchEngine(str(sample_project))
        engine.build_index()

        results = engine.search("login")
        paths = [r["path"] for r in results]
        assert "auth/session.py" in paths

    def test_index_builds_from_empty(self, tmp_path):
        """codebase_index tool: builds index on a fresh project."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def login(): pass\n")

        engine = SearchEngine(str(project))
        count = engine.build_index()
        assert count == 1

    def test_search_returns_summary_and_tags(self, sample_project):
        """Results include metadata from .meta.yaml."""
        import os
        from codexlr8.meta import write_meta

        cart_meta = os.path.join(str(sample_project), "cart", "cart.py.meta.yaml")
        write_meta(cart_meta, {
            "public_api": ["add_item"],
            "dependencies": [],
            "used_by": [],
            "summary": "Shopping cart",
            "tags": ["cart", "checkout"],
        })

        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("cart", exclude=[])
        assert len(results) > 0
        r = results[0]
        assert "cart" in r["path"]
        assert r.get("summary") or r.get("tags")

    def test_search_no_results(self, sample_project):
        """Non-matching query returns empty list."""
        engine = SearchEngine(str(sample_project))
        engine.build_index()
        results = engine.search("zzz_nonexistent_xyz")
        assert results == []

    def test_empty_path_defaults_to_cwd_match(self, tmp_path):
        """Search respects the project_path passed to SearchEngine."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def login(): pass\n")

        engine = SearchEngine(str(project))
        engine.build_index()
        results = engine.search("login")
        assert len(results) > 0
        assert "main.py" in results[0]["path"]

    def test_search_with_scope(self, tmp_path):
        """Scope parameter restricts search to a path prefix."""
        project = tmp_path / "proj"
        src_dir = project / "src"
        lib_dir = project / "lib"
        src_dir.mkdir(parents=True)
        lib_dir.mkdir(parents=True)

        (src_dir / "auth.py").write_text("def login(): pass\n")
        (lib_dir / "auth.py").write_text("def login(): pass\n")

        engine = SearchEngine(str(project))
        engine.build_index()

        # Without scope: both files match
        results = engine.search("login")
        paths = {r["path"] for r in results}
        assert "src/auth.py" in paths
        assert "lib/auth.py" in paths

        # With scope: only src/ files
        results = engine.search("login", scope="src")
        paths = {r["path"] for r in results}
        assert "src/auth.py" in paths
        assert "lib/auth.py" not in paths
