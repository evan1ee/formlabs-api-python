"""Per-user settings in a small JSON file (no FreeCAD dependency, so they are testable)."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from . import constants as C


def _config_dir() -> Path:
    base = os.environ.get("FL_FC_CONFIG_DIR")
    if base:
        return Path(base)
    root = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(root) / "Formlabs" / "FreeCAD"


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _config_dir() / "settings.json"

    def _read(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    _lock = threading.Lock()  # the GUI thread and the send worker both write settings

    def _set(self, key: str, value: str) -> None:
        with Settings._lock:
            data = {**self._read(), key: value}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)  # readers never see a half-written file

    def _get(self, key: str, default: str) -> str:
        v = self._read().get(key)
        return v if isinstance(v, str) and v.strip() else default

    @property
    def material(self) -> str:
        v = self._get("material", C.DEFAULT_MATERIAL)
        return v if C.material_code(v) == v else C.DEFAULT_MATERIAL

    @material.setter
    def material(self, code: str) -> None:
        if C.material_code(code) == code:
            self._set("material", code)

    @property
    def layer(self) -> str:
        v = self._get("layer", C.DEFAULT_LAYER)
        return v if v in C.LAYERS else C.DEFAULT_LAYER

    @layer.setter
    def layer(self, v: str) -> None:
        if v in C.LAYERS:
            self._set("layer", v)

    @property
    def printer(self) -> str:
        return self._get("printer", C.DEFAULT_PRINTER)

    @printer.setter
    def printer(self, v: str) -> None:
        if v.strip():
            self._set("printer", v.strip())

    @property
    def orientation(self) -> str:
        v = self._get("orientation", "view")
        return v if v in C.ORIENTATIONS else "view"

    @orientation.setter
    def orientation(self, v: str) -> None:
        if v in C.ORIENTATIONS:
            self._set("orientation", v)

    @property
    def export_format(self) -> str:
        return "STL" if self._get("export_format", "STEP") == "STL" else "STEP"

    @export_format.setter
    def export_format(self, v: str) -> None:
        self._set("export_format", "STL" if v == "STL" else "STEP")

    @property
    def lock_mode(self) -> str:
        v = self._get("lock_mode", C.LOCK_MODES[0])
        return v if v in C.LOCK_MODES else C.LOCK_MODES[0]

    @lock_mode.setter
    def lock_mode(self, v: str) -> None:
        if v in C.LOCK_MODES:
            self._set("lock_mode", v)

    @property
    def preform_exe(self) -> str:
        return self._get("preform_exe", os.environ.get("FL_PREFORM_EXE") or "connect")

    @property
    def install_dir(self) -> Path:
        """Folder with python/python.exe and the vendored service: this add-on's own runtime, else the SOLIDWORKS one."""
        v = os.environ.get("FL_INSTALL_DIR") or self._get("install_dir", "")
        if v:
            return Path(v)
        own = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Formlabs" / "Runtime"
        if (own / "python" / "python.exe").exists():
            return own  # installed by Install-FormlabsFreeCAD.ps1
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Formlabs for SOLIDWORKS"

    # --- project folder: one per day, named yyyy-mm-dd ---------------------------------------------------------
    @property
    def projects_root(self) -> Path:
        return Path(os.environ.get("FL_PROJECTS_ROOT") or Path.home() / "Documents" / "Formlabs Projects")

    def today_folder(self, now: datetime | None = None) -> Path:
        return self.projects_root / (now or datetime.now()).strftime("%Y-%m-%d")

    def new_project_folder(self, now: datetime | None = None) -> Path:
        day = (now or datetime.now()).strftime("%Y-%m-%d")
        p, n = self.projects_root / day, 2
        while p.exists():
            p = self.projects_root / f"{day}-{n}"
            n += 1
        return p

    @staticmethod
    def _is_today(folder: Path, now: datetime) -> bool:
        today = now.strftime("%Y-%m-%d")
        return folder.name == today or re.fullmatch(re.escape(today) + r"-\d+", folder.name) is not None

    def project_dir(self, now: datetime | None = None) -> Path:
        """The stored folder if it is today's project; an earlier day (or another format) rolls over to today."""
        now = now or datetime.now()
        stored = self._read().get("project_dir", "")
        if not stored or not self._is_today(Path(stored), now):
            stored = str(self.today_folder(now))
            self._set("project_dir", stored)
        return Path(stored)

    def set_project_dir(self, folder: Path) -> None:
        self._set("project_dir", str(folder))
