# CodeXLR8 — Architecture & Design Specification

## Problem Statement

LLM coding agents burn tokens on navigation. Given a task like "fix the login bug," an agent with no prior knowledge of the codebase resorts to `ls`, broad `grep`, and speculative file reads. This is noisy (grep matches comments, tests, vendored code), expensive (reading irrelevant files burns API tokens), and error-prone (hidden dependencies and invariants go undiscovered).

Existing tools (Sourcegraph, Zoekt, ctags, Livegrep, GitHub Code Search) are designed for **human browsing** — web UIs, regex-based queries, no ranking tuned for agent needs, no metadata enrichment.

## Design Goals

1. **Agent-first**: The primary consumer is an LLM agent, not a human browsing a web UI.
2. **Zero setup works**: The engine produces useful results on any codebase without metadata.
3. **Incrementally adoptable**: Optional `.meta.yaml` sidecars add precision over time.
4. **Language agnostic**: No AST parsing. Pure tokenization of file content.
5. **No external dependencies**: SQLite FTS5 + PyYAML + Click. No servers, no API keys, no Docker.
6. **Fast**: <100ms results for codebases up to 10,000 files.

## Architecture

```
                    ┌──────────────────────┐
                    │   Agent (MCP Client)  │
                    │  codebase_search()    │
                    └──────────┬───────────┘
                               │ stdio / HTTP
                    ┌──────────▼───────────┐
                    │     MCP Server        │
                    │  codebase_search      │
                    │  codebase_index       │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  SearchEngine (core)  │
                    │  build_index()        │
                    │  search()             │
                    └──────┬───────┬───────┘
                           │       │
              ┌────────────▼─┐  ┌──▼────────────┐
              │   Scanner     │  │  Config        │
              │  walk + read  │  │  .codexlr8.yaml│
              │  (no parsing) │  │  defaults      │
              └───────┬───────┘  └────────────────┘
                      │
              ┌───────▼────────┐
              │  .meta.yaml     │  ← optional curated layer
              │  summary, tags, │
              │  public_api     │
              └────────────────┘
```

### Module Map

```
src/codexlr8/
  scanner.py     — Walk project, read raw file content
  search.py      — SQLite FTS5 index, AND-semantics query, ranking
  meta.py        — .meta.yaml read/write/generate/validate
  config.py      — .codexlr8.yaml loading with defaults
  cli.py         — Click CLI (scan, init, index, search, status, setup)
  mcp_server.py  — MCP stdio server wrapping SearchEngine
```

## The Three-Layer Value Stack

| Layer | Source | What | Weight |
|---|---|---|---|
| 1 | File content | Function names, variable names, comments, docstrings | BM25 base |
| 2 | `.meta.yaml` curated fields | summary + tags | 0.6–0.8× boost |
| 3 | `.meta.yaml` public_api | Explicit symbol list | 1.0× boost |

**Layer 1** works immediately, zero setup, on any codebase. **Layers 2–3** add precision through optional human/agent curation.

## Search Engine Design

### Index

SQLite FTS5 with `porter unicode61` tokenizer. Virtual table columns:

| Column | Content |
|---|---|
| `path` | Relative file path |
| `summary` | From `.meta.yaml` |
| `tags` | Space-joined from `.meta.yaml` |
| `public_api` | Space-joined from `.meta.yaml` |
| `content` | Raw file content |

A companion `file_meta` table stores `content_size`, `has_meta`, `is_init`, `file_mtime`, and `index_built_at` for incremental updates and status reporting.

### Query Semantics

**AND by default — like Google.** All query tokens must appear in the indexed document. This eliminates the noise of OR semantics where a 10-word query matches every file containing "the" or "is".

Fallback: if AND returns nothing (rare for multi-token queries), the engine retries with OR and applies a post-filter requiring ≥50% of query tokens to match the document.

### Tokenization

Matches identifiers (`[a-zA-Z_][a-zA-Z0-9_]*`) and standalone numbers (`\d+`). Single-letter tokens are discarded. `"Phase 28"` → `["phase", "28"]`. Number support was added in v0.1 after discovering that OR semantics + no-number matching made queries like "Phase 28" only match on "phase".

### Scoring

```
score = (∑ token_boost) × match_ratio

token_boost:
  token ∈ public_api     → 1.0
  token ∈ tags           → 0.8
  token ∈ summary        → 0.6
  token ∈ content (BM25) → 0.3

match_ratio: matched_tokens / total_query_tokens

Penalties:
  __init__.py            → score × 0.6
```

### Incremental Indexing

Tracks `file_mtime` per indexed file. `--incremental` mode compares timestamps and only re-indexes changed, new, or deleted files. Removed files are dropped from the index.

### Exclusion

Files are excluded at **index time** (never enter the index) and **query time** (filtered from results). Patterns are globs (`tests/*`, `test_*`, `*_test.*`) matched against both full path and basename.

## Metadata Sidecar Format (`.meta.yaml`)

```yaml
public_api: [login, logout, reset_password]   # auto: regenerated by tools
dependencies: [models.user, utils.hashing]     # auto: from imports
used_by: [main, api.auth_routes]               # auto: reverse dependency graph
last_modified: "2026-06-14T10:30:00Z"          # auto: timestamp

summary: "User auth: login, session, password reset"  # curated
tags: [auth, security, session]                        # curated
invariants:                                            # curated
  - "db.connect() must be called first"
  - "Passwords are bcrypt hashes, never plaintext"
examples: null                                         # curated
```

### Curation Model

Metadata is **agent-maintained**, not developer-maintained. The agent skill instructs agents to:
- Bootstrap missing `.meta.yaml` files at session start
- Update `summary`, `tags`, `public_api` when modifying a file
- Backfill only files they touch — no mass curation campaigns

## Configuration (`.codexlr8.yaml`)

```yaml
root: "."
include: []                     # scope: only scan these directories
exclude:                        # filter: skip these
  - tests/*
  - test_*
  - *_test.*
extensions:                     # file types to index
  - .py
  - .js
  - .ts
ignore_dirs:                    # skip directories entirely
  - .git
  - __pycache__
  - node_modules
```

All fields have defaults. A missing config file uses `DEFAULT_EXTENSIONS` and `DEFAULT_IGNORE_DIRS` with no include restrictions. CLI `--exclude` flags override config for that command.

## MCP Integration

Single tool: `codebase_search(query, path?, limit?, exclude?)`. Path defaults to config `root` or current directory. The MCP server runs as a subprocess and communicates over stdio per the Model Context Protocol.

Agent calls `codebase_search(query="payment refund")` → gets ranked results with paths, line ranges, scores, summaries, tags, and preview snippets. No file read tool — agents use their existing read tool.

A companion `codebase_index(path?, incremental?, exclude?)` tool lets agents build or update the index from within a session.

## Design Decisions

### Why no AST parsing?

AST parsing requires per-language dependencies (tree-sitter grammars, Python AST, etc.) and still can't handle comments/docstrings well. Pure tokenization of file content across 20+ languages with FTS5 indexing is simpler, faster, and language-agnostic. The metadata layer provides precision where parsing would help.

### Why SQLite FTS5?

Zero dependencies (stdlib `sqlite3`). Free features: stemming, prefix queries, phrase matching, BM25 ranking. No server process. Portable across platforms. Scales fine for codebases up to millions of tokens.

### Why AND semantics?

OR semantics (the initial v0 approach) required "short queries" advice to work around noise. AND semantics means more terms = more precision, matching user expectations from Google. The post-filter threshold (≥50% match for 4+ token queries) handles the "all or nothing" problem gracefully.

### Why sidecars and not inline metadata?

- Indexer reads YAML directly — no source parsing needed
- Auto fields can be regenerated without touching source code
- Works for any file type (code, SQL, Markdown, configs)
- Reading a 15-line `.meta.yaml` costs ~50 tokens

## Future Work

- **Semantic search**: Optional embedding-based hybrid ranking for concept-level queries
- **Cross-file dependency tracking**: Follow `dependencies` / `used_by` chains in search results
- **Language-specific extractors**: Optional tree-sitter plug-ins for deeper analysis
- **Watch mode**: `codexlr8 watch` — auto-reindex on file changes
- **Multi-repo monorepo support**: Per-subproject configs

## Project Constraints

- No AST or tree-sitter parsing in core — tokenization only
- No external services (DB servers, APIs, cloud dependencies)
- Python 3.10+ only (no async/await except in MCP server)
- FTS5 index stored as `.codexlr8_index.db` in project root
- 100% local operation — no telemetry, no network access
