"""Build grouping key, source identity key and hashing (spec §4.2, §7.3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def normalize_layer(layer: float | str) -> str:
    """Layer thickness rounded to 0.001 mm; the literal 'ADAPTIVE' passes through."""
    if isinstance(layer, str) and layer.upper() == "ADAPTIVE":
        return "ADAPTIVE"
    return f"{round(float(layer), 3):.3f}"


def setting_fingerprint(print_setting: str, parameters: dict[str, Any] | None = None) -> str:
    """Identity of a print setting. Custom settings also hash their parameters."""
    if not parameters:
        return print_setting
    blob = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return f"{print_setting}#{hashlib.sha256(blob.encode()).hexdigest()[:12]}"


def build_key(machine_type: str, material_code: str, layer: float | str, fingerprint: str) -> str:
    return "|".join((machine_type, material_code, normalize_layer(layer), fingerprint))


def source_identity_key(document: str, configuration: str, body_id: str) -> str:
    """doc path + configuration + body persistent id (body name is the caller's fallback)."""
    doc = str(document).replace("\\", "/").lower()
    return "|".join((doc, configuration, body_id))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
