"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Builds the shared HPC configuration used by submit, check, and download workflows.
"""

from __future__ import annotations


def build_hpc_config():
    try:
        from hpc.config import HPCConfig
    except ModuleNotFoundError as exc:
        if exc.name == "paramiko":
            raise ModuleNotFoundError(
                "Remote HPC workflows require the `paramiko` package in this Python environment."
            ) from exc
        raise

    return HPCConfig(
        server="cumulus.int.pg.com",
        user="fi2928",
        password=None,
        keyfile=None,
        remote_root="/home/cadmol/fi2928",
    )
