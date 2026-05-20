"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Parses download command-line arguments and calls the manual download runner.
"""

from __future__ import annotations

import argparse
import json

from workflow.core.tasks import resolve_task_json_inputs
from workflow.download.runner import download_tasks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manually download and unpack completed GROMACS tasks")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON metadata files: experiment.json, task_group.json, or hpc_submit_info.json",
    )
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="Keep remote task directories after downloading. By default, downloaded remote task directories are deleted.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_jsons = resolve_task_json_inputs(args.inputs)
    print(json.dumps(download_tasks(task_jsons, clean_remote=not args.keep_remote), indent=2))


if __name__ == "__main__":
    main()
