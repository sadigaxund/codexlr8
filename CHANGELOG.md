# Changelog

## [0.0.2] — Unreleased

Search quality improvements from benchmark feedback.

### Added
- **`--explain` / `-e`**: query token diagnostics showing per-token hit counts, filtered words, and quality signal
- **`--grouped` / `-g`**: clusters search results by directory with `--scope` hints
- **`--group-depth <n>`**: control directory depth for grouping (default 3)
- **`--scope` / `-s`**: restrict search to a path prefix, applied as pre-score SQL filter
- **Path weighting**: filename match (0.8×), filename component (0.7×), directory (0.5×) — works without metadata
- **Coverage warning**: `status` warns when <10% of files have metadata
- **Matched tokens**: each result includes which query tokens matched

### Changed
- Query semantics: replaced AND-then-OR fallback with pure OR + token-coverage scoring
- Default excludes now include `examples/*`, `docs/*`, `tutorials/*`, `benchmarks/*`
- JSON output format: `{"results": [...]}` instead of bare list (supports `explain`, `grouped` wrappers)

### Fixed
- Flat BM25 when metadata absent — path weighting now provides differentiation without sidecars
- No path-weighting in ranking — `lib/foo.py` now outranks `examples/foo.py` for matching query
- AND-then-OR precision hole — multi-token queries no longer return zero or too many flat-score results

## [0.0.1] — First release

Initial release. A purpose-built codebase search engine for LLM coding agents.
