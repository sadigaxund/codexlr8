"""CodeXLR8 CLI — search-first codebase navigation for agents."""

import click

from .scanner import scan_project
from .meta import generate_missing_sidecars
from .search import SearchEngine


@click.group()
def main():
    """CodeXLR8 — a codebase search engine for LLM coding agents."""


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.option("--output", "-o", default=None, help="Write symbol data to JSON file")
def scan(project_path: str, output: str | None):
    """Scan a project and extract code symbols with docstrings.

    PROJECT_PATH is the root directory of the codebase to scan.
    """
    results = scan_project(project_path)
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
@click.option("--include-tests", is_flag=True, default=False, help="Do not penalize test files")
@click.option("--format", "-f", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--limit", "-n", default=10, help="Maximum number of results")
def search(project_path: str, query: str, include_tests: bool, output_format: str, limit: int):
    """Search the codebase for symbols and metadata matching QUERY.

    PROJECT_PATH is the root directory of the codebase to search.
    """
    engine = SearchEngine(project_path)
    results = engine.search(query, include_tests=include_tests, limit=limit)

    if output_format == "json":
        import json
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"{i}. {r['path']}:{r['line_start']}-{r['line_end']}  [score: {r['score']:.2f}]")
        if r.get("summary"):
            click.echo(f"   meta:   {r['summary']}")
        if r.get("tags"):
            click.echo(f"   tags:   {', '.join(r['tags'])}")
        if r.get("preview"):
            click.echo(f"   preview: |")
            for line in r["preview"].strip().splitlines()[:6]:
                click.echo(f"     {line}")
        click.echo()


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
def index(project_path: str):
    """Build the full search index for a project."""
    engine = SearchEngine(project_path)
    count = engine.build_index()
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
