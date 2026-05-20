"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Groups prepared task metadata, archives complete task groups, uploads them, and submits jobs with bsub.
"""

from __future__ import annotations

import shlex
import tarfile
import tempfile
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from workflow.common import build_hpc_config
from workflow.core.tasks import (
    experiment_dir_for_task_json,
    group_dir_for_task_json,
    group_info_path,
    has_group_info,
    list_group_task_jsons,
    load_task_info,
    prepare_group_submit_scripts,
    relative_task_dir_for_remote,
    submit_preuploaded_task,
    submit_task,
)
from workflow.core.temp import safe_temp_dir


@dataclass(frozen=True)
class SubmitGroup:
    experiment_dir: Path
    group_dir: Path
    group_name: str
    task_jsons: list[Path]
    is_group_task: bool
    is_complete: bool


def _group_archive_name(group_name: str) -> str:
    return f"{group_name}.tar.gz"


def _archive_group(group_dir: Path) -> Path:
    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"{group_dir.name}_",
        suffix=".tar.gz",
        delete=False,
        dir=safe_temp_dir(),
    )
    archive_path = Path(temp_file.name)
    temp_file.close()
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(group_dir, arcname=group_dir.name)
    return archive_path


def _submission_record(task_info: dict[str, object], task_json: Path) -> dict[str, object]:
    return {
        "task_json": str(task_json),
        "task_name": task_info["task_name"],
        "group_name": task_info["group_name"],
        "job_id": task_info["job_id"],
        "remote_task_dir": task_info["remote_task_dir"],
    }


def _full_group_selected(group_dir: Path, group_task_jsons: list[Path]) -> bool:
    selected = {path.resolve() for path in group_task_jsons}
    all_group_tasks = {path.resolve() for path in list_group_task_jsons(group_info_path(group_dir))}
    return selected == all_group_tasks


def _remote_experiment_root(config, experiment_dir: Path) -> str:
    return f"{config.remote_root.rstrip('/')}/{experiment_dir.name}"


def _remote_group_root(config, experiment_dir: Path, group_dir: Path) -> str:
    group_relative_dir = group_dir.resolve().relative_to(experiment_dir).as_posix()
    return f"{_remote_experiment_root(config, experiment_dir).rstrip('/')}/{group_relative_dir}"


def _group_submit_context(experiment_dir: Path, group_dir: Path, group_task_jsons: list[Path]) -> SubmitGroup:
    group_name = str(load_task_info(group_task_jsons[0])["group_name"])
    is_group_task = has_group_info(group_dir)
    return SubmitGroup(
        experiment_dir=experiment_dir,
        group_dir=group_dir,
        group_name=group_name,
        task_jsons=group_task_jsons,
        is_group_task=is_group_task,
        is_complete=is_group_task and _full_group_selected(group_dir, group_task_jsons),
    )


def _grouped_submit_contexts(task_jsons: list[Path]) -> list[SubmitGroup]:
    grouped_task_jsons: dict[tuple[Path, Path], list[Path]] = defaultdict(list)
    for task_json in task_jsons:
        experiment_dir = experiment_dir_for_task_json(task_json)
        group_dir = group_dir_for_task_json(task_json)
        grouped_task_jsons[(experiment_dir, group_dir)].append(task_json)
    return [
        _group_submit_context(experiment_dir, group_dir, group_task_jsons)
        for (experiment_dir, group_dir), group_task_jsons in grouped_task_jsons.items()
    ]


def _upload_group_archive(conn, *, remote_base_root: str, remote_group_root: str, group: SubmitGroup) -> None:
    prepare_group_submit_scripts(group.group_dir)
    archive_path = _archive_group(group.group_dir)
    remote_parent = str(Path(remote_group_root).parent)
    remote_archive = f"{remote_parent.rstrip('/')}/{_group_archive_name(group.group_name)}"
    try:
        conn.mkdir(remote_base_root)
        conn.mkdir(remote_parent)
        conn.run(f"rm -rf {shlex.quote(remote_group_root)}")
        conn.upload_files([archive_path], remote_parent)
        conn.run(f"mv {shlex.quote(f'{remote_parent.rstrip('/')}/{archive_path.name}')} {shlex.quote(remote_archive)}")
        conn.run(f"tar -xzf {shlex.quote(remote_archive)} -C {shlex.quote(remote_parent)}")
        conn.run(f"rm -f {shlex.quote(remote_archive)}")
    finally:
        archive_path.unlink(missing_ok=True)


def submit_tasks(task_jsons: list[Path]) -> list[dict[str, object]]:
    from hpc.jobs import HPCJobManager

    config = build_hpc_config()
    submitted: list[dict[str, object]] = []
    for group in _grouped_submit_contexts(task_jsons):
        remote_experiment_root = _remote_experiment_root(config, group.experiment_dir)
        remote_group_root = _remote_group_root(config, group.experiment_dir, group.group_dir)
        experiment_config = replace(config, remote_root=remote_experiment_root)
        group_config = (
            replace(config, remote_root=remote_group_root)
            if group.is_group_task
            else experiment_config
        )
        manager = HPCJobManager(group_config)

        if group.is_complete:
            with manager.connection as conn:
                _upload_group_archive(
                    conn,
                    remote_base_root=config.remote_root,
                    remote_group_root=remote_group_root,
                    group=group,
                )
                for task_json in group.task_jsons:
                    submitted.append(
                        _submission_record(
                            submit_preuploaded_task(task_json, manager),
                            task_json,
                        )
                    )
        else:
            with manager.connection:
                for task_json in group.task_jsons:
                    task_info = load_task_info(task_json)
                    submitted.append(
                        _submission_record(
                            submit_task(
                                task_json,
                                manager,
                                remote_task_name=relative_task_dir_for_remote(task_info, task_json),
                            ),
                            task_json,
                        )
                    )
    return submitted
