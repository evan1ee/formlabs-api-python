from __future__ import annotations

import hashlib
import itertools
from pathlib import Path
from typing import Any

import pytest

from formlabs_sw_service import PINNED_SERVER_VERSION
from formlabs_sw_service.core import ProjectService, SendRequest
from formlabs_sw_service.errors import ServiceError
from formlabs_sw_service.ports import CheckResult, Device, LayoutResult, RemoteModel


class FakePort:
    """In-memory PreForm. Scenes survive `restart()` only through saved .form files."""

    def __init__(self) -> None:
        self.version = PINNED_SERVER_VERSION
        self.valid_materials = {"FLGPGR05", "FLGPCL05"}
        self.scenes: dict[str, dict[str, dict[str, Any]]] = {}
        self.forms: dict[str, dict[str, dict[str, Any]]] = {}
        self.ids = itertools.count(1)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_layout = False
        self.checks: dict[str, CheckResult] = {}
        self.devices = [Device("Form4-A", "Form 4", True)]
        self.print_error: Exception | None = None
        self.import_error: Exception | None = None

    def _rec(self, _n: str, **kw: Any) -> None:
        self.calls.append((_n, kw))

    def restart(self) -> None:
        self.scenes = {}

    def server_version(self) -> str:
        return self.version

    def list_print_settings(self) -> dict[str, Any]:
        return {}

    def validate_print_setting(self, machine_type, material_code, layer, print_setting):
        return material_code in self.valid_materials, {"material": material_code}

    def create_scene(self, machine_type, material_code, layer, print_setting) -> str:
        sid = f"scene-{next(self.ids)}"
        self.scenes[sid] = {}
        return sid

    def open_form_file(self, path: str) -> str:
        sid = f"scene-{next(self.ids)}"
        self.scenes[sid] = {
            f"pm-{next(self.ids)}": dict(m) for m in self.forms[path].values()
        }
        return sid

    def scene_exists(self, scene_id: str) -> bool:
        return scene_id in self.scenes

    def save_form_file(self, scene_id: str, path: str, project_name: str = "") -> None:
        self.forms[path] = {k: dict(v) for k, v in self.scenes[scene_id].items()}
        Path(path).write_text("form")
        # the service renames tmp -> final, so alias the final path too
        self.forms[path.replace(".tmp.form", ".form")] = self.forms[path]

    def delete_scene(self, scene_id: str) -> None:
        self.scenes.pop(scene_id, None)

    def import_model(self, scene_id, file, *, name, lock, units, chordal_tolerance_um, angle_tolerance_deg):
        self._rec("import_model", name=name, lock=lock, units=units)
        if self.import_error:
            raise self.import_error
        pid = f"pm-{next(self.ids)}"
        h = hashlib.sha256(Path(file).read_bytes()).hexdigest()
        self.scenes[scene_id][pid] = {"name": name, "lock": lock, "hash": h, "supports": False}
        return pid

    def replace_model(self, scene_id, model_id, replacement_model_id) -> None:
        self._rec("replace_model", old=model_id, new=replacement_model_id)
        self.scenes[scene_id].pop(model_id)

    def delete_models(self, scene_id, model_ids) -> None:
        self._rec("delete_models", ids=model_ids)
        for m in model_ids:
            self.scenes[scene_id].pop(m)

    def list_models(self, scene_id) -> list[RemoteModel]:
        return [
            RemoteModel(pid, m["name"], m["lock"], {"hash": m["hash"]}) for pid, m in self.scenes[scene_id].items()
        ]

    def auto_support(self, scene_id, params, model_ids=None) -> None:
        self.support_params = dict(params)
        self.support_model_ids = model_ids
        self._rec("auto_support")

    def regenerate_supports(self, scene_id, model_ids) -> None:
        self._rec("regenerate_supports", ids=model_ids)

    def auto_layout(self, scene_id, *, lock_rotation, seed, model_spacing_mm) -> LayoutResult:
        self._rec("auto_layout", lock_rotation=lock_rotation, seed=seed)
        return LayoutResult(not self.fail_layout, [])

    def run_check(self, scene_id: str, check: str) -> CheckResult:
        return self.checks.get(check, CheckResult(check, True, {}, {}))

    def list_devices(self) -> list[Device]:
        return self.devices

    def print_scene(self, scene_id, printer, job_name) -> str | None:
        self._rec("print_scene", printer=printer, print_now=False)
        if self.print_error:
            raise self.print_error
        return "job-1"


@pytest.fixture
def port() -> FakePort:
    return FakePort()


@pytest.fixture
def svc(tmp_path: Path, port: FakePort) -> ProjectService:
    s = ProjectService(tmp_path / "proj", port, autosave=False)
    s.connect()
    return s


@pytest.fixture
def make_req(svc: ProjectService):
    def _make(content: bytes = b"solid-a", body="body1", material="FLGPGR05", layer=0.1, **kw) -> SendRequest:
        f = svc.folder / "exports" / f"{body}.step"
        f.write_bytes(content)
        return SendRequest(
            document="C:/cad/part.sldprt",
            configuration="Default",
            body_id=body,
            body_name=body,
            export_file=str(f),
            export_format="STEP",
            machine_type="FORM-4-0",
            material_code=material,
            layer_thickness_mm=layer,
            **kw,
        )

    return _make


__all__ = ["FakePort", "ServiceError"]
