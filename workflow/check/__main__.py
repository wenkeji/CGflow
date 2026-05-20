"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Parses check command-line arguments and prints simplified remote task statuses.
"""

from __future__ import annotations

import argparse
import json

from workflow.check.status import collect_task_statuses, summarize_statuses
from workflow.core.tasks import resolve_task_json_inputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check tasks listed by JSON metadata files")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON metadata files: experiment.json, task_group.json, or hpc_submit_info.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_jsons = resolve_task_json_inputs(args.inputs)
    print(json.dumps(summarize_statuses(collect_task_statuses(task_jsons)), indent=2))


if __name__ == "__main__":
    main()
