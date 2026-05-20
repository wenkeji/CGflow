"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Parses the create command-line arguments and dispatches to the experiment creation functions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflow.create.experiment import DEFAULT_GROUP_ROOT, create_from_args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create local GROMACS tasks from a JSON experiment config")
    parser.add_argument("--config", type=Path, required=True, help="JSON experiment config file.")
    parser.add_argument("--d", dest="group_name", default=None, help="Optional output directory name under --output-root.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_GROUP_ROOT, help="Parent directory for the experiment.")
    return parser.parse_args()


def main() -> None:
    print(json.dumps(create_from_args(parse_args()), indent=2))


if __name__ == "__main__":
    main()
