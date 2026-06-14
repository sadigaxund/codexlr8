# AGENTS.md — CodeXLR8 Project Guidelines

## Identity

CodeXLR8 is a codebase search engine for LLM coding agents. It replaces `ls` + `grep` with a single, ranked query. The primary consumer is an MCP-enabled agent, not a human at a web browser.

## Principles

1. **Tokenization over parsing.** No AST, no tree-sitter. Read raw file content, let SQLite FTS5 tokenize it. This keeps the tool language-agnostic and dependency-free.

2. **Metadata boosts, never gates.** A file without `.meta.yaml` still gets indexed. Metadata (summary, tags, public_api) improves ranking precision — it's additive, not required.

3. **AND semantics.** Queries require all tokens to match. Fall back to OR + ≥50% token match threshold only if AND returns nothing. Never revert to pure OR.

4. **Zero external services.** Everything runs locally. No API keys, no cloud DBs, no telemetry. SQLite FTS5 is the only database.

5. **Config over code.** File extensions, ignored directories, exclude patterns — all live in `.codexlr8.yaml` with sensible defaults. Never hardcode project-specific values.

6. **Agent-maintained metadata.** `.meta.yaml` curation is the agent's job, not the developer's. The skill file (`skills/codexlr8-skill.md`) teaches agents how to maintain it.

## Commands

```bash
# Run tests (61 tests)
python -m pytest tests/ -v

# Install for development
pip install -e ".[dev]"

# Test the CLI
codexlr8 scan src/codexlr8/
codexlr8 init src/codexlr8/
codexlr8 index src/codexlr8/
codexlr8 search src/codexlr8/ "search engine"
codexlr8 status src/codexlr8/
codexlr8 setup  # interactive config builder

# Test the MCP server
codexlr8-mcp  # runs, then connect with an MCP client

# Before committing
python -m pytest tests/ -v
```

## Project Structure

```
src/codexlr8/
  scanner.py       # File walking + content reading
  search.py        # FTS5 index, AND query, ranking, status
  meta.py          # .meta.yaml I/O, generation, validation
  config.py        # .codexlr8.yaml loader with defaults
  cli.py           # Click CLI
  mcp_server.py    # MCP stdio server
tests/
  conftest.py      # sample_project fixture (6 Python files)
  test_scanner.py  # 12 tests
  test_meta.py     # 20 tests
  test_search.py   # 24 tests
  test_mcp_server.py # 5 tests
skills/
  codexlr8-skill.md   # Agent instruction file
```

## Adding Features

### Adding a new file extension

Edit `DEFAULT_EXTENSIONS` in `scanner.py` and `_defaults()` in `config.py`. Add both. Tests in `test_scanner.py::TestScanProject::test_includes_js_ts_go_rust`.

### Adding a new CLI command

1. Add a `@main.command()` function in `cli.py`
2. Wire it to a `SearchEngine` method or a standalone function
3. Add tests in the appropriate test file
4. Update README commands table

### Adding a new MCP tool

1. Add to `list_tools()` return value in `mcp_server.py`
2. Add handler in `call_tool()`
3. Add test in `test_mcp_server.py`
4. Update skill file if agents should use it

### Changing search behavior

Modify `search()` in `search.py`. Ranking changes go in `_compute_score()`. Tokenization changes go in `_tokenize()`. Query semantics changes go in `search()` (the AND/OR logic). Always add tests documenting the expected behavior.

## What NOT to Change

- **Don't add AST parsing.** If you need per-language features, use optional tree-sitter plug-ins, not core AST.
- **Don't revert to OR semantics.** AND is the correct default. If AND is too strict for a use case, improve the fallback, don't weaken the default.
- **Don't add external dependencies.** New features should not require Docker, cloud services, or native binaries.
- **Don't change the `.meta.yaml` format without backward compatibility.** Parse old fields, write new fields. Add migration logic if needed.
- **Don't namespace the index file.** `.codexlr8_index.db` is in the project root. Keep it there.

## Commit Style

```
Phase N: Short description of the feature or fix

- Bullet list of changes
- Each bullet is a concrete action
- Mention test impact
```

## Release

```bash
git tag v$(python -c "from codexlr8 import __version__; print(__version__)")
git push --tags
```

GitHub Actions publishes to PyPI and creates a release with the relevant CHANGELOG section.
