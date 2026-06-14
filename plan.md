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
  search.py      — SQLite FTS5 index, OR-semantics query with token-coverage scoring
  meta.py        — .meta.yaml read/write/generate/validate
  config.py      — .codexlr8.yaml loading with defaults
  cli.py         — Click CLI (scan, init, index, search, status, setup)
  mcp_server.py  — MCP stdio server wrapping SearchEngine
```

## The Three-Layer Value Stack

| Layer | Source | What | Weight |
|---|---|---|---|
| 1 | File content | Function names, variable names, comments, docstrings | 0.3× per token |
| 2a | File path | Filename, directory components | 0.5–0.8× per token |
| 2b | `.meta.yaml` curated fields | summary + tags | 0.6–0.8× boost |
| 3 | `.meta.yaml` public_api | Explicit symbol list | 1.0× boost |

**Layer 1** and **2a** work immediately, zero setup, on any codebase — path weighting provides differentiation even without metadata. **Layers 2b–3** add precision through optional human/agent curation.

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

**OR with token-coverage scoring.** All tokens are searched with OR. A custom scoring layer (path weighting, metadata boosts, match ratio) surfaces files that match more tokens. A post-filter requires ≥50% token match for multi-token queries. This replaces the previous AND-then-OR fallback, which caused precise multi-token queries to return zero results (AND too strict) or too many flatly-scored results (OR fallback with no differentiation).

### Tokenization

Matches identifiers (`[a-zA-Z_][a-zA-Z0-9_]*`) and standalone numbers (`\d+`). Single-letter tokens are discarded. `"Phase 28"` → `["phase", "28"]`. Number support was added in v0.1 after discovering that OR semantics + no-number matching made queries like "Phase 28" only match on "phase".

### Scoring

```
score = (∑ token_boost) × match_ratio

token_boost:
  token ∈ public_api     → 1.0
  token == filename      → 0.8   (e.g. "axes3d" in axes3d.py)
  token ∈ tags           → 0.8
  token ∈ filename_part  → 0.7   (e.g. "axes3d" in rotate_axes3d_sgskip.py)
  token ∈ summary        → 0.6
  token ∈ dir_path       → 0.5   (e.g. "mplot3d" in lib/mpl_toolkits/mplot3d/)
  token ∈ content (FTS5) → 0.3

match_ratio: matched_tokens / total_query_tokens

Penalties:
  __init__.py            → score × 0.6
```

Path weighting means a file whose name IS the query token ranks above one that merely mentions it in content. Directory-component matching provides a middle tier. This gives the engine differentiation even when metadata is absent.

### Incremental Indexing

Tracks `file_mtime` per indexed file. `--incremental` mode compares timestamps and only re-indexes changed, new, or deleted files. Removed files are dropped from the index.

### Exclusion

Files are excluded at **index time** (never enter the index) and **query time** (filtered from results). Patterns are globs matched against both full path and basename. Default excludes: `tests/*`, `test/*`, `spec/*`, `__tests__/*`, `test_*`, `*_test.*`, `examples/*`, `docs/*`, `tutorials/*`, `benchmarks/*`.

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

Two tools: `codebase_search(query, path?, limit?, exclude?, scope?)` and `codebase_index(path?, incremental?, exclude?)`.

**`codebase_search`**: `path` defaults to config `root` or current directory. `scope` restricts results to a path prefix (like `grep -rn "pattern" directory/`), applied as a pre-score SQL filter. `exclude` patterns filter results post-score.

**`codebase_index`**: builds or incrementally updates the search index.

The MCP server runs as a subprocess and communicates over stdio per the Model Context Protocol. Results include paths, line ranges, scores, summaries, tags, matched tokens, and preview snippets. No file read tool — agents use their existing read tool.

## Search Result Clustering

The CLI supports an optional `--grouped` / `-g` flag that clusters flat search results by directory prefix before displaying them. This gives agents the same narrowing signal that `grep | awk | sort | uniq -c` gives human grep users.

### Format

```
$ codexlr8 search . "get_visible" --grouped

12 results in 3 directories (8 files) across project:

lib/foo/  (5 files)
  lib/foo/bar.py:486  [score: 0.90]
    bar module summary
  lib/foo/baz.py:120  [score: 0.70]
    baz helper
  lib/foo/qux.py:55  [score: 0.50]
  ... and 2 more files

src/core/  (2 files)
  src/core/engine.py:10  [score: 0.60]

...

Use --scope <dir> to narrow results (e.g. --scope lib/foo/)
```

### Rules

1. Groups are sorted by **max score** in the group, not total match count
2. Up to 3 files shown per group; remaining shown as `... and N more files`
3. Group depth defaults to 3 directory levels; configurable via `--group-depth <n>`
4. Root-level files (no directory) group under `"."`
5. A `--scope <dir>` hint at the bottom gives the agent a direct follow-up path
6. Grouping is **CLI-only** — the MCP server and JSON output return flat results (or a `"grouped": true` wrapper in JSON when requested)
7. When `--scope` is already active, the hint changes to "Already scoped."

## Design Decisions

### Why no AST parsing?

AST parsing requires per-language dependencies (tree-sitter grammars, Python AST, etc.) and still can't handle comments/docstrings well. Pure tokenization of file content across 20+ languages with FTS5 indexing is simpler, faster, and language-agnostic. The metadata layer provides precision where parsing would help.

### Why SQLite FTS5?

Zero dependencies (stdlib `sqlite3`). Free features: stemming, prefix queries, phrase matching, BM25 ranking. No server process. Portable across platforms. Scales fine for codebases up to millions of tokens.

### Why OR semantics with scoring?

Pure AND was too strict — a 4-token query frequently returned zero results because code rarely contains all exact words together. Pure OR was too noisy — a 10-word query matched thousands of files. The AND-then-OR fallback was fragile: precise queries hit the OR wall and got flatly-scored noise.

OR with token-coverage scoring uses the scoring layer (path weighting, metadata boosts, match ratio) to naturally surface files matching more tokens. A ≥50% post-filter for multi-token queries eliminates single-token noise. The result: more tokens = higher score, not zero results.

### Why sidecars and not inline metadata?

- Indexer reads YAML directly — no source parsing needed
- Auto fields can be regenerated without touching source code
- Works for any file type (code, SQL, Markdown, configs)
- Reading a 15-line `.meta.yaml` costs ~50 tokens

## Future Work

- **Symbol-level indexing**: Detect function/class/method definitions vs. call sites via regex heuristics per language. Store definitions in a weighted FTS5 column (or separate table) so `def draw` scores higher than `ax.draw()`. This is the one language-level tuning that would meaningfully improve search precision — but only as an optional opt-in, never as a core dependency. Candidates: Python (def/class), JS/TS (function/class), Go (func/type), Rust (fn/struct/impl). Without AST/tree-sitter, this would use line-prefix patterns (e.g., `^\s*def\s+` in Python) approximated by regex, accepting ~95% accuracy for zero-dependency operation.
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
