"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Defines the HPC connection and job path configuration dataclasses used by the workflow layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class HPCConfig:
    """Connection settings plus a few workflow defaults."""

    server: str = "cumulus.int.pg.com"
    user: str = "fi2928"
    port: int = 22
    password: str | None = None
    keyfile: str | None = None
    remote_root: str = "/home/cadmol/fi2928"
    task_group_prefix: str = "job"
    poll_interval: int = 10
    timeout: int = 300
    is_debug: bool = False


@dataclass
class JobPaths:
    """Resolved paths for one submitted job."""

    local_workdir: Path
    remote_root: str
    task_group_name: str
    results_dir_name: str

    @property
    def remote_task_dir(self) -> str:
        return f"{self.remote_root.rstrip('/')}/{self.task_group_name}"
