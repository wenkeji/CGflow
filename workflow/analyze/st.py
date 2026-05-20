"""Surface-tension analysis workflow.

CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

This module extracts surface-tension energy terms from downloaded ST tasks and
writes both experiment-level and parameter-level CSV summaries.
"""

from __future__ import annotations

import re
import shlex
import tempfile
from pathlib import Path

from workflow.analyze.common import AnalysisRow, analysis_task_dir, default_output_path, print_summary
from workflow.analyze.common import row_from_task_info, run_bash, sort_key, task_records_for_scan, write_csv
from workflow.core.temp import safe_temp_dir


SURFACE_TENSION_TERM = "#Surf*SurfTen"
SURFACE_TENSION_FACTOR = 0.05


def extract_st_from_analyze(output: str) -> tuple[float, float]:
    st_match = re.search(r"^SS1\s+([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)", output, re.MULTILINE)
    ee_match = re.search(r"err\.est\.\s+([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)", output)
    if st_match is None:
        raise ValueError("Could not parse `SS1` from `gmx analyze -ee` output")
    if ee_match is None:
        raise ValueError("Could not parse `err.est.` from `gmx analyze -ee` output")
    return float(st_match.group(1)) * SURFACE_TENSION_FACTOR, float(ee_match.group(1)) * SURFACE_TENSION_FACTOR


def calc_st(edr: Path, *, begin: float, gmxrc: Path) -> tuple[float, float]:
    if not edr.exists():
        raise FileNotFoundError(f"Energy file not found: {edr}")
    if not gmxrc.exists():
        raise FileNotFoundError(f"GMXRC not found: {gmxrc}")

    with tempfile.TemporaryDirectory(dir=safe_temp_dir(), prefix="surface_tension_") as tmp:
        tmpdir = Path(tmp)
        run_bash(
            (
                f"source {shlex.quote(str(gmxrc))} && "
                f"printf '%s\\n' {shlex.quote(SURFACE_TENSION_TERM)} | "
                f"gmx energy -f {shlex.quote(str(edr))} -b {begin}"
            ),
            cwd=tmpdir,
        )
        output = run_bash(f"source {shlex.quote(str(gmxrc))} && gmx analyze -f energy.xvg -ee", cwd=tmpdir)
    return extract_st_from_analyze(output)


def st_task_record(task_json: Path, task_info: dict[str, object], *, edr_name: str, begin: float, gmxrc: Path) -> AnalysisRow | None:
    task_dir = analysis_task_dir(task_info, task_json)
    try:
        st, ee = calc_st(task_dir / edr_name, begin=begin, gmxrc=gmxrc)
    except Exception:
        return None
    row = row_from_task_info(task_info, task_dir, scan="st")
    row.value_1 = f"{st:.6f}"
    row.value_2 = f"{ee:.6f}"
    return row


def write_st_csv(path: Path, rows: list[AnalysisRow]) -> Path:
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
            "n_surf",
            "sigma",
            "epsilon",
            "scale_factor",
            "base_epsilon",
            "st_mN_m",
            "ee_mN_m",
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
            row.n_surf,
            row.sigma,
            row.epsilon,
            row.scale_factor,
            row.base_epsilon,
            row.value_1,
            row.value_2,
            row.task_dir,
        ],
    )


def coupled_output_paths(rows: list[AnalysisRow]) -> list[tuple[Path, list[AnalysisRow]]]:
    grouped: dict[tuple[str, str], list[AnalysisRow]] = {}
    for row in rows:
        grouped.setdefault((row.bead_group, row.parameter_task_name), []).append(row)

    outputs: list[tuple[Path, list[AnalysisRow]]] = []
    for (_, parameter_task_name), parameter_rows in sorted(grouped.items()):
        if not parameter_task_name:
            continue
        parameter_rows.sort(key=sort_key)
        outputs.append((Path(parameter_rows[0].task_dir).parent / "surface_tension_analysis.csv", parameter_rows))
    return outputs


def analyze_st(target: Path, *, edr_name: str, begin: float, gmxrc: Path) -> None:
    task_records = task_records_for_scan(target, "st")
    rows = [
        row
        for task_json, task_info in task_records
        if (row := st_task_record(task_json, task_info, edr_name=edr_name, begin=begin, gmxrc=gmxrc)) is not None
    ]
    if not rows:
        output_path = default_output_path(target, "st")
        write_st_csv(output_path, [])
        print_summary([output_path], total=len(task_records), ok=0)
        return

    rows.sort(key=sort_key)
    output_path = default_output_path(target, "st")
    write_st_csv(output_path, rows)
    output_paths = [output_path]
    for parameter_output_path, parameter_rows in coupled_output_paths(rows):
        write_st_csv(parameter_output_path, parameter_rows)
        output_paths.append(parameter_output_path)
    print_summary(output_paths, total=len(task_records), ok=len(rows))
