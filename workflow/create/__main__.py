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

from workflow.core.tasks import BEAD_GROUPS, DEFAULT_NA_MODEL, NA_MODELS
from workflow.create.experiment import DEFAULT_GROUP_ROOT, create_from_args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create local GROMACS task groups")
    parser.add_argument(
        "--scan",
        choices=["st", "cmc", "all"],
        default="st",
        help="`st` creates surface-tension tasks, `cmc` creates CMC tasks, `all` creates both.",
    )
    parser.add_argument(
        "--bead",
        choices=[*BEAD_GROUPS, "all"],
        default="regular",
        help="Bead input set to use. Use `all` to create regular, small, and tini groups.",
    )
    parser.add_argument("--na", choices=NA_MODELS, default=DEFAULT_NA_MODEL, help="Na bead model input set to use.")
    parser.add_argument("--d", dest="group_name", default=None, help="Output directory name.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_GROUP_ROOT, help="Parent directory for the task group.")
    parser.add_argument("--config", type=Path, default=None, help="JSON experiment config. Overrides --scan/--bead defaults.")
    return parser.parse_args()


def main() -> None:
    print(json.dumps(create_from_args(parse_args()), indent=2))


if __name__ == "__main__":
    main()
