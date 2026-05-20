"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Coordinates upload, submission, and remote status checks for one prepared HPC job.
"""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Iterable

from .config import HPCConfig, JobPaths
from .connection import HPCConnection


TIMING_FILE_NAME = "job_timing.json"


class HPCJobManager:
    """Orchestrate one HPC job from local inputs to remote execution."""

    def __init__(self, config: HPCConfig, connection: HPCConnection | None = None):
        self.config = config
        self.connection = connection or HPCConnection(config)

    def make_job_paths(
        self,
        local_workdir: str | Path,
        task_group_name: str | None = None,
        results_dir_name: str | None = None,
    ) -> JobPaths:
        """Build consistent names for the remote task folder."""

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        task_group_name = task_group_name or f"{self.config.task_group_prefix}_{timestamp}"
        results_dir_name = results_dir_name or "."
        return JobPaths(
            local_workdir=Path(local_workdir),
            remote_root=self.config.remote_root,
            task_group_name=task_group_name,
            results_dir_name=results_dir_name,
        )

    def submit(
        self,
        local_files: Iterable[str | Path],
        submit_script_name: str = "submit.lsf",
        task_group_name: str | None = None,
        results_dir_name: str | None = None,
        local_workdir: str | Path | None = None,
    ) -> dict[str, str]:
        """Submit a job and immediately return submission metadata.

        This method does not wait for the job to finish.
        """

        local_files = [Path(path) for path in local_files]
        if not local_files:
            raise ValueError("local_files must not be empty")

        if local_workdir is None:
            local_workdir = local_files[0].resolve().parent

        paths = self.make_job_paths(
            local_workdir=local_workdir,
            task_group_name=task_group_name,
            results_dir_name=results_dir_name,
        )

        if self.connection.ssh is not None:
            submit_output = self._submit_with_connection(
                self.connection,
                local_files=local_files,
                submit_script_name=submit_script_name,
                remote_task_dir=paths.remote_task_dir,
            )
        else:
            with self.connection as conn:
                submit_output = self._submit_with_connection(
                    conn,
                    local_files=local_files,
                    submit_script_name=submit_script_name,
                    remote_task_dir=paths.remote_task_dir,
                )
        job_id = self._parse_job_id(submit_output)

        return {
            "job_id": job_id,
            "submit_output": submit_output,
            "remote_task_dir": paths.remote_task_dir,
            "results_dir_name": paths.results_dir_name,
            "remote_timing_file": f"{paths.remote_task_dir.rstrip('/')}/{TIMING_FILE_NAME}",
        }

    def _submit_with_connection(
        self,
        connection: HPCConnection,
        *,
        local_files: list[Path],
        submit_script_name: str,
        remote_task_dir: str,
    ) -> str:
        connection.mkdir(self.config.remote_root)
        connection.mkdir(remote_task_dir)
        connection.upload_files(local_files, remote_task_dir)
        return self._run_bsub(connection, remote_task_dir, submit_script_name)

    def submit_preuploaded(
        self,
        *,
        remote_task_dir: str,
        results_dir_name: str,
        submit_script_name: str = "submit.lsf",
    ) -> dict[str, str]:
        """Submit a job whose working directory is already uploaded remotely."""

        if self.connection.ssh is not None:
            submit_output = self._run_bsub(self.connection, remote_task_dir, submit_script_name)
        else:
            with self.connection as conn:
                submit_output = self._run_bsub(conn, remote_task_dir, submit_script_name)
        job_id = self._parse_job_id(submit_output)

        return {
            "job_id": job_id,
            "submit_output": submit_output,
            "remote_task_dir": remote_task_dir,
            "results_dir_name": results_dir_name,
            "remote_timing_file": f"{remote_task_dir.rstrip('/')}/{TIMING_FILE_NAME}",
        }

    @staticmethod
    def _run_bsub(connection: HPCConnection, remote_task_dir: str, submit_script_name: str) -> str:
        return connection.run(
            f"cd {shlex.quote(remote_task_dir)} && "
            f"bsub < {shlex.quote(submit_script_name)}"
        )

    def check_job_status_with_connection(
        self,
        connection: HPCConnection,
        *,
        remote_task_dir: str,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Check remote job progress using an already-open connection."""

        stdout_file = f"{remote_task_dir.rstrip('/')}/{job_id}.out" if job_id else None
        stderr_file = f"{remote_task_dir.rstrip('/')}/{job_id}.err" if job_id else None

        stdout_exists = self._remote_file_exists(connection, stdout_file) if stdout_file else False
        stderr_exists = self._remote_file_exists(connection, stderr_file) if stderr_file else False

        result_tar = None
        try:
            result_tar = self._resolve_remote_results_tar(connection, remote_task_dir, job_id=job_id)
        except FileNotFoundError:
            result_tar = None

        is_submitted = stdout_exists or stderr_exists
        is_finished = result_tar is not None

        if is_finished:
            status = "finished"
        elif is_submitted:
            status = "submitted"
        else:
            status = "pending"

        return {
            "status": status,
            "remote_task_dir": remote_task_dir,
            "job_id": job_id,
            "stdout_file": stdout_file,
            "stdout_exists": stdout_exists,
            "stderr_file": stderr_file,
            "stderr_exists": stderr_exists,
            "result_tar": result_tar,
            "submitted": is_submitted,
            "finished": is_finished,
        }

    def _resolve_remote_results_tar(
        self,
        connection: HPCConnection,
        remote_task_dir: str,
        job_id: str | None = None,
    ) -> str:
        """Find the result tar file produced by the LSF job."""

        if job_id:
            remote_tar = f"{remote_task_dir.rstrip('/')}/{job_id}.results.tar"
            exists = connection.run(
                f"test -f {shlex.quote(remote_tar)} && echo READY || echo WAIT"
            )
            if exists == "READY":
                return remote_tar

        resolved = connection.run(
            f"cd {shlex.quote(remote_task_dir)} && "
            "ls -1t *.results.tar 2>/dev/null | head -n 1",
            check=True,
        )
        if not resolved:
            raise FileNotFoundError(f"No *.results.tar found in {remote_task_dir}")
        return f"{remote_task_dir.rstrip('/')}/{resolved}"

    @staticmethod
    def _remote_file_exists(connection: HPCConnection, remote_path: str | None) -> bool:
        """Return whether a remote file exists."""

        if not remote_path:
            return False
        state = connection.run(f"test -f {shlex.quote(remote_path)} && echo READY || echo WAIT")
        return state == "READY"

    @staticmethod
    def _parse_job_id(submit_output: str) -> str:
        """Extract the numeric LSF job id from ``bsub`` output."""

        tokens = submit_output.replace("<", " ").replace(">", " ").split()
        for token in tokens:
            if token.isdigit():
                return token
        raise ValueError(f"Could not parse job id from bsub output: {submit_output!r}")
