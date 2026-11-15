"""Supported materials, layers and lock modes. Codes never appear in the UI; names do."""
from __future__ import annotations

from typing import NamedTuple


class Material(NamedTuple):
    code: str
    name: str
    use: str


MATERIALS: tuple[Material, ...] = (
    Material("FLTO2002", "Tough 2000 V2", "Impact-resistant parts that flex: snaps and clips."),
    Material("FLGPGR05", "Grey V5", "Standard parts and fixtures; stiffer and more brittle, with better surface finish and accuracy."),
    Material("FLGPWH05", "White V5", "Like Grey V5, in white."),
    Material("FLGPCL05", "Clear V5", "Like Grey V5, transparent."),
    Material("FLRG1001", "Rigid 10K", "Very stiff glass-filled parts without snaps; resists high loads."),
)
DEFAULT_MATERIAL = MATERIALS[0].code
LAYERS: tuple[str, ...] = ("0.025", "0.05", "0.1")
DEFAULT_LAYER = "0.1"
DEFAULT_PRINTER = "Form 4B"
MACHINE_TYPE = "FORM-4-0"  # Form 4 and Form 4B share this machine type id
LOCK_MODES: tuple[str, ...] = (
    "LOCKED_ROTATION_FREE_TRANSLATION",
    "LOCKED_XY_ROTATION_FREE_TRANSLATION",
    "FREE",
)
ORIENTATIONS: tuple[str, ...] = ("view", "same", "yup")


def material_name(code: str) -> str:
    return next((m.name for m in MATERIALS if m.code == code), code)


def material_code(name_or_code: str) -> str | None:
    for m in MATERIALS:
        if name_or_code in (m.code, m.name):
            return m.code
    return None
