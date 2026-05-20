"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Wraps SSH and rsync operations so higher-level workflow code can run commands and move files on the HPC cluster.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import paramiko
from paramiko.ssh_exception import AuthenticationException, PasswordRequiredException, SSHException

from .config import HPCConfig


class HPCConnection:
    """Small wrapper around Paramiko.

    The goal is to keep network details here so higher-level code can stay
    focused on job workflow rather than SSH and rsync mechanics.
    """

    def __init__(self, config: HPCConfig):
        self.config = config
        self.ssh: paramiko.SSHClient | None = None

    def connect(self) -> "HPCConnection":
        """Open an SSH session for remote commands.

        We intentionally use ``SSHClient.connect`` instead of manually managing
        ``Transport`` so Paramiko can reuse common SSH behaviors like:
        - default private keys in ``~/.ssh``
        - ssh-agent forwarded identities
        - passwordless login once public keys are configured
        """

        self.close()

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.config.server,
            "port": self.config.port,
            "username": self.config.user,
            "timeout": 20,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if self.config.password:
            connect_kwargs["password"] = self.config.password
        if self.config.keyfile:
            connect_kwargs["pkey"] = self._load_private_key(self.config.keyfile)
            # If the caller explicitly supplied a key file, avoid searching
            # unrelated identities unless agent auth is still available.
            connect_kwargs["look_for_keys"] = False

        try:
            self.ssh.connect(**connect_kwargs)
        except AuthenticationException as exc:
            raise AuthenticationException(
                "Authentication failed. If passwordless login should work, "
                "first confirm `ssh user@host` succeeds from this same machine."
            ) from exc

        return self

    def _load_private_key(self, keyfile: str):
        """Try several Paramiko key parsers so the caller does not need to know the key type.

        Many users store SSH keys as ``id_ed25519`` or ECDSA keys instead of RSA.
        The old implementation always forced RSA parsing, which is why non-RSA
        keys raised confusing decode errors.
        """

        key_path = os.path.expanduser(keyfile)
        key_loaders = [paramiko.RSAKey]
        for key_name in ("Ed25519Key", "ECDSAKey", "DSSKey"):
            key_cls = getattr(paramiko, key_name, None)
            if key_cls is not None:
                key_loaders.append(key_cls)
        errors: list[str] = []

        for key_cls in key_loaders:
            try:
                return key_cls.from_private_key_file(key_path)
            except PasswordRequiredException as exc:
                raise SSHException(
                    f"Private key {key_path} is encrypted and needs a passphrase"
                ) from exc
            except (SSHException, ValueError, TypeError) as exc:
                errors.append(f"{key_cls.__name__}: {exc}")

        raise SSHException(
            "Could not load private key file with any supported key type.\n"
            f"keyfile: {key_path}\n"
            "attempts:\n"
            + "\n".join(errors)
        )

    def close(self) -> None:
        """Close all open network handles safely."""

        if self.ssh is not None:
            self.ssh.close()
            self.ssh = None

    def __enter__(self) -> "HPCConnection":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def run(self, command: str, check: bool = True) -> str:
        """Run a shell command on the cluster."""

        if self.ssh is None:
            raise RuntimeError("SSH connection is not open")

        if self.config.is_debug:
            print(f"[remote] {command}")

        stdin, stdout, stderr = self.ssh.exec_command(command)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        code = stdout.channel.recv_exit_status()
        stdin.close()
        stdout.close()
        stderr.close()

        if check and code != 0:
            raise RuntimeError(f"Remote command failed ({code}): {command}\n{err}")
        return out

    def mkdir(self, remote_dir: str) -> None:
        self.run(f"mkdir -p {shlex.quote(remote_dir)}")

    def upload_files(self, local_files: Iterable[str | Path], remote_dir: str) -> None:
        """Upload a flat list of local files into one remote folder with rsync."""

        self.mkdir(remote_dir)
        for path in local_files:
            local_path = Path(path).resolve()
            self._rsync_file(
                str(local_path),
                f"{self.config.user}@{self.config.server}:{remote_dir.rstrip('/')}/",
                append_verify=False,
            )

    def download_file(self, remote_file: str, local_file: str | Path) -> None:
        """Download one remote file with rsync over SSH, preserving partial progress."""

        local_file = Path(local_file)
        local_file.parent.mkdir(parents=True, exist_ok=True)
        self._rsync_file(
            f"{self.config.user}@{self.config.server}:{remote_file}",
            str(local_file),
            append_verify=True,
        )

    def _rsync_file(self, source: str, destination: str, *, append_verify: bool) -> None:
        if shutil.which("rsync") is None:
            raise FileNotFoundError("rsync executable not found")

        ssh_command = ["ssh", "-p", str(self.config.port)]
        if self.config.keyfile:
            ssh_command.extend(["-i", os.path.expanduser(self.config.keyfile)])

        command = [
            "rsync",
            "-avP",
            "-e",
            " ".join(shlex.quote(part) for part in ssh_command),
            source,
            destination,
        ]
        if append_verify:
            command.insert(2, "--append-verify")
        subprocess.run(command, check=True)
