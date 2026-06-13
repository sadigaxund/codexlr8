# CodeXLR8

A purpose-built codebase search engine for LLM coding agents. Natural language in, ranked file locations out.

```bash
codexlr8 search . "login auth"
# 1. auth/session.py:14-27  [score: 1.60]
#    meta: User authentication — login, logout, session management
#    tags: auth, login, session, security
```

## Why

LLM agents waste tokens with `ls`, `grep`, and speculative file reads when navigating unfamiliar codebases. CodeXLR8 gives them a Google-like search interface: one query, precise results, no noise.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
# 1. Bootstrap metadata sidecars (optional but recommended)
codexlr8 init .

# 2. Build the search index
codexlr8 index .

# 3. Search
codexlr8 search . "payment processing"

# 4. Check freshness
codexlr8 status .
```

## Commands

| Command | What it does |
|---|---|
| `scan <path>` | List source files and line counts |
| `init <path>` | Create empty `.meta.yaml` sidecars for every source file |
| `index <path>` | Build the full-text search index (SQLite FTS5) |
| `search <path> <query>` | Search the codebase, return ranked results |
| `status <path>` | Show index coverage, age, and stats |

## How It Works

CodeXLR8 builds an SQLite FTS5 full-text index from your codebase with a three-layer ranking stack:

| Layer | Source | Weight |
|---|---|---|
| 1 | Code content (function names, variables, comments, docstrings) | Base FTS5 BM25 |
| 2 | `.meta.yaml` `summary` + `tags` fields | 0.6× – 0.8× boost |
| 3 | `.meta.yaml` `public_api` field | 1.0× (strongest) |

Files in `tests/`, `spec/`, `__tests__/` directories and files named `test_*` or `*_test.*` are excluded by default. `__init__.py` re-exports get a 0.6× penalty.

## .meta.yaml Sidecars

Optional YAML files that live next to source files to boost search accuracy. Created automatically by `codexlr8 init`:

```yaml
# auto-generated — tools keep these in sync
public_api: []
dependencies: []
used_by: []
last_modified: "2025-06-14T10:30:00Z"

# curated — you (or an agent) fill these in
summary: "User authentication: login, session management, password reset"
tags: [auth, security, session]
invariants:
  - "db.connect() must be called first"
```

A file without a `.meta.yaml` still gets indexed (Layer 1 only). Adding `summary` and `tags` gives it higher ranking precision.

## Configuration

Optional `.codexlr8.yaml` at the project root:

```yaml
exclude:
  - tests/*
  - test/*
  - spec/*
  - __tests__/*
  - test_*
  - *_test.*
  - vendor/*
  - migrations/*
```

Defaults are sensible for most projects. Override to match your project's conventions. You can also pass `--exclude` on the command line:

```bash
codexlr8 search . "auth" --exclude "tests/*" --exclude "vendor/*"
codexlr8 index . --exclude "tests/*"
```

CLI `--exclude` overrides the config file for that command.

## Incremental Indexing

After code changes, update the index without rebuilding everything:

```bash
codexlr8 index . --incremental
```

Tracks file modification times. Only re-indexes changed, new, or deleted files.

## JSON Output

For programmatic use or agent integration:

```bash
codexlr8 search . "login" --format json
```

## Requirements

- Python 3.10+
- Zero external dependencies beyond stdlib (`sqlite3`, `yaml` from PyYAML, `click` for CLI)
