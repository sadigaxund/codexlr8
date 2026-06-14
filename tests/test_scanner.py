"""Tests for the file scanner."""

import json

from codexlr8.scanner import scan_project

PY_EXTS = [".py"]
ALL_EXTS = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
            ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
            ".kt", ".sql", ".sh", ".lua"]
DEFAULT_IGNORE = [".git", "__pycache__", "node_modules", ".venv", "venv",
                  ".tox", ".mypy_cache", ".pytest_cache", "dist", "build"]


class TestScanProject:
    def test_discovers_files(self, sample_project):
        results = scan_project(str(sample_project), extensions=PY_EXTS, ignore_dirs=DEFAULT_IGNORE)
        paths = {r["path"] for r in results}
        assert "auth/session.py" in paths
        assert "auth/permissions.py" in paths
        assert "cart/cart.py" in paths
        assert "config.py" in paths
        assert "tests/test_auth.py" in paths

    def test_content_is_raw_text(self, sample_project):
        results = scan_project(str(sample_project), extensions=PY_EXTS, ignore_dirs=DEFAULT_IGNORE)
        session = next(r for r in results if r["path"] == "auth/session.py")
        assert "def login" in session["content"]
        assert isinstance(session["content"], str)

    def test_skips_ignored_dirs(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("x = 1\n")
        (project / "__pycache__").mkdir()
        (project / "__pycache__" / "cached.py").write_text("cached = 1\n")
        (project / ".git").mkdir()
        (project / ".git" / "config.py").write_text("x = 1\n")

        results = scan_project(str(project), extensions=PY_EXTS, ignore_dirs=DEFAULT_IGNORE)
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "__pycache__/cached.py" not in paths
        assert ".git/config.py" not in paths

    def test_custom_ignore_dirs(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("x = 1\n")
        (project / "vendor").mkdir()
        (project / "vendor" / "lib.py").write_text("x = 1\n")

        results = scan_project(str(project), extensions=PY_EXTS,
                               ignore_dirs=["vendor"])
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "vendor/lib.py" not in paths

    def test_skips_non_source_extensions(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("x = 1\n")
        (project / "readme.md").write_text("# hello\n")

        results = scan_project(str(project), extensions=PY_EXTS)
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "readme.md" not in paths

    def test_handles_empty_project(self, tmp_path):
        project = tmp_path / "empty"
        project.mkdir()
        results = scan_project(str(project), extensions=PY_EXTS)
        assert results == []

    def test_returns_relative_paths(self, tmp_path):
        project = tmp_path / "nested" / "proj"
        project.mkdir(parents=True)
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "sub").mkdir()
        (project / "sub" / "util.py").write_text("def bar(): pass\n")

        results = scan_project(str(project), extensions=PY_EXTS)
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "sub/util.py" in paths

    def test_includes_js_ts_go_rust(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "app.js").write_text("function login() { }")
        (project / "types.ts").write_text("export interface User { }")
        (project / "server.go").write_text("func main() { }")
        (project / "lib.rs").write_text("pub fn run() { }")

        results = scan_project(str(project), extensions=ALL_EXTS)
        paths = {r["path"] for r in results}
        assert "app.js" in paths
        assert "types.ts" in paths
        assert "server.go" in paths
        assert "lib.rs" in paths

    def test_include_patterns(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "main.py").write_text("x = 1\n")
        (project / "tests").mkdir()
        (project / "tests" / "test_main.py").write_text("assert True\n")

        results = scan_project(str(project), extensions=PY_EXTS, include=["src/*"])
        paths = {r["path"] for r in results}
        assert "src/main.py" in paths
        assert "tests/test_main.py" not in paths

    def test_exclude_patterns(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "main.py").write_text("x = 1\n")
        (project / "src" / "test_helpers.py").write_text("x = 1\n")

        results = scan_project(str(project), extensions=PY_EXTS, exclude=["test_*"])
        paths = {r["path"] for r in results}
        assert "src/main.py" in paths
        assert "src/test_helpers.py" not in paths


class TestCLIScan:
    def test_scan_json_output(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        output_file = tmp_path / "data.json"

        from click.testing import CliRunner
        from codexlr8.cli import scan

        runner = CliRunner()
        result = runner.invoke(scan, [str(project), "--output", str(output_file)])
        assert result.exit_code == 0

        data = json.loads(output_file.read_text())
        assert len(data) == 1
        assert data[0]["path"] == "main.py"
        assert "foo" in data[0]["content"]

    def test_scan_text_output(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")

        from click.testing import CliRunner
        from codexlr8.cli import scan

        runner = CliRunner()
        result = runner.invoke(scan, [str(project)])
        assert result.exit_code == 0
        assert "Scanned 1 files" in result.output
        assert "main.py" in result.output
