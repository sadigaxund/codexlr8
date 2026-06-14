"""Project configuration via .codexlr8.yaml."""

from __future__ import annotations

import os

import yaml

CONFIG_FILE = ".codexlr8.yaml"


def load_config(project_path: str) -> dict:
    """Load project configuration from .codexlr8.yaml if present."""
    config_path = os.path.join(project_path, CONFIG_FILE)
    if not os.path.exists(config_path):
        return _defaults()
    with open(config_path, "r", encoding="utf-8") as f:
        user_config = yaml.safe_load(f) or {}
    defaults = _defaults()
    defaults.update(user_config)
    return defaults


def _defaults() -> dict:
    return {
        "root": ".",
        "fuzzy": True,
        "embeddings": {
            "enabled": False,
            "model": "all-MiniLM-L6-v2",
            "bm25_weight": 0.6,
        },
        "include": [],
        "exclude": [
            "tests/*",
            "test/*",
            "spec/*",
            "__tests__/*",
            "test_*",
            "*_test.*",
            "examples/*",
            "docs/*",
            "tutorials/*",
            "benchmarks/*",
        ],
        "extensions": [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
            ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".hh",
            ".cs", ".swift", ".kt", ".kts", ".scala", ".sh", ".bash",
            ".sql", ".r", ".lua", ".pl", ".pm",
        ],
        "ignore_dirs": [
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
            "dist", "build", ".eggs", "*.egg-info",
        ],
    }
