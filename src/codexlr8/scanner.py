"""Code symbol scanner — extracts function/class/variable names and docstrings."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field


SOURCE_EXTENSIONS = {
    ".py": "ast",
    ".js": "regex",
    ".ts": "regex",
    ".jsx": "regex",
    ".tsx": "regex",
    ".go": "regex",
    ".rs": "regex",
    ".rb": "regex",
    ".java": "regex",
    ".c": "regex",
    ".h": "regex",
    ".cpp": "regex",
    ".hpp": "regex",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
}


def _is_ignored_dir(dirname: str) -> bool:
    return dirname in IGNORE_DIRS or dirname.startswith(".")


def scan_project(project_path: str) -> list[dict]:
    """Walk a project directory and extract symbols from all source files."""
    results = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not _is_ignored_dir(d)]
        for filename in sorted(files):
            ext = os.path.splitext(filename)[1]
            if ext not in SOURCE_EXTENSIONS:
                continue
            filepath = os.path.join(root, filename)
            relpath = os.path.relpath(filepath, project_path)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except Exception:
                continue

            symbols, module_docstring = extract_symbols(source, ext)

            entry: dict = {
                "path": relpath,
                "symbols": symbols,
            }
            if module_docstring:
                entry["docstring"] = module_docstring
            results.append(entry)

    return results


def extract_symbols(source: str, ext: str) -> tuple[list[dict], str | None]:
    """Extract top-level symbols and module docstring from source code."""
    if ext == ".py":
        return _extract_python(source)
    return _extract_regex(source)


def _extract_python(source: str) -> tuple[list[dict], str | None]:
    """Extract symbols from Python source using AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], None

    module_docstring = ast.get_docstring(tree)
    symbols = []

    for node in ast.iter_child_nodes(tree):
        info = _handle_python_node(node, source)
        if info:
            symbols.append(info)

    return symbols, module_docstring


def _handle_python_node(node: ast.AST, source: str) -> dict | None:
    """Extract symbol info from an AST node."""
    if isinstance(node, ast.FunctionDef):
        return {
            "name": node.name,
            "kind": "function",
            "line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "docstring": ast.get_docstring(node),
        }
    elif isinstance(node, ast.AsyncFunctionDef):
        return {
            "name": node.name,
            "kind": "async_function",
            "line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "docstring": ast.get_docstring(node),
        }
    elif isinstance(node, ast.ClassDef):
        docstring = ast.get_docstring(node)
        methods = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(child.name)
        return {
            "name": node.name,
            "kind": "class",
            "line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "docstring": docstring,
            "methods": methods,
        }
    elif isinstance(node, ast.Assign):
        names = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
        if names and not _is_assign_skip(node):
            return {
                "name": ", ".join(names),
                "kind": "variable",
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "docstring": None,
            }
    return None


def _is_assign_skip(node: ast.Assign) -> bool:
    """Skip assignments that are imports, type aliases, or dunder names."""
    # Skip __all__, __version__ etc.
    for target in node.targets:
        if isinstance(target, ast.Name) and target.id.startswith("__"):
            return True
    return False


def _extract_regex(source: str) -> tuple[list[dict], str | None]:
    """Extract symbols from non-Python source using regex patterns.
    
    Handles: JavaScript/TypeScript, Go, Rust, Ruby, Java, C/C++
    """
    import re
    symbols = []

    patterns = [
        # JavaScript/TypeScript: function name() {}, class Name {}, const/let/var name =
        (r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)', "function"),
        (r'^\s*(?:export\s+)?class\s+(\w+)', "class"),
        (r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=', "variable"),
        # Go: func Name(..., func (r *Receiver) Name(...
        (r'^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)', "function"),
        (r'^\s*type\s+(\w+)\s+struct', "struct"),
        (r'^\s*type\s+(\w+)\s+interface', "interface"),
        # Rust: fn name(, struct Name, impl Name, pub fn name(
        (r'^\s*(?:pub\s+)?fn\s+(\w+)', "function"),
        (r'^\s*(?:pub\s+)?struct\s+(\w+)', "struct"),
        (r'^\s*(?:pub\s+)?enum\s+(\w+)', "enum"),
        (r'^\s*(?:pub\s+)?trait\s+(\w+)', "trait"),
        (r'^\s*(?:pub\s+)?impl\s+(\w+)', "impl"),
        # Ruby: def name, class Name, module Name
        (r'^\s*def\s+(?:self\.)?(\w+)', "method"),
        (r'^\s*class\s+(\w+)', "class"),
        (r'^\s*module\s+(\w+)', "module"),
        # Java: public class Name, public void method(
        (r'^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:[\w<>[\]]+\s+)?(\w+)\s*\(', "method"),
        (r'^\s*(?:public\s+)?class\s+(\w+)', "class"),
        # C/C++: void name(, int name(, class Name, struct Name
        (r'^\s*(?:[\w:*&<>]+\s+)+\**(\w+)\s*\(', "function"),
        (r'^\s*(?:class|struct)\s+(\w+)', "class"),
    ]

    for line in source.splitlines():
        for pattern, kind in patterns:
            match = re.match(pattern, line)
            if match:
                name = match.group(1)
                symbols.append({
                    "name": name,
                    "kind": kind,
                    "docstring": None,
                })
                break

    return symbols, None
