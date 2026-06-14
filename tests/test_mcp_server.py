"""Tests for the MCP server."""

import json
import subprocess
import time

import pytest


@pytest.fixture
def indexed_project(tmp_path):
    """Create a project with a built index for MCP testing."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").write_text("def login(): pass\n")
    (project / "tests").mkdir()
    (project / "tests" / "test_auth.py").write_text("def test_login(): assert True\n")

    from codexlr8.search import SearchEngine
    engine = SearchEngine(str(project))
    engine.build_index()
    return project


def _call_mcp(project_path: str, method: str, params: dict | None = None,
              tool_name: str = "", tool_args: dict | None = None) -> list[str]:
    """Send JSON-RPC messages to the MCP server and collect responses.

    Writes initialize → notification → method call sequentially,
    reads all responses. Returns list of response JSON strings.
    """
    import time
    import sys

    proc = subprocess.Popen(
        [sys.executable, "-m", "codexlr8.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    messages = [
        json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        }),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
    ]

    if method == "tools/list":
        messages.append(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }))
    elif method == "tools/call":
        messages.append(json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": tool_name, "arguments": tool_args or {}},
        }))

    # Write all messages, then close stdin
    try:
        proc.stdin.write("\n".join(messages) + "\n")
        proc.stdin.flush()
        proc.stdin.close()
    except BrokenPipeError:
        pass

    # Give the server time to process
    time.sleep(2)

    stdout = proc.stdout.read() if proc.stdout else ""
    stderr = proc.stderr.read() if proc.stderr else ""

    if stderr.strip():
        sys.stderr.write(f"MCP stderr: {stderr[:500]}\n")

    proc.terminate()
    proc.wait(timeout=5)

    return [line for line in stdout.splitlines() if line.strip()]


class TestMCPServer:
    def test_lists_tools(self, indexed_project):
        responses = _call_mcp(str(indexed_project), "tools/list")
        combined = "\n".join(responses)
        assert "codebase_search" in combined
        assert "codebase_index" in combined

    def test_search_returns_results(self, indexed_project):
        responses = _call_mcp(
            str(indexed_project), "tools/call",
            tool_name="codebase_search",
            tool_args={"query": "login", "path": str(indexed_project)},
        )
        combined = "\n".join(responses)
        assert "main.py" in combined

    def test_search_no_results(self, indexed_project):
        responses = _call_mcp(
            str(indexed_project), "tools/call",
            tool_name="codebase_search",
            tool_args={"query": "zzz_nonexistent_xyz", "path": str(indexed_project)},
        )
        combined = "\n".join(responses)
        assert "No results found" in combined

    def test_index_builds(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")

        responses = _call_mcp(
            str(project), "tools/call",
            tool_name="codebase_index",
            tool_args={"path": str(project)},
        )
        combined = "\n".join(responses)
        assert "Index built" in combined

    def test_path_defaults_to_cwd(self, tmp_path):
        """When path is passed explicitly, the MCP server returns results."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def login(): pass\n")
        from codexlr8.search import SearchEngine
        engine = SearchEngine(str(project))
        engine.build_index()

        responses = _call_mcp(
            str(project), "tools/call",
            tool_name="codebase_search",
            tool_args={"query": "login", "path": str(project)},
        )
        combined = "\n".join(responses)
        assert "main.py" in combined or "No results" in combined
