"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Formats topology files and updates nonbonded force-field parameters without breaking column alignment.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NonbondOverride:
    atom_i: str
    atom_j: str
    sigma: float
    epsilon: float
    parameter_name: str
    scale_factor: float | None = None
    base_epsilon: float | None = None
    label: str | None = None


def _format_topology_row(section: str, parts: list[str]) -> str | None:
    if section == "defaults" and len(parts) >= 3:
        return f"{parts[0]:<8} {parts[1]:<10} {parts[2]:<10}\n"
    if section == "atomtypes" and len(parts) >= 6:
        return f"{parts[0]:<8} {parts[1]:>8} {parts[2]:>8} {parts[3]:<6} {parts[4]:>8} {parts[5]:>10}\n"
    if section == "nonbond_params" and len(parts) >= 5:
        return f"{parts[0]:<8} {parts[1]:<8} {parts[2]:>4} {float(parts[3]):>10.4f} {float(parts[4]):>12.4f}\n"
    if section == "bondtypes" and len(parts) >= 5:
        return f"{parts[0]:<8} {parts[1]:<8} {parts[2]:>4} {parts[3]:>10} {parts[4]:>14}\n"
    if section == "angletypes" and len(parts) >= 6:
        return f"{parts[0]:<8} {parts[1]:<8} {parts[2]:<8} {parts[3]:>4} {parts[4]:>10} {parts[5]:>14}\n"
    if section == "moleculetype" and len(parts) >= 2:
        return f"{parts[0]:<12} {parts[1]:>6}\n"
    if section == "atoms" and len(parts) >= 8:
        return (
            f"{parts[0]:>5} {parts[1]:<8} {parts[2]:>6} {parts[3]:<8} "
            f"{parts[4]:<8} {parts[5]:>6} {parts[6]:>8} {parts[7]:>8}\n"
        )
    if section == "bonds" and len(parts) >= 3:
        return f"{parts[0]:>5} {parts[1]:>5} {parts[2]:>6}\n"
    if section == "angles" and len(parts) >= 4:
        return f"{parts[0]:>5} {parts[1]:>5} {parts[2]:>5} {parts[3]:>6}\n"
    if section == "molecules" and len(parts) >= 2:
        return f"{parts[0]:<12} {parts[1]:>8}\n"
    return None


def _format_topology_comment(section: str) -> str | None:
    comments = {
        "defaults": "; nbfunc   comb-rule  gen-pairs\n",
        "atomtypes": "; name       mass   charge ptype     V(nm)  W(kJ/mol)\n",
        "nonbond_params": "; i        j        func      V(nm)    W(kJ/mol)\n",
        "bondtypes": "; i        j        func     b0(nm) kb(kJ/mol/nm2)\n",
        "angletypes": "; i        j        k        func   th0(deg)    cth(kJ/mol)\n",
        "moleculetype": "; Name         nrexcl\n",
        "atoms": "; nr type      resnr residu   atom       cgnr   charge     mass\n",
        "bonds": "; ai    aj  funct\n",
        "angles": "; ai    aj    ak  funct\n",
        "molecules": "; Compound        #mols\n",
    }
    return comments.get(section)


def format_topology_lines(lines: list[str]) -> list[str]:
    formatted: list[str] = []
    section = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]").strip()
            formatted.append(f"[ {section} ]\n")
            continue
        if not stripped:
            formatted.append("\n")
            continue
        if stripped.startswith(";"):
            formatted.append(_format_topology_comment(section) or line)
            continue

        parts = stripped.split()
        formatted.append(_format_topology_row(section, parts) or line)
    return formatted


def _format_nonbond_override_line(
    atom_i: str,
    atom_j: str,
    func: str | int,
    sigma: float,
    epsilon: float,
) -> str:
    return f"{atom_i:<8} {atom_j:<8} {str(func):>4} {sigma:>10.4f} {epsilon:>12.4f}\n"


def _nonbond_override_block(override: NonbondOverride) -> list[str]:
    return [
        "[ nonbond_params ]\n",
        _format_topology_comment("nonbond_params") or "",
        _format_nonbond_override_line(override.atom_i, override.atom_j, 1, override.sigma, override.epsilon),
        "\n",
    ]


def upsert_nonbond_override(lines: list[str], override: NonbondOverride) -> list[str]:
    updated: list[str] = []
    in_nonbond = False
    inserted = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if in_nonbond and not inserted:
                updated.extend(_nonbond_override_block(override))
                inserted = True
            if not inserted and stripped == "[ moleculetype ]":
                updated.extend(_nonbond_override_block(override))
                inserted = True
            in_nonbond = stripped == "[ nonbond_params ]"
            updated.append(line)
            continue
        if in_nonbond and stripped and not stripped.startswith(";"):
            parts = line.split()
            if len(parts) >= 5 and {(parts[0], parts[1]), (parts[1], parts[0])} & {
                (override.atom_i, override.atom_j),
                (override.atom_j, override.atom_i),
            }:
                updated.append(
                    _format_nonbond_override_line(parts[0], parts[1], parts[2], override.sigma, override.epsilon)
                )
                inserted = True
                continue
        updated.append(line)

    if not inserted:
        updated.extend(_nonbond_override_block(override))
    return format_topology_lines(updated)
