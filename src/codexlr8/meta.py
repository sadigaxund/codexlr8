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


def generate_meta_skeleton(existing_meta: dict | None = None) -> dict:
    """Generate a fresh .meta.yaml skeleton, preserving curated fields.

    Auto fields are empty — they can be populated by agents over time.
    Curated fields (summary, tags, invariants, examples) are preserved
    from existing_meta if provided.
    """
    result: dict = {
        "public_api": [],
        "dependencies": [],
        "used_by": [],
        "last_modified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if existing_meta:
        for key in ("summary", "tags", "invariants", "examples"):
            if key in existing_meta:
                result[key] = existing_meta[key]

    return result


def generate_missing_sidecars(project_path: str) -> list[str]:
    """Scan project and create .meta.yaml files for any source files that lack them.

    Returns list of created meta file paths (relative to project root).
    """
    files_data = scan_project(project_path)
    created = []

    for entry in files_data:
        filepath = os.path.join(project_path, entry["path"])
        meta_path = meta_path_for(filepath)

        if os.path.exists(meta_path):
            continue

        meta_data = generate_meta_skeleton()
        write_meta(meta_path, meta_data)
        created.append(entry["path"] + META_EXTENSION)

    return created


def validate_meta(meta_path: str) -> list[str]:
    """Validate a .meta.yaml file structure.

    Returns list of warning strings (empty if valid).
    Checks: file exists, is valid YAML, required keys present.
    """
    warnings = []

    if not os.path.exists(meta_path):
        return ["No .meta.yaml found"]

    try:
        meta = read_meta(meta_path)
    except Exception:
        return [f"Failed to parse {meta_path}"]

    if meta is None:
        return ["Empty or invalid .meta.yaml"]

    # Check auto fields exist
    for key in ("public_api", "dependencies", "used_by"):
        if key not in meta:
            warnings.append(f"Missing required field: '{key}'")
        elif not isinstance(meta[key], list):
            warnings.append(f"Field '{key}' must be a list")

    return warnings
