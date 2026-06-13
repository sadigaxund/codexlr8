"""Tests for the file scanner."""

import json

from codexlr8.scanner import (
    scan_project,
    SOURCE_EXTENSIONS,
    IGNORE_DIRS,
    _is_ignored_dir,
)


class TestScanProject:
    def test_discovers_files(self, sample_project):
        results = scan_project(str(sample_project))
        paths = {r["path"] for r in results}
        assert "auth/session.py" in paths
        assert "auth/permissions.py" in paths
        assert "cart/cart.py" in paths
        assert "config.py" in paths
        assert "tests/test_auth.py" in paths

    def test_content_is_raw_text(self, sample_project):
        results = scan_project(str(sample_project))
        session = next(r for r in results if r["path"] == "auth/session.py")
        assert "def login" in session["content"]
        assert "def logout" in session["content"]
        assert isinstance(session["content"], str)

    def test_skips_ignored_dirs(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("x = 1\n")
        (project / "__pycache__").mkdir()
        (project / "__pycache__" / "cached.py").write_text("cached = 1\n")
        (project / ".git").mkdir()
        (project / ".git" / "config.py").write_text("x = 1\n")

        results = scan_project(str(project))
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "__pycache__/cached.py" not in paths
        assert ".git/config.py" not in paths

    def test_skips_non_source_extensions(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("x = 1\n")
        (project / "readme.md").write_text("# hello\n")
        (project / "data.json").write_text('{"key": "val"}')

        results = scan_project(str(project))
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "readme.md" not in paths
        assert "data.json" not in paths

    def test_handles_empty_project(self, tmp_path):
        project = tmp_path / "empty"
        project.mkdir()
        results = scan_project(str(project))
        assert results == []

    def test_handles_unreadable_file(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "bad.py").write_text("\xff\xfe\x00\x00")

        results = scan_project(str(project))
        paths = {r["path"] for r in results}
        assert "main.py" in paths

    def test_returns_relative_paths(self, tmp_path):
        project = tmp_path / "nested" / "proj"
        project.mkdir(parents=True)
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "sub").mkdir()
        (project / "sub" / "util.py").write_text("def bar(): pass\n")

        results = scan_project(str(project))
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

        results = scan_project(str(project))
        paths = {r["path"] for r in results}
        assert "app.js" in paths
        assert "types.ts" in paths
        assert "server.go" in paths
        assert "lib.rs" in paths


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
