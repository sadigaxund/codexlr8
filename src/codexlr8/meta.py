""".meta.yaml sidecar reading, writing, and generation."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import yaml

from .scanner import scan_project

META_EXTENSION = ".meta.yaml"


def meta_path_for(filepath: str) -> str:
    """Return the .meta.yaml sidecar path for a given source file path."""
    return filepath + META_EXTENSION


def source_path_for(meta_path: str) -> str:
    """Return the source file path for a given .meta.yaml sidecar path."""
    assert meta_path.endswith(META_EXTENSION)
    return meta_path[: -len(META_EXTENSION)]


def read_meta(meta_path: str) -> dict | None:
    """Read a .meta.yaml file, returning parsed dict or None."""
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_meta(meta_path: str, data: dict) -> None:
    """Write a .meta.yaml file."""
    with open(meta_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_auto_fields(filepath: str, symbols: list[dict], existing_meta: dict | None = None) -> dict:
    """Generate auto-populated fields for a source file.

    Returns a dict with auto fields filled in, preserving any curated fields
    from existing_meta.
    """
    result: dict = {}

    # Preserve curated fields if they exist
    if existing_meta:
        for key in ("summary", "tags", "invariants", "examples"):
            if key in existing_meta:
                result[key] = existing_meta[key]

    # Auto-generate public API
    result["public_api"] = [
        s["name"] for s in symbols
        if s["kind"] in ("function", "async_function", "class")
    ]

    # Dependencies will be filled in by the indexer (needs cross-file analysis)
    # Start with a placeholder that the indexer will update
    result["dependencies"] = existing_meta.get("dependencies", []) if existing_meta else []
    result["used_by"] = existing_meta.get("used_by", []) if existing_meta else []

    result["last_modified"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return result


def generate_missing_sidecars(project_path: str) -> list[str]:
    """Scan project and create .meta.yaml files for any source files that lack them.

    Returns list of created meta file paths (relative to project root).
    """
    symbols_data = scan_project(project_path)
    created = []

    for entry in symbols_data:
        filepath = os.path.join(project_path, entry["path"])
        meta_path = meta_path_for(filepath)

        if os.path.exists(meta_path):
            continue

        meta_data = generate_auto_fields(filepath, entry["symbols"])
        write_meta(meta_path, meta_data)
        created.append(entry["path"] + META_EXTENSION)

    return created


def validate_meta(meta_path: str, symbols: list[dict]) -> list[str]:
    """Validate a .meta.yaml against actual source symbols.

    Returns list of warning strings (empty if valid).
    """
    warnings = []
    meta = read_meta(meta_path)
    if meta is None:
        return ["No .meta.yaml found"]

    public_api = set(meta.get("public_api", []))
    actual_symbols = {
        s["name"] for s in symbols
        if s["kind"] in ("function", "async_function", "class")
    }

    missing = public_api - actual_symbols
    if missing:
        warnings.append(f"public_api lists symbols not found in source: {', '.join(sorted(missing))}")

    return warnings
