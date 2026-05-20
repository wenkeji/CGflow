"""Analyze command-line entry.

CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

This entry parses analysis CLI arguments and dispatches to the separate ST or
CMC analysis modules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from workflow.analyze.cmc import analyze_cmc
from workflow.analyze.common import DEFAULT_GMXRC, resolve_analysis_task_jsons, task_scan
from workflow.analyze.st import analyze_st
from workflow.core.tasks import load_task_info


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze tasks from experiment, group, or task metadata JSON")
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="JSON metadata files: experiment.json, task_group.json, or hpc_submit_info.json",
    )
    parser.add_argument("--edr", default="eq.edr", help="Energy file name inside each task directory")
    parser.add_argument(
        "--begin",
        type=float,
        default=10000.0,
        help="Start time passed to `gmx energy -b` in ps; default keeps the last 90 ns of a 100 ns run",
    )
    parser.add_argument("--gmxrc", type=Path, default=DEFAULT_GMXRC, help="Path to GMXRC")
    return parser.parse_args()


def detect_scans(target: Path) -> list[str]:
    scans = {task_scan(load_task_info(task_json)) for task_json in resolve_analysis_task_jsons(target)}
    ordered = [scan for scan in ("st", "cmc") if scan in scans]
    if not ordered:
        raise ValueError(f"Could not detect ST or CMC tasks in {target}")
    return ordered


def analyze_target(target: Path, *, edr_name: str, begin: float, gmxrc: Path) -> None:
    for scan in detect_scans(target):
        if scan == "cmc":
            analyze_cmc(target, gmxrc=gmxrc)
        else:
            analyze_st(target, edr_name=edr_name, begin=begin, gmxrc=gmxrc)


def main() -> None:
    args = parse_args()
    gmxrc = args.gmxrc.resolve()
    for target in args.inputs:
        analyze_target(target.expanduser(), edr_name=args.edr, begin=args.begin, gmxrc=gmxrc)


if __name__ == "__main__":
    main()
