"""CodeXLR8 CLI — search-first codebase navigation for agents."""

import click

from .config import load_config
from .scanner import scan_project
from .meta import generate_missing_sidecars
from .search import SearchEngine


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
@click.option("--format", "-f", "output_format",
              type=click.Choice(["text", "json"]), default="text")
@click.option("--limit", "-n", default=10, help="Maximum number of results")
def search(project_path: str, query: str, exclude_patterns: list[str],
           output_format: str, limit: int):
    """Search the codebase for code matching QUERY.

    PROJECT_PATH is the root directory of the codebase to search.

    \b
    Examples:
      codexlr8 search . "login auth"
      codexlr8 search . "login auth" --exclude "tests/*"
      codexlr8 search . "login auth" -x "tests/*" -x "vendor/*"
    """
    engine = SearchEngine(project_path)
    results = engine.search(query, limit=limit, exclude=exclude_patterns)

    if output_format == "json":
        import json
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"{i}. {r['path']}:{r['line_start']}-{r['line_end']}  "
                   f"[score: {r['score']:.2f}]")
        if r.get("summary"):
            click.echo(f"   meta:   {r['summary']}")
        if r.get("tags"):
            click.echo(f"   tags:   {', '.join(r['tags'])}")
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


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False), default=".")
def setup(project_path: str):
    """Interactively create a .codexlr8.yaml configuration file."""
    import os
    import yaml

    config_path = os.path.join(project_path, ".codexlr8.yaml")

    click.echo()
    click.secho("  ╔══════════════════════════════════════════╗", fg="cyan")
    click.secho("  ║       CodeXLR8  —  Project Setup         ║", fg="cyan", bold=True)
    click.secho("  ╚══════════════════════════════════════════╝", fg="cyan")
    click.echo()

    if os.path.exists(config_path):
        if not click.confirm(
            click.style("  .codexlr8.yaml already exists. Overwrite?", fg="yellow")
        ):
            click.secho("  Aborted.", fg="red")
            return

    click.secho("  Press Enter to accept defaults, or type your own values.", dim=True)
    click.echo()

    # Root
    click.secho("  ▸ Project Root", fg="green", bold=True)
    click.echo("    The directory to scan from (relative to this location).")
    root = click.prompt(
        click.style("    Root", fg="bright_white"), default="."
    ).strip() or "."
    click.echo()

    # Include
    click.secho("  ▸ Include Patterns", fg="green", bold=True)
    click.echo("    Only scan files matching these globs. Leave empty to scan everything.")
    custom_include = click.prompt(
        click.style("    Include", fg="bright_white"), default=""
    ).strip()
    include = [p.strip() for p in custom_include.split(",") if p.strip()]
    click.echo()

    # Exclude
    click.secho("  ▸ Exclude Patterns", fg="green", bold=True)
    click.echo("    Skip files matching these globs during indexing and search.")
    defaults = ["tests/*", "test/*", "spec/*", "__tests__/*", "test_*", "*_test.*"]
    custom_exclude = click.prompt(
        click.style("    Exclude", fg="bright_white"),
        default=", ".join(defaults),
    ).strip()
    exclude = [p.strip() for p in custom_exclude.split(",") if p.strip()] if custom_exclude else defaults
    click.echo()

    # Extensions
    click.secho("  ▸ File Extensions", fg="green", bold=True)
    click.echo("    Which file types to index. Defaults cover most programming languages.")
    ext_defaults = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
                    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
                    ".kt", ".sql", ".sh", ".lua"]
    custom_ext = click.prompt(
        click.style("    Extensions", fg="bright_white"),
        default=", ".join(ext_defaults),
    ).strip()
    extensions = [p.strip() for p in custom_ext.split(",") if p.strip()] if custom_ext else ext_defaults
    click.echo()

    # Ignore dirs
    click.secho("  ▸ Ignored Directories", fg="green", bold=True)
    click.echo("    Directories to skip entirely (build artifacts, caches, dependencies).")
    ig_defaults = [".git", "__pycache__", "node_modules", ".venv", "venv",
                   ".tox", ".mypy_cache", ".pytest_cache", "dist", "build"]
    custom_ig = click.prompt(
        click.style("    Ignore", fg="bright_white"),
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
        click.secho("  Aborted.", fg="red")
