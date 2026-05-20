"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Provides a writable temporary directory helper for archives and GROMACS analysis scratch files.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def safe_temp_dir() -> Path:
    """Return a stable project-owned temp directory."""
    project_temp_dir = Path(__file__).resolve().parent.parent / ".cgflow_tmp"
    project_temp_dir.mkdir(parents=True, exist_ok=True)
    return project_temp_dir
