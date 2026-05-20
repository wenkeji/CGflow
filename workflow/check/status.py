"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Collects remote scheduler, log, and result-tar status for submitted tasks.
"""

from __future__ import annotations

import shlex
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from workflow.common import build_hpc_config
from workflow.core.tasks import (
    group_dir_for_task_json,
    load_task_info,
    local_task_dir,
)


@dataclass
class TaskContext:
    task_json: Path
    task_info: dict[str, object]
    task_name: str
    group_name: str
    local_task_dir: Path
    remote_task_dir: str | None
    job_id: str | None


def _task_name(task_info: dict[str, object], task_json: Path) -> str:
    if task_info.get("task_name"):
        return str(task_info["task_name"])
    if task_info.get("remote_task_dir"):
        return Path(str(task_info["remote_task_dir"])).name
    return task_json.stem


def _group_name(task_info: dict[str, object], task_json: Path) -> str:
    if task_info.get("group_name"):
        return str(task_info["group_name"])
    remote_task_dir = task_info.get("remote_task_dir")
    if remote_task_dir:
        return Path(str(remote_task_dir)).parent.name
    return task_json.parent.name


def _local_task_dir(task_info: dict[str, object], task_json: Path) -> Path:
    return local_task_dir(task_info, task_json)


def _task_context(task_json: Path) -> TaskContext:
    task_info = load_task_info(task_json)
    return TaskContext(
        task_json=task_json,
        task_info=task_info,
        task_name=_task_name(task_info, task_json),
        group_name=_group_name(task_info, task_json),
        local_task_dir=_local_task_dir(task_info, task_json),
        remote_task_dir=str(task_info["remote_task_dir"]) if task_info.get("remote_task_dir") else None,
        job_id=str(task_info["job_id"]) if task_info.get("job_id") else None,
    )


def _group_contexts(task_jsons: list[Path]) -> dict[Path, list[TaskContext]]:
    grouped: dict[Path, list[TaskContext]] = defaultdict(list)
    for task_json in task_jsons:
        context = _task_context(task_json)
        grouped[group_dir_for_task_json(context.task_json)].append(context)
    return grouped


def _prepared_status(context: TaskContext) -> dict[str, object]:
    return _with_context_fields(
        context,
        {
            "status": "prepared",
            "submitted": False,
            "finished": False,
        },
    )


def _with_context_fields(context: TaskContext, status: dict[str, object]) -> dict[str, object]:
    status["task_json"] = str(context.task_json)
    status["task_name"] = context.task_name
    status["group_name"] = context.group_name
    return status


def _remote_status(manager, context: TaskContext, conn) -> dict[str, object]:
    if context.remote_task_dir is None:
        return _prepared_status(context)

    status = manager.check_job_status_with_connection(
        conn,
        remote_task_dir=context.remote_task_dir,
        job_id=context.job_id,
    )
    return _with_context_fields(context, status)


def _parse_lsf_job_states(raw_output: str) -> dict[str, str]:
    job_states: dict[str, str] = {}
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Job <") and "> is not found" in stripped:
            job_id = stripped.split("<", 1)[1].split(">", 1)[0]
            job_states[job_id] = "NOT_FOUND"
            continue
        if stripped.startswith("JOBID"):
            continue
        parts = stripped.split()
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        job_states[parts[0]] = parts[2]
    return job_states


def _batch_remote_statuses(conn, contexts: list[TaskContext]) -> dict[Path, dict[str, object]]:
    remote_contexts = [context for context in contexts if context.remote_task_dir is not None]
    if not remote_contexts:
        return {}
    remote_dirs_by_task_json = {
        context.task_json: str(context.remote_task_dir)
        for context in remote_contexts
    }
    requested_job_ids = [context.job_id for context in remote_contexts if context.job_id]
    lsf_states: dict[str, str] = {}
    if requested_job_ids:
        bjobs_cmd = "bjobs -w -a " + " ".join(shlex.quote(str(job_id)) for job_id in requested_job_ids)
        lsf_states = _parse_lsf_job_states(conn.run(f"{bjobs_cmd} 2>&1 || true"))

    script_lines = ["set -e"]
    for index, context in enumerate(remote_contexts):
        remote_task_dir = str(context.remote_task_dir)
        job_id = context.job_id or ""
        script_lines.extend(
            [
                f"remote_task_dir_{index}={shlex.quote(remote_task_dir)}",
                f"job_id_{index}={shlex.quote(job_id)}",
                f'result_tar_{index}=""',
                f'stdout_exists_{index}=0',
                f'stderr_exists_{index}=0',
                f"if [ -n \"$job_id_{index}\" ]; then",
                f"  [ -f \"$remote_task_dir_{index}/$job_id_{index}.out\" ] && stdout_exists_{index}=1 || true",
                f"  [ -f \"$remote_task_dir_{index}/$job_id_{index}.err\" ] && stderr_exists_{index}=1 || true",
                f"  if [ -f \"$remote_task_dir_{index}/$job_id_{index}.results.tar\" ]; then",
                f"    result_tar_{index}=\"$remote_task_dir_{index}/$job_id_{index}.results.tar\"",
                "  fi",
                "fi",
                f"if [ -z \"$result_tar_{index}\" ]; then",
                f"  resolved_{index}=$(cd \"$remote_task_dir_{index}\" && ls -1t *.results.tar 2>/dev/null | head -n 1 || true)",
                f"  if [ -n \"$resolved_{index}\" ]; then",
                f"    result_tar_{index}=\"$remote_task_dir_{index}/$resolved_{index}\"",
                "  fi",
                "fi",
                f"if [ -n \"$result_tar_{index}\" ]; then",
                f"  status_{index}=finished",
                f"  submitted_{index}=1",
                f"  finished_{index}=1",
                f"elif [ \"$stdout_exists_{index}\" -eq 1 ] || [ \"$stderr_exists_{index}\" -eq 1 ]; then",
                f"  status_{index}=submitted",
                f"  submitted_{index}=1",
                f"  finished_{index}=0",
                "else",
                f"  status_{index}=pending",
                f"  submitted_{index}=0",
                f"  finished_{index}=0",
                "fi",
                (
                    "printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "
                    + shlex.quote(str(context.task_json))
                    + f" \"$status_{index}\""
                    + f" \"$stdout_exists_{index}\""
                    + f" \"$stderr_exists_{index}\""
                    + f" \"$result_tar_{index}\""
                    + f" \"$submitted_{index}\""
                    + f" \"$finished_{index}\""
                    + " "
                    + shlex.quote(job_id)
                ),
            ]
        )

    raw_output = conn.run("\n".join(script_lines))
    statuses_by_task_json: dict[Path, dict[str, object]] = {}
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        (
            task_json,
            status,
            stdout_exists,
            stderr_exists,
            result_tar,
            submitted,
            finished,
            job_id,
        ) = line.split("\t")
        task_json_path = Path(task_json)
        remote_task_dir = remote_dirs_by_task_json[task_json_path]
        statuses_by_task_json[task_json_path] = {
            "status": status,
            "scheduler_status": lsf_states.get(job_id) if job_id else None,
            "remote_task_dir": remote_task_dir,
            "job_id": job_id or None,
            "stdout_file": f"{remote_task_dir.rstrip('/')}/{job_id}.out" if job_id else None,
            "stdout_exists": stdout_exists == "1",
            "stderr_file": f"{remote_task_dir.rstrip('/')}/{job_id}.err" if job_id else None,
            "stderr_exists": stderr_exists == "1",
            "result_tar": result_tar or None,
            "submitted": submitted == "1",
            "finished": finished == "1",
        }
        scheduler_status = statuses_by_task_json[task_json_path]["scheduler_status"]
        if statuses_by_task_json[task_json_path]["finished"]:
            statuses_by_task_json[task_json_path]["status"] = "finished"
        elif scheduler_status is not None:
            statuses_by_task_json[task_json_path]["status"] = str(scheduler_status).lower()
    return statuses_by_task_json


def collect_task_statuses(task_jsons: list[Path]) -> list[dict[str, object]]:
    config = build_hpc_config()
    from hpc.connection import HPCConnection
    from hpc.jobs import HPCJobManager

    manager = HPCJobManager(config)
    statuses: list[dict[str, object]] = []
    grouped_contexts = _group_contexts(task_jsons)
    with HPCConnection(config) as conn:
        for contexts in grouped_contexts.values():
            batch_statuses = _batch_remote_statuses(conn, contexts)
            for context in contexts:
                if context.remote_task_dir is None:
                    statuses.append(_prepared_status(context))
                    continue
                status = batch_statuses.get(context.task_json)
                if status is None:
                    status = _remote_status(manager, context, conn=conn)
                statuses.append(_with_context_fields(context, status))
    return statuses


def _task_path(status: dict[str, object]) -> str:
    task_json = Path(str(status["task_json"]))
    return str(local_task_dir(load_task_info(task_json), task_json))


def summarize_statuses(statuses: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "path": _task_path(status),
            "task_name": status.get("task_name"),
            "job_id": status.get("job_id"),
            "remote_status": status.get("status"),
            "scheduler_status": status.get("scheduler_status"),
            "submitted": bool(status.get("submitted", False)),
            "completed": bool(status.get("finished", False)),
            "result_tar": status.get("result_tar"),
        }
        for status in statuses
    ]
