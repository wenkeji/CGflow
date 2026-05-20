"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Parses force-field override settings such as scale factors, direct epsilons, atoms, and bead-specific mappings.
"""

from __future__ import annotations

from pathlib import Path

from workflow.core.tasks import NonbondOverride


def parse_float(raw: object) -> float:
    if isinstance(raw, int | float):
        return float(raw)
    text = str(raw).strip()
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / float(denominator)
    return float(text)


def map_atom_for_bead(atom: str, bead_group: str) -> str:
    if atom == "C1" and bead_group == "small":
        return "SC1"
    if atom == "C1" and bead_group == "tini":
        return "TC1"
    return atom


def parameter_atoms(parameter: str, bead_group: str, raw_atoms: object | None = None) -> tuple[str, str]:
    if raw_atoms is not None:
        atoms = list(raw_atoms)
        if len(atoms) != 2:
            raise ValueError("forcefield.atoms must contain exactly two atom names")
        return str(atoms[0]), str(atoms[1])
    parts = parameter.split("-", 1)
    if len(parts) != 2:
        raise ValueError("forcefield.parameter must look like C1-C1")
    return map_atom_for_bead(parts[0], bead_group), map_atom_for_bead(parts[1], bead_group)


def read_nonbond_param(source_top: Path, atom_i: str, atom_j: str) -> tuple[float, float]:
    in_nonbond = False
    for line in source_top.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("["):
            in_nonbond = stripped == "[ nonbond_params ]"
            continue
        if not in_nonbond:
            continue
        parts = stripped.split()
        if len(parts) >= 5 and {(parts[0], parts[1]), (parts[1], parts[0])} & {
            (atom_i, atom_j),
            (atom_j, atom_i),
        }:
            return float(parts[3]), float(parts[4])
    raise ValueError(f"Could not find nonbond parameter {atom_i}-{atom_j} in {source_top}")


def format_factor_label(value: float) -> str:
    return f"x{value:0.3f}".rstrip("0").rstrip(".").replace(".", "p")


def forcefield_configs(raw_forcefield: object) -> list[dict[str, object]]:
    if isinstance(raw_forcefield, list):
        return [dict(item) for item in raw_forcefield]
    return [dict(raw_forcefield or {})]


def forcefield_overrides(
    *,
    source_top: Path,
    forcefield_config: dict[str, object],
    bead_group: str,
) -> list[NonbondOverride]:
    parameter = str(forcefield_config.get("parameter", "C1-C1"))
    atoms_by_bead = forcefield_config.get("atoms_by_bead")
    raw_atoms = atoms_by_bead.get(bead_group) if isinstance(atoms_by_bead, dict) else None
    if raw_atoms is None:
        raw_atoms = forcefield_config.get("atoms")
    atom_i, atom_j = parameter_atoms(parameter, bead_group, raw_atoms)
    source_sigma, source_epsilon = read_nonbond_param(source_top, atom_i, atom_j)
    sigma = parse_float(forcefield_config.get("sigma", source_sigma))
    base_epsilon = parse_float(forcefield_config.get("base_epsilon", source_epsilon))

    if "epsilons" in forcefield_config:
        epsilons = [parse_float(value) for value in list(forcefield_config["epsilons"])]
        factors: list[float | None] = [None for _ in epsilons]
    else:
        factors = [parse_float(value) for value in list(forcefield_config.get("scale_factors", [1.0]))]
        epsilons = [base_epsilon * factor for factor in factors]

    overrides: list[NonbondOverride] = []
    prefix = parameter.lower().replace("-", "")
    for epsilon, factor in zip(epsilons, factors):
        label_suffix = format_factor_label(factor) if factor is not None else f"eps{format_factor_label(epsilon)[1:]}"
        overrides.append(
            NonbondOverride(
                atom_i=atom_i,
                atom_j=atom_j,
                sigma=sigma,
                epsilon=epsilon,
                parameter_name=parameter,
                scale_factor=factor,
                base_epsilon=base_epsilon,
                label=f"{prefix}_{label_suffix}",
            )
        )
    return overrides


def all_forcefield_overrides(
    *,
    source_top: Path,
    raw_forcefield: object,
    bead_group: str,
) -> list[NonbondOverride]:
    overrides: list[NonbondOverride] = []
    for forcefield_config in forcefield_configs(raw_forcefield):
        overrides.extend(
            forcefield_overrides(
                source_top=source_top,
                forcefield_config=forcefield_config,
                bead_group=bead_group,
            )
        )
    return overrides
