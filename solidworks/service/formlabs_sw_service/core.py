"""Project / Build / Model orchestration (spec §§4, 7, 8, 10, 12). Pure logic over a PreformPort."""

from __future__ import annotations

import os
import re
import functools
import shutil
import threading
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from typing import Callable

from attrs import asdict, evolve, frozen

from . import PINNED_SERVER_VERSION, errors
from .db import Database
from .errors import ServiceError
from .journal import Journal, now
from .keys import build_key, setting_fingerprint, sha256_file, source_identity_key
from .naming import build_name, project_name
from .models import (
    DEFAULT_LOCK,
    SELECTABLE_LOCKS,
    Build,
    BuildStatus,
    JobStatus,
    Lock,
    ModelStatus,
    OpState,
    PrintJob,
    PrintModel,
    PrintProject,
    ValidationStatus,
)
from .pathsafe import resolve_inside
from .ports import CheckResult, PreformPort
from .store import Store

DOWNLOAD_URL = "https://formlabs.com/support/Formlabs-API-downloads-and-release-notes/"
LAYOUT_SEED = 1  # fixed seed per build for reproducible layouts (spec §8.4, A12)
LAYOUT_SPACING_MM = 2.0

# (check, blocking) per spec §8.5; validate_print_setting is handled separately.
CHECKS: tuple[tuple[str, bool], ...] = (
    ("in_bounds", True),
    ("interferences", True),
    ("manifoldness", True),
    ("thin_features", False),
    ("minima", False),
    ("supportedness", False),
    ("cups", False),
)

RETIRED = "|old:"  # marks a build from an earlier session in its key


@frozen
class SendRequest:
    document: str
    configuration: str
    body_id: str
    body_name: str | None
    export_file: str
    export_format: str  # STEP | STL
    machine_type: str
    material_code: str
    layer_thickness_mm: float | str
    print_setting: str = ""  # empty: resolved from the catalog ("Default settings" entry)
    print_setting_params: dict[str, Any] | None = None
    lock_mode: Lock = DEFAULT_LOCK
    units: str = "MILLIMETERS"
    print_cs_transform: list[list[float]] | None = None
    export_settings: dict[str, Any] | None = None
    chordal_tolerance_um: float = 10.0
    angle_tolerance_deg: float = 5.0


def serialised(fn):
    """All PreForm-touching entry points run under one lock (timers and API workers share it)."""

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self.io_lock:
            return fn(self, *a, **kw)

    return wrapper


def _req_doc(req: SendRequest) -> dict[str, Any]:
    d = asdict(req)
    d["lock_mode"] = req.lock_mode.value
    return d


def _req_from_doc(d: dict[str, Any]) -> SendRequest:
    return SendRequest(**{**d, "lock_mode": Lock(d["lock_mode"])})


def _norm_machine(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


class ProjectService:
    def __init__(
        self,
        folder: str | Path,
        port: PreformPort,
        *,
        name: str | None = None,
        pinned_server_version: str = PINNED_SERVER_VERSION,
        autosave: bool = True,
        autosave_delay_s: float = 2.0,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.folder = Path(folder).resolve()
        for sub in ("builds", "exports", "logs"):
            (self.folder / sub).mkdir(parents=True, exist_ok=True)
        self.port = port
        self.pinned = pinned_server_version
        self.clock = clock
        self.autosave = autosave
        self.autosave_delay_s = autosave_delay_s
        self.io_lock = threading.RLock()
        self._timers: dict[str, threading.Timer] = {}
        self.db = Database(self.folder / "project.db")
        self.store = Store(self.db)
        self.journal = Journal(self.db)
        ts = now()
        existing = self.db.find("project")
        if existing:
            self.project = PrintProject(**existing[0])
        else:
            self.project = PrintProject(uuid.uuid4().hex, name or self._default_project_name(), str(self.folder), ts, ts)
            self.db.put("project", "project_id", self.project.project_id, self._pdoc())
        # Session-only ids: never persisted, never trusted after a server restart (rule 6).
        self._scene: dict[str, str] = {}
        self._pmodel: dict[str, str] = {}
        self._runs: dict[str, dict[str, Any]] = {}
        self.server_version: str | None = None
        self._session_started = False
        self._unnamed: set[str] = set()  # builds whose live scene PreForm still titles "Untitled Project N"

    def _default_project_name(self) -> str:
        """A date folder (see naming.new_project_folder) names its project; otherwise today's date."""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(-\d{2}-\d{2}-\d{2})?(-\d+)?", self.folder.name):
            return self.folder.name
        return project_name(self.clock())

    def _pdoc(self) -> dict[str, Any]:
        p = self.project
        return {k: getattr(p, k) for k in ("project_id", "name", "folder", "created_at", "updated_at", "status")}

    # ---------------------------------------------------------------- connect / restore
    @serialised
    def connect(self) -> dict[str, Any]:
        found = self.port.server_version()
        if found != self.pinned:
            raise ServiceError(
                errors.PREFORM_SERVER_VERSION_UNSUPPORTED,
                f"expected PreForm Server {self.pinned}, found {found}. Download the right build: {DOWNLOAD_URL}",
            )
        self.server_version = found
        if not self._session_started:  # first connect of this service run = a new working session
            self._session_started = True
            self._retire_builds()
        return {"server_version": found, "mismatches": self.restore_all()}

    def _retire_builds(self) -> None:
        """New session, new builds: earlier builds stay on disk but no longer receive new parts.

        Their key is changed so the next send of the same printer/material/layer opens a fresh build. Re-sending
        a part that already lives in a retired build moves it into the current build (existing move logic).
        """
        for b in self.store.builds():
            if RETIRED not in b.key:
                self.store.put_build(b.but(key=f"{b.key}{RETIRED}{b.build_id}"))

    def restore_all(self) -> list[dict[str, Any]]:
        self._scene.clear()
        self._pmodel.clear()
        report: list[dict[str, Any]] = []
        for b in self.store.builds():
            form = self.folder / b.form_file
            if form.exists() and RETIRED not in b.key:  # earlier sessions' builds open only when used
                report += self._open_and_remap(b)
        return report

    def _open_and_remap(self, b: Build) -> list[dict[str, Any]]:
        scene = self.port.open_form_file(str(self.folder / b.form_file))
        self._scene[b.build_id] = scene
        remote = {m.name: m for m in self.port.list_models(scene)}
        out: list[dict[str, Any]] = []
        for m in self.store.models_of(b.build_id):
            r = remote.get(m.model_id)  # models are named <model_id> on import
            if r is None:
                out.append({"build_id": b.build_id, "model_id": m.model_id, "problem": "MISSING_IN_SCENE"})
                continue
            if m.preform_fingerprint and m.preform_fingerprint.get("hash") not in (None, r.fingerprint.get("hash")):
                out.append({"build_id": b.build_id, "model_id": m.model_id, "problem": errors.MODEL_IDENTITY_MISMATCH})
                continue
            self._pmodel[m.model_id] = r.model_id
        return out

    # ---------------------------------------------------------------- build management
    def _ensure_scene(self, b: Build) -> str:
        if b.build_id in self._scene:
            return self._scene[b.build_id]
        if (self.folder / b.form_file).exists():
            self._open_and_remap(b)
        else:
            self._scene[b.build_id] = self.port.create_scene(
                b.machine_type, b.material_code, b.layer_thickness_mm, b.print_setting
            )
            self._unnamed.add(b.build_id)
        return self._scene[b.build_id]

    def _find_or_create_build(self, req: SendRequest) -> Build:
        fp = setting_fingerprint(req.print_setting, req.print_setting_params)
        key = build_key(req.machine_type, req.material_code, req.layer_thickness_mm, fp)
        b = self.store.build_by_key(key)
        if b:
            return b
        bid = uuid.uuid4().hex[:12]
        name = build_name(self.clock(), req.material_code, {x.name for x in self.store.builds()})
        b = Build(
            build_id=bid,
            name=name,
            project_id=self.project.project_id,
            key=key,
            machine_type=req.machine_type,
            material_code=req.material_code,
            layer_thickness_mm=req.layer_thickness_mm,
            print_setting=req.print_setting,
            print_setting_fingerprint=fp,
            form_file=f"builds/{name}.form",
        )
        self.store.put_build(b)
        return b

    def _touch(self, b: Build, status: BuildStatus | None = None) -> Build:
        """Any model change: dirty, validation cleared, acks cleared (spec §8.5, §8.6)."""
        self._runs.pop(b.build_id, None)
        nb = b.but(
            dirty=True,
            validation_status=ValidationStatus.NOT_RUN,
            acked_warnings=[],
            status=status or (BuildStatus.HAS_MODELS if self.store.models_of(b.build_id) else BuildStatus.EMPTY),
        )
        self.store.put_build(nb)
        return nb

    # ---------------------------------------------------------------- send (spec §7.2, §7.3)
    def _revalidate_scenes(self) -> None:
        """Make our picture of PreForm match PreForm before each send.

        * Every cached scene is gone: PreForm was closed and reopened (a new session). Saved builds reopen on next
          use; a build never saved loses its models from the store, so the next send imports them again.
        * Only some scenes are gone: the user deleted those builds in PreForm. They are retired and forgotten.
        * A scene is there but a model was deleted in it: forget the model so the next send imports it again.
        """
        cached = list(self._scene.items())
        gone = [(bid, sc) for bid, sc in cached if not self.port.scene_exists(sc)]
        restarted = bool(gone) and len(gone) == len(cached)
        if restarted:
            self._retire_builds()  # PreForm was restarted: that is a new session too
        for build_id, _scene in gone:
            del self._scene[build_id]
            b = self.store.get_build(build_id)
            if b is not None and not restarted:
                self.store.put_build(b.but(key=f"{b.key}{RETIRED}{b.build_id}"))  # deleted on purpose: never reuse
            for m in self.store.models_of(build_id):
                self._pmodel.pop(m.model_id, None)
                if b is not None and (not restarted or not (self.folder / b.form_file).exists()):
                    self.store.delete_model(m.model_id)
        for build_id, scene in list(self._scene.items()):
            present = {m.name for m in self.port.list_models(scene)}
            lost = [m for m in self.store.models_of(build_id) if m.model_id not in present]
            for m in lost:
                self._pmodel.pop(m.model_id, None)
                self.store.delete_model(m.model_id)
            b = self.store.get_build(build_id)
            if lost and b is not None:
                self._touch(b)

    @serialised
    def send_model(self, req: SendRequest) -> dict[str, Any]:
        return self._send_model(req)

    def _send_model(self, req: SendRequest) -> dict[str, Any]:
        self._revalidate_scenes()
        req = evolve(req, print_setting=self._resolve_print_setting(req))
        if req.lock_mode not in SELECTABLE_LOCKS:
            raise ServiceError(errors.BAD_REQUEST, f"lock {req.lock_mode.value} is not selectable (OD-01)")
        if req.export_format not in ("STEP", "STL"):
            raise ServiceError(errors.BAD_REQUEST, "export_format must be STEP or STL")
        export = resolve_inside(self.folder / "exports", req.export_file)
        if not export.is_file():
            raise ServiceError(errors.NOT_FOUND, f"export file missing: {export}")
        ok, detail = self.port.validate_print_setting(
            req.machine_type, req.material_code, req.layer_thickness_mm, req.print_setting
        )
        if not ok:
            raise ServiceError(errors.MATERIAL_NOT_SUPPORTED, f"print setting not in catalog: {detail}")

        file_hash = sha256_file(export)
        identity = source_identity_key(req.document, req.configuration, req.body_id)
        existing = self.store.model_by_identity(identity)
        target_key = build_key(
            req.machine_type,
            req.material_code,
            req.layer_thickness_mm,
            setting_fingerprint(req.print_setting, req.print_setting_params),
        )
        if existing is None:
            return self._import_new(req, identity, str(export), file_hash)
        old_build = self.store.get_build(existing.build_id)
        assert old_build is not None
        if old_build.key == target_key:
            if existing.source_file_hash == file_hash:
                return {"action": "unchanged", "model_id": existing.model_id, "build_id": old_build.build_id}
            return self._replace_in_place(req, existing, old_build, str(export), file_hash)
        return self._move_between_builds(req, existing, old_build, identity, str(export), file_hash)

    def _remote_import(self, b: Build, model_id: str, req: SendRequest, export: str, lock: Lock, op_kind: str):
        scene = self._ensure_scene(b)
        op = self.journal.begin(
            op_kind,
            b.build_id,
            model_id,
            {
                "file": export,
                "lock": lock.value,
                "scene": scene,
                "request": _req_doc(req),
                "file_hash": sha256_file(export),
            },
        )
        try:
            pid = self.port.import_model(
                scene,
                export,
                name=model_id,
                lock=lock.value,
                units=req.units,
                chordal_tolerance_um=req.chordal_tolerance_um,
                angle_tolerance_deg=req.angle_tolerance_deg,
            )
        except ServiceError as exc:
            self.journal.mark(op, OpState.FAILED, payload={**op.payload, "error": exc.to_dict()})
            raise
        except Exception:
            # Timeout/crash: the call may still have executed (spec §12.2).
            self.journal.mark(op, OpState.UNCERTAIN)
            raise
        remote = {m.model_id: m for m in self.port.list_models(scene)}
        if pid not in remote:
            self.journal.mark(op, OpState.UNCERTAIN)
            raise ServiceError(errors.MODEL_IDENTITY_MISMATCH, f"imported id {pid} not in scene", model_id=model_id)
        self.journal.mark(op, OpState.SUCCEEDED, preform_operation_id=pid)
        return pid, remote[pid].fingerprint

    def _new_model_record(self, req, model_id, build_id, identity, export, file_hash, fp) -> PrintModel:
        return PrintModel(
            model_id=model_id,
            build_id=build_id,
            source_document=req.document,
            source_configuration=req.configuration,
            source_body_name=req.body_name,
            source_identity_key=identity,
            source_file=export,
            source_file_hash=file_hash,
            export_format=req.export_format,
            export_settings=dict(req.export_settings or {}),
            import_chordal_tolerance_um=req.chordal_tolerance_um,
            import_angle_tolerance_deg=req.angle_tolerance_deg,
            print_cs_transform=req.print_cs_transform or [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)],
            preform_fingerprint=fp,
            lock_mode=req.lock_mode,
        )

    def _import_new(self, req, identity, export, file_hash) -> dict[str, Any]:
        b = self._find_or_create_build(req)
        model_id = uuid.uuid4().hex[:12]
        pid, fp = self._remote_import(b, model_id, req, export, req.lock_mode, "import")
        self.store.put_model(self._new_model_record(req, model_id, b.build_id, identity, export, file_hash, fp))
        self._pmodel[model_id] = pid
        b = self._touch(b)
        self._maybe_autosave(b)
        return {"action": "imported", "model_id": model_id, "build_id": b.build_id}

    def _replace_in_place(self, req, old: PrintModel, b: Build, export, file_hash) -> dict[str, Any]:
        # replace_model keeps the *replacement's* lock, so import with the existing lock mode.
        scene = self._ensure_scene(b)
        new_pid, fp = self._remote_import(b, old.model_id, req, export, old.lock_mode, "replace_import")
        op = self.journal.begin("replace", b.build_id, old.model_id, {"old": self._pmodel.get(old.model_id), "new": new_pid})
        try:
            self.port.replace_model(scene, self._pmodel[old.model_id], new_pid)
        except Exception:
            self.journal.mark(op, OpState.UNCERTAIN)
            raise
        self.journal.mark(op, OpState.SUCCEEDED)
        self._pmodel[old.model_id] = new_pid
        self.store.put_model(
            old.but(
                source_file=export,
                source_file_hash=file_hash,
                preform_fingerprint=fp,
                export_format=req.export_format,
                export_settings=dict(req.export_settings or {}),
                print_cs_transform=req.print_cs_transform or old.print_cs_transform,
                # Only supported models have supports to go stale; the server rejects regenerating none.
                status=ModelStatus.SUPPORTS_STALE if old.status != ModelStatus.IMPORTED else ModelStatus.IMPORTED,
            )
        )
        b = self._touch(b)
        self._maybe_autosave(b)
        return {"action": "replaced", "model_id": old.model_id, "build_id": b.build_id}

    def _move_between_builds(self, req, old: PrintModel, old_b: Build, identity, export, file_hash) -> dict[str, Any]:
        new_b = self._find_or_create_build(req)
        pid_old = self._pmodel.get(old.model_id)
        if pid_old:
            op = self.journal.begin("delete", old_b.build_id, old.model_id, {"pid": pid_old})
            self.port.delete_models(self._ensure_scene(old_b), [pid_old])
            self.journal.mark(op, OpState.SUCCEEDED)
        self.store.delete_model(old.model_id)
        self._pmodel.pop(old.model_id, None)
        old_b = self._touch(old_b)
        result = self._import_new(req, identity, export, file_hash)
        self._maybe_autosave(old_b)
        return {**result, "action": "moved", "from_build_id": old_b.build_id, "to_build_id": new_b.build_id}

    # ---------------------------------------------------------------- save (spec §7.4)
    def _maybe_autosave(self, b: Build) -> None:
        """Debounced: a burst of changes produces one save, delay_s after the last (spec §7.4)."""
        if not self.autosave:
            return
        if self.autosave_delay_s <= 0:
            self.save_build(b.build_id)
            return
        prev = self._timers.pop(b.build_id, None)
        if prev:
            prev.cancel()
        t = threading.Timer(self.autosave_delay_s, self._autosave_fire, args=(b.build_id,))
        t.daemon = True
        self._timers[b.build_id] = t
        t.start()

    def _autosave_fire(self, build_id: str) -> None:
        with self.io_lock:
            self._timers.pop(build_id, None)
            b = self.store.get_build(build_id)
            if b and b.dirty and build_id in self._scene:
                try:
                    self.save_build(build_id)
                except Exception:  # noqa: BLE001 - stays dirty; explicit save/shutdown retries
                    pass

    def cancel_autosave(self) -> None:
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()

    @serialised
    def save_build(self, build_id: str) -> Build:
        b = self._must_build(build_id)
        scene = self._ensure_scene(b)
        final = self.folder / b.form_file
        tmp = final.with_name(final.stem + ".tmp.form")  # keeps the .form extension for PreForm
        # No project_name: PreForm titles a build opened from a file by the file name (build name). With a stored
        # project name it falls back to "Untitled Project N" (observed on 3.66.0.1146).
        self.port.save_form_file(scene, str(tmp))
        if final.exists():
            shutil.copy2(final, final.with_suffix(".form.bak"))
        os.replace(tmp, final)
        nb = b.but(dirty=False, status=BuildStatus.SAVED if b.status in (BuildStatus.VALIDATED, BuildStatus.SAVED) else b.status)
        self.store.put_build(nb)
        if build_id in self._unnamed:
            self._adopt_saved_file(nb, scene)
        return nb

    def _adopt_saved_file(self, b: Build, live_scene: str) -> None:
        """PreForm titles a live scene "Untitled Project N" (the API cannot rename it) but titles a scene opened
        from a file by the file name. After the first save, continue in the reopened file so the build carries its
        name, then remove the untitled scene. On any failure the live scene simply stays in use."""
        try:
            self._open_and_remap(b)
        except Exception:  # noqa: BLE001
            self._scene[b.build_id] = live_scene
            return
        self._unnamed.discard(b.build_id)
        try:
            self.port.delete_scene(live_scene)
        except Exception:  # noqa: BLE001 - an extra untitled scene is harmless
            pass

    @serialised
    def save_project(self) -> dict[str, Any]:
        """Save every build with unsaved changes, then write project.json (a readable manifest)."""
        self.cancel_autosave()
        saved: list[str] = []
        for b in self.store.builds():
            if b.dirty and b.build_id in self._scene:
                self.save_build(b.build_id)
                saved.append(b.name or b.build_id)
        self.project = self.project.__class__(**{**self._pdoc(), "updated_at": now()})
        self.db.put("project", "project_id", self.project.project_id, self._pdoc())
        manifest = {
            **self._pdoc(),
            "builds": [
                {
                    "name": b.name,
                    "build_id": b.build_id,
                    "form_file": b.form_file,
                    "machine_type": b.machine_type,
                    "material_code": b.material_code,
                    "layer_thickness_mm": b.layer_thickness_mm,
                    "dirty": b.dirty,
                    "models": [m.source_body_name or m.model_id for m in self.store.models_of(b.build_id)],
                }
                for b in self.store.builds()
            ],
        }
        tmp = self.folder / "project.json.tmp"
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(tmp, self.folder / "project.json")
        return {"project": self.project.name, "saved_builds": saved, "manifest": str(self.folder / "project.json")}

    @serialised
    def save_all(self) -> None:
        for b in self.store.builds():
            if b.dirty and b.build_id in self._scene:
                self.save_build(b.build_id)

    def _must_build(self, build_id: str) -> Build:
        b = self.store.get_build(build_id)
        if b is None:
            raise ServiceError(errors.NOT_FOUND, f"no build {build_id}", build_id=build_id)
        return b

    # ---------------------------------------------------------------- supports / layout
    @serialised
    def generate_supports(self, build_id: str, params: dict[str, Any] | None = None) -> Build:
        b = self._must_build(build_id)
        scene = self._ensure_scene(b)
        models = self.store.models_of(build_id)
        stale = [m for m in models if m.status == ModelStatus.SUPPORTS_STALE]
        # Default support setting: no internal supports (enclosed cavities stay empty) unless a caller opts in.
        effective = {"internal_supports_enabled": False, **(params or b.support_params)}
        op = self.journal.begin("supports", build_id, None, {"params": effective})
        try:
            if any(m.status == ModelStatus.IMPORTED for m in models) or not stale:
                self.port.auto_support(scene, effective)
            else:
                # Replaced models (the part was moved or turned in SOLIDWORKS and sent again) get fresh supports for
                # the new geometry; "regenerate" would rebuild in place from the old support points.
                self.port.auto_support(scene, effective, [self._pmodel[m.model_id] for m in stale])
        except Exception:
            self.journal.mark(op, OpState.UNCERTAIN)
            raise
        self.journal.mark(op, OpState.SUCCEEDED)
        for m in models:
            self.store.put_model(m.but(status=ModelStatus.SUPPORTED))
        nb = self._touch(b, BuildStatus.SUPPORTED).but(support_params=effective)
        self.store.put_build(nb)
        self._maybe_autosave(nb)
        return nb

    @serialised
    def layout(self, build_id: str) -> Build:
        b = self._must_build(build_id)
        scene = self._ensure_scene(b)
        models = self.store.models_of(build_id)
        if b.dirty:  # save first so the pre-layout state can be restored; no save happens after
            b = self.save_build(build_id)
        lock_rot = any(m.lock_mode.rotation_locked for m in models)
        op = self.journal.begin("layout", build_id, None, {})
        res = self.port.auto_layout(scene, lock_rotation=lock_rot, seed=LAYOUT_SEED, model_spacing_mm=LAYOUT_SPACING_MM)
        if not res.ok:
            self.journal.mark(op, OpState.FAILED)
            self._reload_scene(b)
            raise ServiceError(
                errors.LAYOUT_WOULD_EJECT,
                "layout could not fit all models; nothing was changed or ejected",
                build_id=build_id,
            )
        self.journal.mark(op, OpState.SUCCEEDED)
        nb = self._touch(b, BuildStatus.LAID_OUT)
        self._maybe_autosave(nb)
        return nb

    def _reload_scene(self, b: Build) -> None:
        old = self._scene.pop(b.build_id, None)
        if old:
            self.port.delete_scene(old)
        if (self.folder / b.form_file).exists():
            self._open_and_remap(b)

    # ---------------------------------------------------------------- validation (spec §8.5)
    @serialised
    def validate(self, build_id: str) -> dict[str, Any]:
        b = self._must_build(build_id)
        scene = self._ensure_scene(b)
        blocking: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        ok, detail = self.port.validate_print_setting(
            b.machine_type, b.material_code, b.layer_thickness_mm, b.print_setting
        )
        if not ok:
            blocking.append({"check": "print_setting", "detail": detail})
        for check, is_blocking in CHECKS:
            r: CheckResult = self.port.run_check(scene, check)
            if not r.passed:
                (blocking if is_blocking else warnings).append({"check": check, "flagged": r.flagged})
        run_id = uuid.uuid4().hex
        self._runs[build_id] = {"run_id": run_id, "warnings": [w["check"] for w in warnings]}
        if blocking:
            status, bs = ValidationStatus.BLOCKED, BuildStatus.BLOCKED
        elif warnings:
            status, bs = ValidationStatus.NOT_RUN, b.status  # needs acknowledgement
        else:
            status, bs = ValidationStatus.PASSED, BuildStatus.VALIDATED
        self.store.put_build(b.but(validation_status=status, status=bs, acked_warnings=[]))
        return {"run_id": run_id, "blocking": blocking, "warnings": warnings, "status": status.value}

    def acknowledge_warnings(self, build_id: str, run_id: str) -> Build:
        b = self._must_build(build_id)
        run = self._runs.get(build_id)
        if not run or run["run_id"] != run_id:
            raise ServiceError(errors.BAD_REQUEST, "stale validation run; validate again", build_id=build_id)
        if b.validation_status == ValidationStatus.BLOCKED:
            raise ServiceError(errors.VALIDATION_BLOCKED, "blocking errors cannot be acknowledged", build_id=build_id)
        nb = b.but(
            validation_status=ValidationStatus.WARNINGS_ACKED,
            status=BuildStatus.VALIDATED,
            acked_warnings=list(run["warnings"]),
        )
        self.store.put_build(nb)
        return nb

    # ---------------------------------------------------------------- submission (spec §10)
    def list_printers(self) -> list[dict[str, Any]]:
        return [vars(d) if hasattr(d, "__dict__") else {"serial": d.serial} for d in self.port.list_devices()]

    @serialised
    def submit_build(self, build_id: str, printer: str, job_name: str, *, confirmed: bool) -> PrintJob:
        if not confirmed:
            raise ServiceError(errors.BAD_REQUEST, "explicit user confirmation required", build_id=build_id)
        b = self._must_build(build_id)
        if b.validation_status not in (ValidationStatus.PASSED, ValidationStatus.WARNINGS_ACKED):
            raise ServiceError(errors.VALIDATION_BLOCKED, f"validation is {b.validation_status.value}", build_id=build_id)
        dev = next((d for d in self.port.list_devices() if d.serial == printer), None)
        if dev is None or not self._printer_fits(dev.machine_type, b.machine_type):
            raise ServiceError(errors.PRINTER_MISMATCH, f"printer {printer} does not match {b.machine_type}", build_id=build_id)

        b = self.save_build(build_id)
        job_id = uuid.uuid4().hex[:12]
        snap_dir = self.folder / "builds" / "snapshots"
        snap_dir.mkdir(exist_ok=True)
        snap = snap_dir / f"{job_id}.form"
        shutil.copy2(self.folder / b.form_file, snap)
        job = PrintJob(job_id, build_id, printer, job_name, str(snap), print_now=False, status=JobStatus.PENDING)
        self.store.put_job(job)
        op = self.journal.begin("print", build_id, None, {"job_id": job_id, "printer": printer})
        job = job.but(status=JobStatus.IN_FLIGHT, submitted_at=now())
        self.store.put_job(job)
        try:
            printer_job = self.port.print_scene(self._scene[build_id], printer, job_name)
        except ServiceError as exc:
            self.journal.mark(op, OpState.FAILED)
            self.store.put_job(job.but(status=JobStatus.FAILED, error_code=exc.api_code, error_detail=str(exc)))
            raise
        except Exception as exc:
            # Never auto-retry a print: it may have been queued (spec §12.2).
            self.journal.mark(op, OpState.UNCERTAIN)
            self.store.put_job(job.but(status=JobStatus.UNKNOWN, error_detail=str(exc)))
            raise ServiceError(
                errors.OPERATION_STATE_UNCERTAIN, "check the printer queue before resubmitting", build_id=build_id
            ) from exc
        self.journal.mark(op, OpState.SUCCEEDED)
        job = job.but(status=JobStatus.SUCCEEDED, printer_job_id=printer_job)
        self.store.put_job(job)
        self.store.put_build(b.but(status=BuildStatus.SUBMITTED))
        return job

    def _catalog(self) -> dict[str, Any]:
        """Print-setting catalog, cached per server version (spec section 9)."""
        key = self.server_version or "unknown"
        cached = self.db.get("catalog_cache", "server_version", key)
        if cached is not None:
            return cached
        cat = self.port.list_print_settings()
        self.db.put("catalog_cache", "server_version", key, cat)
        return cat

    def _resolve_print_setting(self, req: SendRequest) -> str:
        """The print setting for a material+layer: the catalog's '(Default settings)' entry, never a guess."""
        if req.print_setting:
            return req.print_setting
        wanted = float(req.layer_thickness_mm) if not isinstance(req.layer_thickness_mm, str) else None
        matches: list[tuple[bool, str]] = []
        for t in self._catalog().get("printer_types", []):
            for m in t.get("materials", []):
                for ms in m.get("material_settings", []):
                    sc = ms.get("scene_settings", {})
                    if (
                        sc.get("machine_type") == req.machine_type
                        and sc.get("material_code") == req.material_code
                        and wanted is not None
                        and abs(float(sc.get("layer_thickness_mm", -1)) - wanted) < 1e-6
                    ):
                        matches.append(("Default settings" in ms.get("label", ""), sc["print_setting"]))
        if not matches:
            # Unknown to the catalog (or no catalog): let validate_print_setting give the authoritative answer.
            return "DEFAULT"
        return sorted(matches, key=lambda x: not x[0])[0][1]

    def _printer_fits(self, product_name: str, machine_type: str) -> bool:
        """True when PreForm's own catalog says this printer product prints this machine type."""
        try:
            types = self.port.list_print_settings().get("printer_types", [])
        except Exception:  # noqa: BLE001 - fall back to the name heuristic below
            types = []
        for t in types:
            if product_name in t.get("supported_product_names", []):
                return machine_type in t.get("supported_machine_type_ids", [])
        bm, dm = _norm_machine(machine_type), _norm_machine(product_name)
        return bm in (dm, dm + "0")  # catalog unavailable: Form 4 -> FORM-4-0

    # ---------------------------------------------------------------- recovery (spec §12.2)
    @serialised
    def recover(self) -> list[dict[str, Any]]:
        """Reconcile journal entries left open by a crash. Prints are never retried."""
        report: list[dict[str, Any]] = []
        for op in self.journal.open_ops() + [o for o in self.journal.all_ops() if o.state == OpState.UNCERTAIN]:
            entry = {"op_id": op.op_id, "kind": op.kind, "build_id": op.build_id}
            if op.kind == "print":
                for j in self.store.jobs_of(op.build_id):
                    if j.job_id == op.payload.get("job_id") and j.status in (JobStatus.IN_FLIGHT, JobStatus.PENDING):
                        self.store.put_job(j.but(status=JobStatus.UNKNOWN))
                self.journal.mark(op, OpState.UNCERTAIN)
                report.append({**entry, "outcome": "UNKNOWN_CHECK_PRINTER_QUEUE"})
            elif op.kind == "import" and op.model_id:
                report.append({**entry, "outcome": self._recover_import(op)})
            elif op.kind == "replace_import" and op.model_id:
                # Replace flows cannot be completed blindly: flag for the user.
                self.journal.mark(op, OpState.UNCERTAIN)
                report.append({**entry, "outcome": "FLAGGED_FOR_USER"})
            elif op.state in (OpState.INTENT, OpState.SENT):
                self.journal.mark(op, OpState.UNCERTAIN)
                report.append({**entry, "outcome": "FLAGGED_FOR_USER"})
        return report

    def _recover_import(self, op) -> str:
        """Match by model name; if absent retry the import ONCE (spec §12.2)."""
        b = self.store.get_build(op.build_id)
        if b is None or self.store.get_model(op.model_id):
            self.journal.mark(op, OpState.SUCCEEDED)
            return "ALREADY_RECORDED"
        req = _req_from_doc(op.payload["request"])
        scene = self._ensure_scene(b)
        found = next((m for m in self.port.list_models(scene) if m.name == op.model_id), None)
        outcome = "FOUND_IN_SCENE"
        if found is None:
            if op.payload.get("retried"):
                self.journal.mark(op, OpState.FAILED)
                return "RETRY_ALREADY_USED"
            self.journal.mark(op, OpState.INTENT, payload={**op.payload, "retried": True})
            pid = self.port.import_model(
                scene,
                op.payload["file"],
                name=op.model_id,
                lock=op.payload["lock"],
                units=req.units,
                chordal_tolerance_um=req.chordal_tolerance_um,
                angle_tolerance_deg=req.angle_tolerance_deg,
            )
            found = next(m for m in self.port.list_models(scene) if m.model_id == pid)
            outcome = "RETRIED_OK"
        identity = source_identity_key(req.document, req.configuration, req.body_id)
        self.store.put_model(
            self._new_model_record(req, op.model_id, b.build_id, identity, op.payload["file"], op.payload["file_hash"], found.fingerprint)
        )
        self._pmodel[op.model_id] = found.model_id
        self._touch(b)
        self.journal.mark(op, OpState.SUCCEEDED)
        return outcome
