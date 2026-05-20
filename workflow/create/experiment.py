"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Builds JSON-configured experiments, including ST/CMC task manifests.
"""

from __future__ import annotations

import json
from pathlib import Path

from workflow.core.tasks import BEAD_GROUPS, DEFAULT_NA_MODEL, EXPERIMENT_INFO_NAME, GROUP_INFO_NAME, TASK_INFO_NAME
from workflow.core.tasks import CmcTaskGroupBuilder, SurfaceTensionTaskGroupBuilder, bead_group_dir
from workflow.create.forcefield import all_forcefield_overrides


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GROUP_ROOT = Path.cwd()


def manifest_record(group_info: dict[str, object], scan: str, bead_group: str) -> dict[str, object]:
    group_dir = Path(str(group_info["group_dir"]))
    record = {
        "scan": scan,
        "bead_group": bead_group,
        "group_name": group_info["group_name"],
        "group_dir": str(group_dir),
    }
    group_json = group_dir / GROUP_INFO_NAME
    task_json = group_dir / TASK_INFO_NAME
    if group_json.exists():
        record["group_json"] = str(group_json)
    elif task_json.exists():
        record["task_json"] = str(task_json)
    return record


def create_configured_experiment(args) -> dict[str, object]:
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Current directory: {Path.cwd()}\n"
            "Use `create --config /full/path/to/input.json`, or run `create --config input.json` "
            "from the directory that contains input.json."
        )
    config = json.loads(config_path.read_text())

    na_model = str(config.get("na_model", DEFAULT_NA_MODEL))
    bead_groups = list(config.get("bead_groups", config.get("beads", ["regular"])))
    if bead_groups == ["all"]:
        bead_groups = list(BEAD_GROUPS)
    bead_groups = [str(bead_group) for bead_group in bead_groups]
    for bead_group in bead_groups:
        bead_group_dir(PROJECT_ROOT, bead_group, na_model)

    scans = [str(scan) for scan in config.get("scans", ["st", "cmc"])]
    experiment_dir = (args.output_root / args.group_name).resolve() if args.group_name else args.output_root.resolve()
    experiment_name = args.group_name or str(config.get("name", experiment_dir.name))
    experiment_dir.mkdir(parents=True, exist_ok=True)

    raw_forcefield = config.get("forcefield")
    has_forcefield_scan = bool(raw_forcefield)
    st_config = dict(config.get("st", {}))
    cmc_config = dict(config.get("cmc", {}))
    st_enabled = "st" in scans and st_config.get("enabled", True)
    cmc_enabled = "cmc" in scans and cmc_config.get("enabled", True)
    if st_enabled and "n_surfs" not in st_config:
        raise ValueError("Configured ST scans require `st.n_surfs`; no coupled-scan default is used.")
    n_surfs = [int(value) for value in st_config.get("n_surfs", [])]

    group_records: list[dict[str, object]] = []
    task_records: list[dict[str, object]] = []
    results: list[dict[str, object]] = []

    for bead_group in bead_groups:
        if st_enabled:
            group_name = f"st_{bead_group}"
            if has_forcefield_scan:
                st_source_top = bead_group_dir(PROJECT_ROOT, bead_group, na_model) / "st" / "sys.top"
                overrides = all_forcefield_overrides(source_top=st_source_top, raw_forcefield=raw_forcefield, bead_group=bead_group)
                group_info = SurfaceTensionTaskGroupBuilder.parameter_scan_from_repo(
                    repo_root=PROJECT_ROOT,
                    group_dir=experiment_dir / group_name,
                    group_name=group_name,
                    bead_group=bead_group,
                    na_model=na_model,
                    n_surfs=n_surfs,
                    nonbond_overrides=overrides,
                ).prepare()
            else:
                group_info = SurfaceTensionTaskGroupBuilder.structure_scan_from_repo(
                    repo_root=PROJECT_ROOT,
                    group_dir=experiment_dir / group_name,
                    group_name=group_name,
                    bead_group=bead_group,
                    na_model=na_model,
                    n_surfs=n_surfs,
                ).prepare()
            results.append(group_info)
            group_records.append(manifest_record(group_info, "st", bead_group))

        if cmc_enabled:
            if has_forcefield_scan:
                cmc_source_top = bead_group_dir(PROJECT_ROOT, bead_group, na_model) / "cmc" / "sys.top"
                cmc_overrides = all_forcefield_overrides(source_top=cmc_source_top, raw_forcefield=raw_forcefield, bead_group=bead_group)
                for override in cmc_overrides:
                    task_name = override.label or "forcefield"
                    group_name = f"cmc_{bead_group}_{task_name}"
                    group_info = CmcTaskGroupBuilder.parameter_from_repo(
                        repo_root=PROJECT_ROOT,
                        group_dir=experiment_dir / f"cmc_{bead_group}" / task_name,
                        group_name=group_name,
                        bead_group=bead_group,
                        na_model=na_model,
                        nonbond_override=override,
                    ).prepare()
                    results.append(group_info)
                    task_records.append(manifest_record(group_info, "cmc", bead_group))
            else:
                group_name = f"cmc_{bead_group}"
                group_info = CmcTaskGroupBuilder.from_repo(
                    repo_root=PROJECT_ROOT,
                    group_dir=experiment_dir / group_name,
                    group_name=group_name,
                    bead_group=bead_group,
                    na_model=na_model,
                ).prepare()
                results.append(group_info)
                task_records.append(manifest_record(group_info, "cmc", bead_group))

    experiment_info = {
        "experiment_name": experiment_name,
        "experiment_dir": str(experiment_dir),
        "config_json": str(config_path),
        "na_model": na_model,
        "bead_groups": bead_groups,
        "scans": [scan for scan, enabled in (("st", st_enabled), ("cmc", cmc_enabled)) if enabled],
        "forcefield": raw_forcefield or {},
        "st": {"n_surfs": n_surfs, "enabled": st_enabled},
        "cmc": {"enabled": cmc_enabled},
        "groups": group_records,
        "tasks": task_records,
    }
    (experiment_dir / EXPERIMENT_INFO_NAME).write_text(json.dumps(experiment_info, indent=2))
    return {**experiment_info, "experiment_json": str(experiment_dir / EXPERIMENT_INFO_NAME), "created": results}


def create_from_args(args) -> dict[str, object]:
    return create_configured_experiment(args)
