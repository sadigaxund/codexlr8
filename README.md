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
| 1 | Raw file content | 0.3× per token |
| 2a | File path (filename, directory) | 0.5× – 0.8× |
| 2b | `.meta.yaml` `summary` + `tags` | 0.6× – 0.8× |
| 3 | `.meta.yaml` `public_api` | 1.0× (strongest) |

Search uses OR semantics with token-coverage scoring: more matching tokens = higher score. A ≥50% post-filter eliminates single-token noise for multi-word queries. Path weighting (Layer 2a) provides differentiation even without metadata — a file whose name IS the query token ranks above one that merely mentions it.

### Scoped search and clustering

```bash
# Narrow to a specific directory (like grep -rn "pattern" dir/)
codexlr8 search . "get_visible" --scope lib/mpl_toolkits/

# Cluster results by directory to see where matches concentrate
codexlr8 search . "get_visible" --grouped
# 12 results in 3 directories (8 files) across project:
#   lib/mpl_toolkits/mplot3d/  (5 files)
#     ─ axes3d.py:388  [score: 0.90]
#     ...

# Diagnose your query — see which terms hit, which don't
codexlr8 search . "axes not hiding" --explain
# Query analysis:
#   "axes"    212 matches  — broad term (212/212 results)
#   "not"     77 matches
#   "hiding"  0 matches    — consider dropping or replacing
#   Top score: 1.20 (strong match)

# Combine both — group, then scope to drill down
```

### Search Quality & Fine-Tuning

```bash
# Measure search accuracy against known queries
codexlr8 eval . --queries queries.json
# Precision@1: 67%, MRR: 0.83, Recall@5: 67%

# Typos are auto-corrected (fuzzy fallback on zero results)
codexlr8 search . "funtion"  # → corrects to "function"

# Opt-in embeddings: hybrid BM25 + semantic search
# pip install codexlr8[embeddings]
# set embeddings.enabled: true in .codexlr8.yaml

# Fine-tune a model on YOUR codebase vocabulary
codexlr8 recommend-model .   # picks the right model for your size
codexlr8 train .              # TSDAE training, 5-45min on CPU
codexlr8 eval .               # measure improvement
```

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
