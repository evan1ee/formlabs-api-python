"""Path validation: every path must stay inside the project (or install) folder (spec §13)."""

from __future__ import annotations

from pathlib import Path

from . import errors


def resolve_inside(root: str | Path, candidate: str | Path) -> Path:
    root_p = Path(root).resolve()
    cand = Path(candidate)
    full = (cand if cand.is_absolute() else root_p / cand).resolve()
    try:
        full.relative_to(root_p)
    except ValueError:
        raise errors.ServiceError(
            errors.PATH_OUTSIDE_PROJECT, f"{candidate} is outside {root_p}"
        ) from None
    return full
