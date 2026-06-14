# Changelog

## [0.0.3] — Unreleased

Search quality infrastructure: eval framework, fuzzy fallback, embeddings layer, fine-tuning.

### Added
- **`eval` command**: measure search quality with Precision@1, MRR, Recall@5
- **`--explain` / `-e`**: per-token hit counts, zero-match detection, quality signal
- **`--grouped` / `-g`**: directory-clustered results with `--scope` hints
- **`--scope` / `-s`**: SQL LIKE pre-filter for path-prefix search
- **Fuzzy fallback**: difflib Levenshtein correction on zero results (config: `fuzzy: true`)
- **Embeddings layer**: opt-in hybrid BM25 + cosine rerank via `embeddings.enabled`
- **`train` command**: TSDAE fine-tune any sentence-transformers model on codebase
- **`recommend-model` command**: suggest best model by codebase size
- **Scope-granularity eval**: `file`, `scope`, `exact` assert modes with line overlap
- **Incremental embed**: `--incremental` only re-embeds changed files

### Changed
- Query semantics: AND-then-OR → pure OR + token-coverage scoring
- Default excludes: added `examples/*`, `docs/*`, `tutorials/*`, `benchmarks/*`
- JSON output: `{"results": [...]}` wrapper with optional `explain`/`grouped` keys

### Fixed
- Flat BM25 when metadata absent — path weighting provides differentiation
- No path differentiation in ranking — filename, dir component weighting
- AND-then-OR precision hole — multi-token queries no longer fail or return noise

## [0.0.2] — 2026-06-14

Search quality improvements from benchmark feedback. (Superseded by 0.0.3)

## [0.0.1] — First release

Initial release. A purpose-built codebase search engine for LLM coding agents.
