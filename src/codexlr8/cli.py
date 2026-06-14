"""CodeXLR8 CLI — search-first codebase navigation for agents."""

import asyncio
import os
import click

from .config import load_config
from .scanner import scan_project
from .meta import generate_missing_sidecars
from .search import SearchEngine, _group_results, _explain_query, _tokenize


EXCLUDE_HELP = (
    "Exclude files matching a glob pattern. Repeatable. "
    "Defaults from .codexlr8.yaml if not specified. "
    'Example: --exclude "tests/*" --exclude "migrations/*"'
)


def _parse_excludes(ctx: click.Context, param: click.Option, values: tuple[str, ...]) -> list[str]:
    """Collect --exclude values from CLI and fall back to config defaults."""
    if values:
        return list(values)
    config = load_config(ctx.params["project_path"])
    return config.get("exclude", [])


@click.group()
def main():
    """CodeXLR8 — a codebase search engine for LLM coding agents."""


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.option("--output", "-o", default=None, help="Write scan data to JSON file")
def scan(project_path: str, output: str | None):
    """Scan a project and show file counts and line counts."""
    config = load_config(project_path)
    results = scan_project(
        project_path,
        extensions=config.get("extensions"),
        ignore_dirs=config.get("ignore_dirs"),
        include=config.get("include"),
        exclude=config.get("exclude"),
    )
    if output:
        import json
        with open(output, "w") as f:
            json.dump(results, f, indent=2)
        click.echo(f"Wrote content data for {len(results)} files to {output}")
    else:
        total_lines = sum(len(r.get("content", "").splitlines()) for r in results)
        click.echo(f"Scanned {len(results)} files ({total_lines} lines total)")
        for entry in results[:10]:
            lines = len(entry["content"].splitlines())
            click.echo(f"  {entry['path']}  ({lines} lines)")
        if len(results) > 10:
            click.echo(f"  ... and {len(results) - 10} more files")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.argument("query")
@click.option("--exclude", "-x", "exclude_patterns", multiple=True,
              callback=_parse_excludes, help=EXCLUDE_HELP)
@click.option("--scope", "-s", default=None,
              help="Restrict search to files under a path prefix (e.g. src/ or lib/mpl_toolkits/)")
@click.option("--grouped", "-g", is_flag=True, default=False,
              help="Cluster results by directory before listing files")
@click.option("--explain", "-e", is_flag=True, default=False,
              help="Show token breakdown and query diagnostics")
@click.option("--group-depth", default=3,
              help="Max directory depth for grouping (default: 3)")
@click.option("--format", "-f", "output_format",
              type=click.Choice(["text", "json"]), default="text")
@click.option("--limit", "-n", default=10, help="Maximum number of results")
def search(project_path: str, query: str, exclude_patterns: list[str],
           scope: str | None, grouped: bool, explain: bool, group_depth: int,
           output_format: str, limit: int):
    """Search the codebase for code matching QUERY.

    PROJECT_PATH is the root directory of the codebase to search.

    \b
    Examples:
      codexlr8 search . "login auth"
      codexlr8 search . "login auth" --grouped
      codexlr8 search . "login auth" --explain
      codexlr8 search . "login auth" --exclude "tests/*"
      codexlr8 search . "login auth" -x "tests/*" -x "vendor/*"
      codexlr8 search . "get_visible" --scope lib/mpl_toolkits/
    """
    engine = SearchEngine(project_path)
    results = engine.search(query, limit=limit, exclude=exclude_patterns, scope=scope)

    if output_format == "json":
        import json
        output = {"results": results}
        if explain:
            output["explain"] = _explain_query(query, _tokenize(query), results)
        if grouped:
            groups_data = _group_results(results, group_depth)
            output["grouped"] = True
            output["groups"] = groups_data["groups"]
            output["summary"] = {
                "total_results": groups_data["total_results"],
                "total_files": groups_data["total_files"],
                "total_groups": len(groups_data["groups"]),
            }
        click.echo(json.dumps(output, indent=2))
        return

    if not results:
        click.echo("No results found.")
        if explain:
            tokens = _tokenize(query)
            click.echo()
            click.echo("Query analysis:")
            for t in tokens:
                click.echo(f"  \"{t}\"  \u2717 no matches")
            click.echo()
            click.echo("0 tokens matched. All terms are absent from the codebase.")
        return

    if explain:
        tokens = _tokenize(query)
        explain_data = _explain_query(query, tokens, results)
        _print_explain(explain_data)
        click.echo()

    if grouped:
        _print_grouped(results, group_depth, scope)
        return

    for i, r in enumerate(results, 1):
        click.echo(f"{i}. {r['path']}:{r['line_start']}-{r['line_end']}  "
                   f"[score: {r['score']:.2f}]")
        if r.get("summary"):
            click.echo(f"   meta:   {r['summary']}")
        if r.get("tags"):
            click.echo(f"   tags:   {', '.join(r['tags'])}")
        if r.get("matched_tokens"):
            click.echo(f"   matched: {', '.join(r['matched_tokens'])}")
        if r.get("preview"):
            click.echo("   preview: |")
            for line in r["preview"].strip().splitlines()[:6]:
                click.echo(f"     {line}")
        click.echo()


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.option("--incremental", "-i", is_flag=True, default=False,
              help="Only re-index files that have changed since last build")
@click.option("--exclude", "-x", "exclude_patterns", multiple=True,
              callback=_parse_excludes, help=EXCLUDE_HELP)
def index(project_path: str, incremental: bool, exclude_patterns: list[str]):
    """Build the full search index for a project.

    \b
    Examples:
      codexlr8 index .
      codexlr8 index . --incremental
      codexlr8 index . --exclude "tests/*" --exclude "vendor/*"
    """
    engine = SearchEngine(project_path)
    count = engine.build_index(incremental=incremental, exclude=exclude_patterns)
    if incremental:
        click.echo(f"Incrementally updated {count} files.")
    else:
        click.echo(f"Indexed {count} files.")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
def init(project_path: str):
    """Bootstrap missing .meta.yaml sidecar files for a project."""
    created = generate_missing_sidecars(project_path)
    if created:
        click.echo(f"Created {len(created)} .meta.yaml files:")
        for path in created:
            click.echo(f"  {path}")
    else:
        click.echo("All files already have .meta.yaml sidecars.")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
def status(project_path: str):
    """Show index state and file coverage."""
    engine = SearchEngine(project_path)
    state = engine.status()
    click.echo(f"Project: {state['project_path']}")
    click.echo(f"Files indexed: {state['files_indexed']}")
    click.echo(f"Files with .meta.yaml: {state['files_with_meta']}")
    click.echo(f"Files without .meta.yaml: {state['files_without_meta']}")
    click.echo(f"Total lines indexed: {state['total_lines']}")
    click.echo(f"Index age: {state.get('index_age', 'N/A')}")
    click.echo(f"Coverage: {state.get('coverage_pct', 0)}%")
    if state.get("warning"):
        click.echo()
        click.secho(f"  Warning: {state['warning']}", fg="yellow")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.option("--queries", "-q", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Path to JSON file with query definitions")
@click.option("--limit", "-n", default=10,
              help="Max results per query (default: 10)")
def eval_cmd(project_path: str, queries: str, limit: int):
    """Evaluate search quality against a query set.

    QUERIES is a JSON file with an array of query objects:
    [{"query": "...", "expected": "path/to/file.py", "min_rank": 1}]

    Outputs a per-query pass/fail table and aggregate metrics:
    Precision@1, Mean Reciprocal Rank (MRR), Recall@5.
    """
    from .eval import load_queries, run_eval
    import json

    try:
        query_defs = load_queries(queries)
    except (json.JSONDecodeError, ValueError) as e:
        raise click.ClickException(f"Invalid queries file: {e}")

    if not query_defs:
        raise click.ClickException("Queries file contains no queries.")

    metrics = run_eval(project_path, query_defs, limit=limit)

    # Per-query table
    click.secho("  Query                             Expected            Mode   Lines    Rank  Score   Status", fg="cyan", bold=True)
    click.secho("  " + "─" * 100, fg="cyan")

    for r in metrics["results"]:
        query_str = f'"{r["query"]}"'.ljust(34)
        expected_str = r["expected"].ljust(20)
        mode_str = r.get("assert", "file").ljust(6)
        lines_str = ""
        if r.get("line_start"):
            lines_str = f"{r['line_start']}-{r['line_end']}".ljust(8)
        else:
            lines_str = "—".ljust(8)
        rank_str = str(r["rank"]).ljust(6) if r["rank"] else "—     "
        score_str = f'{r["score"]:.2f}'.ljust(8) if r["score"] else "—       "
        status = r["status"]

        if status.startswith("pass"):
            status_style = {"fg": "green"}
        elif "found" in status:
            status_style = {"fg": "yellow"}
        else:
            status_style = {"fg": "red"}

        click.echo(f"  {query_str} {expected_str} {mode_str} {lines_str} {rank_str} {score_str} {click.style(status, **status_style)}")

    # Aggregate metrics
    click.echo()
    click.echo(click.style("  " + "─" * 40, fg="cyan"))
    click.secho(f"  Precision@1:  {metrics['precision_at_1']:.2%}  "
                f"({metrics['passed']}/{metrics['num_queries']} passed)", fg="green")
    click.secho(f"  MRR:          {metrics['mrr']:.4f}", fg="green")
    click.secho(f"  Recall@5:     {metrics['recall_at_5']:.2%}", fg="green")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False), default=".")
def setup(project_path: str):
    """Interactively create a .codexlr8.yaml configuration file.

    Also detects MCP clients and offers to inject the server config.
    """
    import os
    import json
    import yaml
    import sys

    click.echo()
    click.secho("  ╔══════════════════════════════════════════╗", fg="cyan")
    click.secho("  ║       CodeXLR8  —  Setup                 ║", fg="cyan", bold=True)
    click.secho("  ╚══════════════════════════════════════════╝", fg="cyan")
    click.echo()

    # ---- Phase 1: MCP client detection and injection ----
    mcp_config = {
        "mcpServers": {
            "codexlr8": {
                "command": "uvx",
                "args": ["codexlr8", "mcp-server"],
            }
        }
    }
    mcp_json = json.dumps(mcp_config, indent=2)

    clients = {
        "Claude Code": os.path.expanduser("~/.claude/claude.json"),
        "Cursor": os.path.expanduser("~/.cursor/mcp.json"),
    }

    detected = {name: path for name, path in clients.items() if os.path.exists(path)}

    if detected:
        click.secho("  ▸ MCP Clients Detected", fg="green", bold=True)
        for name, path in detected.items():
            click.echo(f"    [✓] {name}  ({path})")

        click.echo()
        for name, path in detected.items():
            if click.confirm(click.style(f"  Inject CodeXLR8 into {name}?", fg="yellow")):
                _inject_mcp_config(path, mcp_json)
                click.secho(f"    ✓  Injected into {os.path.basename(path)}", fg="green")

        click.echo()
        click.secho("  CodeXLR8 MCP server is now configured.", fg="cyan")
        click.secho("  Restart your MCP client to activate the tools.", dim=True)
        click.echo()
    else:
        click.secho("  ▸ No MCP clients detected.", dim=True)
        click.echo()
        click.echo("  To manually configure an MCP client, add this to its config file:")
        click.echo()
        click.echo(mcp_json)
        click.echo()
        if not click.confirm(click.style("  Continue with project config?", fg="yellow")):
            click.secho("  Done. Run 'codexlr8 setup' again later if needed.", fg="cyan")
            return

    # ---- Phase 2: Project config ----
    config_path = os.path.join(project_path, ".codexlr8.yaml")

    if os.path.exists(config_path):
        if not click.confirm(
            click.style("  .codexlr8.yaml already exists. Overwrite?", fg="yellow")
        ):
            click.secho("  Skipped project config.", fg="cyan")
            return

    click.secho("  ▸ Project Config", fg="green", bold=True)
    click.secho("  Press Enter to accept defaults, or type your own values.", dim=True)
    click.echo()

    root = click.prompt(
        click.style("    Root", fg="bright_white"), default="."
    ).strip() or "."
    click.echo()

    custom_include = click.prompt(
        click.style("    Include (comma-separated, empty = all)", fg="bright_white"), default=""
    ).strip()
    include = [p.strip() for p in custom_include.split(",") if p.strip()]
    click.echo()

    defaults = ["tests/*", "test/*", "spec/*", "__tests__/*", "test_*", "*_test.*",
                "examples/*", "docs/*", "tutorials/*", "benchmarks/*"]
    custom_exclude = click.prompt(
        click.style("    Exclude (comma-separated)", fg="bright_white"),
        default=", ".join(defaults),
    ).strip()
    exclude = [p.strip() for p in custom_exclude.split(",") if p.strip()] if custom_exclude else defaults
    click.echo()

    ext_defaults = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
                    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
                    ".kt", ".sql", ".sh", ".lua"]
    custom_ext = click.prompt(
        click.style("    Extensions (comma-separated)", fg="bright_white"),
        default=", ".join(ext_defaults),
    ).strip()
    extensions = [p.strip() for p in custom_ext.split(",") if p.strip()] if custom_ext else ext_defaults
    click.echo()

    ig_defaults = [".git", "__pycache__", "node_modules", ".venv", "venv",
                   ".tox", ".mypy_cache", ".pytest_cache", "dist", "build"]
    custom_ig = click.prompt(
        click.style("    Ignore dirs (comma-separated)", fg="bright_white"),
        default=", ".join(ig_defaults),
    ).strip()
    ignore_dirs = [p.strip() for p in custom_ig.split(",") if p.strip()] if custom_ig else ig_defaults

    config = {
        "root": root,
        "include": include,
        "exclude": exclude,
        "extensions": extensions,
        "ignore_dirs": ignore_dirs,
    }

    click.echo()
    click.secho("  ── Preview ──", fg="cyan")
    for line in yaml.dump(config, default_flow_style=False).strip().splitlines():
        click.echo(f"  {click.style(line, fg='bright_white')}")
    click.echo()

    if click.confirm(click.style("  Write this to .codexlr8.yaml?", fg="yellow")):
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
        click.secho(f"  ✓  Wrote {config_path}", fg="green")
    else:
        click.secho("  Skipped.", dim=True)

    # ---- Phase 3: Agent skill ----
    click.echo()
    click.secho("  ▸ Agent Skill", fg="green", bold=True)
    skill_dir = os.path.expanduser("~/.claude/skills/codexlr8")
    skill_path = os.path.join(skill_dir, "SKILL.md")

    if os.path.exists(skill_path):
        click.echo(f"    Skill already installed: {skill_path}")
    elif click.confirm(click.style("  Install agent skill for Claude Code?", fg="yellow")):
        os.makedirs(skill_dir, exist_ok=True)
        with open(skill_path, "w") as f:
            f.write(_SKILL_CONTENT)
        click.secho(f"    ✓  Installed to {skill_path}", fg="green")

    click.echo()
    click.secho("  Setup complete.", fg="cyan", bold=True)
    click.secho("  Run 'codexlr8 index .' to build your first search index.", dim=True)


def _print_explain(data: dict):
    """Print query diagnostic breakdown."""
    click.secho("Query analysis:", fg="cyan", bold=True)
    click.echo(f"  Original:  \"{data['query']}\"")
    click.echo(f"  Tokens:    {', '.join(data['tokens'])}")
    click.echo()

    for token in data["tokens"]:
        hits = data["token_hits"].get(token, 0)
        total = data["total_results"]
        if hits == 0:
            status = click.style(f"{hits} matches", fg="red")
            hint = " — consider dropping or replacing"
        elif hits <= 3:
            status = click.style(f"{hits} matches", fg="yellow")
            hint = " — very specific"
        elif hits <= total * 0.1:
            status = click.style(f"{hits} matches", fg="green")
            hint = ""
        else:
            status = click.style(f"{hits} matches", fg="yellow")
            hint = f" — broad term ({hits}/{total} results)"

        click.echo(f"  \"{token}\"  {status}{hint}")

    for fw in data["filtered"]:
        click.echo(f"  \"{fw}\"  {click.style('filtered', fg='yellow')} — single letter, ignored")

    click.echo()
    top = data["top_score"]
    if top < 0.60:
        quality = click.style("weak", fg="red")
    elif top < 1.20:
        quality = click.style("moderate", fg="yellow")
    else:
        quality = click.style("strong", fg="green")
    click.echo(f"  Top score: {top} ({quality} match)")

    if data["filtered"]:
        click.echo(click.style("  Tip:", dim=True) + " single-letter words are ignored. Use full terms.")
    zero_match = [t for t in data["tokens"] if data["token_hits"].get(t, 0) == 0]
    if zero_match:
        click.echo(click.style("  Tip:", dim=True) + f" \"{zero_match[0]}\" doesn't exist — try a synonym or drop it.")


def _print_grouped(results: list[dict], group_depth: int, scope: str | None):
    """Print search results clustered by directory."""
    groups_data = _group_results(results, group_depth)
    groups = groups_data["groups"]
    total = groups_data["total_results"]
    files = groups_data["total_files"]

    scope_label = f"in {scope}" if scope else "across project"
    click.echo(f"{total} results in {len(groups)} directories ({files} files) {scope_label}:")
    click.echo()

    top_groups = groups[:5]
    for g in top_groups:
        # Directory header with match count
        label = g["prefix"].rstrip(os.sep)
        click.echo(f"{label}/  ({g['count']} files)")

        for f in g["files"]:
            line_info = f"{f['path']}:{f['line_start']}-{f['line_end']}"
            score_info = f"{f['score']:.2f}"
            click.echo(f"  {click.style(line_info, fg='cyan')}  "
                       f"[score: {score_info}]")

            # Summary line from preview or metadata
            if f.get("summary"):
                click.echo(f"    {f['summary']}")
            elif f.get("preview"):
                first_line = f["preview"].strip().splitlines()[0].strip() if f["preview"].strip() else ""
                if first_line:
                    click.echo(f"    {first_line[:100]}")

        if g["has_more"]:
            click.echo(f"  ... and {g['remaining']} more files")
        click.echo()

    if len(groups) > 5:
        click.echo(f"... and {len(groups) - 5} more directories")

    # Scope hint
    click.echo()
    if scope:
        click.echo(click.style("Already scoped. Remove --scope to broaden.", dim=True))
    else:
        click.echo(
            click.style(
                f"Use --scope <dir> to narrow results (e.g. --scope {top_groups[0]['prefix']})",
                dim=True
            )
        )


def _inject_mcp_config(config_path: str, mcp_json: str) -> None:
    """Inject the CodeXLR8 MCP config into an existing client config file.

    If the file contains valid JSON with an 'mcpServers' key, merge.
    Otherwise, write fresh.
    """
    import json
    import os

    existing: dict = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, Exception):
            pass

    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    if "codexlr8" in existing.get("mcpServers", {}):
        # Already present — skip
        return

    codexlr8_config = {"command": "uvx", "args": ["codexlr8", "mcp-server"]}
    existing["mcpServers"]["codexlr8"] = codexlr8_config

    with open(config_path, "w") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")


@main.command()
def mcp_config():
    """Print the MCP client config JSON for Claude Code / other clients."""
    import json

    config = {
        "mcpServers": {
            "codexlr8": {
                "command": "uvx",
                "args": ["codexlr8", "mcp-server"],
            }
        }
    }
    click.echo()
    click.secho("  Add this to your MCP client config:", fg="cyan")
    click.echo("  (Claude Code: ~/.claude/claude.json, Cursor: .cursor/mcp.json)")
    click.echo()
    click.echo(json.dumps(config, indent=2))
    click.echo()
    click.echo(
        "  Works with any MCP client: Claude Code, Cursor, Windsurf, "
        "Continue.dev, custom agents."
    )


@main.command(name="mcp-server")
def mcp_server_cmd():
    """Start the CodeXLR8 MCP server (for use with uvx / MCP clients)."""

    from .mcp_server import _run
    asyncio.run(_run())


@main.command()
def install_skill():
    """Install the CodeXLR8 agent skill into ~/.claude/skills/."""
    import os

    skill_dir = os.path.expanduser("~/.claude/skills/codexlr8")
    os.makedirs(skill_dir, exist_ok=True)
    dest = os.path.join(skill_dir, "SKILL.md")

    with open(dest, "w") as f:
        f.write(_SKILL_CONTENT)

    click.secho(f"  ✓  Installed skill to {dest}", fg="green")


_SKILL_CONTENT = r"""# CodeXLR8 — Agent Search Skill

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

For deeper diagnostics, run:

```bash
codexlr8 search . "your query" --explain
```

This shows per-token hit counts and flags zero-match terms so you can refine before calling `codebase_search` again.

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

## Excluding files

By default, test files (`tests/`, `test_*`, `*_test.*`), spec files, and vendored code are excluded from search results. Use `exclude` to filter more:

```
codebase_search(query="auth", exclude=["vendor/*", "migrations/*"])
```

Exclude patterns are globs that match file paths. Use `*` for wildcards.

## Quick reference

| Task | Tool call |
|---|---|
| Find code for a feature | `codebase_search(query="...")` |
| Search within a directory | `codebase_search(query="...", scope="src/")` |
| Cluster results by directory | Shell: `codexlr8 search . "query" --grouped` |
| Diagnose query terms | Shell: `codexlr8 search . "query" --explain` |
| Build/update index | `codebase_index(incremental=true)` |
| Check metadata coverage | Shell: `codexlr8 status .` |
| Bootstrap missing sidecars | Shell: `codexlr8 init .` |
| Rebuild full index | Shell: `codexlr8 index .` |
"""
