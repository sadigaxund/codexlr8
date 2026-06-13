"""CodeXLR8 MCP server — exposes codebase search to LLM agents."""

from __future__ import annotations

import json
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .search import SearchEngine

server = Server("codexlr8")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="codebase_search",
            description=(
                "Search the codebase using natural language. "
                "Returns ranked results with file paths, line numbers, "
                "relevance scores, metadata descriptions, and code previews. "
                "Use this BEFORE reading any files to find the right code. "
                "Query tips: use 2-4 keywords related to the task "
                '(e.g. "login auth", "payment stripe charge", "cart checkout").'
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query, 2-4 keywords",
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to the project root to search in",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10)",
                        "default": 10,
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Glob patterns for files to exclude. "
                                       "Uses .codexlr8.yaml defaults if not set.",
                    },
                },
                "required": ["query", "path"],
            },
        ),
        Tool(
            name="codebase_index",
            description=(
                "Build or update the codebase search index. "
                "Run this at the start of a session if the index is missing or stale. "
                "Use --incremental for updates after code changes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the project root",
                    },
                    "incremental": {
                        "type": "boolean",
                        "description": "Only update changed files (default false)",
                        "default": False,
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Glob patterns for files to exclude",
                    },
                },
                "required": ["path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "codebase_search":
        return await _handle_search(arguments)
    elif name == "codebase_index":
        return await _handle_index(arguments)
    raise ValueError(f"Unknown tool: {name}")


async def _handle_search(args: dict) -> list[TextContent]:
    project_path = os.path.abspath(args["path"])
    query = args["query"]
    limit = args.get("limit", 10)
    exclude = args.get("exclude")

    engine = SearchEngine(project_path)
    results = engine.search(query, limit=limit, exclude=exclude)

    if not results:
        return [TextContent(type="text", text="No results found.")]

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r['path']}:{r['line_start']}-{r['line_end']}  "
            f"[score: {r['score']:.2f}]"
        )
        if r.get("summary"):
            lines.append(f"   summary: {r['summary']}")
        if r.get("tags"):
            lines.append(f"   tags: {', '.join(r['tags'])}")
        if r.get("preview"):
            lines.append("   preview: |")
            for pline in r["preview"].strip().splitlines()[:6]:
                lines.append(f"     {pline}")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_index(args: dict) -> list[TextContent]:
    project_path = os.path.abspath(args["path"])
    incremental = args.get("incremental", False)
    exclude = args.get("exclude")

    engine = SearchEngine(project_path)
    count = engine.build_index(incremental=incremental, exclude=exclude)

    msg = f"Index updated: {count} files." if incremental else f"Index built: {count} files."
    return [TextContent(type="text", text=msg)]


def main():
    import asyncio
    asyncio.run(_run())


async def _run():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    main()
