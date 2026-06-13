"""Tests for the code scanner."""

import json
import os

from codexlr8.scanner import (
    scan_project,
    extract_symbols,
    SOURCE_EXTENSIONS,
    IGNORE_DIRS,
    _is_ignored_dir,
)


class TestScanProject:
    def test_discovers_python_files(self, sample_project):
        results = scan_project(str(sample_project))
        paths = {r["path"] for r in results}
        assert "auth/session.py" in paths
        assert "auth/permissions.py" in paths
        assert "cart/cart.py" in paths
        assert "config.py" in paths
        assert "tests/test_auth.py" in paths

    def test_skips_ignored_dirs(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
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
        (project / "image.png").write_text("fake png")

        results = scan_project(str(project))
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        assert "readme.md" not in paths
        assert "data.json" not in paths
        assert "image.png" not in paths

    def test_handles_empty_project(self, tmp_path):
        project = tmp_path / "empty"
        project.mkdir()
        results = scan_project(str(project))
        assert results == []

    def test_handles_unreadable_file(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "bad.py").write_text("\xff\xfe\x00\x00")  # invalid utf-8

        results = scan_project(str(project))
        paths = {r["path"] for r in results}
        assert "main.py" in paths
        # bad.py should be skipped gracefully

    def test_symbol_structure_python(self, sample_project):
        results = scan_project(str(sample_project))

        session = next(r for r in results if r["path"] == "auth/session.py")
        symbols = {s["name"]: s for s in session["symbols"]}
        assert "login" in symbols
        assert symbols["login"]["kind"] == "function"
        assert symbols["login"]["line"] > 0
        assert symbols["login"]["docstring"] is not None

    def test_module_docstring_captured(self, sample_project):
        results = scan_project(str(sample_project))
        session = next(r for r in results if r["path"] == "auth/session.py")
        assert "session" in (session.get("docstring") or "").lower()

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


class TestExtractPython:
    def test_functions(self):
        source = '''
def login(username, password):
    """Auth login."""
    pass

def logout():
    """Destroy session."""
    pass
'''
        symbols, docstring = extract_symbols(source, ".py")
        names = {s["name"] for s in symbols}
        assert "login" in names
        assert "logout" in names
        login = next(s for s in symbols if s["name"] == "login")
        assert login["docstring"] == "Auth login."
        assert login["kind"] == "function"

    def test_async_functions(self):
        source = '''
async def fetch_data(url):
    """Fetch data asynchronously."""
    pass
'''
        symbols, _ = extract_symbols(source, ".py")
        assert len(symbols) == 1
        assert symbols[0]["kind"] == "async_function"
        assert symbols[0]["name"] == "fetch_data"

    def test_classes(self):
        source = '''
class ShoppingCart:
    """A cart."""

    def add_item(self, name, price):
        """Add item."""
        pass

    def checkout(self):
        """Checkout."""
        pass
'''
        symbols, _ = extract_symbols(source, ".py")
        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "ShoppingCart"
        assert classes[0]["docstring"] == "A cart."
        assert set(classes[0]["methods"]) == {"add_item", "checkout"}

    def test_variables(self):
        source = '''
DEBUG = True
API_URL = "https://api.example.com"
'''
        symbols, _ = extract_symbols(source, ".py")
        vars_ = [s for s in symbols if s["kind"] == "variable"]
        assert len(vars_) == 2
        names = {s["name"] for s in vars_}
        assert "DEBUG" in names
        assert "API_URL" in names

    def test_skips_dunder_variables(self):
        source = '''
__version__ = "1.0"
__all__ = ["foo"]
PUBLIC = 42
'''
        symbols, _ = extract_symbols(source, ".py")
        names = {s["name"] for s in symbols}
        assert "PUBLIC" in names
        assert "__version__" not in names
        assert "__all__" not in names

    def test_module_docstring(self):
        source = '"""Module doc."""\n\nx = 1\n'
        symbols, docstring = extract_symbols(source, ".py")
        assert docstring == "Module doc."

    def test_empty_source(self):
        symbols, docstring = extract_symbols("", ".py")
        assert symbols == []
        assert docstring is None

    def test_syntax_error_graceful(self):
        source = "def broken(\n"  # incomplete
        symbols, docstring = extract_symbols(source, ".py")
        assert symbols == []
        assert docstring is None


class TestExtractRegex:
    def test_javascript_functions(self):
        source = '''
function login(username, password) { }
export async function fetchData(url) { }
class ShoppingCart { }
const API_URL = "https://...";
'''
        symbols, _ = extract_symbols(source, ".js")
        names = {s["name"] for s in symbols}
        assert "login" in names
        assert "fetchData" in names

    def test_typescript(self):
        source = '''
export class AuthService { }
export const MAX_RETRIES = 3;
'''
        symbols, _ = extract_symbols(source, ".ts")
        names = {s["name"] for s in symbols}
        assert "AuthService" in names
        assert "MAX_RETRIES" in names

    def test_go(self):
        source = '''
func Login(username string) error { }
type Session struct { }
type Auth interface { }
'''
        symbols, _ = extract_symbols(source, ".go")
        names = {s["name"] for s in symbols}
        assert "Login" in names
        assert "Session" in names
        assert "Auth" in names

    def test_rust(self):
        source = '''
pub fn login() -> Result<()> { }
pub struct Session { }
pub enum AuthResult { }
pub trait Authenticator { }
'''
        symbols, _ = extract_symbols(source, ".rs")
        names = {s["name"] for s in symbols}
        assert "login" in names
        assert "Session" in names
        assert "AuthResult" in names
        assert "Authenticator" in names

    def test_cpp(self):
        source = '''
class ShoppingCart { };
int calculateTotal(int items) { };
'''
        symbols, _ = extract_symbols(source, ".cpp")
        names = {s["name"] for s in symbols}
        assert "ShoppingCart" in names
        assert "calculateTotal" in names

    def test_unknown_extension_returns_empty(self):
        symbols, _ = extract_symbols("code goes here", ".unknown")
        assert symbols == []


class TestCLIScan:
    def test_scan_json_output(self, tmp_path):
        """Test that --output writes valid JSON."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        output_file = tmp_path / "symbols.json"

        from click.testing import CliRunner
        from codexlr8.cli import scan

        runner = CliRunner()
        result = runner.invoke(scan, [str(project), "--output", str(output_file)])
        assert result.exit_code == 0

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert len(data) == 1
        assert data[0]["path"] == "main.py"
        assert len(data[0]["symbols"]) == 1
        assert data[0]["symbols"][0]["name"] == "foo"

    def test_scan_text_output(self, tmp_path):
        """Test text output format."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")

        from click.testing import CliRunner
        from codexlr8.cli import scan

        runner = CliRunner()
        result = runner.invoke(scan, [str(project)])
        assert result.exit_code == 0
        assert "Scanned 1 files" in result.output
