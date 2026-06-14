# CodeXLR8

[![PyPI version](https://img.shields.io/pypi/v/codexlr8)](https://pypi.org/project/codexlr8/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![CI](https://github.com/sadigaxund/codexlr8/actions/workflows/test.yml/badge.svg)](https://github.com/sadigaxund/codexlr8/actions)

A codebase search engine for LLM coding agents. **One query, precise results, no noise.**

## Setup

```bash
pip install codexlr8
codexlr8 setup
```

`setup` auto-detects MCP clients (Claude Code, Cursor) and injects the server config, then walks you through project configuration. After setup, build the search index:

```bash
codexlr8 index .
```

Your agents now have `codebase_search` and `codebase_index` tools. Search from the CLI yourself:

```bash
codexlr8 search . "login auth"
# 1. auth/session.py:14-27  [score: 1.60]
#    meta: User authentication — login, logout, session management
#    tags: auth, login, session, security
```

## How It Works

CodeXLR8 indexes your codebase into an SQLite FTS5 database alongside optional `.meta.yaml` sidecar files that boost ranking precision:

| Layer | Source | Boost |
|---|---|---|
| 1 | Raw file content (function names, variables, comments, docstrings) | FTS5 BM25 base |
| 2 | `.meta.yaml` `summary` + `tags` | 0.6× – 0.8× |
| 3 | `.meta.yaml` `public_api` | 1.0× (strongest) |

Search uses AND semantics (like Google): all query tokens must match. If no results, falls back to OR with a ≥50% token threshold.

## .meta.yaml Sidecars

Optional YAML files next to source files, created by `codexlr8 init`:

```yaml
public_api: [login, logout, reset_password]
summary: "User auth: login, session, password reset"
tags: [auth, security, session]
invariants:
  - "db.connect() must be called first"
```

Files without `.meta.yaml` still get indexed — metadata just produces higher ranking scores.

## Configuration

Optional `.codexlr8.yaml` at the project root:

```yaml
root: "."
include: []                     # scope: only scan these
exclude:                        # skip these
  - tests/*
  - test_*
extensions:                     # file types to index
  - .py
  - .js
ignore_dirs:                    # skip entirely
  - .git
  - __pycache__
```

All fields have defaults. Use `codexlr8 setup` to create one interactively, or edit by hand.

## Agent Integration

Works with **Claude Code, Cursor, Windsurf, Continue.dev** and any MCP-compatible client.

`codexlr8 setup` auto-detects installed clients and offers to inject the MCP server config. For manual setup, add this to your client's config:

```json
{
  "mcpServers": {
    "codexlr8": {
      "command": "uvx",
      "args": ["codexlr8", "mcp-server"]
    }
  }
}
```

Tools available to agents:

| Tool | Description |
|---|---|
| `codebase_search(query, path?, limit?, exclude?)` | Search the codebase, return ranked results |
| `codebase_index(path?, incremental?, exclude?)` | Build or update the search index |

The included agent skill ([SKILL.md](SKILL.md)) teaches agents to search before reading files, maintain `.meta.yaml` sidecars, and keep the index fresh.

## Commands

```
codexlr8 setup            Interactive project + MCP config
codexlr8 scan <path>      List source files and line counts
codexlr8 init <path>      Bootstrap .meta.yaml sidecars
codexlr8 index <path>     Build the search index
codexlr8 search <path> <q> Search the codebase
codexlr8 status <path>    Show index coverage and age
codexlr8 install-skill    Install agent skill for Claude Code
codexlr8 mcp-config       Print MCP client config JSON
```

## Contributing

See [AGENTS.md](AGENTS.md) for principles and development guidelines.

## License

Apache 2.0. See [LICENSE](LICENSE).
