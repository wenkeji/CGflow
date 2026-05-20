"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Creates local task folders, writes submit metadata, and builds ST/CMC task definitions from model inputs.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from hpc.gromacs import LsfScriptBuilder

from .topology import NonbondOverride, format_topology_lines, upsert_nonbond_override


GROUP_INFO_NAME = "task_group.json"
EXPERIMENT_INFO_NAME = "experiment.json"
TASK_INFO_NAME = "hpc_submit_info.json"
SUBMIT_SCRIPT_NAME = "submit.lsf"
BEAD_GROUPS = ("regular", "small", "tini")
NA_MODELS = ("Tini_Na", "regular_Na")
DEFAULT_NA_MODEL = "Tini_Na"
ST_NHOUR = 24
ST_QNAME = "background"
ST_NCORES = 64
CMC_NHOUR = 96
CMC_QNAME = "standard"
CMC_NCORES = 256


def _format_scan_value(value: float) -> str:
    return f"{value:0.3f}".rstrip("0").rstrip(".").replace(".", "p")


def bead_group_dir(repo_root: Path, bead_group: str, na_model: str = DEFAULT_NA_MODEL) -> Path:
    if bead_group not in BEAD_GROUPS:
        raise ValueError(f"Unsupported bead group: {bead_group}")
    if na_model not in NA_MODELS:
        raise ValueError(f"Unsupported Na model: {na_model}")
    group_dir = repo_root / "model" / na_model / bead_group
    if not group_dir.exists():
        raise FileNotFoundError(f"Bead task group input directory not found: {group_dir}")
    return group_dir


def group_info_path(group_dir: Path) -> Path:
    return group_dir / GROUP_INFO_NAME


def task_info_path(task_dir: Path) -> Path:
    return task_dir / TASK_INFO_NAME


def has_group_info(group_dir: Path) -> bool:
    return group_info_path(group_dir).exists()


def local_task_dir(task_info: dict[str, object], task_json: Path | None = None) -> Path:
    if task_info.get("local_workdir"):
        return Path(str(task_info["local_workdir"]))
    if task_json is not None:
        return task_json.parent
    raise KeyError("Task info does not include local_workdir")


def experiment_dir_for_task_json(task_json: Path) -> Path:
    for parent in [task_json.parent, *task_json.parents]:
        if (parent / EXPERIMENT_INFO_NAME).exists():
            return parent
    raise FileNotFoundError(f"No {EXPERIMENT_INFO_NAME} found above {task_json}")


def relative_task_dir_for_remote(task_info: dict[str, object], task_json: Path) -> str:
    experiment_dir = experiment_dir_for_task_json(task_json)
    task_dir = local_task_dir(task_info, task_json).resolve()
    try:
        return task_dir.relative_to(experiment_dir).as_posix()
    except ValueError as exc:
        raise ValueError(f"Task directory is outside experiment directory: {task_dir}") from exc


def group_dir_for_task_json(task_json: Path) -> Path:
    for parent in [task_json.parent, *task_json.parents]:
        group_json = group_info_path(parent)
        if group_json.exists():
            return parent
    return task_json.parent


def default_lsf_settings() -> dict[str, object]:
    builder = LsfScriptBuilder()
    return {
        "ncores": builder.ncores,
        "nhour": builder.nhour,
        "qname": builder.qname,
        "group": builder.group,
        "app": builder.app,
        "mpi": builder.mpi,
        "gmx_module": builder.gmx_module,
        "stdout_name": builder.stdout_name,
        "stderr_name": builder.stderr_name,
    }


def st_lsf_settings() -> dict[str, object]:
    return {**default_lsf_settings(), "ncores": ST_NCORES, "nhour": ST_NHOUR, "qname": ST_QNAME}


def cmc_lsf_settings() -> dict[str, object]:
    return {**default_lsf_settings(), "ncores": CMC_NCORES, "nhour": CMC_NHOUR, "qname": CMC_QNAME}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _save_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_task_info(task_json: Path) -> dict[str, object]:
    return _load_json(task_json)


def save_task_info(task_json: Path, task_info: dict[str, object]) -> Path:
    return _save_json(task_json, task_info)


def list_group_task_jsons(group_json: Path) -> list[Path]:
    group_info = _load_json(group_json)
    return [Path(task["task_json"]).expanduser().resolve() for task in group_info["tasks"]]


def list_experiment_task_jsons(experiment_json: Path) -> list[Path]:
    experiment_info = _load_json(experiment_json)
    resolved: list[Path] = []
    for group in experiment_info.get("groups", []):
        group_json = Path(str(group["group_json"])).expanduser().resolve()
        resolved.extend(list_group_task_jsons(group_json))
    for task in experiment_info.get("tasks", []):
        resolved.append(Path(str(task["task_json"])).expanduser().resolve())
    return resolved


def resolve_metadata_input_path(raw_input: str | Path) -> Path:
    path = Path(raw_input).expanduser().resolve()
    supported_names = {EXPERIMENT_INFO_NAME, GROUP_INFO_NAME, TASK_INFO_NAME}
    if not path.exists():
        raise FileNotFoundError(f"Input JSON not found: {path}")
    if not path.is_file() or path.name not in supported_names:
        raise ValueError(
            "Input must be a JSON metadata file named "
            f"{EXPERIMENT_INFO_NAME}, {GROUP_INFO_NAME}, or {TASK_INFO_NAME}: {path}"
        )
    return path


def resolve_task_json_inputs(inputs: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()

    for raw_input in inputs:
        path = resolve_metadata_input_path(raw_input)
        if path.name == EXPERIMENT_INFO_NAME:
            candidates = list_experiment_task_jsons(path)
        elif path.name == GROUP_INFO_NAME:
            candidates = list_group_task_jsons(path)
        elif path.name == TASK_INFO_NAME:
            candidates = [path]
        else:
            raise ValueError(f"Unsupported input JSON: {path}")

        for candidate in candidates:
            if candidate not in seen:
                resolved.append(candidate)
                seen.add(candidate)

    if not resolved:
        raise ValueError(f"At least one {EXPERIMENT_INFO_NAME}, {GROUP_INFO_NAME}, or {TASK_INFO_NAME} is required.")
    return resolved


def write_submit_script(task_info: dict[str, object]) -> Path:
    task_dir = local_task_dir(task_info)
    lsf_settings = dict(task_info.get("lsf", {}))
    builder = LsfScriptBuilder(
        lsfname=SUBMIT_SCRIPT_NAME,
        jobname=str(lsf_settings.pop("jobname", task_info["task_name"])),
        ncores=int(lsf_settings.pop("ncores", 64)),
        nhour=int(lsf_settings.pop("nhour", 24)),
        qname=str(lsf_settings.pop("qname", "standard")),
        group=str(lsf_settings.pop("group", "cadmol")),
        app=str(lsf_settings.pop("app", "gromacs")),
        mpi=str(lsf_settings.pop("mpi", "intelmpi")),
        gmx_module=str(lsf_settings.pop("gmx_module", "gromacs/2022.4")),
        stdout_name=str(lsf_settings.pop("stdout_name", "%J.out")),
        stderr_name=str(lsf_settings.pop("stderr_name", "%J.err")),
    )
    builder.set_commands(str(command) for command in task_info["commands"])
    return builder.dump(task_dir / SUBMIT_SCRIPT_NAME)


def task_local_files(task_info: dict[str, object]) -> list[Path]:
    task_dir = local_task_dir(task_info)
    files = [task_dir / str(name) for name in task_info["input_files"]]
    files.append(task_dir / SUBMIT_SCRIPT_NAME)
    return files


def prepare_group_submit_scripts(group_dir: Path) -> list[Path]:
    task_jsons = list_group_task_jsons(group_info_path(group_dir))
    prepared: list[Path] = []
    for task_json in task_jsons:
        task_info = load_task_info(task_json)
        prepared.append(write_submit_script(task_info))
    return prepared


def submit_task(
    task_json: Path,
    manager,
    *,
    remote_task_name: str | None = None,
) -> dict[str, object]:
    task_info = load_task_info(task_json)
    write_submit_script(task_info)

    result = manager.submit(
        local_files=task_local_files(task_info),
        submit_script_name=SUBMIT_SCRIPT_NAME,
        task_group_name=remote_task_name or str(task_info["task_name"]),
        results_dir_name=str(task_info["results_dir_name"]),
        local_workdir=Path(task_info["local_workdir"]),
    )
    task_info.update(result)
    save_task_info(task_json, task_info)
    return task_info


def submit_preuploaded_task(
    task_json: Path,
    manager,
    *,
    remote_task_name: str | None = None,
) -> dict[str, object]:
    task_info = load_task_info(task_json)
    task_remote_name = remote_task_name or str(task_info["task_name"])
    result = manager.submit_preuploaded(
        remote_task_dir=f"{manager.config.remote_root.rstrip('/')}/{task_remote_name}",
        results_dir_name=str(task_info["results_dir_name"]),
        submit_script_name=SUBMIT_SCRIPT_NAME,
    )
    task_info.update(result)
    save_task_info(task_json, task_info)
    return task_info


@dataclass
class CopySpec:
    source: str | Path
    target_name: str

    def copy_to(self, target_dir: Path) -> str:
        source_path = Path(self.source).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Input file not found: {source_path}")
        target_path = target_dir / self.target_name
        shutil.copy2(source_path, target_path)
        return self.target_name


@dataclass
class TaskSpec:
    task_name: str
    commands: list[str]
    input_files: list[str] | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class TaskGroupBuilder:
    group_dir: Path
    group_name: str
    copy_specs: list[CopySpec] = field(default_factory=list)
    tasks: list[TaskSpec] = field(default_factory=list)
    lsf_settings: dict[str, object] = field(default_factory=default_lsf_settings)
    group_metadata: dict[str, object] = field(default_factory=dict)

    def add_copy(self, source: str | Path, target_name: str | None = None) -> "TaskGroupBuilder":
        source_path = Path(source)
        self.copy_specs.append(CopySpec(source=source, target_name=target_name or source_path.name))
        return self

    def add_task(
        self,
        task_name: str,
        commands: Iterable[str],
        input_files: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> "TaskGroupBuilder":
        self.tasks.append(
            TaskSpec(
                task_name=task_name,
                commands=[str(command) for command in commands],
                input_files=input_files,
                metadata=dict(metadata or {}),
            )
        )
        return self

    def prepare(self) -> dict[str, object]:
        self.group_dir.mkdir(parents=True, exist_ok=True)
        task_records: list[dict[str, str]] = []

        for task in self.tasks:
            task_dir = self.group_dir / task.task_name
            task_dir.mkdir(parents=True, exist_ok=True)
            copied_files = [copy_spec.copy_to(task_dir) for copy_spec in self.copy_specs]
            task_info = {
                "group_name": self.group_name,
                "task_name": task.task_name,
                "local_workdir": str(task_dir),
                "input_files": task.input_files or copied_files,
                "commands": task.commands,
                "results_dir_name": ".",
                "lsf": dict(self.lsf_settings),
            }
            task_info.update(task.metadata)
            task_info_path_obj = _save_json(task_info_path(task_dir), task_info)
            task_records.append(
                {
                    "task_name": task.task_name,
                    "task_json": str(task_info_path_obj),
                    **task.metadata,
                }
            )

        group_info = {
            "group_name": self.group_name,
            "group_dir": str(self.group_dir),
            "lsf": dict(self.lsf_settings),
            "tasks": task_records,
        }
        group_info.update(self.group_metadata)
        _save_json(group_info_path(self.group_dir), group_info)
        return group_info


@dataclass
class SurfaceTensionTaskGroupBuilder:
    group_dir: Path
    group_name: str
    source_mdp: Path
    source_gro: Path
    source_top: Path
    n_surfs: list[int] = field(default_factory=list)
    scan_type: str = "structure"
    nonbond_overrides: list[NonbondOverride] = field(default_factory=list)
    lsf_settings: dict[str, object] = field(default_factory=default_lsf_settings)
    base_n_surf: int = 500
    bead_group: str = "regular"
    na_model: str = DEFAULT_NA_MODEL

    @staticmethod
    def _template_paths(
        repo_root: Path,
        bead_group: str = "regular",
        na_model: str = DEFAULT_NA_MODEL,
    ) -> tuple[Path, Path, Path]:
        source_dir = bead_group_dir(repo_root, bead_group, na_model) / "st"
        return source_dir / "MD.mdp", source_dir / "init.gro", source_dir / "sys.top"

    @staticmethod
    def _read_base_n_surf(source_top: Path) -> int:
        lines = source_top.read_text().splitlines()
        in_molecules = False
        for line in lines:
            stripped = line.strip()
            if stripped == "[ molecules ]":
                in_molecules = True
                continue
            if not in_molecules or not stripped or stripped.startswith(";"):
                continue
            parts = stripped.split()
            if len(parts) >= 2 and parts[0] == "Qd":
                return int(parts[1])
        raise ValueError(f"Could not infer base n_surf from {source_top}")

    @classmethod
    def structure_scan_from_repo(
        cls,
        *,
        repo_root: Path,
        group_dir: Path,
        group_name: str,
        bead_group: str = "regular",
        na_model: str = DEFAULT_NA_MODEL,
        n_surfs: list[int] | None = None,
    ) -> "SurfaceTensionTaskGroupBuilder":
        source_mdp, source_gro, source_top = cls._template_paths(repo_root, bead_group, na_model)
        return cls(
            group_dir=group_dir,
            group_name=group_name,
            source_mdp=source_mdp,
            source_gro=source_gro,
            source_top=source_top,
            n_surfs=list(n_surfs or []),
            scan_type="structure",
            base_n_surf=cls._read_base_n_surf(source_top),
            bead_group=bead_group,
            na_model=na_model,
            lsf_settings=st_lsf_settings(),
        )

    @classmethod
    def parameter_scan_from_repo(
        cls,
        *,
        repo_root: Path,
        group_dir: Path,
        group_name: str,
        bead_group: str = "regular",
        na_model: str = DEFAULT_NA_MODEL,
        n_surfs: list[int] | None = None,
        nonbond_overrides: list[NonbondOverride] | None = None,
    ) -> "SurfaceTensionTaskGroupBuilder":
        source_mdp, source_gro, source_top = cls._template_paths(repo_root, bead_group, na_model)
        return cls(
            group_dir=group_dir,
            group_name=group_name,
            source_mdp=source_mdp,
            source_gro=source_gro,
            source_top=source_top,
            n_surfs=list(n_surfs or []),
            scan_type="forcefield+structure",
            nonbond_overrides=list(nonbond_overrides or []),
            base_n_surf=cls._read_base_n_surf(source_top),
            bead_group=bead_group,
            na_model=na_model,
            lsf_settings=st_lsf_settings(),
        )

    @staticmethod
    def _surface_tension_commands() -> list[str]:
        return [
            "gmx_mpi grompp -f em.mdp -c init.gro -p sys.top -o em.tpr || exit 1",
            'gmx_mpi mdrun -s em.tpr -deffnm em -ntomp "${OMP_NUM_THREADS:-1}" || exit 1',
            "gmx_mpi grompp -f MD.mdp -c em.gro -p sys.top -o eq.tpr || exit 1",
            'gmx_mpi mdrun -s eq.tpr -deffnm eq -ntomp "${OMP_NUM_THREADS:-1}" || exit 1',
        ]

    def _source_em_mdp(self) -> Path:
        local_em_mdp = self.source_mdp.parent / "em.mdp"
        if local_em_mdp.exists():
            return local_em_mdp
        sibling_cmc_em_mdp = self.source_mdp.parent.parent / "cmc" / "em.mdp"
        if sibling_cmc_em_mdp.exists():
            return sibling_cmc_em_mdp
        raise FileNotFoundError(f"Could not find an EM mdp file next to {self.source_mdp}")

    @staticmethod
    def _structure_task_name(n_surf: int) -> str:
        return f"surf_{n_surf:04d}"

    def _parameter_task_name(self, parameter: float | NonbondOverride) -> str:
        if isinstance(parameter, NonbondOverride):
            if parameter.label:
                return parameter.label
            if parameter.scale_factor is not None:
                return f"{self._parameter_prefix()}_x{_format_scan_value(parameter.scale_factor)}"
            return f"{self._parameter_prefix()}_{_format_scan_value(parameter.epsilon)}"
        return f"{self._parameter_prefix()}_{_format_scan_value(parameter)}"

    def _parameter_prefix(self) -> str:
        if self.scan_type.startswith("forcefield"):
            parameters = {override.parameter_name for override in self.nonbond_overrides}
            if len(parameters) == 1:
                return next(iter(parameters)).lower().replace("-", "")
            return "ff"
        raise ValueError(f"Scan type does not define a force-field parameter axis: {self.scan_type}")

    def _scan_axes(self) -> list[str]:
        axes: list[str] = []
        if self.scan_type == "structure":
            axes.append("structure")
        if self.scan_type.startswith("forcefield"):
            axes.append("forcefield")
        if "+structure" in self.scan_type:
            axes.append("structure")
        return axes

    def _gen_gro(self, n_surf: int, output: Path) -> None:
        p4_lines: list[str] = []
        qd_lines: list[str] = []
        surf_lines: list[str] = []

        with self.source_gro.open() as handle:
            handle.readline()
            natoms = int(handle.readline().strip())
            for _ in range(natoms):
                line = handle.readline()
                resname = line[5:10].strip()
                if resname == "P4":
                    p4_lines.append(line)
                elif resname == "Qd":
                    qd_lines.append(line)
                elif resname == "C13Qa":
                    surf_lines.append(line)
            box = handle.readline()

        if self.base_n_surf <= 0 or len(surf_lines) % self.base_n_surf != 0:
            raise ValueError(f"Could not infer C13Qa bead count from {self.source_gro}")
        surf_beads_per_molecule = len(surf_lines) // self.base_n_surf
        if n_surf > len(qd_lines):
            raise ValueError(f"Requested {n_surf} Qd beads but only {len(qd_lines)} exist in {self.source_gro}")
        requested_surf_lines = n_surf * surf_beads_per_molecule
        if requested_surf_lines > len(surf_lines):
            available = len(surf_lines) // surf_beads_per_molecule
            raise ValueError(f"Requested {n_surf} C13Qa molecules but only {available} exist in {self.source_gro}")

        with output.open("w") as handle:
            handle.write("surface_tension_series\n")
            handle.write(f"{len(p4_lines) + n_surf + requested_surf_lines}\n")
            handle.writelines(p4_lines)
            handle.writelines(qd_lines[:n_surf])
            handle.writelines(surf_lines[:requested_surf_lines])
            handle.write(box)

    def _gen_top(self, n_surf: int, output: Path) -> None:
        output.write_text("".join(self._rewrite_topology(n_surf)))

    def _rewrite_topology(self, n_surf: int, parameter: float | NonbondOverride | None = None) -> list[str]:
        lines = self.source_top.read_text().splitlines(keepends=True)
        lines = self._rewrite_molecule_counts(lines, n_surf)
        if self.scan_type.startswith("forcefield"):
            if not isinstance(parameter, NonbondOverride):
                raise ValueError("forcefield scan requires a nonbond override")
            lines = upsert_nonbond_override(lines, parameter)
        return format_topology_lines(lines)

    def _rewrite_molecule_counts(self, lines: list[str], n_surf: int) -> list[str]:
        updated: list[str] = []
        in_molecules = False
        replaced = False
        for line in lines:
            stripped = line.strip()
            if stripped == "[ molecules ]":
                in_molecules = True
                updated.append(line)
                continue
            if in_molecules and stripped.startswith(";"):
                updated.append(line)
                continue
            if in_molecules and not replaced and stripped.startswith("P4"):
                updated.append("P4             7500\n")
                updated.append(f"Qd             {n_surf}\n")
                updated.append(f"C13Qa          {n_surf}\n")
                replaced = True
                continue
            if in_molecules and replaced and (stripped.startswith("Qd") or stripped.startswith("C13Qa")):
                continue
            updated.append(line)
        if not replaced:
            raise ValueError(f"Could not find the [ molecules ] counts block to update in {self.source_top}")
        return updated

    def _task_name(self, n_surf: int, parameter: float | NonbondOverride | None = None) -> str:
        if self.scan_type == "structure":
            return self._structure_task_name(n_surf)
        if parameter is None:
            raise ValueError("Coupled scans require an epsilon value")
        parameter_name = self._parameter_task_name(parameter)
        structure_name = self._structure_task_name(n_surf)
        return f"{parameter_name}/{structure_name}"

    def _metadata(self, *, n_surf: int, parameter: float | NonbondOverride | None = None) -> dict[str, object]:
        metadata: dict[str, object] = {
            "scan_type": self.scan_type,
            "bead_group": self.bead_group,
            "na_model": self.na_model,
            "scan_axes": self._scan_axes(),
            "n_surf": n_surf,
        }
        if isinstance(parameter, NonbondOverride):
            metadata.update(
                {
                    "epsilon": parameter.epsilon,
                    "sigma": parameter.sigma,
                    "parameter_name": parameter.parameter_name,
                    "parameter_task_name": self._parameter_task_name(parameter),
                }
            )
            if parameter.scale_factor is not None:
                metadata["scale_factor"] = parameter.scale_factor
            if parameter.base_epsilon is not None:
                metadata["base_epsilon"] = parameter.base_epsilon
        elif parameter is not None:
            raise ValueError(f"Unsupported surface-tension scan parameter: {parameter!r}")
        return metadata

    def _iter_task_cases(self) -> Iterable[tuple[int, float | NonbondOverride | None]]:
        if self.scan_type == "structure":
            for n_surf in self.n_surfs:
                yield n_surf, None
            return
        if self.scan_type.startswith("forcefield"):
            for override in self.nonbond_overrides:
                for n_surf in self.n_surfs:
                    yield n_surf, override
            return

        raise ValueError(f"Unsupported surface-tension scan type: {self.scan_type}")

    def _write_task_inputs(
        self,
        task_dir: Path,
        *,
        n_surf: int,
        parameter: float | NonbondOverride | None = None,
    ) -> None:
        if self.scan_type == "structure":
            self._gen_gro(n_surf, task_dir / "init.gro")
            self._gen_top(n_surf, task_dir / "sys.top")
            return

        self._gen_gro(n_surf, task_dir / "init.gro")
        (task_dir / "sys.top").write_text("".join(self._rewrite_topology(n_surf, parameter)))

    def prepare(self) -> dict[str, object]:
        builder = TaskGroupBuilder(
            group_dir=self.group_dir,
            group_name=self.group_name,
            lsf_settings=dict(self.lsf_settings),
            group_metadata={
                "scan_type": self.scan_type,
                "bead_group": self.bead_group,
                "na_model": self.na_model,
                "n_surfs": list(self.n_surfs),
                "nonbond_overrides": [override.__dict__ for override in self.nonbond_overrides],
                "scan_axes": self._scan_axes(),
                "base_n_surf": self.base_n_surf,
            },
        )
        builder.add_copy(self._source_em_mdp(), "em.mdp")
        builder.add_copy(self.source_mdp, "MD.mdp")

        for n_surf, parameter in self._iter_task_cases():
            builder.add_task(
                task_name=self._task_name(n_surf, parameter),
                commands=self._surface_tension_commands(),
                input_files=["em.mdp", "MD.mdp", "init.gro", "sys.top"],
                metadata=self._metadata(n_surf=n_surf, parameter=parameter),
            )
        group_info = builder.prepare()

        for n_surf, parameter in self._iter_task_cases():
            task_dir = self.group_dir / self._task_name(n_surf, parameter)
            self._write_task_inputs(task_dir, n_surf=n_surf, parameter=parameter)
        return group_info


@dataclass
class CmcTaskGroupBuilder:
    group_dir: Path
    group_name: str
    source_em_mdp: Path
    source_eq_mdp: Path
    source_gro: Path
    source_top: Path
    lsf_settings: dict[str, object] = field(default_factory=default_lsf_settings)
    bead_group: str = "regular"
    na_model: str = DEFAULT_NA_MODEL
    nonbond_override: NonbondOverride | None = None

    @classmethod
    def from_repo(
        cls,
        *,
        repo_root: Path,
        group_dir: Path,
        group_name: str,
        bead_group: str = "regular",
        na_model: str = DEFAULT_NA_MODEL,
    ) -> "CmcTaskGroupBuilder":
        source_dir = bead_group_dir(repo_root, bead_group, na_model) / "cmc"
        return cls(
            group_dir=group_dir,
            group_name=group_name,
            source_em_mdp=source_dir / "em.mdp",
            source_eq_mdp=source_dir / "eq.mdp",
            source_gro=source_dir / "init.gro",
            source_top=source_dir / "sys.top",
            lsf_settings=cmc_lsf_settings(),
            bead_group=bead_group,
            na_model=na_model,
        )

    @classmethod
    def parameter_from_repo(
        cls,
        *,
        repo_root: Path,
        group_dir: Path,
        group_name: str,
        bead_group: str = "regular",
        na_model: str = DEFAULT_NA_MODEL,
        nonbond_override: NonbondOverride,
    ) -> "CmcTaskGroupBuilder":
        source_dir = bead_group_dir(repo_root, bead_group, na_model) / "cmc"
        return cls(
            group_dir=group_dir,
            group_name=group_name,
            source_em_mdp=source_dir / "em.mdp",
            source_eq_mdp=source_dir / "eq.mdp",
            source_gro=source_dir / "init.gro",
            source_top=source_dir / "sys.top",
            lsf_settings=cmc_lsf_settings(),
            bead_group=bead_group,
            na_model=na_model,
            nonbond_override=nonbond_override,
        )

    @staticmethod
    def _cmc_commands() -> list[str]:
        return [
            "gmx_mpi grompp -f em.mdp -c init.gro -p sys.top -o em.tpr || exit 1",
            'gmx_mpi mdrun -s em.tpr -deffnm em -ntomp "${OMP_NUM_THREADS:-1}" || exit 1',
            "gmx_mpi grompp -f eq.mdp -c em.gro -p sys.top -o eq.tpr || exit 1",
            'gmx_mpi mdrun -s eq.tpr -deffnm eq -ntomp "${OMP_NUM_THREADS:-1}" || exit 1',
        ]

    def _write_simple_submit_script(self, task_dir: Path) -> Path:
        lsf_settings = dict(self.lsf_settings)
        command_block = "\n".join(self._cmc_commands())
        script = f"""#!/bin/bash -x
#BSUB -J {self.group_name}
#BSUB -n {int(lsf_settings.pop("ncores", CMC_NCORES))}
#BSUB -q {str(lsf_settings.pop("qname", CMC_QNAME))}
#BSUB -G {str(lsf_settings.pop("group", "cadmol"))}
#BSUB -W {int(lsf_settings.pop("nhour", CMC_NHOUR))}:00
#BSUB -app {str(lsf_settings.pop("app", "gromacs"))}
#BSUB -a {str(lsf_settings.pop("mpi", "intelmpi"))}
#BSUB -o {str(lsf_settings.pop("stdout_name", "%J.out"))}
#BSUB -e {str(lsf_settings.pop("stderr_name", "%J.err"))}

sleep 15
source /etc/profile.d/modules.sh
module load {str(lsf_settings.pop("gmx_module", "gromacs/2022.4"))}

OLD_DIR=$PWD
export OMP_NUM_THREADS=$LSB_DJOB_NUMPROC

find . -maxdepth 1 -type f -exec cp {{}} "$WORK_DIR"/ \\;
cd "$WORK_DIR" || exit 1

{command_block}

echo "Collecting results..."
tar cvf "$OLD_DIR/$LSB_JOBID.results.tar" *
exit
"""
        target = task_dir / SUBMIT_SCRIPT_NAME
        target.write_text(script)
        return target

    def prepare(self) -> dict[str, object]:
        task_dir = self.group_dir
        task_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(self.source_em_mdp, task_dir / "em.mdp")
        shutil.copy2(self.source_eq_mdp, task_dir / "eq.mdp")
        shutil.copy2(self.source_gro, task_dir / "init.gro")
        if self.nonbond_override is None:
            lines = self.source_top.read_text().splitlines(keepends=True)
            (task_dir / "sys.top").write_text("".join(format_topology_lines(lines)))
        else:
            lines = self.source_top.read_text().splitlines(keepends=True)
            (task_dir / "sys.top").write_text("".join(upsert_nonbond_override(lines, self.nonbond_override)))
        submit_script = self._write_simple_submit_script(task_dir)
        task_info = {
            "group_name": self.group_name,
            "task_name": self.group_name,
            "local_workdir": str(task_dir),
            "input_files": ["em.mdp", "eq.mdp", "init.gro", "sys.top"],
            "commands": self._cmc_commands(),
            "results_dir_name": ".",
            "lsf": dict(self.lsf_settings),
            "task_type": "cmc",
            "bead_group": self.bead_group,
            "na_model": self.na_model,
            "simulation_stages": ["em", "eq"],
        }
        if self.nonbond_override is not None:
            task_info.update(
                {
                    "scan_type": "forcefield",
                    "scan_axes": ["forcefield"],
                    "parameter_name": self.nonbond_override.parameter_name,
                    "parameter_task_name": self.nonbond_override.label or self.group_name,
                    "sigma": self.nonbond_override.sigma,
                    "epsilon": self.nonbond_override.epsilon,
                }
            )
            if self.nonbond_override.scale_factor is not None:
                task_info["scale_factor"] = self.nonbond_override.scale_factor
            if self.nonbond_override.base_epsilon is not None:
                task_info["base_epsilon"] = self.nonbond_override.base_epsilon
        task_info_path_obj = _save_json(task_info_path(task_dir), task_info)

        result = {
            "group_name": self.group_name,
            "group_dir": str(self.group_dir),
            "task_dir": str(task_dir),
            "task_type": "cmc",
            "bead_group": self.bead_group,
            "na_model": self.na_model,
            "simulation_stages": ["em", "eq"],
            "input_files": ["em.mdp", "eq.mdp", "init.gro", "sys.top"],
            "task_json": str(task_info_path_obj),
            "submit_script": str(submit_script),
            "lsf": dict(self.lsf_settings),
        }
        if self.nonbond_override is not None:
            result.update(
                {
                    "scan_type": "forcefield",
                    "scan_axes": ["forcefield"],
                    "parameter_name": self.nonbond_override.parameter_name,
                    "parameter_task_name": self.nonbond_override.label or self.group_name,
                    "sigma": self.nonbond_override.sigma,
                    "epsilon": self.nonbond_override.epsilon,
                }
            )
            if self.nonbond_override.scale_factor is not None:
                result["scale_factor"] = self.nonbond_override.scale_factor
            if self.nonbond_override.base_epsilon is not None:
                result["base_epsilon"] = self.nonbond_override.base_epsilon
        return result
