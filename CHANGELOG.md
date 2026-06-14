# Changelog

## [0.0.1] — Unreleased

Initial release. A purpose-built codebase search engine for LLM coding agents.

### Features
- Full-text codebase search with SQLite FTS5 and AND semantics
- `.meta.yaml` sidecar files for curated metadata (summary, tags, public_api)
- CLI: `scan`, `init`, `index`, `search`, `status`, `setup`
- MCP server for agent integration (`codebase_search`, `codebase_index`)
- Agent skill file with session workflow guidance
- Custom ranking: metadata boosts (public_api > tags > filename > summary > path > content) + BM25
- Configurable scope: root, include/exclude patterns, file extensions, ignore dirs
- Incremental indexing via file mtime tracking
- Interactive `setup` wizard for `.codexlr8.yaml`
- JSON output for programmatic use
