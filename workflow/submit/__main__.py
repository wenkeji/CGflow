"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Parses submit command-line arguments and calls the submission runner.
"""

from __future__ import annotations

import argparse
import json

from workflow.core.tasks import resolve_task_json_inputs
from workflow.submit.runner import submit_tasks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit one or more prepared GROMACS tasks")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON metadata files: experiment.json, task_group.json, or hpc_submit_info.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps({"submitted": submit_tasks(resolve_task_json_inputs(args.inputs))}, indent=2))


if __name__ == "__main__":
    main()
