"""Centralized path resolution for the RAG pipeline."""

from __future__ import annotations

import os
from pathlib import Path


def _find_project_root() -> Path:
    """Discover project root: env var > walk up to pyproject.toml > fallback."""
    env = os.getenv("MANUAL_SIH_ROOT")
    if env:
        return Path(env)

    # Walk up from this file to find pyproject.toml
    cur = Path(__file__).resolve().parent
    for _ in range(10):
        if (cur / "pyproject.toml").exists():
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent

    # Fallback: assume src/manual_sih_rag/rag/ -> 3 levels up
    return Path(__file__).resolve().parent.parent.parent.parent


PROJECT_ROOT = _find_project_root()
DB_DIR = PROJECT_ROOT / "db"
DATA_DIR = PROJECT_ROOT / "data"
