"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Builds default and JSON-configured experiments, including ST/CMC task manifests.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from workflow.core.tasks import BEAD_GROUPS, DEFAULT_NA_MODEL, EXPERIMENT_INFO_NAME, GROUP_INFO_NAME, TASK_INFO_NAME
from workflow.core.tasks import CmcTaskGroupBuilder, SurfaceTensionTaskGroupBuilder, bead_group_dir
from workflow.create.forcefield import all_forcefield_overrides


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GROUP_ROOT = Path.cwd()


def resolve_scan_mode(scan: str) -> str:
    if scan == "cmc":
        return "cmc"
    if scan == "st":
        return "structure"
    raise ValueError("`--scan` only supports `st` or `cmc`")


def scan_prefix(scan: str) -> str:
    return "cmc" if resolve_scan_mode(scan) == "cmc" else "st"


def default_experiment_name(na_model: str = DEFAULT_NA_MODEL) -> str:
    return f"{na_model}_{time.strftime('%Y%m%d_%H%M%S')}"


def default_group_name(scan: str, bead_group: str) -> str:
    return f"{scan_prefix(scan)}_{bead_group}_{time.strftime('%Y%m%d_%H%M%S')}"


def group_names(base_name: str | None, scan: str, bead_groups: list[str]) -> dict[str, str]:
    if base_name is None:
        return {bead_group: default_group_name(scan, bead_group) for bead_group in bead_groups}
    if len(bead_groups) == 1:
        return {bead_groups[0]: base_name}
    return {bead_group: f"{base_name}_{bead_group}" for bead_group in bead_groups}


def resolve_bead_groups(raw: str) -> list[str]:
    if raw == "all":
        return list(BEAD_GROUPS)
    if raw not in BEAD_GROUPS:
        raise ValueError(f"`--bead` only supports {', '.join(BEAD_GROUPS)} or all")
    return [raw]


def build_builder(args, group_dir: Path, group_name: str, bead_group: str, scan: str | None = None):
    scan_mode = resolve_scan_mode(scan or args.scan)
    builder_kwargs = {
        "repo_root": PROJECT_ROOT,
        "group_dir": group_dir,
        "group_name": group_name,
        "bead_group": bead_group,
        "na_model": args.na,
    }
    bead_group_dir(PROJECT_ROOT, bead_group, args.na)
    if scan_mode == "cmc":
        return CmcTaskGroupBuilder.from_repo(**builder_kwargs)
    return SurfaceTensionTaskGroupBuilder.structure_scan_from_repo(**builder_kwargs)


def manifest_record(group_info: dict[str, object], scan: str, bead_group: str) -> dict[str, object]:
    group_dir = Path(str(group_info["group_dir"]))
    record = {
        "scan": scan_prefix(scan),
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


def create_single_scan(args) -> dict[str, object]:
    scan = resolve_scan_mode(args.scan)
    bead_groups = resolve_bead_groups(args.bead)
    names = group_names(args.group_name, scan, bead_groups)
    results = []
    for bead_group in bead_groups:
        group_name = names[bead_group]
        group_dir = (args.output_root / group_name).resolve()
        results.append(build_builder(args, group_dir, group_name, bead_group).prepare())
    return results[0] if len(results) == 1 else {"groups": results}


def create_default_experiment(args) -> dict[str, object]:
    bead_groups = resolve_bead_groups(args.bead)
    experiment_name = args.group_name or default_experiment_name(args.na)
    experiment_dir = (args.output_root / experiment_name).resolve()
    experiment_dir.mkdir(parents=True, exist_ok=True)

    group_records: list[dict[str, object]] = []
    task_records: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    for scan in ("st", "cmc"):
        for bead_group in bead_groups:
            group_name = f"{scan_prefix(scan)}_{bead_group}"
            group_info = build_builder(args, experiment_dir / group_name, group_name, bead_group, scan=scan).prepare()
            results.append(group_info)
            record = manifest_record(group_info, scan, bead_group)
            if "group_json" in record:
                group_records.append(record)
            elif "task_json" in record:
                task_records.append(record)

    experiment_info = {
        "experiment_name": experiment_name,
        "experiment_dir": str(experiment_dir),
        "na_model": args.na,
        "bead_groups": bead_groups,
        "scans": ["st", "cmc"],
        "groups": group_records,
        "tasks": task_records,
    }
    (experiment_dir / EXPERIMENT_INFO_NAME).write_text(json.dumps(experiment_info, indent=2))
    return {**experiment_info, "experiment_json": str(experiment_dir / EXPERIMENT_INFO_NAME), "created": results}


def create_configured_experiment(args) -> dict[str, object]:
    if args.config is None:
        raise ValueError("Config path is required")
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Current directory: {Path.cwd()}\n"
            "Use `create --config /full/path/to/input.json`, or run `create --config input.json` "
            "from the directory that contains input.json."
        )
    config = json.loads(config_path.read_text())

    na_model = str(config.get("na_model", args.na))
    bead_groups = list(config.get("bead_groups", config.get("beads", [args.bead])))
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
    if args.config is not None:
        return create_configured_experiment(args)
    if args.scan == "all":
        return create_default_experiment(args)
    return create_single_scan(args)
