"""Naming rules: project = yyyy-mm-dd, build = yyyy-mm-dd-hh-mm-ss-<material name>."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

STAMP = "%Y-%m-%d-%H-%M-%S"  # yyyy-mm-dd-hh-mm-ss (builds)
DAY = "%Y-%m-%d"  # yyyy-mm-dd (projects)


def project_name(when: datetime) -> str:
    return when.strftime(DAY)


#: The supported materials by name; people see names, never material codes.
MATERIAL_NAMES = {
    "FLTO2002": "Tough-2000-V2",
    "FLGPGR05": "Grey-V5",
    "FLGPWH05": "White-V5",
    "FLGPCL05": "Clear-V5",
    "FLRG1001": "Rigid-10K",
}


def material_name(material_code: str) -> str:
    return MATERIAL_NAMES.get(material_code, material_code)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "NA"


def build_name(when: datetime, material_code: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """`<date>-<time>-<material name>`; a `-2`, `-3`... suffix keeps names unique within a project."""
    base = f"{when.strftime(STAMP)}-{_safe(material_name(material_code))}"
    name, n = base, 2
    while name.lower() in {t.lower() for t in taken}:
        name, n = f"{base}-{n}", n + 1
    return name


def new_project_folder(root: str | Path, when: datetime) -> Path:
    """`<root>/<date>-<time>`; never reuses an existing folder."""
    base = project_name(when)
    p, n = Path(root) / base, 2
    while p.exists():
        p, n = Path(root) / f"{base}-{n}", n + 1
    return p
