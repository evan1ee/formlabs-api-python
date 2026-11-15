"""Turns FreeCAD solids into export files placed the way the view shows them.

All FreeCAD imports are lazy so the rest of the package is importable (and testable) without FreeCAD.
Runs on the GUI thread: FreeCAD documents are not thread safe.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import orientation

CONTAINER_TYPES = ("App::Part", "App::DocumentObjectGroup", "Assembly::AssemblyObject")


@dataclass(frozen=True)
class ExportedBody:
    body_id: str
    body_name: str
    file: Path
    transform: list[list[float]]  # 4x4, mm, model -> print coordinates (baked into the export)
    doc_path: str
    config: str = "Default"


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "body"


def view_rotation(gui: Any | None = None) -> list[list[float]] | None:
    """Camera-to-world 3x3 of the active 3D view, or None when there is no view (headless)."""
    try:
        if gui is None:
            import FreeCADGui as gui  # type: ignore[no-redef]
        q = gui.ActiveDocument.ActiveView.getCameraOrientation().Q
        return orientation.quaternion_to_matrix(q[0], q[1], q[2], q[3])
    except Exception:  # noqa: BLE001 - no GUI/view: the caller falls back to the model axes
        return None


def _has_solid(obj: Any) -> bool:
    shape = getattr(obj, "Shape", None)
    try:
        return shape is not None and not shape.isNull() and len(shape.Solids) > 0
    except Exception:  # noqa: BLE001
        return False


def _children(obj: Any) -> list[Any]:
    if obj.TypeId in CONTAINER_TYPES:
        return list(getattr(obj, "Group", None) or obj.OutList)
    linked = getattr(obj, "LinkedObject", None)
    if obj.TypeId == "App::Link" and linked is not None and linked.TypeId in CONTAINER_TYPES:
        return list(getattr(linked, "Group", None) or linked.OutList)
    return []


def leaves(objs: list[Any], only_visible: bool) -> list[Any]:
    """Solid-bearing objects under `objs`, containers expanded, sources of other solids dropped."""
    found: list[Any] = []
    seen: set[str] = set()

    def walk(o: Any) -> None:
        key = o.Name
        if key in seen:
            return
        seen.add(key)
        if only_visible and not getattr(o, "Visibility", True):
            return
        kids = _children(o)
        if kids:
            for k in kids:
                walk(k)
        elif _has_solid(o):
            found.append(o)

    for o in objs:
        walk(o)
    # A feature's input solids (a Cut's base and tool) are part of the result, not extra parts.
    inputs = {i.Name for o in found if o.TypeId != "App::Link" for i in getattr(o, "OutList", []) if i is not o}
    return [o for o in found if o.Name not in inputs]


def collect(doc: Any, selection: list[Any]) -> list[Any]:
    """The selection if there is one (hidden objects count when picked), otherwise every visible solid."""
    if selection:
        picked = leaves(selection, only_visible=False)
        if picked:
            return picked
    top = [o for o in doc.Objects if not getattr(o, "InList", [])]
    objs = leaves(top, only_visible=True)
    if not objs:
        raise ValueError("There is no visible solid to send. Show a part or select one first.")
    return objs


def _matrix(fc: Any, m: list[list[float]]) -> Any:
    return fc.Matrix(*[m[i][j] for i in range(4) for j in range(4)])


def _global_placement(obj: Any) -> Any:
    """Own placement times every containing App::Part's placement (works for links too)."""
    pl = obj.Placement
    parent = obj.getParentGeoFeatureGroup()
    while parent is not None:
        pl = parent.Placement.multiply(pl)
        parent = parent.getParentGeoFeatureGroup()
    return pl


def _global_shape(obj: Any) -> tuple[Any, list[list[float]]]:
    """The object's shape in document (global) coordinates, plus its global placement as a 4x4."""
    base = obj.getLinkedObject(True) if obj.TypeId == "App::Link" else obj  # a link shows its target at its own placement
    shape = base.Shape.copy()
    pl = _global_placement(obj)
    shape.Placement = pl
    a = pl.Matrix.A  # 16 numbers, row-major
    return shape, [[float(a[4 * i + j]) for j in range(4)] for i in range(4)]


def _mul4(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


_STEP_COUNTER = re.compile(rb"(translator [0-9.]+ )[0-9]+")
_STEP_NAME = re.compile(rb"FILE_NAME\('[^']*',\s*'[^']*'")


def normalize_step(path: Path) -> None:
    """STEP stores the export time and file name in its header, so identical geometry would hash differently every
    time and the service could never see "unchanged". Replace both with fixed values."""
    data = _STEP_COUNTER.sub(rb"\g<1>1", path.read_bytes())  # "Open CASCADE STEP translator 7.8 3": a per-session counter
    path.write_bytes(_STEP_NAME.sub(b"FILE_NAME('part','1970-01-01T00:00:00'", data, count=1))


def export_objects(
    doc: Any,
    objs: list[Any],
    staging: Path,
    fmt: str,
    mode: str,
    camera_to_world: list[list[float]] | None,
    progress: Callable[[str], None] | None = None,
    fc: Any | None = None,
) -> list[ExportedBody]:
    if fc is None:
        import FreeCAD as fc  # type: ignore[no-redef]
    staging.mkdir(parents=True, exist_ok=True)
    rot4 = orientation.to_4x4(orientation.rotation_for(mode, camera_to_world))
    doc_path = getattr(doc, "FileName", "") or f"unsaved:{doc.Name}"
    out: list[ExportedBody] = []
    used: set[str] = set()
    for obj in objs:
        base = sanitize(obj.Name)
        bid = base if base not in used else f"{base}_{len(used)}"
        used.add(bid)
        shape, placement = _global_shape(obj)
        shape.transformShape(_matrix(fc, rot4), True)  # exact geometry copy, no re-tessellation
        file = staging / f"{bid}_{uuid.uuid4().hex[:8]}.{'stl' if fmt == 'STL' else 'step'}"
        if fmt == "STL":
            shape.exportStl(str(file))
        else:
            shape.exportStep(str(file))
            normalize_step(file)
        out.append(ExportedBody(bid, getattr(obj, "Label", obj.Name), file, _mul4(rot4, placement), doc_path))
        if progress:
            progress(obj.Label if hasattr(obj, "Label") else obj.Name)
    return out
