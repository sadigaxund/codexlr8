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
        "exclude": [
            "tests/",
            "test/",
            "spec/",
            "__tests__/",
            "test_*",
            "*_test.*",
        ],
    }
