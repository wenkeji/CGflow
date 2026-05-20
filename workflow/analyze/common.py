"""Analyze workflow shared helpers.

CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

This module resolves task metadata, builds common analysis rows, runs shell
commands, and writes shared CSV outputs for ST and CMC analysis workflows.
"""

from __future__ import annotations

import csv
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from workflow.core.tasks import load_task_info, resolve_task_json_inputs
from workflow.core.tasks import resolve_metadata_input_path


DEFAULT_GMXRC = Path("/usr/local/gromacs/bin/GMXRC")


@dataclass
class AnalysisRow:
    scan: str
    group_name: str
    task_name: str
    bead_group: str = ""
    na_model: str = ""
    parameter_name: str = ""
    parameter_task_name: str = ""
    n_surf: str = ""
    sigma: str = ""
    epsilon: str = ""
    scale_factor: str = ""
    base_epsilon: str = ""
    value_1: str = ""
    value_2: str = ""
    value_3: str = ""
    value_4: str = ""
    task_dir: str = ""


def default_output_path(target: Path, scan: str) -> Path:
    raw_path = resolve_metadata_input_path(target)
    filename = "surface_tension_analysis.csv" if scan == "st" else "cmc_analysis.csv"
    return (raw_path.parent / filename).resolve()


def resolve_analysis_task_jsons(target: Path) -> list[Path]:
    return resolve_task_json_inputs([str(resolve_metadata_input_path(target))])


def analysis_task_dir(task_info: dict[str, object], task_json: Path) -> Path:
    local_workdir = task_info.get("local_workdir")
    if local_workdir:
        local_dir = Path(str(local_workdir))
        if local_dir.exists():
            return local_dir
    return task_json.parent


def task_records_for_scan(target: Path, scan: str) -> list[tuple[Path, dict[str, object]]]:
    records: list[tuple[Path, dict[str, object]]] = []
    for task_json in resolve_analysis_task_jsons(target):
        task_info = load_task_info(task_json)
        if task_scan(task_info) == scan:
            records.append((task_json, task_info))
    return records


def task_scan(task_info: dict[str, object]) -> str:
    task_type = str(task_info.get("task_type", ""))
    scan_type = str(task_info.get("scan_type", ""))
    group_name = str(task_info.get("group_name", ""))
    task_name = str(task_info.get("task_name", ""))
    if task_type == "cmc" or group_name.startswith("cmc_"):
        return "cmc"
    if scan_type in {"structure", "forcefield+structure"}:
        return "st"
    if "n_surf" in task_info or "surf_" in task_name or group_name.startswith("st_"):
        return "st"
    return ""


def row_from_task_info(task_info: dict[str, object], task_dir: Path, *, scan: str) -> AnalysisRow:
    def as_text(value: object) -> str:
        return "" if value is None else str(value)

    return AnalysisRow(
        scan=scan,
        group_name=as_text(task_info.get("group_name")),
        task_name=as_text(task_info.get("task_name")),
        bead_group=as_text(task_info.get("bead_group")),
        na_model=as_text(task_info.get("na_model")),
        parameter_name=as_text(task_info.get("parameter_name")),
        parameter_task_name=as_text(task_info.get("parameter_task_name")),
        n_surf=as_text(task_info.get("n_surf")),
        sigma=as_text(task_info.get("sigma")),
        epsilon=as_text(task_info.get("epsilon")),
        scale_factor=as_text(task_info.get("scale_factor")),
        base_epsilon=as_text(task_info.get("base_epsilon")),
        task_dir=str(task_dir),
    )


def run_bash(command: str, cwd: Path) -> str:
    try:
        completed = subprocess.run(["bash", "-lc", command], cwd=cwd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        raise RuntimeError(output.strip() or f"Command failed: {command}") from exc
    return completed.stdout + completed.stderr


def read_xvg_series(path: Path) -> list[tuple[float, float]]:
    if not path.exists():
        raise FileNotFoundError(f"XVG file not found: {path}")
    series: list[tuple[float, float]] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "@")):
            continue
        columns = line.split()
        if len(columns) >= 2:
            series.append((float(columns[0]), float(columns[1])))
    if not series:
        raise ValueError(f"No numeric data found in {path}")
    return series


def sort_key(row: AnalysisRow) -> tuple[str, str, float, float, str]:
    epsilon_match = re.search(r"_(\d+)p(\d+)$", row.parameter_task_name)
    surf_match = re.search(r"surf_(\d+)$", row.task_name)
    epsilon = float(row.epsilon) if row.epsilon else (
        float(f"{epsilon_match.group(1)}.{epsilon_match.group(2)}") if epsilon_match else float("-inf")
    )
    n_surf = float(row.n_surf) if row.n_surf else (float(surf_match.group(1)) if surf_match else float("-inf"))
    return (row.bead_group, row.parameter_task_name, epsilon, n_surf, row.task_name)


def print_summary(output_paths: list[Path], total: int, ok: int) -> None:
    print(f"output_csv: {', '.join(str(path) for path in output_paths)}")
    print(f"tasks_total: {total}")
    print(f"tasks_ok: {ok}")
    print(f"tasks_failed: {total - ok}")


def write_csv(path: Path, rows: list[AnalysisRow], header: list[str], row_builder) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row_builder(row))
    return path
