"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Downloads finished result tarballs and safely unpacks them into the local task directories.
"""

from __future__ import annotations

import shlex
import tarfile
from posixpath import dirname, normpath
from pathlib import Path, PurePosixPath

from workflow.common import build_hpc_config
from workflow.core.tasks import load_task_info, local_task_dir


def _safe_member_path(target_dir: Path, member_name: str) -> Path:
    target_path = (target_dir / member_name).resolve()
    if target_path != target_dir and target_dir not in target_path.parents:
        raise ValueError(f"Unsafe tar member path: {member_name}")
    return target_path


def _safe_link_path(member: tarfile.TarInfo, target_path: Path, target_dir: Path) -> None:
    link_name = PurePosixPath(member.linkname)
    if link_name.is_absolute():
        raise ValueError(f"Unsafe absolute tar link target: {member.name} -> {member.linkname}")

    link_path = (target_path.parent / link_name).resolve()

    if link_path != target_dir and target_dir not in link_path.parents:
        raise ValueError(f"Unsafe tar link target: {member.name} -> {member.linkname}")


def _validate_tar_member(member: tarfile.TarInfo, target_dir: Path) -> None:
    target_path = _safe_member_path(target_dir, member.name)
    if member.isdir() or member.isfile():
        return
    if member.issym() or member.islnk():
        _safe_link_path(member, target_path, target_dir)
        return
    raise ValueError(f"Unsupported tar member type: {member.name}")


def _safe_extract_tar(local_tar: Path, target_dir: Path) -> None:
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(local_tar) as archive:
        for member in archive.getmembers():
            _validate_tar_member(member, target_dir)
        try:
            archive.extractall(target_dir, filter="fully_trusted")
        except TypeError:
            archive.extractall(target_dir)


def _remote_path_is_under(path: str, root: str) -> bool:
    clean_path = normpath(path)
    clean_root = normpath(root)
    return clean_path != clean_root and clean_path.startswith(f"{clean_root}/")


def _clean_remote_task_dir(conn, remote_task_dir: str, remote_root: str) -> None:
    if not _remote_path_is_under(remote_task_dir, remote_root):
        raise ValueError(f"Refusing to clean remote path outside remote root: {remote_task_dir}")

    conn.run(f"rm -rf {shlex.quote(remote_task_dir)}")

    parent = dirname(normpath(remote_task_dir))
    clean_root = normpath(remote_root)
    while parent != clean_root and _remote_path_is_under(parent, clean_root):
        removed = conn.run(f"rmdir {shlex.quote(parent)} 2>/dev/null && echo REMOVED || echo KEEP")
        if removed != "REMOVED":
            break
        parent = dirname(parent)


def _partial_download_path(task_dir: Path, remote_tar: str) -> Path:
    return task_dir / f".{Path(remote_tar).name}.part"


def _seed_legacy_partial_download(task_dir: Path, remote_tar: str, partial_tar: Path) -> None:
    if partial_tar.exists():
        return

    legacy_pattern = f".{Path(remote_tar).stem}_*.tar"
    candidates = [path for path in task_dir.glob(legacy_pattern) if path.is_file()]
    if not candidates:
        return

    largest = max(candidates, key=lambda path: path.stat().st_size)
    largest.rename(partial_tar)


def _download_task(task_json: Path, conn, manager, *, clean_remote: bool) -> dict[str, object]:
    task_info = load_task_info(task_json)
    remote_task_dir = task_info.get("remote_task_dir")
    if not remote_task_dir:
        return {
            "task_json": str(task_json),
            "status": "not_submitted",
        }

    job_id = str(task_info["job_id"]) if task_info.get("job_id") else None
    remote_tar = manager._resolve_remote_results_tar(conn, str(remote_task_dir), job_id=job_id)
    task_dir = local_task_dir(task_info, task_json)
    task_dir.mkdir(parents=True, exist_ok=True)
    local_tar = _partial_download_path(task_dir, remote_tar)
    _seed_legacy_partial_download(task_dir, remote_tar, local_tar)

    transfer_method = "rsync"
    conn.download_file(remote_tar, local_tar)
    _safe_extract_tar(local_tar, task_dir)
    local_tar.unlink(missing_ok=True)

    if clean_remote:
        _clean_remote_task_dir(conn, str(remote_task_dir), manager.config.remote_root)

    return {
        "task_json": str(task_json),
        "task_name": task_info.get("task_name"),
        "group_name": task_info.get("group_name"),
        "status": "downloaded",
        "remote_results_tar": remote_tar,
        "remote_deleted": clean_remote,
        "local_task_dir": str(task_dir),
        "transfer_method": transfer_method,
    }


def download_tasks(task_jsons: list[Path], *, clean_remote: bool = True) -> list[dict[str, object]]:
    config = build_hpc_config()
    try:
        from hpc.connection import HPCConnection
        from hpc.jobs import HPCJobManager
    except ModuleNotFoundError as exc:
        if exc.name == "paramiko":
            raise ModuleNotFoundError(
                "Downloading remote HPC task results requires the `paramiko` package in this Python environment."
            ) from exc
        raise

    manager = HPCJobManager(config)
    records: list[dict[str, object]] = []
    with HPCConnection(config) as conn:
        for task_json in task_jsons:
            try:
                records.append(_download_task(task_json, conn, manager, clean_remote=clean_remote))
            except FileNotFoundError as exc:
                records.append(
                    {
                        "task_json": str(task_json),
                        "status": "not_ready",
                        "error": str(exc),
                    }
                )
    return records
