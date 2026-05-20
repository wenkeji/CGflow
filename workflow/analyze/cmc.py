"""CMC analysis workflow.

CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

This module runs the GROMACS cluster-size workflow for CMC tasks and writes CMC
summary CSV files.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from workflow.analyze.common import AnalysisRow, analysis_task_dir, default_output_path, print_summary
from workflow.analyze.common import read_xvg_series, row_from_task_info, run_bash, sort_key, task_records_for_scan, write_csv


CMC_CUT = 0.8
CMC_INDEX_SOURCE_GROUP = 2
CMC_INDEX_GROUP_NAME = "surf"


def calc_cmc(task_dir: Path, *, gmxrc: Path) -> tuple[float, float, float, float]:
    eq_tpr = task_dir / "eq.tpr"
    eq_trr = task_dir / "eq.trr"
    for required in [eq_tpr, eq_trr]:
        if not required.exists():
            raise FileNotFoundError(f"Required CMC input file not found: {required}")
    if not gmxrc.exists():
        raise FileNotFoundError(f"GMXRC not found: {gmxrc}")

    run_bash(
        (
            f"source {shlex.quote(str(gmxrc))} && "
            f"printf '{CMC_INDEX_SOURCE_GROUP}\\nname 5 {CMC_INDEX_GROUP_NAME}\\nq\\n' | "
            f"gmx make_ndx -f {shlex.quote(str(eq_tpr))} -o index.ndx"
        ),
        cwd=task_dir,
    )
    run_bash(
        (
            f"source {shlex.quote(str(gmxrc))} && "
            f"printf '%s\\n' {shlex.quote(CMC_INDEX_GROUP_NAME)} | "
            f"gmx clustsize -f {shlex.quote(str(eq_trr))} -s {shlex.quote(str(eq_tpr))} "
            f"-n index.ndx -cut {CMC_CUT} -mc maxclust.xvg -nc nclust.xvg"
        ),
        cwd=task_dir,
    )

    maxclust = read_xvg_series(task_dir / "maxclust.xvg")
    nclust = read_xvg_series(task_dir / "nclust.xvg")
    avg_maxclust = sum(value for _, value in maxclust) / len(maxclust)
    final_maxclust = maxclust[-1][1]
    avg_nclust = sum(value for _, value in nclust) / len(nclust)
    final_nclust = nclust[-1][1]
    return avg_maxclust, final_maxclust, avg_nclust, final_nclust


def cmc_task_record(task_json: Path, task_info: dict[str, object], *, gmxrc: Path) -> AnalysisRow | None:
    task_dir = analysis_task_dir(task_info, task_json)
    try:
        avg_maxclust, final_maxclust, avg_nclust, final_nclust = calc_cmc(task_dir, gmxrc=gmxrc)
    except Exception:
        return None

    row = row_from_task_info(task_info, task_dir, scan="cmc")
    row.value_1 = f"{avg_maxclust:.6f}"
    row.value_2 = f"{final_maxclust:.6f}"
    row.value_3 = f"{avg_nclust:.6f}"
    row.value_4 = f"{final_nclust:.6f}"
    return row


def write_cmc_csv(path: Path, rows: list[AnalysisRow]) -> Path:
    return write_csv(
        path,
        rows,
        [
            "scan",
            "bead_group",
            "na_model",
            "group_name",
            "task_name",
            "parameter_name",
            "parameter_task_name",
            "sigma",
            "epsilon",
            "scale_factor",
            "base_epsilon",
            "avg_maxclust",
            "final_maxclust",
            "avg_nclust",
            "final_nclust",
            "task_dir",
        ],
        lambda row: [
            row.scan,
            row.bead_group,
            row.na_model,
            row.group_name,
            row.task_name,
            row.parameter_name,
            row.parameter_task_name,
            row.sigma,
            row.epsilon,
            row.scale_factor,
            row.base_epsilon,
            row.value_1,
            row.value_2,
            row.value_3,
            row.value_4,
            row.task_dir,
        ],
    )


def print_cmc_summary(task_dir: Path) -> None:
    print(f"task_dir: {task_dir}")
    print(f"index_file: {task_dir / 'index.ndx'}")
    print(f"maxclust_file: {task_dir / 'maxclust.xvg'}")
    print(f"nclust_file: {task_dir / 'nclust.xvg'}")
    print(f"cut: {CMC_CUT:.1f}")


def analyze_cmc(target: Path, *, gmxrc: Path) -> None:
    task_records = task_records_for_scan(target, "cmc")
    rows = [
        row
        for task_json, task_info in task_records
        if (row := cmc_task_record(task_json, task_info, gmxrc=gmxrc)) is not None
    ]
    rows.sort(key=sort_key)
    output_path = default_output_path(target, "cmc")
    write_cmc_csv(output_path, rows)
    print_summary([output_path], total=len(task_records), ok=len(rows))
    if len(rows) == 1:
        print_cmc_summary(Path(rows[0].task_dir))
