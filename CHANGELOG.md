# Changelog

## [0.0.1] — Unreleased

Initial release. A purpose-built codebase search engine for LLM coding agents.

### Features
- Full-text codebase search with SQLite FTS5 and OR semantics with token-coverage scoring
- `.meta.yaml` sidecar files for curated metadata (summary, tags, public_api)
- CLI: `scan`, `init`, `index`, `search`, `status`, `setup`
- MCP server for agent integration (`codebase_search`, `codebase_index`)
- Agent skill file with session workflow guidance
- Custom ranking: metadata boosts (public_api > tags > filename > summary > path > content) + BM25
- Path weighting: filename match (0.8×), filename component (0.7×), directory (0.5×) — works without metadata
- Directory-scoped search: `--scope lib/foo/` filters before scoring, like grep's directory arg
- Search result clustering: `--grouped` groups results by directory with scope hints
- Configurable scope: root, include/exclude patterns, file extensions, ignore dirs
- Default excludes: tests, examples, docs, tutorials, benchmarks
- Incremental indexing via file mtime tracking
- Interactive `setup` wizard for `.codexlr8.yaml`
- Status command shows metadata coverage and warns when <10%
- JSON output for programmatic use
- Matched tokens returned in results for search diagnostics
