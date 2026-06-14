# CodeXLR8 — Agent Search Skill

You have access to a codebase search engine called CodeXLR8. It is a purpose-built search index for this codebase. Use it **before** reading any files to find the right code.

## When to search

- **Before any file read** — if a task mentions a feature, concept, or bug (e.g. "fix the login bug", "add refund to payments", "how does checkout work"), search first.
- **When you're lost** — if you don't know which file or module handles a responsibility, search.
- **Before grep or ls** — CodeXLR8 replaces directory listing and text search. One query is cheaper and more precise than `ls` + `grep`.

## How to search

Use `codebase_search` with the key nouns and terms from the task description:

```
codebase_search(query="login auth")
codebase_search(query="stripe charge customer refund")
codebase_search(query="shopping cart checkout payment")
```

### Query strategy

Describe what you're looking for in natural language. The engine uses OR semantics with a scoring layer — more terms increase precision through token-coverage ranking, not a hard AND requirement.

**Good queries use distinct, discriminating terms:**

| Task | Good query | Why |
|---|---|---|
| Fix login bug | `"login auth session token"` | Covers auth module, session, tokens — distinct terms, not synonyms |
| Payment refund | `"stripe refund charge customer"` | Each term narrows to a different aspect of the feature |
| 3D plot visibility | `"axes3d draw visible renderer"` | Domain term + method + symptom — different dimensions of the bug |
| Checkout flow | `"checkout cart payment order"` | Covers all stages of the flow |

**What to avoid:**
- Single-word queries (`"login"`) — too broad, returns everything mentioning login
- Synonyms (`"login authenticate signin"`) — redundant, wastes tokens without improving coverage
- Full sentences (`"I need to find where user login happens"`) — stop words like `"I"`, `"need"`, `"to"` are filtered out

### Using scope and grouping

When you know which directory the code lives in, scope the search:

```
codebase_search(query="get_visible", scope="lib/mpl_toolkits/")
```

When you don't know, run a shell command to see where results cluster:

```bash
codexlr8 search . "get_visible" --grouped
```

This prints directories ranked by their highest-scoring file, with a `--scope` hint to copy into your next MCP call.

### When results don't look right

Check the `matched` field on each result. If a file you expected isn't showing, the missing token tells you what to adjust. If all results only match 1 of 4 tokens, your terms are too scattered — try removing one.

## Interpreting results

Results include:

| Field | Meaning |
|---|---|
| `path:line-line` | File and line range where the match lives |
| `score` | Relevance (higher = better) |
| `summary` | Human-written description of the file's purpose |
| `tags` | Curated keywords (auth, payment, cart, etc.) |
| `matched` | Which query tokens the file matched — use this to debug failed searches |
| `preview` | First ~10 lines around the best match |

**Ranking:** Files with curated `.meta.yaml` (summary + tags) rank highest, followed by filename matches, then path directory matches. Raw content matches rank lowest. `__init__.py` re-exports are penalized.

## Maintaining the index

### Session start — check health

At the start of every session, run:

```
codebase_index(path=".")
```

This builds the index if it doesn't exist, or is a no-op if it's fresh. If the index is stale (older than the latest commit), consider:

```
codebase_index(path=".", incremental=true)
```

### After making changes

After you modify files, update the index so your next search reflects the changes:

```
codebase_index(path=".", incremental=true)
```

Run this once per session when you're done editing, not after every single file.

## Maintaining .meta.yaml sidecars

### Checking coverage

Run `codexlr8 status .` (via shell) to see coverage:

```
Files indexed: 42
Files with .meta.yaml: 15
Files without .meta.yaml: 27
```

If more than 50% of indexed files lack a `.meta.yaml`, run `codexlr8 init .` to bootstrap the missing ones.

### Filling in metadata

After modifying a file, check its `.meta.yaml` sidecar and update:

- **`summary`** — one sentence describing the file's purpose. Be specific: "User authentication: login, logout, password reset, session creation" not just "auth stuff".
- **`tags`** — 2-5 keywords for the module's domain: `[auth, login, session, security]`.
- **`public_api`** — list of exported function/class names. Update when you add or remove exports.
- **`invariants`** — any contract the caller must uphold: "db.connect() must be called first".

Example before:
```yaml
public_api: []
dependencies: []
used_by: []
summary: ""
tags: []
```

Example after:
```yaml
public_api: [login, logout, reset_password]
dependencies: [models.user, utils.hashing, utils.db]
used_by: [main, api.auth_routes]
summary: "User authentication: login, logout, password reset, session creation"
tags: [auth, login, session, security]
invariants:
  - "Passwords are always bcrypt-hashed before storage"
```

**Only curate files you actually touch.** Don't try to backfill the entire codebase.

## Excluding files and scoping search

By default, test files (`tests/`, `test_*`, `*_test.*`), spec files, and vendored code are excluded from search results.

### Exclude patterns

Use `exclude` to filter out more files:
```
codebase_search(query="auth", exclude=["vendor/*", "migrations/*"])
```
Exclude patterns are globs that match file paths. Use `*` for wildcards.

### Directory scoping

When you know which directory contains the relevant code (e.g. a bug is in the 3D plotting library), use `scope` to restrict the search:
```
codebase_search(query="get_visible", scope="lib/mpl_toolkits/")
```
This is equivalent to `grep -rn "pattern" directory/`. The scope filter is applied before scoring, making it far more efficient than post-hoc exclude patterns.

## Quick reference

| Task | Tool call |
|---|---|
| Find code for a feature | `codebase_search(query="...")` |
| Search within a directory | `codebase_search(query="...", scope="src/")` |
| Cluster results by directory | Shell: `codexlr8 search . "query" --grouped` |
| Build/update index | `codebase_index(incremental=true)` |
| Check metadata coverage | Shell: `codexlr8 status .` |
| Bootstrap missing sidecars | Shell: `codexlr8 init .` |
| Rebuild full index | Shell: `codexlr8 index .` |
